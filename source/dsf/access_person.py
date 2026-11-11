"""
access_person -- where the evaluator of the access model (access_eval) governs a person (phase 2 of informes/control-acceso/PLAN-ACCESO.md).

A person is governed by the evaluator ONLY when something is attached to them: a profile of their own, a group with profiles, or a permissions
ceiling of theirs or of one of their groups. Everybody else is decided by permissions.decide exactly as before (`decide` answers None and
identity falls back). For a governed person the profiles are, in this order:

  the base profiles of their base role (access_base.base_profiles_for: the ladder of OP_ROLES, the camera rule of a viewer)
  + the custom role they hold, as ONE profile (role_profile: its grants as allow, its denials as deny) so a role and an attachment add up
  + every profile attached to them and to their groups (the union; a deny anywhere wins, see access_eval)

and every ceiling (theirs and their groups') must allow the call too, so a ceiling of a group cuts everybody in it. Stopping is allowed
before anything else; an operation that cannot be delegated is conceded only by a base profile (the administrator's), never by an attached one.
A custom role that cannot be turned into a profile (it cannot happen with a role the store accepted) leaves the person with nothing but stopping.

Known and deliberate difference from permissions.decide for a person who holds a custom role AND has attachments: a grant of the role that
covers a mode-gated operation carries the mode condition of the person (stricter than before, never looser), and the camera flag of a viewer
does not cut an operation that the role grants by name.
"""
import collections
import re

import access_base
import access_eval
import access_profile
import permission_caps as caps
import permissions

Person = collections.namedtuple("Person", "name profiles sources ceilings broken groups")


def role_profile(rd):
    """The custom role `rd` (a role_store record) as a profile document; None when it adds and denies nothing; ValueError when it cannot be one. Capability ids are written as cap:<id>
    (a name that is both an operation and a capability has always meant the capability in a role: permissions.entry_hits)."""
    def entry(e):
        return access_profile.CAP_PREFIX + e if e in caps.CAPABILITIES else e

    gated_base = rd["base"] in (permissions.VIEWER, permissions.OPERATOR)
    plain, gated = [], []
    for e in rd.get("grant") or ():
        hits_gated = gated_base and any(permissions.entry_hits(e, op) for op in permissions.MODE_GATED)
        (gated if hits_gated else plain).append(entry(e))
    rules = []
    if plain:
        rules.append({"id": "RoleGrant", "decision": "allow", "operations": plain})
    if gated:
        rules.append({"id": "RoleGrantInYourModes", "decision": "allow", "operations": gated, "when": {"mode": [access_profile.MODE_VARIABLE]}})
    if rd.get("deny"):
        rules.append({"id": "RoleDeny", "decision": "deny", "operations": [entry(e) for e in rd["deny"]]})
    if not rules:
        return None  # a role with nothing added is its base role
    try:
        return access_profile.validate({"version": access_profile.SCHEMA_VERSION, "name": _safe_name(rd["name"]), "rules": rules})
    except access_profile.ProfileError as e:
        raise ValueError("the role cannot be a profile: %s" % e)


def _safe_name(name):
    return "Role_" + re.sub(r"[^A-Za-z0-9_.\-]", "_", str(name))[:58]


def build(view, ident):
    """The Person the evaluator decides for, or None when nothing is attached to the person (permissions.decide decides)."""
    name = ident.get("name")
    if not name or not view.has_attachments(name):
        return None
    att = view.person(name)
    role, camera, rd = ident.get("role"), bool(ident.get("camera")), ident.get("role_def")
    profiles, sources, broken = [], [], False
    if role in permissions.RANK:
        for d in access_base.base_profiles_for(role, camera):
            profiles.append(d)
            sources.append("base")
        if rd:
            try:
                doc = role_profile(rd)
            except ValueError:
                broken = True
            else:
                if doc is not None:
                    profiles.append(doc)
                    sources.append("role")
    for d in view.documents(att["all_profiles"]):
        profiles.append(d)
        sources.append("attached")
    return Person(name, profiles, sources, view.documents(att["ceilings"]), broken, att["groups"])


def request_context(ident, dctx, via="session", extra=None):
    """The context of access_eval for a call: the cleaned arguments, the mode of the machine, the modes of the person, the way in."""
    ctx = {"args": dctx.get("args") or {}, "mode": dctx.get("mode"), "modes": ident.get("modes") if "modes" not in dctx else dctx.get("modes"), "via": via}
    for k in ("job_running", "machine_on"):
        if dctx.get(k) is not None:
            ctx[k] = dctx[k]
    ctx.update(extra or {})
    return ctx


def evaluate(pr, op, ctx, target=None):
    """access_eval.Decision for a Person. Every ceiling must allow; a refusal by a ceiling names it."""
    if op in permissions.STOP_OPS:
        return access_eval.Decision(True, {"code": "stop"})
    if pr.broken:
        return access_eval.Decision(False, {"code": "role_unreadable"})
    if not pr.ceilings:
        return access_eval.evaluate(op, pr.profiles, ctx, target)
    first = None
    for b in pr.ceilings:
        d = access_eval.evaluate(op, pr.profiles, ctx, target, b)
        if not d.allowed:
            if d.reason["code"] == "ceiling":
                d.reason["ceiling"] = b["name"]
            return d
        first = first or d
    return first


def decide(view, ident, op, dctx, target=None, via="session"):
    """access_eval.Decision of a governed person, or None when nothing is attached to them (use permissions.decide)."""
    pr = build(view, ident)
    if pr is None:
        return None
    return evaluate(pr, op, request_context(ident, dctx, via), target)


def legacy_why(decision, op, ident, dctx):
    """The reason code of permissions.decide that a decision stands for (what the pages and clients already understand): "" | "denied" |
    "ceiling" | "mode" | "mode_unknown" | "camera" | "role"."""
    code = decision.reason.get("code")
    if decision.allowed:
        return ""
    if code == "explicit_deny":
        return "denied"
    if code == "ceiling":
        return "ceiling"
    if op in permissions.CAMERA_OPS and ident.get("role") == permissions.VIEWER and not dctx.get("camera"):
        return "camera"
    if "mode" in decision.reason.get("failed_conditions", ()):
        return "mode" if str(dctx.get("mode") or "").strip().lower() in permissions.MODES else "mode_unknown"
    return "role"


def explain(pr, op, ctx, target=None):
    """Every rule the evaluator looked at, for the checker: [{"source", "profile", "id", "decision", "matched", "why"}]. `source` is
    base / role / attached / ceiling; `why` is [] when the rule matched, else why not (operation, target, condition:<key>)."""
    target = target or access_profile.default_target(op)
    rows = []
    for src, doc in list(zip(pr.sources, pr.profiles)) + [("ceiling", b) for b in pr.ceilings]:
        for st in doc["rules"]:
            matched, why = access_eval.rule_report(st, op, target, ctx)
            rows.append({"source": src, "profile": doc["name"], "id": st["id"], "decision": st["decision"], "matched": matched, "why": why})
    return rows
