"""Safe stop and resume of the live job: the operations of the service (2026-10-22).

The lines of a live job go through the G-code bridge (another program, bridge/gcode_bridge.py + live_stop.py), so the bridge is the one that
stops feeding the board, keeps the journal of what ran and saves the interrupted record (data/live-interrupted.json). This module is the
door for the pages: it checks what the service knows (mode, homing, restart of the board, a job running), asks the bridge through its action
file (data/bridge-action.json, the same mechanism as the Services page) and waits for its answer in bridge-state.json (key live_stop).

Operations (roles in permissions.py):
  livejob.stop_safe         operator   stop the live job without cutting anything: laser off, record saved, the rest of the job refused
  livejob.interrupted.list  viewer     the interrupted jobs (light) and, for each, why it can or cannot be resumed now
  livejob.interrupted.get   viewer     one record with its path and bounding box (to draw it)
  livejob.resume.arm        operator   arm ONE record: the next BRIDGE JOB START of the program starts the verified resume (confirm level 3)
  livejob.resume.disarm     operator   cancel the armed resume
  livejob.interrupted.hide  operator   take a record off the work table without deleting it (stays listed)
  livejob.interrupted.discard operator forget a record (deletes it)

It is NOT the emergency stop (M112, machine.stop): nothing is cancelled and the power stays. Only laser jobs can be resumed.
"""
import json
import os
import time

import fs_atomic
import machine_state
import paths
from messages import M
from workshop_api import READ, STOP, WRITE, ApiError, Arg, Op

STATE_FILE = paths.DATA_DIR + "/bridge-state.json"
ACTION_FILE = paths.DATA_DIR + "/bridge-action.json"
RECORDS_FILE = paths.DATA_DIR + "/live-interrupted.json"
HIDDEN_FILE = paths.DATA_DIR + "/live-interrupted-hidden.json"   # ids taken off the work table (the record stays in the list)
STATE_MAX_AGE_S = 15           # a bridge state older than this: the bridge is not running
ACTION_WAIT_S = 10.0           # the bridge picks an action up within its tick (~2 s)
STOP_WAIT_S = 150.0            # the stop waits for the lines the board already accepted
POLL_S = 0.4
REBOOT_TOL_S = 30              # the Duet boot mark moves more than this = the board restarted since the stop (origins and offsets are gone)
BLOCKERS = ("not_laser", "rebooted", "machine_unknown", "job_running", "machine_busy", "not_homed", "not_resumable")


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def bridge_state():
    """bridge-state.json of the bridge, or ApiError when it is not there / not updating (the bridge is stopped or too old to have this)."""
    try:
        st = _read_json(STATE_FILE)
    except (OSError, ValueError):
        raise ApiError("failed", M("livejob_bridge_down"))
    # the age is the one of the FILE: the bridge writes its floats with 6 digits ("time": 1.79271e+09 is only good to ~3 hours)
    try:
        age = time.time() - os.path.getmtime(STATE_FILE)
    except OSError:
        raise ApiError("failed", M("livejob_bridge_down"))
    if age > STATE_MAX_AGE_S:
        raise ApiError("failed", M("livejob_bridge_down"))
    if not (st.get("live_stop") or {}).get("enabled"):
        raise ApiError("failed", M("livejob_bridge_old"))
    return st


def _records():
    try:
        data = _read_json(RECORDS_FILE)
    except (OSError, ValueError):
        return []
    recs = data.get("records") if isinstance(data, dict) else None
    return [r for r in (recs or []) if isinstance(r, dict) and r.get("id")]


def _hidden_ids():
    try:
        data = _read_json(HIDDEN_FILE)
    except (OSError, ValueError):
        return set()
    ids = data.get("ids") if isinstance(data, dict) else None
    return {str(i) for i in (ids or [])}


def _record(rid):
    rec = next((r for r in _records() if r.get("id") == rid), None)
    if rec is None:
        raise ApiError("not_found", M("livejob_unknown_record"))
    return rec


def _send(action, args=None, wait=None):
    """Writes an action for the bridge and returns its result ({seq, ok, code, text}) once it has been picked up."""
    seq = int(time.time() * 1000)
    body = dict(args or {}, seq=seq, action=action)
    os.makedirs(os.path.dirname(ACTION_FILE), exist_ok=True)
    tmp = ACTION_FILE + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    os.replace(tmp, ACTION_FILE)
    end = time.time() + (ACTION_WAIT_S if wait is None else wait)
    while time.time() < end:
        try:
            res = (_read_json(STATE_FILE) or {}).get("action") or {}
        except (OSError, ValueError):
            res = {}
        if res.get("seq") == seq:
            return res
        time.sleep(POLL_S)
    raise ApiError("failed", M("livejob_bridge_no_answer"))


