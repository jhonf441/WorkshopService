"""
audit_reads -- which reads that SUCCEED are recorded (phase 4, PLAN-ACCESO.md 4.2): by category, off by default, sampled and capped per day.

The switches, the sampling and the cap are in audit_settings.py (key "audit" of the service settings). The category of an operation comes from
its capability (permission_caps): camera and config by the category of the capability, audit by the capability security.audit. Sampling is a
plain counter (one of every `read_sample`, no randomness) and the day follows clock.wall(). Refused reads are never here: they are always recorded.
"""
import clock
import audit_settings
import permission_caps as caps

_counters = {}  # category -> reads seen
_day = {"key": None, "recorded": {}}


def category_of(op_name):
    """The read category of an operation ("camera", "audit", "config") or None."""
    cid = caps.capability_of(op_name)
    if cid is None:
        return None
    if cid == "security.audit":
        return "audit"
    cat = caps.CAPABILITIES[cid]["category"]
    return cat if cat in ("camera", "config") else None


def admit(op_name):
    """True when a read that succeeded must be recorded: its category is on, it is the one of every `read_sample`, and the daily cap of the
    category is not used up."""
    cat = category_of(op_name)
    s = audit_settings.get()
    if cat is None or not s["reads"].get(cat):
        return False
    n = _counters[cat] = _counters.get(cat, 0) + 1
    if (n - 1) % s["read_sample"]:
        return False
    day = int(clock.wall() // 86400)
    if _day["key"] != day:
        _day["key"], _day["recorded"] = day, {}
    if _day["recorded"].get(cat, 0) >= s["read_daily_cap"]:
        return False
    _day["recorded"][cat] = _day["recorded"].get(cat, 0) + 1
    return True


def reset():
    _counters.clear()
    _day["key"], _day["recorded"] = None, {}
