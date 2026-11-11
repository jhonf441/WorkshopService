"""
access_usage -- the LAST USE of each capability by each person (phase 6 of informes/control-acceso/PLAN-ACCESO.md, section 4.5).

A small JSON file, `workshop-access-usage.json`, next to the access file (paths.CONF; override: env WORKSHOP_ACCESS_USAGE). It is NOT a database table:

    {"version": 1, "used": {"<person, casefolded>": {"<capability id>": <epoch seconds, a whole number>, ...}, ...}}

Design (the Pi's SD card is never punished and a decision is never slowed or broken by this file):
  - memory first: `touch` looks in a dict and returns; a pair (person, capability) is stamped at most once per WRITE_EVERY_S, so a jog that
    calls 15 times a second costs one dict lookup and one comparison;
  - the file is written at most once per WRITE_EVERY_S for ALL pairs together, by whoever touches after the interval (no thread), and at the
    clean shutdown (`flush_all`, called by main._clean_stop);
  - fail-safe: a file that is missing, damaged or has anything unexpected starts the memory empty (it is replaced by the next write); a file
    that cannot be written is logged and tried again one interval later; `touch` never raises;
  - bounded: at most MAX_PAIRS pairs (a new pair over the limit is not recorded).
Pure Python, no DSF import (tested on a PC). The capability of an operation is looked up by the caller (identity), not here.
"""
import json
import os
import threading
import time

import fs_atomic
import paths

USAGE_FILE = os.environ.get("WORKSHOP_ACCESS_USAGE") or paths.CONF + "/workshop-access-usage.json"
SCHEMA = 1
WRITE_EVERY_S = 60
MAX_PAIRS = 3000
MAX_CAPABILITY = 64

_STORES = []  # every store opened by this process, for the clean shutdown
_STORES_LOCK = threading.Lock()


def _key(name):
    return str(name or "").strip().casefold()


def parse(raw):
    """{(person, capability): epoch} from the text of a file; ValueError when it is not what this module writes."""
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("version") != SCHEMA or not isinstance(data.get("used"), dict):
        raise ValueError("unexpected content")
    out = {}
    for person, caps_ in data["used"].items():
        if not isinstance(person, str) or not isinstance(caps_, dict):
            raise ValueError("unexpected person")
        for cap, ts in caps_.items():
            if not isinstance(cap, str) or not 0 < len(cap) <= MAX_CAPABILITY or isinstance(ts, bool) or not isinstance(ts, int) or ts < 0:
                raise ValueError("unexpected entry")
            out[(person, cap)] = ts
    if len(out) > MAX_PAIRS:
        raise ValueError("too many entries")
    return out


def serialize(mem):
    used = {}
    for (person, cap), ts in sorted(mem.items()):
        used.setdefault(person, {})[cap] = int(ts)
    return json.dumps({"version": SCHEMA, "used": used}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class UsageStore:
    def __init__(self, path=None, log=print, clock=time.time):
        self.path = path or USAGE_FILE
        self.log = log
        self.clock = clock
        self.lock = threading.Lock()
        self.damaged = False
        self._mem = {}
        self._dirty = False
        self._flushed_at = 0
        self._failed = False
        self._load()
        with _STORES_LOCK:
            _STORES.append(self)

    def _load(self):
        try:
            with open(self.path, "rb") as fh:
                self._mem = parse(fh.read())
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:  # a damaged file only loses the last-use dates: it is replaced by the next write
            self._mem, self.damaged = {}, True
            self.log("access usage: the file cannot be read (%s): last uses start empty" % e)

    def touch(self, person, capability):
        """Records that `person` used `capability` now. True when the memory changed. Never raises, never waits for the disk but once per interval."""
        try:
            pair = (_key(person), str(capability))
            now = int(self.clock())
            last = self._mem.get(pair)
            if last is not None and now - last < WRITE_EVERY_S:
                return False
            with self.lock:
                if last is None and len(self._mem) >= MAX_PAIRS:
                    return False
                self._mem[pair] = now
                self._dirty = True
                due = now - self._flushed_at >= WRITE_EVERY_S
            if due:
                self.flush()
            return True
        except Exception:  # noqa: BLE001  a record that fails must never fail the call that was allowed
            return False

    def flush(self, force=False):
        """Writes the file when something changed and the interval passed (always with `force`). True when it was written; False otherwise,
        including a write that failed (it is logged and tried again one interval later)."""
        with self.lock:
            now = int(self.clock())
            if not self._dirty or (not force and now - self._flushed_at < WRITE_EVERY_S):
                return False
            snapshot = dict(self._mem)
            self._flushed_at = now
            try:
                fs_atomic.write_bytes(self.path, serialize(snapshot), mode=0o600)
            except OSError as e:
                if not self._failed:
                    self.log("access usage: the file cannot be written (%s)" % e)
                self._failed = True
                return False
            self._failed = False
            self.damaged = False
            self._dirty = False
            return True

    def used(self):
        """{person (casefolded): {capability: epoch}} as it is now."""
        with self.lock:
            out = {}
            for (person, cap), ts in self._mem.items():
                out.setdefault(person, {})[cap] = ts
            return out

    def last_used(self, person, capability=None):
        """The epoch of the last use of `capability` by `person`, or of any capability when none is given; None when never."""
        with self.lock:
            p = _key(person)
            if capability is not None:
                return self._mem.get((p, str(capability)))
            seen = [ts for (who, _), ts in self._mem.items() if who == p]
            return max(seen) if seen else None

    def forget(self, person):
        """The person was removed: their dates go too (a new person with the same name starts with none)."""
        with self.lock:
            p = _key(person)
            gone = [pair for pair in self._mem if pair[0] == p]
            for pair in gone:
                del self._mem[pair]
            if gone:
                self._dirty = True
            return bool(gone)


def flush_all():
    """The clean shutdown: every store of this process writes what it has. Never raises."""
    with _STORES_LOCK:
        stores = list(_STORES)
    for s in stores:
        try:
            s.flush(force=True)
        except Exception:  # noqa: BLE001
            pass
