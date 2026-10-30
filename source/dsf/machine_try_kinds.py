"""What each `gcode_kind` of machine.try knows (Machine v2, phase 3): how to check its values, where the previous value is in the object model, and
which lines of the closed list (machine_gcode.py) say it. machine_try.py does the timer, the pending file and the one-trial-at-a-time rule.

A kind is a `Kind(clean, previous, lines, persist)`:
    clean(values, env)     -> `applied` (a dict that is stored and returned); machine_config.PlanError for a value that is not valid
    previous(om, applied)  -> the SAME shape with what the board has now, or None when the model does not say (the trial is refused: no way back)
    lines(d)               -> [(template, numbers)] that put `d` (applied or previous) on the board
    persist(applied)       -> (plan kind, values) to make the trial permanent through machine.config.plan

Shapes: M208 keeps the phase 2 shape `{"X": {"min", "max"}}`; the other kinds use the `values` of the plan of the same kind (`{"axes": {...}}`,
`{"s", "x", "y", "z"}`, `{"type", "frequency", "damping"}`). The current limit of M906 is checked here too (profile cap, hard ceiling).
"""
import machine_config as mc
import machine_plans as plans
import machine_plans_motion as pmo
import machine_profile

ALL = pmo.ALL
IDLE_PERCENT, IDLE_TIMEOUT = "idle_percent", "idle_timeout"


class Kind:
    def __init__(self, clean, previous, lines, persist):
        self.clean, self.previous, self.lines, self.persist = clean, previous, lines, persist


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _row(om, letter):
    mv = (om or {}).get("move") or {}
    if letter == "E":
        rows = mv.get("extruders") or []
        return rows[0] if rows and isinstance(rows[0], dict) else None
    return next((a for a in mv.get("axes") or [] if isinstance(a, dict) and a.get("letter") == letter), None)


def _axes_previous(om, letters, key):
    out = {}
    for c in letters:
        row = _row(om, c)
        v = _num(row.get(key)) if isinstance(row, dict) else None
        if v is None:
            return None
        out[c] = v
    return out


# ---- M208 (phase 2) ----

def _clean_m208(values, env):
    return {c: {"min": lo, "max": hi} for c, (lo, hi) in plans._axis_map(values, "axes", plans._limit).items()}


def _previous_m208(om, applied):
    out = {}
    for c in applied:
        row = _row(om, c)
        lo, hi = (_num(row.get("min")), _num(row.get("max"))) if isinstance(row, dict) else (None, None)
        if lo is None or hi is None:
            return None
        out[c] = {"min": lo, "max": hi}
    return out


# ---- one value per axis ----

def axes_kind(config_kind, om_key, template, name, lo, hi, wait=False, letters=ALL, cap=False, extra=None):
    def clean(values, env):
        top = min(hi, machine_profile.current_cap(env.get("profile"))) if cap else hi
        new = plans._axis_map(values, "axes", lambda v, f: plans._number(v, lo, hi, f), letters)
        for c, v in new.items():
            if v > top:
                raise mc.PlanError("current_over_limit", "axes." + c)
        return {"axes": new}

    def previous(om, applied):
        prev = _axes_previous(om, applied["axes"], om_key)
        return None if prev is None else {"axes": prev}

    def lines(d):
        return ([("wait_moves", {})] if wait else []) + [(template, {"axis": c, name: v}) for c, v in d["axes"].items()]
    return Kind(clean, previous, lines, lambda applied: (config_kind, applied))


# ---- M906: currents and the idle values ----

def _clean_m906(values, env):
    out = {}
    if values.get("axes") is not None:
        out.update(axes_kind("config.m906", "current", "current_set", "v", 50, machine_profile.CURRENT_CEILING_MA, cap=True).clean(values, env))
    for key, lo, hi in ((IDLE_PERCENT, 0, 100), (IDLE_TIMEOUT, 1, 3600)):
        v = values.get(key)
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not lo <= v <= hi:
                raise mc.PlanError("bad_value", key)
            out[key] = int(v)
    if not out:
        raise mc.PlanError("bad_value", "values")
    return out


def _previous_m906(om, applied):
    out = {}
    if "axes" in applied:
        prev = _axes_previous(om, applied["axes"], "current")
        if prev is None:
            return None
        out["axes"] = prev
    idle = ((om or {}).get("move") or {}).get("idle")
    idle = idle if isinstance(idle, dict) else {}
    if IDLE_PERCENT in applied:
        f = _num(idle.get("factor"))
        if f is None:
            return None
        out[IDLE_PERCENT] = int(round(f * 100))
    if IDLE_TIMEOUT in applied:
        t = _num(idle.get("timeout"))
        if t is None or not 1 <= t <= 3600:
            return None
        out[IDLE_TIMEOUT] = int(t)
    return out


def _lines_m906(d):
    out = [("current_set", {"axis": c, "v": v}) for c, v in (d.get("axes") or {}).items()]
    if IDLE_PERCENT in d:
        out.append(("idle_percent_set", {"idle": d[IDLE_PERCENT]}))
    if IDLE_TIMEOUT in d:
        out.append(("idle_timeout_set", {"secs": d[IDLE_TIMEOUT]}))
    return out


