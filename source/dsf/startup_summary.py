"""Start-up summaries of the plugins (2026-10-24): readiness.report / readiness.list.

Each plugin computes its "Puesta en marcha" card in the browser (it needs the page's own data). To give a new person ONE
list of what is left, every card reports its totals here when they change, and the service page lists the plugins that
are installed with what each one last said. A plugin that was never opened has no entry: the list shows it as "not
checked yet", never as ready. An entry of a plugin that is no longer installed is simply not listed (the page filters).

Stored in 0:/sys/workshop/data/startup-summary.json: {"<PluginId>": {"pending": n, "total": n, "skipped": n (only when > 0), "at": epoch seconds}}.
pending / total count only what the person has to do: optional functions that are off and rows marked "Do not use" are not in them; they are
reported apart as skipped ("N optional not in use"), so a card with only skipped rows is ready (2026-11-20).
"""
import json
import os
import re
import threading
import time

import paths
from workshop_api import READ, WRITE, Arg, ApiError, Op

# ---- the three outcomes of a row (2026-11-20): ready, pending, not in use ----
# The page of each plugin sends its rows as they are ({id, state, optional}: state = what the machine says, BEFORE any decision) and the ids the
# person put away ("Do not use"). The service applies the decisions itself every time it answers, with the same rules as vue/_shared36/startup.js
# (tests/startup-optional.test.js and dsf/test_startup_summary.py share the cases), so a decision made in the plugin, in another browser or in the
# settings file "startup" is seen at once by the Machine setup page and the home, even if the plugin page is not open.
RAW_STATES = ("configured", "example", "missing", "session", "na")
MAX_ROWS = 200


def summarize(rows, omitted):
    """{total, pending, session, skipped, extra}: skipped = rows the person does not use (chosen, or optional and still off); extra = optional
    rows that work; total counts neither. Only a row that is still to do can be skipped; one that works stays ready."""
    omitted = set(omitted or ())
    steps = skipped = extra = pending = session = 0
    for r in rows or ():
        state = r.get("state")
        if state == "na":
            continue
        optional = bool(r.get("optional"))
        if state in ("example", "missing", "session"):
            if r.get("id") in omitted or (optional and state == "example"):
                skipped += 1
                continue
        if optional and state == "configured":
            extra += 1
            continue
        steps += 1
        if state in ("example", "missing"):
            pending += 1
        elif state == "session":
            session += 1
    return {"total": steps, "pending": pending, "session": session, "skipped": skipped, "extra": extra}


def decisions(plugin, route=None):
    """The ids of the plugin that the person chose not to use, from the settings file "startup" ({"<PluginId>": [ids]}). Read as a plain file, like
    load(): the file is written by settings.merge (settings_store.py), and importing that module from here would make a cycle."""
    try:
        with open(route or DECISIONS, encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return []
    ids = v.get(plugin) if isinstance(v, dict) else None
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def _clean_rows(rows):
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("rows")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not (0 < len(r["id"]) <= 80) or r.get("state") not in RAW_STATES:
            raise ValueError("rows")
        out.append({"id": r["id"], "state": r["state"], "optional": bool(r.get("optional"))})
    return out


def _clean_ids(ids):
    if not isinstance(ids, list) or len(ids) > MAX_ROWS or not all(isinstance(i, str) and 0 < len(i) <= 80 for i in ids):
        raise ValueError("omitted")
    return ids

FILE = paths.DATA_DIR + "/startup-summary.json"
DECISIONS = paths.CONFIG_DIR + "/startup.json"  # settings name "startup"
ID = re.compile(r"^Workshop[A-Za-z0-9]{1,40}$")
_lock = threading.Lock()


def load(route=None):
    try:
        with open(route or FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record(plugin, pending, total, route=None, now=None, skipped=0, rows=None, omitted=None):
    """Stores the summary of one plugin. Returns True when it changed (a repeated report writes nothing)."""
    if not ID.match(str(plugin or "")):
        raise ValueError("plugin")
    pending, total, skipped = int(pending), int(total), int(skipped or 0)
    if not (0 <= pending <= total <= 500):
        raise ValueError("counts")
    if not 0 <= skipped <= 500:
        raise ValueError("skipped")
    route = route or FILE
    with _lock:
        d = load(route)
        old = d.get(plugin) or {}
        if rows is not None:
            rows = _clean_rows(rows)
            omitted = _clean_ids(omitted if omitted is not None else [])
        if old.get("pending") == pending and old.get("total") == total and old.get("skipped", 0) == skipped and old.get("rows") == rows and old.get("omitted") == omitted:
            return False
        d[plugin] = {"pending": pending, "total": total, "at": int(now if now is not None else time.time())}
        if skipped:
            d[plugin]["skipped"] = skipped
        if rows is not None:
            d[plugin]["rows"] = rows
            d[plugin]["omitted"] = omitted
        os.makedirs(os.path.dirname(route), exist_ok=True)
        tmp = route + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, route)
    return True


def _report(args, ctx):
    try:
        changed = record(args["plugin"], args["pending"], args["total"], skipped=args.get("skipped") or 0, rows=args.get("rows"), omitted=args.get("omitted"))
    except ValueError as e:
        raise ApiError("invalid_args", "readiness.report: invalid " + str(e), field=str(e))
    return {"changed": changed}


def listing(data=None, decided=None):
    """What readiness.list answers: for a plugin that sent its rows the counts are worked out NOW from them and the decisions (the ones it sent
    with them plus the ones of the settings file); an older report without rows keeps the counts it sent. Rows themselves are not returned."""
    out = {}
    for plugin, e in (load() if data is None else data).items():
        e = dict(e)
        rows = e.pop("rows", None)
        sent = e.pop("omitted", None) or []
        if rows is not None:
            now = (decided or decisions)(plugin)
            s = summarize(rows, list(sent) + [i for i in now if i not in sent])
            e["pending"], e["total"] = s["pending"], s["total"]
            e.pop("skipped", None)
            if s["skipped"]:
                e["skipped"] = s["skipped"]
        out[plugin] = e
    return out


def _list(args, ctx):
    return {"plugins": listing()}


def ops():
    a = Arg
    return [
        Op("readiness.report", _report, WRITE,
           {"plugin": a("str", True, desc="Id of the plugin whose start-up card reports (Workshop...)."),
            "pending": a("int", True, min=0, max=500, desc="Rows still to configure (orange or red), never an optional one that is off."),
            "total": a("int", True, min=0, max=500, desc="Rows that are steps of the person (optional ones that are off or not in use are not counted)."),
            "skipped": a("int", False, min=0, max=500, desc="Optional rows that are off or that the person chose not to use (not steps to do). Omitted = 0."),
            "rows": a("obj", False, desc="The rows as the machine says them, before any decision: [{id, state: configured|example|missing|session|na, optional}]. With them the service recounts every time it is asked, applying the decisions of the settings file startup."),
            "omitted": a("obj", False, desc="The ids the page had put away when it reported (list of strings).")},
           "A plugin's start-up card tells the service how many rows are pending, so the service page can list them all. "
           "Nothing is written when the numbers did not change.", log=False),
        Op("readiness.list", _list, READ, {},
           "What each plugin's start-up card last reported: {plugins: {Id: {pending, total, skipped?, at}}}. A plugin that never reported is missing.", log=False),
    ]
