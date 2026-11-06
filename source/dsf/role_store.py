"""
role_store -- the custom roles of the workshop: a base role plus grants and denials (phase 1-2 of informes/permisos-por-rol/DISENO.md).

The four base roles (viewer, operator, technician, admin) are in code and cannot be changed. A custom role is saved here:

    {"version": 1, "roles": [{"name", "base", "description", "grant": [...], "deny": [...], "created", "updated", "updated_by"}]}

  base         viewer, operator or technician (NEVER admin: nobody gets the administrator's key by a custom role)
  grant/deny   entries: a capability id (permission_caps.CAPABILITIES), an operation name or an fnmatch pattern ("lights.*"), like the
               patterns of the API keys. The decision rules are in permissions.decide(); the validation is here.

Where it lives: next to the users file (paths.CONF/workshop-roles.json, outside the plugin folder so a reinstall does not erase it;
override: env WORKSHOP_ROLES), written atomically (fs_atomic). There is no migration and no copy to fall back to: a file that exists
but is not exactly what this module writes is `damaged` and FAILS CLOSED: no custom role is known, so the people who have one can do
nothing until the file is repaired or deleted by hand (a stale copy could give more than the owner decided). The base roles keep working.
Pure Python, no DSF import: tested on a PC (test_roles.py).
"""
import copy
import json
import os
import re
import threading
import time

import fs_atomic
import paths
import permission_caps as caps
import permissions

ROLES_FILE = os.environ.get("WORKSHOP_ROLES") or paths.CONF + "/workshop-roles.json"
SCHEMA = 1
MAX_ROLES = 30
MAX_ENTRIES = 100
MAX_DESCRIPTION = 200
NONE_ROLE = "none"  # the "role" of a person whose custom role cannot be resolved: it is in no table, so it can do nothing
_NAME = re.compile(r"^[\w .\-]{1,32}$", re.UNICODE)
_ENTRY = re.compile(r"^[a-z0-9_.*?\-]{1,64}$")
_FIELDS = {"name", "base", "description", "grant", "deny", "created", "updated", "updated_by"}
_REQUIRED = {"name", "base", "grant", "deny"}


class RoleError(Exception):
    """A request about roles that cannot be done. code: invalid_name, reserved_name, invalid_base, admin_base, invalid_entry, unknown_entry,
    not_delegable, stop_deny, conflict_entries, too_many, unknown_role, in_use, damaged, save_failed, invalid_args."""

    def __init__(self, code, message="", **extra):
        super().__init__(message or code)
        self.code = code
        self.extra = extra


def _key(name):
    return str(name or "").strip().casefold()


def clean_name(name):
    n = " ".join(str(name or "").split())
    if not _NAME.match(n):
        raise RoleError("invalid_name", "the name must have 1 to 32 letters, digits, spaces, dots or hyphens")
    if _key(n) in permissions.ROLES or _key(n) == NONE_ROLE:
        raise RoleError("reserved_name", "'%s' is the name of a base role" % n)
    return n


def clean_base(base):
    b = str(base or "").strip().lower()
    if b == permissions.ADMIN:
        raise RoleError("admin_base", "a custom role cannot be based on admin")
    if b not in permissions.CUSTOM_BASES:
        raise RoleError("invalid_base", "the base must be one of: " + ", ".join(permissions.CUSTOM_BASES))
    return b


def _clean_list(entries, field):
    if entries is None:
        entries = []
    if isinstance(entries, str):
        entries = [x for x in entries.replace(";", ",").split(",")]
    if not isinstance(entries, (list, tuple)):
        raise RoleError("invalid_args", "%s must be a list" % field, field=field)
    out = []
    for e in entries:
        if not isinstance(e, str):
            raise RoleError("invalid_entry", "an entry of %s is not text" % field, field=field)
        e = e.strip().lower()
        if not e:
            continue
        if not _ENTRY.match(e):
            raise RoleError("invalid_entry", "'%s' is not a capability, an operation or a pattern" % e, field=field, entry=e)
        if e not in out:
            out.append(e)
    if len(out) > MAX_ENTRIES:
        raise RoleError("too_many", "at most %d entries in %s" % (MAX_ENTRIES, field), field=field)
    return out


