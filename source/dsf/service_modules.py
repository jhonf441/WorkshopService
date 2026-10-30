"""
Service modules that depend on their plugin being ACTIVE
(2026-10-12, items 17 and 27 of the diagnosis): if the user stops or
disables a plugin in Settings > Plugins, the part of the service that works
for it goes idle (it paints nothing, sends nothing); when it is reactivated
it runs again on its own.

    import service_modules
    if service_modules.is_active("WorkshopLights"): ...

Signal: the machine.enabledPlugins list of 0:/sys/dwc-settings.json. It is
what DWC changes when pressing Start/Stop (DSF's object model has no
"active" flag for plugins that only have a DWC part, and "plugins" is
outside the common subscription of machine_state). The file is read from
disk (without asking DSF or DuetWebServer for anything): one os.stat every
TTL_S and the JSON only if the file's date changed.

When in doubt the module STAYS active: file missing, unreadable or without
the list (development PC, DWC not yet having saved its settings). It only
turns off when the file has the list and the plugin is not in it.

For a new module: make its
loop call is_active(Id) at the beginning of each pass.

"""
import paths
import json
import os
import threading
import time

PATH_SETTINGS = paths.DWC_SETTINGS
TTL_S = 3.0

LIGHTS = "WorkshopLights"  # "Lights and states" on screen
CAMERA = "WorkshopCamera"  # camera relay, timelapse and watchdog
POWER = "WorkshopPower"  # consumption meter reader
MOTORS = "WorkshopMotors"  # driver polling
VISION = "WorkshopVision"  # uses the camera relay
RS485 = "WorkshopRS485"  # servo alarm pause (own backend process)
WORKBENCH = "WorkshopWorkbench"  # its camera layer uses the relay
ACTIVITY = "WorkshopActivity"  # history, board events and phone notices
HEALTH = "WorkshopPiHealth"  # Pi watchdog
JOG = "WorkshopJog"  # jog engine
BAR = "WorkshopControlBar"  # shutdown with timer
CONFIGURATOR = "WorkshopConfig"  # configuration rollback
MACHINE = "WorkshopMachine"  # maintenance counters
PRINTING = "WorkshopPrinting"  # record of the PID tuning (pid_trace.py)

# Each internal process of the service and the DWC plugins that need it (any of them enabled is enough). A process
# that is not listed here (the G-code interception, the black box, the single subscription) has its own rule below.
# THE PROTOCOL (so the service does nothing that nobody uses): a process STARTS only when a plugin that needs it is
# enabled in DWC (Settings > Plugins) or when the user forced it on; the supervisor of heartbeats.py keeps it at rest until
# then and starts it by itself when it becomes needed. A forced-off process does not start at the next restart. The
# user can change each one in the service page (config "modulos": {process: "auto" | "on" | "off"}).
PROCESSES = {
    "status_light": (LIGHTS,),
    "consumption": (POWER,),
    "motors": (MOTORS,),
    "camera": (CAMERA, VISION, WORKBENCH),
    "trace": (WORKBENCH,),
    "jog": (JOG, WORKBENCH, VISION),
    "timer": (BAR,),
    "maintenance": (MACHINE,),
    "pid_trace": (PRINTING,),
}
# Safety processes are NEVER gated by plugins (CLAUDE.md: "Safety modules are never gated"): in "auto" they always run.
# Only an explicit "off" of the user in config "modulos" stops them.
SAFETY = ("events", "jobs", "risk", "config_guard", "motion", "health", "guard")
MODES = ("auto", "on", "off")

# Processes whose rule in "auto" is not a plugin but a setting of the service itself:
# the G-code interceptor (main.py) connects to DSF only while the automatic air is on.
OWN = ("interceptor",)
_rule_own = {}


def set_rule(label, function):
    """main.py tells here when a PROPIOS process is needed in auto mode (funcion() -> bool)."""
    _rule_own[label] = function

_lock = threading.Lock()
_path = [PATH_SETTINGS]
_clock = [time.monotonic]
_cache = {"seen": -1e9, "signature": None, "list": None}


def configure(route=None, clock=None):
    """For tests only: another path / another clock, and it empties the cache."""
    with _lock:
        _path[0] = route or PATH_SETTINGS
        _clock[0] = clock or time.monotonic
        _cache.update(seen=-1e9, signature=None, list=None)


def _read_items(route):
    """Union of the enabledPlugins lists of the file, or None if they are not there."""
    with open(route, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return None
    entries = None
    for key in ("machine", "main"):
        sec = payload.get(key)
        l = sec.get("enabledPlugins") if isinstance(sec, dict) else None
        if isinstance(l, list):
            entries = (entries or set()) | {str(x) for x in l}
    return entries


def enabled():
    """Set of Ids enabled in DWC, or None if unknown. Cached."""
    current_time = _clock[0]()
    with _lock:
        if current_time - _cache["seen"] < TTL_S:
            return _cache["list"]
        _cache["seen"] = current_time
        route = _path[0]
        try:
            st = os.stat(route)
            signature = (st.st_mtime_ns, st.st_size)
            if signature != _cache["signature"]:
                _cache["list"] = _read_items(route)
                _cache["signature"] = signature
        except (OSError, ValueError):
            # file half-written: the last thing known is kept;
            # no file: it is not known
            if not os.path.exists(route):
                _cache["list"] = None
                _cache["signature"] = None
        return _cache["list"]


def is_active(plugin_id):
    """True if the plugin is enabled (or it cannot be known)."""
    entries = enabled()
    if entries is None:
        return True
    return any(i in entries for i in (plugin_id,))


# ---- the user's choice for each process ----

_settings = [{}]   # reference to config["modulos"]; set once by main.py


def set_settings(d):
    """d = the dict config["modulos"] (read live, so a change saved by the page applies at once)."""
    _settings[0] = d if isinstance(d, dict) else {}


def kind(process):
    m = str(_settings[0].get(process) or "auto").lower()
    return m if m in MODES else "auto"


def needs_state():
    """The single subscription to the machine state runs only while some process that reads it can run."""
    return any(process(p) for p in list(PROCESSES) + list(SAFETY))


def process(label):
    """Should this internal process run? (forced on / off, or its plugins enabled)"""
    if label == "subscription":
        return needs_state()
    m = kind(label)
    if m == "on":
        return True
    if m == "off":
        return False
    if label in OWN:
        f = _rule_own.get(label)
        return bool(f()) if f else True
    if label in SAFETY:
        return True
    ids = PROCESSES.get(label)
    if not ids:
        return True
    return any(is_active(i) for i in ids)


def reason(label):
    """Why it runs or rests: {"codigo", "plugins"} for the page to translate."""
    m = kind(label)
    if label == "subscription":
        return {"code": "on_demand", "plugins": []}
    if m == "on":
        return {"code": "forced_on", "plugins": []}
    if m == "off":
        return {"code": "forced_off", "plugins": []}
    if label in OWN:
        return {"code": "air_auto" if process(label) else "without_air_auto", "plugins": []}
    if label in SAFETY:
        return {"code": "safety", "plugins": []}
    ids = PROCESSES.get(label)
    if not ids:
        return {"code": "always", "plugins": []}
    return {"code": "plugin_active" if process(label) else "plugin_inactive", "plugins": list(ids)}


def status():
    """{process: {modo, activo, razon}} for the service page."""
    out = {}
    for p in list(PROCESSES) + list(SAFETY) + list(OWN) + ["subscription"]:
        out[p] = {"mode": kind(p), "active": process(p), "reason": reason(p)}
    return out
