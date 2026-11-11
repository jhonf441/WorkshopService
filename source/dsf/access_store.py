"""
access_store -- the file of the access model, `workshop-access.json` (phases 1 and 2 of informes/control-acceso/PLAN-ACCESO.md, sections 3.1 and 3.5):

    {"version": 1,
     "profiles": [<profile document of access_profile: the ACTIVE version of each custom profile>, ...],
     "versions": {"<profile>": {"active": 3, "items": [{"n": 2, "doc": {...}, "at": "...", "by": "..."}, ...]}},   (up to 5 per profile)
     "groups":   [{"name", "description", "profiles": [...], "ceiling": null | "<profile>", "updated", "updated_by"}],
     "users":    [{"name", "profiles": [...], "groups": [...], "ceiling": null | "<profile>"}]}

`versions`, `groups` and `users` are optional (a file of phase 1 is valid); everything else is refused. A person is in 0..N groups, has 0..N
profiles attached and at most one permissions ceiling; a group has profiles and a ceiling too. Who is who comes from workshop-users.json
(the name of the person); the roles of role_store are NOT stored here (access_admin shows each as a group with one profile).

Where it lives: next to the users file (paths.CONF/workshop-access.json, outside the plugin folder; override: env WORKSHOP_ACCESS), written with
fs_atomic.write_with_backup (a damaged file never replaces a healthy .bak), mode 600 where the system has modes. The read is STRICT and FAILS
CLOSED, like role_store: a file that exists but is not exactly what this module writes (unknown field, a name twice, a reference to
something that does not exist, a limit passed) is `damaged`: no custom profile, group or attachment is known (so nobody has anything but
stopping and what the base roles give: identity then decides with permissions.decide for everybody) and nothing can be saved until it is
repaired or deleted by hand. The .bak is NEVER read by itself (a stale copy could give more than the owner decided). No migration.

The base profiles of access_base are never stored and their names are reserved; they can be attached (and used as a ceiling) by name, except
`base.administrator`: administrators are made by the role, never by an attachment. Every change goes through `transact`: the new state is
built on a copy, checked (integrity here, the rules of the administrator in `check`) and only then saved and published, so a refused
change leaves memory and file as they were. A published state is never changed in place, so a reader can keep it. Pure Python, no DSF
import (tested on a PC).
"""
import copy
import json
import os
import re
import threading
import time

import fs_atomic
import access_base
import access_profile
import paths

ACCESS_FILE = os.environ.get("WORKSHOP_ACCESS") or paths.CONF + "/workshop-access.json"
SCHEMA = 1
MAX_PROFILES = 50
MAX_VERSIONS = 5
MAX_GROUPS = 30
MAX_ATTACHED = 20      # profiles attached to one person or group
MAX_MEMBERSHIPS = 10   # groups of one person
MAX_PEOPLE = 100   # people with something attached
MAX_DESCRIPTION = 200
FORBIDDEN_ATTACH = access_base.ADMIN_PROFILE
_GROUP_NAME = re.compile(r"^[\w .\-]{1,32}$", re.UNICODE)
_TOP = {"version", "profiles"}
_TOP_OPTIONAL = {"versions", "groups", "users"}
_GROUP_FIELDS = {"name", "description", "profiles", "ceiling", "updated", "updated_by"}
_USER_FIELDS = {"name", "profiles", "groups", "ceiling"}
_ITEM_FIELDS = {"n", "doc", "at", "by"}


class AccessError(Exception):
    """A request about the access model that cannot be done. code: damaged, reserved_name, invalid_name, too_many, unknown_profile,
    unknown_group, unknown_user, unknown_version, in_use, admin_profile, already, not_attached, no_allow, save_failed, invalid_args,
    invalid_profile (`detail` is the ProfileError code). `extra` carries what the text of the answer needs (users, groups, profile...)."""

    def __init__(self, code, message="", **extra):
        super().__init__(message or code)
        self.code = code
        self.extra = extra


def _key(name):
    return str(name or "").strip().casefold()


def empty_state():
    return {"profiles": {}, "versions": {}, "groups": {}, "users": {}}


