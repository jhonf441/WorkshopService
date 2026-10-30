"""
Jobs poller -- it runs in a background thread inside dsf/main.py
(like status_light.py / consumption_poller.py), looking at the object model
of the single DSF subscription (machine_state.get_status: in memory, without
asking for anything) every POLL_INTERVAL_S seconds to detect:

  - Start/end of a job (print/laser/CNC), via state.status
    ("processing"/"simulating"/"paused"/"resuming" = active job) and
    job.file.fileName. The duration is given by RRF directly (job.duration,
    in seconds) -- it is not measured by hand with wall-clock, so that it matches
    what DWC already shows.
  - Changes of global.selectedMode (FFF/Laser/CNC).

Each transition is recorded in the activity history (db.py / table
actividad) via activity.log_event(). The energy consumption of the job
is computed by subtracting global.consumptionKWh between the start and the end
(the same pattern already used by consumption_period.py: subtract an
accumulated value, do not integrate power by hand).

(2026-10-12: before, it asked for GET /machine/status over HTTP; see machine_state.py.)

It must never bring the plugin down if there is no state -- any exception
is logged and retried in the next cycle.

"""
import job_states
import json
import os
import time

import heartbeats

import activity
import machine_state
import live_job
from messages import M, J

POLL_INTERVAL_S = 5

JOB_ACTIVE_STATES = job_states.POLLER_ACTIVE

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop-service.log")


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [job_poller] {msg}\n")
    except Exception:
        pass


def _get_status():
    return machine_state.get_status()  # single subscription: no request


