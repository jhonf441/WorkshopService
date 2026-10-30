"""Input shaping of Machine v2 (phase 3, design 2.8): `machine.shaping.get` and `machine.shaping.test`.

machine.shaping.get    (operator, read only) the shaper the board has now (move.shaping), the types the service can set, the M593 lines of the
                       configuration and whether an accelerometer is there (capabilities `accelerometers`, from sensors.accelerometers). The tolerant
                       reading: a key the firmware did not report is null.
machine.shaping.test   (technician, returns TEXT only) a ringing-test G-code: squares at several accelerations. It is never sent to the board; the
                       person runs it as a job. Then counts the ripples on the part and enters them in machine.calc `ringing` (frequency) -> a plan of kind
                       `config.m593` or a trial `machine.try` M593. The accelerometer path is the run kind `shaping.tune` (machine_tune.py), refused
                       without an accelerometer.

Setting the shaper is `machine.config.plan` kind `config.m593` (file) or `machine.try` M593 (volatile, auto revert). `custom` shapers are shown and never edited.
"""
import config_scan
import machine_geometry as geo
import machine_gcode
import machine_patch as pt
import machine_patch_motion as pm
from messages import M
from workshop_api import ApiError, Arg, READ, Op

TYPES = ("none", "zvd", "zvdd", "zvddd", "mzv", "ei2", "ei3")
MIN_FREQUENCY_HZ = 4
MARGIN_MM = 5.0
DEFAULT_ACCELS = (500, 1000, 2000)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def current_shaper(om):
    """{"type", "frequency", "damping", "amplitudes", "delays", "min_acceleration"} or None when the model has no move.shaping."""
    s = ((om or {}).get("move") or {}).get("shaping")
    if not isinstance(s, dict):
        return None
    delays = s.get("delays") if isinstance(s.get("delays"), list) else s.get("durations")
    nums = lambda v: [x for x in (_num(i) for i in v) if x is not None] if isinstance(v, list) else None          # noqa: E731
    return {"type": str(s["type"]).lower() if isinstance(s.get("type"), str) else None, "frequency": _num(s.get("frequency")),
            "damping": _num(s.get("damping")), "amplitudes": nums(s.get("amplitudes")), "delays": nums(delays),
            "min_acceleration": _num(s.get("minAcceleration"))}


def accelerometer_view(caps):
    c = ((caps or {}).get("capabilities") or {}).get("accelerometers") or {}
    return {"present": bool(c.get("present")), "source": c.get("source"), "count": c.get("count") or 0, "items": list(c.get("items") or [])}


def definitions(read):
    out = []
    scan = config_scan.scan(read)
    for path in scan["files"]:
        for n, raw in enumerate(str(read(path) or "").splitlines(), 1):
            code = pt.split_comment(raw)[0]
            if pt.command_word(code)[0] == "M593":
                out.append({"file": path, "line": n, "text": code.strip()[:160]})
    return out


def shaping_view(om, caps, read):
    cur = current_shaper(om)
    warnings = []
    if cur and cur["type"] == "custom":
        warnings.append("custom_shaper")
    if cur and cur["type"] not in (None, "none"):
        warnings.append("retune_pressure_advance")
    return {"available": cur is not None, "current": cur, "types": list(TYPES), "min_frequency_hz": MIN_FREQUENCY_HZ,
            "accelerometer": accelerometer_view(caps), "definitions": definitions(read), "warnings": warnings}


def _get(args, ctx):
    import machine_ops as mo
    return shaping_view(mo.model(), mo._caps(), mo.read_sd)


# ---- ringing test (text only) ----

def _axis_limits(om, letter):
    for a in ((om or {}).get("move") or {}).get("axes") or []:
        if isinstance(a, dict) and a.get("letter") == letter:
            lo, hi = geo.num(a.get("min")), geo.num(a.get("max"))
            if lo is not None and hi is not None and lo < hi:
                return lo, hi
    return None


