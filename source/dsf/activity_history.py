"""Activity history queries behind the operations activity.list, activity.delete, activity.clear and activity.summary
(api_ops.py registers them; phase 5 of the redesign, they replace handlers/activity_query.py).

Paginated, filterable reads of the "activity" table of db.py for the table of the service page. Every function takes named,
already validated arguments and returns the dict the operation answers with. A missing start date is an answer with an
`error` text, as it always was (the page shows it), not an ApiError.
"""
import db
import messages
from messages import M

MAX_LIMIT = 200


def _span(since, until):
    """The range as ISO date-times: a date alone starts at 00:00:00 and ends at 23:59:59; no end means the day of the start."""
    since = str(since).strip()
    until = str(until).strip() or since
    if len(since) == 10:
        since += "T00:00:00"
    if len(until) == 10:
        until += "T23:59:59"
    return since, until


def _excluded(exclude):
    """Event types to leave out, from a list (or a text) of names separated by commas."""
    joined = ",".join(exclude) if isinstance(exclude, (list, tuple)) else str(exclude)
    return [t.strip() for t in joined.split(",") if t.strip()]


def _person(user):
    """The person whose events are wanted (empty: everybody). Who "mine" means is decided by the caller (activity_ops)."""
    return str(user).strip()[:60] or None


def _with_english(row):
    # the history keeps the Spanish text and the key + parameters of each message; the page shows description_en when DWC is in English.
    # message_key / message_params stay in the rows: the pages decide by key (event-kinds.js isCancelledEvent)
    row["description_en"] = messages.in_language(row.get("description"), row.get("message_key"), row.get("message_params"), "en")


def list_events(*, since, until="", kind="", exclude=(), limit=50, offset=0, query="", user=""):
    """One page of the events of a range, newest first, with the total and the kinds that exist."""
    type_name = str(kind).strip() or None
    limit = min(int(limit), MAX_LIMIT)
    offset = max(int(offset), 0)
    text = str(query).strip()[:80] or None
    person = _person(user)
    if not str(since).strip():
        return {"error": M("query_since_missing")}
    since, until = _span(since, until)
    total, rows = db.activity_query(since, until, type_name=type_name, limit=limit, offset=offset, exclude=_excluded(exclude),
                                    raw_text=text, user=person)
    for r in rows:
        if isinstance(r, dict) and r.get("description"):
            _with_english(r)
    return {"total": total, "rows": rows, "kinds": db.activity_kinds()}


def summary(*, since, until="", exclude=(), user=""):
    """Counts and totals of a range (see db.activity_summary), with the English text of each job and failure."""
    person = _person(user)
    if not str(since).strip():
        return {"error": M("query_since_missing")}
    since, until = _span(since, until)
    res = db.activity_summary(since, until, exclude=_excluded(exclude), user=person)
    for row in res["jobs"] + res["faults"]:
        _with_english(row)
    return res


def delete_event(*, event_id):
    """Deletes one event for good."""
    return {"deleted": db.activity_delete([int(event_id)])}


def clear_events(*, since, until="", kind="", exclude=(), query=""):
    """Deletes every event that matches the filter and says how many."""
    type_name = str(kind).strip() or None
    text = str(query).strip()[:80] or None
    if not str(since).strip():
        return {"error": M("query_since_missing")}
    since, until = _span(since, until)
    return {"deleted": db.activity_delete_where(since, until, type_name=type_name, exclude=_excluded(exclude), raw_text=text)}
