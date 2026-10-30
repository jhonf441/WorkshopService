"""Store of the shared settings files of the workshop, with a revision (F1-B).

Problem: the pages used to read a whole file (jog.json, laser.json...), change one field and write
the WHOLE file back through DWC's file API. Two people editing at the same time overwrote each other
in silence. Here the service is the one that writes: every read returns {value, rev} and every write
carries the rev it was based on (base_rev); if the file changed meanwhile the write is refused with a
conflict and the caller gets the current value to merge or retry.

  - rev = short hash of the exact bytes of the file on the card, "0" when the file does not exist yet.
    A hash (and not a counter kept inside the file) means a client that still writes the file directly
    through DWC's file API does not break anything: its write simply changes the rev, so the next
    set() based on the old rev is refused. Such a client has no protection of its own, nothing else.
  - only the names of NAMES (no paths, no '..'), all under sys/workshop/config (one under data);
  - atomic write: temporary file + fsync + os.replace; the previous healthy version stays as <file>.bak
    (one rolling copy; the pages read it when the file is damaged);
  - one lock per file serializes read-compare-write (and merge) inside the service.
"""
import hashlib
import json
import os
import threading

import sd_paths

CONFIG_DIR = "sys/workshop/config"
DATA_DIR = "sys/workshop/data"
# name -> folder (relative to the SD). Whitelist: nothing else can be read or written through the API.
NAMES = {n: CONFIG_DIR for n in (
    "bridge", "buttons", "camera", "camera-map", "cameras", "clamps", "current", "focus", "jog", "jog-macros",
    "laser", "materials", "motors", "printing", "rs485", "step-ceiling", "vision", "zcal",
    "work_state", "zone-extra", "zone-sizes", "zone-zpoints")}
NAMES["laser-designs"] = DATA_DIR
# Machine v2 (calibration records and maintenance counters): revisioned like the rest, but only machine_store.py writes them
# (settings.set / settings.merge refuse these names: a record is made by a procedure of the service, never typed in).
NAMES["machine-calibrations"] = CONFIG_DIR
NAMES["machine-maintenance"] = CONFIG_DIR
NAMES["machine-pointsets"] = CONFIG_DIR   # named point sets of the Machine bed view (docs/MACHINE-POINTSETS-CONTRACT.md); an ordinary store: operator reads, technician writes
SERVICE_ONLY = frozenset({"machine-calibrations", "machine-maintenance"})
MAX_BYTES = 2 * 1024 * 1024  # a settings file is small; this stops a runaway client
NO_FILE_REV = "0"  # rev of a file that does not exist yet

_locks = {}
_locks_guard = threading.Lock()


class SettingsError(Exception):
    """Invalid name or value."""


class Conflict(Exception):
    """base_rev is not the current rev: carries the current value and rev."""

    def __init__(self, value, rev):
        super().__init__("settings changed by someone else")
        self.value = value
        self.rev = rev


def path_of(name):
    """Real path of a whitelisted name; SettingsError otherwise (no free paths)."""
    folder = NAMES.get(name) if isinstance(name, str) else None
    if folder is None:
        raise SettingsError("unknown settings name")
    return sd_paths.sd(folder + "/" + name + ".json")


def lock_of(name):
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def rev_of_bytes(raw):
    return hashlib.sha1(raw).hexdigest()[:12]


def _parse(raw):
    return json.loads(raw.decode("utf-8-sig"))


def _read_raw(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _read(path):
    """(value, rev) of the file; a damaged or missing file falls back to the .bak value (the rev stays that of the file itself)."""
    raw = _read_raw(path)
    rev = NO_FILE_REV if raw is None else rev_of_bytes(raw)
    for candidate in (raw, _read_raw(path + ".bak")):
        if candidate is None:
            continue
        try:
            return _parse(candidate), rev
        except ValueError:
            continue
    return None, rev


def get(name):
    """{"value", "rev"}; value is None when there is no file (rev "0")."""
    path = path_of(name)
    with lock_of(name):
        value, rev = _read(path)
    return {"value": value, "rev": rev}


def _write_atomic(path, raw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-" + str(os.getpid())
    with open(tmp, "wb") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())  # to the card before the rename (power cut)
    try:  # the previous healthy version stays as .bak
        with open(path, "rb") as f0:
            old = f0.read()
        _parse(old)
        with open(path + ".bak", "wb") as fb:
            fb.write(old)
    except (OSError, ValueError):
        pass
    os.replace(tmp, path)


def _encode(value):
    if not isinstance(value, (dict, list)):
        raise SettingsError("a settings value must be an object or a list")
    raw = (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise SettingsError("settings value too large")
    return raw


def set(name, value, base_rev):
    """Writes value if base_rev is the current rev. Returns {"rev", "changed"}; raises Conflict or SettingsError."""
    path = path_of(name)
    raw = _encode(value)
    with lock_of(name):
        current, rev = _read(path)
        if str(base_rev) != rev:
            raise Conflict(current, rev)
        new_rev = rev_of_bytes(raw)
        if new_rev == rev:
            return {"rev": rev, "changed": False}
        _write_atomic(path, raw)
    return {"rev": new_rev, "changed": True}


def merge(name, patch):
    """Sets the top-level keys of patch over the current object (no base_rev: for fields that do not clash).
    Returns {"value", "rev", "changed"}."""
    path = path_of(name)
    if not isinstance(patch, dict):
        raise SettingsError("a merge patch must be an object")
    with lock_of(name):
        current, rev = _read(path)
        if current is None:
            current = {}
        if not isinstance(current, dict):
            raise SettingsError("the file is not an object: use set")
        merged = dict(current)
        merged.update(patch)
        raw = _encode(merged)
        new_rev = rev_of_bytes(raw)
        if new_rev == rev:
            return {"value": merged, "rev": rev, "changed": False}
        _write_atomic(path, raw)
    return {"value": merged, "rev": new_rev, "changed": True}