def validate_test(args, om):
    """(clean params, reason or None, field). The square must fit inside the limits of the axes it moves, with a margin."""
    axes = args.get("axes") or "XY"
    size = args.get("size", 50)
    feed = args.get("feed", 6000)
    reps = args.get("repeats", 2)
    accels = list(DEFAULT_ACCELS if args.get("accels") is None else args["accels"])
    if axes not in ("X", "Y", "XY") or not all(not isinstance(v, bool) and isinstance(v, (int, float)) for v in (size, feed, reps)):
        return None, "bad_value", "axes"
    if not 10 <= size <= 200 or not 600 <= feed <= 30000 or not 1 <= reps <= 5 or int(reps) != reps:
        return None, "bad_value", "size" if not 10 <= size <= 200 else ("feed" if not 600 <= feed <= 30000 else "repeats")
    if not 1 <= len(accels) <= 6 or not all(not isinstance(a, bool) and isinstance(a, (int, float)) and 50 <= a <= 20000 for a in accels):
        return None, "bad_value", "accels"
    origin, lim = {}, {}
    for letter in "XY":
        lim[letter] = _axis_limits(om, letter)
        if lim[letter] is None:
            return None, "no_limits", letter
        key = "origin_" + letter.lower()
        o = args.get(key)
        o = lim[letter][0] + 20 if o is None else o
        if isinstance(o, bool) or not isinstance(o, (int, float)):
            return None, "bad_value", key
        origin[letter] = float(o)
    span = {"X": size if "X" in axes else 0, "Y": size if "Y" in axes else 0}
    for letter in "XY":
        lo, hi = lim[letter]
        if origin[letter] < lo + MARGIN_MM or origin[letter] + span[letter] > hi - MARGIN_MM:
            return None, "out_of_reach", letter
    return {"axes": axes, "origin_x": origin["X"], "origin_y": origin["Y"], "size": float(size), "feed": int(feed), "accels": [float(a) for a in accels],
            "repeats": int(reps)}, None, ""


def ringing_gcode(p):
    """The text of the ringing test. Only comments, G90, M400, M204 and G1 X/Y with S0 (rule of the workshop: every new G1 carries S0)."""
    ox, oy, size, feed = p["origin_x"], p["origin_y"], p["size"], p["feed"]
    t = machine_gcode.num_text
    x1, y1 = ox + (size if "X" in p["axes"] else 0), oy + (size if "Y" in p["axes"] else 0)
    out = ["; Ringing test for input shaping -- generated by Machine, it is NOT sent to the machine",
           "; %s mm %s at X%s Y%s, feed %d mm/min, %d laps at each acceleration: %s mm/s2" % (t(size), p["axes"], t(ox), t(oy), feed, p["repeats"],
                                                                                           ", ".join(t(a) for a in p["accels"])),
           "; Look at the corners of each lap: count the ripples after the corner, measure their distance, then use machine.calc ringing.",
           "G90", "M400", "G1 X%s Y%s F%d S0" % (t(ox), t(oy), feed)]
    path = [("X", x1)] * ("X" in p["axes"]) + [("Y", y1)] * ("Y" in p["axes"]) + [("X", ox)] * ("X" in p["axes"]) + [("Y", oy)] * ("Y" in p["axes"])
    for a in p["accels"]:
        out += ["; --- acceleration %s mm/s2" % t(a), "M204 P%s T%s" % (t(a), t(a))]
        for _ in range(p["repeats"]):
            out += ["G1 %s%s F%d S0" % (axis, t(pos), feed) for axis, pos in path]
        out.append("M400")
    out.append("; Put your own accelerations back (M204 / M201 of your mode file) before the next job.")
    return "\n".join(out) + "\n"


def _test(args, ctx):
    import machine_ops as mo
    clean, reason, field = validate_test(args, mo.model())
    if reason == "bad_value":
        raise ApiError("invalid_args", M("machine_shaping_bad_value", field=field), field=field, reason="bad_value")
    if reason:
        raise ApiError("refused", M("machine_shaping_" + reason, field=field), reason=reason, field=field)
    text = ringing_gcode(clean)
    return {"gcode": text, "lines": len(text.splitlines()), "params": clean, "notes": ["not_sent", "restore_acceleration", "count_ripples"]}


def ops():
    a = Arg
    return [
        Op("machine.shaping.get", _get, READ, {},
           "The input shaper of the board (move.shaping: type, frequency, damping, amplitudes, delays; null for what it did not report), the types that "
           "can be set, the M593 lines of the configuration and the accelerometer capability (present, source, items).", log=False),
        Op("machine.shaping.test", _test, READ,
           {"axes": a("str", choices=("X", "Y", "XY"), desc="Axes of the test (XY)."), "origin_x": a("num", desc="Start X (axis minimum + 20)."),
            "origin_y": a("num", desc="Start Y (axis minimum + 20)."), "size": a("num", desc="Side of the square in mm, 10-200 (50)."),
            "feed": a("int", desc="Speed in mm/min, 600-30000 (6000)."), "accels": a("obj", desc="1-6 accelerations in mm/s2, 50-20000 (500, 1000, 2000)."),
            "repeats": a("int", desc="Laps at each acceleration, 1-5 (2).")},
           "Generates the G-code of a ringing test (squares at several accelerations) as TEXT. It is never sent to the machine: save it and run it as "
           "a job. Refused when the square does not fit inside the limits of the axes.", log=False),
    ]