def _clean(doc):
    """The validated copy of a custom document; its name must not be a base one."""
    try:
        out = access_profile.validate(doc, base=False)
    except access_profile.ProfileError as e:
        raise AccessError("invalid_profile", str(e), detail=e.code)
    if access_base.is_reserved_name(out["name"]):
        raise AccessError("reserved_name", "'%s' is the name of a base or plugin profile (the prefixes `base.` and `plugin.` are reserved)" % out["name"])
    return out


def clean_group_name(name):
    n = " ".join(str(name or "").split())
    if not _GROUP_NAME.match(n):
        raise AccessError("invalid_name", "the name must have 1 to 32 letters, digits, spaces, dots or hyphens")
    return n


def _cut(items, limit, what):
    if len(items) > limit:
        raise AccessError("too_many", "at most %d %s" % (limit, what))


# ---- reading a state ----

class AccessView:
    """The read side of a state: the same questions for the real store and for the state a change would produce."""

    def __init__(self, state):
        self.state = state

    def resolve(self, name):
        """(canonical name, document, base) of a profile that exists (custom or base), or None. Names are not case sensitive."""
        k = _key(name)
        doc = self.state["profiles"].get(k)
        if doc is not None:
            return doc["name"], doc, False
        for n, d in access_base.BASE_PROFILES.items():
            if _key(n) == k:
                return n, d, True
        hit = access_base.plugin_profile(name)
        return (hit[0], hit[1], True) if hit else None

    def person(self, user):
        """What a person has: {"groups": [...], "profiles": [direct], "ceiling": name|None, "via_groups": {group: [profiles]},
        "all_profiles": [names, direct first, no repeats], "ceilings": [names of the person's and of the groups' ceilings]}."""
        rec = self.state["users"].get(_key(user)) or {"profiles": [], "groups": [], "ceiling": None}
        via, allp = {}, list(rec["profiles"])
        bounds = [rec["ceiling"]] if rec["ceiling"] else []
        for g in rec["groups"]:
            grec = self.state["groups"].get(_key(g))
            if grec is None:
                continue
            via[grec["name"]] = list(grec["profiles"])
            allp.extend(p for p in grec["profiles"] if p not in allp)
            if grec["ceiling"] and grec["ceiling"] not in bounds:
                bounds.append(grec["ceiling"])
        return {"groups": list(rec["groups"]), "profiles": list(rec["profiles"]), "ceiling": rec["ceiling"], "via_groups": via,
                "all_profiles": list(dict.fromkeys(allp)), "ceilings": bounds}

    def documents(self, names):
        return [r[1] for r in (self.resolve(n) for n in names) if r]

    def has_attachments(self, user):
        """True when the person has a profile or a ceiling of their own or through a group: only then the evaluator governs them."""
        p = self.person(user)
        return bool(p["all_profiles"] or p["ceilings"])

    def members(self, group):
        k = _key(group)
        return sorted((r["name"] for r in self.state["users"].values() if any(_key(g) == k for g in r["groups"])), key=str.casefold)

    def holders(self, profile):
        """{"users": [...], "groups": [...]}: who has the profile attached or as a ceiling."""
        p = _key(profile)
        us = sorted((r["name"] for r in self.state["users"].values()
                     if any(_key(x) == p for x in r["profiles"]) or (r["ceiling"] and _key(r["ceiling"]) == p)), key=str.casefold)
        gs = sorted((g["name"] for g in self.state["groups"].values()
                     if any(_key(x) == p for x in g["profiles"]) or (g["ceiling"] and _key(g["ceiling"]) == p)), key=str.casefold)
        return {"users": us, "groups": gs}


# ---- integrity of a state (reading the file and before every save) ----

