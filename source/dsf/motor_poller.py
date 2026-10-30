"""
Motor state poller -- it runs in a background thread inside
dsf/main.py (like status_light.py/consumption_poller.py/job_poller.py),
publishing every POLL_INTERVAL_S seconds a complete structured report
(not text) via bridge.set_status("motorReport", {...}) -- it is available
immediately and reactive on the plugin's "Motors" page in DWC
(dwc-src/Motors.vue), just like "connected"/etc.

Every fast cycle (1 s) it recomputes speed/frequency/RPM from the standard
object model (free, at no extra cost). Every M122_EVERY_N_CYCLES
cycles (slower, these are heavier commands) it sends, for each LOCAL driver:
M122 (text diagnostics), M569 without parameters (timing/
configured current) and a READ-ONLY M569.2 (without V, never) twice
-- the GSTAT register (0x01, reset/error latch) and DRV_STATUS (0x6F,
state + instantaneous real current). The raw DRV_STATUS is only requested if
it is known which chip the local board has (motor_status.chip_of_board): its
bit map depends on the chip. If not known, only RRF's standard state
from the object model (boards[].drivers[].status) is used, which is valid
for any board. See dsf/motor_status.py for the safety details, the bit maps
and how the speed is computed (current move + standstill).

2026-10-12 (enable/disable motors from the page): with a known chip,
CHOPCONF (0x6C, read-only M569.2) is also read for each local driver:
TOFF=0 = driver disabled. It is the only way to know whether a motor is
enabled (RRF does not publish it in the object model). It is read at the
same slow rate and also in the cycle after someone asks for a re-read
(request_reread(), the API (motors) S"reread"), so that the page sees right
away the result of an M17/M18. "enabled_seq" goes up with each new
reading: the page waits for it to go up to confirm.

2026-10-12 (DCS load): the driver reads (M122, M569, M569.2 GSTAT / DRV_STATUS /
CHOPCONF: about 5 G-codes per driver every 5 s, each one a round trip of
DuetControlServer to the drivers) run ONLY while the Motors page is open: the
page sends the API (motors) S"watch" every ~10 s (viewers.py, topic "motors").
Without a heartbeat for viewers.TTL_S the poller does one cycle every IDLE_S
with NO IPC at all (the report is built from the object model and the last
driver values read, and it is published only if it changed or every
IDLE_KEEPALIVE_S). The report says so: "idle": true and "drivers_read_at" (when
the driver values were read; empty if never). The first heartbeat wakes the
poller and the driver reads run in that same cycle.

2026-10-21 (Motors redesign, TallerPlugins docs-internal/MOTORES-DISENO.md): which axes and extruders are
RELEASED (without holding force) is known here, not by the page: from the CHOPCONF readings (local drivers) and
from the API requests (handlers/motors.py calls note_request; the only source for CAN drivers). It is published as
"released" (+ "released_since") and it feeds the automatic level 4 risk (risk_rules.py) and the status lights.
Without the page CHOPCONF is read only when it matters: while something is released (every idle cycle) and in the
cycle after a change of the homed flags (M18 removes the homing; homing moves the axis, which enables it again).

"""
import os
import threading
import time

import heartbeats
import service_modules

import motor_status
import settings_store
import viewers
from messages import M

POLL_INTERVAL_S = 1
IDLE_S = 30  # nobody looking at the Motors page: one cycle every IDLE_S, no IPC
IDLE_KEEPALIVE_S = 60  # idle and unchanged: republish this often (age of the report)
M122_EVERY_N_CYCLES = 5  # M122 is heavier -- it refreshes about every 5 s, not every 1 s

# CHOPCONF re-read requested from outside the thread (handlers/motors.py)
_reread = threading.Event()

# Released axes / extruders: key ("X", "E0") -> {"since": epoch s (int), "by": "reading" | "request",
# "unhomed": the axis was seen without homing after the release (None for an extruder)}
_released = {}
# Keys whose drivers were last read WITH force. RRF leaves every driver off after power-up until the first move, and an
# extruder that is not used stays off: a driver read off counts as released only after it was seen holding (or after
# an M18 of the API), so neither the start-up nor an unused extruder raises the level 4 risk.
_holding = set()
_released_lock = threading.Lock()