def _known_ops():
    return sorted(set(permissions.OP_ROLES) | set(permissions.PLANNED_OP_ROLES))


def _check_grant(entry):
    """A grant must exist and must be able to give something: a capability that can be delegated, or a pattern with at least one
    operation that can be delegated."""
    if entry in caps.CAPABILITIES:
        if not (entry == caps.HARDWARE_PARAMS or any(caps.delegable(p) for p in caps.CAPABILITIES[entry]["ops"])):
            raise RoleError("not_delegable", "'%s' cannot be granted to a role that is not an administrator" % entry, field="grant", entry=entry)
        return
    hit = [o for o in _known_ops() if permissions.entry_hits(entry, o)]
    if not hit:
        raise RoleError("unknown_entry", "'%s' matches no operation" % entry, field="grant", entry=entry)
    if not any(caps.delegable(o) for o in hit):
        raise RoleError("not_delegable", "'%s' cannot be granted to a role that is not an administrator" % entry, field="grant", entry=entry)


def _check_deny(entry):
    """A denial must exist, and must leave stopping alone: stopping is never blocked."""
    if entry in caps.CAPABILITIES:
        if caps.has_stop(entry, permissions.STOP_OPS):
            raise RoleError("stop_deny", "'%s' includes stopping, which is never blocked" % entry, field="deny", entry=entry)
        return
    hit = [o for o in _known_ops() if permissions.entry_hits(entry, o)]
    if not hit:
        raise RoleError("unknown_entry", "'%s' matches no operation" % entry, field="deny", entry=entry)
    if all(o in permissions.STOP_OPS for o in hit):
        raise RoleError("stop_deny", "'%s' only matches stopping, which is never blocked" % entry, field="deny", entry=entry)


def build(name, base, grant=None, deny=None, description="", now=None, actor="", created=None):
    """The validated record of a role, ready to save. Raises RoleError."""
    name = clean_name(name)
    base = clean_base(base)
    grant = _clean_list(grant, "grant")
    deny = _clean_list(deny, "deny")
    for e in grant:
        _check_grant(e)
    for e in deny:
        _check_deny(e)
    both = [e for e in grant if e in deny]
    if both:
        raise RoleError("conflict_entries", "'%s' is both granted and denied" % both[0], entry=both[0])
    desc = " ".join(str(description or "").split())
    if len(desc) > MAX_DESCRIPTION:
        raise RoleError("invalid_args", "the description is too long (at most %d characters)" % MAX_DESCRIPTION, field="description")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now if now is not None else time.time()))
    return {"name": name, "base": base, "description": desc, "grant": grant, "deny": deny, "created": created or stamp, "updated": stamp,
            "updated_by": str(actor or "")[:40]}


def _read_record(rec):
    """Structural check of a record read from the file (the shape this module writes, nothing else). The entries are checked for their
    spelling only: one that matches no operation today (an operation was renamed) is harmless, and must not lock everybody out."""
    if not isinstance(rec, dict) or not _REQUIRED <= set(rec) or not set(rec) <= _FIELDS:
        raise RoleError("damaged", "bad record")
    if not isinstance(rec["name"], str) or " ".join(rec["name"].split()) != rec["name"]:
        raise RoleError("damaged", "bad name")
    clean_name(rec["name"])
    clean_base(rec["base"])
    for f in ("grant", "deny"):
        if not isinstance(rec[f], list) or len(rec[f]) > MAX_ENTRIES or any(not isinstance(e, str) or not _ENTRY.match(e) for e in rec[f]):
            raise RoleError("damaged", "bad " + f)
    if set(rec["grant"]) & set(rec["deny"]):
        raise RoleError("damaged", "an entry is granted and denied")
    for f in ("description", "created", "updated", "updated_by"):
        if f in rec and not isinstance(rec[f], str):
            raise RoleError("damaged", "bad " + f)
    return {"name": rec["name"], "base": rec["base"].strip().lower(), "description": rec.get("description", ""), "grant": list(rec["grant"]),
            "deny": list(rec["deny"]), "created": rec.get("created", ""), "updated": rec.get("updated", ""), "updated_by": rec.get("updated_by", "")}