def check_integrity(st):
    """Raises AccessError when `st` would not read back: a reference to something that does not exist, a repeat, a limit passed."""
    v = AccessView(st)
    _cut(st["profiles"], MAX_PROFILES, "custom profiles")
    _cut(st["groups"], MAX_GROUPS, "groups")
    _cut(st["users"], MAX_PEOPLE, "people with attachments")
    for k, entry in st["versions"].items():
        if k not in st["profiles"]:
            raise AccessError("damaged", "versions of an unknown profile")
        _cut(entry["items"], MAX_VERSIONS, "versions of a profile")
    for k in st["profiles"]:
        if k not in st["versions"]:
            raise AccessError("damaged", "a profile without versions")

    def refs(lst, what):
        if len(set(map(_key, lst))) != len(lst):
            raise AccessError("damaged", "%s lists a name twice" % what)
        _cut(lst, MAX_ATTACHED, "profiles attached to one name")
        for n in lst:
            if access_base.is_plugin_name(n):
                continue  # a plugin profile may be missing for a while (its plugin is being updated): the person keeps nothing from it, the file stays valid
            r = v.resolve(n)
            if r is None or r[0] != n:
                raise AccessError("unknown_profile", "there is no profile '%s'" % n, profile=n)
            if r[0] == FORBIDDEN_ATTACH:
                raise AccessError("admin_profile", "%s cannot be attached: administrators are made by the role" % n)

    def bound(n, what):
        if n is None:
            return
        if access_base.is_plugin_name(n):
            raise AccessError("plugin_ceiling", "a plugin profile cannot be a ceiling", profile=n)
        r = v.resolve(n)
        if r is None or r[0] != n:
            raise AccessError("unknown_profile", "there is no profile '%s'" % n, profile=n)
        if not any(s["decision"] == "allow" for s in r[1]["rules"]):
            raise AccessError("no_allow", "a ceiling without an allow rule would block everything", profile=n)

    for g in st["groups"].values():
        refs(g["profiles"], "group " + g["name"])
        bound(g["ceiling"], "group " + g["name"])
    for u in st["users"].values():
        refs(u["profiles"], u["name"])
        bound(u["ceiling"], u["name"])
        if len(set(map(_key, u["groups"]))) != len(u["groups"]):
            raise AccessError("damaged", "a group twice")
        _cut(u["groups"], MAX_MEMBERSHIPS, "groups of one person")
        for g in u["groups"]:
            gr = st["groups"].get(_key(g))
            if gr is None or gr["name"] != g:
                raise AccessError("unknown_group", "there is no group '%s'" % g, group=g)
        if not (u["profiles"] or u["groups"] or u["ceiling"]):
            raise AccessError("damaged", "an empty person record")


# ---- the file ----

def _text(rec, field, limit=200):
    v = rec.get(field, "")
    if not isinstance(v, str) or len(v) > limit:
        raise AccessError("damaged", "bad " + field)
    return v


def _names(rec, field):
    v = rec.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise AccessError("damaged", "bad " + field)
    return list(v)


def _read_versions(data, st):
    raw = data.get("versions")
    if raw is None:  # a file of phase 1: every profile is its own version 1
        for k, doc in st["profiles"].items():
            st["versions"][k] = {"active": 1, "items": [{"n": 1, "doc": copy.deepcopy(doc), "at": "", "by": ""}]}
        return
    if not isinstance(raw, dict):
        raise AccessError("damaged", "bad versions")
    for name, entry in raw.items():
        k = _key(name)
        if k not in st["profiles"] or st["profiles"][k]["name"] != name:
            raise AccessError("damaged", "versions of an unknown profile")
        if not isinstance(entry, dict) or set(entry) != {"active", "items"} or not isinstance(entry["items"], list) \
                or not 1 <= len(entry["items"]) <= MAX_VERSIONS or isinstance(entry["active"], bool) or not isinstance(entry["active"], int):
            raise AccessError("damaged", "bad versions entry")
        items, seen = [], set()
        for it in entry["items"]:
            if not isinstance(it, dict) or set(it) != _ITEM_FIELDS or isinstance(it["n"], bool) or not isinstance(it["n"], int) or it["n"] < 1 \
                    or it["n"] in seen:
                raise AccessError("damaged", "bad version")
            seen.add(it["n"])
            try:
                doc = _clean(it["doc"])
            except AccessError as e:
                raise AccessError("damaged", "bad version: %s" % e)
            if _key(doc["name"]) != k:
                raise AccessError("damaged", "a version of another profile")
            items.append({"n": it["n"], "doc": doc, "at": _text(it, "at"), "by": _text(it, "by")})
        if entry["active"] not in seen or next(i for i in items if i["n"] == entry["active"])["doc"] != st["profiles"][k]:
            raise AccessError("damaged", "the active version is not the profile")
        st["versions"][k] = {"active": entry["active"], "items": items}


