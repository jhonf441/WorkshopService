"""Work state of the operator, shared by every screen (F3-S, 2026-10-21): workstate.get / workstate.set.

The Workbench keeps, per work zone, which steps of "Prepare" were done (measure the material, frame the border), the focus
that was applied (the Z where the lens was left) and the focus height chosen for "Focus here". Before this it lived in one
browser. Writing the shared settings (settings.set) needs a technician, but this is what an OPERATOR does all day, so it has
its own operations (operator may read and write; a viewer only reads). It is stored with the shared settings store under the
name `work_state` (settings_store.py), so it has a revision, an atomic write and a backup like the other files.

Document (the same shape the Workbench already keeps under the key `work_state` of the `focus` file, so moving it is trivial):

    {"v": 1,
     "zones": {"<zone number>": {"prepare": {"measure": ts, "border": ts}, "applied": {"z": number|null, "ts": ts}|null}},
     "focus_h": {"h": number, "base": number, "ts": ts}|null}

ts is a time in milliseconds since the epoch; for a prepare mark a NEGATIVE ts means "cleared at that time". Unknown keys, wrong
types (booleans, text where a number goes), absurd values and documents over MAX_ZONES zones are refused as a whole.

workstate.set merges what it receives into what is stored, zone by zone and mark by mark, and the newest time wins (a tie goes
to the new value), so two screens that save at different moments lose nothing and what a screen did not touch is not overwritten.
"""
import copy
import math

import settings_store as store
from messages import M
from workshop_api import READ, WRITE, Arg, ApiError, Op

NAME = "work_state"
VERSION = 1
MAX_ZONES = 32
MAX_TS = 4e12          # year ~2096 in ms
MAX_ABS_Z = 10000.0
MAX_H = 1000.0
PREPARE_KINDS = ("measure", "border")
RETRIES = 6


class Invalid(ValueError):
    """The document has a wrong shape; .field says where."""

    def __init__(self, field):
        super().__init__(field)
        self.field = field


def empty():
    return {"v": VERSION, "zones": {}, "focus_h": None}


def _num(v, field, lo=-MAX_ABS_Z, hi=MAX_ABS_Z):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < lo or v > hi:
        raise Invalid(field)
    return v


def _ts(v, field, signed=False):
    v = _num(v, field, -MAX_TS if signed else 0, MAX_TS)
    if v == 0:
        raise Invalid(field)
    return v


def _only(obj, allowed, field):
    if not isinstance(obj, dict) or set(obj) - set(allowed):
        raise Invalid(field)


def _zone_key(k, field):
    if not isinstance(k, str) or not k.isdigit() or not k.isascii() or not 1 <= len(k) <= 3 or int(k) < 1:
        raise Invalid(field)
    return str(int(k))


def _zone(z, field):
    _only(z, ("prepare", "applied"), field)
    out = {"prepare": {}, "applied": None}
    prep = z.get("prepare", {})
    _only(prep, PREPARE_KINDS, field + ".prepare")
    for kind, v in prep.items():
        out["prepare"][kind] = _ts(v, field + ".prepare." + kind, signed=True)
    ap = z.get("applied")
    if ap is not None:
        _only(ap, ("z", "ts"), field + ".applied")
        if "ts" not in ap:
            raise Invalid(field + ".applied.ts")
        zv = ap.get("z")
        out["applied"] = {"z": None if zv is None else _num(zv, field + ".applied.z"), "ts": _ts(ap["ts"], field + ".applied.ts")}
    return out


def validate(doc):
    """Clean copy of a document (partial is fine: missing parts are empty); Invalid when anything is wrong."""
    _only(doc, ("v", "zones", "focus_h"), "state")
    if isinstance(doc.get("v"), bool) or doc.get("v", VERSION) != VERSION:
        raise Invalid("state.v")
    zones = doc.get("zones", {})
    if not isinstance(zones, dict) or len(zones) > MAX_ZONES:
        raise Invalid("state.zones")
    out = empty()
    for k, z in zones.items():
        key = _zone_key(k, "state.zones")
        out["zones"][key] = _zone(z, "state.zones." + key)
    fh = doc.get("focus_h")
    if fh is not None:
        _only(fh, ("h", "base", "ts"), "state.focus_h")
        if "h" not in fh or "ts" not in fh:
            raise Invalid("state.focus_h")
        out["focus_h"] = {"h": _num(fh["h"], "state.focus_h.h", 0, MAX_H), "base": _num(fh.get("base", 0), "state.focus_h.base"),
                          "ts": _ts(fh["ts"], "state.focus_h.ts")}
    return out


def _newer(old, new):
    """The one with the newest time; a tie goes to the new one."""
    if old is None:
        return new
    if new is None:
        return old
    return new if abs(new.get("ts", 0)) >= abs(old.get("ts", 0)) else old


def merge(stored, incoming):
    """stored and incoming are clean documents; returns the merged one (stored is not changed)."""
    out = copy.deepcopy(stored)
    for k, z in incoming["zones"].items():
        cur = out["zones"].setdefault(k, {"prepare": {}, "applied": None})
        for kind, v in z["prepare"].items():
            old = cur["prepare"].get(kind)
            if old is None or abs(v) >= abs(old):
                cur["prepare"][kind] = v
        cur["applied"] = _newer(cur["applied"], z["applied"])
    out["focus_h"] = _newer(out["focus_h"], incoming["focus_h"])
    return out


def _stored():
    """(clean document, rev) from the store; a damaged file counts as empty (the next set rewrites it clean)."""
    got = store.get(NAME)
    try:
        return validate(got["value"]) if got["value"] is not None else empty(), got["rev"]
    except Invalid:
        return empty(), got["rev"]


def get():
    doc, rev = _stored()
    return {"state": doc, "rev": rev}


def update(incoming):
    """Merges `incoming` (validated here) into the stored document. Returns {state, rev, changed}."""
    clean = validate(incoming)
    for _ in range(RETRIES):
        stored, rev = _stored()
        merged = merge(stored, clean)
        if merged == stored and rev != store.NO_FILE_REV:
            return {"state": stored, "rev": rev, "changed": False}
        try:
            r = store.set(NAME, merged, rev)
        except store.Conflict:
            continue  # somebody saved between the read and the write: merge over theirs
        return {"state": merged, "rev": r["rev"], "changed": r["changed"]}
    raise ApiError("conflict", M("workstate_busy"))


def _get_op(args, ctx):
    return get()


def _set_op(args, ctx):
    try:
        return update(args["state"])
    except Invalid as e:
        raise ApiError("invalid_args", M("workstate_invalid", field=e.field), field=e.field)
    except store.SettingsError as e:
        raise ApiError("invalid_args", str(e), field="state")


def ops():
    return [
        Op("workstate.get", _get_op, READ, {},
           "Reads the work state shared by every screen: per zone the Prepare steps done and the focus applied, and the focus height. "
           "Returns {state, rev}; state is empty when nothing was saved yet.", log=False),
        Op("workstate.set", _set_op, WRITE,
           {"state": Arg("obj", True, desc="Part of the work state to record: {v: 1, zones: {\"<zone>\": {prepare: {measure: ts, border: ts}, "
                                           "applied: {z, ts}}}, focus_h: {h, base, ts}}. ts is epoch milliseconds (negative for a cleared "
                                           "mark). Unknown keys or wrong values refuse the whole call.")},
           "Records the work state (an operator may). It is merged into what is stored mark by mark and the newest time wins, so what "
           "did not change is not overwritten. Returns {state, rev, changed} with the merged state. Noted in the audit like any write."),
    ]
