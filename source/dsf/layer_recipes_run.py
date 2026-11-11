"""Temperature-by-layer RECIPES, the part that touches the world: the armed run, its tick and the Activity / audit records.

The decisions are layer_recipes_plan.py and layer_recipes_state.py (pure). Here: who armed what (in memory, never saved: a restart disarms), reading the
single DSF subscription, sending `M568 P<tool> S...` (extruder) and `M140 P<bed> S<t>` (bed zones) through the bridge, and recording every change. The
tick runs inside the loop of pellet_layers_run.py (one thread, one heartbeat "pellet_layers"); it never raises out of the loop.
One recipe at a time, and a recipe with an extruder track never runs next to an armed pellet profile (same heater, two writers).
Design: informes/recetas-temperatura-por-capa/DISENO.md.
"""
import re
import threading
import time

import audit
import layer_recipes as lr
import layer_recipes_file as filetemps
import layer_recipes_preview as preview
import layer_recipes_plan as plan
import layer_recipes_state as st
import pellet_layers as pl
import pellet_layers_run as pellet_run
import sd_paths
import settings_store
from messages import M

_lock = threading.RLock()
_state = {"run": None, "last": None}


class Conflict(pellet_run.Conflict):
    """Another run holds the heater (a pellet profile) or a recipe is already armed."""


def _is_error(answer):
    return bool(re.search(r"error|abort", str(answer or ""), re.I))


def load_store():
    return lr.validate_store(settings_store.get(lr.AREA)["value"])


def _bed_config():
    import bed_zones_config
    return bed_zones_config.load()


def _printing_steps():
    """The zone stagger of the Pellet and zones page (printing.json "step"), {} when it is not there."""
    try:
        value = settings_store.get("printing")["value"]
        return value.get("step") if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - no stagger is a plain base (the same temperature on every heater)
        return {}


def file_bases(recipe, file, bed_config=None):
    """What the job FILE holds at the start of each layer for the heaters of the recipe (scanned once, the same scan the preview uses): a list with one
    {"extruder": [..] | None, "bed": [..] | None} per layer. A file that can not be read gives [] (then the board's temperatures are the base)."""
    path = preview.safe_path(sd_paths.SD, sd_paths.sd(file))
    job = preview.read_job(path) if path else None
    if not job:
        return []
    config, problem = bed_config() if bed_config else _bed_config()
    zones = config if config and config.get("enabled") and not problem else None
    extruder = recipe["tracks"].get("extruder")
    stagger = plan.stagger_for(extruder["heaters"], _printing_steps()) if extruder else None
    scan = job["scan"]
    return filetemps.base_vectors(scan["commands"], recipe["tracks"], job["layer_line"], zones, scan["truncated"], stagger)


def armed_recipe():
    with _lock:
        run = _state["run"]
        return run.name if run is not None and not run.ended else None


def armed_extruder():
    """True while an armed recipe has an extruder track (pelletlayers.arm refuses then)."""
    with _lock:
        run = _state["run"]
        return run is not None and not run.ended and run.has("extruder")


def arm(name, file, who, now=None, bed_config=None):
    """Arms the recipe `name` for the job file `file`. Raises LookupError (no such recipe), ValueError (a Msg), Conflict."""
    now = time.time() if now is None else now
    if not isinstance(file, str) or not file.strip():
        raise ValueError(M("layer_recipes_err_file"))
    recipes = load_store()["recipes"]
    if name not in recipes:
        raise LookupError(name)
    recipe = recipes[name]
    track = recipe["tracks"].get("bed")
    if track:
        config, problem = bed_config() if bed_config else _bed_config()
        bad = plan.bed_problem(track, config, problem)
        if bad:
            raise ValueError(M(bad[0], **bad[1]))
    bases = file_bases(recipe, file.strip(), bed_config)
    with _lock:
        cur = _state["run"]
        if cur is not None and not cur.ended:
            raise Conflict(M("layer_recipes_err_already_armed", recipe=cur.name))
        if recipe["tracks"].get("extruder") and pellet_run.armed_profile() is not None:
            raise Conflict(M("layer_recipes_err_pellet_armed", profile=pellet_run.armed_profile()))
        _state["run"] = st.RecipeRun(name, recipe, file.strip(), now, who, bases)
        _state["last"] = None
    return status()


