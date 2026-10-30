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
  ops    extra operation patterns allowed (fnmatch: "light.*")
  deny   patterns refused even if their class is allowed
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


class KeyError_(Exception):
    """A request about a key that cannot be done (bad name, unknown id...)."""


def _hash(plain):
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _clean_name(name):
    n = " ".join(str(name or "").split())
    if not 1 <= len(n) <= 40 or any(ord(c) < 32 for c in n):
        raise KeyError_("the name must have 1 to 40 characters")
    return n


def _clean_patterns(v, what):
    if v is None:
        return []
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, (list, tuple)) or len(v) > MAX_PATTERNS:
        raise KeyError_(f"{what}: a list of at most {MAX_PATTERNS} patterns")
    out = []
    for p in v:
        p = str(p).strip().lower()
        if not _PATTERN.match(p):
            raise KeyError_(f"{what}: '{p}' is not a valid operation pattern (letters, digits, . _ - * ?)")
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
                "ops": list(r.get("ops") or []), "deny": list(r.get("deny") or [])}

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
                   "kinds": kinds, "ops": ops, "deny": deny}
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
            r["kinds"], r["ops"] = new_kinds, new_ops
            if deny is not None:
                r["deny"] = _clean_patterns(deny, "deny")
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
                    "ops": list(hit.get("ops") or []), "deny": list(hit.get("deny") or [])}


def allows(rec, op_name, op_kind):
    """The same rule as Registry._key_allows, for the page (preview of what a key can call)."""
    if op_kind == "admin":
        return False
    if any(fnmatch.fnmatchcase(op_name, p) for p in rec.get("deny") or ()):
        return False
    return op_kind in (rec.get("kinds") or ()) or any(fnmatch.fnmatchcase(op_name, p) for p in rec.get("ops") or ())
