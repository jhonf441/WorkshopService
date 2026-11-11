"""Temperature-by-layer RECIPES, the transparency preview: what a recipe WOULD send for a job file, layer by layer, with the lines of the file around each change.

It reads the file (never writes it) and sends nothing to the machine. The decisions are the SAME function the armed run uses
(layer_recipes_plan.commands_for, through plan.simulate), with a simulated board that starts at the first point of the recipe and takes every code, so
what is shown here is what would be sent. The limits come from the heaters the board reports now (heat.heaters[h].max) and the bed-zones configuration;
when a heater is not known the cap of the track itself is used and a note says so.

    preview(recipe, file, path, heat, tools, bed_config, bed_problem) -> {file, layers, axis, truncated, notes: [{key, params}], changes: [...]}
"""
import os

import gcode_plan
import gcode_temps
import layer_recipes_file as filetemps
import layer_recipes_plan as plan
import pellet_layers as pl

MAX_CHANGES = 400
MAX_TABLE = 1500
FILE_LINES = 60
LINE_CHARS = 200
CONTEXT = 3
EXTENSIONS = (".g", ".gcode", ".gco", ".nc", ".ngc", ".tap", ".gc")


def safe_path(sd_root, path):
    """The real path when it is a G-code file inside the SD, else None (the preview never reads anything else)."""
    root = os.path.realpath(sd_root)
    real = os.path.realpath(path)
    inside = real == root or real.startswith(root.rstrip(os.sep) + os.sep)
    return real if inside and real.lower().endswith(EXTENSIONS) and os.path.isfile(real) else None


def _text(raw):
    return raw.decode("utf-8", "replace").rstrip("\r\n")[:LINE_CHARS]


def read_lines(path, wanted):
    """{line number: text} for the 1-based line numbers in `wanted` (one pass over the file, lines cut to LINE_CHARS)."""
    out = {}
    if not wanted:
        return out
    last = max(wanted)
    with open(path, "rb") as fh:
        for n, raw in enumerate(fh, 1):
            if n in wanted:
                out[n] = _text(raw)
            if n >= last:
                break
    return out


def _models(heat, numbers):
    heaters = (heat or {}).get("heaters") or []
    return [heaters[h] if isinstance(h, int) and 0 <= h < len(heaters) else None for h in numbers]


def build_ctx(recipe, heat, tools, bed_config, bed_problem):
    """(ctx for the planner, notes). Unknown heaters get the cap of the track alone (and a note); a bed track that can not run is left out."""
    notes, ctx, skip = [], {}, []
    tracks = recipe["tracks"]
    if tracks.get("extruder"):
        track = tracks["extruder"]
        tool = next((t for t in (tools or []) if isinstance(t, dict) and t.get("number") == track["tool"]), None)
        models = _models(heat, track["heaters"])
        caps = plan.track_caps(track, models) if tool is not None else None
        if caps is None:
            caps = [track["max_temp"]] * len(track["heaters"])
            notes.append({"key": "layer_recipes_preview_caps_assumed", "params": {"track": "extruder"}})
        ctx["extruder"] = {"caps": caps}
    if tracks.get("bed"):
        track = tracks["bed"]
        bad = plan.bed_problem(track, bed_config, bed_problem)
        if bad:
            notes.append({"key": "layer_recipes_preview_zones_undefined", "params": {"problem": bad[0], **bad[1]}})
            skip.append("bed")
        else:
            slots = (heat or {}).get("bedHeaters") or []
            numbers = [slots[z] if z < len(slots) else None for z in track["zones"]]
            caps = plan.track_caps(track, _models(heat, numbers), bed_config["max_temp"])
            if caps is None:
                caps = [min(track["max_temp"], bed_config["max_temp"])] * len(track["zones"])
                notes.append({"key": "layer_recipes_preview_caps_assumed", "params": {"track": "bed"}})
            ctx["bed"] = {"caps": caps, "zones": {"zones": bed_config["zones"], "max_temp": bed_config["max_temp"]}}
    return ctx, notes, skip


def _track_view(entry, bed):
    if entry is None:
        return None
    out = {"temps": entry["temps"], "limited": entry["limited"]}
    out["codes" if bed else "code"] = entry["codes"] if bed else entry["code"]
    return out


def _scan(path):
    try:
        return gcode_temps.scan_file(path)
    except Exception:  # noqa: BLE001 - the preview still works without the file's own temperatures
        return {"commands": [], "truncated": False}


def _file_view(seen, n):
    """What the file itself holds when layer n starts, per track: {"temps": [..]} or None."""
    snap = seen[n - 1] if n <= len(seen) else {}
    return {name: ({"temps": snap[name]} if snap.get(name) else None) for name in ("extruder", "bed")}


def _conflicts(scan, recipe, zones, layer_line, n):
    start = layer_line[n - 1] if n <= len(layer_line) else None
    if not start:
        return []
    end = layer_line[n] if n < len(layer_line) else None
    return filetemps.conflicts(scan["commands"], recipe["tracks"], zones, start, end)


