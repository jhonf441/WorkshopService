"""
Internal implementation of the API operation(s) activity.list, activity.delete, activity.clear (api_ops.py maps their named
arguments to the one-letter parameters below).

Paginated, filterable query of the activity history (table
"actividad" of db.py) for the real table of the WorkshopService plugin UI
(dwc-src/WorkshopService.vue) -- unlike activity_report.py (which
builds a summary text for a BtnCmd panel), this returns raw JSON
so the frontend renders a table with real pagination, which is
what BtnCmd's text-only panels cannot offer once there are
too many events to see them all at once.

Usage: <params> D"2026-10-01" A"2026-10-07" [T"job_end"] [L50] [O0]
  D = from (ISO date, inclusive; "YYYY-MM-DD" or full "YYYY-MM-DDTHH:MM:SS")
  A = to (same, inclusive; a date without time is completed to end of day)
  T = type (optional, exact filter: job_start/job_end/power/config/modo/sistema)
  L = rows per page (default 50, cap 200)
  O = offset for paging (default 0)
  X = types to exclude, separated by commas (e.g. X"servicio" to hide
      the service restarts)
  Q = text to search in the description, the type or the detail (2026-10-13)
  W = only the events of this user name; E = 1: only the events of the person of the session (open mode: no filter)

Delete (2026-10-09, Activity page):
  <params> C"borrar" I<id>                 -> one event
  <params> C"limpiar" D.. A.. [T..] [X..]  -> everything filtered
  (C/I and not M: inside an M-code "M.." would run as another command)

The answer is the JSON as a plain string (via resolve_code) -- it does not go
through bridge.send(), so quotes do not need escaping as in other
handlers that build "set global.x = ...".

"""
import json

import db
import identity
import messages
from messages import M

MAX_LIMIT = 200


def run(params, bridge, config):
    action = str(params.get("C", "")).strip().lower()
    if action == "remove":
        try:
            n = db.activity_delete([int(float(params.get("I")))])
        except (TypeError, ValueError):
            return json.dumps({"error": M("activity_query_id_missing")})
        return json.dumps({"deleted": n})
    since = str(params.get("D", "")).strip()
    until = str(params.get("A", "")).strip()
    type_name = str(params.get("T", "")).strip() or None
    limit = min(int(float(params.get("L", 50))), MAX_LIMIT)
    offset = max(int(float(params.get("O", 0))), 0)
    exclude = [t.strip() for t in str(params.get("X", "")).split(",") if t.strip()]
    raw_text = str(params.get("Q", "")).strip()[:80] or None
    # W = only the events of this person; E = "mine": the person of the session (identity.current(); without users, open mode, nothing is filtered)
    user = str(params.get("W", "")).strip()[:60] or None
    if not user and str(params.get("E", "0")).strip() in ("1", "true", "True"):
        who = identity.current()  # the person of the session (None in open mode and for programs)
        user = who["name"] if who else None

    if not since:
        return json.dumps({"error": M("query_since_missing")})
    if not until:
        until = since

    if len(since) == 10:
        since += "T00:00:00"
    if len(until) == 10:
        until += "T23:59:59"

    if action == "summary":
        res = db.activity_summary(since, until, exclude=exclude, user=user)
        for row in res["jobs"] + res["faults"]:
            row["description_en"] = messages.in_language(row.get("description"), row.get("message_key"), row.get("message_params"), "en")
        return json.dumps(res)

    if action == "clean":
        n = db.activity_delete_where(since, until, type_name=type_name, exclude=exclude, raw_text=raw_text)
        return json.dumps({"deleted": n})

    total, rows = db.activity_query(since, until, type_name=type_name, limit=limit, offset=offset, exclude=exclude, raw_text=raw_text, user=user)
    # the history keeps the Spanish text and the key + parameters of each message; the page shows description_en when DWC is in English.
    # message_key / message_params stay in the rows: the pages decide by key (event-kinds.js isCancelledEvent)
    for r in rows:
        if isinstance(r, dict) and r.get("description"):
            r["description_en"] = messages.in_language(r["description"], r.get("message_key"), r.get("message_params"), "en")
    return json.dumps({"total": total, "rows": rows, "kinds": db.activity_kinds()})
