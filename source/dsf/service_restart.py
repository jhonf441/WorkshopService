"""
Restart of the whole service from the Services page (processes redesign, phase 3, op service.restart).

The service is a DSF plugin process: ending it with a NON-ZERO exit code is a crash for DSF, and sbcAutoRestart (plugin.json) brings it
back. That is the same road the interception watchdog takes (main.py: intercept_watchdog.InterceptWatchdog(..., lambda: os._exit(1))). A
SIGTERM is NOT used: DSF reads it as "stopped on purpose" and does not revive the plugin.

While it restarts (a few seconds) the protections are off: the code interception, the laser guard, the black box, the status lights. So it is
refused unless the machine is at rest. `blockers()` is pure (every reading is an injected getter); `request()` answers first and, in a short
delay thread, runs the clean part of main's shutdown (a callback main passes in with configure(): the same helper _handle_shutdown uses) and
then the exit function. The exit function is injectable too, so a test never ends its own process.
"""
import os
import threading
import time

from messages import M

DELAY_S = 1.0           # the answer reaches the page before the process goes down
IDLE_STATUSES = ("idle", "off")

_lock = threading.Lock()
_state = {"pending": False, "thread": None}
_cfg = {"cleanup": None, "exit": None, "log": print}


def exit_process():
    """Really ends the process: non-zero, like the interception watchdog's exit function (DSF sees a crash and revives the plugin)."""
    os._exit(1)


def configure(cleanup=None, exit_fn=None, log=None):
    """main.py: cleanup() = the clean part of its shutdown. Tests: exit_fn (never the real one)."""
    _cfg["cleanup"] = cleanup
    _cfg["exit"] = exit_fn
    if log is not None:
        _cfg["log"] = log


def reset():
    """For tests."""
    with _lock:
        _state.update(pending=False, thread=None)
    _cfg.update(cleanup=None, exit=None, log=print)


# ---- default readings (all from memory: nothing is asked of DSF) ----

def _model():
    import machine_state
    return machine_state.last_state() or {}


def default_status():
    return ((_model().get("state") or {}).get("status")) or None


def default_job():
    import job_states
    import live_job
    return live_job.read_in() is not None or default_status() in job_states.ACTIVE


def default_laser():
    import laser_guard
    pwm = (_model().get("state") or {}).get("laserPwm")
    return bool(laser_guard.armed() or (isinstance(pwm, (int, float)) and pwm > 0))


def default_motion(bridge=None):
    """Who owns the movement (text) or None: a reservation, a jog gesture, or the G-code bridge sending orders."""
    import motion_owner
    snap = motion_owner.snapshot(bridge)
    owner = snap.get("owner")
    if owner:
        return str(owner.get("origin") or "?")
    if (snap.get("bridge") or {}).get("active"):
        return "bridge"
    return None


def default_alarm():
    """A protection of the guard is down right now (protection_guard.status(); a guard that is merely stale is not an alarm here)."""
    import protection_guard
    st = protection_guard.status()
    return bool(st and st.get("degraded"))


def default_getters(bridge=None):
    return {"status": default_status, "job": default_job, "laser": default_laser, "motion": lambda: default_motion(bridge),
            "alarm": default_alarm}


# ---- the decision ----

def blockers(getters):
    """List of {"code", "message"} (message: an es/en M) for everything that forbids the restart now; [] = allowed. A reading that fails
    counts as blocking (fail closed). getters: status() -> str|None, job() -> bool, laser() -> bool, motion() -> None|str, alarm() -> bool."""
    out = []

    def read(name, default_block):
        try:
            return getters[name]()
        except Exception:  # noqa: BLE001
            return default_block

    status = read("status", None)
    if status is None:
        out.append({"code": "status_unknown", "message": M("service_restart_block_status_unknown")})
    elif status not in IDLE_STATUSES:
        out.append({"code": "status", "message": M("service_restart_block_status", status=status)})
    if read("job", True):
        out.append({"code": "job", "message": M("service_restart_block_job")})
    if read("laser", True):
        out.append({"code": "laser", "message": M("service_restart_block_laser")})
    who = read("motion", "?")
    if who:
        out.append({"code": "motion", "message": M("service_restart_block_motion", who=who)})
    if read("alarm", True):
        out.append({"code": "alarm", "message": M("service_restart_block_alarm")})
    return out


def _run(getters, delay_s):
    try:
        time.sleep(delay_s)
        again = blockers(getters)  # something may have started during the delay: then it does not go down
        if again:
            _cfg["log"]("service restart cancelled: " + "; ".join(r["code"] for r in again))
            return
        cleanup = _cfg["cleanup"]
        if cleanup is not None:
            try:
                cleanup()
            except Exception as e:  # noqa: BLE001 - the exit must happen whatever the cleanup does
                _cfg["log"](f"service restart: cleanup failed: {e}")
        (_cfg["exit"] or exit_process)()
    finally:
        with _lock:
            _state["pending"] = False


def request(bridge=None, getters=None, delay_s=None):
    """(reasons, started): reasons is [] when allowed. When allowed, a thread does the cleanup and the exit after delay_s (default DELAY_S);
    a second request while one is pending starts nothing (the exit happens once)."""
    getters = getters or default_getters(bridge)
    delay_s = DELAY_S if delay_s is None else delay_s
    reasons = blockers(getters)
    if reasons:
        return reasons, False
    with _lock:
        if _state["pending"]:
            return [], False
        _state["pending"] = True
        t = threading.Thread(target=_run, args=(getters, delay_s), name="service-restart", daemon=True)
        _state["thread"] = t
    t.start()
    return [], True


def thread():
    """For tests: the thread of the last accepted request."""
    return _state["thread"]
