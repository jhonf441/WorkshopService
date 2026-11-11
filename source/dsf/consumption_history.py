"""Electric consumption history behind the operation energy.history (energy_ops.py registers it; phase 5 of the redesign, it
replaces handlers/consumption_query.py).

A paginated read of the "consumption" table of db.py for the table of the Power page, with a summary and the power series of
the whole range. Named, already validated arguments in, the dict of the answer out. A missing start date is an answer with an
`error` text, as it always was, not an ApiError.
"""
import db
import meters
from messages import M


def _span(since, until):
    """The range as ISO date-times: a date alone starts at 00:00:00 and ends at 23:59:59; no end means the day of the start."""
    since = str(since).strip()
    until = str(until).strip() or since
    if len(since) == 10:
        since += "T00:00:00"
    if len(until) == 10:
        until += "T23:59:59"
    return since, until


def _total(since, until, limit, offset, configured):
    """meter "total": the table shows the main meter, the numbers add up the meters that are on their own line."""
    main = meters.main(configured)
    main_slot = main["slot"] if main else "general"
    own = [m["slot"] for m in meters.of_line_own(configured)] or [main_slot]
    total, rows = db.consumption_query(since, until, limit=limit, offset=offset, meter=main_slot)
    spans = [r for r in (db.consumption_span_summary(since, until, slot) for slot in own) if r]
    serial, step_s = db.consumption_serial_total(since, until, own)
    summary = None
    if spans:
        watts = [p["power_w"] for p in serial if p["power_w"] is not None]
        summary = {"consumption_kwh": sum(r["consumption_kwh"] for r in spans), "peak_w": max(watts) if watts else 0.0,
                   "average_w": sum(watts) / len(watts) if watts else 0.0, "samples": len(watts)}
    return total, rows, summary, serial, step_s


def history(*, since, until="", limit=50, offset=0, meter=""):
    """Rows (one page), summary and power series of a meter over a range. meter: its key (empty: the main one, the one that feeds
    the system) or "total"."""
    limit = min(int(limit), 200)
    offset = max(int(offset), 0)
    since, until = _span(since, until)
    if not since:
        return {"error": M("query_since_missing")}
    configured = [m for m in meters.entries() if meters.configured(m)]
    main = meters.main(configured)
    key = str(meter).strip().lower() or (main["slot"] if main else "general")
    if key == "total":
        total, rows, summary, serial, step_s = _total(since, until, limit, offset, configured)
    else:
        total, rows = db.consumption_query(since, until, limit=limit, offset=offset, meter=key)
        summary = db.consumption_span_summary(since, until, key)
        serial, step_s = db.consumption_serial(since, until, meter=key)
    return {"total": total, "rows": rows, "summary": summary, "serial": serial, "serial_step_s": step_s, "meter": key}
