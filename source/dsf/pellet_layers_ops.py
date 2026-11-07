"""API operations pelletlayers.list / get / set / remove / status / arm / disarm (api_ops.init registers them through build(ctx)).

Logic: pellet_layers.py (pure). The armed run and the thread: pellet_layers_run.py. Profiles live in the settings area "pellet-layers"
(settings.set refuses it: SERVICE_ONLY). Roles (permissions.py): list / get / status = viewer, set / remove / arm = technician, disarm = a stop
(never blocked). Arming is off by default, per job and in memory: see DISENO.md.
"""
import activity
import identity
import pellet_layers as pl
import pellet_layers_run as run
import settings_store
from messages import M
from workshop_api import READ, STOP, WRITE, Arg, ApiError, Op


def _errors(error):
    return [{"field": x["field"], "message": str(x["message"])} for x in error.errors]


def _store():
    try:
        value = settings_store.get(pl.AREA)
        return pl.validate_store(value["value"]), value["rev"]
    except pl.ProfileError as e:
        raise ApiError("failed", M("pellet_layers_store_invalid"), errors=_errors(e))


def _save(change):
    """Read-change-write of the whole store with its own revision; a clash with another writer is retried."""
    for _ in range(3):
        store, rev = _store()
        change(store["profiles"])
        try:
            r = settings_store.set(pl.AREA, store, rev)
        except settings_store.Conflict:
            continue
        return store, r
    raise ApiError("conflict", M("pellet_layers_store_busy"))


def _note(ctx, text):
    try:
        activity.log_event(ctx.get("bridge"), "config", text)
    except Exception as e:  # noqa: BLE001 - the history must never undo a saved change
        ctx["log_file"]("pellet layers: could not note the change in Activity: %s" % e)


def build(ctx):
    def list_(args, c):
        store, rev = _store()
        return {"profiles": [pl.summary(n, p) for n, p in sorted(store["profiles"].items())], "rev": rev}

    def get(args, c):
        store, rev = _store()
        name = args["name"]
        if name not in store["profiles"]:
            raise ApiError("invalid_args", M("pellet_layers_err_not_found", name=name), field="name")
        return {"name": name, "profile": store["profiles"][name], "rev": rev}

    def set_(args, c):
        try:
            name = pl.clean_name(args["name"])
            clean = pl.validate_profile(args["profile"])
        except pl.ProfileError as e:
            raise ApiError("invalid_args", e.errors[0]["message"], field=e.errors[0]["field"], errors=_errors(e))
        if run.armed_profile() == name:
            raise ApiError("conflict", M("pellet_layers_err_armed_profile", name=name))

        def change(profiles):
            if name not in profiles and len(profiles) >= pl.MAX_PROFILES:
                raise ApiError("invalid_args", M("pellet_layers_err_too_many", max=pl.MAX_PROFILES), field="name")
            profiles[name] = clean

        store, r = _save(change)
        if r["changed"]:
            _note(ctx, M("pellet_layers_saved", name=name))
        return {"name": name, "profile": clean, "rev": r["rev"], "changed": r["changed"]}

    def remove(args, c):
        name = args["name"]
        if run.armed_profile() == name:
            raise ApiError("conflict", M("pellet_layers_err_armed_profile", name=name))
        found = []

        def change(profiles):
            found[:] = [profiles.pop(name, None)]

        store, r = _save(change)
        if not found[0]:
            raise ApiError("invalid_args", M("pellet_layers_err_not_found", name=name), field="name")
        _note(ctx, M("pellet_layers_removed", name=name))
        return {"name": name, "rev": r["rev"]}

    def status(args, c):
        return run.status()

    def arm(args, c):
        who = identity.actor(c)
        try:
            out = run.arm(args["name"], args["file"], who)
        except pl.ProfileError as e:
            raise ApiError("failed", M("pellet_layers_store_invalid"), errors=_errors(e))
        except LookupError:
            raise ApiError("invalid_args", M("pellet_layers_err_not_found", name=args["name"]), field="name")
        except ValueError as e:
            raise ApiError("invalid_args", e.args[0])
        _note(ctx, M("pellet_layers_armed", name=args["name"], file=args["file"]))
        return out

    def disarm(args, c):
        was = run.armed_profile()
        out = run.disarm(identity.actor(c), record=lambda kind, text: activity.log_event(ctx.get("bridge"), kind, text))
        return dict(out, was_armed=was is not None)

    a = Arg
    return [
        Op("pelletlayers.list", list_, READ, {}, "The pellet temperature-by-layer profiles: {profiles: [{name, tool, heaters, mode, axis, points, first, last}], rev}.", log=False),
        Op("pelletlayers.get", get, READ, {"name": a("str", True, desc="Profile name.")},
           "One profile: {name, profile: {tool, heaters, mode, axis, max_temp, max_step, max_spread, points: [{at, temps}]}, rev}.", log=False),
        Op("pelletlayers.set", set_, WRITE,
           {"name": a("str", True, desc="Profile name (1 to 40 characters)."), "profile": a("obj", True, desc="The whole profile (see pelletlayers.get).")},
           "Validates and saves one profile (creates or replaces it). Saving never heats anything: a profile does nothing until it is armed for a job. "
           "Invalid fields answer invalid_args with one message per field. A profile that is armed cannot be changed."),
        Op("pelletlayers.remove", remove, WRITE, {"name": a("str", True, desc="Profile name.")}, "Deletes a profile (not while it is armed)."),
        Op("pelletlayers.status", status, READ, {},
           "The armed run: {armed, phase, profile, file, layer, applied, limited, changes, next, reason}. phase: off, waiting, waiting_heat, waiting_layer, "
           "running, holding, ended.", log=False),
        Op("pelletlayers.arm", arm, WRITE,
           {"name": a("str", True, desc="Profile name."), "file": a("str", True, desc="File name of the job it is armed for (job.file.fileName).")},
           "ARMS a profile for ONE job file: from then on, while that job is printing, the service sends M568 P<tool> S<temperatures> when the layer "
           "changes, always inside the limits of the profile and of each heater. It never switches a heater on or off. A pause holds; cancel, end or a "
           "refusal of the board disarm it and leave the temperatures as they are. It is dropped after an hour if the job never starts."),
        Op("pelletlayers.disarm", disarm, STOP, {},
           "Stops applying the profile now and leaves the temperatures as they are. Never blocked.", exclusive=False),
    ]
