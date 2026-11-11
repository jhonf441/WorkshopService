"""
access_admin -- the rules of the administrator of the access model (phase 2 of informes/control-acceso/PLAN-ACCESO.md): what a change may not do, what
the screens read, and the checker. The operations of the API (access_ops) only map arguments to these functions and errors to answers; the
file and its integrity are in access_store, the decision in access_eval / access_person.

Rules of a change (`guard`, run on the state the change WOULD produce, before it is saved):
  - nobody can be left unable to administer access control: every administrator (role admin) who is governed by the evaluator must still be allowed every
    access.* operation. A `deny` of their own, of a group of theirs, or a ceiling that does not include access.* is refused, for ANY administrator
    (not only the last one), so there is always someone who can undo a mistake;
  - nobody changes their own attachments, groups or ceiling (like nobody changes their own role);
  - a profile, a group or a person's attachment that is in use is not deleted; `base.administrator` is never attached (access_store).
The roles of role_store are shown as groups with one profile (the role) and are read-only here: they are not stored in the access file.
"""
import access_person
import access_profile
import access_store
import access_targets
import permissions
import role_store
from access_store import AccessError

# every operation an administrator needs to repair the model: all of them must stay allowed (see `guard`)
ADMIN_PROBES = ("access.profiles.list", "access.profiles.get", "access.profiles.set", "access.profiles.remove", "access.groups.list", "access.groups.get",
                "access.groups.set", "access.groups.remove", "access.attach", "access.detach", "access.ceiling.set", "access.profile.versions",
                "access.profile.rollback", "access.check", "access.person.get", "access.review", "access.report", "access.plugins.validate")
BRIEF = 250  # characters of what a change left before / after in the audit row (the row holds 600)


def _key(name):
    return str(name or "").strip().casefold()


class Env:
    """The three stores a call needs: access (access_store.AccessStore), users (users.UserStore or None), roles (role_store.RoleStore or None)."""

    def __init__(self, access, users=None, roles=None, mode_of=lambda: None):
        self.access, self.users, self.roles, self.mode_of = access, users, roles, mode_of

    def user(self, name):
        """The canonical name of a person, or None."""
        rec = self.users.users.get(_key(name)) if self.users is not None else None
        return rec["name"] if rec else None

    def role_names(self):
        return [r["name"] for r in self.roles.list()] if self.roles is not None and not self.roles.damaged else []

    def reserved(self):
        """Names a group cannot take: the base roles and the custom roles (they are shown as groups)."""
        return {_key(n) for n in list(permissions.ROLES) + [role_store.NONE_ROLE] + self.role_names()}

    def administrators(self):
        return [r for r in self.users.users.values() if r["role"] == permissions.ADMIN] if self.users is not None else []


# ---- the rules of a change ----

def guard(env, actor=None, same=None):
    """The `check` of AccessStore.transact: refuses a state in which an administrator could not administer access control. `same(view)` may add a rule."""
    def check(view):
        for rec in env.administrators():
            ident = {"name": rec["name"], "role": permissions.ADMIN, "modes": list(permissions.MODES), "camera": True}
            pr = access_person.build(view, ident)
            if pr is None:
                continue
            ctx = access_person.request_context(ident, {"mode": None, "args": {}})
            for op in ADMIN_PROBES:
                d = access_person.evaluate(pr, op, ctx)
                if not d.allowed:
                    raise AccessError("lockout", "the change would leave '%s' unable to use %s" % (rec["name"], op), user=rec["name"], op=op,
                                   profile=d.reason.get("profile") or d.reason.get("ceiling") or "")
        if same is not None:
            same(view)
    return check


def not_myself(actor, *names):
    """Raises self_change when `actor` is one of `names` (a person's own attachments, groups and ceiling are changed by somebody else)."""
    if actor and any(_key(n) == _key(actor) for n in names if n):
        raise AccessError("self_change", "nobody changes their own attachments")


def brief_profile(doc, version=None):
    """A profile as short text for the audit: v<n>|decision:id:operations;..."""
    if not doc:
        return "-"
    body = ";".join("%s:%s:%s" % (s["decision"], s["id"], ",".join(s["operations"][:4]) + ("+" if len(s["operations"]) > 4 else "")) for s in doc["rules"])
    return (("v%s|" % version if version else "") + body)[:BRIEF]


def brief_attach(rec):
    if not rec:
        return "-"
    return ("%s|%s|%s" % (",".join(rec.get("profiles") or ()), ",".join(rec.get("groups") or rec.get("members") or ()), rec.get("ceiling") or ""))[:BRIEF]


# ---- reading ----

def profile_row(view, name, doc, base, version=None):
    h = view.holders(name)
    row = {"name": name, "base": base, "rules": len(doc["rules"]), "attached_to": h}
    if version is not None:
        row["version"] = version
    return row


def profile_list(env):
    v = env.access.view()
    rows = []
    for d in env.access.list():
        e = v.state["versions"].get(_key(d["name"]))
        rows.append(profile_row(v, d["name"], d, False, e["active"] if e else 1))
    base = [profile_row(v, n, d, True) for n, d in sorted(access_store.access_base.BASE_PROFILES.items())]
    plugin = [profile_row(v, n, d, True) for n, d in access_store.access_base.plugin_profiles().items()]
    return {"damaged": env.access.damaged, "profiles": rows, "base": base, "plugin": plugin,
            "limits": {"profiles": access_store.MAX_PROFILES, "versions": access_store.MAX_VERSIONS, "rules": access_profile.MAX_RULES,
                       "entries": access_profile.MAX_ENTRIES, "groups": access_store.MAX_GROUPS, "attached": access_store.MAX_ATTACHED,
                       "memberships": access_store.MAX_MEMBERSHIPS},
            "never_attached": [access_store.FORBIDDEN_ATTACH]}


