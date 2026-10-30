"""
Internal implementation of the API operation(s) history.list, history.delete (api_ops.py maps their named
arguments to the one-letter parameters below).

History of received commands (calls to the services' API) for the Activity page.
They are stored masked: without the meter key, without long hex JSONs, and
without the response of consumo_medidor. 30 days are kept (max 20000).

Usage: <params> D"2026-10-01" A"2026-10-09" [N"<name>"] [E1] [Q"<text>"] [L50] [O0]
  N = only one command (e.g. "trabajo", "luces"); E1 = only those that failed;
  Q = search text in the code or the response; R1 = only those that change something,
  R2 = only reads; V"<via>" = only those that arrived that way
  Origin filters (2026-10-12): G"<channel>" (HTTP, SBC, Aux...), T"<kind>" (page, console, job_file,
  macro, bridge, service, external...), Y"<plugin or page tag>", Z"<ok|error|blocked>"; "-" = rows
  without that data (saved before the origin existed). The answer also has "last_hour": counters
  per kind / channel / plugin / result of the last hour (memory ring).
     <params> C"borrar" D"..." A"..."   -> deletes that range

"""
import json

import db
import origin_track
from messages import M

MAX_LIMIT = 200


def _span(params):
    since = str(params.get("D", "")).strip()
    until = str(params.get("A", "")).strip() or since
    if len(since) == 10:
        since += "T00:00:00"
    if len(until) == 10:
        until += "T23:59:59"
    return since, until


def run(params, bridge, config):
    since, until = _span(params)
    if not since:
        return json.dumps({"error": M("query_since_missing")})
    if str(params.get("C", "")).strip().lower() == "remove":
        n = db.commands_delete(since, until)
        return json.dumps({"ok": True, "deleted": n})
    try:
        limit = min(int(float(params.get("L", 50))), MAX_LIMIT)
        offset = max(int(float(params.get("O", 0))), 0)
    except (TypeError, ValueError):
        limit, offset = 50, 0
    label = str(params.get("N", "")).strip() or None
    raw_text = str(params.get("Q", "")).strip() or None
    try:
        only_err = int(float(params.get("E", 0))) == 1
    except (TypeError, ValueError):
        only_err = False
    try:
        type_name = int(float(params.get("R", 0)))  # 0 all, 1 changes, 2 reads
    except (TypeError, ValueError):
        type_name = 0
    via = str(params.get("V", "")).strip() or None
    channel = str(params.get("G", "")).strip() or None
    kind = str(params.get("T", "")).strip() or None
    plugin = str(params.get("Y", "")).strip() or None
    result = str(params.get("Z", "")).strip() or None
    total, errors, rows, names, summary = db.commands_query(since, until, label, only_err, raw_text, limit, offset, type_name, via,
                                                               channel, kind, plugin, result)
    return json.dumps({"total": total, "errors": errors, "rows": rows, "names": names, "summary": summary,
                       "last_hour": origin_track.counters()}, ensure_ascii=False)
