"""Store of the calibration records and the maintenance state of Machine v2 (design section 4.3; phase 0).

Two files of settings_store (revision = hash of the bytes, so two technicians recording at the same time never overwrite each
other: the loser re-reads and tries again):

    machine-calibrations   {"schema": 1, "records": [record, ...]}      oldest first, the last MAX_RECORDS kept
    machine-maintenance    {"schema": 1, "done": {item id: {"ts", "user", "role", "run_id", "base"?, "note"?}}, "counters": {...},
                            "notify": {"enabled"}?, "notified": {item id: {"level", "epoch"}}?}      (phase 4: machine_odometer.py, machine_maintenance.py)

Only this module writes them (settings.set / settings.merge refuse the names, see settings_store.SERVICE_ONLY): a record is made by a
procedure of the service on behalf of a person, never typed in. Every record is also noted in the audit with its run_id.

Record (schema 1; `id` is made here; unknown fields are refused so a typo is not saved in silence):
    id          "c-<epoch>-<6 hex>"
    kind        one of KINDS
    ts          epoch seconds (int)
    user, role, device   who (from identity.actor); "" without users
    origin      "machine"
    run_id      the procedure run that made it, or null (a manual entry)
    machine     {"name", "board", "firmware", "kinematics", "axes_fingerprint"}   (fingerprint_of(capabilities))
    inputs      what was asked (small object)
    results     what was measured (small object)
    applied     null | {"files": [{"path", "sha_before", "sha_after", "snapshot_id"}]}   config files a record changed
    notes       text, up to 500 characters
    state       done | partial | stopped | error
The index keeps small data only: a record over MAX_RECORD_BYTES is refused (too_large) (a mesh or a report goes in a file of its own, not here).

A file with any other `schema` is refused (StoreError) and never rewritten by this service.
"""
import hashlib
import json
import secrets
import time

import audit
import permissions
import settings_store as store

SCHEMA = 1
CALIBRATIONS = "machine-calibrations"
MAINTENANCE = "machine-maintenance"
MAX_RECORDS = 500
MAX_RECORD_BYTES = 2500   # a whole record, as compact JSON: 500 of them stay well under settings_store.MAX_BYTES (2 MB) even pretty printed
MAX_NOTES = 500
STATES = ("done", "partial", "stopped", "error")
RETRIES = 6

# the procedures of machine.run (design 4.1) and the configuration writes; ADMIN kinds come from permissions
RUN_KINDS = ("probe.read", "probe.repeat", "probe.accuracy", "probe.trigger", "probe.offset", "level.g32", "level.g30", "level.measure",
             "mesh.probe", "homing.verify", "homing.repeat", "offsets.verify", "safety.check", "shaping.tune")
CONFIG_KINDS = ("config.g31", "config.m671", "config.bed", "config.g10", "config.m557", "config.m593", "config.m425", "config.m556",
                "config.m376", "config.m203", "config.m201", "config.m205", "config.m566") + tuple(permissions.MACHINE_ADMIN_KINDS)
RECORD_KINDS = ("offsets.snapshot", "laser.pointer", "calc.steps", "calc.skew", "calc.backlash", "calc.ringing")      # records that are not a machine.run (machine.offsets.snapshot, machine.mark_cross)
KINDS = RUN_KINDS + RECORD_KINDS + CONFIG_KINDS
FIELDS = ("id", "kind", "ts", "user", "role", "device", "origin", "run_id", "machine", "inputs", "results", "applied", "notes", "state")


class StoreError(ValueError):
    """Invalid record or a file this version cannot read. .code is a short code for the caller."""

    def __init__(self, code, detail=""):
        super().__init__("%s%s" % (code, ": " + detail if detail else ""))
        self.code = code


# ---- schema ----

def empty(name):
    return {"schema": SCHEMA, "records": []} if name == CALIBRATIONS else {"schema": SCHEMA, "done": {}, "counters": {}}


def check(value, name):
    """What the file holds (None = no file yet) as the current schema. A file of any other schema is refused (StoreError) and never
    rewritten by this service."""
    if value is None:
        return empty(name)
    v = value.get("schema") if isinstance(value, dict) else None
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise StoreError("schema_invalid")
    if v != SCHEMA:
        raise StoreError("schema_unsupported", "found %s, known %s" % (v, SCHEMA))
    return value