def custom_identity(ident, source):
    """Identity of a person whose role is a custom one: `role` becomes the BASE role (what the pages and the programs that only know the
    four roles understand), `role_name` the name of the custom role, `role_def` its record (what permissions.decide() needs). When the
    role cannot be found (deleted by hand, damaged file) `role` is NONE_ROLE and there is no definition: nothing is allowed."""
    rd = source.get(ident["role"]) if source is not None else None
    if rd is None:
        return dict(ident, role=NONE_ROLE, role_name=ident["role"], role_def=None)
    return dict(ident, role=rd["base"], role_name=rd["name"], role_def=rd)


class RoleStore:
    def __init__(self, path=None, log=print, now=time.time):
        self.path = path or ROLES_FILE
        self.log = log
        self.now = now
        self.lock = threading.RLock()
        self.roles = {}      # casefolded name -> record
        self.damaged = False
        self.load()

    # ---- file ----
    def load(self):
        with self.lock:
            self.roles, self.damaged = {}, False
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict) or set(data) != {"version", "roles"} or data["version"] != SCHEMA or not isinstance(data["roles"], list):
                    raise RoleError("damaged", "bad file")
                if len(data["roles"]) > MAX_ROLES:
                    raise RoleError("damaged", "too many roles")
                roles = {}
                for rec in data["roles"]:
                    rec = _read_record(rec)
                    if _key(rec["name"]) in roles:
                        raise RoleError("damaged", "a name twice")
                    roles[_key(rec["name"])] = rec
                self.roles = roles
            except (OSError, ValueError, RoleError) as e:
                self.roles, self.damaged = {}, True
                self.log("roles: the roles file exists but cannot be read (%s): custom roles fail closed" % e)

    def _save(self):
        data = {"version": SCHEMA, "roles": sorted(self.roles.values(), key=lambda r: r["name"].casefold())}
        fs_atomic.write_json(self.path, data, indent=1, ensure_ascii=False)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ---- reading ----
    def exists(self, name):
        with self.lock:
            return not self.damaged and _key(name) in self.roles

    def canonical(self, name):
        """The saved spelling of a role name, or None."""
        with self.lock:
            rec = None if self.damaged else self.roles.get(_key(name))
            return rec["name"] if rec else None

    def get(self, name):
        """A copy of the record, or None (unknown, or the file is damaged)."""
        with self.lock:
            rec = None if self.damaged else self.roles.get(_key(name))
            return copy.deepcopy(rec) if rec else None

    def list(self):
        with self.lock:
            return [copy.deepcopy(r) for r in sorted(self.roles.values(), key=lambda r: r["name"].casefold())]

    # ---- changing ----
    def _writable(self):
        if self.damaged:
            raise RoleError("damaged", "the roles file is damaged")

    def set(self, name, base, grant=None, deny=None, description="", actor=""):
        """Creates or replaces a custom role. Returns (before or None, after)."""
        with self.lock:
            self._writable()
            old = self.roles.get(_key(name))
            if old is None and len(self.roles) >= MAX_ROLES:
                raise RoleError("too_many", "at most %d custom roles" % MAX_ROLES)
            if old is not None:
                name = old["name"]  # the spelling of the first time: the people who have it point to that
            rec = build(name, base, grant, deny, description, self.now(), actor, created=(old or {}).get("created"))
            before = copy.deepcopy(old) if old else None
            self.roles[_key(rec["name"])] = rec
            try:
                self._save()
            except OSError as e:
                self._restore(rec["name"], old)
                raise RoleError("save_failed", "the roles file could not be saved: %s" % e)
            return before, copy.deepcopy(rec)

    def remove(self, name, users_with_role=()):
        """Deletes a custom role that nobody has (`users_with_role`: the names of the people who have it, checked by the caller)."""
        with self.lock:
            self._writable()
            old = self.roles.get(_key(name))
            if old is None:
                raise RoleError("unknown_role", "there is no role '%s'" % name)
            if users_with_role:
                raise RoleError("in_use", "the role is in use", users=list(users_with_role))
            del self.roles[_key(name)]
            try:
                self._save()
            except OSError as e:
                self._restore(old["name"], old)
                raise RoleError("save_failed", "the roles file could not be saved: %s" % e)
            return copy.deepcopy(old)

    def _restore(self, name, old):
        if old is None:
            self.roles.pop(_key(name), None)
        else:
            self.roles[_key(name)] = old