# ---- M425 ----

def _clean_m425(values, env):
    out = axes_kind("config.m425", "backlash", "backlash_set", "v", 0, 2, letters=pmo.BACKLASH_LETTERS).clean(values, env)
    if values.get("multiplier") is not None:
        out["multiplier"] = plans._number(values["multiplier"], 1, 100, "multiplier")
    return out


def _previous_m425(om, applied):
    prev = _axes_previous(om, applied["axes"], "backlash")
    if prev is None:
        return None
    out = {"axes": prev}
    if "multiplier" in applied:
        f = _num(((om or {}).get("move") or {}).get("backlashFactor"))
        if f is None or not 1 <= f <= 100:
            return None
        out["multiplier"] = f
    return out


def _lines_m425(d):
    out = [("backlash_set", {"axis": c, "v": v}) for c, v in d["axes"].items()]
    return out + ([("backlash_factor", {"mult": d["multiplier"]})] if "multiplier" in d else [])


# ---- M556: skew (always sent as factors with S1) ----

SKEW_KEYS = (("x", "tanXY"), ("y", "tanYZ"), ("z", "tanXZ"))


def _current_skew(om):
    sk = (((om or {}).get("move") or {}).get("compensation") or {}).get("skew")
    sk = sk if isinstance(sk, dict) else {}
    vals = {k: _num(sk.get(tan)) for k, tan in SKEW_KEYS}
    return None if any(v is None for v in vals.values()) else vals


def _clean_m556(values, env):
    s = plans._number(values.get("s"), 1, 1000, "s") if values.get("s") is not None else None
    given = {k: plans._number(values[k], -100, 100, k) for k in "xyz" if values.get(k) is not None}
    if s is None or not given:
        raise mc.PlanError("bad_value", "s" if s is None else "values")
    cur = _current_skew(env.get("om"))
    if cur is None:
        raise mc.PlanError("no_previous", "skew")
    out = {"s": s}
    for k in "xyz":
        out[k] = given.get(k, round(cur[k] * s, 6))
        if abs(out[k]) > 0.1 * s:
            raise mc.PlanError("bad_value", k)
    return out


def _previous_m556(om, applied):
    cur = _current_skew(om)
    return None if cur is None else dict({"s": 1}, **cur)


def _lines_m556(d):
    return [("skew_set", {"fx": d["x"] / d["s"], "fy": d["y"] / d["s"], "fz": d["z"] / d["s"]})]


# ---- M593 ----

def _clean_m593(values, env):
    kind = values.get("type")
    if kind not in pmo.SHAPERS:
        raise mc.PlanError("bad_type", "type")
    out = {"type": kind}
    if kind != "none":
        if values.get("frequency") is None:
            raise mc.PlanError("no_frequency", "frequency")
        out["frequency"] = plans._number(values["frequency"], 4, 300, "frequency")
        out["damping"] = plans._number(values["damping"], 0, 0.99, "damping") if values.get("damping") is not None else 0.1
    return out


def _previous_m593(om, applied):
    sh = ((om or {}).get("move") or {}).get("shaping")
    if not isinstance(sh, dict):
        return None
    kind = str(sh.get("type") or "").lower()
    if kind == "none":
        return {"type": "none"}
    f = _num(sh.get("frequency"))
    d = _num(sh.get("damping"))
    if kind not in pmo.SHAPERS or f is None or not 4 <= f <= 300:       # a custom shaper (or an unknown one) cannot be put back from here
        return None
    return {"type": kind, "frequency": f, "damping": d if d is not None and 0 <= d <= 0.99 else 0.1}


def _lines_m593(d):
    if d["type"] == "none":
        return [("shaping_none", {})]
    return [("shaping_set", {"shaper": d["type"], "freq": d["frequency"], "damp": d["damping"]})]


def _make():
    kinds = {"M208": Kind(_clean_m208, _previous_m208, lambda d: [("limits_set", {"axis": c, "lo": v["min"], "hi": v["max"]}) for c, v in d.items()],
                          lambda applied: ("config.m208", {"axes": applied})),
             "M92": axes_kind("config.m92", "stepsPerMm", "steps_set", "v", 0.01, 99999),
             "M906": Kind(_clean_m906, _previous_m906, _lines_m906, lambda applied: ("config.m906", applied)),
             "M425": Kind(_clean_m425, _previous_m425, _lines_m425, lambda applied: ("config.m425", applied)),
             "M556": Kind(_clean_m556, _previous_m556, _lines_m556, lambda applied: ("config.m556", applied)),
             "M593": Kind(_clean_m593, _previous_m593, _lines_m593, lambda applied: ("config.m593", applied))}
    table = {"M913": ("config.m913", "percentCurrent"), "M917": ("config.m917", "percentStstCurrent"), "M203": ("config.m203", "speed"),
             "M201": ("config.m201", "acceleration"), "M205": ("config.m205", "printingJerk"), "M566": ("config.m566", "jerk")}
    for word, (config_kind, om_key) in table.items():
        _, lo, hi, template, name, wait = pmo.AXIS_KINDS[config_kind]
        kinds[word] = axes_kind(config_kind, om_key, template, name, lo, hi, wait=wait)
    return kinds


SPECS = _make()