def parse(raw):
    """The state of the bytes of a file, or AccessError('damaged')."""
    try:
        data = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except ValueError as e:
        raise AccessError("damaged", "not JSON: %s" % e)
    if not isinstance(data, dict) or not _TOP <= set(data) <= _TOP | _TOP_OPTIONAL or isinstance(data["version"], bool) \
            or data["version"] != SCHEMA or not isinstance(data["profiles"], list) or len(data["profiles"]) > MAX_PROFILES:
        raise AccessError("damaged", "bad file")
    st = empty_state()
    try:
        for doc in data["profiles"]:
            doc = _clean(doc)
            if _key(doc["name"]) in st["profiles"]:
                raise AccessError("damaged", "a name twice")
            st["profiles"][_key(doc["name"])] = doc
        _read_versions(data, st)
        groups, people = data.get("groups", []), data.get("users", [])
        if not isinstance(groups, list) or not isinstance(people, list):
            raise AccessError("damaged", "bad groups or users")
        for g in groups:
            if not isinstance(g, dict) or not {"name", "profiles"} <= set(g) <= _GROUP_FIELDS or not isinstance(g.get("name"), str) \
                    or clean_group_name(g["name"]) != g["name"] or _key(g["name"]) in st["groups"]:
                raise AccessError("damaged", "bad group")
            b = g.get("ceiling")
            if b is not None and not isinstance(b, str):
                raise AccessError("damaged", "bad ceiling")
            st["groups"][_key(g["name"])] = {"name": g["name"], "description": _text(g, "description", MAX_DESCRIPTION), "profiles": _names(g, "profiles"),
                                             "ceiling": b, "updated": _text(g, "updated"), "updated_by": _text(g, "updated_by")}
        for u in people:
            if not isinstance(u, dict) or set(u) != _USER_FIELDS or not isinstance(u.get("name"), str) or not u["name"] or _key(u["name"]) in st["users"]:
                raise AccessError("damaged", "bad person")
            b = u["ceiling"]
            if b is not None and not isinstance(b, str):
                raise AccessError("damaged", "bad ceiling")
            st["users"][_key(u["name"])] = {"name": u["name"], "profiles": _names(u, "profiles"), "groups": _names(u, "groups"), "ceiling": b}
        check_integrity(st)
    except AccessError as e:
        raise AccessError("damaged", "bad content: %s" % e)
    return st


def serialize(st):
    data = {"version": SCHEMA, "profiles": sorted(st["profiles"].values(), key=lambda d: d["name"].casefold())}
    if st["versions"]:
        data["versions"] = {st["profiles"][k]["name"]: {"active": e["active"], "items": sorted(e["items"], key=lambda i: i["n"])}
                            for k, e in sorted(st["versions"].items())}
    if st["groups"]:
        data["groups"] = sorted(st["groups"].values(), key=lambda g: g["name"].casefold())
    if st["users"]:
        data["users"] = sorted(st["users"].values(), key=lambda u: u["name"].casefold())
    return json.dumps(data, indent=1, ensure_ascii=False).encode("utf-8")


# ---- changes (each works on a copy of the state, see AccessStore.transact) ----

def _stamp(now):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now()))


def _profile_name(st, name):
    r = AccessView(st).resolve(name)
    if r is None:
        raise AccessError("unknown_profile", "there is no profile '%s'" % name, profile=str(name))
    return r


def _attachable(st, name):
    canonical = _profile_name(st, name)[0]
    if canonical == FORBIDDEN_ATTACH:
        raise AccessError("admin_profile", "%s cannot be attached: administrators are made by the role" % canonical)
    return canonical


def _rename_refs(st, old, new):
    for rec in list(st["groups"].values()) + list(st["users"].values()):
        rec["profiles"] = [new if x == old else x for x in rec["profiles"]]
        if rec["ceiling"] == old:
            rec["ceiling"] = new


