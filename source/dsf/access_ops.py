"""
access_ops -- the operations access.* of the API (phase 2 of informes/control-acceso/PLAN-ACCESO.md). Administrator only (permissions.OP_ROLES) and never
delegable (permission_caps.NOT_DELEGABLE: `access.*`). The rules are in access_admin, the file in access_store, the decision in access_person.

  access.profiles.list / get / set / remove      custom profiles (a save is a new version) and the base ones (read-only)
  access.profile.versions / rollback              the (up to 5) versions of a profile; go back to an older one
  access.groups.list / get / set / remove        groups; the custom roles are listed as groups with one profile (read-only)
  access.attach / access.detach                     a profile to a person or a group, or a person into a group
  access.ceiling.set                            the permissions ceiling of a person or a group
  access.attach.validate / detach.validate / ceiling.validate / groups.validate
                                              dry runs of the four changes above (groups.validate: set, or remove with `remove`): same guard, same
                                              refusals, nothing written, no audit row
  access.person.get                           what a person has: groups, profiles (own and through groups), ceiling
  access.check                                what the model would answer for (person, operation, target, context); changes nothing; `items`: up to 100
  access.profiles.validate                    dry run of access.profiles.set: the same refusals and warnings, nothing written, no version, no audit row
  auth.can                                    ANY role: would the caller's OWN identity be allowed this operation (and target)? the cause, the profile and
                                              the rule by name; `operations`: up to 100; never about another person
  access.plugins.validate                     reads the permissions.json of the installed plugins, validates them and registers their profiles
                                              (plugin.<id>.readonly / operator / admin, attachable like any profile); changes nothing stored
  access.review                               the review of accesses (access_review): findings, high severity first; reads only
  access.report                               people and keys: lockouts, last sign-in, age of the PIN, last use of each capability, keys; reads only

Every change asks for a level 3 confirmation and leaves in the audit the thing before and after (ctx["audit_detail"], read by audit.record).
The access file is made when the first call needs it, next to the users file (the registry is built before the users store exists); the
decision of every call is made by identity.AuthRegistry through `identity.access_source`, which this module sets in `build`.
"""
import json
import os
import time

import access_admin
import access_plugin_files
import access_profile
import access_report
import access_review
import access_store
import access_targets
import access_usage
import audit_alarms
import identity
import messages
import permissions
from access_store import AccessError
from messages import M
from workshop_api import ADMIN, READ, ApiError, Arg, Op

_STATUS = {"invalid_profile": 422, "invalid_name": 422, "reserved_name": 422, "too_many": 422, "invalid_args": 422, "admin_profile": 422,
           "no_allow": 422, "unknown_profile": 404, "unknown_group": 404, "unknown_user": 404, "unknown_version": 404, "in_use": 409,
           "plugin_ceiling": 422, "already": 409, "not_attached": 409, "lockout": 409, "self_change": 409, "damaged": 403, "save_failed": 500}


def _text(e):
    """The translated text (key access_err_<code>) of an access_store.AccessError."""
    return M("access_err_" + e.code, detail=str(e), profile=e.extra.get("profile", ""), group=e.extra.get("group", ""), user=e.extra.get("user", ""),
             op=e.extra.get("op", ""), users=", ".join(e.extra.get("users") or ()), groups=", ".join(e.extra.get("groups") or ()))


def _error(e):
    """access_store.AccessError -> an answer with a translated text (key access_err_<code>)."""
    extra = {"reason": e.code}
    for k, v in e.extra.items():
        extra[k] = v
    text = _text(e)
    return identity.StatusError(e.code if e.code in _STATUS else "failed", text, _STATUS.get(e.code, 409), **extra)


def _confirm(key, title_key, text_key):
    """The confirmation of a change: level 3 with both languages inside the operation (api_ops.CONFIRM_TEXTS is not touched)."""
    texts = {lang: {"title": messages.render(lang, title_key), "text": messages.render(lang, text_key)} for lang in ("es", "en")}
    return {"level": 3, "key": key, "texts": texts}