def profile_get(env, name):
    v = env.access.view()
    r = v.resolve(name)
    if r is None:
        raise AccessError("unknown_profile", "there is no profile '%s'" % name, profile=str(name))
    canonical, doc, base = r
    out = {"name": canonical, "base": base, "document": doc, "attached_to": v.holders(canonical)}
    if not base:
        vs = env.access.versions(canonical)
        out["version"] = next(x["n"] for x in vs if x["active"])
        out["versions"] = len(vs)
    return out


def group_row(view, g):
    return {"name": g["name"], "source": "group", "readonly": False, "description": g.get("description", ""), "profiles": list(g["profiles"]),
            "ceiling": g["ceiling"], "members": view.members(g["name"]), "updated": g.get("updated", ""), "updated_by": g.get("updated_by", "")}


def role_rows(env):
    """The custom roles as groups with one profile: the role itself (read-only; they are not in the access file)."""
    out = []
    for r in (env.roles.list() if env.roles is not None and not env.roles.damaged else []):
        members = sorted((u["name"] for u in env.users.users.values() if u["role"] == r["name"]), key=str.casefold) if env.users is not None else []
        out.append({"name": r["name"], "source": "role", "readonly": True, "description": r.get("description", ""), "profiles": [r["name"]],
                    "ceiling": None, "members": members, "updated": r.get("updated", ""), "updated_by": r.get("updated_by", ""),
                    "role": {"base": r["base"], "grant": list(r["grant"]), "deny": list(r["deny"])}})
    return out


def group_list(env):
    v = env.access.view()
    groups = [group_row(v, g) for g in sorted(v.state["groups"].values(), key=lambda g: g["name"].casefold())]
    return {"damaged": env.access.damaged, "groups": groups + role_rows(env)}


def group_get(env, name):
    v = env.access.view()
    g = v.state["groups"].get(_key(name))
    if g is not None:
        return {"group": group_row(v, g)}
    for r in role_rows(env):
        if _key(r["name"]) == _key(name):
            return {"group": r}
    raise AccessError("unknown_group", "there is no group '%s'" % name, group=str(name))


def person_get(env, user):
    name = env.user(user)
    if name is None:
        raise AccessError("unknown_user", "there is no person '%s'" % user, user=str(user))
    v = env.access.view()
    p = v.person(name)
    rec = env.users.users[_key(name)]
    p.update(name=name, role=rec["role"], governed=v.has_attachments(name) and not env.access.damaged,
             profiles=[x for x in p["profiles"]], damaged=env.access.damaged)
    return p


# ---- the checker ----

def check(env, args):
    """What would the model answer for a person, an operation and a request: the decision, the rule that decided and why every other
    one did not match. Changes nothing."""
    name = env.user(args["user"])
    if name is None:
        raise AccessError("unknown_user", "there is no person '%s'" % args["user"], user=str(args["user"]))
    operation = str(args["operation"]).strip()
    target = args.get("target") or access_targets.target_of(operation, args.get("args"))  # what the real call would declare
    if target is not None and not access_profile.concrete_target(target):
        raise AccessError("invalid_args", "the target must be workshop:<plugin>:<type>/<id> with no wildcard", field="target")
    rec = env.users.users[_key(name)]
    cam = bool(rec.get("camera_for_viewer") or env.users.get_settings().get("camera_for_viewer"))
    ident = {"name": name, "role": rec["role"], "modes": list(rec.get("modes") or []), "id": None, "camera": cam}
    if ident["role"] not in permissions.RANK:
        ident = role_store.custom_identity(ident, env.roles)
    mode = str(args.get("mode") or "").strip().lower() or None
    if mode is None and args.get("mode_now"):
        mode = env.mode_of()
    dctx = {"args": args.get("args") or {}, "modes": ident["modes"], "camera": cam, "mode": mode, "role_def": ident.get("role_def")}
    for k in ("job_running", "machine_on"):
        if args.get(k) is not None:
            dctx[k] = bool(args[k])
    via = args.get("via") or "session"
    legacy_ok, legacy_why = permissions.decide(ident.get("role_name") or ident["role"], operation, dctx)
    out = {"user": name, "operation": operation, "target": target or access_profile.default_target(operation),
           "legacy": {"allowed": legacy_ok, "reason": legacy_why}}
    view = None if env.access.damaged else env.access.view()
    pr = access_person.build(view, ident) if view is not None else None
    if pr is None:
        out.update(engine="legacy", allowed=legacy_ok, reason={"code": "allow" if legacy_ok else legacy_why or "role"}, deciding=None, rules=[],
                   groups=[])
        return out
    ctx = access_person.request_context(ident, dctx, via)
    dec = access_person.evaluate(pr, operation, ctx, target)
    rows = access_person.explain(pr, operation, ctx, target)
    deciding = next((r for r in rows if r["profile"] == dec.reason.get("profile") and r["id"] == dec.reason.get("id")), None) if dec.reason.get("profile") else None
    out.update(engine="access", allowed=dec.allowed, reason=dict(dec.reason), deciding=deciding, rules=rows, groups=list(pr.groups))
    return out