def set_profile(st, doc, actor, now):
    """Creates a custom profile or saves a NEW version of it (it becomes the active one; the oldest one that is not active goes beyond 5).
    Returns {"before": doc|None, "after": doc, "version": n, "changed": bool}. Saving what is already active changes nothing."""
    new = _clean(doc)
    k = _key(new["name"])
    old = st["profiles"].get(k)
    if old is None and len(st["profiles"]) >= MAX_PROFILES:
        raise AccessError("too_many", "at most %d custom profiles" % MAX_PROFILES)
    entry = st["versions"].get(k) or {"active": 0, "items": []}
    if old == new:
        return {"before": copy.deepcopy(old), "after": copy.deepcopy(new), "version": entry["active"], "changed": False}
    n = max([i["n"] for i in entry["items"]] or [0]) + 1
    entry["items"].append({"n": n, "doc": copy.deepcopy(new), "at": _stamp(now), "by": str(actor or "")[:40]})
    entry["active"] = n
    while len(entry["items"]) > MAX_VERSIONS:
        gone = min((i for i in entry["items"] if i["n"] != n), key=lambda i: i["n"])
        entry["items"].remove(gone)
    st["versions"][k] = entry
    st["profiles"][k] = new
    if old is not None and old["name"] != new["name"]:
        _rename_refs(st, old["name"], new["name"])
    return {"before": copy.deepcopy(old), "after": copy.deepcopy(new), "version": n, "changed": True}


def rollback_profile(st, name, version):
    """Makes an older version the active one (the others stay). Returns {"before", "after", "version"}."""
    k = _key(name)
    old = st["profiles"].get(k)
    if old is None:
        raise AccessError("unknown_profile", "there is no profile '%s'" % name, profile=str(name))
    entry = st["versions"][k]
    item = next((i for i in entry["items"] if i["n"] == version), None)
    if item is None:
        raise AccessError("unknown_version", "the profile has no version %s" % version, profile=old["name"])
    if version == entry["active"]:
        raise AccessError("already", "version %s is already the active one" % version, profile=old["name"])
    entry["active"] = version
    st["profiles"][k] = copy.deepcopy(item["doc"])
    if old["name"] != item["doc"]["name"]:
        _rename_refs(st, old["name"], item["doc"]["name"])
    return {"before": copy.deepcopy(old), "after": copy.deepcopy(item["doc"]), "version": version}


def remove_profile(st, name):
    k = _key(name)
    old = st["profiles"].get(k)
    if old is None:
        raise AccessError("unknown_profile", "there is no profile '%s'" % name, profile=str(name))
    h = AccessView(st).holders(old["name"])
    if h["users"] or h["groups"]:
        raise AccessError("in_use", "the profile is attached", profile=old["name"], users=h["users"], groups=h["groups"])
    del st["profiles"][k]
    del st["versions"][k]
    return copy.deepcopy(old)


def _group(st, name):
    g = st["groups"].get(_key(name))
    if g is None:
        raise AccessError("unknown_group", "there is no group '%s'" % name, group=str(name))
    return g


def group_brief(st, name):
    g = st["groups"].get(_key(name))
    if g is None:
        return None
    return {"profiles": list(g["profiles"]), "ceiling": g["ceiling"], "members": AccessView(st).members(g["name"]), "description": g["description"]}


def set_group(st, name, description, profiles, members, users, reserved, actor, now):
    """Creates a group or replaces its description and profiles (its ceiling stays). `members`: None keeps the people, a list sets them
    exactly. `users(name)` gives the canonical name of a person or None; `reserved` are the casefolded names a group cannot take (the custom
    roles, which the pages show as groups). Returns {"before", "after"} (group_brief)."""
    name = clean_group_name(name)
    if _key(name) in reserved:
        raise AccessError("reserved_name", "'%s' is the name of a role" % name)
    old = st["groups"].get(_key(name))
    before = group_brief(st, name)
    if old is None and len(st["groups"]) >= MAX_GROUPS:
        raise AccessError("too_many", "at most %d groups" % MAX_GROUPS)
    desc = " ".join(str(description or "").split())
    if len(desc) > MAX_DESCRIPTION:
        raise AccessError("invalid_args", "the description is too long", field="description")
    if not isinstance(profiles, list):
        raise AccessError("invalid_args", "profiles must be a list", field="profiles")
    pols = []
    for p in profiles:
        c = _attachable(st, p)
        if c not in pols:
            pols.append(c)
    _cut(pols, MAX_ATTACHED, "profiles attached to one name")
    if old is not None and old["name"] != name:
        old["name"] = name  # only the case changed
    g = old or {"name": name, "description": "", "profiles": [], "ceiling": None, "updated": "", "updated_by": ""}
    g.update(description=desc, profiles=pols, updated=_stamp(now), updated_by=str(actor or "")[:40])
    st["groups"][_key(name)] = g
    if members is not None:
        if not isinstance(members, list):
            raise AccessError("invalid_args", "members must be a list", field="members")
        want = []
        for m in members:
            c = users(m)
            if c is None:
                raise AccessError("unknown_user", "there is no person '%s'" % m, user=str(m))
            if c not in want:
                want.append(c)
        for u in list(st["users"].values()):
            if _key(u["name"]) not in map(_key, want):
                u["groups"] = [x for x in u["groups"] if _key(x) != _key(name)]
        for c in want:
            join(st, c, g["name"], missing_ok=True)
        _drop_empty(st)
    return {"before": before, "after": group_brief(st, name)}


