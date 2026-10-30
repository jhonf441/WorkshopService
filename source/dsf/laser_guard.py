"""Keeps a laser power that nobody turned off from marking the work.

A program that sends `M3 S...` or `G1 ... S12.5` and leaves (it was cancelled, the connection dropped, the final M5 timed out, the first move was refused
because the axes were not homed) leaves the power set, and the next G1 without its own S (the jog buttons of DWC, a macro) fires the laser along the way
(seen 2026-10-18; the bridge log of 10-14 has final M5 that timed out). The guard is ARMED by anything that can leave the power set: an M3 / M4 seen by the
interceptor, any order of the bridge, or a laser power above zero in the object model. It says when the power has to be turned off: armed and, for HOLD_S
seconds in a row, the machine is idle, no live job is open and the bridge has been quiet for BRIDGE_QUIET_S seconds. An M5 (seen by the interceptor)
disarms it. Pure logic: main.py feeds it and sends the M5.
"""
import threading

HOLD_S = 5.0          # idle time before the M5
BRIDGE_QUIET_S = 10.0  # the bridge is not streaming (a program that is still sending must not be cut)

_lock = threading.Lock()
_state = {"armed": False, "since": None, "armed_at": None}


def note(code_key, now):
    """code_key: "M3", "M4" or "M5" as the interceptor reads them."""
    with _lock:
        if code_key in ("M3", "M4"):
            _state["armed"] = True
            _state["armed_at"] = now
            _state["since"] = None
        elif code_key == "M5":
            _state["armed"] = False
            _state["since"] = None


def arm(now):
    """Something that can leave the power set was seen (bridge activity, power above zero)."""
    note("M3", now)


def armed():
    with _lock:
        return _state["armed"]


def decide(now, status, live_job_open, bridge_quiet_s):
    """True when the power has to be turned off now (and the guard is disarmed: the caller sends the M5).
    status: the machine status ("idle", "busy", "processing"...). bridge_quiet_s: seconds since the last order of the bridge, None if never."""
    with _lock:
        if not _state["armed"]:
            return False
        quiet = bridge_quiet_s is None or bridge_quiet_s >= BRIDGE_QUIET_S
        if status != "idle" or live_job_open or not quiet:
            _state["since"] = None
            return False
        if _state["since"] is None:
            _state["since"] = now
            return False
        if now - _state["since"] >= HOLD_S:
            _state["armed"] = False
            _state["since"] = None
            return True
        return False


def rearm():
    """The M5 could not be sent: try again at the next check."""
    with _lock:
        _state["armed"] = True


def reset():
    with _lock:
        _state.update({"armed": False, "since": None, "armed_at": None})
