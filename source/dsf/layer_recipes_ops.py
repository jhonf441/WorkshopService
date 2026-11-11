"""API operations layerrecipes.list / get / set / remove / import_pellet / preview / status / arm / disarm and bedestimates.get / set (api_ops.init
registers them through build(ctx)).

Logic: layer_recipes.py and bed_estimates.py (pure); the planner layer_recipes_plan.py; the armed run layer_recipes_run.py; the preview
layer_recipes_preview.py. The stores live in service-only settings areas ("layer-recipes", "bed-estimates"): settings.set refuses them, so nothing can
skip the validation. Storing, reading and previewing never heat anything or send a code; only an ARMED recipe does, during its job.
Roles (permissions.py): list / get / preview / status = viewer, set / remove / import / arm / bedestimates.set = technician, disarm = a stop (never blocked).
"""
import activity
import bed_estimates as be
import identity
import layer_recipes as lr
import layer_recipes_preview
import layer_recipes_run as run
import sd_paths
import settings_store
from messages import M
from workshop_api import READ, STOP, WRITE, Arg, ApiError, Op


def _errors(error):
    return [{"field": x["field"], "message": str(x["message"])} for x in error.errors]


def _read(area, check, empty_key):
    try:
        value = settings_store.get(area)
        return check(value["value"]), value["rev"]
    except (lr.pl.ProfileError, be.EstimatesError) as e:
        raise ApiError("failed", M(empty_key), errors=_errors(e))


def _write(area, check, change, busy_key, empty_key):
    """Read-change-write of a whole store with its own revision; a clash with another writer is retried."""
    for _ in range(3):
        store, rev = _read(area, check, empty_key)
        change(store)
        try:
            return store, settings_store.set(area, store, rev)
        except settings_store.Conflict:
            continue
    raise ApiError("conflict", M(busy_key))


def _note(ctx, text):
    try:
        activity.log_event(ctx.get("bridge"), "config", text)
    except Exception as e:  # noqa: BLE001 - the history must never undo a saved change
        ctx["log_file"]("layer recipes: could not note the change in Activity: %s" % e)


def _live():
    """(heat, tools) of the object model now, ({}, []) when it is not there (the preview then assumes the caps of the tracks and says so)."""
    try:
        import machine_state
        return machine_state.read_in("heat", default={}, timeout=1), machine_state.read_in("tools", default=[], timeout=1)
    except Exception:  # noqa: BLE001 - no model: the preview still works
        return {}, []


