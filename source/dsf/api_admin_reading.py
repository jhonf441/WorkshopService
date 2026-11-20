"""Which ADMIN operations only read (see api_ops.record and test_admin_reading.py)."""
# ADMIN is a permission class (session only, never a key), not a statement about writing. These ADMIN operations were reviewed one by one: they
# only read (the *.validate ones work on a copy that is thrown away), so the activity list shows them as reading. Everything else of class ADMIN
# is in ADMIN_CHANGING. test_admin_reading.py fails when an ADMIN operation is in neither list, or when one of this list is not read-only.
READ_ONLY_ADMIN = frozenset((
    "access.attach.validate", "access.ceiling.validate", "access.check", "access.detach.validate", "access.groups.get", "access.groups.list",
    "access.groups.validate", "access.person.get", "access.profile.versions", "access.profiles.get", "access.profiles.list",
    "access.profiles.validate", "access.report", "access.review", "audit.export", "audit.list", "keys.list", "keys.preview", "roles.effective",
    "roles.get", "roles.list", "users.list"))
# Changes something, or reads but leaves a trace of its own: access.plugins.validate registers the plugin profiles, audit.verify may raise an
# alarm, audit.settings reads or changes.
ADMIN_CHANGING = frozenset((
    "access.attach", "access.ceiling.set", "access.detach", "access.groups.remove", "access.groups.set", "access.plugins.validate",
    "access.profile.rollback", "access.profiles.remove", "access.profiles.set", "audit.settings", "audit.verify", "comms.set", "gcodelib.forget",
    "guard.set", "keys.create", "keys.revoke", "keys.update", "package.apply", "password.clear", "password.set", "profile.set", "roles.remove",
    "roles.set", "service.restart", "startup.apply", "startup.integrity.restore", "users.add", "users.close_sessions", "users.enable",
    "users.remove", "users.reset_pin", "users.set", "users.settings"))


def reads(op):
    """The ONE answer to "does this operation only read?": its class is read, or it is an ADMIN one reviewed as read-only. The activity list (api_ops.record) and api.describe (field `reads`) both use it."""
    return bool(op is not None and (op.kind == "read" or op.name in READ_ONLY_ADMIN))
