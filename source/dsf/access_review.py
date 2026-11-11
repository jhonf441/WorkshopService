"""
access_review -- the REVIEW OF ACCESSES (phase 6 of informes/control-acceso/PLAN-ACCESO.md, section 4.5): a pure function that reads a snapshot of
the access model and returns findings. No I/O, no clock of its own (`now` is an argument), nothing is changed. The snapshot is built by
access_report.snapshot; the operation is access.review (access_ops).

    review(data, now) -> [finding, ...]       sorted by severity (high first), then code, then subject

`data` (every key optional, a missing one is empty):
    profiles  [{"name", "doc": <validated document>, "holders": {"users": [...], "groups": [...]}}]   the CUSTOM profiles
    people    [{"name", "role", "groups": [...], "profiles": [...], "last_seen": epoch | None, "created": "YYYY-MM-DDTHH:MM:SS" | None}]
    damaged   True when the access file cannot be read (no profile and no attachment is known: those findings are left out)
    keys      [{"id", "name", "enabled", "created": epoch | None, "last_used": epoch | None, "expires": epoch | None, "ops": [...], "kinds": [...]}]

A finding: {"code", "severity", "subject", "params", "message"}; severity is high / medium / low / info, `message` is a translated text
(key access_review_<code>). The findings, ONE function and ONE test each:

  profile_grants_risk4   high    an allow rule of a custom profile names `cap:machine.hardware_params` (or another risk 4 capability with a delegable
                                 operation), or matches an operation of risk 4 that a profile can concede (delegable, inside the risk_max
                                 of the rule). Today no operation of risk 4 is delegable: the hardware key is the one real case
  deny_never_matches     medium  a deny rule that cannot hold: no operation of the table matches any entry, risk_max is below the risk of
                                 everything it names, or `via` leaves out session (the only way the evaluator decides today)
  profile_unattached     low     a custom profile that nobody and no group has
  person_without_access  info    a person with no group and no profile: the base role alone decides for them
  key_wide_unused        high    an enabled key that reaches many things (WIDE_KEY_BREADTH entries) and was not used for UNUSED_KEY_DAYS
  admin_no_recent_login  medium  an administrator who did not sign in for ADMIN_LOGIN_DAYS (never, counted from when they were created)
"""
import time

import access_profile as ip
import permission_caps as caps
import permissions
from messages import M

UNUSED_KEY_DAYS = 30
ADMIN_LOGIN_DAYS = 30
WIDE_KEY_BREADTH = 5
DAY_S = 86400
SEVERITIES = ("high", "medium", "low", "info")
SAMPLE = 5  # operations or entries named in the detail of a finding

CODES = ("profile_grants_risk4", "deny_never_matches", "profile_unattached", "person_without_access", "key_wide_unused", "admin_no_recent_login")


def _finding(code, severity, subject, **params):
    text = dict(params)
    if "why" in params:
        text["why"] = M("access_review_why_" + params["why"])
    if "never" in params:
        text["since"] = M("access_review_%s_%s" % (code, "never" if params["never"] else "days"), days=params["days"])
    return {"code": code, "severity": severity, "subject": subject, "params": params, "message": M("access_review_" + code, subject=subject, **text)}


def known_operations():
    return sorted(set(permissions.OP_ROLES) | set(permissions.PLANNED_OP_ROLES))


def op_risk(operation):
    cid = caps.capability_of(operation)
    return caps.CAPABILITIES[cid]["risk"] if cid else 4  # the evaluator's rule: not in a capability = the highest


def _hits(rule, ops):
    return [o for o in ops if any(ip.action_matches(e, o) for e in rule["operations"])]


def _risk4_caps(rule):
    """The capabilities of risk 4 that an allow rule names with `cap:<id>` and that a profile can really concede: one with an operation that is
    delegable, or the hardware key, which lifts the escalation of the hardware-risk writes."""
    out = []
    for e in rule["operations"]:
        cid = e[len(ip.CAP_PREFIX):] if e.startswith(ip.CAP_PREFIX) else None
        cap = caps.CAPABILITIES.get(cid) if cid else None
        if cap and cap["risk"] == 4 and (cid == caps.HARDWARE_PARAMS or any(caps.delegable(o) for o in cap["ops"])):
            out.append(e)
    return out


