"""
access_eval -- THE evaluator of the access model: one function, one place, the order of section 3.3 of informes/control-acceso/PLAN-ACCESO.md.
Pure (no I/O). It runs in the shadow of permissions.decide: nothing in the service calls it yet.

    evaluate(operation, profiles, ctx=None, target=None, ceiling=None) -> Decision(allowed, reason)

Order:
  1  a STOP operation (permissions.STOP_OPS) is allowed, always: no profile, no ceiling and no missing context can block it
  2  an operation that cannot be delegated (permission_caps.NOT_DELEGABLE) is allowed only by a BASE profile (access_base: the base roles'
     ladder, e.g. the administrator's); a custom profile never concedes it, whatever it says
  3  any `deny` rule that matches (operation, target, conditions) decides: denied
  4  the permissions ceiling, when there is one: it must allow the call too (its own deny rules count in step 3)
  5  an `allow` rule that matches decides: allowed, EXCEPT when the arguments escalate the call (permissions.needed_role): then a
     matching allow rule must ALSO list, literally, the tier of the role the call needs (`tier:technician`, `tier:admin`) or, for the
     hardware-risk writes of permissions.ESCALATE_IN, `cap:machine.hardware_params`. A wildcard does not match a tier.
  6  nothing matched: denied (implicit)

ctx (all optional): args (cleaned arguments of the call), mode (now: laser / cnc / fff), modes (the modes the PERSON may operate: what
${person.modes} stands for; None = laser only, like permissions.clean_modes), job_running, machine_on, via (session / key / macro / local).
A condition whose value is not in ctx does not hold for an `allow` and does hold for a `deny` (fail closed both ways), except `mode` with all
three modes listed, which holds for an unknown mode too.

The Decision is a (allowed, reason) tuple; reason is a dict: code (stop, allow, explicit_deny, ceiling, escalated, not_delegable,
implicit_deny, bad_request), profile and id of the rule that decided when there is one, and for a refusal that was close
`failed_conditions` (the conditions that stopped an allow rule that matched the operation) and `needed_tier`.
"""
import collections

import access_base
import access_profile as ip
import permission_caps as caps
import permissions

Decision = collections.namedtuple("Decision", "allowed reason")


def _decision(allowed, code, profile=None, rule_id=None, **extra):
    r = {"code": code}
    if profile is not None:
        r["profile"] = profile
        r["id"] = rule_id
    r.update(extra)
    return Decision(allowed, r)


def _risk(operation):
    cid = caps.capability_of(operation) if ":" not in operation else None
    return caps.CAPABILITIES[cid]["risk"] if cid else 4  # not in a capability: the highest, fail closed


def _expand_modes(values, modes):
    out = []
    for v in values:
        out.extend(permissions.clean_modes(modes) if v == ip.MODE_VARIABLE else [v])
    return out


def _condition(key, want, ctx, operation):
    """True / False / None (the context does not say)."""
    if key == "risk_max":
        return _risk(operation) <= want
    if key == "mode":
        listed = _expand_modes(want, ctx.get("modes"))
        if all(m in listed for m in permissions.MODES):
            return True
        mode = str(ctx.get("mode") or "").strip().lower()
        return None if mode not in permissions.MODES else mode in listed
    have = ctx.get(key)
    if have is None:
        return None
    return have in want if key == "via" else bool(have) is want


def _failed(st, ctx, operation, decision):
    """The conditions that stop the rule: a False one, or an unknown one when the rule is an allow."""
    out = []
    for k, v in (st.get("when") or {}).items():
        r = _condition(k, v, ctx, operation)
        if r is False or (r is None and decision == "allow"):
            out.append(k)
    return out


def _covers(st, operation, target):
    if not any(ip.action_matches(a, operation) for a in st["operations"]):
        return False
    return any(ip.target_matches(r, target) for r in st.get("targets", ("*",)))


def _rules(profiles, decision, base_only=False):
    for doc in profiles:
        if base_only and not access_base.is_base(doc):
            continue
        for st in doc["rules"]:
            if st["decision"] == decision:
                yield doc["name"], st


