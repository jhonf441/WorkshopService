"""
api_keys -- keys of external services for the API of the service (2026-10-13).

Why: until now an external program had two ways in: the DWC password (full power, and the password
has to be shared) or the local key (only for programs of this machine). A key per service lets the
owner say what it may do and revoke it alone.

A key looks like "wk_<48 hex>" and is shown ONCE, when it is created. Only its SHA-256 is stored
(0:/sys/workshop/data/api-keys.json, mode 640), so the file does not give anybody a key.
It is sent in the header X-Workshop-Key. What a key may call:
  kinds  operation classes (read, write, motion, stop, power); never "admin": keys, passwords and
         the restore of configurations need a DWC session
  ops    extra operation patterns allowed (fnmatch: "light.*") and capabilities ("cap:camera.capture", permission_caps)
  deny   patterns and capabilities refused even if their class is allowed (deny always wins)
Capabilities are the same groups of operations the custom roles use (permission_caps.py). In a key an entry of ops / deny is either
  - a pattern or an operation name, exactly as before ("camera.capture" is the OPERATION, even though four names are also capability ids), or
  - "cap:<id>": every operation of that capability. The prefix keeps the two meanings apart, so no key saved before capabilities existed
    can change what it does. When a bare name is a capability id and not an operation, keys.create / keys.update save it as "cap:<id>".
A key never gets an operation that cannot be delegated (permission_caps.NOT_DELEGABLE) through a capability, and never an administration
operation (kind admin) by any road. A key saved before capabilities has no "strict" mark and keeps its exact decisions (test_key_golden.py,
fixtures/key_decisions_golden.json), including classes and patterns that reach some non-delegable operations of kind write; a key created
or whose permissions are saved again carries strict = true: its classes and patterns never reach a non-delegable operation either.
Also: optional expiry, enabled flag, last use. Managing keys (list / create / update / revoke) are
administration operations: only a DWC session can call them (api_ops.py).

Pure Python, no DSF import: it is tested on a PC (test_api.py).
"""
import paths
import fnmatch
import hashlib
import json
import os
import re
import secrets
import threading
import time

import permission_caps as caps
import permissions

KEYS_FILE = paths.DATA_DIR + "/api-keys.json"
MAX_KEYS = 30
MAX_PATTERNS = 100
KINDS = ("read", "write", "motion", "stop", "power")  # "admin" can never be given to a key
SAVE_USE_EVERY_S = 60  # last_used is written to disk at most this often

# What the page offers as starting points (the owner can edit the lists afterwards)
PRESETS = {
    "read": {"kinds": ["read"], "ops": []},
    "lights_air": {"kinds": [], "ops": ["api.*", "state.get", "light.*", "air.*", "statuslight.set", "lights.get", "lights.scene", "sound.beep"]},
    "notify": {"kinds": [], "ops": ["api.*", "state.get", "job.get", "notifications.send"]},
    "control": {"kinds": ["read", "write", "stop"], "ops": []},
    "full": {"kinds": ["read", "write", "motion", "stop", "power"], "ops": []},
}

_PATTERN = re.compile(r"^[a-z0-9_.*?\-]{1,60}$")
CAP_PREFIX = "cap:"


class KeyError_(Exception):
    """A request about a key that cannot be done (bad name, unknown id...)."""


def _hash(plain):
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _clean_name(name):
    n = " ".join(str(name or "").split())
    if not 1 <= len(n) <= 40 or any(ord(c) < 32 for c in n):
        raise KeyError_("the name must have 1 to 40 characters")
    return n


def _check_capability(cid, what):
    """An entry "cap:<id>" must name a capability; in `ops` it must also be one a key may receive."""
    c = caps.CAPABILITIES.get(cid)
    if c is None:
        raise KeyError_(f"{what}: '{cid}' is not a capability (the ids are in roles.list)")
    if what == "ops" and (c["class"] == "admin" or not any(caps.delegable(p) for p in c["ops"])):
        raise KeyError_(f"ops: the capability '{cid}' cannot be given to a key (administration and non-delegable operations)")