def _fmt(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _zones_snapshot(status):
    move = status.get("move") or {}
    axes = {a.get("letter"): a for a in (move.get("axes") or []) if a}
    ox = (axes.get("X") or {}).get("workplaceOffsets") or []
    oy = (axes.get("Y") or {}).get("workplaceOffsets") or []
    return {
        "wn": move.get("workplaceNumber"),
        "offsets": [(ox[i] if i < len(ox) else 0, oy[i] if i < len(oy) else 0) for i in range(9)],
        "laser_on": (status.get("global") or {}).get("laserOffsetOn"),
    }


def _zones_events(bridge, prev, cur, skip_offsets=False):
    """Records changes of active zone, of origin and of the laser offset
    (2026-10-08). They are detected by comparing the object model between polls,
    so they count wherever they come from (jog, Zones page, console, macros)."""
    if prev is None:
        return
    if cur["laser_on"] is not None and prev["laser_on"] is not None and cur["laser_on"] != prev["laser_on"]:
        activity.log_event(
            bridge, "zone",
            M("laser_offset_applied") if cur["laser_on"] else M("laser_offset_removed"),
        )
        return "offset"  # shifts all the origins at once: do not list them one by one
    if cur["wn"] != prev["wn"] and isinstance(cur["wn"], int):
        of = machine_state.zone_name(prev["wn"]) if isinstance(prev["wn"], int) else "?"
        activity.log_event(bridge, "zone", M("zone_active", old=of, new=machine_state.zone_name(cur["wn"])))
    if skip_offsets:
        return None
    for i, (a, b) in enumerate(zip(prev["offsets"], cur["offsets"])):
        if abs(a[0] - b[0]) > 0.01 or abs(a[1] - b[1]) > 0.01:
            activity.log_event(
                bridge, "zone",
                M("zone_origin", zone=machine_state.zone_name(i), x0=_fmt(a[0]), y0=_fmt(a[1]), x1=_fmt(b[0]), y1=_fmt(b[1])),
            )


_air_last = [None]


def run_loop(bridge, config):
    log_file(f"starting (poll every {POLL_INTERVAL_S}s)")

    job_active = False
    job_file = None
    job_start_kwh = None
    job_start_iso = None
    job_start_epoch = None
    last_mode = None
    last_zones = None
    skip_offsets = 0  # polls to skip after a laser offset change
    cycle = 0

    while True:
        cycle += 1
        try:
            status = _get_status()
            state = status.get("state", {}) or {}
            job = status.get("job", {}) or {}
            global_vars = status.get("global", {}) or {}

            machine_status = state.get("status")

            # Air (2026-10-08): the live job calls laser/airon.g directly (not
            # the API (airassist)), so airAssist stayed False for the whole
            # cut. In Laser mode the air is gpOut[7] (M42 P7): it is taken from there.
            try:
                if (status.get("global") or {}).get("selectedMode") == "Laser":
                    gp = state.get("gpOut") or []
                    if len(gp) > 7 and gp[7] is not None:
                        air = (gp[7].get("pwm") or 0) > 0
                        if air != _air_last[0]:
                            _air_last[0] = air
                            bridge.set_status("airAssist", air)
            except Exception:
                pass
            file_info = job.get("file") or {}
            file_name = file_info.get("fileName")
            duration = job.get("duration")
            kind = global_vars.get("selectedMode")
            consumption_kwh = global_vars.get("consumptionKWh")

            now_active = machine_status in JOB_ACTIVE_STATES

            # 2026-10-12: job opened with the API (trabajo) (live_job.py):
            # real activity, close when the file ends and for lack of activity
            try:
                live_job.watch(bridge, config, status)
            except Exception as e:
                log_file(f"job_live: {e}")

            if now_active and not job_active:
                job_active = True
                job_file = file_name
                job_start_kwh = consumption_kwh
                job_start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
                job_start_epoch = int(time.time())
                activity.log_event(
                    bridge, "job_start",
                    M("job_started", label=job_file or M("no_name"), zone=""),
                    kind=kind,
                )

            elif job_active and not now_active:
                consumption_delta = None
                if consumption_kwh is not None and job_start_kwh is not None:
                    consumption_delta = round(consumption_kwh - job_start_kwh, 3)
                verb_key = "job_cancelled" if machine_status == "cancelling" else "job_finished"
                # 2026-10-10: otros medidores (ver medidores.desglose)
                extra = ""
                try:
                    import meters
                    dz = meters.breakdown(job_start_iso, time.strftime("%Y-%m-%dT%H:%M:%S")) if job_start_iso else None
                except Exception:
                    dz = None
                if dz:
                    if dz["extra_kwh"] and consumption_delta is not None:
                        consumption_delta = round(consumption_delta + dz["extra_kwh"], 3)
                    extra = M("in_parentheses", text=dz["text"])
                # 2026-10-12: if the file carried the API (trabajo) S"inicio", the end
                # (with name, zone and kWh) was already recorded by live_job.py: do not duplicate
                # hours or kWh in the activity.
                if live_job.file_registered(job_file, job_start_epoch):
                    log_file(f"end of {job_file}: already recorded by the API call P\"trabajo\"")
                else:
                    activity.log_event(
                        bridge, "job_end", M(verb_key, label=job_file or M("no_name"), extra=extra),
                        kind=kind, duration_s=duration, consumption_kwh=consumption_delta,
                    )
                job_active = False
                job_file = None
                job_start_kwh = None

            if kind is not None and kind != last_mode:
                if last_mode is not None:
                    activity.log_event(bridge, "mode", M("mode_changed", mode=kind), kind=kind)
                last_mode = kind

            zones = _zones_snapshot(status)
            try:
                # laseroffset.g changes the flag and AFTER that reapplies the
                # origins: if the poll catches them in different rounds, do not
                # list each origin as "changed".
                if _zones_events(bridge, last_zones, zones, skip_offsets > 0) == "offset":
                    skip_offsets = 2
                elif skip_offsets > 0:
                    skip_offsets -= 1
            except Exception as e:
                log_file(f"zones: {e}")
            last_zones = zones

            if cycle == 1 or cycle % 60 == 0:
                log_file(f"cycle {cycle} OK: status={machine_status} job_active={job_active}")
            heartbeats.ok("jobs")
        except BaseException as e:
            log_file(f"cycle {cycle} error ({type(e).__name__}: {e})")
            heartbeats.error("jobs", e)

        time.sleep(POLL_INTERVAL_S)
