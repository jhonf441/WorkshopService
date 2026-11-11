"""History of the calls received by the service, behind the operations history.list and history.delete
(activity_ops.py registers them; phase 5 of the redesign, they replace handlers/commands_query.py).

The calls are stored masked (no meter key, no long hex JSON, no answer of the consumption meter) for 30 days, at most 20000 rows
(db.command_insert). Named, already validated arguments in, the dict of the answer out. A missing start date is an answer with an
`error` text, as it always was, not an ApiError.
"""
import db
import origin_track
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


def list_calls(*, since, until="", name="", errors=False, query="", limit=50, offset=0, rw=0, via="", channel="", kind="", plugin="",
               result=""):
    """One page of the received calls of a range, newest first, with the counters of the range and of the last hour.
    rw: 0 every call, 1 only the ones that change something, 2 only reads. A "-" in channel, kind, plugin or result means the rows
    saved without origin data."""
    since, until = _span(since, until)
    if not since:
        return {"error": M("query_since_missing")}
    total, error_count, rows, names, summary = db.commands_query(
        since, until, str(name).strip() or None, bool(errors), str(query).strip() or None, min(int(limit), 200), max(int(offset), 0),
        int(rw), str(via).strip() or None, str(channel).strip() or None, str(kind).strip() or None, str(plugin).strip() or None,
        str(result).strip() or None)
    return {"total": total, "errors": error_count, "rows": rows, "names": names, "summary": summary,
            "last_hour": origin_track.counters()}


def delete_calls(*, since, until=""):
    """Deletes the received calls of a range from the history."""
    since, until = _span(since, until)
    if not since:
        return {"error": M("query_since_missing")}
    return {"ok": True, "deleted": db.commands_delete(since, until)}
