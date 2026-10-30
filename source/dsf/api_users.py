"""
api_users -- the operations auth.*, users.* and audit.list of the API (F1-A of the redesign, 2026-10-21).

  auth.login(name, pin) -> token       the person identifies; the token goes in the header X-Workshop-Token
  auth.logout, auth.whoami, auth.keepalive, auth.change_pin
  users.list / add / set / remove / reset_pin / settings      administrator only (permissions.py)
  audit.list                                                  administrator only, read only

The rules (roles, PINs, locks) are in users.py and permissions.py; the application on every call is in identity.py. This file
only maps the named arguments to them and the errors to answers. The PINs never reach the history of commands or the audit
(api_ops._SECRET_ARGS, audit.SECRET_ARGS) and the answers of auth.* are not stored.
"""
import time

import db
import identity
import permissions
import users
from messages import M
from workshop_api import ADMIN, READ, WRITE, ApiError, Arg, Op

_STATUS = {"bad_credentials": 401, "locked": 429, "damaged": 403, "invalid_name": 422, "pin_policy": 422, "invalid_args": 422}


def _error(e):
    """users.UserError -> ApiError with a text that is translated (key users_err_<code>)."""
    extra = {"reason": e.code}
    if e.code == "pin_policy":
        text = M("users_err_pin_policy", min=users.MIN_PIN, max=users.MAX_PIN)
    elif e.code == "locked":
        extra["wait_s"] = e.extra.get("wait_s", 0)
        text = M("users_err_locked", wait_s=extra["wait_s"])
    elif e.code == "bad_credentials":
        text = M("users_err_bad_credentials")
    else:
        text = M("users_err_" + e.code)
    return identity.StatusError("failed" if e.code not in _STATUS else e.code, text, _STATUS.get(e.code, 409), **extra)


def _client(ctx):
    http = ctx.get("http") or {}
    return http.get("device") or http.get("addr") or ""


def _actor(ctx):
    u = ctx.get("user")
    return u.get("name") if isinstance(u, dict) and not u.get("compat") else None


def _public_user(ident):
    return {"name": ident.get("name", ""), "role": ident["role"], "modes": list(ident.get("modes") or []), "camera": bool(ident.get("camera"))}