# ---- records ----

def fingerprint_of(caps):
    """{"name", "board", "firmware", "kinematics", "axes_fingerprint"} from a capabilities.get answer: what identifies the machine a
    record was made on. The axes fingerprint is a short hash of letters, ranges and driver counts (it changes when the geometry does)."""
    c = (caps or {}).get("capabilities") or {}
    board = (caps or {}).get("board") or {}
    axes = [(a.get("letter"), a.get("min"), a.get("max"), len(a.get("drivers") or [])) for a in (c.get("axes") or {}).get("items") or []]
    raw = json.dumps(axes, separators=(",", ":"))
    return {"name": "", "board": board.get("short_name") or board.get("name"), "firmware": board.get("firmware_version"),
            "kinematics": (c.get("kinematics") or {}).get("name"), "axes_fingerprint": hashlib.sha1(raw.encode()).hexdigest()[:10]}


def new_id(now=None):
    return "c-%d-%s" % (int(now if now is not None else time.time()), secrets.token_hex(3))


def make_record(kind, who, run_id=None, machine=None, inputs=None, results=None, applied=None, notes="", state="done", now=None):
    """A valid record (ValueError-free path for the runner); validate() is applied before returning."""
    who = who or {}
    rec = {"id": new_id(now), "kind": kind, "ts": int(now if now is not None else time.time()), "user": who.get("user", ""),
           "role": who.get("role", ""), "device": who.get("device", ""), "origin": "machine", "run_id": run_id,
           "machine": machine or {"name": "", "board": None, "firmware": None, "kinematics": None, "axes_fingerprint": ""},
           "inputs": inputs or {}, "results": results or {}, "applied": applied, "notes": notes, "state": state}
    return validate(rec)


def _small_object(v, field):
    if not isinstance(v, dict):
        raise StoreError("invalid_field", field)
    try:
        json.dumps(v, separators=(",", ":"))
    except (TypeError, ValueError):
        raise StoreError("invalid_field", field)
    return v


def _applied(v):
    if v is None:
        return None
    files = v.get("files") if isinstance(v, dict) and set(v) == {"files"} else None
    if not isinstance(files, list) or len(files) > 16:
        raise StoreError("invalid_field", "applied")
    for f in files:
        if not isinstance(f, dict) or set(f) != {"path", "sha_before", "sha_after", "snapshot_id"} or not isinstance(f["path"], str):
            raise StoreError("invalid_field", "applied.files")
    return v


def validate(rec):
    """The record as it is stored. StoreError (with .code) for anything that is not valid."""
    if not isinstance(rec, dict) or set(rec) - set(FIELDS):
        raise StoreError("unknown_field", ", ".join(sorted(set(rec) - set(FIELDS))) if isinstance(rec, dict) else "")
    if rec.get("kind") not in KINDS:
        raise StoreError("invalid_kind", str(rec.get("kind")))
    if rec.get("state") not in STATES:
        raise StoreError("invalid_state", str(rec.get("state")))
    if not isinstance(rec.get("ts"), int) or isinstance(rec.get("ts"), bool) or rec["ts"] < 0:
        raise StoreError("invalid_field", "ts")
    for k in ("id", "user", "role", "device", "notes"):
        if not isinstance(rec.get(k, ""), str):
            raise StoreError("invalid_field", k)
    if not rec.get("id"):
        raise StoreError("invalid_field", "id")
    if rec.get("run_id") is not None and not isinstance(rec["run_id"], str):
        raise StoreError("invalid_field", "run_id")
    out = dict(rec, origin="machine", notes=str(rec.get("notes") or "")[:MAX_NOTES], applied=_applied(rec.get("applied")))
    for k in ("machine", "inputs", "results"):
        out[k] = _small_object(rec.get(k) if rec.get(k) is not None else {}, k)
    if len(json.dumps(out, separators=(",", ":"))) > MAX_RECORD_BYTES:
        raise StoreError("too_large", "record")
    return out


# ---- reading and writing with a revision ----

def _load(name):
    got = store.get(name)
    return check(got["value"], name), got["rev"]


def _write(name, value, base_rev):
    return store.set(name, value, base_rev)


