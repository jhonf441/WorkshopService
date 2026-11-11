"""Temperature-by-layer RECIPES: the pure logic (no I/O, no clock). A recipe is what a material needs along a print: ONE name, a kind (pellet or
filament), the material and up to two tracks that follow the same layer rule, the extruder track and the bed track.

    {"format": 2, "kind": "pellet" | "filament", "material": "PLA natural", "note": "",
     "tracks": {"extruder": {"tool", "heaters", "mode", "axis", "max_temp", "max_step", "max_spread", "points"},
                "bed": {"zones": [0, 1], "mode", "axis", "max_temp", "max_step", "max_spread", "points"}}}

A recipe is RELATIVE to the G-code (owner decision 2026-11-09, the only mode): the `temps` of a point are DELTAS in degrees per heater / zone over what the
file itself asks for at that layer (extruder range -150..150, bed -60..60); max_temp, max_step and max_spread stay ABSOLUTE limits of the result.

Stage 1 of informes/recetas-temperatura-por-capa/DISENO.md: this module only stores and validates. Nothing here (or in layer_recipes_ops.py) heats
anything or sends a code; the thread that applies the extruder track is still pellet_layers_run.py (the bed track gets its own stage). The extruder track
is EXACTLY a pellet_layers profile (same validation), the bed track is the same shape with the bed heaters as zones and the lower limits of a bed.
"""
import pellet_layers as pl
from messages import M

AREA = "layer-recipes"

KINDS = ("pellet", "filament")
MAX_RECIPES = 60
MATERIAL_MAX = 40
NOTE_MAX = 200
BED_HARD_MAX_TEMP = 150.0   # C: no bed track may set a bigger max_temp than this
BED_NUMBER_MAX = 31         # the bed heater numbers the service accepts (bed_zones_config.py)
TRACKS = ("extruder", "bed")
FORMAT = 2                  # the only format: the points of a track are DELTAS over what the G-code asks (a recipe without it is ignored)
DELTA_MAX = {"extruder": 150.0, "bed": 60.0}   # C: the biggest delta a point may carry on each track


class RecipeError(pl.ProfileError):
    """errors: [{"field", "message"}], every problem found (the same shape as a profile error)."""


def _err(field, key, **params):
    return {"field": field, "message": M(key, field=field, **params)}


def clean_name(name):
    """The name as it is stored: a trimmed text of 1 to NAME_MAX characters. Raises RecipeError."""
    try:
        return pl.clean_name(name)
    except pl.ProfileError as e:
        raise RecipeError([{"field": "name", "message": M("layer_recipes_err_name", max=pl.NAME_MAX)}] if e.errors else [])


def _prefixed(track, error):
    return [{"field": "tracks.%s.%s" % (track, x["field"]), "message": x["message"]} for x in error.errors]


def _track(raw, name):
    """One track in its stored form. The points carry DELTAS in degrees per heater / zone over what the G-code asks (negative allowed), so the
    static checks are: the same structure as a pellet profile (tool, heaters or zones, mode, axis, max_temp, max_step, max_spread, order and
    count of the points), each delta inside DELTA_MAX[name] and the deltas of one point no further apart than max_spread. max_temp, max_step and
    max_spread are ABSOLUTE limits applied to the resulting temperatures at run time. Raises pl.ProfileError with every problem found."""
    if not isinstance(raw, dict):
        raise pl.ProfileError([_err("track", "layer_recipes_err_track")])
    bed = name == "bed"
    shaped = dict(raw)
    if bed:
        shaped["tool"] = 0  # a stand-in for the structure check, it is not stored
        shaped["heaters"] = raw.get("zones")
    heaters = shaped.get("heaters")
    counted = isinstance(heaters, list) and 1 <= len(heaters) <= pl.MAX_ZONES
    points = raw.get("points")
    # the structure is checked by the profile validator with neutral temperatures; the real values (deltas) are checked below
    if isinstance(points, list):
        shaped["points"] = [dict(p, temps=[pl.MIN_TEMP] * len(heaters)) if isinstance(p, dict) and counted else p for p in points]
    errors, out = [], None
    try:
        out = pl.validate_profile(shaped)
    except pl.ProfileError as e:
        errors = [dict(x, field="zones" if bed and x["field"] == "heaters" else x["field"]) for x in e.errors]
    spread = raw.get("max_spread")
    limit = DELTA_MAX[name]
    deltas = []
    if isinstance(points, list):
        for i, p in enumerate(points):
            temps = p.get("temps") if isinstance(p, dict) else None
            field = "points[%d].temps" % i
            if not isinstance(temps, list) or not temps or (counted and len(temps) != len(heaters)):
                errors.append(_err(field, "pellet_layers_err_point_temps"))
                deltas.append(None)
            elif not all(pl._num(t, -limit, limit) for t in temps):
                errors.append(_err(field, "layer_recipes_err_delta_range", min=int(-limit), max=int(limit)))
                deltas.append(None)
            else:
                if pl._num(spread, pl.SPREAD_MIN, pl.SPREAD_MAX) and max(temps) - min(temps) > spread:
                    errors.append(_err(field, "layer_recipes_err_delta_spread", max=int(spread)))
                deltas.append([float(t) for t in temps])
    zones = raw.get("zones")
    if bed and isinstance(zones, list) and any(isinstance(z, int) and not isinstance(z, bool) and z > BED_NUMBER_MAX for z in zones):
        errors.append(_err("zones", "layer_recipes_err_bed_zones", max=BED_NUMBER_MAX))
    if bed and out is not None and out["max_temp"] > BED_HARD_MAX_TEMP:
        errors.append(_err("max_temp", "layer_recipes_err_bed_max", max=int(BED_HARD_MAX_TEMP)))
    if errors:
        raise pl.ProfileError(errors)
    stored = {"mode": out["mode"], "axis": out["axis"], "max_temp": out["max_temp"], "max_step": out["max_step"], "max_spread": out["max_spread"],
              "points": [{"at": p["at"], "temps": d} for p, d in zip(out["points"], deltas)]}
    if bed:
        return dict({"zones": out["heaters"]}, **stored)
    return dict({"tool": out["tool"], "heaters": out["heaters"]}, **stored)


