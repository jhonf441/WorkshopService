"""
roles_ops -- the operations roles.* of the API (phase 2 of informes/permisos-por-rol/DISENO.md). Administrator only (permissions.OP_ROLES),
and `roles.*` can never be granted to another role (permission_caps.NOT_DELEGABLE).

  roles.list        the custom roles, the capabilities (what a grant or a denial may name) and the limits
  roles.get         one role (base or custom), who has it and what it adds or takes away
  roles.set         creates or replaces a custom role (a base role + grants + denials); asks for a confirmation like keys.create
  roles.remove      deletes a custom role nobody has; asks for a confirmation
  roles.effective   what a person or a role may do, operation by operation, with the reason of each block

The rules are in permissions.py (decide), the validation and the file in role_store.py; this file maps arguments to them and errors to
answers. Every change leaves in the audit the role before and after (ctx["audit_detail"], read by audit.record).
"""
import json

import identity
import permission_caps as caps
import permissions
import role_store
from messages import M
from workshop_api import ADMIN, ApiError, Arg, Op

_STATUS = {"invalid_name": 422, "reserved_name": 422, "invalid_base": 422, "admin_base": 422, "invalid_entry": 422, "unknown_entry": 422,
           "not_delegable": 422, "stop_deny": 422, "conflict_entries": 422, "too_many": 422, "invalid_args": 422, "unknown_role": 404,
           "unknown_user": 404, "in_use": 409, "damaged": 403, "save_failed": 500}
DETAIL_SIDE = 250  # characters of the role before / after kept in the audit row (the row holds 600)


def _error(e):
    """role_store.RoleError -> an answer with a translated text (key roles_err_<code>)."""
    extra = {"reason": e.code}
    for k in ("field", "entry", "users"):
        if k in e.extra:
            extra[k] = e.extra[k]
    text = M("roles_err_" + e.code, entry=e.extra.get("entry", ""), max=role_store.MAX_ROLES, users=", ".join(e.extra.get("users") or ()))
    return identity.StatusError(e.code if e.code in _STATUS else "failed", text, _STATUS.get(e.code, 409), **extra)


def _actor(ctx):
    u = ctx.get("user")
    return u.get("name") if isinstance(u, dict) and not u.get("compat") else ""


def _brief(rec):
    """A role as one short text for the audit: base|grants|denials."""
    if not rec:
        return "-"
    return ("%s|%s|%s" % (rec["base"], ",".join(rec["grant"]), ",".join(rec["deny"])))[:DETAIL_SIDE]


def _detail(name, before, after):
    return json.dumps({"role": name, "before": _brief(before), "after": _brief(after)}, ensure_ascii=False, separators=(",", ":"))


def _view(rec, n_users=0):
    out = dict(rec)
    out["users"] = n_users
    return out


def _category_key(cid):
    return "capcat_" + cid


def capability_view():
    """The capabilities for the screens: id, category, class, risk, the operations it groups, a translated title and what a role can do with it."""
    out = []
    for item in caps.describe():
        cid = item["id"]
        item["title"] = M("cap_" + cid.replace(".", "_"))
        item["delegable"] = cid == caps.HARDWARE_PARAMS or any(caps.delegable(p) for p in item["ops"])
        item["deniable"] = not caps.has_stop(cid, permissions.STOP_OPS)
        out.append(item)
    return out


