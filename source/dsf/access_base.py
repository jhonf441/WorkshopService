"""
access_base -- the base (read-only) profiles of the four base roles, GENERATED from permissions.OP_ROLES and its context rules (phase 1 of
informes/control-acceso/PLAN-ACCESO.md, section 3.2). They are never stored and nobody edits them: this module builds them when it is imported.

  base.viewer         the operations of the table whose lowest role is viewer
  base.operator       + the operator's; the operations of MODE_GATED carry the condition mode = ${person.modes} (the modes of the person)
  base.technician     + the technician's, no mode condition; the `tier:technician` operation lifts the escalation of a call whose arguments
                       change settings (permissions.ESCALATE)
  base.administrator  "*" and both tiers (`tier:admin` lifts the hardware-risk escalation of permissions.ESCALATE_IN)
  base.viewer_camera   the camera operations (permissions.CAMERA_OPS) for a viewer that has `camera_for_viewer`: attached IN ADDITION to the
                       role by whoever builds the profile list of that person (base_profiles_for)

Every role may open every plugin page ("ui:*:open", rule OpenPages: today nobody is stopped from seeing a plugin); a deny of a profile silences one.

The PLUGIN profiles (phase 5, access_plugin_manifest) are not base profiles: they come from the permissions.json of the installed plugins, are
registered here with set_plugin_profiles (access_plugin_files), are read-only like the base ones and can be attached by name (`plugin.<id>.<level>`),
but is_base() is false for them, so they never concede an operation that cannot be delegated. They cannot be a ceiling (a plugin that goes away
would take the ceiling with it) and a custom profile cannot take their prefix.

An operation is listed by name (generated, so a new classified operation is in the profile of its role without touching this file).
The escalation tiers are literal operations: no wildcard and no custom profile can match them (access_eval), which is how "a grant never lifts what
an argument escalated" of permissions._decide_custom is kept.
"""
import access_profile
import permissions

ROLE_PROFILE = {permissions.VIEWER: "base.viewer", permissions.OPERATOR: "base.operator", permissions.TECHNICIAN: "base.technician",
               permissions.ADMIN: "base.administrator"}
CAMERA_PROFILE = "base.viewer_camera"
ADMIN_PROFILE = ROLE_PROFILE[permissions.ADMIN]


def _ops_up_to(role):
    """Operations of the table whose lowest role is `role` or lower, sorted."""
    table = dict(permissions.OP_ROLES)
    table.update(permissions.PLANNED_OP_ROLES)
    return sorted(op for op, r in table.items() if permissions.RANK[r] <= permissions.RANK[role])


def _doc(name, rules):
    return access_profile.validate({"version": access_profile.SCHEMA_VERSION, "name": name, "rules": rules}, base=True)


OPEN_PAGES = {"id": "OpenPages", "decision": "allow", "operations": ["ui:*:open"]}


def _viewer():
    return _doc(ROLE_PROFILE[permissions.VIEWER], [
        {"id": "ReadAndStop", "decision": "allow", "operations": _ops_up_to(permissions.VIEWER)}, dict(OPEN_PAGES)])


def _operator():
    ops = _ops_up_to(permissions.OPERATOR)
    gated = [o for o in ops if o in permissions.MODE_GATED]
    return _doc(ROLE_PROFILE[permissions.OPERATOR], [
        {"id": "OperatorOperations", "decision": "allow", "operations": [o for o in ops if o not in permissions.MODE_GATED]},
        {"id": "OperatorMotionInYourModes", "decision": "allow", "operations": gated, "when": {"mode": [access_profile.MODE_VARIABLE]}},
        dict(OPEN_PAGES)])


def _technician():
    return _doc(ROLE_PROFILE[permissions.TECHNICIAN], [
        {"id": "TechnicianOperations", "decision": "allow", "operations": _ops_up_to(permissions.TECHNICIAN)},
        {"id": "TechnicianTier", "decision": "allow", "operations": [access_profile.TIER_PREFIX + permissions.TECHNICIAN]}, dict(OPEN_PAGES)])


def _admin():
    return _doc(ROLE_PROFILE[permissions.ADMIN], [
        {"id": "FullAccess", "decision": "allow", "operations": ["*"]},
        {"id": "AdministratorTiers", "decision": "allow",
         "operations": [access_profile.TIER_PREFIX + permissions.TECHNICIAN, access_profile.TIER_PREFIX + permissions.ADMIN]}])


def _camera():
    return _doc(CAMERA_PROFILE, [{"id": "ViewCamera", "decision": "allow", "operations": sorted(permissions.CAMERA_OPS)}])


def build_base_profiles():
    """{name: document} of the base profiles, built from the tables as they are now."""
    docs = [_viewer(), _operator(), _technician(), _admin(), _camera()]
    return {d["name"]: d for d in docs}


BASE_PROFILES = build_base_profiles()
RESERVED_PREFIX = "base."  # no custom profile may start with it, whatever it is
PLUGIN_PREFIX = "plugin."  # nor with this one: the profiles of the plugins (see the module doc)
RESERVED_NAMES = frozenset(n.casefold() for n in BASE_PROFILES)
_plugin_profiles = {}  # casefolded id -> document; replaced as a whole (never changed in place), so a reader never sees half of a refresh


def is_reserved_name(name):
    """True when a custom profile may not be called `name`: a base profile, or anything that starts with a reserved prefix."""
    k = str(name or "").strip().casefold()
    return k in RESERVED_NAMES or k.startswith(RESERVED_PREFIX) or k.startswith(PLUGIN_PREFIX)


def is_plugin_name(name):
    return str(name or "").strip().casefold().startswith(PLUGIN_PREFIX)


def set_plugin_profiles(docs):
    """Replaces the registered plugin profiles by `docs` ({id: validated document}); every id starts with `plugin.`."""
    global _plugin_profiles
    _plugin_profiles = {str(n).casefold(): d for n, d in docs.items() if is_plugin_name(n) and d.get("name") == n}


def plugin_profiles():
    """{id: document} of the registered plugin profiles, sorted by id."""
    return {d["name"]: d for _, d in sorted(_plugin_profiles.items())}


def plugin_profile(name):
    """(canonical id, document) of a registered plugin profile (not case sensitive), or None."""
    d = _plugin_profiles.get(str(name or "").strip().casefold())
    return (d["name"], d) if d else None


def is_base(doc):
    """True when `doc` is exactly one of the base profiles (a stored document can never be: its name is reserved)."""
    return isinstance(doc, dict) and BASE_PROFILES.get(doc.get("name")) == doc


def base_profiles_for(role, camera=False):
    """The base documents of a person with a base role (and `camera_for_viewer`): what the evaluator gets for them. [] for an unknown role."""
    name = ROLE_PROFILE.get(role)
    if name is None:
        return []
    out = [BASE_PROFILES[name]]
    if camera:
        out.append(BASE_PROFILES[CAMERA_PROFILE])
    return out
