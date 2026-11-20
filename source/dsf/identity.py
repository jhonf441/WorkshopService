"""
identity -- who is calling, and what that person may do (F1-A of the redesign, 2026-10-21).

`AuthRegistry` is the registry of the service (workshop_api.Registry) with the role rules of permissions.py applied in
`_allowed`, before anything else runs. workshop_api.py itself stays as it is (the RS485 plugin keeps a copy of it that a test
requires to be equal): everything new is here.

The caller sends the session token in the header X-Workshop-Token (the same header the local programs use for their local key:
the key is compared first, anything else is looked up here as a session) and a random id of the browser in X-Workshop-Device.
`http_identity(headers)` turns them into ctx["http"]["identity"]; the token itself is never kept in the context.

Rules:
  - nobody has been created yet (users.UserStore.configured() is False): everybody is admin, as before this existed;
  - users exist: a call of a DWC session needs a valid token, except login / whoami / ping and the STOP operations
    (stopping is never blocked); the settings can allow an unidentified caller to read as a viewer (kiosk);
  - external keys, local programs (Vision, bridge), macros and the service itself do not go through the roles.
The user of the call is left in ctx["user"] for the history and the audit, and in a context variable (`current()`) so that
code deep inside a handler (activity.log_event) can write who did it without receiving it as an argument.
"""
import contextvars

import api_keys
import audit_alarms
import access_context
import access_person
import permission_caps as caps
import permissions
import workshop_api as wa
from messages import M

COMPAT_USER = {"name": "", "role": permissions.ADMIN, "modes": list(permissions.MODES), "camera": True, "sid": None, "compat": True}

_holder = contextvars.ContextVar("workshop_identity", default=None)

# Where the access file of the access model comes from: fn(users store) -> access_store.AccessStore or None. access_ops.build sets it (the registry is built
# before the users store exists, and the store is made when the first call needs it). A registry can also be given its own: `registry.access`.
access_source = None
# Where the last-use file comes from: fn(users store) -> access_usage.UsageStore or None (access_ops.build sets it). A registry can have its own: `registry.usage`.
usage_source = None


def current():
    """The user of the call being served in this thread, or None (background code, no identity, compatibility mode)."""
    h = _holder.get()
    u = h.get("user") if h else None
    return u if u and not u.get("compat") and u.get("name") else None


class StatusError(wa.ApiError):
    """An ApiError with its own HTTP status (401 wrong PIN, 429 locked...)."""

    def __init__(self, code, message, status, **extra):
        super().__init__(code, message, **extra)
        self.status = status


class LoginRequired(StatusError):
    """401: the service has users and the call came without a valid session."""

    def __init__(self):
        super().__init__("login_required", M("auth_login_required"), 401)


def clean_device(v):
    """Id of the browser: letters, digits, - and _, up to 40."""
    return "".join(c for c in str(v or "") if c.isalnum() or c in "-_")[:40]


def actor(ctx):
    """Who is behind a call, for the owner of the movement: {"device": browser id, "user": name, "role": role}. The open mode
    (nobody created yet) and the calls of programs or of the service itself have no name (user "")."""
    ctx = ctx or {}
    u = ctx.get("user")
    named = isinstance(u, dict) and not u.get("compat")
    return {"device": clean_device((ctx.get("http") or {}).get("device")), "user": (u.get("name") or "") if named else "",
            "role": (u.get("role") or "") if isinstance(u, dict) else ""}


def http_identity(headers, store):
    """{"identity": {...} | None, "device": str} for ctx["http"]. The token in the header may also be the local key of a
    system program (then it matches no session and the identity is None, which is fine for those: they do not use it)."""
    tok = wa.header(headers, wa.TOKEN_HEADER)
    ident = store.resolve(tok) if (store is not None and tok) else None
    return {"identity": ident, "device": clean_device(wa.header(headers, "x-workshop-device"))}


