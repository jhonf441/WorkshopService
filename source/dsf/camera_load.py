"""Load of the Pi seen by the camera relay: it MEASURES nothing, it reads what the service already publishes.

Before, camera_relay.py read the temperature and the CPU on its own and sent its own phone notice, overlapping PiHealth
(health_poller.py, which measures them and warns about a hot CPU). Now:
  - temperature and CPU come from the `healthPi` data of health_poller (reading()); stale data counts as "unknown", never as zero;
  - the relay only adds what is its own: the kB/s it sends out;
  - the level (0 normal, 1 loaded: fewer frames to remote screens, 2 critical: 2 screens per camera) is decided here (step());
  - a notice about heat alone is not sent (PiHealth sends it); the relay still lowers its frames because of it (notify_worthy()).
The notice itself goes out as before: activity.log_event() records it and calls notifier.notify_event() (same channels, types and
quiet hours as every other notice); the 10 minutes between two notices of the same kind are kept here (notice_due()).
"""
import time

from messages import M, J

HEALTH_KEY = "healthPi"
MAX_AGE_S = 90           # health_poller publishes every ~10 s; older than this is not a reading
TEMP_LOADED_C = 75
TEMP_CRITICAL_C = 80
CPU_LOADED = 92
CRITICAL_AFTER_S = 60    # loaded this long without improving becomes critical
RELAX_AFTER_S = 30       # to go down a level, this long without load
NOTICE_GAP_S = 600       # between two notices (a critical one always goes out)


def new_state():
    return {"level": 0, "since": 0.0, "low_since": 0.0, "temp": None, "cpu": None, "kbps": 0.0, "reason": "", "notice": 0.0}


def reading(published, now=None):
    """(temp_c, cpu_pct) from the `healthPi` data in `published` (bridge.payload), (None, None) when missing or stale."""
    d = (published or {}).get(HEALTH_KEY)
    if not isinstance(d, dict):
        return None, None
    stamp = d.get("updated_at")
    try:
        age = (now if now is not None else time.time()) - time.mktime(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError, OverflowError):
        return None, None
    if abs(age) > MAX_AGE_S:
        return None, None
    cpu = d.get("cpu") if isinstance(d.get("cpu"), dict) else {}
    return _num(cpu.get("temp_c")), _num(cpu.get("use_pct"))


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def reasons_of(temp, cpu, kbps, kbps_limit):
    """List of (code, message) that make the Pi loaded."""
    out = []
    if temp is not None and temp >= TEMP_LOADED_C:
        out.append(("temp", M("cam_load_temp", t=temp)))
    if cpu is not None and cpu >= CPU_LOADED:
        out.append(("cpu", M("cam_load_cpu", cpu=cpu)))
    if kbps >= kbps_limit:
        out.append(("kbps", M("cam_load_kbps", kbps=kbps)))
    return out


def step(state, temp, cpu, kbps, kbps_limit, t):
    """Updates `state` with one measurement. Returns (old_level, new_level, reasons)."""
    reasons = reasons_of(temp, cpu, kbps, kbps_limit)
    critical = (temp is not None and temp >= TEMP_CRITICAL_C) or (reasons and state["level"] >= 1 and t - state["since"] > CRITICAL_AFTER_S)
    level = 2 if critical else (1 if reasons else 0)
    old = state["level"]
    if level < old:
        if not state["low_since"]:
            state["low_since"] = t
        if t - state["low_since"] < RELAX_AFTER_S:
            level = old
    else:
        state["low_since"] = 0.0
    state.update(temp=temp, cpu=round(cpu) if cpu is not None else None, kbps=round(kbps, 1), reason=J([m for _, m in reasons]))
    if level != old:
        if level > old:
            state["since"] = t
        state["level"] = level
    return old, level, reasons


def notify_worthy(reasons):
    """False when the only cause is the temperature: PiHealth already sends that notice."""
    return not reasons or any(code != "temp" for code, _ in reasons)


def notice_due(state, level, t):
    """True when a notice of this change may go out now (and remembers it). A critical one always goes out."""
    if t - state["notice"] > NOTICE_GAP_S or level == 2:
        state["notice"] = t
        return True
    return False