def board_base(recipe, heat, tools):
    """What the board holds now for the heaters of each track ({"extruder": [..] | None, "bed": [..] | None}): the fallback base when the file does not
    fix a heater. Nothing known (no object model) is None."""
    out = {"extruder": None, "bed": None}
    track = recipe["tracks"].get("extruder")
    if track:
        tool = next((t for t in (tools or []) if isinstance(t, dict) and t.get("number") == track["tool"]), None)
        active = tool.get("active") if tool else None
        out["extruder"] = list(active) if isinstance(active, list) and len(active) == len(track["heaters"]) else None
    track = recipe["tracks"].get("bed")
    if track:
        slots = (heat or {}).get("bedHeaters") or []
        heaters = (heat or {}).get("heaters") or []
        models = [heaters[slots[z]] if z < len(slots) and isinstance(slots[z], int) and 0 <= slots[z] < len(heaters) else None for z in track["zones"]]
        out["bed"] = [m.get("active") if isinstance(m, dict) else None for m in models] if models else None
    return out


def layer_bases(recipe, file_bases, fallback, layers):
    """{track: [base list or None per layer]}: the file's base per layer with the board's value for the heaters the file does not fix."""
    out = {}
    for name in recipe["tracks"]:
        column = []
        for i in range(layers):
            row = file_bases[i] if i < len(file_bases) else {}
            column.append(plan.resolve_base(row.get(name), (fallback or {}).get(name)))
        out[name] = column
    return out


def layers_table(applied, layer_line, scan, zones, tracks):
    """(rows, truncated): per layer what the file holds at its start (as written, no stagger) and what the recipe holds after that layer (the resolved
    base + delta, clamped; None where the base is unknown)."""
    seen = filetemps.snapshots(scan["commands"], tracks, layer_line[:MAX_TABLE], zones, scan["truncated"])
    rows = []
    for i in range(min(len(applied), MAX_TABLE)):
        snap = seen[i] if i < len(seen) else {}
        rows.append({"layer": i + 1, "file": {n: snap.get(n) for n in ("extruder", "bed")},
                     "recipe": {n: applied[i].get(n) if n in tracks else None for n in ("extruder", "bed")}})
    return rows, len(applied) > MAX_TABLE


def read_job(path):
    """{"layer_z", "layer_line", "scan"} of a job file (one pass for the layers, one for the temperature commands), None when it can not be read or
    has no layers. Shared by the preview and the armed run so both see the file the same way."""
    stats = {}
    try:
        gcode_plan.arm(path, "FFF", {"move": {}}, stats=stats)
    except Exception:  # noqa: BLE001 - an unreadable file is not a crash
        return None
    layer_z, layer_line = stats.get("layer_z") or [], stats.get("layer_line") or []
    return {"layer_z": layer_z, "layer_line": layer_line, "scan": _scan(path)} if layer_z else None


def flat_recipe(flat):
    """(recipe, base) of a FLAT preview recipe built on the fly from the zone temperatures of a material that has no layer recipe:
    flat = {"extruder": {"tool", "heaters", "temps"}, "bed": {"zones", "temps"}} (absolute temperatures per zone, already staggered by the caller:
    the stagger rule stays in the pages and in stagger_for, it is not repeated here). The recipe has one point of zero deltas, so what the preview
    shows is the material's own temperatures for every layer, inside the same caps. Nothing is stored. Raises lr.RecipeError (invalid temperatures)."""
    import layer_recipes as lr
    tracks, base = {}, {}
    for name, key in (("extruder", "heaters"), ("bed", "zones")):
        raw = flat.get(name) if isinstance(flat, dict) else None
        if raw is None:
            continue
        temps = raw.get("temps") if isinstance(raw, dict) else None
        if not isinstance(temps, list) or not temps or not all(pl._num(t, pl.MIN_TEMP, pl.HARD_MAX_TEMP) for t in temps):
            raise lr.RecipeError([lr._err("flat.%s.temps" % name, "layer_recipes_err_flat_temps", min=int(pl.MIN_TEMP), max=int(pl.HARD_MAX_TEMP))])
        track = {key: raw.get(key), "mode": "steps", "axis": "layer", "max_temp": float(max(temps)) + 1, "max_step": pl.MAX_STEP_LIMIT,
                 "max_spread": float(pl.SPREAD_MAX), "points": [{"at": 1, "temps": [0] * len(temps)}]}
        if name == "extruder":
            track["tool"] = raw.get("tool")
        tracks[name] = track
        base[name] = [float(t) for t in temps]
    recipe = lr.validate_recipe({"format": lr.FORMAT, "kind": "filament", "material": "", "note": "", "tracks": tracks})
    for name, temps in base.items():
        if len(recipe["tracks"][name]["heaters" if name == "extruder" else "zones"]) != len(temps):
            raise lr.RecipeError([lr._err("flat.%s" % name, "layer_recipes_err_flat_temps", min=int(pl.MIN_TEMP), max=int(pl.HARD_MAX_TEMP))])
    return recipe, base


