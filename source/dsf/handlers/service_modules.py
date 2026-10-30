"""
Internal implementation of the API operation(s) modules.list, modules.set (api_ops.py maps their named arguments to
the one-letter parameters below).

Which internal processes of the service run (service_modules.py): each one starts only when a plugin that needs it is enabled in
DWC, unless the user forces it on or off here. The choice is kept in config["modulos"].

    <params> C"lista"
    <params> C"fijar" P"<process>" M"auto"|"on"|"off"
"""
import json

import service_modules


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
        if kind == "auto":
            settings.pop(pid, None)
        else:
            settings[pid] = kind
        service_modules.set_settings(settings)
        bridge.save_config()
    return json.dumps({"ok": True, "modules": service_modules.status()})