def disarm(who=None, record=None):
    """The person's stop: ends the run and leaves the temperatures as they are."""
    with _lock:
        run = _state["run"]
        if run is None or run.ended:
            return status()
        events = run.disarm()
        _state["last"] = run.view()
    for e in events:
        _record_disarm(run, e, record)
    return status()


def status():
    with _lock:
        run = _state["run"]
        view = run.view() if run is not None else _state["last"]
    if view is None:
        return {"armed": False, "phase": "off", "recipe": None, "file": None, "layer": None, "key": None, "tracks": {}, "changes": 0, "reason": None}
    return view


def _who(run):
    return run.armed_by if run is not None else {}


def _safe_record(record, kind, text):
    try:
        record(kind, text)  # activity.log_event: history, black box
    except Exception:  # noqa: BLE001 - a record that fails must not undo or repeat a change already made
        pass


def _record_apply(run, e, record):
    key = "layer_recipes_applied_extruder" if e["track"] == "extruder" else "layer_recipes_applied_bed"
    _safe_record(record, "config", M(key, layer=e["layer"], temps=" / ".join(pl._fmt(t) for t in e["temps"]), code="; ".join(e["codes"])))
    audit.event("layerrecipes.apply", {"recipe": run.name, "track": e["track"], "layer": e["layer"], "code": "; ".join(e["codes"]),
                                       "limited": ",".join(e["notes"])}, _who(run))


def _record_disarm(run, e, record):
    text = M(e["reason"], **e["params"])
    if record is not None:
        _safe_record(record, "error" if e["warn"] else "config", M("layer_recipes_disarmed", recipe=run.name, reason=text))
    audit.event("layerrecipes.disarm", {"recipe": run.name, "reason": e["reason"]}, _who(run), ok=not e["warn"], code=e["reason"], message=str(text))


def _snapshot(model, bed_config):
    snap = pl.snapshot(model)
    heat = (model or {}).get("heat") if isinstance(model, dict) else None
    snap["bed_heaters"] = list((heat or {}).get("bedHeaters") or [])
    config, problem = bed_config()
    snap["bed_config"], snap["bed_problem"] = config, problem
    return snap


def tick(status_model, send, record, now=None, table=None, bed_config=None):
    """One pass. send(code) -> answer text (raises on a failed send); record(kind, message). Returns the events it handled."""
    now = time.time() if now is None else now
    with _lock:
        run = _state["run"]
        if run is None or run.ended:
            return []
        snap = _snapshot(status_model, bed_config or _bed_config)
        axis = next(iter(run.recipe["tracks"].values()))["axis"]
        if snap["file"] == run.file and (axis == "z" or snap["layer"] is None):
            snap["layer_z"] = (table or pellet_run._layer_table)(run.file)
        handled = []
        for e in run.step(snap, now):
            if e["type"] == "apply":
                answer = _send_all(send, e["codes"])
                if _is_error(answer):
                    for d in run.rejected(e["track"], answer):
                        _record_rejection(run, d, record)
                        handled.append(d)
                    continue
                run.commit(e, now)
                _record_apply(run, e, record)
            elif e["type"] == "note":
                _safe_record(record, "error" if e.get("warn") else "config", M(e["key"], **e["params"]))
            elif e["type"] == "disarm":
                _record_disarm(run, e, record)
            handled.append(e)
        if run.ended:
            _state["last"] = run.view()
        return handled


def _send_all(send, codes):
    """Sends the codes in order; the answer is the first one that looks like an error (the rest of the track is not sent)."""
    answer = ""
    for code in codes:
        try:
            answer = send(code)
        except Exception as ex:  # noqa: BLE001 - a send that fails is a rejection: stop, say so
            return "error: %s" % ex
        if _is_error(answer):
            return answer
    return answer


def _record_rejection(run, d, record):
    if d["type"] == "disarm":
        _record_disarm(run, d, record)
    else:
        _safe_record(record, "error", M(d["key"], **d["params"]))
        audit.event("layerrecipes.track_rejected", {"recipe": run.name, "track": d["params"]["track"]}, _who(run), ok=False,
                    code=d["key"], message=d["params"]["answer"])
