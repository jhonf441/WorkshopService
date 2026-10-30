"""`machine.try` of Machine v2 (phases 2 and 3): a VOLATILE trial of a value that is normally written in the configuration, with automatic revert.

Kinds (`gcode_kind`): M208 (axis limits, phase 2) and, in phase 3, M92 (steps/mm), M906 (currents, idle), M913, M917, M203, M201, M205, M566, M425 (backlash),
M556 (skew) and M593 (input shaping). What each kind checks, reads and sends is in machine_try_kinds.py (the closed list of machine_gcode.py is the only
way to the board). M376 answers `not_implemented`. The role is decided by the registry from `gcode_kind` (permissions.ESCALATE_IN: M208, M92, M906, M913 and
M917 are the administrator's; a call WITHOUT gcode_kind needs admin too).

    machine.try {gcode_kind, values, seconds: 5-600 (60)}                 sends the lines, remembers the previous values, starts a timer
    machine.try {gcode_kind, action: "keep",   try_id}                    the trial stays (volatile until the next start); the answer tells how to persist it
    machine.try {gcode_kind, action: "revert", try_id}                    puts the previous values back now

Without `keep` the previous values are sent back when the time is over, even if the page was closed. The trial is written to
`0:/sys/workshop/data/machine/try-pending.json` BEFORE the first line is sent, so a restart of the service puts everything back as its first act
(`recover_pending`, started by main.py). A revert the board does not accept is tried again every RETRY_S seconds (MAX_RETRIES times) and then it stays
pending (the file keeps it; the next start tries again). One trial at a time. Refused with a job (the movement class `geometry`, and the status here), while
a procedure runs, and for M906 above the current cap of the profile. The change is the movement class `geometry` and needs a confirmation.
"""
import fs_atomic
import json
import os
import threading
import time

import identity
import machine_config as mc
import machine_parsers as parsers
import machine_profile
import machine_try_kinds as kinds
import motion_owner
import sd_paths
from messages import M
from workshop_api import ApiError, Arg, MOTION, READ, Op

KINDS = ("M208", "M92", "M906", "M913", "M917", "M593", "M425", "M556", "M376", "M203", "M201", "M205", "M566")
IMPLEMENTED = tuple(kinds.SPECS)
MIN_S, MAX_S, DEFAULT_S = 5, 600, 60
RETRY_S, MAX_RETRIES = 10, 6
PENDING = "sys/workshop/data/machine/try-pending.json"
JOB_STATUS = motion_owner.FILE_STATES | {"paused", "changingTool"}

_lock = threading.Lock()
_tries = {}
_hooks = {"clock": None, "timer": None}        # the tests replace them: a fake clock and a fake Timer class


def _now():
    return (_hooks["clock"] or time.time)()


def _make_timer(seconds, fn, args):
    t = (_hooks["timer"] or threading.Timer)(seconds, fn, args=args)
    t.daemon = True
    return t


def _pending_path():
    return sd_paths.sd(PENDING)


def _save_pending():
    rows = [{k: v for k, v in t.items() if k not in ("timer", "retries")} for t in _tries.values()]
    path = _pending_path()
    if not rows:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    fs_atomic.write_json(path, rows)


def _send(lines):
    import machine_ops as mo
    replies = mo.geometry_send(lines)
    return replies, parsers.find_errors("\n".join(replies))


def _lines_of(kind, values):
    return kinds.SPECS[kind].lines(values)


def revert(try_id, reason="timeout"):
    """Sends the previous values back. True when done; False (the trial stays pending) when the board could not be reached or refused."""
    with _lock:
        t = _tries.get(try_id)
    if t is None:
        return False
    try:
        _, errors = _send(_lines_of(t.get("gcode_kind", "M208"), t["previous"]))
    except Exception as e:  # noqa: BLE001
        print("machine.try: could not revert %s: %s" % (try_id, e))
        return False
    if errors:
        print("machine.try: the board refused the revert of %s: %s" % (try_id, errors[0]["text"]))
        return False
    _forget(try_id)
    return True