def _update(name, change):
    """Reads, applies change(value) -> value, writes with the revision read; on a conflict (another writer) it reads again and
    repeats, up to RETRIES times. Returns what change returned last."""
    for _ in range(RETRIES):
        value, rev = _load(name)
        value = change(value)
        try:
            _write(name, value, rev)
            return value
        except store.Conflict:
            continue
    raise StoreError("conflict", name)


def append(rec, who=None, log=print):
    """Stores a record (validated) at the end of the calibration history, drops the oldest beyond MAX_RECORDS, and notes it in the
    audit with its run_id. Returns the stored record."""
    clean = validate(rec)

    def add(value):
        records = list(value["records"]) + [clean]
        return dict(value, records=records[-MAX_RECORDS:])

    _update(CALIBRATIONS, add)
    audit.event("machine.record", {"id": clean["id"], "kind": clean["kind"], "run_id": clean["run_id"], "state": clean["state"]},
                who or {"user": clean["user"], "role": clean["role"], "device": clean["device"]}, log=log)
    return clean


def records(kind=None, limit=50):
    """Newest first. kind=None: every kind."""
    value, _ = _load(CALIBRATIONS)
    out = [r for r in reversed(value["records"]) if kind is None or r.get("kind") == kind]
    return out[:max(0, int(limit))]


def query(kind=None, user=None, since=None, until=None, state=None, limit=50, offset=0):
    """Newest first, filtered: kind, user (exact), ts between since and until (epoch seconds, inclusive), state. Returns (page, total)."""
    value, _ = _load(CALIBRATIONS)
    rows = [r for r in reversed(value["records"])
            if (kind is None or r.get("kind") == kind) and (user is None or r.get("user") == user) and (state is None or r.get("state") == state)
            and (since is None or r["ts"] >= since) and (until is None or r["ts"] <= until)]
    offset = max(0, int(offset))
    return rows[offset:offset + max(0, int(limit))], len(rows)


def get_record(rec_id):
    value, _ = _load(CALIBRATIONS)
    return next((r for r in value["records"] if r.get("id") == rec_id), None)


def revision():
    """Revision of the calibration file (changes with every record)."""
    return store.get(CALIBRATIONS)["rev"]


def last_by_kind(now=None):
    """{kind: {"ts", "age_days", "state", "user"}} of the newest record of each kind that ended done or partial. No values: this is what
    the overview (open to every role) is built from."""
    now = int(now if now is not None else time.time())
    out = {}
    value, _ = _load(CALIBRATIONS)
    for r in value["records"]:
        if r.get("state") in ("done", "partial") and r["ts"] >= out.get(r["kind"], {}).get("ts", -1):
            out[r["kind"]] = {"ts": r["ts"], "age_days": max(0, (now - r["ts"]) // 86400), "state": r["state"], "user": r.get("user", "")}
    return out


# ---- maintenance ----

def maintenance():
    value, rev = _load(MAINTENANCE)
    return dict(value, rev=rev)


def update_maintenance(change):
    """Read-modify-write of the maintenance store with the revision check (change(value) -> value; it runs again after a conflict).
    The counters poller, `done` and the plan settings all write through here, so none of them overwrites another."""
    return _update(MAINTENANCE, change)


def maintenance_done(item_id, who, run_id=None, now=None, log=print, base=None, note=""):
    """Notes that a maintenance item was done (who, when) and the counters at that moment (`base`, the new zero of the item). The plan
    itself (intervals) lives in the machine profile."""
    if not isinstance(item_id, str) or not 1 <= len(item_id) <= 40:
        raise StoreError("invalid_field", "id")
    who = who or {}
    entry = {"ts": int(now if now is not None else time.time()), "user": who.get("user", ""), "role": who.get("role", ""), "run_id": run_id}
    if base is not None:
        entry["base"] = base
    if note:
        entry["note"] = str(note)[:200]

    def mark(value):
        notified = {k: v for k, v in (value.get("notified") or {}).items() if k != item_id}
        return dict(value, done=dict(value["done"], **{item_id: entry}), notified=notified)

    update_maintenance(mark)
    audit.event("machine.maintenance.done", {"id": item_id, "run_id": run_id, "note": entry.get("note", "")}, who, log=log)
    return entry