class AuthRegistry(wa.Registry):
    """Registry with roles. `users` is a users.UserStore; `mode_of()` returns the mode of the machine now ("laser"...) or None."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.users = None
        self.on_denied = None  # fn(op, args, ctx, body) for refusals of operations that are not logged
        self.mode_of = lambda: None
        self.usage = None  # access_usage.UsageStore of this registry (tests); else usage_source(self.users)
        self.access = None  # access_store.AccessStore of this registry (tests); else access_source(self.users)
        self.state_of = access_context.read_live  # () -> (object model, its age): the live conditions of the rules of a governed person

    def _access_view(self):
        """The state of the access model now, or None (no store, or its file is damaged: then nobody has attachments and the base roles decide)."""
        store = self.access
        if store is None and access_source is not None and self.users is not None:
            store = access_source(self.users)
        if store is None:
            return None
        audit_alarms.access_file(store.damaged)  # a damaged file raises one visible alarm per period, and a note when it heals
        return None if store.damaged else store.view()

    def call(self, op_name, args=None, ctx=None):
        ctx = dict(ctx or {})
        ctx["args_raw"] = args if isinstance(args, dict) else {}
        ctx["holder"] = holder = {}
        token = _holder.set(holder)
        try:
            status, body = super().call(op_name, args, ctx)
        finally:
            _holder.reset(token)
        op = self.ops.get(str(op_name or ""))
        if status == 403 and self.on_denied is not None and op is not None and not op.log:
            try:  # a refused call of an operation that is not logged (jog...) is still worth a line in the audit
                self.on_denied(op, ctx["args_raw"], dict(ctx, user=holder.get("user"), access_decision=holder.get("access_decision")), body)
            except Exception as e:  # noqa: BLE001
                self.log("audit of a refusal: %s" % e)
        return status, body

    def _set_user(self, ctx, user):
        ctx["user"] = user
        h = ctx.get("holder")
        if h is not None:
            h["user"] = user

    def _key_allows(self, op, rec):
        """Permissions of a key (api_keys.why_not: classes, patterns and capabilities minus the denials, never administration or, for a
        strict key, a non-delegable operation). The same rule gives the page its list of allowed operations."""
        why = api_keys.why_not(rec, op.name, op.kind)
        if why is None:
            return
        name, kname = op.name, rec.get("name", "?")
        if why == "admin":
            raise wa.ApiError("forbidden", f"'{name}' needs a DWC session: a key cannot call administration operations")
        if why == "denied":
            raise wa.ApiError("forbidden", f"the key '{kname}' does not allow '{name}'")
        if why == "not_delegable":
            raise wa.ApiError("forbidden", f"the key '{kname}' does not allow '{name}': a key cannot call operations that are not delegable")
        raise wa.ApiError("forbidden", f"the key '{kname}' does not allow '{name}' (kind {op.kind})")

    def _allowed(self, op, via, ctx=None):
        super()._allowed(op, via, ctx)
        if via in (wa.VIA_SESSION, wa.VIA_OPEN) and ctx is not None:
            self._check_role(op, ctx)

    def _check_role(self, op, ctx):
        store = self.users
        if store is None or not store.configured():
            self._set_user(ctx, COMPAT_USER)
            return
        http = ctx.get("http") or {}
        ident = http.get("identity")
        name = op.name
        if ident is None and name in permissions.STOP_OPS:
            return  # stopping is never blocked
        if ident is None and name not in permissions.PUBLIC_OPS:
            ident = store.anonymous()
            if ident is None:
                raise LoginRequired()
        if ident is not None:
            self._set_user(ctx, ident)
        if name in permissions.PUBLIC_OPS:
            return
        if store.damaged:
            raise wa.ApiError("forbidden", M("auth_users_damaged"), reason="damaged")
        dctx = {"args": ctx.get("args_raw") or {}, "modes": ident.get("modes"), "camera": ident.get("camera"), "mode": self.mode_of(),
                "role_def": ident.get("role_def")}
        view = self._access_view()
        dec = access_context.decide(view, ident, name, dctx, self.state_of) if view is not None else None
        if dec is not None:  # something is attached to the person: the evaluator governs them (access_person)
            self._decided(ctx, dec.allowed, dec.reason)
            if not dec.allowed:
                raise self._forbidden_access(name, ident, dctx, dec)
            self._note_use(ident, name)
            return
        ok, why = permissions.decide(role_name(ident), name, dctx)
        self._decided(ctx, ok, {"code": why or "role"})
        if not ok:
            raise self._forbidden(name, ident, dctx, why)
        self._note_use(ident, name)

    def own_answer(self, ident, name, args=None, target=None):
        """What `_check_role` would decide for `ident` calling `name` now, as {"allowed", "reason": {...}} (auth.can). Only about the identity it is
        given: the caller's own. The reason names the cause, and the profile, the rule (its id) and the ceiling that decided, never their contents.
        The same decision as a real call: same context (mode of the machine, live conditions), same evaluator, same base roles."""
        name = str(name)
        if name in permissions.STOP_OPS:
            return {"allowed": True, "reason": {"code": "stop"}}
        dctx = {"args": args if isinstance(args, dict) else {}, "modes": ident.get("modes"), "camera": ident.get("camera"), "mode": self.mode_of(),
                "role_def": ident.get("role_def")}
        view = self._access_view()
        dec = access_context.decide(view, ident, name, dctx, self.state_of, target) if view is not None else None
        if dec is None:
            ok, why = permissions.decide(role_name(ident), name, dctx)
            reason = {"code": "allow" if ok else why or "role"}
            if not ok:
                reason["needed_role"] = permissions.needed_role(name, dctx)
            return {"allowed": ok, "reason": reason}
        reason = {k: dec.reason[k] for k in ("code", "profile", "ceiling", "needed_tier") if dec.reason.get(k) is not None}
        if dec.reason.get("id") is not None:
            reason["rule"] = dec.reason["id"]
        if dec.reason.get("failed_conditions"):
            reason["failed_conditions"] = list(dec.reason["failed_conditions"])
        if not dec.allowed:
            reason["why"] = access_person.legacy_why(dec, name, ident, dctx)
            reason["needed_role"] = permissions.needed_role(name, dctx)
        return {"allowed": dec.allowed, "reason": reason}

    def _note_use(self, ident, name):
        """The last use of the capability of an ALLOWED call (access_usage: memory first, a pair at most once a minute). Never raises, never refuses."""
        try:
            who, cap = ident.get("name"), caps.capability_of(name)
            if not who or cap is None:
                return
            store = self.usage
            if store is None and usage_source is not None and self.users is not None:
                store = usage_source(self.users)
            if store is not None:
                store.touch(who, cap)
        except Exception:  # noqa: BLE001  the record of a use never decides a call
            pass

    @staticmethod
    def _decided(ctx, allowed, reason):
        """What decided the call (the code, and the profile and rule when the evaluator did), kept for the audit detail."""
        d = {k: reason[k] for k in ("code", "profile", "id", "ceiling") if reason.get(k) is not None}
        d["allowed"] = bool(allowed)
        ctx["access_decision"] = d
        if ctx.get("holder") is not None:
            ctx["holder"]["access_decision"] = d

    @staticmethod
    def _forbidden_access(name, ident, dctx, dec):
        why = access_person.legacy_why(dec, name, ident, dctx)
        need = permissions.needed_role(name, dctx)
        extra = {"reason": why, "role": ident["role"], "needed_role": need, "op_name": name, "access": dict(dec.reason)}
        if ident.get("role_name"):
            extra["role_name"] = ident["role_name"]
        if why == "mode":
            extra["mode"] = dctx.get("mode")
        if why == "denied":
            text = M("auth_forbidden_access_deny", profile=dec.reason.get("profile", "?"))
        elif why == "ceiling":
            text = M("auth_forbidden_ceiling", ceiling=dec.reason.get("ceiling", "?"))
        else:
            text = forbidden_message(why, ident, need, dctx.get("mode"))
        return wa.ApiError("forbidden", text, **extra)

    @staticmethod
    def _forbidden(name, ident, dctx, why):
        need = permissions.needed_role(name, dctx)
        extra = {"reason": why, "role": ident["role"], "needed_role": need, "op_name": name}
        if ident.get("role_name"):
            extra["role_name"] = ident["role_name"]
        if why == "mode":
            extra["mode"] = dctx.get("mode")
        return wa.ApiError("forbidden", forbidden_message(why, ident, need, dctx.get("mode")), **extra)


def role_name(ident):
    """The name the person's role goes by: the custom role's name, or the base role."""
    return ident.get("role_name") or ident["role"]


def forbidden_message(why, ident, need, mode=None):
    """The text of a refusal (the same for a real 403 and for what `roles.effective` explains)."""
    if why == "mode":
        return M("auth_forbidden_mode", mode=M("auth_mode_" + str(mode)))
    if why == "mode_unknown":
        return M("auth_forbidden_mode_unknown")
    if why == "camera":
        return M("auth_forbidden_camera")
    custom = ident.get("role_name") is not None
    label = ident["role_name"] if custom else M("auth_role_" + ident["role"])
    if why == "denied":
        return M("auth_forbidden_denied", role=label)
    if why == "unknown_role":
        return M("auth_forbidden_role_missing", role=label)
    return M("auth_forbidden_role", role=label, needed=M("auth_role_" + need))