def remove_group(st, name):
    g = _group(st, name)
    members = AccessView(st).members(g["name"])
    if members:
        raise AccessError("in_use", "the group has people", group=g["name"], users=members)
    before = group_brief(st, g["name"])
    del st["groups"][_key(g["name"])]
    return {"before": before, "after": None}


def _person(st, user):
    k = _key(user)
    return st["users"].setdefault(k, {"name": str(user), "profiles": [], "groups": [], "ceiling": None})


def _drop_empty(st):
    for k in [k for k, u in st["users"].items() if not (u["profiles"] or u["groups"] or u["ceiling"])]:
        del st["users"][k]


def _target(st, kind, name, users):
    """The record a profile is attached to: ("group", record) or ("user", record), the person created when new."""
    if kind == "group":
        return _group(st, name)
    c = users(name)
    if c is None:
        raise AccessError("unknown_user", "there is no person '%s'" % name, user=str(name))
    return _person(st, c)


def brief_of(st, kind, name, users):
    if kind == "group":
        return group_brief(st, name)
    c = users(name)
    p = AccessView(st).person(c or name)
    return {"profiles": p["profiles"], "groups": p["groups"], "ceiling": p["ceiling"]}


def attach(st, kind, name, profile, users):
    rec = _target(st, kind, name, users)
    c = _attachable(st, profile)
    if any(_key(x) == _key(c) for x in rec["profiles"]):
        raise AccessError("already", "'%s' already has %s" % (rec["name"], c), profile=c)
    rec["profiles"].append(c)
    _cut(rec["profiles"], MAX_ATTACHED, "profiles attached to one name")
    if kind == "group":
        rec["updated"] = rec["updated"] or ""
    return rec["name"]


def detach(st, kind, name, profile, users):
    rec = _target(st, kind, name, users)
    c = _profile_name(st, profile)[0]
    if c not in rec["profiles"]:
        raise AccessError("not_attached", "'%s' does not have %s" % (rec["name"], c), profile=c)
    rec["profiles"].remove(c)
    _drop_empty(st)
    return rec["name"]


def join(st, user, group, missing_ok=False):
    g = _group(st, group)
    u = _person(st, user)
    if any(_key(x) == _key(g["name"]) for x in u["groups"]):
        if missing_ok:
            return u["name"]
        raise AccessError("already", "'%s' is already in %s" % (u["name"], g["name"]), group=g["name"])
    u["groups"].append(g["name"])
    _cut(u["groups"], MAX_MEMBERSHIPS, "groups of one person")
    return u["name"]


def leave(st, user, group):
    g = _group(st, group)
    u = st["users"].get(_key(user))
    if u is None or g["name"] not in u["groups"]:
        raise AccessError("not_attached", "'%s' is not in %s" % (user, g["name"]), group=g["name"])
    u["groups"].remove(g["name"])
    _drop_empty(st)
    return u["name"]


def set_ceiling(st, kind, name, profile, users):
    """Sets (or clears, profile None / "") the permissions ceiling of a person or a group."""
    rec = _target(st, kind, name, users)
    rec["ceiling"] = _profile_name(st, profile)[0] if profile else None
    _drop_empty(st)
    return rec["name"]