def _retry(try_id, reason="timeout"):
    """Timer callback: revert; when it fails, try again later (the trial is still in the pending file)."""
    if revert(try_id, reason):
        return
    with _lock:
        t = _tries.get(try_id)
        if t is None or t.get("retries", 0) >= MAX_RETRIES:
            return
        t["retries"] = t.get("retries", 0) + 1
        timer = _make_timer(RETRY_S, _retry, (try_id, "retry"))
        t["timer"] = timer
    timer.start()


def _forget(try_id):
    with _lock:
        t = _tries.pop(try_id, None)
        if t and t.get("timer"):
            t["timer"].cancel()
        _save_pending()


def recover_pending():
    """First act of the service: a trial left pending by a restart is put back (the values are volatile, but the board kept the trial value if only
    the service restarted). Returns how many were put back."""
    try:
        with open(_pending_path(), encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return 0
    done = 0
    for t in rows if isinstance(rows, list) else []:
        if isinstance(t, dict) and isinstance(t.get("previous"), dict) and t.get("id") and t.get("gcode_kind", "M208") in kinds.SPECS:
            with _lock:
                _tries[t["id"]] = dict(t, timer=None)
            done += 1 if revert(t["id"], "restart") else 0
    return done


def expire_due(now=None):
    """Reverts every trial whose time is over (what the timers do; callable by a test with a fake clock). Returns the ids put back."""
    now = _now() if now is None else now
    with _lock:
        due = [i for i, t in _tries.items() if t["expires_at"] <= now]
    return [i for i in due if revert(i, "timeout")]


def reset():
    """For the tests."""
    with _lock:
        for t in _tries.values():
            if t.get("timer"):
                t["timer"].cancel()
        _tries.clear()
    _hooks.update(clock=None, timer=None)


def _refuse_clean(e, kind):
    """The ApiError for a PlanError of clean()."""
    if e.code == "current_over_limit":
        import machine_ops as mo
        cap = machine_profile.current_cap(mo.profile_block())
        raise ApiError("refused", M("machine_try_current_limit", axis=e.field.split(".")[-1], limit=cap), reason="current_over_limit",
                       field="values." + e.field, limit_ma=cap, ceiling_ma=machine_profile.CURRENT_CEILING_MA)
    if e.code == "no_previous":
        raise ApiError("refused", M("machine_try_no_previous"), reason="no_previous")
    raise ApiError("invalid_args", M("machine_try_bad_value", field=e.field), field="values." + e.field, reason="bad_value")


def start(args, ctx):
    import machine_ops as mo
    kind = args.get("gcode_kind", "M208")
    spec = kinds.SPECS[kind]
    values = args.get("values")
    if not isinstance(values, dict):
        raise ApiError("invalid_args", M("machine_try_bad_value", field="values"), field="values", reason="bad_value")
    om = mo.model()
    try:
        applied = spec.clean(values, {"om": om, "profile": mo.profile_block()})
    except mc.PlanError as e:
        _refuse_clean(e, kind)
    seconds = int(args.get("seconds") or DEFAULT_S)
    if _tries:
        raise ApiError("refused", M("machine_try_pending"), reason="try_pending", try_id=next(iter(_tries)))
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])
    if str(mo.machine_status() or "") in JOB_STATUS:
        raise ApiError("refused", M("machine_try_job_running"), reason="job_running")
    previous = spec.previous(om, applied)
    if previous is None:
        raise ApiError("refused", M("machine_try_no_previous"), reason="no_previous")
    who = identity.actor(ctx)
    tid = "t-%d-%s" % (int(_now()), os.urandom(2).hex())
    entry = {"id": tid, "gcode_kind": kind, "previous": previous, "applied": applied, "ts": int(_now()), "seconds": seconds,
             "expires_at": int(_now()) + seconds, "user": who["user"]}
    with _lock:
        _tries[tid] = dict(entry, timer=None)
        _save_pending()          # written BEFORE sending: if the service dies in between, the revert still happens
    try:
        replies, errors = _send(spec.lines(applied))
    except Exception as e:  # noqa: BLE001
        revert(tid)
        _forget(tid)
        raise ApiError("failed", M("machine_try_board_error", text=str(e)[:120]))
    if errors:
        revert(tid)
        _forget(tid)
        raise ApiError("failed", M("machine_try_board_error", text=errors[0]["text"]), reason="board_error")
    timer = _make_timer(seconds, _retry, (tid, "timeout"))
    with _lock:
        _tries[tid]["timer"] = timer
    timer.start()
    return dict(entry, try_id=tid, action="start")


