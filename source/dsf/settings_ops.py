"""API operations settings.get / settings.set / settings.merge (F1-B): the shared settings files with a revision.
The store itself is settings_store.py; this file only maps it to the API and notes the change in Activity."""
import activity
import settings_store as store
from messages import M
from workshop_api import READ, WRITE, Arg, ApiError, Op


def _log(ctx, name):
    try:
        activity.log_event(ctx.get("bridge"), "config", M("settings_changed", name=name))
    except Exception as e:  # the record must never undo a saved change
        ctx["log_file"](f"settings: could not note the change of {name} in Activity: {e}")


def _wrap(fn):
    try:
        return fn()
    except store.SettingsError as e:
        raise ApiError("invalid_args", str(e), field="name")
    except store.Conflict as c:
        raise ApiError("conflict", "the settings changed since they were read", current={"value": c.value, "rev": c.rev})


def _not_service_only(name):
    if name in store.SERVICE_ONLY:
        raise ApiError("forbidden", "this settings file is written by the service itself, not through settings.set / settings.merge")


def build(ctx):
    """The operations; ctx is api_ops._ctx (bridge, log_file)."""
    def get(args, c):
        return _wrap(lambda: store.get(args["name"]))

    def set_(args, c):
        _not_service_only(args["name"])
        r = _wrap(lambda: store.set(args["name"], args["value"], args["base_rev"]))
        if r["changed"]:
            _log(ctx, args["name"])
        return r

    def merge(args, c):
        _not_service_only(args["name"])
        r = _wrap(lambda: store.merge(args["name"], args["patch"]))
        if r["changed"]:
            _log(ctx, args["name"])
        return r

    d_name = "Settings file: one of " + ", ".join(sorted(store.NAMES)) + " (a name, never a path)."
    return [
        Op("settings.get", get, READ, {"name": Arg("str", True, desc=d_name)},
           "Reads a shared settings file and its revision: {value, rev}. value is null and rev \"0\" when the file does not exist yet.", log=False),
        Op("settings.set", set_, WRITE,
           {"name": Arg("str", True, desc=d_name), "value": Arg("obj", True, desc="The whole new content (object or list)."),
            "base_rev": Arg("str", True, desc="The rev returned by settings.get (\"0\" for a file that does not exist yet).")},
           "Writes a shared settings file only if nobody changed it since base_rev was read; otherwise it answers the error "
           "'conflict' with error.current = {value, rev} so the caller can merge and retry. Returns {rev, changed}. Noted in Activity."),
        Op("settings.merge", merge, WRITE,
           {"name": Arg("str", True, desc=d_name), "patch": Arg("obj", True, desc="Object whose top-level keys replace those of the file.")},
           "Sets only some top-level keys of a shared settings file, with no revision check (for fields that do not clash with the work of "
           "others). Returns {value, rev, changed}. Noted in Activity."),
    ]
