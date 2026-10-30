"""
Internal implementation of the API operation(s) job.get, job.start, job.end, job.cancel, job.close, job.timeout (api_ops.py maps their named
arguments to the one-letter parameters below).

Records the start/end of a job sent LIVE (e.g. a program over the
network bridge). Those jobs are not "jobs" for RRF (there is no file,
state.status never goes through "processing"), so job_poller.py does not
see them: it has to be announced with this handler from the program's
Start/End GCode.
If the start comes from a file (the program can also send the job as a
file), it closes by itself when that file ends.

Usage: <params> S"inicio" [N"<name>"]    -> at the start
     <params> S"fin"                     -> at the end
     <params> S"cancelar"                -> if it is cut by hand
     <params> S"cerrar"                  -> close the open one (cuts at its last activity)
     <params> S"plazo" D<min>            -> with no activity for that long, it closes by itself (0 = never)
     <params> S"movimiento" [M<mode>] [L<s>] [P<s>] -> how movement is blocked (global, used by motion_owner.py):
                                           M "protegido" | "duet" (like Duet: only a file blocks), L = seconds of
                                           rest that release the movement, P = seconds of rest that close the
                                           live job (0 = do not close because of this)
     <params>                            -> query (JSON)

It saves in the activity: duration, mode, active zone/material, kWh
consumed and approximate cost (rate from the Consumption page). The open
job is saved in job_current.json, so it survives a service
restart. Start, automatic closes and cutting the duration at the last
activity: live_job.py (2026-10-12).

"""
import json

import live_job
from messages import M, J


def run(params, bridge, config):
    action = str(params.get("S", "query")).strip().lower()

    if action == "start":
        label = str(params.get("N") or "").strip() or live_job.default_name()
        return live_job.launch(bridge, config, label)

    if action in ("end", "cancel", "close"):
        r = live_job.shut(bridge, config, "manual" if action == "close" else action)
        if r is None:
            if action == "close":
                return M("job_there_no_open_job")
            return M("job_there_was_no_open_job_job")
        dur, kwh, _end = r
        key = {"end": "job_job_finished_summary", "cancel": "job_job_cancelled_summary", "close": "job_job_closed_summary"}[action]
        return M(key, minutes=dur / 60, energy=M("job_energy_kwh", kwh=kwh) if kwh is not None else "")

    if action == "deadline":
        try:
            d = max(0, min(int(float(params.get("D"))), 24 * 60))
        except (TypeError, ValueError):
            return "Error: job.timeout needs minutes (0 = never)"
        config.setdefault("job_in_live", {})["deadline_inactive_min"] = d
        bridge.save_config()
        live_job.emit(bridge, live_job.read_in(), config)
        if not d:
            return M("job_live_job_no_longer_closes_by_itself")
        return M("job_live_job_closes_by_itself_after", min=d)

    if action == "movement":
        import motion_owner
        mov = config.setdefault("movement", {})
        changes = []
        if "M" in params:
            kind = str(params.get("M")).strip().lower()
            if kind not in motion_owner.MODES:
                return "Error: movement.lock needs mode protected or duet"
            mov["block"] = kind
            changes.append(M("job_lock_mode", kind=kind))
        if "L" in params:
            try:
                v = int(float(params.get("L")))
            except (TypeError, ValueError):
                return "Error: movement.lock needs release_s in seconds"
            mov["release_s"] = max(motion_owner.RECENT_MIN_S, min(motion_owner.RECENT_MAX_S, v))
            changes.append(M("job_releases_after", s=mov['release_s']))
        if "P" in params:
            try:
                v = int(float(params.get("P")))
            except (TypeError, ValueError):
                return "Error: movement.lock needs idle_s in seconds"
            v = 0 if v <= 0 else max(motion_owner.RECENT_MIN_S, min(v, 3600))
            config.setdefault("job_in_live", {})["stop_idle_s"] = v
            changes.append(M("job_live_job_not_closed_when_idle") if not v else M("job_live_job_closes_after_idle", s=v))
        if changes:
            bridge.save_config()
            motion_owner.publish(bridge, force=True)
        kind, lib = motion_owner.settings()
        if changes:
            return M("job_movement_changes", changes=J(changes))
        return M("job_movement_current", kind=kind, release=lib, idle=live_job.stop_s(config))

    return json.dumps({"open": live_job.read_in(), "deadline_inactive_min": live_job.deadline_min(config)})
