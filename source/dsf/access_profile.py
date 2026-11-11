"""
access_profile -- the profile document of the access model (phase 1 of informes/control-acceso/PLAN-ACCESO.md, section 3.2). Pure: no I/O, no service
import; it only reads the tables of permissions.py and permission_caps.py. NOTHING calls it yet: the engine runs in the shadow of the real
decision (permissions.decide) until a later phase connects it.

A document:

    {"version": 1, "name": "LightsOperator", "rules": [
        {"id": "UseLights", "decision": "allow", "operations": ["cap:lights.use", "lights.config"], "targets": ["workshop:lights:scene/*"]},
        {"id": "NoM950", "decision": "deny", "operations": ["lights.apply_m950"]},
        {"id": "OnlyCam2", "decision": "allow", "operations": ["cap:camera.capture"], "targets": ["workshop:camera:camera/cam2"],
         "when": {"mode": ["fff"], "job_running": false}}]}

Operations (an entry of `operations`):
  an operation name ("lights.config"), an fnmatch pattern ("lights.*", "*"), "cap:<id>" (every operation of a capability, the same syntax the API
  keys use) or "<ns>:*" (a whole namespace: the namespace of an API operation is the part before its first dot, see namespace_of; the namespace of
  a plugin is the one its permissions.json declares, see access_plugin_manifest). "ui:<plugin>:open" (or the pattern "ui:*:open") is the interface
  operation of a plugin: showing it in the side bar and opening its pages; "<plugin>:*" covers it too, so one deny silences a whole plugin.
  "cap:machine.hardware_params" is the explicit key that lifts the hardware-risk escalation.
Targets: "workshop:<plugin>:<type>/<id>", "*" and prefixes ("workshop:camera:camera/cam*"). Omitted = every target. A call without a target is
  evaluated against "workshop:<plugin>:*" (default_target), so a rule restricted to one target does not cover it.
Conditions (a CLOSED list, each one has a test): mode (list of laser / cnc / fff, or the variable "${person.modes}": the modes of the person),
  job_running (bool), machine_on (bool), via (list of session / key / macro / local), risk_max (1 to 4: the risk of the capability of the operation).
  There is no time, date or IP condition and none can be added through a document: they are refused by name.
Rules checked when a document is saved: a deny can never cover a STOP operation (stopping is never blocked); no unknown field anywhere; the
reserved namespaces `cap` and `tier` are not an operation namespace. Base documents (access_base) may also carry the literal `tier:<role>` operations:
the escalation tiers that a wildcard or a custom profile can never match.
"""
import copy
import fnmatch
import re

import permission_caps as caps
import permissions

SCHEMA_VERSION = 1
DECISIONS = ("allow", "deny")
CONDITION_KEYS = ("mode", "job_running", "machine_on", "via", "risk_max")
VIAS = ("session", "key", "macro", "local")
MODE_VARIABLE = "${person.modes}"
CAP_PREFIX = "cap:"
TIER_PREFIX = "tier:"
RESERVED_NAMESPACES = ("cap", "tier")
MAX_RULES = 50
MAX_ENTRIES = 100
MAX_BASE_ENTRIES = 600  # the generated base profiles list every operation by name
_TIME_WORDS = ("time", "date", "hour", "day", "week", "month", "year", "expir", "ip", "addr", "cidr", "schedule", "until", "before", "after", "mfa")

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")
_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")
_OP = re.compile(r"^[a-z0-9_.*?\-]{1,64}$")
_NS_ACTION = re.compile(r"^([a-z][a-z0-9_]{0,31}):([a-z0-9_.*?\-]{1,64})$")
_UI_ACTION = re.compile(r"^ui:([a-z][a-z0-9_]{0,31}|\*):open$")
UI_PREFIX = "ui:"
_TARGET = re.compile(r"^workshop:([a-z0-9_]{1,32}|\*):([A-Za-z0-9_.\-/*%]{1,100})$")
_CONCRETE = re.compile(r"^workshop:[a-z0-9_]{1,32}:[A-Za-z0-9_.\-/%]{1,100}$")
_DOC_FIELDS = {"version", "name", "rules"}
_STMT_FIELDS = {"id", "decision", "operations", "targets", "when"}


