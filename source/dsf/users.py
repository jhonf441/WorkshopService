"""
users -- people of the workshop: name + PIN, role, sessions (F1-A of the redesign, 2026-10-21).

What it keeps:
  - the users (name, role, modes an operator may run, camera for viewers) and the settings of the sessions, in ONE file;
  - the PIN of each one only as a salted hash (scrypt, else PBKDF2), never in clear;
  - the sessions (token -> user) ONLY in memory: restarting the service logs everybody out.

Where the file lives: like the keys (config_store.py) it goes OUTSIDE the SD, in /opt/dsf/conf (mode 600). Reason: DWC's file
API serves any file of the SD to whoever opens DWC, and a PIN of 4 digits has only 10,000 possibilities: a hash on the SD could be
cracked in seconds. In /opt/dsf/conf the web does not reach it. (Override: env WORKSHOP_USERS.)

Compatibility: while the file does not exist (no user created) `configured()` is False and the API behaves as before (everybody is
admin); the first user created turns the identity on. A file that exists but cannot be read is `damaged`: it fails CLOSED (nobody
logs in; delete the file by hand to start again), never open.

Protection against guessing PINs: after MAX_FAILS wrong PINs the user, the client (device or address) and, in the end, the whole
service are locked for a while that grows with every new lock. Pure Python, no DSF import: tested on a PC (test_users.py).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

import paths
import permissions

USERS_FILE = os.environ.get("WORKSHOP_USERS") or paths.CONF + "/workshop-users.json"
MIN_PIN = 4
MAX_PIN = 12
MAX_USERS = 40
MAX_SESSIONS = 60
MAX_FAILS = 5            # wrong PINs before a lock
FAIL_WINDOW_S = 600      # failures older than this are forgotten
LOCK_BASE_S = 60         # first lock; doubles with every new lock, up to LOCK_MAX_S
LOCK_MAX_S = 900
GLOBAL_FAILS = 40        # wrong PINs of everybody within the window before every login waits
GLOBAL_LOCK_S = 60
DEFAULT_SETTINGS = {
    "idle_minutes": 720,         # a session with no activity this long expires (12 h: a day of work is not asked the PIN again)
    "max_hours": 12,             # and no session lives longer than this, active or not
    "never_expires": False,      # True: sessions end only by logging out or restarting the service (the two limits above are ignored)
    "anonymous_viewer": False,   # a caller with no login may read the state (e.g. the touch screen of the kiosk)
    "camera_for_viewer": False,  # viewers see the camera (also per user)
    "enabled": True,             # False: the people stay saved but nobody is asked to identify (everybody is an administrator again)
}
_NAME = re.compile(r"^[\w .\-]{1,32}$", re.UNICODE)
_SCRYPT = dict(n=2 ** 14, r=8, p=1)


class UserError(Exception):
    """A request about users that cannot be done. code: invalid_name, pin_policy, exists, unknown_user, last_admin,
    self_demote, bad_credentials, locked, damaged, too_many, invalid_args."""

    def __init__(self, code, message="", **extra):
        super().__init__(message or code)
        self.code = code
        self.extra = extra


# ---- PIN hashing ----

def hash_pin(pin, salt=None):
    """'scrypt$<salt hex>$<hash hex>' (or 'pbkdf2$...' where scrypt is not available)."""
    salt = salt or secrets.token_bytes(16)
    raw = str(pin).encode("utf-8")
    try:
        h = hashlib.scrypt(raw, salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT)
        algo = "scrypt"
    except (AttributeError, ValueError):
        h = hashlib.pbkdf2_hmac("sha256", raw, salt, 200000, 32)
        algo = "pbkdf2"
    return "%s$%s$%s" % (algo, salt.hex(), h.hex())


def verify_pin(pin, stored):
    try:
        algo, salt, want = str(stored).split("$")
        salt_b = bytes.fromhex(salt)
        raw = str(pin).encode("utf-8")
        if algo == "scrypt":
            h = hashlib.scrypt(raw, salt=salt_b, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT)
        elif algo == "pbkdf2":
            h = hashlib.pbkdf2_hmac("sha256", raw, salt_b, 200000, 32)
        else:
            return False
        return hmac.compare_digest(h.hex(), want)
    except (ValueError, TypeError, AttributeError):
        return False


_dummy = []


def _dummy_hash():
    """Hash that no PIN opens, to spend the same time when the name does not exist."""
    if not _dummy:
        _dummy.append(hash_pin("0000", bytes(16)))
    return _dummy[0]


def check_pin_policy(pin):
    p = str(pin if pin is not None else "")
    if not p.isdigit() or not MIN_PIN <= len(p) <= MAX_PIN:
        raise UserError("pin_policy", "the PIN must have %d to %d digits" % (MIN_PIN, MAX_PIN))
    if len(set(p)) == 1:
        raise UserError("pin_policy", "the PIN cannot be one repeated digit")
    return p


def clean_name(name):
    n = " ".join(str(name or "").split())
    if not _NAME.match(n):
        raise UserError("invalid_name", "the name must have 1 to 32 letters, digits, spaces, dots or hyphens")
    return n


def _key(name):
    return str(name or "").strip().casefold()


class UserStore:
    def __init__(self, path=None, log=print, now=time.time):
        self.path = path or USERS_FILE
        self.log = log
        self.now = now
        self.lock = threading.RLock()
        self.users = {}       # casefolded name -> record
        self.settings = dict(DEFAULT_SETTINGS)
        self.damaged = False
        self.sessions = {}    # token hash -> {name key, created, last, device}
        self.fails = {}       # "u:<name>" / "c:<client>" / "g" -> {"n", "first", "until", "strikes"}
        self.load()

    # ---- file ----
    def load(self):
        with self.lock:
            self.users, self.settings, self.damaged = {}, dict(DEFAULT_SETTINGS), False
            if not os.path.exists(self.path) and not os.path.exists(self.path + ".bak"):
                return
            data = None
            for f in (self.path, self.path + ".bak"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    break
                except (OSError, ValueError):
                    continue
            if not isinstance(data, dict) or not isinstance(data.get("users"), list):
                self.damaged = True
                self.log("users: the users file exists but cannot be read: the identity fails closed")
                return
            for rec in data["users"]:
                if isinstance(rec, dict) and rec.get("name") and rec.get("pin_hash") and rec.get("role") in permissions.RANK:
                    self.users[_key(rec["name"])] = rec
            self.settings.update({k: data.get("settings", {}).get(k, v) for k, v in DEFAULT_SETTINGS.items()})

    def _save(self):
        data = {"version": 1, "users": list(self.users.values()), "settings": self.settings}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        if os.path.exists(self.path):
            try:
                os.replace(self.path, self.path + ".bak")
            except OSError:
                pass
        os.replace(tmp, self.path)

    # ---- state ----
    def configured(self):
        """True when identity is required: there is at least one user and the owner has not switched the roles off, or the file is
        damaged (fail closed, the switch does not count)."""
        return (bool(self.users) and bool(self.settings.get("enabled", True))) or self.damaged

    def _public(self, rec):
        return {"name": rec["name"], "role": rec["role"], "modes": list(rec.get("modes") or []),
                "camera_for_viewer": bool(rec.get("camera_for_viewer")), "created": rec.get("created"),
                "pin_changed": rec.get("pin_changed")}

    def list(self):
        with self.lock:
            out = sorted((self._public(r) for r in self.users.values()), key=lambda r: r["name"].casefold())
            now = self.now()
            live = {}
            for s in self.sessions.values():
                if self._alive(s, now):
                    live[s["key"]] = max(live.get(s["key"], 0), s["last"])
            for r in out:
                r["last_seen"] = live.get(_key(r["name"]))
                r["sessions"] = sum(1 for s in self.sessions.values() if s["key"] == _key(r["name"]) and self._alive(s, now))
            return out

    def get_settings(self):
        with self.lock:
            return dict(self.settings)

    def set_settings(self, changes):
        with self.lock:
            s = dict(self.settings)
            if changes.get("idle_minutes") is not None:
                s["idle_minutes"] = int(min(max(int(changes["idle_minutes"]), 1), 1440))
            if changes.get("max_hours") is not None:
                s["max_hours"] = int(min(max(int(changes["max_hours"]), 1), 168))
            for k in ("anonymous_viewer", "camera_for_viewer", "never_expires"):
                if changes.get(k) is not None:
                    s[k] = bool(changes[k])
            self.settings = s
            self._save()
            return dict(s)

    def set_enabled(self, enabled, actor=None, pin=None, client=""):
        """Switches the roles on or off WITHOUT touching the people. Off needs the PIN of the administrator who asks (counted like a login
        attempt) and ends every session; on needs at least one person. Not while the file is damaged."""
        with self.lock:
            if self.damaged:
                raise UserError("damaged", "the users file is damaged")
            if not self.users:
                raise UserError("no_users", "there are no people to turn on")
            if enabled:
                self.settings["enabled"] = True
            else:
                rec = self._rec(actor) if actor else None
                if rec is None or rec.get("role") != "admin":
                    raise UserError("admin_only", "only a logged in administrator may turn the roles off")
                self._check_locks(actor, client)
                if not verify_pin(pin, rec["pin_hash"]):
                    self._fail(actor, client)
                    raise UserError("bad_credentials", "the PIN is wrong")
                self.settings["enabled"] = False
                self.sessions.clear()
            self._save()
            return dict(self.settings)

    # ---- management ----
    def _rec(self, name):
        rec = self.users.get(_key(name))
        if rec is None:
            raise UserError("unknown_user", "there is no user '%s'" % name)
        return rec

    def _admins(self):
        return [r for r in self.users.values() if r["role"] == permissions.ADMIN]

    def _check_role(self, role):
        if role not in permissions.RANK:
            raise UserError("invalid_args", "the role must be one of: " + ", ".join(permissions.ROLES))
        return role

    def add(self, name, pin, role, modes=None, camera_for_viewer=False):
        with self.lock:
            if self.damaged:
                raise UserError("damaged", "the users file is damaged")
            name = clean_name(name)
            if _key(name) in self.users:
                raise UserError("exists", "there is already a user '%s'" % name)
            if len(self.users) >= MAX_USERS:
                raise UserError("too_many", "at most %d users" % MAX_USERS)
            self._check_role(role)
            pin = check_pin_policy(pin)
            rec = {"name": name, "role": role, "modes": permissions.clean_modes(modes), "camera_for_viewer": bool(camera_for_viewer),
                   "pin_hash": hash_pin(pin), "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.now())),
                   "pin_changed": None}
            self.users[_key(name)] = rec
            self._save()
            return self._public(rec)

    def set(self, name, actor=None, role=None, modes=None, camera_for_viewer=None):
        """Changes role / modes / camera of a user. Nobody lowers their own role, and the last admin stays."""
        with self.lock:
            rec = self._rec(name)
            if role is not None:
                self._check_role(role)
                if role != rec["role"]:
                    if actor is not None and _key(actor) == _key(rec["name"]):
                        raise UserError("self_demote", "you cannot change your own role")
                    if rec["role"] == permissions.ADMIN and len(self._admins()) <= 1:
                        raise UserError("last_admin", "the machine cannot be left without an administrator")
                    rec["role"] = role
                    self.kill_sessions(rec["name"])  # the permissions change at once, not at the next login
            if modes is not None:
                rec["modes"] = permissions.clean_modes(modes)
            if camera_for_viewer is not None:
                rec["camera_for_viewer"] = bool(camera_for_viewer)
            self._save()
            return self._public(rec)

    def remove(self, name, actor=None):
        with self.lock:
            rec = self._rec(name)
            if actor is not None and _key(actor) == _key(rec["name"]):
                raise UserError("self_demote", "you cannot remove yourself")
            if rec["role"] == permissions.ADMIN and len(self._admins()) <= 1:
                raise UserError("last_admin", "the machine cannot be left without an administrator")
            del self.users[_key(name)]
            self.kill_sessions(rec["name"])
            self._save()
            return self._public(rec)

    def reset_pin(self, name, pin):
        with self.lock:
            rec = self._rec(name)
            rec["pin_hash"] = hash_pin(check_pin_policy(pin))
            rec["pin_changed"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.now()))
            self.kill_sessions(rec["name"])
            self.fails.pop("u:" + _key(name), None)
            self._save()
            return self._public(rec)

    def change_pin(self, name, old_pin, new_pin, client=""):
        """The user's own change: needs the old PIN (counted like a login attempt)."""
        with self.lock:
            rec = self._rec(name)
            self._check_locks(name, client)
            if not verify_pin(old_pin, rec["pin_hash"]):
                self._fail(name, client)
                raise UserError("bad_credentials", "the PIN is wrong")
            rec["pin_hash"] = hash_pin(check_pin_policy(new_pin))
            rec["pin_changed"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.now()))
            self._save()
            return self._public(rec)

    # ---- guessing protection ----
    def _entry(self, k):
        now = self.now()
        e = self.fails.get(k)
        if e is None or (now - e["first"] > FAIL_WINDOW_S and e["until"] <= now):
            e = self.fails[k] = {"n": 0, "first": now, "until": 0, "strikes": e["strikes"] if e else 0}
        return e

    def _check_locks(self, name, client):
        now = self.now()
        wait = 0
        for k in ("u:" + _key(name), "c:" + str(client or ""), "g"):
            e = self.fails.get(k)
            if e and e["until"] > now:
                wait = max(wait, int(e["until"] - now) + 1)
        if wait:
            raise UserError("locked", "too many wrong PINs; wait %d s" % wait, wait_s=wait)

    def _fail(self, name, client):
        now = self.now()
        for k, limit in (("u:" + _key(name), MAX_FAILS), ("c:" + str(client or ""), MAX_FAILS * 2), ("g", GLOBAL_FAILS)):
            e = self._entry(k)
            e["n"] += 1
            if e["n"] >= limit:
                e["strikes"] += 1
                e["until"] = now + (GLOBAL_LOCK_S if k == "g" else min(LOCK_BASE_S * 2 ** (e["strikes"] - 1), LOCK_MAX_S))
                e["n"] = 0
                e["first"] = now
        if len(self.fails) > 500:  # never grows without limit
            for k in [k for k, e in self.fails.items() if e["until"] <= now and now - e["first"] > FAIL_WINDOW_S]:
                del self.fails[k]

    # ---- sessions ----
    @staticmethod
    def _sid(token):
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    def _alive(self, s, now):
        st = self.settings
        if st.get("never_expires"):
            return True
        return now - s["last"] <= st["idle_minutes"] * 60 and now - s["created"] <= st["max_hours"] * 3600

    def login(self, name, pin, client="", device=""):
        """Returns (token, public record). Raises UserError bad_credentials / locked / damaged. The slow hash runs OUTSIDE the lock:
        the HTTP thread that resolves tokens never waits for a login."""
        with self.lock:
            if self.damaged:
                raise UserError("damaged", "the users file is damaged")
            self._check_locks(name, client)
            rec = self.users.get(_key(name))
            stored = rec["pin_hash"] if rec else _dummy_hash()  # the same work for an unknown name
        ok = verify_pin(pin, stored)
        with self.lock:
            if not rec or not ok or self.users.get(_key(name)) is not rec:
                self._fail(name, client)
                raise UserError("bad_credentials", "wrong name or PIN")
            self.fails.pop("u:" + _key(name), None)
            now = self.now()
            for sid in [k for k, s in self.sessions.items() if not self._alive(s, now)]:
                del self.sessions[sid]
            while len(self.sessions) >= MAX_SESSIONS:  # the oldest goes
                del self.sessions[min(self.sessions, key=lambda k: self.sessions[k]["last"])]
            token = secrets.token_urlsafe(32)
            self.sessions[self._sid(token)] = {"key": _key(name), "created": now, "last": now, "device": str(device or "")[:40]}
            return token, self._public(rec)

    def resolve(self, token):
        """Identity of a token without touching it: {name, role, modes, camera, sid} or None (unknown, expired, user gone)."""
        if not token:
            return None
        with self.lock:
            sid = self._sid(token)
            s = self.sessions.get(sid)
            if s is None:
                return None
            if not self._alive(s, self.now()):
                del self.sessions[sid]
                return None
            rec = self.users.get(s["key"])
            if rec is None:
                del self.sessions[sid]
                return None
            return {"name": rec["name"], "role": rec["role"], "modes": list(rec.get("modes") or []), "sid": sid,
                    "camera": bool(rec.get("camera_for_viewer") or self.settings.get("camera_for_viewer"))}

    def touch(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if s is not None:
                s["last"] = self.now()

    def logout(self, sid):
        with self.lock:
            return self.sessions.pop(sid, None) is not None

    def kill_sessions(self, name):
        with self.lock:
            k = _key(name)
            for sid in [i for i, s in self.sessions.items() if s["key"] == k]:
                del self.sessions[sid]

    def anonymous(self):
        """Identity of a caller with no login when the settings allow it (a viewer), else None."""
        with self.lock:
            if self.settings.get("anonymous_viewer") and not self.damaged:
                return {"name": "", "role": permissions.VIEWER, "modes": [], "sid": None, "camera": bool(self.settings.get("camera_for_viewer"))}
            return None
