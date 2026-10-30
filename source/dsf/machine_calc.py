"""Calibration arithmetic of Machine v2 (phase 3, design 2.6): steps per mm, skew from the diagonals, backlash, ringing frequency.

Pure functions first (numeric tests in test_machine_calc.py), then the operation `machine.calc`. Nothing here talks to the board: the result
carries the G-code line the change would be (`line`) and the `plan` (kind + values) that `machine.config.plan` takes to write it.

steps    new = old * commanded / measured, rounded to 3 places; a correction outside 0.5-2 is refused (a typing mistake, not a calibration)
skew     two diagonals of a square of nominal side S. With equal sides sin(d) = (diag_diff^2 - diag_sum^2) / (4 S^2): positive = obtuse
         (the firmware convention of M556). The value for M556 is the deviation S * tan(d); XY goes to X, YZ to Y, ZX to Z.
backlash lost motion samples (mm) -> the mean is the proposal for M425, with the warning that M425 is for FIXED backlash only
ringing  frequency (Hz) = speed (mm/s) * ripples / distance (mm): the manual entry of the input shaper
"""
import math

import identity
import machine_gcode
import machine_store
from messages import M
from workshop_api import ApiError, Arg, WRITE, Op

AXIS_LETTERS = "XYZUVWABC"
CALCS = ("steps", "skew", "backlash", "ringing")
PAIRS = {"XY": "X", "YZ": "Y", "ZX": "Z"}
MAX_SKEW_DEG = 3.0
MIN_RATIO, MAX_RATIO = 0.5, 2.0
LARGE_RATIO = (0.9, 1.1)
MAX_BACKLASH_SAMPLE = 2.0
BIG_BACKLASH = 0.5
MIN_FREQUENCY, HIGH_FREQUENCY = 4.0, 200.0


class CalcError(ValueError):
    """Invalid input (`bad_value`, with .field) or a result that cannot be right (`out_of_range`, `implausible`, `no_value`)."""

    def __init__(self, code, field=""):
        super().__init__(code)
        self.code, self.field = code, field


def _num(values, key, lo, hi, required=True):
    v = values.get(key)
    if v is None and not required:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        raise CalcError("bad_value", key)
    return float(v)


def _letter(values, letters):
    a = values.get("axis")
    if not isinstance(a, str) or len(a) != 1 or a.upper() not in letters:
        raise CalcError("bad_value", "axis")
    return a.upper()


def _t(v, places=3):
    return machine_gcode.num_text(v, places)


# ---- steps per mm ----

def steps_per_mm(old, commanded, measured):
    """(new, ratio): the corrected steps/mm. CalcError out_of_range when the ratio is outside 0.5-2."""
    ratio = commanded / measured
    if not MIN_RATIO <= ratio <= MAX_RATIO:
        raise CalcError("out_of_range", "measured")
    new = round(old * ratio, 3)
    if not 0.01 <= new <= 99999:
        raise CalcError("out_of_range", "old")
    return new, ratio


def calc_steps(values, om):
    axis = _letter(values, AXIS_LETTERS + "E")
    commanded, measured = _num(values, "commanded", 1, 5000), _num(values, "measured", 0.001, 50000)
    old = _num(values, "old", 0.01, 99999, required=False)
    if old is None:
        old = current_steps(om, axis)
    if old is None:
        raise CalcError("no_value", "old")
    new, ratio = steps_per_mm(old, commanded, measured)
    warnings = ["microstepping_note"] + (["large_correction"] if not LARGE_RATIO[0] <= ratio <= LARGE_RATIO[1] else [])
    return {"axis": axis, "old": old, "commanded": commanded, "measured": measured, "ratio": round(ratio, 6), "new": new,
            "change_pct": round((ratio - 1) * 100, 3), "line": "M92 %s%s" % (axis, _t(new)), "warnings": warnings,
            "plan": {"kind": "config.m92", "values": {"axes": {axis: new}}}}


def current_steps(om, axis):
    mv = (om or {}).get("move") or {}
    row = None
    if axis == "E":
        row = (mv.get("extruders") or [None])[0]
    else:
        row = next((a for a in mv.get("axes") or [] if isinstance(a, dict) and a.get("letter") == axis), None)
    v = row.get("stepsPerMm") if isinstance(row, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


# ---- skew ----

def skew_from_diagonals(side, diag_sum, diag_diff):
    """(angle in degrees, tangent, deviation mm): positive = obtuse. CalcError implausible when it cannot be a square of that side."""
    nominal = side * math.sqrt(2)
    if abs(diag_sum - nominal) > 0.15 * nominal or abs(diag_diff - nominal) > 0.15 * nominal:
        raise CalcError("implausible", "diag_sum")
    s = (diag_diff ** 2 - diag_sum ** 2) / (4 * side ** 2)
    if abs(s) > math.sin(math.radians(MAX_SKEW_DEG)):
        raise CalcError("implausible", "diag_diff")
    angle = math.asin(s)
    tan = math.tan(angle)
    return math.degrees(angle), tan, side * tan


def calc_skew(values, om):
    pair = values.get("pair")
    if pair not in PAIRS:
        raise CalcError("bad_value", "pair")
    side = _num(values, "side", 10, 1000)
    d_sum, d_diff = _num(values, "diag_sum", 1, 3000), _num(values, "diag_diff", 1, 3000)
    angle, tan, dev = skew_from_diagonals(side, d_sum, d_diff)
    letter = PAIRS[pair]
    dev3 = round(dev, 3)
    warnings = ["negligible"] if dev3 == 0 else []
    return {"pair": pair, "side": side, "diag_sum": d_sum, "diag_diff": d_diff, "angle_deg": round(angle, 4), "tan": round(tan, 6),
            "deviation": dev3, "letter": letter, "line": "M556 S%s %s%s" % (_t(side), letter, _t(dev3)), "warnings": warnings,
            "plan": {"kind": "config.m556", "values": {"s": side, letter.lower(): dev3}}}


# ---- backlash ----

def backlash_stats(samples):
    n = len(samples)
    mean = sum(samples) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in samples) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": mean, "stdev": sd, "min": min(samples), "max": max(samples)}