class ProfileError(ValueError):
    """A document that cannot be accepted. code: invalid_document, unknown_field, invalid_version, invalid_name, invalid_rule, invalid_id,
    duplicate_id, invalid_decision, invalid_operation, unknown_capability, reserved_namespace, invalid_target, invalid_condition,
    forbidden_condition, stop_deny, too_many."""

    def __init__(self, code, message="", where=""):
        super().__init__(("%s: %s" % (where, message or code)) if where else (message or code))
        self.code = code
        self.where = where


def ui_operation(plugin):
    """The interface operation of a plugin: "ui:<plugin>:open"."""
    return "ui:%s:open" % plugin


def namespace_of(operation):
    """The namespace (plugin) of an operation: the plugin of "ui:<plugin>:open", the part before ':' of "<ns>:<name>", else the part of an
    operation name before its first dot."""
    a = str(operation)
    m = _UI_ACTION.match(a)
    if m:
        return m.group(1)
    if ":" in a:
        return a.split(":", 1)[0]
    return a.split(".", 1)[0]


def default_target(operation):
    """The target a call without one is evaluated against."""
    return "workshop:%s:*" % namespace_of(operation)


def concrete_target(target):
    """True when `target` is a target of a request (no wildcard)."""
    return isinstance(target, str) and bool(_CONCRETE.match(target))


def _glob(pattern, text):
    """Matching where only `*` is special (a target id may hold any other character)."""
    if "*" not in pattern:
        return pattern == text
    return re.fullmatch(".*".join(re.escape(p) for p in pattern.split("*")), text, re.DOTALL) is not None


def target_matches(pattern, target):
    """True when a rule's target pattern covers the target of a request."""
    return pattern == "*" or _glob(pattern, target)


def action_matches(entry, operation):
    """True when an `operations` entry covers `operation` (an operation name, or "<ns>:<name>" of a plugin operation)."""
    operation = str(operation)
    if entry.startswith(CAP_PREFIX):
        return ":" not in operation and caps.capability_of(operation) == entry[len(CAP_PREFIX):]
    if entry.startswith(TIER_PREFIX):
        return False  # tiers are matched literally by the evaluator, never by a request
    if ":" in operation:
        m = _NS_ACTION.match(entry)
        if m and m.group(2) == "*" and operation.startswith(UI_PREFIX) and namespace_of(operation) == m.group(1):
            return True  # "<plugin>:*" covers the interface operation of the plugin
        return fnmatch.fnmatchcase(operation, entry)
    if ":" in entry:
        m = _NS_ACTION.match(entry)
        return bool(m) and m.group(2) == "*" and namespace_of(operation) == m.group(1)
    if "*" not in entry and "?" not in entry:
        return entry == operation
    return fnmatch.fnmatchcase(operation, entry)


def _known_ops():
    return sorted(set(permissions.OP_ROLES) | set(permissions.PLANNED_OP_ROLES))


def _check_action(entry, where, base):
    if not isinstance(entry, str):
        raise ProfileError("invalid_operation", "an operation is not text", where)
    if entry.startswith(CAP_PREFIX):
        if entry[len(CAP_PREFIX):] not in caps.CAPABILITIES:
            raise ProfileError("unknown_capability", "'%s' is not a capability" % entry, where)
        return
    if entry.startswith(TIER_PREFIX):
        if base and entry[len(TIER_PREFIX):] in permissions.ROLES:
            return
        raise ProfileError("reserved_namespace", "'%s' is reserved" % entry, where)
    if _OP.match(entry) or _UI_ACTION.match(entry):
        return
    m = _NS_ACTION.match(entry)
    if not m:
        raise ProfileError("invalid_operation", "'%s' is not an operation, a pattern, cap:<id> or <ns>:<name>" % entry, where)
    if m.group(1) in RESERVED_NAMESPACES:
        raise ProfileError("reserved_namespace", "'%s' is reserved" % m.group(1), where)


def _check_target(entry, where):
    if not isinstance(entry, str) or not (entry == "*" or _TARGET.match(entry)):
        raise ProfileError("invalid_target", "'%s' is not workshop:<plugin>:<type>/<id>" % (entry,), where)