def _find(args):
    t = _tries.get(str(args.get("try_id") or ""))
    if t is None:
        raise ApiError("not_found", M("machine_try_not_found"), reason="not_found")
    return t


def _op(args, ctx):
    kind = args["gcode_kind"]
    if kind not in IMPLEMENTED:
        raise ApiError("not_implemented", M("machine_try_kind_not_implemented", kind=kind), field="gcode_kind")
    action = args.get("action") or "start"
    if action == "start":
        return start(args, ctx)
    t = _find(args)
    if t["gcode_kind"] != kind:
        # the role was decided from the argument gcode_kind: a trial of another kind (e.g. an admin M208 trial) cannot be kept or reverted with it
        raise ApiError("invalid_args", M("machine_try_not_found"), field="gcode_kind")
    if action == "keep":
        plan_kind, plan_values = kinds.SPECS[t["gcode_kind"]].persist(t["applied"])
        _forget(t["id"])
        return {"try_id": t["id"], "action": "keep", "kept": True, "applied": t["applied"], "persist": {"kind": plan_kind, "values": plan_values}}
    if not revert(t["id"], "manual"):
        raise ApiError("failed", M("machine_try_revert_failed"), reason="revert_failed")
    return {"try_id": t["id"], "action": "revert", "reverted": True, "previous": t["previous"]}


def _pending(args, ctx):
    return {"pending": [dict({k: v for k, v in t.items() if k != "timer"}, try_id=i, seconds_left=max(0, int(t["expires_at"] - _now()))) for i, t in _tries.items()]}


def ops():
    a = Arg
    return [Op("machine.try.pending", _pending, READ, {}, "The volatile trial waiting for its automatic revert, if any (so a page that was reloaded can keep or revert it)."),
            Op("machine.try", _op, MOTION,
               {"gcode_kind": a("str", True, choices=KINDS, desc="What is tried: M208 limits, M92 steps/mm, M906 currents (and idle), M913, M917, M203 speeds, "
                                                                 "M201 accelerations, M205 / M566 jerk, M425 backlash, M556 skew, M593 input shaping. M376 answers "
                                                                 "not_implemented. M208, M92, M906, M913 and M917 need an administrator."),
                "action": a("str", choices=("start", "keep", "revert"), desc="start (default), keep (the trial stays) or revert (put it back now)."),
                "values": a("obj", desc="Per kind, like the values of machine.config.plan of the same kind (M208: {axes: {\"X\": {min, max}}})."),
                "seconds": a("int", min=MIN_S, max=MAX_S, desc="Seconds before the automatic revert (60)."),
                "try_id": a("str", desc="For keep / revert.")},
               "Tries a VOLATILE value and puts the previous one back after `seconds` unless keep is sent, even if the page was closed "
               "or the service restarted. One trial at a time; denied with a job. M906 stays within the current cap of the profile. Making it "
               "permanent is machine.config.plan (keep answers with the kind and values to use).",
               motion="geometry", confirm={"level": 3, "key": "machine.try"}, exclusive=False)]
