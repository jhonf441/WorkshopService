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

import permissions
import workshop_api as wa
from messages import M

COMPAT_USER = {"name": "", "role": permissions.ADMIN, "modes": list(permissions.MODES), "camera": True, "sid": None, "compat": True}

_holder = contextvars.ContextVar("workshop_identity", default=None)


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
                self.on_denied(op, ctx["args_raw"], dict(ctx, user=holder.get("user")), body)
            except Exception as e:  # noqa: BLE001
                self.log("audit of a refusal: %s" % e)
        return status, body

    def _set_user(self, ctx, user):
        ctx["user"] = user
        h = ctx.get("holder")
        if h is not None:
            h["user"] = user

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
        dctx = {"args": ctx.get("args_raw") or {}, "modes": ident.get("modes"), "camera": ident.get("camera"), "mode": self.mode_of()}
        ok, why = permissions.decide(ident["role"], name, dctx)
        if not ok:
            raise self._forbidden(name, ident, dctx, why)

    @staticmethod
    def _forbidden(name, ident, dctx, why):
        need = permissions.needed_role(name, dctx)
        extra = {"reason": why, "role": ident["role"], "needed_role": need, "op_name": name}
        if why == "mode":
            extra["mode"] = dctx.get("mode")
        if why == "mode":
            return wa.ApiError("forbidden", M("auth_forbidden_mode", mode=M("auth_mode_" + str(dctx.get("mode")))), **extra)
        if why == "mode_unknown":
            return wa.ApiError("forbidden", M("auth_forbidden_mode_unknown"), **extra)
        if why == "camera":
            return wa.ApiError("forbidden", M("auth_forbidden_camera"), **extra)
        return wa.ApiError("forbidden", M("auth_forbidden_role", role=M("auth_role_" + ident["role"]), needed=M("auth_role_" + need)), **extra)