def make_ops(store_of):
    """The operations. store_of() returns the users.UserStore (or None when the installation has none)."""
    S, I, N, B, L = "str", "int", "num", "bool", "list"
    a = Arg

    def store():
        st = store_of()
        if st is None:
            raise ApiError("internal", M("users_err_unavailable"))
        return st

    def call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except users.UserError as e:
            raise _error(e)

    def login(args, ctx):
        st = store()
        if not st.configured():
            raise ApiError("failed", M("users_err_no_users"))
        name = str(args.get("name") or "").strip()
        ctx["audit_user"] = name[:40]
        token, rec = call(st.login, name, args.get("pin"), _client(ctx), (ctx.get("http") or {}).get("device", ""))
        ident = st.resolve(token)
        ctx["user"] = ident
        s = st.get_settings()
        return {"token": token, "user": _public_user(ident), "idle_minutes": s["idle_minutes"], "max_hours": s["max_hours"]}

    def logout(args, ctx):
        u = ctx.get("user")
        return {"logged_out": bool(u and u.get("sid") and store().logout(u["sid"]))}

    def whoami(args, ctx):
        st = store_of()
        if st is None or not st.configured():
            off = bool(st is not None and st.users and not st.damaged and not st.get_settings().get("enabled", True))
            return {"configured": False, "damaged": False, "compat": True, "login_required": False, "users_disabled": off,
                    "user": _public_user(identity.COMPAT_USER), "role": permissions.ADMIN, "table": permissions.table_for_client()}
        ident = ctx.get("user") or st.anonymous()
        out = {"configured": True, "damaged": st.damaged, "compat": False, "table": permissions.table_for_client(),
               "login_required": ident is None, "anonymous_viewer": bool(st.get_settings()["anonymous_viewer"])}
        out["user"] = _public_user(ident) if ident else None
        out["role"] = ident["role"] if ident else None
        out["named"] = bool(ident and ident.get("name"))
        out["idle_minutes"] = st.get_settings()["idle_minutes"]
        return out

    def resolve(args, ctx):
        """Who a session token is, asked by a LOCAL program (the Vision server, with the local key) on behalf of a browser. It answers the
        role only (no permission table); the token of the browser is the argument because that program is authenticated by its own key."""
        st = store_of()
        if st is None or not st.configured():
            return {"configured": False, "compat": True, "role": permissions.ADMIN, "user": None}
        ident = st.resolve(str(args.get("token") or "")) or st.anonymous()
        return {"configured": True, "compat": False, "role": ident["role"] if ident else None, "user": _public_user(ident) if ident else None}

    def keepalive(args, ctx):
        u = ctx.get("user")
        if u and u.get("sid"):
            store().touch(u["sid"])
        return {"alive": bool(u)}

    def change_pin(args, ctx):
        name = _actor(ctx)
        if not name:
            raise ApiError("failed", M("users_err_not_logged_in"))
        call(store().change_pin, name, args.get("old_pin"), args.get("new_pin"), _client(ctx))
        return {"changed": True}

    def users_list(args, ctx):
        st = store()
        return {"configured": st.configured(), "enabled": bool(st.get_settings().get("enabled", True)), "damaged": st.damaged,
                "users": st.list(), "settings": st.get_settings(),
                "roles": list(permissions.ROLES), "modes": list(permissions.MODES), "min_pin": users.MIN_PIN, "max_pin": users.MAX_PIN}

    def users_add(args, ctx):
        st = store()
        first = not st.configured() and not st.users  # roles switched off with people saved: nobody is "the first"
        if first and args.get("role") != permissions.ADMIN:
            raise ApiError("invalid_args", M("users_err_first_admin"), field="role")
        rec = call(st.add, args.get("name"), args.get("pin"), args.get("role"), args.get("modes"), bool(args.get("camera_for_viewer")))
        out = {"user": rec}
        if first:  # whoever creates the first administrator is that administrator from now on
            token, _ = call(st.login, rec["name"], args.get("pin"), _client(ctx), (ctx.get("http") or {}).get("device", ""))
            out["token"] = token
            ctx["user"] = st.resolve(token)
        return out

    def users_set(args, ctx):
        return {"user": call(store().set, args.get("name"), _actor(ctx), args.get("role"), args.get("modes"), args.get("camera_for_viewer"))}

    def users_remove(args, ctx):
        return {"removed": call(store().remove, args.get("name"), _actor(ctx))}

    def users_reset_pin(args, ctx):
        return {"user": call(store().reset_pin, args.get("name"), args.get("pin"))}

    def users_settings(args, ctx):
        st = store()
        changes = {k: args.get(k) for k in ("idle_minutes", "max_hours", "never_expires", "anonymous_viewer", "camera_for_viewer") if args.get(k) is not None}
        return {"settings": st.set_settings(changes) if changes else st.get_settings()}

    def users_enable(args, ctx):
        st = store()
        on = bool(args.get("enabled"))
        if not on and not _actor(ctx):
            raise ApiError("failed", M("users_err_admin_only"))
        return {"enabled": bool(call(st.set_enabled, on, _actor(ctx), args.get("pin"), _client(ctx)).get("enabled", True))}

    def audit_list(args, ctx):
        since = str(args.get("from") or "").strip() or time.strftime("%Y-%m-%d")
        until = str(args.get("to") or "").strip() or since
        if len(since) == 10:
            since += "T00:00:00"
        if len(until) == 10:
            until += "T23:59:59"
        total, rows, who = db.audit_query(since, until, user=str(args.get("user") or "").strip() or None,
                                          op=str(args.get("op") or "").strip() or None, only_errors=bool(args.get("errors")),
                                          limit=args.get("limit") or 50, offset=args.get("offset") or 0)
        return {"total": total, "rows": rows, "users": who}

    d_name = "Name of the person (1 to 32 letters, digits, spaces, dots or hyphens)."
    d_pin = "PIN: %d to %d digits." % (users.MIN_PIN, users.MAX_PIN)
    d_role = "viewer, operator, technician or admin."
    d_modes = "Modes an operator may run: a list of laser, cnc, fff (default: only laser). Technicians and administrators have all."
    return [
        Op("auth.login", login, WRITE, {"name": a(S, True, desc=d_name), "pin": a(S, True, desc=d_pin)},
           "Identifies a person. Answers a token to send in the header X-Workshop-Token (with an id of the browser in X-Workshop-Device). "
           "Too many wrong PINs lock the user for a while.", exclusive=False),
        Op("auth.logout", logout, WRITE, {}, "Ends the session of the token sent.", exclusive=False),
        Op("auth.whoami", whoami, READ, {}, "Who the caller is, the role, and the permission table (operation -> lowest role) the pages use to hide what the role cannot do.",
           log=False),
        Op("auth.resolve", resolve, READ, {"token": a(S, True, desc="Session token of a browser (the header X-Workshop-Token it sent)."),
                                           "device": a(S, desc="Id of that browser.")},
           "For local programs (the Vision server): who a browser's session token is, to apply the roles to the calls the page makes to them directly. "
           "Needs the local key; for a DWC session it is an administrator's operation.", log=False, exclusive=False),
        Op("auth.keepalive", keepalive, READ, {}, "The person is still there: postpones the expiry of the session (send on real use, at most once a minute).",
           log=False),
        Op("auth.change_pin", change_pin, WRITE, {"old_pin": a(S, True, desc="Current PIN."), "new_pin": a(S, True, desc=d_pin)},
           "The logged in person changes their own PIN.", exclusive=False),
        Op("users.list", users_list, ADMIN, {}, "Lists the people with their role, modes and last activity, and the session settings."),
        Op("users.add", users_add, ADMIN,
           {"name": a(S, True, desc=d_name), "pin": a(S, True, desc=d_pin), "role": a(S, True, choices=permissions.ROLES, desc=d_role),
            "modes": a(L, desc=d_modes), "camera_for_viewer": a(B, default=False, desc="A viewer sees the camera.")},
           "Adds a person. The first one created turns the identity on and has to be an administrator."),
        Op("users.set", users_set, ADMIN,
           {"name": a(S, True, desc="Person."), "role": a(S, choices=permissions.ROLES, desc=d_role), "modes": a(L, desc=d_modes),
            "camera_for_viewer": a(B, desc="A viewer sees the camera.")},
           "Changes role, modes or camera of a person. Nobody changes their own role and the last administrator stays."),
        Op("users.remove", users_remove, ADMIN, {"name": a(S, True, desc="Person.")},
           "Removes a person and ends their sessions. Not yourself, not the last administrator."),
        Op("users.reset_pin", users_reset_pin, ADMIN, {"name": a(S, True, desc="Person."), "pin": a(S, True, desc=d_pin)},
           "Sets a new PIN for a person and ends their sessions."),
        Op("users.settings", users_settings, ADMIN,
           {"idle_minutes": a(I, min=1, max=1440, desc="Minutes without activity before a session expires."),
            "max_hours": a(I, min=1, max=168, desc="Longest life of a session, active or not."),
            "never_expires": a(B, desc="Sessions never expire (the two limits above are ignored); they end by logging out or restarting the service."),
            "anonymous_viewer": a(B, desc="A caller with no login may read the state as a viewer (touch screen)."),
            "camera_for_viewer": a(B, desc="Viewers see the camera.")},
           "Reads or changes the session settings (without arguments it only reads)."),
        Op("users.enable", users_enable, ADMIN,
           {"enabled": a(B, True, desc="False switches the roles off: nobody is asked to identify and everybody is an administrator again, the people stay saved. True switches them on."),
            "pin": a(S, desc="The PIN of the administrator who asks (needed to switch off).")},
           "Switches the roles and PINs on or off without deleting the people. Switching off ends every session and needs the administrator's PIN; it also opens the camera and Vision on the network."),
        Op("audit.list", audit_list, ADMIN,
           {"from": a(S, desc="Start (YYYY-MM-DD or full date and time); default today."), "to": a(S, desc="End, same format; default the same day."),
            "user": a(S, desc="Only this person."), "op": a(S, desc="Only operations starting with this text."),
            "errors": a(B, desc="Only refused or failed calls."), "limit": a(I, min=1, max=200, default=50, desc="Rows per page."),
            "offset": a(I, min=0, default=0, desc="Rows to skip.")},
           "Reads the audit: who did what, from which device. It cannot be changed or deleted from the API."),
    ]