def _clean_patterns(v, what):
    """The entries of ops / deny: operation names, fnmatch patterns and "cap:<id>" capabilities, lower case, without repeats."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, (list, tuple)) or len(v) > MAX_PATTERNS:
        raise KeyError_(f"{what}: a list of at most {MAX_PATTERNS} entries")
    out = []
    for p in v:
        p = str(p).strip().lower()
        if p.startswith(CAP_PREFIX):
            _check_capability(p[len(CAP_PREFIX):], what)
        elif not _PATTERN.match(p):
            raise KeyError_(f"{what}: '{p}' is not a valid operation pattern or capability (letters, digits, . _ - * ?, or cap:<id>)")
        elif p in caps.CAPABILITIES and not permissions.classified(p):
            p = CAP_PREFIX + p  # a bare capability id that is not an operation name
            _check_capability(p[len(CAP_PREFIX):], what)
        if p not in out:
            out.append(p)
    return out


def _clean_kinds(v):
    if v is None:
        return []
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    out = []
    for k in v or []:
        k = str(k).strip().lower()
        if k == "admin":
            raise KeyError_("a key can never have administration operations")
        if k not in KINDS:
            raise KeyError_(f"unknown operation class '{k}' (one of: {', '.join(KINDS)})")
        if k not in out:
            out.append(k)
    return out


class KeyStore:
    def __init__(self, path=KEYS_FILE, clock=time.time, log=print):
        self.path = path
        self.clock = clock
        self.log = log
        self.lock = threading.Lock()
        self._keys = None  # list of dicts, loaded on first use
        self._saved_use = 0.0

    # -- storage --
    def _load(self):
        if self._keys is not None:
            return
        self._keys = []
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            for r in d.get("keys") or []:
                if isinstance(r, dict) and r.get("id") and r.get("hash"):
                    self._keys.append(r)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            self.log(f"api keys: the file could not be read ({e}); no key is valid until it is fixed")

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "keys": self._keys}, f, ensure_ascii=False, indent=1)
        try:
            os.chmod(tmp, 0o640)
        except OSError:
            pass
        os.replace(tmp, self.path)

    @staticmethod
    def _public(r):
        return {"id": r["id"], "name": r["name"], "prefix": r.get("prefix", ""), "created": r.get("created"),
                "last_used": r.get("last_used"), "uses": r.get("uses", 0), "expires": r.get("expires"),
                "enabled": bool(r.get("enabled", True)), "kinds": list(r.get("kinds") or []),
                "ops": list(r.get("ops") or []), "deny": list(r.get("deny") or []), "strict": bool(r.get("strict"))}

    # -- the operations of the page --
    def list(self):
        with self.lock:
            self._load()
            return [self._public(r) for r in self._keys]

    def create(self, name, kinds=None, ops=None, deny=None, days=None, preset=None):
        """Returns (plain key, public record). The plain key is not kept anywhere."""
        name = _clean_name(name)
        if preset:
            p = PRESETS.get(preset)
            if p is None:
                raise KeyError_(f"unknown preset '{preset}'")
            kinds = p["kinds"] if kinds is None else kinds
            ops = p["ops"] if ops is None else ops
        kinds, ops, deny = _clean_kinds(kinds), _clean_patterns(ops, "ops"), _clean_patterns(deny, "deny")
        if not kinds and not ops:
            raise KeyError_("the key must allow something: an operation class or an operation pattern")
        exp = None
        if days not in (None, "", 0):
            try:
                d = float(days)
            except (TypeError, ValueError):
                raise KeyError_("days must be a number")
            if not 0 < d <= 3650:
                raise KeyError_("days must be between 0 and 3650")
            exp = int(self.clock() + d * 86400)
        with self.lock:
            self._load()
            if len(self._keys) >= MAX_KEYS:
                raise KeyError_(f"at most {MAX_KEYS} keys")
            if any(r["name"].lower() == name.lower() for r in self._keys):
                raise KeyError_(f"there is already a key called '{name}'")
            plain = "wk_" + secrets.token_hex(24)
            rec = {"id": secrets.token_hex(4), "name": name, "hash": _hash(plain), "prefix": plain[:9],
                   "created": int(self.clock()), "last_used": None, "uses": 0, "expires": exp, "enabled": True,
                   "kinds": kinds, "ops": ops, "deny": deny, "strict": True}
            self._keys.append(rec)
            self._save()
            return plain, self._public(rec)

    def update(self, kid, name=None, kinds=None, ops=None, deny=None, enabled=None, days=None):
        with self.lock:
            self._load()
            r = next((x for x in self._keys if x["id"] == kid), None)
            if r is None:
                raise KeyError_("no key with that id")
            if name is not None:
                n = _clean_name(name)
                if any(x is not r and x["name"].lower() == n.lower() for x in self._keys):
                    raise KeyError_(f"there is already a key called '{n}'")
                r["name"] = n
            new_kinds = r["kinds"] if kinds is None else _clean_kinds(kinds)
            new_ops = r["ops"] if ops is None else _clean_patterns(ops, "ops")
            if not new_kinds and not new_ops:
                raise KeyError_("the key must allow something: an operation class or an operation pattern")
            new_deny = r.get("deny") or [] if deny is None else _clean_patterns(deny, "deny")
            r["kinds"], r["ops"], r["deny"] = new_kinds, new_ops, new_deny
            if kinds is not None or ops is not None or deny is not None:
                r["strict"] = True  # saving the permissions again applies the current rule (no non-delegable operation by a class or a pattern)
            if enabled is not None:
                r["enabled"] = bool(enabled)
            if days is not None:
                if days in ("", 0):
                    r["expires"] = None
                else:
                    try:
                        d = float(days)
                    except (TypeError, ValueError):
                        raise KeyError_("days must be a number")
                    if not 0 < d <= 3650:
                        raise KeyError_("days must be between 0 and 3650")
                    r["expires"] = int(self.clock() + d * 86400)
            self._save()
            return self._public(r)

    def revoke(self, kid):
        with self.lock:
            self._load()
            r = next((x for x in self._keys if x["id"] == kid), None)
            if r is None:
                raise KeyError_("no key with that id")
            self._keys.remove(r)
            self._save()
            return self._public(r)

    # -- the check of every request --
    def lookup(self, plain):
        """The record of a valid key, or None (unknown, disabled, expired)."""
        if not plain or not plain.startswith("wk_") or len(plain) > 80:
            return None
        h = _hash(plain)
        with self.lock:
            self._load()
            hit = None
            for r in self._keys:  # compare all: the time does not tell which one matched
                if secrets.compare_digest(r["hash"], h):
                    hit = r
            if hit is None or not hit.get("enabled", True):
                return None
            now = self.clock()
            if hit.get("expires") and now > hit["expires"]:
                return None
            hit["last_used"] = int(now)
            hit["uses"] = hit.get("uses", 0) + 1
            if now - self._saved_use >= SAVE_USE_EVERY_S:
                self._saved_use = now
                try:
                    self._save()
                except OSError as e:
                    self.log(f"api keys: last use not saved ({e})")
            return {"id": hit["id"], "name": hit["name"], "kinds": list(hit.get("kinds") or []),
                    "ops": list(hit.get("ops") or []), "deny": list(hit.get("deny") or []), "strict": bool(hit.get("strict"))}


def _hits(entries, op_name):
    """True when an entry of ops / deny covers the operation: a "cap:<id>" entry by the capability of the operation, any other by fnmatch."""
    for p in entries or ():
        if p.startswith(CAP_PREFIX):
            if caps.capability_of(op_name) == p[len(CAP_PREFIX):]:
                return True
        elif fnmatch.fnmatchcase(op_name, p):
            return True
    return False


def _cap_grants(entries, op_name):
    """True when a "cap:<id>" entry gives the operation to a key: the capability of the operation, delegable, not of the admin class."""
    cid = caps.capability_of(op_name)
    return (cid is not None and caps.delegable(op_name) and caps.CAPABILITIES[cid]["class"] != "admin"
            and (CAP_PREFIX + cid) in (entries or ()))


def why_not(rec, op_name, op_kind):
    """None when the key may call the operation, else why not: "admin", "denied", "not_delegable" or "not_granted". THE rule of the keys:
    Registry._key_allows (identity.AuthRegistry) and the page (keys.list -> allowed_ops) both come here."""
    if op_kind == "admin":
        return "admin"
    if _hits(rec.get("deny"), op_name):
        return "denied"
    strict = bool(rec.get("strict"))
    if strict and not caps.delegable(op_name):
        return "not_delegable"
    ops = rec.get("ops") or ()
    if op_kind in (rec.get("kinds") or ()) or _cap_grants(ops, op_name):
        return None
    if any(fnmatch.fnmatchcase(op_name, p) for p in ops if not p.startswith(CAP_PREFIX)):
        return None
    return "not_granted"


def allows(rec, op_name, op_kind):
    """True when the key may call the operation (see why_not)."""
    return why_not(rec, op_name, op_kind) is None


def draft(kinds=None, ops=None, deny=None):
    """The record a key would have with these permissions (validated like create(), nothing saved): for the preview of the page."""
    return {"kinds": _clean_kinds(kinds), "ops": _clean_patterns(ops, "ops"), "deny": _clean_patterns(deny, "deny"), "strict": True}


def allowed_ops(rec, ops):
    """The names of the operations of `ops` (an iterable of (name, kind)) that the key may call, in the order given."""
    return [n for n, k in ops if allows(rec, n, k)]