def _actor(ctx):
    u = ctx.get("user")
    return u.get("name") if isinstance(u, dict) and not u.get("compat") else ""


def _detail(what, name, before, after):
    return json.dumps({"access": what, "name": name, "before": before, "after": after}, ensure_ascii=False, separators=(",", ":"))


def source(ctx, users):
    """The access file of the registry whose users store is `users` (made at the first call, next to the users file), else None."""
    if users is None or ctx.get("users") is not users:
        return None
    held = ctx.get("access")
    if held is not None and held[0] is users:
        return held[1]
    path = os.environ.get("WORKSHOP_ACCESS") or os.path.join(os.path.dirname(users.path) or ".", "workshop-access.json")
    store = access_store.AccessStore(path, log=ctx.get("log_file") or print)
    if ctx.get("registry") is not None:
        access_plugin_files.refresh(ctx["registry"].ops)  # the plugin profiles exist before the first decision that needs the file
    if not users.damaged:
        store.reconcile([u["name"] for u in users.users.values()])  # people removed while nobody was looking
    hooks = getattr(users, "on_removed", None)
    if isinstance(hooks, list):
        hooks.append(store.forget_user)
    ctx["access"] = (users, store)
    return store


def usage_source(ctx, users):
    """The last-use file of the registry whose users store is `users` (next to the users file; env WORKSHOP_ACCESS_USAGE), else None."""
    if users is None or ctx.get("users") is not users:
        return None
    held = ctx.get("usage")
    if held is not None and held[0] is users:
        return held[1]
    path = os.environ.get("WORKSHOP_ACCESS_USAGE") or os.path.join(os.path.dirname(users.path) or ".", "workshop-access-usage.json")
    store = access_usage.UsageStore(path, log=ctx.get("log_file") or print)
    hooks = getattr(users, "on_removed", None)
    if isinstance(hooks, list):
        hooks.append(store.forget)
    ctx["usage"] = (users, store)
    return store


