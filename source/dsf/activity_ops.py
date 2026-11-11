"""API operations of the Activity page: activity.list / delete / clear / summary (activity_history.py), history.list / delete
(commands_history.py) and blackbox.status / lines / note / hide / show (black_box_view.py). api_ops.init registers them through
build(ctx), like settings_ops.

The class, arguments, roles (permissions.py) and flags of each operation are the ones they had when they were handlers.
"""
import activity_history
import black_box
import black_box_view
import commands_history
import identity
from messages import M
from workshop_api import READ, WRITE, Arg, ApiError, Op

D_FROM = "Start of the range, inclusive: YYYY-MM-DD (from 00:00:00) or a full date and time YYYY-MM-DDTHH:MM:SS."
D_TO = "End of the range, inclusive, same format; a date alone means the end of that day. Empty: the same as from."
D_LIMIT = "Rows per page (default 50, at most 200)."
D_OFFSET = "Rows to skip, for paging (default 0)."
D_TYPE = "Only events of this exact type (for example job_start, job_end, power, config, modo, sistema). Empty: every type."
D_EXCLUDE = "Event types to leave out, for example [\"servicio\"] hides the restarts of the service."
D_USER = "Only the events done by this person (user name, as in rows[].user)."
D_MINE = "true: only the events of the person of this session (the server knows who it is); without users (open mode) it filters nothing."
D_QUERY = "Text searched in the description, the type and the detail of each event (the first 80 characters are used)."


def person(user, mine):
    """The person whose events are wanted: the one named, else the one of the session when `mine` (nobody in open mode)."""
    if not str(user).strip()[:60] and mine:
        who = identity.current()  # the person of the session (None in open mode and for programs)
        return who["name"] if who else ""
    return user


def _activity_ops():
    S, I, B, L = "str", "int", "bool", "list"
    a = Arg

    def list_events(args, c):
        return activity_history.list_events(
            since=args["from"], until=args.get("to", ""), kind=args.get("type", ""), exclude=args.get("exclude", ()),
            limit=args.get("limit", 50), offset=args.get("offset", 0), query=args.get("query", ""),
            user=person(args.get("user", ""), args.get("mine", False)))

    def delete_event(args, c):
        return activity_history.delete_event(event_id=args["id"])

    def clear_events(args, c):
        return activity_history.clear_events(since=args["from"], until=args.get("to", ""), kind=args.get("type", ""),
                                             exclude=args.get("exclude", ()), query=args.get("query", ""))

    def summary(args, c):
        return activity_history.summary(since=args["from"], until=args.get("to", ""), exclude=args.get("exclude", ()),
                                        user=person(args.get("user", ""), args.get("mine", False)))

    return [
        Op("activity.list", list_events, READ,
           {"from": a(S, True, desc=D_FROM), "to": a(S, desc=D_TO), "type": a(S, desc=D_TYPE), "exclude": a(L, desc=D_EXCLUDE),
            "limit": a(I, min=1, max=200, desc=D_LIMIT), "offset": a(I, min=0, desc=D_OFFSET), "query": a(S, desc=D_QUERY),
            "user": a(S, desc=D_USER), "mine": a(B, desc=D_MINE)},
           "Lists the events of the Activity history (jobs, power, configuration, warnings...) of a date range, paged and filtered; "
           "also returns the total and the event types that exist."),
        Op("activity.delete", delete_event, WRITE,
           {"id": a(I, True, desc="Id of the event, as returned by activity.list (rows[].id).")},
           "Deletes one event of the Activity history for good."),
        Op("activity.clear", clear_events, WRITE,
           {"from": a(S, True, desc=D_FROM), "to": a(S, desc=D_TO), "type": a(S, desc=D_TYPE), "exclude": a(L, desc=D_EXCLUDE),
            "query": a(S, desc=D_QUERY)},
           "Deletes every Activity event that matches the filter (date range, type, excluded types, text) and returns how many; cannot be undone."),
        Op("activity.summary", summary, READ,
           {"from": a(S, True, desc=D_FROM), "to": a(S, desc=D_TO), "exclude": a(L, desc=D_EXCLUDE),
            "user": a(S, desc=D_USER), "mine": a(B, desc=D_MINE)},
           "Summary of the Activity history of a date range: events per type, jobs started / finished / cancelled, total job time and kWh, "
           "the finished jobs (newest first, up to 30), the last failures and emergency stops (up to 8) and the first and last event."),
    ]


