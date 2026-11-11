"""How each internal process of the service runs, behind the operations modules.list and modules.set (service_ops.py registers them;
phase 5 of the redesign, it replaces handlers/service_modules.py).

Which internal processes run is decided by service_modules.py: each one starts only when a plugin that needs it is enabled in DWC,
unless the user forces it on or off here. The choice is kept in config["modules"] ({process: "on" | "off"}; "auto" is the absence).
Both answers are dicts that carry their own `ok`: a refused change is {"ok": False, "error": ...} (an answer, not an ApiError).
"""
import process_catalog
import service_modules
from messages import M


def listing():
    """Every process with its mode, whether it runs now and why."""
    return {"ok": True, "modules": service_modules.status()}


def set_mode(bridge, config, *, process, mode):
    """Forces a process on or off, or gives it back to "auto" (process: its id as listed; mode: auto, on or off)."""
    pid = str(process).strip()
    kind = str(mode).strip().lower()
    if pid not in service_modules.PROCESSES and pid not in service_modules.SAFETY and pid not in service_modules.OWN and pid != "subscription":
        return {"ok": False, "error": "unknown process"}
    if kind not in service_modules.MODES:
        return {"ok": False, "error": "mode must be auto, on or off"}
    settings = config.setdefault("modules", {})
    # a locked process (safety group and the ones the service stands on) has no switch; "auto" is still accepted to drop an old
    # stored on/off of it (back to the default is always the safe direction)
    if process_catalog.is_locked(pid) and not (kind == "auto" and pid in settings):
        return {"ok": False, "error": M("modules_process_locked", process=pid)}
    if kind == "auto":
        settings.pop(pid, None)
    else:
        settings[pid] = kind
    service_modules.set_settings(settings)
    bridge.save_config()
    status = service_modules.status()
    return {"ok": True, "modules": status, "process": pid, "status": status.get(pid)}