def _tag_rules(profiles, tags, decision, target, ctx, operation):
    """(profile, rule_id) of the first rule of `decision` that lists one of `tags` literally and whose target and conditions hold."""
    for name, st in _rules(profiles, decision):
        if any(t in st["operations"] for t in tags) and any(ip.target_matches(r, target) for r in st.get("targets", ("*",))):
            if not _failed(st, ctx, operation, decision):
                return name, st["id"]
    return None


def _tiers(operation, args):
    """The literal operations that lift an escalated call (empty when the arguments do not escalate it) and the role it needs."""
    if ":" in operation:
        return [], None
    need = permissions.needed_role(operation, {"args": args})
    if need == permissions.required_role(operation):
        return [], None
    tags = [ip.TIER_PREFIX + need]
    if operation in permissions.ESCALATE_IN:
        tags.append(ip.CAP_PREFIX + caps.HARDWARE_PARAMS)
    return tags, need


def _allowing(profiles, operation, target, ctx, tags, base_only=False):
    """(profile, rule_id, None) of the allow rule that grants, or (None, None, info) when nothing does: info = ("escalated", need) /
    ("close", failed conditions) / None."""
    close, found = [], None
    for name, st in _rules(profiles, "allow", base_only):
        if not _covers(st, operation, target):
            continue
        failed = _failed(st, ctx, operation, "allow")
        if failed:
            close.extend(k for k in failed if k not in close)
        elif found is None:
            found = (name, st["id"])
    if found is None:
        return None, None, ("close", close) if close else None
    if tags and not _tag_rules(profiles, tags, "allow", target, ctx, operation):
        return None, None, ("escalated", None)
    return found[0], found[1], None


def evaluate(operation, profiles, ctx=None, target=None, ceiling=None):
    """The decision for `operation` (an operation name or "<ns>:<name>") of a person who holds `profiles` (a list of validated documents:
    the base ones of access_base and the custom ones of the store), see the module doc. `ceiling` is a document or a list of them."""
    operation = str(operation)
    ctx = ctx or {}
    if operation in permissions.STOP_OPS:
        return _decision(True, "stop")
    if target is None:
        target = ip.default_target(operation)
    elif not ip.concrete_target(target):
        return _decision(False, "bad_request", detail="target")
    args = ctx.get("args") if isinstance(ctx.get("args"), dict) else {}
    tags, need = _tiers(operation, args)
    ceiling = [ceiling] if isinstance(ceiling, dict) else list(ceiling or [])
    for name, st in _rules(list(profiles) + ceiling, "deny"):
        lifts = any(t in st["operations"] for t in tags)
        if (_covers(st, operation, target) or lifts) and any(ip.target_matches(r, target) for r in st.get("targets", ("*",))) \
                and not _failed(st, ctx, operation, "deny"):
            return _decision(False, "explicit_deny", name, st["id"])
    delegable = ":" in operation or caps.delegable(operation)
    if ceiling:
        bp, _, _ = _allowing(ceiling, operation, target, ctx, tags)
        if bp is None:
            return _decision(False, "ceiling")
    profile, rule_id, info = _allowing(list(profiles), operation, target, ctx, tags, base_only=not delegable)
    if profile is not None:
        return _decision(True, "allow", profile, rule_id)
    if info and info[0] == "escalated":
        return _decision(False, "escalated", needed_tier=need)
    if not delegable:
        return _decision(False, "not_delegable")
    extra = {"failed_conditions": info[1]} if info else {}
    return _decision(False, "implicit_deny", **extra)


def allowed(operation, profiles, ctx=None, target=None, ceiling=None):
    return evaluate(operation, profiles, ctx, target, ceiling).allowed


def rule_report(st, operation, target, ctx=None):
    """(matched, why) for one rule and one request, for the checker: why is [] when it matched, else "operation", "target" or
    "condition:<key>" (one per condition that failed). `target` is the concrete one (ip.default_target when the call names none)."""
    ctx = ctx or {}
    if not any(ip.action_matches(a, operation) for a in st["operations"]):
        return False, ["operation"]
    if not any(ip.target_matches(r, target) for r in st.get("targets", ("*",))):
        return False, ["target"]
    failed = _failed(st, ctx, operation, st["decision"])
    if failed:
        return False, ["condition:" + k for k in failed]
    return True, []