def calc_backlash(values, om):
    axis = _letter(values, AXIS_LETTERS)
    raw = values.get("samples")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
        raise CalcError("bad_value", "samples")
    samples = [_sample(v) for v in raw]
    mult = _num(values, "multiplier", 1, 100, required=False)
    st = backlash_stats(samples)
    proposal = round(st["mean"], 3)
    warnings = ["fixed_backlash_only", "not_in_g32"]
    if st["n"] > 1 and (st["stdev"] > 0.35 * st["mean"] or st["max"] - st["min"] > 0.5 * st["mean"]) and st["mean"] > 0:
        warnings.append("inconsistent")
    if proposal > BIG_BACKLASH:
        warnings.append("big_backlash")
    if proposal == 0:
        warnings.append("zero")
    kin = str((((om or {}).get("move") or {}).get("kinematics") or {}).get("name") or "").lower()
    if kin and kin != "cartesian":
        warnings.append("per_motor")
    line = "M425 %s%s" % (axis, _t(proposal)) + (" S%s" % _t(mult) if mult is not None else "")
    plan_values = {"axes": {axis: proposal}}
    if mult is not None:
        plan_values["multiplier"] = mult
    return {"axis": axis, "n": st["n"], "mean": round(st["mean"], 4), "stdev": round(st["stdev"], 4), "min": st["min"], "max": st["max"],
            "proposal": proposal, "multiplier": mult, "line": line, "warnings": warnings, "plan": {"kind": "config.m425", "values": plan_values}}


def _sample(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= MAX_BACKLASH_SAMPLE:
        raise CalcError("bad_value", "samples")
    return float(v)


# ---- ringing frequency ----

def ringing_frequency(feed_mm_min, ripples, distance):
    """Hz: the tool crosses `ripples` ripples while travelling `distance` mm at `feed`."""
    speed = feed_mm_min / 60.0
    return speed * ripples / distance, distance / ripples, speed


def calc_ringing(values, om):
    feed, ripples, dist = _num(values, "feed", 60, 60000), _num(values, "ripples", 2, 200), _num(values, "distance", 1, 1000)
    hz, wavelength, speed = ringing_frequency(feed, ripples, dist)
    warnings = (["below_minimum"] if hz < MIN_FREQUENCY else []) + (["very_high"] if hz > HIGH_FREQUENCY else [])
    f = round(hz, 2)
    return {"frequency_hz": f, "wavelength_mm": round(wavelength, 3), "speed_mm_s": round(speed, 3), "warnings": warnings,
            "plan": {"kind": "config.m593", "values": {"frequency": f}}}


CALCULATORS = {"steps": calc_steps, "skew": calc_skew, "backlash": calc_backlash, "ringing": calc_ringing}
REFUSED = ("out_of_range", "implausible", "no_value")


# ---- operation ----

def _op(args, ctx):
    import machine_ops as mo
    name, values = args["calc"], args.get("values")
    if not isinstance(values, dict):
        raise ApiError("invalid_args", M("machine_calc_bad_value", field="values"), field="values", reason="bad_value")
    try:
        out = dict(CALCULATORS[name](values, mo.model()), calc=name)
    except CalcError as e:
        if e.code in REFUSED:
            raise ApiError("refused", M("machine_calc_" + e.code, field=e.field), reason=e.code, field="values." + e.field)
        raise ApiError("invalid_args", M("machine_calc_bad_value", field=e.field), field="values." + e.field, reason="bad_value")
    out["record_id"] = _save(name, values, out, args, ctx, mo) if args.get("save") else None
    return out


def _save(name, values, out, args, ctx, mo):
    try:
        rec = machine_store.make_record("calc." + name, identity.actor(ctx), machine=machine_store.fingerprint_of(mo._caps()), inputs=values,
                                        results={k: v for k, v in out.items() if k != "calc"}, notes=str(args.get("note") or ""), state="done")
        return machine_store.append(rec)["id"]
    except machine_store.StoreError as e:
        raise ApiError("failed", M("machine_calc_store_failed", reason=e.code))


def ops():
    a = Arg
    return [Op("machine.calc", _op, WRITE,
               {"calc": a("str", True, choices=CALCS, desc="steps (new = old * commanded / measured), skew (from the two diagonals of a square), "
                                                            "backlash (from samples of lost motion) or ringing (frequency from the ripples)."),
                "values": a("obj", True, desc="steps: {axis, commanded, measured, old?}. skew: {pair XY|YZ|ZX, side, diag_sum, diag_diff}. "
                                              "backlash: {axis, samples: [mm], multiplier?}. ringing: {feed mm/min, ripples, distance mm}."),
                "save": a("bool", desc="Store the result in the calibration history (kind calc.<calc>)."), "note": a("str", desc="Free note up to 500 characters.")},
               "Arithmetic of the calibration assistants: it sends nothing to the board. Returns the new value, the G-code line it would be, the "
               "warnings and the plan (kind + values) for machine.config.plan.")]