def make_ops(roles_of, users_of):
    """The operations. roles_of() returns the role_store.RoleStore, users_of() the users.UserStore (either may be None)."""
    S, B, L = "str", "bool", "list"
    a = Arg

    def rstore():
        st = roles_of()
        if st is None:
            raise ApiError("internal", M("roles_err_unavailable"))
        return st

    def holders(name):
        """Names of the people who have the role `name`."""
        us = users_of()
        return [u["name"] for u in us.list() if u["role"] == name] if us is not None else []

    def roles_list(args, ctx):
        st = rstore()
        return {"damaged": st.damaged, "bases": list(permissions.CUSTOM_BASES), "base_roles": list(permissions.ROLES),
                "roles": [_view(r, len(holders(r["name"]))) for r in st.list()], "capabilities": capability_view(),
                "categories": [{"id": c, "title": M(_category_key(c))} for c in caps.CATEGORIES], "classes": list(caps.CLASSES),
                "not_delegable": list(caps.NOT_DELEGABLE), "stop_ops": sorted(permissions.STOP_OPS),
                "limits": {"roles": role_store.MAX_ROLES, "entries": role_store.MAX_ENTRIES, "description": role_store.MAX_DESCRIPTION}}

    def roles_get(args, ctx):
        name = str(args["name"]).strip()
        if name.strip().lower() in permissions.ROLES:
            r = name.strip().lower()
            return {"role": {"name": r, "base": r, "builtin": True, "description": "", "grant": [], "deny": []}, "users": holders(r),
                    "allow": [], "deny": []}
        rec = rstore().get(name)
        if rec is None:
            raise _error(role_store.RoleError("unknown_role"))
        allow, deny = permissions.resolved_lists(rec["name"], rec)
        return {"role": rec, "users": holders(rec["name"]), "allow": allow, "deny": deny,
                "hardware_params": caps.HARDWARE_PARAMS in rec["grant"]}

    def roles_set(args, ctx):
        try:
            before, after = rstore().set(args["name"], args["base"], args.get("grant"), args.get("deny"), args.get("description") or "", _actor(ctx))
        except role_store.RoleError as e:
            raise _error(e)
        ctx["audit_detail"] = _detail(after["name"], before, after)
        return {"role": _view(after, len(holders(after["name"]))), "created": before is None, "before": before}

    def roles_remove(args, ctx):
        st = rstore()
        name = st.canonical(args["name"])
        try:
            old = st.remove(args["name"], holders(name) if name else ())
        except role_store.RoleError as e:
            raise _error(e)
        ctx["audit_detail"] = _detail(old["name"], old, None)
        return {"removed": old}

    def roles_effective(args, ctx):
        who_user, who_role = str(args.get("user") or "").strip(), str(args.get("role") or "").strip()
        if bool(who_user) == bool(who_role):
            raise ApiError("invalid_args", M("roles_err_effective_subject"), field="user")
        st = rstore()
        modes = camera = None
        if who_user:
            us = users_of()
            rec = us.users.get(who_user.casefold()) if us is not None else None
            if rec is None:
                raise _error(role_store.RoleError("unknown_user"))
            role_label, modes = rec["role"], list(rec.get("modes") or [])
            camera = bool(rec.get("camera_for_viewer") or us.get_settings().get("camera_for_viewer"))
            subject = {"type": "user", "name": rec["name"]}
        else:
            role_label, subject = who_role, {"type": "role", "name": who_role}
        if role_label in permissions.ROLES:
            role, rd = role_label, None
        else:
            rd = st.get(role_label)
            if rd is None and not who_user:
                raise _error(role_store.RoleError("unknown_role"))
            role = rd["name"] if rd else role_label  # a person whose role vanished: decide() refuses everything (unknown_role)
        if args.get("modes") is not None:
            modes = permissions.clean_modes(args["modes"])
        if modes is None:
            modes = list(permissions.MODES)
        if args.get("camera") is not None:
            camera = bool(args["camera"])
        mode = str(args.get("mode") or "").strip().lower() or None
        ctx_ = {"modes": modes, "camera": bool(camera), "mode": mode}
        rows = permissions.effective_ops(role, rd, ctx_)
        if rd:
            ident = {"role": rd["base"], "role_name": rd["name"]}
        elif role in permissions.RANK:
            ident = {"role": role}
        else:
            ident = {"role": role_store.NONE_ROLE, "role_name": role}
        prefix = str(args.get("prefix") or "").strip()
        out = []
        for r in rows:
            r["category"] = (caps.CAPABILITIES.get(r["capability"]) or {}).get("category")
            if not r["allowed"]:
                r["message"] = identity.forbidden_message(r["reason"], ident, r["needed_role"], mode)
            if prefix and not r["op"].startswith(prefix):
                continue
            out.append(r)
        counts = {"allowed": sum(1 for r in out if r["allowed"]), "blocked": sum(1 for r in out if not r["allowed"]),
                  "by_grant": sum(1 for r in out if r["source"] == "grant"), "by_deny": sum(1 for r in out if r["source"] == "deny")}
        if args.get("blocked_only"):
            out = [r for r in out if not r["allowed"]]
        subject.update(role=ident["role"], role_name=rd["name"] if rd else role, modes=modes, camera=bool(camera), mode=mode)
        return {"subject": subject, "counts": counts, "ops": out,
                "hardware_params": bool(rd and caps.HARDWARE_PARAMS in rd["grant"]) or role == permissions.ADMIN}

    d_name = "Name of the custom role (1 to 32 letters, digits, spaces, dots or hyphens; not the name of a base role)."
    d_base = "Base role it starts from: viewer, operator or technician (never admin)."
    d_grant = ("What it may do on top of its base role: capability ids (see roles.list), operation names or patterns such as lights.*. "
               "Operations that cannot be delegated (users, roles, keys, passwords...) are refused. machine.hardware_params is the explicit key to "
               "the hardware-risk parameters (M208, M92, M906, M913, M917, M569, M584, prologue).")
    d_deny = "What it may NOT do even if its base role may (same kinds of entries). Stopping can never be denied. A denial wins over a grant."
    return [
        Op("roles.list", roles_list, ADMIN, {}, "Lists the custom roles (with how many people have each), the capabilities a grant or a denial may name, "
           "the operations that cannot be delegated and the limits.", log=False),
        Op("roles.get", roles_get, ADMIN, {"name": a(S, True, desc="A base role (viewer, operator, technician, admin) or a custom role.")},
           "One role: its definition, the people who have it and the operations it adds to or takes away from its base role.", log=False),
        Op("roles.set", roles_set, ADMIN,
           {"name": a(S, True, desc=d_name), "base": a(S, True, desc=d_base), "grant": a(L, desc=d_grant), "deny": a(L, desc=d_deny),
            "description": a("str", desc="Free text, up to %d characters." % role_store.MAX_DESCRIPTION)},
           "Creates a custom role or replaces the one with that name (the whole definition is replaced). The change applies to the people who have it "
           "on their next call. Needs a confirmation; the audit keeps the role before and after.", confirm={"level": 3, "key": "roles.set"}),
        Op("roles.remove", roles_remove, ADMIN, {"name": a(S, True, desc="Custom role.")},
           "Deletes a custom role. Refused while somebody has it. Needs a confirmation; the audit keeps the role.",
           confirm={"level": 3, "key": "roles.remove"}),
        Op("roles.effective", roles_effective, ADMIN,
           {"user": a(S, desc="A person (their role, modes and camera are used)."), "role": a(S, desc="Or a role (base or custom); then modes default to all, camera to off."),
            "modes": a(L, desc="Modes of an operator to assume (laser, cnc, fff)."), "mode": a(S, desc="Mode the machine is in now (laser, cnc, fff), if known."),
            "camera": a(B, desc="Assume the camera is (or is not) allowed to a viewer."), "blocked_only": a(B, default=False, desc="Only what is blocked."),
            "prefix": a(S, desc="Only operations starting with this text.")},
           "What a person or a role may do, operation by operation, with the reason of every block (role, denied, mode, camera) and whether it comes "
           "from the base role, a grant or a denial. `escalated` tells the same call when it changes settings or writes hardware parameters.", log=False),
    ]