def validate_recipe(raw):
    """The recipe in its stored form, or RecipeError with one message per problem."""
    if not isinstance(raw, dict):
        raise RecipeError([_err("recipe", "layer_recipes_err_recipe")])
    errors = []
    if not is_current(raw):
        errors.append(_err("format", "layer_recipes_err_format", format=FORMAT))
    kind = raw.get("kind")
    if kind not in KINDS:
        errors.append(_err("kind", "layer_recipes_err_kind"))
    material = raw.get("material", "")
    if not isinstance(material, str) or len(material.strip()) > MATERIAL_MAX:
        errors.append(_err("material", "layer_recipes_err_material", max=MATERIAL_MAX))
        material = ""
    note = raw.get("note", "")
    if not isinstance(note, str) or len(note.strip()) > NOTE_MAX:
        errors.append(_err("note", "layer_recipes_err_note", max=NOTE_MAX))
        note = ""
    tracks = raw.get("tracks")
    out = {}
    if not isinstance(tracks, dict) or not any(tracks.get(t) is not None for t in TRACKS) or any(k not in TRACKS for k in tracks):
        errors.append(_err("tracks", "layer_recipes_err_tracks"))
    else:
        for name in TRACKS:
            if tracks.get(name) is None:
                continue
            try:
                out[name] = _track(tracks[name], name)
            except pl.ProfileError as e:
                errors.extend(_prefixed(name, e))
        if len(out) == 2 and out["extruder"]["axis"] != out["bed"]["axis"]:
            errors.append(_err("tracks.bed.axis", "layer_recipes_err_axis"))
    if errors:
        raise RecipeError(errors)
    return {"format": FORMAT, "kind": kind, "material": material.strip(), "note": note.strip(), "tracks": out}


def is_current(raw):
    """True for a recipe of the current format (format 2: deltas). The others are ignored, never an error."""
    return isinstance(raw, dict) and raw.get("format") == FORMAT and not isinstance(raw.get("format"), bool)


def validate_store(value):
    """The whole stored value {"recipes": {name: recipe}}; a missing value is no recipes. Raises RecipeError."""
    if value is None:
        return {"recipes": {}}
    if not isinstance(value, dict) or not isinstance(value.get("recipes"), dict):
        raise RecipeError([_err("recipes", "layer_recipes_err_recipe")])
    if len(value["recipes"]) > MAX_RECIPES:
        raise RecipeError([_err("recipes", "layer_recipes_err_too_many", max=MAX_RECIPES)])
    kept = {n: r for n, r in value["recipes"].items() if is_current(r)}  # a recipe of an older format is skipped (gone on the next write)
    return {"recipes": {clean_name(n): validate_recipe(r) for n, r in kept.items()}}


def summary(name, recipe):
    """One line of the list: what the page shows before opening a recipe."""
    t = recipe["tracks"]
    first = t.get("extruder") or t.get("bed")
    return {"name": name, "kind": recipe["kind"], "material": recipe["material"], "tracks": [k for k in TRACKS if k in t],
            "axis": first["axis"], "points": len(first["points"])}


def from_pellet(profile):
    """A pellet_layers profile as a recipe with only the extruder track (kind pellet, no material yet), relative to the FIRST point: that point
    becomes zeros, the others are their temperatures minus it, per heater. The profile's absolute max_temp stays. None when the result is not a
    valid recipe (a difference over the delta range or zones further apart than max_spread)."""
    first = profile["points"][0]["temps"]
    track = dict(profile, points=[{"at": p["at"], "temps": [t - f for t, f in zip(p["temps"], first)]} for p in profile["points"]])
    recipe = {"format": FORMAT, "kind": "pellet", "material": "", "note": "", "tracks": {"extruder": track}}
    try:
        return validate_recipe(recipe)
    except RecipeError:
        return None


def import_pellet(store, profiles):
    """Adds every pellet profile that has no recipe of the same name yet: (new store, names added). Existing recipes are never replaced; a profile
    that can not be expressed as deltas (see from_pellet) is left out."""
    recipes = dict(store["recipes"])
    added = []
    for name in sorted(profiles):
        if name in recipes or len(recipes) >= MAX_RECIPES:
            continue
        recipe = from_pellet(profiles[name])
        if recipe is None:
            continue
        recipes[name] = recipe
        added.append(name)
    return {"recipes": recipes}, added
