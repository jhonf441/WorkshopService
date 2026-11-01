"""Plugins the person stopped on purpose: `plugins.stopped.get` / `plugins.stopped.set`.

DWC takes a plugin out of `machine.enabledPlugins` when it cannot load it, and the kiosk script (kiosk/ensure-emergencyfab.sh) puts the
plugins that are missing back. A plugin that a person stops from the page looks exactly the same from that list, so the page records it here
and the script leaves it alone.

File: `0:/sys/workshop/data/stopped-plugins.json`, `{"v": 1, "stopped": ["WorkshopCamera", ...]}` (sorted). The script reads it from the SD folder
of the Pi (see STOPPED_FILE in the script). Only ids of the workshop plugins are kept: they start
with "Workshop". A missing or damaged file means that nothing was stopped on purpose (the script behaves as before).
"""
import json
import re
import threading

import fs_atomic
import paths
from messages import M
from workshop_api import READ, WRITE, Arg, ApiError, Op

FILE = paths.DATA_DIR + "/stopped-plugins.json"
VERSION = 1
PLUGIN_ID = re.compile(r"^Workshop[A-Za-z0-9_]{1,60}$")
_lock = threading.Lock()


def read():
    """Sorted ids stopped on purpose; empty when the file is missing or not what this module writes."""
    try:
        with open(FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return []
    ids = doc.get("stopped") if isinstance(doc, dict) else None
    if not isinstance(ids, list):
        return []
    return sorted({x for x in ids if isinstance(x, str) and PLUGIN_ID.match(x)})


def set_stopped(plugin_id, stopped):
    """Records (or forgets) that `plugin_id` was stopped on purpose. Returns {stopped: [ids], changed: bool}."""
    if not isinstance(plugin_id, str) or not PLUGIN_ID.match(plugin_id):
        raise ApiError("invalid_args", M("stopped_plugins_invalid_id", id=str(plugin_id)[:70]), field="id")
    with _lock:
        ids = set(read())
        before = set(ids)
        if stopped:
            ids.add(plugin_id)
        else:
            ids.discard(plugin_id)
        out = sorted(ids)
        if ids != before:
            fs_atomic.write_json(FILE, {"v": VERSION, "stopped": out}, indent=1)
        return {"stopped": out, "changed": ids != before}


def _get_op(args, ctx):
    return {"stopped": read()}


def _set_op(args, ctx):
    return set_stopped(args["id"], bool(args["stopped"]))


def ops():
    return [
        Op("plugins.stopped.get", _get_op, READ, {},
           "Ids of the workshop plugins that a person stopped on purpose (the kiosk does not put them back in the enabled list). "
           "Returns {stopped: [ids]}.", log=False),
        Op("plugins.stopped.set", _set_op, WRITE,
           {"id": Arg("str", True, desc="Id of the plugin; only the workshop plugins (they start with Workshop, for example WorkshopCamera)."),
            "stopped": Arg("bool", True, desc="true records that the plugin was stopped on purpose; false forgets it (the plugin was started again).")},
           "Records that a plugin was stopped on purpose (or started again) so kiosk/ensure-emergencyfab.sh does not reactivate it. An operator may. "
           "Returns {stopped: [ids], changed}; an id that is not a workshop plugin answers invalid_args."),
    ]
