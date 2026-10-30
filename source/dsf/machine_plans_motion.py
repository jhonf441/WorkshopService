"""Planners of the phase 3 configuration kinds for machine.config.plan (Machine v2): skew, backlash, input shaping, motor currents, speeds,
accelerations, jerks and the basic parameters of the drivers. Same contract as machine_plans.py (pure; returns the plan body; `before` / `after` in the
SAME shape `values` takes, so machine.history.restore can feed them back; `now` = volatile lines of the closed list that apply_now sends).

    config.m556   {s?: 1-1000, x?, y?, z?}                                   technician   deviations in mm (|v| <= 0.1 s); s required if the line has none
    config.m425   {axes: {"X": mm 0-2}, multiplier?: 1-100}                    technician
    config.m593   {type, frequency?: 4-300, damping?: 0-0.99}                  technician   type: none zvd zvdd zvddd mzv ei2 ei3 (custom is shown, not edited)
    config.m906   {axes?: {"X": mA}, idle_percent?: 0-100, idle_timeout?: s}   ADMIN        every current <= the cap of the profile (never above 6300 mA)
    config.m913   {axes: {"X": 0-100}}   config.m917 the same                  ADMIN
    config.m203 / m201 / m205 / m566  {axes: {"X": v}}                         technician   speed mm/min, accel mm/s2, job jerk mm/s, jerk mm/min
    config.m569   {drivers: {"0.0": {direction?: 0|1, mode?: spreadcycle|stealthchop}}}   ADMIN   only S and D of an existing line; no volatile line
"""
import machine_config as mc
import machine_patch as pt
import machine_patch_motion as pm
import machine_plans as plans
import machine_profile

ALL = pm.LETTERS
BACKLASH_LETTERS = pt.AXIS_LETTERS
SHAPERS = ("none", "zvd", "zvdd", "zvddd", "mzv", "ei2", "ei3")
BIG_RATIO = (0.5, 2.0)


def _bad(field, code="bad_value"):
    return mc.PlanError(code, field)


def _run(env, word, tokens, now, picks, shape, extra=()):
    """The common path: edit the last file that defines `word` for one of the letters, return the plan body with before / after in the shape of the kind."""
    letters = set(tokens)
    path, before, res, scan, hits = plans._edit(
        env, lambda t: bool(set(pm.read_letters(t, word, ALL + "ITSPF")) & letters), lambda t: pm.patch_word(t, word, tokens))
    pick = lambda text: {c: v for c, v in pm.read_letters(text, word, ALL + "ITSPF").items() if c in picks}                   # noqa: E731
    old, new = pick(mc._decode(before)), pick(res["text"])
    body = plans._body(path, before, res, scan, hits, now, shape(old) if old else None, shape(new))
    body["warnings"] += list(extra)
    return body


def _big(old, new, picks):
    return any(old.get(c) and not BIG_RATIO[0] <= new[c] / old[c] <= BIG_RATIO[1] for c in picks if c in new)


# ---- one value per axis: M913 M917 M203 M201 M205 M566 ----

AXIS_KINDS = {
    "config.m913": ("M913", 0, 100, "current_pct_set", "pct", True),
    "config.m917": ("M917", 0, 100, "standstill_set", "pct", True),
    "config.m203": ("M203", 1, 99999, "speed_set", "v", False),
    "config.m201": ("M201", 1, 99999, "accel_set", "v", False),
    "config.m205": ("M205", 0, 1000, "jerk_set", "v", False),
    "config.m566": ("M566", 0, 60000, "jerk_machine_set", "v", False),
}


def plan_axes_kind(kind, values, env):
    word, lo, hi, tpl, name, wait = AXIS_KINDS[kind]
    new = plans._axis_map(values, "axes", lambda v, f: plans._number(v, lo, hi, f), ALL)
    now = ([("wait_moves", {})] if wait else []) + [(tpl, {"axis": c, name: v}) for c, v in new.items()]       # M913 / M917 do not wait for the moves
    body = _run(env, word, {c: pt.num_text(v) for c, v in new.items()}, now, set(new), lambda d: {"axes": d})
    if body["before"] and _big(body["before"]["axes"], new, new):
        body["warnings"].append("big_change")
    return body