def build(ctx):
    def recipes():
        return _read(lr.AREA, lr.validate_store, "layer_recipes_store_invalid")

    def rewrite(change):
        return _write(lr.AREA, lr.validate_store, change, "layer_recipes_store_busy", "layer_recipes_store_invalid")

    def list_(args, c):
        store, rev = recipes()
        return {"recipes": [lr.summary(n, r) for n, r in sorted(store["recipes"].items())], "rev": rev}

    def get(args, c):
        store, rev = recipes()
        name = args["name"]
        if name not in store["recipes"]:
            raise ApiError("invalid_args", M("layer_recipes_err_not_found", name=name), field="name")
        return {"name": name, "recipe": store["recipes"][name], "rev": rev}

    def set_(args, c):
        try:
            name = lr.clean_name(args["name"])
            clean = lr.validate_recipe(args["recipe"])
        except lr.pl.ProfileError as e:
            raise ApiError("invalid_args", e.errors[0]["message"], field=e.errors[0]["field"], errors=_errors(e))
        if run.armed_recipe() == name:
            raise ApiError("conflict", M("layer_recipes_err_armed_recipe", name=name))

        def change(store):
            if name not in store["recipes"] and len(store["recipes"]) >= lr.MAX_RECIPES:
                raise ApiError("invalid_args", M("layer_recipes_err_too_many", max=lr.MAX_RECIPES), field="name")
            store["recipes"][name] = clean

        store, r = rewrite(change)
        if r["changed"]:
            _note(ctx, M("layer_recipes_saved", name=name))
        return {"name": name, "recipe": clean, "rev": r["rev"], "changed": r["changed"]}

    def remove(args, c):
        name = args["name"]
        if run.armed_recipe() == name:
            raise ApiError("conflict", M("layer_recipes_err_armed_recipe", name=name))
        found = []

        def change(store):
            found[:] = [store["recipes"].pop(name, None)]

        store, r = rewrite(change)
        if not found[0]:
            raise ApiError("invalid_args", M("layer_recipes_err_not_found", name=name), field="name")
        _note(ctx, M("layer_recipes_removed", name=name))
        return {"name": name, "rev": r["rev"]}

    def import_pellet(args, c):
        """Copies the pellet profiles that have no recipe of the same name yet (nothing is replaced, the profiles stay where they are)."""
        import pellet_layers as pl
        try:
            profiles = pl.validate_store(settings_store.get(pl.AREA)["value"])["profiles"]
        except pl.ProfileError as e:
            raise ApiError("failed", M("pellet_layers_store_invalid"), errors=_errors(e))
        added = []

        def change(store):
            new, names = lr.import_pellet(store, profiles)
            store["recipes"] = new["recipes"]
            added[:] = names

        store, r = rewrite(change)
        if added:
            _note(ctx, M("layer_recipes_imported", n=len(added)))
        return {"added": added, "rev": r["rev"]}

    def status(args, c):
        return run.status()

    def arm(args, c):
        who = identity.actor(c)
        try:
            out = run.arm(args["name"], args["file"], who)
        except lr.pl.ProfileError as e:
            raise ApiError("failed", M("layer_recipes_store_invalid"), errors=_errors(e))
        except LookupError:
            raise ApiError("invalid_args", M("layer_recipes_err_not_found", name=args["name"]), field="name")
        except run.Conflict as e:
            raise ApiError("conflict", e.args[0])
        except ValueError as e:
            raise ApiError("invalid_args", e.args[0])
        _note(ctx, M("layer_recipes_armed", name=args["name"], file=args["file"]))
        return out

    def disarm(args, c):
        was = run.armed_recipe()
        out = run.disarm(identity.actor(c), record=lambda kind, text: activity.log_event(ctx.get("bridge"), kind, text))
        return dict(out, was_armed=was is not None)

    def preview(args, c):
        name, flat_base = args.get("name"), None
        if args.get("flat") is not None:
            # a material without layers: a flat recipe built from its zone temperatures, never saved
            try:
                recipe, flat_base = layer_recipes_preview.flat_recipe(args["flat"])
            except lr.pl.ProfileError as e:
                raise ApiError("invalid_args", e.errors[0]["message"], field=e.errors[0]["field"], errors=_errors(e))
        else:
            store, rev = recipes()
            if not isinstance(name, str) or name not in store["recipes"]:
                raise ApiError("invalid_args", M("layer_recipes_err_not_found", name=name), field="name")
            recipe = store["recipes"][name]
        file = args["file"]
        if not isinstance(file, str) or not file.strip():
            raise ApiError("invalid_args", M("layer_recipes_err_file"), field="file")
        import bed_zones_config
        config, problem = bed_zones_config.load()
        heat, tools = _live()
        path = layer_recipes_preview.safe_path(sd_paths.SD, sd_paths.sd(file.strip()))
        out = layer_recipes_preview.preview(recipe, file.strip(), path, heat, tools, config, problem, run._printing_steps(), flat_base)
        for n in out["notes"]:
            n["message"] = str(M(n["key"], **n["params"]))
        return dict(out, name=name or "", **({"flat": True} if flat_base is not None else {}))

    def estimates_get(args, c):
        store, rev = _read(be.AREA, be.validate, "bed_estimates_store_invalid")
        return dict(store, rev=rev)

    def estimates_set(args, c):
        try:
            clean = be.validate({"inputs": args.get("inputs"), "insulation": args.get("insulation")})
        except be.EstimatesError as e:
            raise ApiError("invalid_args", e.errors[0]["message"], field=e.errors[0]["field"], errors=_errors(e))
        for _ in range(3):
            rev = settings_store.get(be.AREA)["rev"]
            try:
                r = settings_store.set(be.AREA, clean, rev)
            except settings_store.Conflict:
                continue
            return dict(clean, rev=r["rev"], changed=r["changed"])
        raise ApiError("conflict", M("bed_estimates_store_busy"))

    a = Arg
    return [
        Op("layerrecipes.list", list_, READ, {}, "The temperature-by-layer recipes: {recipes: [{name, kind, material, tracks, axis, points}], rev}.", log=False),
        Op("layerrecipes.get", get, READ, {"name": a("str", True, desc="Recipe name.")},
           "One recipe: {name, recipe: {format: 2, kind: pellet|filament, material, note, tracks: {extruder?, bed?}}, rev}. The points of a track are DELTAS over the G-code.", log=False),
        Op("layerrecipes.set", set_, WRITE,
           {"name": a("str", True, desc="Recipe name (1 to 40 characters)."), "recipe": a("obj", True, desc="The whole recipe (see layerrecipes.get).")},
           "Validates and saves one recipe (creates or replaces it). Saving never heats anything. Invalid fields answer invalid_args with one message per field."),
        Op("layerrecipes.remove", remove, WRITE, {"name": a("str", True, desc="Recipe name.")}, "Deletes a recipe."),
        Op("layerrecipes.import_pellet", import_pellet, WRITE, {},
           "Copies every pellet profile that has no recipe of the same name as an extruder-only recipe, as deltas over the profile's first point. Nothing is replaced; the profiles stay."),
        Op("layerrecipes.preview", preview, READ,
           {"name": a("str", False, desc="Recipe name (needed unless `flat` is given)."), "file": a("str", True, desc="G-code file of the job (0:/gcodes/...)."),
            "flat": a("obj", False, desc="Instead of a saved recipe, a FLAT one built on the fly for a material without layers: {extruder?: {tool, heaters, temps}, "
                      "bed?: {zones, temps}}, absolute temperatures per zone (already staggered by the caller). Nothing is saved.")},
           "Transparency preview, read-only: reads the G-code file and returns what the recipe WOULD send, layer by layer, with the same planner and limits "
           "as the armed run: {name, file, layers, axis, truncated, notes: [{key, params, message}], changes: [{layer, z, line, at, extruder: {temps, code, "
           "limited} | null, bed: {temps, codes, limited} | null, context: [{n, text, mark}], file, conflicts, delta, base}], file_temps, layers_table}. "
           "Temperatures are base (the file's, else the board's) + delta, resolved; with `flat` the base is the material's own temperatures (delta 0) and the answer adds "
           "flat: true. It never modifies the file nor sends anything.", log=False),
        Op("layerrecipes.status", status, READ, {},
           "The armed recipe run: {armed, phase, recipe, file, layer, key, tracks: {extruder?: {applied, base, next, limited, overridden, overridden_layer}, bed?: {...}}, "
           "changes, reason}. phase: off, waiting, waiting_heat, waiting_layer, running, holding, ended.", log=False),
        Op("layerrecipes.arm", arm, WRITE,
           {"name": a("str", True, desc="Recipe name."), "file": a("str", True, desc="File name of the job it is armed for (job.file.fileName).")},
           "ARMS a recipe for ONE job file (in memory, off by default, dropped after an hour if the job never starts): while that job is printing, the "
           "service sends M568 P<tool> S... (extruder track) and M140 P<bed> S<t> for each listed zone (bed track) when the layer changes, inside the limits "
           "of the recipe and of each heater. It never switches a heater on or off. A pause holds; cancel, end or a lost job disarm it and leave the "
           "temperatures as they are; a board that refuses a code turns that track off. The bed track needs the bed zones enabled with all its zones "
           "defined. `conflict` while another recipe, or a pellet profile (when the recipe has an extruder track), is armed."),
        Op("layerrecipes.disarm", disarm, STOP, {},
           "Stops applying the recipe now and leaves the temperatures as they are. Never blocked.", exclusive=False),
        Op("bedestimates.get", estimates_get, READ, {},
           "The optional data of the bed power estimate and the insulation test: {inputs, insulation: {before, after}, rev}.", log=False),
        Op("bedestimates.set", estimates_set, WRITE,
           {"inputs": a("obj", False, desc="The optional inputs (numbers or empty)."), "insulation": a("obj", False, desc="The two finished insulation runs.")},
           "Saves the optional data of the estimate and the runs of the insulation test (the whole value). It touches no heater."),
    ]