def profile_grants_risk4(profiles):
    out = []
    ops = [o for o in known_operations() if o not in permissions.STOP_OPS and caps.delegable(o)]
    for p in profiles or ():
        found = []
        for rule in p["doc"]["rules"]:
            if rule["decision"] != "allow":
                continue
            limit = (rule.get("when") or {}).get("risk_max", 4)
            found.extend(e for e in _risk4_caps(rule) if e not in found)
            found.extend(o for o in _hits(rule, ops) if op_risk(o) == 4 and op_risk(o) <= limit and o not in found)
        if found:
            out.append(_finding("profile_grants_risk4", "high", p["name"], count=len(found), operations=", ".join(sorted(found)[:SAMPLE])))
    return out


def _never_why(rule, ops):
    """Why the deny rule can never hold (a short code), or None."""
    when = rule.get("when") or {}
    if "via" in when and "session" not in when["via"]:
        return "via"
    if all(e.startswith(ip.CAP_PREFIX) or ":" not in e for e in rule["operations"]):  # a <ns>:<name> entry may be a plugin operation we do not know
        hit = _hits(rule, ops)
        if not hit:
            return "operation"
        if "risk_max" in when and all(op_risk(o) > when["risk_max"] for o in hit):
            return "risk_max"
    return None


def deny_never_matches(profiles):
    out = []
    ops = known_operations()
    for p in profiles or ():
        for rule in p["doc"]["rules"]:
            if rule["decision"] != "deny":
                continue
            why = _never_why(rule, ops)
            if why:
                out.append(_finding("deny_never_matches", "medium", p["name"], rule=rule["id"], why=why))
    return out


def profile_unattached(profiles):
    return [_finding("profile_unattached", "low", p["name"]) for p in profiles or ()
            if not (p.get("holders") or {}).get("users") and not (p.get("holders") or {}).get("groups")]


def person_without_access(people):
    return [_finding("person_without_access", "info", p["name"], role=p.get("role", "")) for p in people or ()
            if not p.get("groups") and not p.get("profiles")]


def iso_epoch(text):
    try:
        return int(time.mktime(time.strptime(str(text), "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, OverflowError):
        return None


def admin_no_recent_login(people, now, days=ADMIN_LOGIN_DAYS):
    out = []
    for p in people or ():
        if p.get("role") != permissions.ADMIN:
            continue
        seen = p.get("last_seen")
        since = seen if seen else iso_epoch(p.get("created"))
        if since is None:
            continue  # nothing says since when: no finding is made up
        if now - since > days * DAY_S:
            out.append(_finding("admin_no_recent_login", "medium", p["name"], days=int((now - since) // DAY_S), never=not seen))
    return out


def key_breadth(rec):
    """How much a key reaches: its capability entries, its other operation patterns and its classes."""
    return len(rec.get("ops") or ()) + len(rec.get("kinds") or ())


def key_wide_unused(keys, now, days=UNUSED_KEY_DAYS):
    out = []
    for k in keys or ():
        if not k.get("enabled", True) or key_breadth(k) < WIDE_KEY_BREADTH:
            continue
        if k.get("expires") and now > k["expires"]:
            continue
        since = k.get("last_used") or k.get("created")
        if since is None or now - since <= days * DAY_S:
            continue
        out.append(_finding("key_wide_unused", "high", k.get("name") or k.get("id", "?"), id=k.get("id", ""), days=int((now - since) // DAY_S),
                            breadth=key_breadth(k), never=not k.get("last_used")))
    return out


def review(data, now=None):
    data = data or {}
    now = int(time.time() if now is None else now)
    # a damaged access file knows no profile and no attachment: what it cannot know is not reported as missing
    profiles, attached = ([], False) if data.get("damaged") else (data.get("profiles"), True)
    found = (profile_grants_risk4(profiles) + deny_never_matches(profiles) + profile_unattached(profiles)
             + (person_without_access(data.get("people")) if attached else []) + key_wide_unused(data.get("keys"), now)
             + admin_no_recent_login(data.get("people"), now))
    return sorted(found, key=lambda f: (SEVERITIES.index(f["severity"]), CODES.index(f["code"]), f["subject"].casefold()))