def _history_ops():
    S, I, B = "str", "int", "bool"
    a = Arg

    def list_calls(args, c):
        return commands_history.list_calls(
            since=args["from"], until=args.get("to", ""), name=args.get("name", ""), errors=args.get("errors", False),
            query=args.get("query", ""), limit=args.get("limit", 50), offset=args.get("offset", 0), rw=args.get("rw", 0),
            via=args.get("via", ""), channel=args.get("channel", ""), kind=args.get("kind", ""), plugin=args.get("plugin", ""),
            result=args.get("result", ""))

    def delete_calls(args, c):
        return commands_history.delete_calls(since=args["from"], until=args.get("to", ""))

    return [
        Op("history.list", list_calls, READ,
           {"from": a(S, True, desc=D_FROM), "to": a(S, desc=D_TO),
            "name": a(S, desc="Only the calls of this operation, for example lights.get."),
            "errors": a(B, desc="true: only the calls that failed."),
            "query": a(S, desc="Text searched in the call and in its answer."),
            "limit": a(I, min=1, max=200, desc=D_LIMIT), "offset": a(I, min=0, desc=D_OFFSET),
            "rw": a(I, min=0, max=2, desc="0 every call, 1 only the ones that change something, 2 only reads."),
            "via": a(S, desc="Only the calls that arrived this way, as written in the history (for example \"API (DWC session)\", \"macro\", \"service\")."),
            "channel": a(S, desc="Only the calls of this origin channel (HTTP, SBC, Aux...); \"-\" for rows saved without origin data."),
            "kind": a(S, desc="Only the calls of this origin kind (page, console, job_file, macro, bridge, service, external...); \"-\" for rows without origin data."),
            "plugin": a(S, desc="Only the calls of this plugin or page tag; \"-\" for rows without origin data."),
            "result": a(S, desc="Only the calls with this result: ok, error or blocked; \"-\" for rows without origin data.")},
           "Lists the API calls received by the service (origin, result, duration) of a date range, paged and filtered; "
           "also returns counters of the range and of the last hour.", log=False),
        Op("history.delete", delete_calls, WRITE,
           {"from": a(S, True, desc=D_FROM), "to": a(S, desc=D_TO)},
           "Deletes the received calls of a date range from the history; cannot be undone."),
    ]


def _black_box_ops(ctx):
    S, I = "str", "int"
    a = Arg

    def box():
        """The running black box; the operations of it fail (424) while it is not active."""
        running = black_box.current()
        if running is None:
            raise ApiError("failed", M("blackbox_error_black_box_not_active_config"))
        return running

    def box_status(args, c):
        return black_box_view.status(box())

    def box_lines(args, c):
        return black_box_view.lines(box(), args.get("n", 20))

    def box_note(args, c):
        box()
        if not args["text"].strip():
            raise ApiError("failed", M("blackbox_error_text_missing"))
        return black_box_view.note(args["text"])

    def box_hide(args, c):
        box()
        return black_box_view.hide(ctx["bridge"])

    def box_show(args, c):
        box()
        return black_box_view.show(ctx["bridge"])

    return [
        Op("blackbox.status", box_status, READ, {},
           "State of the black box (a line of load, CPU, RAM, temperature and state every few seconds in 0:/sys/workshop/data/blackbox/) "
           "and the report of the last unclean shutdown."),
        Op("blackbox.lines", box_lines, READ,
           {"n": a(I, min=1, max=200, default=20, desc="Number of lines, 1 to 200 (default 20).")},
           "Returns the last lines written by the black box, as text."),
        Op("blackbox.note", box_note, WRITE, {"text": a(S, True, desc="Text of the note.")},
           "Writes a note event in the black box (for example from a macro, to mark a moment).", macro=True),
        Op("blackbox.hide", box_hide, WRITE, {}, "Hides the card with the report of the last unclean shutdown of the system."),
        Op("blackbox.show", box_show, WRITE, {}, "Shows again the card with the report of the last unclean shutdown of the system (the report is never deleted)."),
    ]


def build(ctx):
    return _activity_ops() + _history_ops() + _black_box_ops(ctx)
