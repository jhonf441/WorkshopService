"""
Internal implementation of the API operation(s) modules.list, modules.set (api_ops.py maps their named arguments to
the one-letter parameters below).

Which internal processes of the service run (service_modules.py): each one starts only when a plugin that needs it is enabled in
DWC, unless the user forces it on or off here. The choice is kept in config["modulos"].

    <params> C"lista"
    <params> C"fijar" P"<process>" M"auto"|"on"|"off"
"""
import json

import process_catalog
import service_modules
from messages import M


def run(params, bridge, config):
    action = str(params.get("C", "list")).strip().lower()
    if action == "set":
        pid = str(params.get("P", "")).strip()
        kind = str(params.get("M", "")).strip().lower()
        if pid not in service_modules.PROCESSES and pid not in service_modules.SAFETY and pid not in service_modules.OWN and pid != "subscription":
            return json.dumps({"ok": False, "error": "unknown process"})
        if kind not in service_modules.MODES:
            return json.dumps({"ok": False, "error": "mode must be auto, on or off"})
        settings = config.setdefault("modules", {})
        # a locked process (safety group and the ones the service stands on) has no switch; "auto" is still accepted to drop an old
        # stored on/off of it (back to the default is always the safe direction)
        if process_catalog.is_locked(pid) and not (kind == "auto" and pid in settings):
            return json.dumps({"ok": False, "error": M("modules_process_locked", process=pid)})
        if kind == "auto":
            settings.pop(pid, None)
        else:
            settings[pid] = kind
        service_modules.set_settings(settings)
        bridge.save_config()
    status = service_modules.status()
    result = {"ok": True, "modules": status}
    if action == "set":
        result["process"] = pid
        result["status"] = status.get(pid)
    return json.dumps(result)