def _mode():
    try:
        import api_ops
        return api_ops.current_mode()
    except Exception:  # noqa: BLE001
        return None


def _boot_mark():
    try:
        up = machine_state.read_in("state.upTime")
        return round(time.time() - float(up), 1) if up is not None else None
    except Exception:  # noqa: BLE001
        return None


def _status():
    try:
        return machine_state.read_in("state.status")
    except Exception:  # noqa: BLE001
        return None


def _homed_xy():
    try:
        axes = machine_state.read_in("move.axes") or []
        wanted = [a for a in axes if isinstance(a, dict) and a.get("letter") in ("X", "Y")]
        return bool(wanted) and all(a.get("homed") for a in wanted)
    except Exception:  # noqa: BLE001
        return None


def blockers(rec, live_job_active=False, mode=None, status=None, mark=None, homed=None):
    """Why this record cannot be resumed now: a list of codes from BLOCKERS (empty = it can). The arguments are for tests."""
    out = []
    if not rec.get("resumable"):
        out.append("not_resumable")
    mode = _mode() if mode is None else mode
    status = _status() if status is None else status
    homed = _homed_xy() if homed is None else homed
    mark = _boot_mark() if mark is None else mark
    if mode is None or status is None:
        out.append("machine_unknown")
    if mode is not None and mode != "laser":
        out.append("not_laser")
    if live_job_active:
        out.append("job_running")
    elif status is not None and status not in ("idle",):
        out.append("machine_busy")
    if rec.get("boot_mark") is not None and mark is not None and abs(float(mark) - float(rec["boot_mark"])) > REBOOT_TOL_S:
        out.append("rebooted")
    if homed is False:
        out.append("not_homed")
    return out


def _light(rec, live_job_active):
    row = {k: rec.get(k) for k in ("id", "name", "started", "stopped", "reason", "lines", "bbox", "cut_mm", "program_pos", "position", "mode",
                                   "resumable", "why_not", "armed", "boot_mark")}
    row["blockers"] = blockers(rec, live_job_active)
    row["can_resume"] = not row["blockers"]
    # when the board started (epoch s): the page says WHEN it restarted and how long after the stop, so a restart by a power cut is not read as
    # a consequence of the stop (the safe stop never restarts anything)
    mark = _boot_mark() if "rebooted" in row["blockers"] else None
    row["rebooted_at"] = round(mark) if mark is not None else None
    return row


# ---------------------------------------------------------------------------------------------------- operations
def stop_safe(args, ctx):
    st = bridge_state()
    if not ((st.get("activity") or {}).get("live_job") or {}).get("active"):
        raise ApiError("conflict", M("livejob_no_job"))
    res = _send("stop_safe", {"mode": _mode(), "boot_mark": _boot_mark()})
    if not res.get("ok"):
        raise ApiError("failed", str(res.get("text") or M("livejob_stop_failed")))
    end = time.time() + STOP_WAIT_S
    seq = res.get("seq")
    last = {}
    while time.time() < end:
        last = (bridge_state().get("live_stop") or {}).get("last_result") or {}
        if last.get("seq") == seq:
            break
        time.sleep(POLL_S)
    else:
        raise ApiError("failed", M("livejob_stop_timeout"))
    if not last.get("ok"):
        raise ApiError("failed", M("livejob_stop_failed_why", why=str(last.get("text") or "")))
    rec = next((r for r in _records() if r.get("id") == last.get("id")), None) or {}
    return {"stopped": True, "id": last.get("id"), "lines": rec.get("lines"), "resumable": bool(rec.get("resumable")), "why_not": rec.get("why_not"),
            "message": M("livejob_stopped", n=rec.get("lines") or 0)}


def list_op(args, ctx):
    try:
        st = bridge_state()
    except ApiError as e:
        return {"available": False, "reason": e.message if hasattr(e, "message") else str(e), "records": [], "live_job": False}
    live = bool(((st.get("activity") or {}).get("live_job") or {}).get("active"))
    ls = st.get("live_stop") or {}
    summary = {r.get("id"): r for r in _records()}
    rows = [_light(summary[r["id"]], live) for r in ls.get("interrupted") or [] if r.get("id") in summary]
    hidden = _hidden_ids()
    for row in rows:
        row["hidden"] = row["id"] in hidden
    return {"available": True, "live_job": live, "stopping": bool(ls.get("stopping")), "resume": ls.get("resume"), "records": rows}


