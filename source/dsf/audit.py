"""
audit -- who did what (F1-A of the redesign, 2026-10-21).

An append-only record (table `audit` of db.py) of every call that changes something, every refusal and every login: user, role,
device (random id of the browser), address, way in, operation, a summary of the arguments WITHOUT PINs or secrets, the result and
the time. The API has no operation that deletes or edits it (not even for an administrator); only the maintenance purges rows
older than db.AUDIT_DAYS. `audit.list` (administrator) reads it.

Phase 4 (registro de actividad con cadena de verificacion): each row also gets a link of the chain (audit_chain.py, same transaction), a detail
(profile and rule that decided, target, decision, duration), optional read events by category (audit_reads.py, off by default) and the alarms of
audit_alarms.py. `audit.list` itself is of kind admin, so it is recorded as before; audit.verify / export / settings are always recorded.

What is recorded: any operation that is not a plain read, `auth.*`, `users.*`, `audit.*`, and any refusal (403 / 401 of an operation
that is logged). Plain reads that succeed are not (the pages poll them all the time). The address is the one the request says
(X-Forwarded-For when a proxy sets it): it is information for the reader of the audit, never used to decide anything.
"""
import json
import time

import access_targets
import audit_alarms
import audit_reads
import clock
import db

SECRET_ARGS = frozenset({"pin", "new_pin", "old_pin", "password", "key", "local_key", "token", "secret", "topic", "ntfy_topic", "api_key"})
ALWAYS_PREFIX = ("auth.", "users.", "keys.", "password.", "roles.", "access.")
ALWAYS_OPS = ("audit.verify", "audit.export", "audit.settings")  # audit.list is a read like the others (audit_reads: optional, off by default)
DENIED = ("forbidden", "login_required")
DEDUPE_S = 10
_recent = {}


def summary(args, limit=400):
    """Arguments as short JSON text, secrets replaced by ***, long values cut."""
    out = {}
    for k, v in (args or {}).items():
        if str(k).lower() in SECRET_ARGS:
            out[k] = "***"
        elif isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            out[k] = v if len(s) <= 80 else "...(%d bytes)" % len(s)
        elif isinstance(v, str) and len(v) > 80:
            out[k] = v[:80] + "..."
        else:
            out[k] = v
    s = json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else ""
    return s[:limit]


def actor(ctx):
    """(user, role) of a call for the record."""
    via = ctx.get("via")
    u = ctx.get("user")
    if via == "key" and isinstance(ctx.get("key"), dict):
        return "key:%s" % (ctx["key"].get("name") or "?"), "key"
    if via == "macro":
        return "macro", "macro"
    if via == "token":
        return "local:%s" % (ctx.get("origin") or "program"), "local"
    if isinstance(u, dict):
        return u.get("name") or ctx.get("audit_user") or "", u.get("role_name") or u.get("role") or ""  # a custom role by its name
    return ctx.get("audit_user") or "", ""


def wanted(op_name, kind, ctx, ok, code):
    if ctx.get("via") == "internal":
        return False
    if code in DENIED:
        return True
    if op_name.startswith(ALWAYS_PREFIX) or op_name in ALWAYS_OPS:
        return True
    if kind != "read":
        return True
    return audit_reads.admit(op_name)  # a read that succeeded: only when its category is on, sampled and under the daily cap


def _dedupe(user, op_name, code, now):
    if code not in DENIED:
        return False
    k = (user, op_name, code)
    if now - _recent.get(k, 0) < DEDUPE_S:
        return True
    if len(_recent) > 200:
        _recent.clear()
    _recent[k] = now
    return False


def now_text():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(clock.wall()))


def detail(op_name, args, ctx, ok, code, message):
    """The data of an event that the old columns do not hold, without secrets: the decision (allowed / denied / error) and its reason, the profile and
    the rule that decided when the evaluator did, the target the call declares and how long it took."""
    d = {"decision": "allowed" if ok else ("denied" if code in DENIED else "error"), "duration_ms": max(int(ctx.get("duration_ms") or 0), 0)}
    acc = ctx.get("access_decision")
    if isinstance(acc, dict):
        d["reason"] = acc.get("code")
        for k_out, k_in in (("profile", "profile"), ("rule", "id"), ("ceiling", "ceiling")):
            if acc.get(k_in) is not None:
                d[k_out] = str(acc[k_in])[:64]
    elif code:
        d["reason"] = code
    target = access_targets.target_of(op_name, args)
    if target:
        d["target"] = str(target)[:140]
    if not ok and message:
        d["message"] = str(message)[:200]
    return d


def record(op_name, kind, args, ctx, ok, code, message, log=print):
    """Writes the audit row of a call. Never raises."""
    try:
        if not wanted(op_name, kind, ctx, ok, code):
            return
        user, role = actor(ctx)
        http = ctx.get("http") or {}
        if code in DENIED:
            audit_alarms.denied(user or "anonymous " + str(http.get("addr") or "?"))  # counted before the dedupe: every refusal counts for a burst
        audit_alarms.sensitive(op_name, args, ctx, ok, user)
        if _dedupe(user, op_name, code, clock.wall()):
            return
        text = str(message or "")
        # an operation that changes something important may leave its own text (roles.set: the role before and after), which replaces the
        # summary of the arguments: the audit keeps the change itself
        db.audit_insert(now_text(), user, role, http.get("device", ""), http.get("addr", ""), ctx.get("via", ""),
                        op_name, str(ctx.get("audit_detail") or "")[:600] or summary(args), ok, code, "" if ok else text,
                        detail(op_name, args, ctx, ok, code, message))
    except Exception as e:  # noqa: BLE001 - the audit must never break a call
        try:
            log("audit: %s" % e)
        except Exception:
            pass


def event(op_name, args, who, ok=True, code="", message="", log=print):
    """Row for something the service did for a person without it being an API call of its own (the end of a procedure of Machine,
    a calibration record). `who` = {"user", "role", "device"} (what identity.actor() gives). `args` is summarized like a call's,
    so put the run_id and the kind there. Never raises."""
    try:
        who = who or {}
        db.audit_insert(now_text(), who.get("user", ""), who.get("role", ""), who.get("device", ""), "", "service",
                        op_name, summary(args), ok, code, "" if ok else str(message or ""))
    except Exception as e:  # noqa: BLE001 - the audit must never break what it describes
        try:
            log("audit: %s" % e)
        except Exception:
            pass
