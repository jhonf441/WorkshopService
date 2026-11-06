"""Bed split in zones: turns the M140 / M190 a slicer sends (no P) into one M140 per zone.

RRF cannot group heaters in one bed (M140 P0 H0:1 does not work) and slicers send `M140 S60` with no P, which only reaches bed 0. The
service intercepts M140 / M190 and, when there is no P, replaces them with `M140 P<bed> S<setpoint + offset>` for every active zone. With a P the
code goes through untouched; so does one that names its heaters with H (a slicer that sends one `M140 S.. H<n>` per zone: an explicit order). Setpoint 0 or -273.15 turns every active zone off.

Pure logic, no I/O: bed_zones_intercept.py feeds it the code and the object model and sends what it returns. The PID and the protections
(M143, heater faults) stay in the firmware: nothing here closes a loop, it only computes setpoints and says when the zones have arrived.

Config (a plain dict, validated by the caller):
    zones:      [{"bed": <M140 P number>, "active": bool, "offset": <C>}, ...]
    max_temp:   highest setpoint any zone may get, in C
    max_offset: highest absolute offset, in C
    tolerance:  how far from its target a zone may be and still count as arrived, in C
    timeout_s:  longest M190 wait, in seconds
"""
import math

OFF = -273.15       # RRF: a temperature near absolute zero turns the heater off
OFF_BELOW = -273.0  # a setpoint at or under this is a request to turn off

DEFAULTS = {
    "zones": [{"bed": i, "active": True, "offset": 0.0} for i in range(4)],
    "max_temp": 110.0,
    "max_offset": 15.0,
    "tolerance": 2.0,
    "timeout_s": 600.0,
}

# result of translate()
PASS = "pass"    # not ours: let the code through
SET = "set"      # replace it with `codes`
ERROR = "error"  # refuse it: `error` is a key, `params` its values

# result of progress()
WAITING = "waiting"
REACHED = "reached"
TIMEOUT = "timeout"
FAULT = "fault"


def _number(value):
    """A finite float, or None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value):
    """Temperature as RRF reads it: no trailing zeros ("60", "62.5", "-273.15")."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def active_zones(config):
    return [z for z in config.get("zones", []) if z.get("active")]


def zone_target(setpoint, zone, config):
    """Setpoint of one zone for a global setpoint, or a (key, params) error. Returns (value, None) or (None, (key, params))."""
    max_temp = config["max_temp"]
    if setpoint <= OFF_BELOW:
        return OFF, None
    offset = _number(zone.get("offset", 0.0))
    if offset is None or abs(offset) > config["max_offset"]:
        return None, ("bed_zones_offset_out_of_range", {"bed": zone.get("bed"), "max": config["max_offset"]})
    if setpoint == 0:
        return OFF, None
    target = max(setpoint + offset, 0.0)
    if target > max_temp:
        return None, ("bed_zones_over_max", {"bed": zone.get("bed"), "target": _fmt(target), "max": _fmt(max_temp)})
    return target, None


def translate(code_key, params, config):
    """What to do with an intercepted code.

    code_key: "M140" or "M190". params: the letters of the code as a dict, upper case keys ("S": "60", "P": "1"); a letter that
    is absent is not in the dict. Returns a dict {"action": PASS | SET | ERROR, "codes": [...], "wait": bool, "targets": {bed: C},
    "error": key, "params": {...}}.
    """
    if code_key not in ("M140", "M190"):
        return {"action": PASS}
    if params.get("P") not in (None, ""):
        return {"action": PASS}  # the user chose a bed: not ours
    if params.get("H") not in (None, ""):
        return {"action": PASS}  # the code names its heaters (a slicer that sends one M140 S.. H<n> per zone): an explicit order, the firmware reads it as written
    if params.get("S") in (None, ""):
        return {"action": PASS}  # no setpoint (M140 R.. or a query): the firmware answers it
    setpoint = _number(params.get("S"))
    if setpoint is None:
        return {"action": ERROR, "error": "bed_zones_invalid_setpoint", "params": {"value": str(params.get("S"))}}
    zones = active_zones(config)
    if not zones:
        return {"action": PASS}  # nothing configured: behave like the firmware alone
    targets = {}
    for zone in zones:
        target, error = zone_target(setpoint, zone, config)
        if error:
            return {"action": ERROR, "error": error[0], "params": error[1]}
        targets[zone["bed"]] = target
    codes = [f"M140 P{bed} S{_fmt(target)}" for bed, target in targets.items()]
    off = all(t == OFF for t in targets.values())
    return {"action": SET, "codes": codes, "targets": targets, "off": off, "wait": code_key == "M190" and not off}


def progress(targets, temps, elapsed_s, config, faults=()):
    """State of an M190 wait.

    targets: {bed: C} from translate(). temps: {bed: current C or None}. faults: beds the firmware reports in fault.
    Returns {"state": WAITING | REACHED | TIMEOUT | FAULT, "pending": [beds that have not arrived], "fault": [beds]}.
    A fault wins over everything (the caller must answer the code with an error); a missing reading is "not arrived".
    """
    bad = [bed for bed in targets if bed in faults]
    if bad:
        return {"state": FAULT, "pending": sorted(targets), "fault": sorted(bad)}
    pending = []
    for bed, target in targets.items():
        if target == OFF:
            continue  # a zone that is off is not waited for
        now = _number(temps.get(bed))
        if now is None or now < target - config["tolerance"]:
            pending.append(bed)
    if not pending:
        return {"state": REACHED, "pending": [], "fault": []}
    if elapsed_s >= config["timeout_s"]:
        return {"state": TIMEOUT, "pending": sorted(pending), "fault": []}
    return {"state": WAITING, "pending": sorted(pending), "fault": []}


def zone_code(bed, temperature, config):
    """The M140 for ONE zone chosen by hand (the setpoint of one zone on the page). No offset is added: the number typed is the setpoint of that zone.
    Returns (code, None) or (None, (key, params)). Off (0, -273.15 or lower) is always accepted; the zone must be a configured one."""
    if bed not in [z.get("bed") for z in config.get("zones", [])]:
        return None, ("bed_zones_unknown_zone", {"bed": bed})
    value = _number(temperature)
    if value is None or OFF_BELOW < value < 0:
        return None, ("bed_zones_invalid_setpoint", {"value": str(temperature)})
    if value <= OFF_BELOW or value == 0:
        return f"M140 P{bed} S{_fmt(OFF)}", None
    if value > config["max_temp"]:
        return None, ("bed_zones_over_max", {"bed": bed, "target": _fmt(value), "max": _fmt(config["max_temp"])})
    return f"M140 P{bed} S{_fmt(value)}", None


def off_codes(config):
    """One M140 per CONFIGURED zone (active or not) that turns it off: a stop must reach every zone."""
    return [f"M140 P{z['bed']} S{_fmt(OFF)}" for z in config.get("zones", [])]


def deviation(target, current, config):
    """True when a zone that is heating or holding is further from its target than the tolerance (to show an alert, not to act)."""
    if target is None or target == OFF:
        return False
    now = _number(current)
    return now is not None and abs(now - target) > config["tolerance"]
