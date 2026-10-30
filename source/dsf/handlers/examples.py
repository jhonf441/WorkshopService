"""
Internal implementation of the API operation(s) examples.list, examples.create (api_ops.py maps their named
arguments to the one-letter parameters below).

The example files that a plugin offers once (examples.py): which ones it has and in what state, and the creation of the
ones that are missing. Nothing already on the SD is ever overwritten.

    <params> C"lista" P"<PluginId>"
    <params> C"crear" P"<PluginId>" [F"<destination>"]   (F: create that one again even if it was created before)
"""
import json

import examples


def run(params, bridge, config):
    action = str(params.get("C", "list")).strip().lower()
    plugin = str(params.get("P", "")).strip()
    if not plugin or "/" in plugin or "\\" in plugin or ".." in plugin:
        return json.dumps({"ok": False, "error": "plugin id needed"})
    if action == "create":
        f = str(params.get("F", "")).strip()
        r = examples.install(plugin, recreate=[f] if f else None)
        r["ok"] = True
        r["files"] = examples.list_items(plugin)
        return json.dumps(r)
    return json.dumps({"ok": True, "files": examples.list_items(plugin)})