def _check_conditions(cond, where):
    if not isinstance(cond, dict):
        raise ProfileError("invalid_condition", "conditions must be an object", where)
    for k, v in cond.items():
        low = str(k).lower()
        if k not in CONDITION_KEYS:
            if any(w in low for w in _TIME_WORDS):
                raise ProfileError("forbidden_condition", "'%s': no condition of time, date or address exists in this model" % k, where)
            raise ProfileError("invalid_condition", "'%s' is not a condition (%s)" % (k, ", ".join(CONDITION_KEYS)), where)
        w = "%s.%s" % (where, k)
        if k in ("job_running", "machine_on"):
            if not isinstance(v, bool):
                raise ProfileError("invalid_condition", "must be true or false", w)
        elif k == "risk_max":
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 4:
                raise ProfileError("invalid_condition", "must be a whole number from 1 to 4", w)
        else:
            allowed = permissions.MODES if k == "mode" else VIAS
            if not isinstance(v, list) or not v or len(v) > 8 or any(not isinstance(x, str) for x in v):
                raise ProfileError("invalid_condition", "must be a non-empty list of text", w)
            if any(x not in allowed and not (k == "mode" and x == MODE_VARIABLE) for x in v):
                raise ProfileError("invalid_condition", "values must be among: %s" % ", ".join(allowed), w)


def _stop_only(entry):
    """True when a deny entry would deny a STOP operation (it only covers stopping, or is a capability that holds a stop)."""
    if entry.startswith(CAP_PREFIX):
        return caps.has_stop(entry[len(CAP_PREFIX):], permissions.STOP_OPS)
    hit = [o for o in _known_ops() if action_matches(entry, o)]
    return bool(hit) and all(o in permissions.STOP_OPS for o in hit)


def _check_rule(st, where, base):
    if not isinstance(st, dict):
        raise ProfileError("invalid_rule", "a rule must be an object", where)
    extra = set(st) - _STMT_FIELDS
    if extra:
        raise ProfileError("unknown_field", "unknown field '%s'" % sorted(extra)[0], where)
    if not {"id", "decision", "operations"} <= set(st):
        raise ProfileError("invalid_rule", "id, decision and operations are required", where)
    if not isinstance(st["id"], str) or not _ID.match(st["id"]):
        raise ProfileError("invalid_id", "the id must have 1 to 64 letters or digits", where)
    if st["decision"] not in DECISIONS:
        raise ProfileError("invalid_decision", "the decision must be allow or deny", where)
    limit = MAX_BASE_ENTRIES if base else MAX_ENTRIES
    for f in ("operations", "targets"):
        if f in st and (not isinstance(st[f], list) or not st[f] or len(st[f]) > limit):
            raise ProfileError("invalid_rule", "%s must be a non-empty list of at most %d entries" % (f, limit), where)
    for e in st["operations"]:
        _check_action(e, where + ".operations", base)
    for e in st.get("targets", ()):
        _check_target(e, where + ".targets")
    if "when" in st:
        _check_conditions(st["when"], where + ".when")
    if st["decision"] == "deny":
        for e in st["operations"]:
            if _stop_only(e):
                raise ProfileError("stop_deny", "'%s' covers stopping, which is never blocked" % e, where)


def validate(doc, base=False):
    """A deep copy of the document when it is valid, else ProfileError. Strict: an unknown field anywhere is refused. `base` is for the
    documents of access_base (they may hold the `tier:<role>` operations); a stored document is always validated with base=False."""
    if not isinstance(doc, dict):
        raise ProfileError("invalid_document", "a profile must be an object")
    extra = set(doc) - _DOC_FIELDS
    if extra:
        raise ProfileError("unknown_field", "unknown field '%s'" % sorted(extra)[0])
    if not _DOC_FIELDS <= set(doc):
        raise ProfileError("invalid_document", "version, name and rules are required")
    if isinstance(doc["version"], bool) or doc["version"] != SCHEMA_VERSION:
        raise ProfileError("invalid_version", "version must be %d" % SCHEMA_VERSION)
    if not isinstance(doc["name"], str) or not _NAME.match(doc["name"]):
        raise ProfileError("invalid_name", "the name must start with a letter and have at most 64 letters, digits, dots, underscores or hyphens")
    sts = doc["rules"]
    if not isinstance(sts, list) or not sts:
        raise ProfileError("invalid_document", "rules must be a non-empty list")
    if len(sts) > MAX_RULES:
        raise ProfileError("too_many", "at most %d rules" % MAX_RULES)
    seen = set()
    for i, st in enumerate(sts):
        _check_rule(st, "rules[%d]" % i, base)
        if st["id"] in seen:
            raise ProfileError("duplicate_id", "the id '%s' is used twice" % st["id"], "rules[%d]" % i)
        seen.add(st["id"])
    return copy.deepcopy(doc)
