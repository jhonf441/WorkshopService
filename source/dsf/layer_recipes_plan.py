"""Temperature-by-layer RECIPES, the planner: what to send at a layer. PURE (no I/O, no clock, no object model).

ONE function decides for BOTH tracks, and both the armed run (layer_recipes_run.py) and the transparency preview (layer_recipes_preview.py) call it,
so what the preview shows is what the run sends. It reuses the rules of pellet_layers.py (raw_targets, limit_change, caps_for, code_for): a
temperature is never above min(track max_temp, heater max - HEADROOM_C, and for the bed the bed-zones max_temp), never below MIN_TEMP (nothing here
switches a heater off), moves at most max_step per layer advanced, and the zones never end more than max_spread apart.

    commands_for(recipe, layer, last_applied, ctx) -> {"extruder": track or None, "bed": track or None}

A recipe is RELATIVE to the G-code (format 2): the points of a track are DELTAS in degrees per heater / zone. The value of a layer is
base + delta(layer), where the BASE is what the file itself holds for each heater / zone when that layer starts (ctx[track]["base"]) and delta comes from
pellet_layers.raw_targets over the delta points (same steps / ramp interpolation). Then the same limits as always, all ABSOLUTE: min(track max_temp, heater
max - HEADROOM, bed-zones max) above, MIN_TEMP below, max_step per layer advanced from the last applied value, max_spread among the zones. A track with
no base (None, or a None inside) is not computed: nothing is guessed.

    layer        {"layer": <number, 1-based>, "key": <the layer number or the Z in mm, as the recipe's axis says>}
    last_applied {"extruder": {"layer": n, "temps": [...]} or None, "bed": ...}   None = nothing applied yet (the board's own temperatures rule)
    ctx          {"extruder": {"base": [..], "caps": [..], "active": [..]}, "bed": {"base": [..], "caps": [..], "active": [..], "zones": <bed_zones config>}}
                 base = the file's temperature per heater / zone at this layer's start; active = what the board holds now (the starting point of the first move)

    a track result: {"base": [...], "delta": [...], "temps": [...], "raw": [...], "limited": bool, "notes": ["cap"|"step"|"spread"|"zone"], "send": bool, "held": bool,
                     "code": "M568 P0 S200:210" (extruder) | "codes": ["M140 P0 S60", ...] (bed)}
    send is False when the board already has those temperatures or when no legal move exists (held: it keeps what it has). A track that is not in
    the recipe, or whose context is incomplete (no caps, no previous temperatures) is None: it is never guessed.
"""
import bed_zones
import pellet_layers as pl

SAME_TOL = 0.05   # C: the same tolerance pellet_layers.Run uses to say "the board already has it"
TRACKS = ("extruder", "bed")


def key_for(axis, layer, layer_z=None, z=None):
    """The curve key of a layer: the layer number, or (axis z) the height of that layer in the plan table, else the current Z. None when unknown."""
    if axis == "layer":
        return layer
    if layer_z and len(layer_z) >= layer:
        return layer_z[layer - 1]
    return z


def governing_at(track, key):
    """The `at` of the recipe point that rules at `key` (the last point at or before it; the first one before the curve starts)."""
    pts = track["points"]
    before = [p["at"] for p in pts if p["at"] <= key]
    return before[-1] if before else pts[0]["at"]


def track_caps(track, heater_models, extra_max=None):
    """The highest temperature each heater of the track may be asked for (None when a heater does not tell its maximum)."""
    top = track["max_temp"] if extra_max is None else min(track["max_temp"], extra_max)
    return pl.caps_for({"max_temp": top}, heater_models)


def bed_problem(track, config, problem=None):
    """(key, params) naming why the bed track can not run with this bed-zones configuration, or None when it can."""
    if problem:
        return "layer_recipes_err_bed_config_invalid", {}
    if not config or not config.get("enabled"):
        return "layer_recipes_err_bed_disabled", {}
    defined = [z.get("bed") for z in config.get("zones", [])]
    for zone in track["zones"]:
        if zone not in defined:
            return "layer_recipes_err_bed_zone_undefined", {"zone": zone}
    return None


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def stagger_for(heaters, steps):
    """The offset of each heater of a tool over the nozzle temperature, from the Pellet and zones page (printing.json "step": {heater number: degrees,
    negative}): the first heater of the tool is the nozzle and has none, the others add their own step (the rule Preheat of Materials uses). Heaters
    with no step, or anything that is not a number, get 0. The service never sends this on its own: it is only the shape of the BASE of an extruder track."""
    steps = steps if isinstance(steps, dict) else {}
    out = []
    for k, h in enumerate(heaters):
        v = steps.get(str(h), steps.get(h)) if k > 0 else 0
        out.append(float(v) if _number(v) else 0.0)
    return out


def resolve_base(file_values, board_values):
    """The base vector of a track at a layer: per heater / zone the file's temperature when it fixes one (a number of at least MIN_TEMP), else the
    board's, else unknown. None when any heater is unknown (the track is then not computed) or nothing is given."""
    if not file_values and not board_values:
        return None
    n = len(file_values or board_values)
    out = []
    for i in range(n):
        for source in (file_values, board_values):
            v = source[i] if source and i < len(source) else None
            if _number(v) and v >= pl.MIN_TEMP:
                out.append(float(v))
                break
        else:
            return None
    return out


def _same(temps, previous):
    return all(abs(t - p) < SAME_TOL for t, p in zip(temps, previous))


