"""Start-up summaries of the plugins (2026-10-24): readiness.report / readiness.list.

Each plugin computes its "Puesta en marcha" card in the browser (it needs the page's own data). To give a new person ONE
list of what is left, every card reports its totals here when they change, and the service page lists the plugins that
are installed with what each one last said. A plugin that was never opened has no entry: the list shows it as "not
checked yet", never as ready. An entry of a plugin that is no longer installed is simply not listed (the page filters).

Stored in 0:/sys/workshop/data/startup-summary.json: {"<PluginId>": {"pending": n, "total": n, "at": epoch seconds}}.
"""
import json
import os
import re
import threading
import time

import paths
from workshop_api import READ, WRITE, Arg, ApiError, Op

FILE = paths.DATA_DIR + "/startup-summary.json"
ID = re.compile(r"^Workshop[A-Za-z0-9]{1,40}$")
_lock = threading.Lock()


def load(route=None):
    try:
        with open(route or FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record(plugin, pending, total, route=None, now=None):
    """Stores the summary of one plugin. Returns True when it changed (a repeated report writes nothing)."""
    if not ID.match(str(plugin or "")):
        raise ValueError("plugin")
    pending, total = int(pending), int(total)
    if not (0 <= pending <= total <= 500):
        raise ValueError("counts")
    route = route or FILE
    with _lock:
        d = load(route)
        old = d.get(plugin) or {}
        if old.get("pending") == pending and old.get("total") == total:
            return False
        d[plugin] = {"pending": pending, "total": total, "at": int(now if now is not None else time.time())}
        os.makedirs(os.path.dirname(route), exist_ok=True)
        tmp = route + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, route)
    return True


def _report(args, ctx):
    try:
        changed = record(args["plugin"], args["pending"], args["total"])
    except ValueError as e:
        raise ApiError("invalid_args", "readiness.report: invalid " + str(e), field=str(e))
    return {"changed": changed}


def _list(args, ctx):
    return {"plugins": load()}


def ops():
    a = Arg
    return [
        Op("readiness.report", _report, WRITE,
           {"plugin": a("str", True, desc="Id of the plugin whose start-up card reports (Workshop...)."),
            "pending": a("int", True, min=0, max=500, desc="Rows still to configure (orange or red)."),
            "total": a("int", True, min=0, max=500, desc="Rows that apply to this machine.")},
           "A plugin's start-up card tells the service how many rows are pending, so the service page can list them all. "
           "Nothing is written when the numbers did not change.", log=False),
        Op("readiness.list", _list, READ, {},
           "What each plugin's start-up card last reported: {plugins: {Id: {pending, total, at}}}. A plugin that never reported is missing.", log=False),
    ]