def forget_user(st, user):
    """Drops everything attached to a person (the person was removed: a new one with the same name must start with nothing)."""
    return st["users"].pop(_key(user), None) is not None


class AccessStore:
    def __init__(self, path=None, log=print, now=time.time):
        self.path = path or ACCESS_FILE
        self.log = log
        self.now = now
        self.lock = threading.RLock()
        self.state = empty_state()
        self.damaged = False
        self.load()

    @property
    def profiles(self):
        return self.state["profiles"]

    # ---- file ----
    def load(self):
        with self.lock:
            self.state, self.damaged = empty_state(), False
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, "rb") as fh:
                    self.state = parse(fh.read())
            except (OSError, AccessError) as e:
                self.state, self.damaged = empty_state(), True
                self.log("access: the access file exists but cannot be read (%s): custom profiles, groups and attachments fail closed" % e)

    def _save(self, st):
        fs_atomic.write_with_backup(self.path, serialize(st), validate=lambda raw: parse(raw) is not None, mode=0o600)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _writable(self):
        if self.damaged:
            raise AccessError("damaged", "the access file is damaged")

    def transact(self, change, check=None):
        """Builds the new state on a copy with `change(state)` (its result is returned), checks it (integrity, then `check(AccessView)` of the
        caller, which raises to refuse) and only then saves and publishes it. Anything raised leaves memory and file as they were."""
        with self.lock:
            self._writable()
            st = copy.deepcopy(self.state)
            out = change(st)
            check_integrity(st)
            if check is not None:
                check(AccessView(st))
            try:
                self._save(st)
            except OSError as e:
                raise AccessError("save_failed", "the access file could not be saved: %s" % e)
            self.state = st
            return out

    # ---- reading ----
    def view(self):
        """A read-only view of the state now (never changed in place: it can be kept while others save)."""
        with self.lock:
            return AccessView(self.state)

    def get(self, name):
        """A copy of the custom document (the active version), or None (unknown, or the file is damaged)."""
        with self.lock:
            doc = self.state["profiles"].get(_key(name))
            return copy.deepcopy(doc) if doc else None

    def list(self):
        with self.lock:
            return [copy.deepcopy(d) for d in sorted(self.state["profiles"].values(), key=lambda d: d["name"].casefold())]

    def documents(self, names):
        """The documents of the custom profiles called `names` (the ones that exist; none when the file is damaged)."""
        return [d for d in (self.get(n) for n in names) if d]

    def versions(self, name):
        """[{"n", "active", "at", "by", "doc"}] newest first, or None when there is no such profile."""
        with self.lock:
            k = _key(name)
            e = self.state["versions"].get(k)
            if e is None:
                return None
            return [{"n": i["n"], "active": i["n"] == e["active"], "at": i["at"], "by": i["by"], "doc": copy.deepcopy(i["doc"])}
                    for i in sorted(e["items"], key=lambda i: -i["n"])]

    def groups(self):
        with self.lock:
            v = AccessView(self.state)
            return [dict(copy.deepcopy(g), members=v.members(g["name"])) for g in sorted(self.state["groups"].values(), key=lambda g: g["name"].casefold())]

    # ---- changing (profiles, as in phase 1) ----
    def set(self, doc, actor=""):
        """Creates or replaces a custom profile (a new version). Returns (before or None, after)."""
        r = self.transact(lambda st: set_profile(st, doc, actor, self.now))
        return r["before"], r["after"]

    def remove(self, name):
        return self.transact(lambda st: remove_profile(st, name))

    def forget_user(self, user):
        """The person was removed: nothing stays attached to the name. False when nothing was (or the file is damaged)."""
        with self.lock:
            if self.damaged or _key(user) not in self.state["users"]:
                return False
            try:
                return self.transact(lambda st: forget_user(st, user))
            except AccessError as e:
                self.log("access: could not forget %s: %s" % (user, e))
                return False

    def reconcile(self, names):
        """Drops the attachments of people who are not in `names` (the people of the users file): they were removed while this store was not
        looking, and a new person with the same name must not inherit them."""
        with self.lock:
            keep = {_key(n) for n in names}
            stale = [u["name"] for k, u in self.state["users"].items() if k not in keep]
            for n in stale:
                self.forget_user(n)
            return stale