def _plan_track(track, layer, last, info, bed):
    if not isinstance(info, dict):
        return None
    caps = info.get("caps")
    n = len(track["heaters"] if not bed else track["zones"])
    previous = last["temps"] if last else info.get("active")
    base = info.get("base")
    if not caps or len(caps) != n or not previous or len(previous) != n or not base or len(base) != n or any(not _number(b) for b in base):
        return None
    delta = pl.raw_targets(track, layer["key"])
    raw = [round(b + d, 2) for b, d in zip(base, delta)]
    advanced = 1 if not last else layer["layer"] - last["layer"]
    temps, notes = pl.limit_change(track, raw, previous, caps, advanced)
    out = {"base": [float(b) for b in base], "delta": delta, "raw": raw, "held": temps is None}
    if temps is None:
        out.update(temps=list(previous), limited=True, notes=notes, send=False)
        return out
    out.update(temps=temps, limited=bool(notes), notes=notes, send=not _same(temps, previous))
    return out


def _extruder(track, plan):
    plan["code"] = pl.code_for(track["tool"], plan["temps"]) if plan["send"] else None
    return plan


def _bed(track, plan, zones):
    """One M140 P<bed> S<t> per zone whose temperature changes, through bed_zones.zone_code (the code the Heat button sends for one zone)."""
    codes = []
    if plan["send"]:
        previous = plan["previous"]
        for bed, t, p in zip(track["zones"], plan["temps"], previous):
            if abs(t - p) < SAME_TOL:
                continue
            code, error = bed_zones.zone_code(bed, t, zones)
            if error:  # a zone the config does not know or a setpoint over its maximum: nothing is sent for the track
                plan.update(temps=list(previous), limited=True, notes=sorted(set(plan["notes"] + ["zone"])), send=False, held=True)
                codes = []
                break
            codes.append(code)
    plan["codes"] = codes
    return plan


def commands_for(recipe, layer, last_applied, ctx):
    """What to send at `layer`. See the module text for the shapes. Never raises on a missing part of the context."""
    last_applied = last_applied or {}
    ctx = ctx or {}
    out = {"extruder": None, "bed": None}
    tracks = recipe.get("tracks") or {}
    if tracks.get("extruder"):
        plan = _plan_track(tracks["extruder"], layer, last_applied.get("extruder"), ctx.get("extruder"), False)
        out["extruder"] = _extruder(tracks["extruder"], plan) if plan else None
    if tracks.get("bed"):
        info = ctx.get("bed")
        plan = _plan_track(tracks["bed"], layer, last_applied.get("bed"), info, True)
        if plan and isinstance(info.get("zones"), dict):
            last = last_applied.get("bed")
            plan["previous"] = list(last["temps"] if last else info["active"])
            plan = _bed(tracks["bed"], plan, info["zones"])
            plan.pop("previous")
            out["bed"] = plan
    return out


def describe(plan):
    """The text of a track result for the history: "200 / 210 / 220"."""
    return " / ".join(pl._fmt(t) for t in plan["temps"])


def simulate(recipe, keys, ctx, start=None, bases=None):
    """The changes of trace() (see there)."""
    return trace(recipe, keys, ctx, start, bases)[0]


def trace(recipe, keys, ctx, start=None, bases=None):
    """Runs the planner over layers 1..len(keys) as the armed run would (every layer is seen, none skipped) with a simulated board that always
    accepts the codes. keys[i] is the key of layer i + 1. bases: {"extruder": [per layer: base list or None], "bed": [...]} the file's temperatures at
    each layer's start (a ctx "base" is used for every layer when this is not given). start: {"extruder": [...], "bed": [...]} what the board holds
    when the first computable layer comes; by default the resolved value of that layer, inside its caps.
    Returns (changes, applied): changes = [{"layer", "key", "extruder": track or None, "bed": track or None}] for every layer where something is sent,
    applied = [{"extruder": [temps] or None, "bed": ...}] one per layer: what the recipe holds after that layer (None where the base is unknown)."""
    tracks = recipe.get("tracks") or {}
    ctx = {k: dict(v) for k, v in (ctx or {}).items() if isinstance(v, dict)}
    last = {"extruder": None, "bed": None}
    changes, applied = [], []
    for i, key in enumerate(keys):
        row = {"extruder": None, "bed": None}
        applied.append(row)
        if key is None:
            continue
        for name in TRACKS:
            if tracks.get(name) and name in ctx and bases is not None:
                column = bases.get(name) or []
                ctx[name]["base"] = column[i] if i < len(column) else None
            info = ctx.get(name)
            base = info.get("base") if info else None
            if tracks.get(name) and info is not None and "active" not in info and base and all(_number(b) for b in base) and info.get("caps"):
                given = (start or {}).get(name)
                raw = [b + d for b, d in zip(base, pl.raw_targets(tracks[name], key))]
                info["active"] = list(given) if given else [max(pl.MIN_TEMP, min(r, c)) for r, c in zip(raw, info["caps"])]
        layer = {"layer": i + 1, "key": key}
        plans = commands_for(recipe, layer, last, ctx)
        sent = {}
        for name in TRACKS:
            plan = plans[name]
            if plan is None:
                continue
            if not plan["held"]:
                last[name] = {"layer": layer["layer"], "temps": list(plan["temps"])}
            if plan["send"]:
                sent[name] = plan
            if last[name]:
                row[name] = list(last[name]["temps"])
        if sent:
            changes.append({"layer": layer["layer"], "key": key, "extruder": sent.get("extruder"), "bed": sent.get("bed")})
    return changes, applied