# ---- M906 ----

def _cap(env):
    return machine_profile.current_cap(env.get("profile"))


def plan_m906(values, env):
    cap = _cap(env)
    tokens, now, picks = {}, [], set()
    if values.get("axes") is not None:
        new = plans._axis_map(values, "axes", lambda v, f: plans._number(v, 50, machine_profile.CURRENT_CEILING_MA, f), ALL)
        for c, v in new.items():
            if v > cap:
                raise mc.PlanError("current_over_limit", "axes." + c)
        tokens.update({c: pt.num_text(v) for c, v in new.items()})
        now += [("current_set", {"axis": c, "v": v}) for c, v in new.items()]
        picks |= set(new)
    idle = _opt_int(values, "idle_percent", 0, 100)
    secs = _opt_int(values, "idle_timeout", 1, 3600)
    if idle is not None:
        tokens["I"] = str(idle)
        now.append(("idle_percent_set", {"idle": idle}))
        picks.add("I")
    if secs is not None:
        tokens["T"] = str(secs)
        now.append(("idle_timeout_set", {"secs": secs}))
        picks.add("T")
    if not tokens:
        raise _bad("values")

    def shape(d):
        out = {"axes": {c: v for c, v in d.items() if c in ALL}} if any(c in ALL for c in d) else {}
        if "I" in d:
            out["idle_percent"] = int(d["I"])
        if "T" in d:
            out["idle_timeout"] = int(d["T"])
        return out
    body = _run(env, "M906", tokens, now, picks, shape, extra=["idle_zero_unhomes"] if idle == 0 else [])
    if body["before"] and body["before"].get("axes") and _big(body["before"]["axes"], {c: float(tokens[c]) for c in tokens if c in ALL}, picks):
        body["warnings"].append("big_change")
    return body


def _opt_int(values, key, lo, hi):
    v = values.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v != int(v) or not lo <= v <= hi:
        raise _bad(key)
    return int(v)


# ---- M425 ----

def plan_m425(values, env):
    new = plans._axis_map(values, "axes", lambda v, f: plans._number(v, 0, 2, f), BACKLASH_LETTERS)
    mult = values.get("multiplier")
    tokens = {c: pt.num_text(v) for c, v in new.items()}
    now = [("backlash_set", {"axis": c, "v": v}) for c, v in new.items()]
    picks = set(new)
    if mult is not None:
        mult = plans._number(mult, 1, 100, "multiplier")
        tokens["S"] = pt.num_text(mult)
        now.append(("backlash_factor", {"mult": mult}))
        picks.add("S")

    def shape(d):
        out = {"axes": {c: v for c, v in d.items() if c in BACKLASH_LETTERS}}
        if "S" in d:
            out["multiplier"] = d["S"]
        return out
    return _run(env, "M425", tokens, now, picks, shape)


# ---- M556 ----

def plan_m556(values, env):
    tokens, picks = {}, set()
    for key, lo, hi in (("s", 1, 1000), ("x", -100, 100), ("y", -100, 100), ("z", -100, 100)):
        if values.get(key) is not None:
            tokens[key.upper()] = pt.num_text(plans._number(values[key], lo, hi, key))
            picks.add(key.upper())
    if not tokens:
        raise _bad("values")
    body = _run(env, "M556", tokens, None, picks, lambda d: {k.lower(): v for k, v in d.items()})
    text = body["files"][0]["new"].decode("utf-8", "replace") if body["files"] else ""
    eff = pm.read_letters(text, "M556", "SXYZ")
    if "S" not in eff:
        raise _bad("s")
    s = eff["S"]
    for c in "XYZ":
        if abs(eff.get(c, 0.0)) > 0.1 * s:
            raise _bad(c.lower())
    body["now"] = {"lines": [("skew_set", {"fx": eff.get("X", 0.0) / s, "fy": eff.get("Y", 0.0) / s, "fz": eff.get("Z", 0.0) / s})]}
    return body