def _order(key):
    """Axes first (in letter order), then the extruders by number."""
    k = str(key)
    if k[:1] == "E" and k[1:].isdigit():
        return (1, int(k[1:]), "")
    return (0, 0, k)


def released():
    """Sorted keys of the axes / extruders without holding force (empty: none)."""
    with _released_lock:
        return sorted(_released, key=_order)


def released_since():
    """Epoch seconds (int) since the oldest one is released, or None."""
    with _released_lock:
        return min((v["since"] for v in _released.values()), default=None)


def status_keys(status):
    """The keys of every axis and extruder with drivers of the object model ("all" of M17 / M18)."""
    move = (status or {}).get("move") or {}
    keys = [str(a.get("letter")) for a in move.get("axes") or [] if a and a.get("letter") and a.get("drivers")]
    keys += ["E%d" % i for i, x in enumerate(move.get("extruders") or []) if x and (x.get("drivers") or x.get("driver"))]
    return keys


def homed_by_axis(status):
    """letter -> homed (bool) of the axes of the object model."""
    move = (status or {}).get("move") or {}
    return {str(a.get("letter")): bool(a.get("homed")) for a in move.get("axes") or [] if a and a.get("letter")}


def update_released(prev, enabled_by_key, homed, now, requests=None, holding=None):
    """Pure: (released, holding) after a cycle.
    prev: the released dict; enabled_by_key: key -> [True / False / None per driver] (None = not known: CAN board,
    unknown chip, no reading); homed: letter -> bool; now: epoch s; requests: [("disable" | "enable", keys)];
    holding: keys last read with force.
    - a request to disable adds its keys (by "request"), one to enable removes them;
    - every known driver enabled: the key holds (and it is no longer released);
    - some known driver disabled: released ("reading") if the key was holding or already released; otherwise it was
      never seen with force (start-up, an extruder that is not used) and nothing is claimed;
    - a key released by request whose drivers cannot be read clears when its axis is homed again (homing moves the
      axis, and any move enables its drivers): seen WITHOUT homing first (M18 removes it), then homed. A snapshot
      taken a moment before the M18 still says homed: that alone clears nothing."""
    out = {k: dict(v) for k, v in (prev or {}).items()}
    hold = set(holding or ())
    for action, keys in requests or []:
        for k in keys:
            if action == "disable":
                hold.discard(k)
                if k not in out:
                    out[k] = {"since": int(now), "by": "request", "unhomed": None if _order(k)[0] else False}
            else:
                out.pop(k, None)
    for k, values in (enabled_by_key or {}).items():
        known = [v for v in values if isinstance(v, bool)]
        if not known:
            continue
        if all(known):
            hold.add(k)
            out.pop(k, None)
            continue
        if k in hold or k in out:
            hold.discard(k)
            if k not in out:
                out[k] = {"since": int(now), "by": "reading", "unhomed": None if _order(k)[0] else False}
            else:
                out[k]["by"] = "reading"
    for k in list(out):
        v = out[k]
        values = (enabled_by_key or {}).get(k) or []
        if v["by"] != "request" or any(isinstance(x, bool) for x in values) or k not in homed:
            continue
        if not homed[k]:
            v["unhomed"] = True
        elif v.get("unhomed"):
            out.pop(k, None)
    return out, hold


def _apply(enabled_by_key, homed, requests=None):
    """Runs update_released on the module state (call with _released_lock held)."""
    new, hold = update_released(_released, enabled_by_key, homed, time.time(), requests, _holding)
    _released.clear()
    _released.update(new)
    _holding.clear()
    _holding.update(hold)


def note_request(action, keys):
    """handlers/motors.py after an M17 / M18 the board accepted: action "disable" | "enable", keys of the motors
    (every one of the machine for "all"). Applied right away so the risk and the lights do not wait for the poller."""
    action = "disable" if action == "disable" else "enable"
    keys = [str(k) for k in keys or []]
    with _released_lock:
        _apply({}, {}, [(action, keys)])


def request_reread():
    """Reads the enabled state of the drivers in the next cycle (~1 s).
    Whoever asks is looking at the page: it also counts as a heartbeat."""
    _reread.set()
    viewers.heartbeat("motors")


LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop-service.log")


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [motor_poller] {msg}\n")
    except Exception:
        pass


def run_loop(bridge, config, stop=lambda: False, pause=None):
    """stop() / pause(seconds): hooks for the tests (default: run forever and
    sleep with viewers.sleep, which a first heartbeat interrupts)."""
    if pause is None:
        pause = lambda s: viewers.sleep("motors", s)  # noqa: E731
    log_file(f"starting (poll every {POLL_INTERVAL_S}s, M122 every {M122_EVERY_N_CYCLES} cycles)")
    full_steps = config.get("motor_status", {}).get("full_steps_per_rev", 200)
    # Optional: force the raw DRV_STATUS map of the local board
    # ("tmc51xx" / "tmc22xx") if the board is not in motor_status.CHIP_BY_BOARD.
    chip_forced = config.get("motor_status", {}).get("chip_drivers_local")
    chip_notified = False
    cycle = 0
    m122_text = None
    gstat_by_local_driver = {}
    m569_by_local_driver = {}
    drv_status_raw_by_local_driver = {}
    chopconf_by_local_driver = {}
    enabled_seq = 0
    without_alim_before = False
    loop_hz_max_ever = None  # highest ceiling the firmware measured in some M122 (see motor_status.py)
    # 2026-10-09 (Motors > Measure > Pulse ceiling): each M122 resets the
    # firmware's hiccups counter to zero, so it is ACCUMULATED here: the test
    # compares hiccups_total before and after each stretch, and m122_seq tells it
    # when there was a new reading (after the stretch ended).
    hiccups_total = 0
    m122_seq = 0
    watched_before = False
    read_in = ""  # when the drivers were last read (report["drivers_read_at"])
    homed_before = None  # homed flags of the previous cycle (a change triggers a CHOPCONF read without the page)

    while not stop():
        # the Motors plugin is stopped or disabled (Settings > Plugins): the drivers are not polled (service_modules.py)
        if not service_modules.is_active(service_modules.MOTORS):
            heartbeats.ok("motors")
            heartbeats.detail("motors", M("motor_poller_at_rest_motors_plugin_stopped"))
            with _released_lock:
                _released.clear()  # nobody watches the drivers: nothing is claimed (the module rests with its plugin)
                _holding.clear()
            homed_before = None
            pause(3)
            continue
        cycle += 1
        watched = viewers.active("motors")
        if watched and not watched_before:
            cycle = 1  # someone just opened the page: read the drivers in this very cycle
        watched_before = watched
        try:
            status = motor_status.fetch_status()
            local_ids = motor_status.local_driver_indices(status)
            chip_local = motor_status.chip_of_board(motor_status.board_local(status), chip_forced)
            if chip_local is None and not chip_notified:
                chip_notified = True
                log_file("unknown chip of the local drivers: the raw DRV_STATUS is not read, "
                         "the object model state is used")

            # 2026-10-08 ("when the PSU is turned off many M569 errors come out"):
            # with the supply off (state.status "off", VIN ~0 V) the board is still
            # alive on its 5 V, but the drivers have no power -- each M569/M569.2 took up
            # to the timeout and filled the log with errors. Without power no driver is
            # queried and the old data is discarded (it is no longer real).
            without_alim = motor_status.drivers_without_power_supply(status)
            homed = homed_by_axis(status)
            homed_changed = homed_before is not None and homed != homed_before
            homed_before = homed
            with _released_lock:
                released_any = bool(_released)
            power_back = False
            if without_alim:
                if not without_alim_before:
                    log_file("drivers without power (PSU off): M122/M569/M569.2 paused")
                gstat_by_local_driver.clear()
                m569_by_local_driver.clear()
                drv_status_raw_by_local_driver.clear()
                chopconf_by_local_driver.clear()
                m122_text = None
            elif without_alim_before:
                log_file("drivers powered again: readings resumed")
                cycle = 1  # do the slow reading in this same cycle
                power_back = True
            without_alim_before = without_alim

            slow = watched and not without_alim and cycle % M122_EVERY_N_CYCLES == 1
            reread = _reread.is_set()
            if reread:
                _reread.clear()
            reread = reread and watched
            # without the page: only when it matters (something released, a homing change, the power back)
            needed = not watched and (homed_changed or released_any or power_back)
            if not without_alim and chip_local is not None and (slow or reread or needed):
                # CHOPCONF: enabled / disabled of each local driver
                read_items = {}
                for local_idx in local_ids:
                    c = motor_status.read_chopconf_raw(bridge, local_idx)
                    if c is not None:
                        read_items[local_idx] = c
                chopconf_by_local_driver.clear()
                chopconf_by_local_driver.update(read_items)
                enabled_seq += 1

            if slow:
                m122_fresh = False
                try:
                    m122_text = bridge.send("M122")
                    m122_fresh = True
                except Exception as e:
                    log_file(f"M122 failed ({type(e).__name__}: {e}), reusing the last text")

                for local_idx in local_ids:
                    g = motor_status.read_gstat(bridge, local_idx)
                    if g is not None:
                        gstat_by_local_driver[local_idx] = g
                    # M569 (timing/current/mode) changes little -- it is enough
                    # to refresh it at the same slow rate as GSTAT/M122.
                    m = motor_status.read_m569(bridge, local_idx)
                    if m is not None:
                        m569_by_local_driver[local_idx] = m
                    # Raw DRV_STATUS (carries CS_ACTUAL): only with a known chip,
                    # because the bit map depends on the chip.
                    if chip_local is not None:
                        d = motor_status.read_drv_status_raw(bridge, local_idx)
                        if d is not None:
                            drv_status_raw_by_local_driver[local_idx] = d

                bc = motor_status.parse_m122_board_capacity(m122_text)
                if bc and bc.get("loop_hz_max"):
                    loop_hz_max_ever = max(loop_hz_max_ever or 0, bc["loop_hz_max"])
                if m122_fresh and bc and "hiccups_ring0" in bc:
                    hiccups_total += int(bc.get("hiccups_ring0") or 0) + int(bc.get("hiccups_ring1") or 0)
                    m122_seq += 1

            try:  # the motor data the person saved in the Advisor (steps per revolution of each motor); without it, config.json / 200
                steps_of = motor_status.steps_per_rev_resolver(settings_store.get("motors")["value"], full_steps)
            except Exception:  # noqa: BLE001  a damaged or missing file must not stop the reading of the drivers
                steps_of = None
            report = motor_status.compute_motor_report(
                status, full_steps_per_rev=full_steps, m122_text=m122_text, steps_per_rev_of=steps_of,
                gstat_by_local_driver=gstat_by_local_driver,
                loop_hz_max_ever=loop_hz_max_ever,
                m569_by_local_driver=m569_by_local_driver,
                drv_status_raw_by_local_driver=drv_status_raw_by_local_driver,
                chip_local=chip_local,
                chopconf_by_local_driver=chopconf_by_local_driver,
            )
            report["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            report["without_power_supply"] = without_alim
            report["hiccups_total"] = hiccups_total
            report["m122_seq"] = m122_seq
            report["enabled_seq"] = enabled_seq
            if slow or reread:
                read_in = report["updated_at"]
            report["idle"] = not watched
            report["drivers_read_at"] = read_in
            enabled_by_key = {
                str(e.get("label")): [d.get("enabled") for d in e.get("drivers") or []]
                for e in report.get("entries") or [] if e.get("label")
            }
            with _released_lock:
                _apply({} if without_alim else enabled_by_key, homed)
            report["released"] = released()
            report["released_since"] = released_since()

            if watched:
                bridge.set_status("motorReport", report)
            else:
                # nobody looking: only real changes (and a keepalive), not a new timestamp
                bridge.set_status("motorReport", report, volatile=("updated_at",), keepalive_s=IDLE_KEEPALIVE_S)
            heartbeats.ok("motors")

            if cycle == 1 or cycle % 150 == 0:
                log_file(f"cycle {cycle} OK: {len(report['entries'])} motors")
        except BaseException as e:
            log_file(f"cycle {cycle} error ({type(e).__name__}: {e})")
            heartbeats.error("motors", e)

        pause(POLL_INTERVAL_S if watched else IDLE_S)