def preview(recipe, file, path, heat=None, tools=None, bed_config=None, bed_problem=None, steps=None, flat_base=None):
    """The preview of `recipe` for the file `file` read at `path` (None = not readable). Never raises on a bad file. flat_base: {track: temps} from
    flat_recipe(): the base of every layer is that fixed vector (the material's temperatures) instead of the file's / the board's."""
    axis = next(iter(recipe["tracks"].values()))["axis"]
    out = {"file": file, "layers": 0, "axis": axis, "truncated": False, "notes": [], "changes": [],
           "file_temps": {"count": 0, "truncated": False, "lines": []}, "layers_table": [], "layers_table_truncated": False}
    if path is None:
        out["notes"].append({"key": "layer_recipes_preview_no_file", "params": {}})
        return out
    stats = {}
    try:
        gcode_plan.arm(path, "FFF", {"move": {}}, stats=stats)
    except Exception:  # noqa: BLE001 - an unreadable file is a note, not a crash
        out["notes"].append({"key": "layer_recipes_preview_no_file", "params": {}})
        return out
    layer_z, layer_line = stats.get("layer_z") or [], stats.get("layer_line") or []
    out["layers"] = len(layer_z)
    if not layer_z:
        out["notes"].append({"key": "layer_recipes_preview_no_layers", "params": {}})
        return out
    scan = _scan(path)
    out["file_temps"] = {"count": len(scan["commands"]), "truncated": scan["truncated"], "lines": scan["commands"][:FILE_LINES]}
    zones = bed_config if bed_config and bed_config.get("enabled") and not bed_problem else None
    ctx, notes, skip = build_ctx(recipe, heat, tools, bed_config, bed_problem)
    out["notes"].extend(notes)
    if skip:
        recipe = {"tracks": {k: v for k, v in recipe["tracks"].items() if k not in skip}}
        if not recipe["tracks"]:
            return out
    keys = [plan.key_for(axis, i + 1, layer_z) for i in range(len(layer_z))]
    if flat_base:
        bases = {name: [list(flat_base[name])] * len(keys) for name in recipe["tracks"] if name in flat_base}
    else:
        stagger = plan.stagger_for(recipe["tracks"]["extruder"]["heaters"], steps) if recipe["tracks"].get("extruder") else None
        file_bases = filetemps.base_vectors(scan["commands"], recipe["tracks"], layer_line, zones, scan["truncated"], stagger)
        bases = layer_bases(recipe, file_bases, board_base(recipe, heat, tools), len(keys))
    for name, column in bases.items():
        if any(b is None for b in column):
            out["notes"].append({"key": "layer_recipes_preview_base_unknown", "params": {"track": name}})
    changes, applied = plan.trace(recipe, keys, ctx, None, bases)
    out["layers_table"], out["layers_table_truncated"] = layers_table(applied, layer_line, scan, zones, recipe["tracks"])
    sets = filetemps.controlled(scan["commands"], recipe["tracks"], zones, layer_line[0]) if layer_line else 0
    if len(changes) > MAX_CHANGES:
        out["truncated"] = True
        out["notes"].append({"key": "layer_recipes_preview_truncated", "params": {"max": MAX_CHANGES}})
        changes = changes[:MAX_CHANGES]
    wanted = set()
    for c in changes:
        line = layer_line[c["layer"] - 1] if c["layer"] <= len(layer_line) else None
        wanted.update(range(max(1, line - CONTEXT), line + CONTEXT + 1) if line else [])
    lines = read_lines(path, wanted)
    seen = filetemps.snapshots(scan["commands"], recipe["tracks"], layer_line, zones, scan["truncated"])
    governing = recipe["tracks"].get("extruder") or recipe["tracks"].get("bed")
    for c in changes:
        n = c["layer"]
        line = layer_line[n - 1] if n <= len(layer_line) else None
        context = [{"n": k, "text": lines[k], "mark": k == line} for k in range(max(1, line - CONTEXT), line + CONTEXT + 1) if k in lines] if line else []
        out["changes"].append({"layer": n, "z": layer_z[n - 1] if n <= len(layer_z) else None, "line": line,
                               "at": plan.governing_at(governing, c["key"]), "extruder": _track_view(c["extruder"], False),
                               "bed": _track_view(c["bed"], True), "context": context,
                               "file": _file_view(seen, n), "conflicts": _conflicts(scan, recipe, zones, layer_line, n),
                               "delta": {k: (pl.raw_targets(recipe["tracks"][k], c["key"]) if k in recipe["tracks"] else None) for k in ("extruder", "bed")},
                               "base": {k: (c[k]["base"] if c.get(k) else None) for k in ("extruder", "bed")}})
    if sets:
        out["notes"].append({"key": "layer_recipes_preview_file_sets", "params": {"count": sets}})
    return out
