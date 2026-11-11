"""
audit_ops -- the operations audit.* of the API (phase 4 of informes/control-acceso/PLAN-ACCESO.md: the activity record with a verification chain).

  audit.list      the page query, with filters (person, group, operation, target, result, only refusals, range). With none of the new filters the
                  answer is what it always was.
  audit.verify    walks the verification chain (audit_chain.py) and says 'ok' with the number of links or the first broken row; a limit of links per
                  call keeps the Pi responsive: it answers where it stopped and is called again with `after`.
  audit.export    JSONL with the hash of every row, by range of dates, paged (rows per call and `after`).
  audit.settings  reads or changes the settings of the record: optional read events, sampling, daily cap and the alarms (audit_settings.py).

Administrator only (permissions.OP_ROLES) and never delegable (permission_caps.NOT_DELEGABLE for verify, export and settings). None of them deletes or
edits anything: the API still has no way to do that, not even for an administrator. The alarms of audit_alarms.py go out through the Activity record + phone
mechanism (type "security_alarm" of notifier.KINDS); bootstrap.start_api connects them (audit_ops cannot import activity: cycle).
"""
import time

import audit_alarms
import audit_chain
import audit_settings
import audit_store
import db_conn
import identity
from messages import M
from workshop_api import ADMIN, ApiError, Arg, Op


def _range(args):
    since = str(args.get("from") or "").strip() or time.strftime("%Y-%m-%d")
    until = str(args.get("to") or "").strip() or since
    return since + "T00:00:00" if len(since) == 10 else since, until + "T23:59:59" if len(until) == 10 else until


def make_ops(ctx):
    """The operations; `ctx` is api_ops._ctx (bridge, config, users)."""
    S, I, B, O = "str", "int", "bool", "obj"
    a = Arg
    audit_settings.bind(ctx.get("config"))
    audit_alarms.users_of = lambda: ctx.get("users")
    audit_alarms.state_store = (_state_read, _state_write)

    def members(group):
        """The people of an access group (access_ops.source keeps the access file), or None when the model is unavailable."""
        users = ctx.get("users")
        store = identity.access_source(users) if identity.access_source is not None and users is not None else None
        return store.view().members(group) if store is not None and not store.damaged else []

    def audit_list(args, c):
        since, until = _range(args)
        group = str(args.get("group") or "").strip()
        total, rows, who = audit_store.query_rows(
            audit_store.path_of(),
            since, until, user=str(args.get("user") or "").strip() or None, op=str(args.get("op") or "").strip() or None,
            only_errors=bool(args.get("errors")), limit=args.get("limit") or 50, offset=args.get("offset") or 0,
            users=members(group) if group else None, target=str(args.get("target") or "").strip() or None,
            result=str(args.get("result") or "").strip() or None, only_denied=bool(args.get("denied")), with_detail=bool(args.get("detail")))
        return {"total": total, "rows": rows, "users": who}

    def audit_verify(args, c):
        out = audit_chain.verify(audit_store.path_of(), args.get("after") or 0, args.get("limit") or 2000)
        audit_alarms.chain_broken(out)
        return out

    def audit_export(args, c):
        since, until = _range(args)
        return audit_store.export_page(audit_store.path_of(), since, until, args.get("after") or 0, args.get("limit") or 1000)

    def audit_settings_op(args, c):
        changes = args.get("settings")
        if changes is None:
            return {"settings": audit_settings.get()}
        try:
            cleaned = audit_settings.clean(changes)
        except audit_settings.SettingsInvalid as e:
            raise ApiError("invalid_args", M("audit_err_setting", field=str(e)), field="settings")
        out = audit_settings.apply(cleaned)
        bridge = ctx.get("bridge")
        if bridge is not None:
            bridge.save_config()
        return {"settings": out}

    return [
        Op("audit.list", audit_list, ADMIN,
           {"from": a(S, desc="Start (YYYY-MM-DD or full date and time); default today."), "to": a(S, desc="End, same format; default the same day."),
            "user": a(S, desc="Only this person."), "op": a(S, desc="Only operations starting with this text."),
            "errors": a(B, desc="Only refused or failed calls."), "limit": a(I, min=1, max=200, default=50, desc="Rows per page."),
            "offset": a(I, min=0, default=0, desc="Rows to skip."),
            "group": a(S, desc="Only the people who belong to this access group now."),
            "target": a(S, desc="Only events on this target (workshop:<plugin>:<type>/<id>)."),
            "result": a(S, choices=audit_store.RESULTS, desc="Only allowed, denied (refused by the access rules or no session) or error calls."),
            "denied": a(B, desc="Only the refusals (no permission or no session)."),
            "detail": a(B, desc="Add to each row the detail of the event (profile and rule that decided, target, decision, duration) when it has one.")},
           "Reads the audit: who did what, from which device. It cannot be changed or deleted from the API."),
        Op("audit.verify", audit_verify, ADMIN,
           {"after": a(I, min=0, default=0, desc="Id of the last link of the previous call (0 = from the start)."),
            "limit": a(I, min=1, max=audit_chain.VERIFY_MAX_ROWS, default=2000, desc="Most links to look at in this call.")},
           "Verifies the chain of hashes of the audit. Answers ok with the number of links, or the first broken row and why; `done` false means call "
           "again with after = next_after. A row older than the chain is outside it."),
        Op("audit.export", audit_export, ADMIN,
           {"from": a(S, desc="Start (YYYY-MM-DD or full date and time); default today."), "to": a(S, desc="End, same format; default the same day."),
            "after": a(I, min=0, default=0, desc="Id of the last row of the previous page (0 = from the start)."),
            "limit": a(I, min=1, max=audit_store.EXPORT_MAX_ROWS, default=1000, desc="Most rows in this page.")},
           "Exports audit rows as JSON lines with the hash of each one (`jsonl`); `done` false means call again with after = next_after."),
        Op("audit.settings", audit_settings_op, ADMIN,
           {"settings": a(O, desc="What to change: reads {camera, audit, config: bool}, alarms {access_damaged, denial_burst, sensitive_change, "
                                  "chain_broken: bool}, read_sample, read_daily_cap, burst_threshold, burst_window_s, alarm_quiet_s. Without it only reads.")},
           "Reads or changes the settings of the audit: optional read events (off by default), their sampling and daily cap, and the alarms."),
    ]


def _state_read(name):
    with db_conn.read(audit_store.path_of()) as conn:
        r = conn.execute("SELECT state, ts FROM audit_alarm_state WHERE name = ?", (name,)).fetchone()
    return (r[0], r[1]) if r else None


def _state_write(name, state, ts):
    with db_conn.write(audit_store.path_of()) as conn:
        conn.execute("INSERT OR REPLACE INTO audit_alarm_state (name, state, ts) VALUES (?, ?, ?)", (name, state, ts))

