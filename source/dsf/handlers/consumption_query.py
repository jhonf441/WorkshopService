"""
Internal implementation of the API operation(s) energy.history (api_ops.py maps their named
arguments to the one-letter parameters below).

Paginated query of the FULL electric consumption history (table
"consumo" of db.py) for the real table of the WorkshopService plugin UI
(dwc-src/Consumption.vue) -- it replaces the "Consumption" tab that existed in
BtnCmd (a sliding-window BtnCmdChart of 30 min, with no retention,
which started empty again on every page load and gave no way to
see the complete history).

Usage: <params> D"2026-10-01" A"2026-10-07" [L50] [O0]
  D = from (ISO date, inclusive; "YYYY-MM-DD" or full "YYYY-MM-DDTHH:MM:SS")
  A = to (same, inclusive; a date without time is completed to end of day)
  L = rows per page (default 50, cap 200)
  O = offset for paging (default 0)

The answer is the JSON as a plain string (via resolve_code), like
activity_query.py -- it does not go through bridge.send(), so quotes
do not need escaping.

"""
import json

import db
from messages import M

MAX_LIMIT = 200


def run(params, bridge, config):
    since = str(params.get("D", "")).strip()
    until = str(params.get("A", "")).strip()
    limit = min(int(float(params.get("L", 50))), MAX_LIMIT)
    offset = max(int(float(params.get("O", 0))), 0)

    if not since:
        return json.dumps({"error": M("query_since_missing")})
    if not until:
        until = since

    if len(since) == 10:
        since += "T00:00:00"
    if len(until) == 10:
        until += "T23:59:59"

    # 2026-10-10: several meters. M"<key>" (without M = the main one) or M"total"
    # (sum of the own-line ones; the table shows the main one's).
    import meters
    lst = [m for m in meters.entries() if meters.configured(m)]
    prin = meters.main(lst)
    key = str(params.get("M", "")).strip().lower() or (prin["slot"] if prin else "general")
    if key == "total":
        own = [m["slot"] for m in meters.of_line_own(lst)] or ([prin["slot"]] if prin else ["general"])
        total, rows = db.consumption_query(since, until, limit=limit, offset=offset, meter=prin["slot"] if prin else "general")
        res = [db.consumption_span_summary(since, until, c) for c in own]
        res = [r for r in res if r]
        serial, step_s = db.consumption_serial_total(since, until, own)
        summary = None
        if res:
            pots = [p["power_w"] for p in serial if p["power_w"] is not None]
            summary = {"consumption_kwh": sum(r["consumption_kwh"] for r in res), "peak_w": max(pots) if pots else 0.0,
                       "average_w": sum(pots) / len(pots) if pots else 0.0, "samples": len(pots)}
    else:
        total, rows = db.consumption_query(since, until, limit=limit, offset=offset, meter=key)
        summary = db.consumption_span_summary(since, until, key)
        serial, step_s = db.consumption_serial(since, until, meter=key)
    return json.dumps({"total": total, "rows": rows, "summary": summary, "serial": serial, "serial_step_s": step_s, "meter": key})