# ---- M593 ----

def plan_m593(values, env):
    kind = values.get("type")
    if kind not in SHAPERS:
        raise _bad("type", "bad_type")
    freq = values.get("frequency")
    damp = values.get("damping")
    if freq is not None:
        freq = plans._number(freq, 4, 300, "frequency")
    if damp is not None:
        damp = plans._number(damp, 0, 0.99, "damping")
    if kind != "none" and freq is None:
        raise _bad("frequency", "no_frequency")
    path, before, res, scan, hits = plans._edit(env, lambda t: pm.read_m593(t) is not None, lambda t: pm.patch_m593(t, kind, freq, damp))
    old_v, new_v = pm.read_m593(mc._decode(before)), pm.read_m593(res["text"])
    eff = new_v or {}
    if kind == "none":
        now = [("shaping_none", {})]
    else:
        now = [("shaping_set", {"shaper": kind, "freq": eff.get("frequency", freq), "damp": eff.get("damping", damp if damp is not None else 0.1)})]
    body = plans._body(path, before, res, scan, hits, now, old_v, new_v)
    if old_v and old_v.get("type") == "custom":
        body["warnings"].append("custom_shaper_replaced")
    return body


# ---- M569 (basic parameters only) ----

def _drivers(values):
    raw = values.get("drivers")
    if not isinstance(raw, dict) or not raw:
        raise _bad("drivers")
    out = {}
    for key, ch in raw.items():
        drv = pm.norm_driver(key)
        if drv is None or not isinstance(ch, dict) or not ch or set(ch) - {"direction", "mode"}:
            raise _bad("drivers." + str(key))
        tokens = {}
        if "direction" in ch:
            if isinstance(ch["direction"], bool) or ch["direction"] not in (0, 1):
                raise _bad("drivers.%s.direction" % key)
            tokens["S"] = str(int(ch["direction"]))
        if "mode" in ch:
            if ch["mode"] not in pm.DRIVER_MODES:
                raise _bad("drivers.%s.mode" % key)
            tokens["D"] = str(pm.DRIVER_MODES[ch["mode"]])
        if not tokens:
            raise _bad("drivers." + str(key))
        out[drv] = tokens
    return out


def _patch_drivers(text, drivers):
    notices, action, line = [], "same", None
    for drv in sorted(drivers):
        r = pm.patch_m569(text, drv, drivers[drv])
        text = r["text"]
        notices += [x for x in r["notices"] if x not in notices]
        if r["action"] != "same":
            action, line = "replaced", line or r["line"]
    return {"text": text, "action": action, "line": line or 1, "notices": notices}


def plan_m569(values, env):
    drivers = _drivers(values)
    path, before, res, scan, hits = plans._edit(env, lambda t: bool(set(pm.read_m569(t)) & set(drivers)), lambda t: _patch_drivers(t, drivers))

    def shape(text):
        cur = pm.read_m569(text)
        out = {}
        for drv, tokens in drivers.items():
            row = {}
            if "S" in tokens and cur.get(drv, {}).get("direction") is not None:
                row["direction"] = cur[drv]["direction"]
            if "D" in tokens and cur.get(drv, {}).get("mode") is not None:
                row["mode"] = cur[drv]["mode"]
            if row:
                out[drv] = row
        return {"drivers": out} if out else None
    body = plans._body(path, before, res, scan, hits, None, shape(mc._decode(before)), shape(res["text"]))
    body["now"] = None
    return body


PLANNERS = {"config.m556": plan_m556, "config.m425": plan_m425, "config.m593": plan_m593, "config.m906": plan_m906, "config.m569": plan_m569}
for _kind in AXIS_KINDS:
    PLANNERS[_kind] = (lambda k: lambda values, env: plan_axes_kind(k, values, env))(_kind)