class _Api:
    """The handlers and the table of one registry; `ctx` is the shared context of api_ops (users, roles, registry, log_file)."""

    def __init__(self, ctx):
        self.ctx = ctx

    def env(self):
        users = self.ctx.get("users")
        store = source(self.ctx, users)
        if store is None:
            raise ApiError("internal", M("access_err_unavailable"))
        reg = self.ctx.get("registry")
        if reg is not None:
            access_plugin_files.refresh(reg.ops)  # the plugin profiles an attachment may name are the ones installed now
        return access_admin.Env(store, users, self.ctx.get("roles"), (lambda: reg.mode_of()) if reg is not None else (lambda: None))

    @staticmethod
    def run(e, change, actor, same=None, dry=False):
        try:
            return e.access.transact(change, access_admin.guard(e, actor, same), dry=dry)
        except AccessError as x:
            raise _error(x)

    @staticmethod
    def read(fn, *args):
        try:
            return fn(*args)
        except AccessError as x:
            raise _error(x)

    @staticmethod
    def target(args):
        user, group = str(args.get("user") or "").strip(), str(args.get("group") or "").strip()
        if bool(user) == bool(group):
            raise _error(AccessError("invalid_args", "give a person (user) or a group (group), not both", field="user"))
        return ("user", user) if user else ("group", group)

    # ---- profiles ----
    def profiles_list(self, args, c):
        return self.read(access_admin.profile_list, self.env())

    def profiles_get(self, args, c):
        return self.read(access_admin.profile_get, self.env(), args["name"])

    def profiles_set(self, args, c):
        e, doc = self.env(), args["document"]
        r = self.run(e, lambda st: access_store.set_profile(st, doc, _actor(c), e.access.now), _actor(c))
        name = r["after"]["name"]
        c["access_changed_profile"] = r["after"]  # for the alarm of a profile that grants risk 4 (audit_alarms)
        c["audit_detail"] = _detail("profile.set", name, access_admin.brief_profile(r["before"]), access_admin.brief_profile(r["after"], r["version"]))
        out = access_admin.profile_get(e, name)
        out.update(created=r["before"] is None, changed=r["changed"])
        return out

    def profiles_remove(self, args, c):
        e = self.env()
        old = self.run(e, lambda st: access_store.remove_profile(st, args["name"]), _actor(c))
        c["audit_detail"] = _detail("profile.remove", old["name"], access_admin.brief_profile(old), "-")
        return {"removed": old}

    def versions(self, args, c):
        vs = self.env().access.versions(args["name"])
        if vs is None:
            raise _error(AccessError("unknown_profile", "there is no profile '%s'" % args["name"], profile=args["name"]))
        return {"name": vs[0]["doc"]["name"], "versions": vs, "max": access_store.MAX_VERSIONS}

    def rollback(self, args, c):
        e = self.env()
        r = self.run(e, lambda st: access_store.rollback_profile(st, args["name"], args["version"]), _actor(c))
        name = r["after"]["name"]
        c["access_changed_profile"] = r["after"]
        c["audit_detail"] = _detail("profile.rollback", name, access_admin.brief_profile(r["before"]), access_admin.brief_profile(r["after"], r["version"]))
        out = access_admin.profile_get(e, name)
        out["rolled_back_to"] = r["version"]
        return out

    # ---- groups ----
    def groups_list(self, args, c):
        return self.read(access_admin.group_list, self.env())

    def groups_get(self, args, c):
        return self.read(access_admin.group_get, self.env(), args["name"])

    def groups_set(self, args, c):
        e = self.env()
        actor, name, members = _actor(c), args["name"], args.get("members")
        before_members = e.access.view().members(name)

        def same(view):
            if members is not None:
                access_admin.not_myself(actor, *(set(before_members) ^ set(view.members(name))))
        r = self.run(e, lambda st: access_store.set_group(st, name, args.get("description") or "", args.get("profiles") or [], members, e.user,
                                                       e.reserved(), actor, e.access.now), actor, same)
        c["access_members_changed"] = sorted(set(before_members) ^ set(e.access.view().members(name)))  # for the alarm of an administrator's group
        c["audit_detail"] = _detail("group.set", name, access_admin.brief_attach(r["before"]), access_admin.brief_attach(r["after"]))
        return access_admin.group_get(e, name)

    def groups_remove(self, args, c):
        e = self.env()
        r = self.run(e, lambda st: access_store.remove_group(st, args["name"]), _actor(c))
        c["audit_detail"] = _detail("group.remove", args["name"], access_admin.brief_attach(r["before"]), "-")
        return {"removed": args["name"]}

    # ---- attachments ----
    @staticmethod
    def _myself(e, actor, kind, name):
        if kind == "user":
            try:
                access_admin.not_myself(actor, e.user(name) or name)
            except AccessError as x:
                raise _error(x)

    @staticmethod
    def _answer(e, kind, name, what, c, before):
        after = access_store.brief_of(e.access.view().state, kind, name, e.user)
        c["audit_detail"] = _detail(what, name, access_admin.brief_attach(before), access_admin.brief_attach(after))
        return access_admin.person_get(e, name) if kind == "user" else access_admin.group_get(e, name)

    def change_attachment(self, args, c, what, member_fn, profile_fn, dry=False):
        e, actor = self.env(), _actor(c)
        kind, name = self.target(args)
        profile, member_of = str(args.get("profile") or "").strip(), str(args.get("member_of") or "").strip()
        if bool(profile) == bool(member_of) or (member_of and kind != "user"):
            raise _error(AccessError("invalid_args", "give a profile, or a group for a person (member_of), not both", field="profile"))
        self._myself(e, actor, kind, name)
        before = access_store.brief_of(e.access.view().state, kind, name, e.user)

        def apply(st):
            if not member_of:
                return profile_fn(st, kind, name, profile, e.user)
            if not e.user(name):
                raise AccessError("unknown_user", "there is no person '%s'" % name, user=name)
            return member_fn(st, e.user(name), member_of)
        self.run(e, apply, actor, dry=dry)
        if dry:
            return {"valid": True, "what": what, "kind": kind, "name": e.user(name) or name if kind == "user" else name}
        if member_of:
            c["access_members_changed"] = [name]  # a person joined or left a group: the alarm looks at administrators
        return self._answer(e, kind, name, what, c, before)

    def attach(self, args, c):
        return self.change_attachment(args, c, "attach", access_store.join, access_store.attach)

    def detach(self, args, c):
        return self.change_attachment(args, c, "detach", access_store.leave, access_store.detach)

    def ceiling_set(self, args, c, dry=False):
        e, actor = self.env(), _actor(c)
        kind, name = self.target(args)
        self._myself(e, actor, kind, name)
        before = access_store.brief_of(e.access.view().state, kind, name, e.user)
        self.run(e, lambda st: access_store.set_ceiling(st, kind, name, str(args.get("profile") or "").strip(), e.user), actor, dry=dry)
        if dry:
            return {"valid": True, "what": "ceiling", "kind": kind, "name": e.user(name) or name if kind == "user" else name}
        return self._answer(e, kind, name, "ceiling", c, before)

    def person(self, args, c):
        return self.read(access_admin.person_get, self.env(), args["user"])

    def check(self, args, c):
        items = args.get("items")
        if items is None:
            if not args.get("operation"):
                raise _error(AccessError("invalid_args", "give an operation, or a list of them in items", field="operation"))
            return self.read(access_admin.check, self.env(), args)
        if args.get("operation"):
            raise _error(AccessError("invalid_args", "give an operation or items, not both", field="items"))
        out = self.read(access_admin.check_many, self.env(), args["user"], items)
        for row in out["items"]:
            if row.get("error"):
                row["error"]["text"] = _text(AccessError(row["error"]["code"], row["error"]["detail"]))
        return out

    def profiles_validate(self, args, c):
        """access.profiles.set without the write: the same guard on the state the change would produce, on a copy that is thrown away."""
        e, doc = self.env(), args["document"]
        actor = _actor(c)
        try:
            r = e.access.transact(lambda st: access_store.set_profile(st, doc, actor, e.access.now), access_admin.guard(e, actor), dry=True)
        except AccessError as x:
            raise _error(x)
        name, warnings = r["after"]["name"], []
        if not r["changed"]:
            warnings.append({"code": "unchanged", "text": M("access_warn_unchanged", profile=name)})
        if audit_alarms.admin_like(r["after"]):
            warnings.append({"code": "admin_like", "text": M("access_warn_admin_like", profile=name)})
        elif audit_alarms.grants_risk4(r["after"]):
            warnings.append({"code": "risk4", "text": M("access_warn_risk4", profile=name)})
        return {"valid": True, "name": name, "created": r["before"] is None, "changed": r["changed"], "version": r["version"], "warnings": warnings}

    def attach_validate(self, args, c):
        """access.attach without the write (same guard, same refusals, nothing saved, no audit detail)."""
        return self.change_attachment(args, c, "attach", access_store.join, access_store.attach, dry=True)

    def detach_validate(self, args, c):
        return self.change_attachment(args, c, "detach", access_store.leave, access_store.detach, dry=True)

    def ceiling_validate(self, args, c):
        return self.ceiling_set(args, c, dry=True)

    def groups_validate(self, args, c):
        """access.groups.set (or, with remove, access.groups.remove) without the write."""
        e = self.env()
        actor, name, members = _actor(c), args["name"], args.get("members")
        if args.get("remove"):
            self.run(e, lambda st: access_store.remove_group(st, name), actor, dry=True)
            return {"valid": True, "what": "remove", "kind": "group", "name": name}
        before_members = e.access.view().members(name)

        def same(view):
            if members is not None:
                access_admin.not_myself(actor, *(set(before_members) ^ set(view.members(name))))
        self.run(e, lambda st: access_store.set_group(st, name, args.get("description") or "", args.get("profiles") or [], members, e.user,
                                                   e.reserved(), actor, e.access.now), actor, same, dry=True)
        return {"valid": True, "what": "set", "kind": "group", "name": name}

    # ---- the caller's own answers (auth.can) ----
    def can(self, args, c):
        """Would the caller be allowed this? Only the identity of the call (like auth.whoami): there is no argument that names a person."""
        reg = self.ctx.get("registry")
        st = reg.users if reg is not None else None
        ops, single = args.get("operations"), args.get("operation")
        if (ops is None) == (not single):
            raise _error(AccessError("invalid_args", "give an operation, or a list of them in operations (not both)", field="operation"))
        if ops is None:
            asked = [{"operation": single, "target": args.get("target"), "args": args.get("args")}]
        else:
            asked = self.read(access_admin.batch_items, ops)
        if st is None or not st.configured():  # nobody has been created (or the roles are switched off): everybody is administrator, as before
            env = {"configured": False, "named": False, "login_required": False}
            answer = lambda op, tg, ar: {"allowed": True, "reason": {"code": "allow"}}  # noqa: E731
        else:
            ident = c.get("user") if isinstance(c.get("user"), dict) and not c["user"].get("compat") else None
            ident = ident or st.anonymous()
            env = {"configured": True, "named": bool(ident and ident.get("name")), "login_required": ident is None}
            answer = lambda op, tg, ar: self._own(reg, st, ident, op, tg, ar)  # noqa: E731
        rows = [self._row(it, answer, ops is None) for it in asked]
        return dict(rows[0], **env) if ops is None else dict(env, items=rows)

    @staticmethod
    def _row(it, answer, strict):
        """One item of auth.can: its answer, or (a batch) {"operation", "error"} when the item itself is not usable; a single call refuses instead."""
        try:
            if isinstance(it, str):
                it = {"operation": it}
            if not isinstance(it, dict) or set(it) - {"operation", "target", "args"}:
                raise AccessError("invalid_args", "every item is an operation name or an object with operation, target and args", field="items")
            op = str(it.get("operation") or "").strip()
            if not op or len(op) > 100:
                raise AccessError("invalid_args", "every item needs an operation", field="operation")
            target = it.get("target")
            if target is not None and not access_profile.concrete_target(target):
                raise AccessError("invalid_args", "the target must be workshop:<plugin>:<type>/<id> with no wildcard", field="target")
            call_args = it.get("args") if isinstance(it.get("args"), dict) else {}
            shown = target or access_targets.target_of(op, call_args) or access_profile.default_target(op)
            return dict(operation=op, target=shown, **answer(op, target, call_args))
        except AccessError as x:
            if strict:
                raise _error(x)
            return {"operation": str(it.get("operation") or "") if isinstance(it, dict) else "", "error": {"code": x.code, "text": _text(x)}}

    @staticmethod
    def _own(reg, st, ident, op, target, call_args):
        """The answer for the caller's identity (None: nobody identified) with its text; a stop is allowed for everybody."""
        if op in permissions.STOP_OPS:
            return {"allowed": True, "reason": {"code": "stop"}}
        if ident is None:
            return {"allowed": False, "reason": {"code": "session"}, "text": M("auth_login_required")}
        if st.damaged:
            return {"allowed": False, "reason": {"code": "damaged"}, "text": M("auth_users_damaged")}
        out = reg.own_answer(ident, op, call_args, target)
        r = out["reason"]
        if not out["allowed"]:
            why = r.get("why") or r["code"]
            if why == "denied" and r.get("profile"):
                out["text"] = M("auth_forbidden_access_deny", profile=r["profile"])
            elif why == "ceiling" and r.get("ceiling"):
                out["text"] = M("auth_forbidden_ceiling", ceiling=r["ceiling"])
            else:
                known = why if why in ("mode", "mode_unknown", "camera", "denied", "unknown_role") else "role"
                out["text"] = identity.forbidden_message(known, ident, r.get("needed_role") or permissions.ADMIN, reg.mode_of())
        return out

    def plugins_validate(self, args, c):
        reg = self.ctx.get("registry")
        report = access_plugin_files.refresh(reg.ops if reg is not None else {})
        for f in report["findings"]:
            f["text"] = M("access_plugin_finding_" + f["code"], plugin=f["plugin"], detail=f["detail"])
        return report
    def review(self, args, c):
        e = self.env()
        data = access_report.snapshot(e, self.ctx.get("keys"))
        found = access_review.review(data, int(time.time()))
        counts = {s: sum(1 for f in found if f["severity"] == s) for s in access_review.SEVERITIES}
        return {"generated": int(time.time()), "damaged": data["damaged"], "findings": found, "counts": counts, "high": counts["high"],
                "limits": {"unused_key_days": access_review.UNUSED_KEY_DAYS, "admin_login_days": access_review.ADMIN_LOGIN_DAYS,
                           "wide_key_breadth": access_review.WIDE_KEY_BREADTH}}

    def report(self, args, c):
        e = self.env()
        users = self.ctx.get("users")
        usage = usage_source(self.ctx, users)
        data = access_report.snapshot(e, self.ctx.get("keys"))
        return access_report.people_and_keys(data, users.lockouts() if users is not None else {}, usage.used() if usage is not None else {}, int(time.time()))

    # ---- the table ----
    def profile_ops(self):
        a = Arg
        change = _confirm("access.change", "access_confirm_change_title", "access_confirm_change_text")
        remove = _confirm("access.remove", "access_confirm_remove_title", "access_confirm_remove_text")
        return [
            Op("access.profiles.list", self.profiles_list, ADMIN, {}, "Lists the custom profiles (with who has each attached), the base ones and the limits.", log=False),
            Op("access.profiles.get", self.profiles_get, ADMIN, {"name": a("str", True, desc="A custom or base profile (not case sensitive).")},
               "One profile: its document, its active version and who has it attached.", log=False),
            Op("access.profiles.set", self.profiles_set, ADMIN,
               {"document": a("obj", True, desc='The profile: {"version": 1, "name", "rules": [{"id", "decision": "allow"|"deny", "operations": [...], '
                                                '"targets": [...], "when": {...}}]}. Saving a name that exists makes a new version (up to 5 are kept).')},
               "Creates a custom profile or saves a new version of it. Refused if it would leave an administrator unable to use access.*. Needs a confirmation; "
               "the audit keeps the profile before and after.", confirm=change),
            Op("access.profiles.remove", self.profiles_remove, ADMIN, {"name": a("str", True, desc="A custom profile.")},
               "Deletes a custom profile. Refused while a person or a group has it attached or as a ceiling. Needs a confirmation.", confirm=remove),
            Op("access.profile.versions", self.versions, ADMIN, {"name": a("str", True, desc="A custom profile.")},
               "The versions of a profile kept (up to 5), newest first, with who saved each and which one is active.", log=False),
            Op("access.profile.rollback", self.rollback, ADMIN,
               {"name": a("str", True, desc="A custom profile."), "version": a("int", True, desc="A version of access.profile.versions.")},
               "Makes an older version of a profile the active one. Needs a confirmation; the audit keeps both.", confirm=change),
        ]

    def group_ops(self):
        a = Arg
        change = _confirm("access.change", "access_confirm_change_title", "access_confirm_change_text")
        remove = _confirm("access.remove", "access_confirm_remove_title", "access_confirm_remove_text")
        return [
            Op("access.groups.list", self.groups_list, ADMIN, {},
               "Lists the groups with their profiles, ceiling and members. The custom roles appear as read-only groups with one profile.", log=False),
            Op("access.groups.get", self.groups_get, ADMIN, {"name": a("str", True, desc="A group or a custom role.")}, "One group.", log=False),
            Op("access.groups.set", self.groups_set, ADMIN,
               {"name": a("str", True, desc="1 to 32 letters, digits, spaces, dots or hyphens; not a base role or a custom role."),
                "description": a("str", desc="Free text, up to %d characters." % access_store.MAX_DESCRIPTION),
                "profiles": a("list", desc="Profiles attached to the group (custom or base, never base.administrator). The whole list is replaced."),
                "members": a("list", desc="People in the group. Left out: the members stay; given: it is the exact list (nobody can change their own membership).")},
               "Creates a group or replaces its description and profiles (its ceiling stays). Needs a confirmation; the audit keeps it before and after.",
               confirm=change),
            Op("access.groups.remove", self.groups_remove, ADMIN, {"name": a("str", True, desc="A group.")},
               "Deletes a group. Refused while it has people. Needs a confirmation.", confirm=remove),
        ]

    def attach_ops(self):
        a = Arg
        change = _confirm("access.change", "access_confirm_change_title", "access_confirm_change_text")
        d_target = "A person (user) or a group (group): one of the two."
        t_user, t_group = a("str", desc="A person of the workshop."), a("str", desc="A group (not a custom role: those are read-only).")
        return [
            Op("access.attach", self.attach, ADMIN,
               {"user": t_user, "group": t_group, "profile": a("str", desc="The profile to attach (custom or base, never base.administrator)."),
                "member_of": a("str", desc="Instead of a profile: the group to put the person in (only with user).")},
               "Attaches a profile to a person or a group, or puts a person in a group. " + d_target + " Nobody changes their own. Refused if it would "
               "leave an administrator unable to use access.*. Needs a confirmation; the audit keeps it before and after.", confirm=change),
            Op("access.detach", self.detach, ADMIN,
               {"user": t_user, "group": t_group, "profile": a("str", desc="The profile to detach."),
                "member_of": a("str", desc="Instead of a profile: the group to take the person out of.")},
               "The opposite of access.attach. " + d_target + " Needs a confirmation; the audit keeps it before and after.", confirm=change),
            Op("access.ceiling.set", self.ceiling_set, ADMIN,
               {"user": t_user, "group": t_group,
                "profile": a("str", desc="The profile that is the ceiling (it must have an allow rule). Empty: remove the ceiling.")},
               "Sets or removes the permissions ceiling of a person or a group: whatever they have, they can do nothing the ceiling does not allow. "
               + d_target + " Needs a confirmation.", confirm=change),
            Op("access.person.get", self.person, ADMIN, {"user": a("str", True, desc="A person.")},
               "What a person has: groups, profiles (own and through groups), ceiling, and whether the evaluator governs them.", log=False),
            Op("access.check", self.check, ADMIN,
               {"user": a("str", True, desc="A person."), "operation": a("str", desc="An operation name (or <ns>:<name>). Or give items."),
                "items": a("any", desc="Instead of operation: up to %d requests of the same person, each an object with operation and optionally target, "
                                        "args, mode, mode_now, job_running, machine_on, via. The answer has one entry per request, equal to the single answer." %
                                        access_admin.MAX_BATCH),
                "target": a("str", desc="workshop:<plugin>:<type>/<id> (no wildcard). Left out: the default target of the operation."),
                "args": a("obj", desc="The arguments of the call (they can escalate it: settings, hardware parameters)."),
                "mode": a("str", desc="Mode of the machine: laser, cnc or fff."), "mode_now": a("bool", desc="Use the mode the machine is in now."),
                "job_running": a("bool", desc="Context: a job is running."), "machine_on": a("bool", desc="Context: the machine is on."),
                "via": a("str", choices=("session", "key", "macro", "local"), desc="Way in (default session).")},
               "What the access model would answer for a person, an operation, a target and a context: allowed or not, the rule that decided and "
               "why each other rule did not match. Changes nothing. With items it answers a list of requests (up to %d) in one call." % access_admin.MAX_BATCH,
               log=False),
            Op("access.plugins.validate", self.plugins_validate, ADMIN, {},
               "Reads the permissions.json of every installed plugin, checks it (every operation it calls exists, is classified and is its own or declared "
               "shared; the three profiles use only known capabilities; the interface operation ui:<plugin>:open is declared) and registers the valid "
               "profiles (plugin.<namespace>.readonly, .operator, .admin) so they can be attached. Changes nothing stored.", log=False),
        ]

    def validate_ops(self):
        a = Arg
        t_user, t_group = a("str", desc="A person of the workshop."), a("str", desc="A group (not a custom role: those are read-only).")
        return [
            Op("access.profiles.validate", self.profiles_validate, ADMIN,
               {"document": a("obj", True, desc="The profile, as in access.profiles.set.")},
               "Dry run of access.profiles.set: runs the same checks (profile, reserved names, limits, a deny of a stop, an administrator left without "
               "access) on the state the save would produce and answers the same errors, plus warnings. Writes nothing, makes no version and leaves no "
               "audit row.", log=False),
            Op("access.attach.validate", self.attach_validate, ADMIN,
               {"user": t_user, "group": t_group, "profile": a("str", desc="The profile to attach."), "member_of": a("str", desc="Instead of a profile: the group.")},
               "Dry run of access.attach: the same checks (own access, base.administrator, unknown names, already attached, an administrator left without "
               "access, limits) on a copy; answers the same errors. Writes nothing and leaves no audit row.", log=False),
            Op("access.detach.validate", self.detach_validate, ADMIN,
               {"user": t_user, "group": t_group, "profile": a("str", desc="The profile to detach."), "member_of": a("str", desc="Instead of a profile: the group.")},
               "Dry run of access.detach: the same checks and errors on a copy. Writes nothing and leaves no audit row.", log=False),
            Op("access.ceiling.validate", self.ceiling_validate, ADMIN,
               {"user": t_user, "group": t_group, "profile": a("str", desc="The profile that would be the ceiling. Empty: remove the ceiling.")},
               "Dry run of access.ceiling.set: the same checks and errors (needs an allow rule, not a plugin profile, an administrator left without "
               "access) on a copy. Writes nothing and leaves no audit row.", log=False),
            Op("access.groups.validate", self.groups_validate, ADMIN,
               {"name": a("str", True, desc="A group."), "description": a("str", desc="As in access.groups.set."), "profiles": a("list", desc="As in access.groups.set."),
                "members": a("list", desc="As in access.groups.set."), "remove": a("bool", desc="true: dry run of access.groups.remove instead.")},
               "Dry run of access.groups.set (or, with remove, of access.groups.remove): the same checks and errors on a copy (a group with members "
               "cannot be removed, nobody changes their own membership, limits). Writes nothing and leaves no audit row.", log=False),
        ]

    def auth_ops(self):
        a = Arg
        return [
            Op("auth.can", self.can, READ,
               {"operation": a("str", desc="An operation name (or <ns>:<name>). Or give operations."),
                "target": a("str", desc="workshop:<plugin>:<type>/<id> (no wildcard). Left out: the target the call would declare."),
                "args": a("obj", desc="The arguments the call would carry (they can escalate it)."),
                "operations": a("any", desc="Instead of operation: up to %d items, each an operation name or an object with operation, target and args."
                                % access_admin.MAX_BATCH)},
               "Would the CALLER be allowed this operation (and target) now: allowed, and the cause (code, and the profile, rule and ceiling by name, "
               "never their contents). Only about the person making the call: it takes no person. A stop is always allowed. Any role, any session.",
               log=False),
        ]

    def review_ops(self):
        return [
            Op("access.review", self.review, ADMIN, {},
               "The review of accesses: profiles that reach risk 4, deny rules that can never hold, profiles nobody has, people with no group and no profile, "
               "wide keys unused for 30 days, administrators without a recent sign-in. Findings with a severity (high first); changes nothing.", log=False),
            Op("access.report", self.report, ADMIN, {},
               "People and keys: role, groups, locked PINs, last sign-in, age of the PIN, the last use of each capability, and each key with its last use. "
               "Reads only.", log=False),
        ]


def build(ctx):
    """The operations. Also tells identity where the access file is (a registry decides with it only for people who have attachments)."""
    ctx["access"] = None
    ctx["usage"] = None
    identity.access_source = lambda users: source(ctx, users)
    identity.usage_source = lambda users: usage_source(ctx, users)
    api = _Api(ctx)
    return api.profile_ops() + api.group_ops() + api.attach_ops() + api.validate_ops() + api.review_ops() + api.auth_ops()