def get_op(args, ctx):
    rec = dict(_record(args["id"]))
    for heavy in ("checkpoints", "tail"):
        rec.pop(heavy, None)
    rec["blockers"] = blockers(rec, False)
    return rec


def arm_op(args, ctx):
    rec = _record(args["id"])
    st = bridge_state()
    live = bool(((st.get("activity") or {}).get("live_job") or {}).get("active"))
    why = blockers(rec, live)
    if why:
        raise ApiError("conflict", M("livejob_blocked_" + why[0]), blockers=why)
    import interlocks
    err = interlocks.refusal()
    if err is not None:
        raise err
    who = ((ctx or {}).get("user") or {}).get("name") or ""
    res = _send("resume_arm", {"id": rec["id"], "overlap_lines": args.get("overlap_lines") or 0, "by": who})
    if not res.get("ok"):
        raise ApiError("failed", str(res.get("text") or ""))
    return {"armed": True, "id": rec["id"], "message": M("livejob_armed")}


def disarm_op(args, ctx):
    res = _send("resume_disarm")
    if not res.get("ok"):
        raise ApiError("failed", str(res.get("text") or ""))
    return {"armed": False}


def hide_op(args, ctx):
    """Takes a record off the work table (or puts it back). Nothing is deleted: it stays in the list of interrupted jobs."""
    _record(args["id"])
    ids = _hidden_ids()
    (ids.add if args["hidden"] else ids.discard)(args["id"])
    fs_atomic.write_json(HIDDEN_FILE, {"ids": sorted(ids)})
    return {"id": args["id"], "hidden": bool(args["hidden"])}


def discard_op(args, ctx):
    _record(args["id"])
    res = _send("interrupted_discard", {"id": args["id"]})
    if not res.get("ok"):
        raise ApiError("failed", str(res.get("text") or ""))
    ids = _hidden_ids()
    if args["id"] in ids:
        ids.discard(args["id"])
        fs_atomic.write_json(HIDDEN_FILE, {"ids": sorted(ids)})
    return {"discarded": True}


def ops():
    ident = Arg("str", True, desc="Id of the interrupted job (livejob.interrupted.list).")
    return [
        Op("livejob.stop_safe", stop_safe, STOP, {},
           "Stops the live job safely, without cutting power or cancelling anything: the lines that come after are refused, what the board already "
           "accepted finishes, the laser goes off, where it stopped is read and an interrupted record (line number, hash, position, modal state, "
           "path) is saved so the job can be resumed. Not the emergency stop. Fails when there is no live job or the bridge does not answer."),
        Op("livejob.interrupted.list", list_op, READ, {},
           "The interrupted live jobs (light) with, for each, blockers: why it cannot be resumed now (not_laser, rebooted, machine_unknown, "
           "job_running, machine_busy, not_homed, not_resumable) and can_resume. Also the progress of a resume in course.", log=False),
        Op("livejob.interrupted.get", get_op, READ, {"id": ident},
           "One interrupted job with its path [[x, y, cut]] and bounding box in the program's coordinates, its modal state and where the head was.",
           log=False),
        Op("livejob.resume.arm", arm_op, WRITE,
           {"id": ident, "overlap_lines": Arg("int", False, default=0, min=0, max=39,
                                              desc="Go back this many lines and cut them again (a small overlap at the join); 0 = continue exactly.")},
           "Arms ONE interrupted job (for 30 minutes): the next time the program sends the same job (BRIDGE JOB START) the bridge verifies and skips the "
           "lines already done, goes to where it stopped with the laser off and continues. Any line that differs cancels it and nothing runs. Needs "
           "the confirmation of level 3, laser mode, homed XY, the board not restarted since the stop and no job running.",
           confirm={"level": 3, "key": "livejob.resume.arm"}),
        Op("livejob.resume.disarm", disarm_op, WRITE, {}, "Cancels the armed resume (the record stays)."),
        Op("livejob.interrupted.hide", hide_op, WRITE, {"id": ident, "hidden": Arg("bool", True, desc="true: take it off the work table (it stays listed); false: put it back.")},
           "Takes an interrupted job off the work table, or puts it back, WITHOUT deleting its record: it stays in the list with the point where it stopped."),
        Op("livejob.interrupted.discard", discard_op, WRITE, {"id": ident}, "Forgets an interrupted job (its record is deleted)."),
    ]
