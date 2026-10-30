"""Data of the printable reports of Machine v2 (phase 2, design 2.11): `machine.report`.

The service returns DATA; the plugin draws the page (tables, the colour map of the mesh and the level residual as inline SVG, signature line,
`@media print`). No server side PDF and no server SVG: the numbers are what the page needs to draw them.

machine.report {id}        the report of ONE calibration record (technician)
machine.report {full:true} the status report of the whole machine: the newest good record of every kind with its table, the limits, the
                           offsets, the mesh and level figures, a fresh safety check (read only)

Shape (both):
    {"schema": 1, "kind": "calibration" | "machine", "generated_at": epoch, "generated_by": user,
     "machine": {"name", "board", "firmware", "kinematics", "axes_fingerprint"}}
calibration adds:
    "record": {id, kind, ts, user, role, state, run_id, notes}, "tables": [{"id": "inputs" | "results", "rows": [{"key", "value"}]}],
    "applied": [{path, sha_before, sha_after, snapshot_id}] | null, "mesh": mesh figure | null, "level": level figure | null,
    "signature": {"person": user, "date": ts}
machine adds:
    "records": [{"record": {...}, "tables": [...], "mesh": ..., "level": ...} one per kind, newest good record],
    "limits": machine_limits.limits_view, "offsets": machine_offsets tables, "compensation": the active mesh (type, file, taper),
    "safety": machine_safety.evaluate(...), "signature": {"person", "date"}
mesh figure:   {"id", "axes", "grid", "rows" [[z or null]], "stats", "scale": {"min", "max", "symmetric": bool}}   (rows[j][i]: axis1 index j, axis0 index i)
level figure:  {"tolerance", "passes": [{"n", "before", "after"}], "residual": mm | null, "light": "ok" | "warn" | null}
"""
import audit
import identity
import machine_diff
import machine_heightmap as hm
import machine_store
from messages import M
from workshop_api import ApiError, Arg, READ, Op

MAX_TABLE_ROWS = 60
SKIP_KEYS = ("samples",)


def table(obj, ident):
    rows = [{"key": k, "value": v} for k, v in machine_diff.flatten(obj or {}).items() if not any(s in k for s in SKIP_KEYS)]
    return {"id": ident, "rows": rows[:MAX_TABLE_ROWS]}


def mesh_figure(rec):
    mid = (rec.get("results") or {}).get("mesh_id")
    text = hm.csv_of(mid) if mid else None
    parsed = hm.parse_csv(text) if text else None
    if not parsed or not parsed["ok"]:
        return None
    zs = [z for row in parsed["rows"] for z in row if z is not None]
    big = max([abs(z) for z in zs], default=0.0)
    return {"id": mid, "axes": parsed["axes"], "grid": parsed["grid"], "rows": parsed["rows"], "stats": hm.stats(parsed),
            "scale": {"min": -big, "max": big, "symmetric": True}}


def level_figure(rec):
    res = rec.get("results") or {}
    if not rec["kind"].startswith("level."):
        return None
    passes = [{"n": p.get("n"), "before": (p.get("before") or {}).get("deviation"), "after": (p.get("after") or {}).get("deviation")}
              for p in res.get("passes") or [] if isinstance(p, dict)]
    spread = (res.get("verified") or {}).get("spread") or {}
    residual = spread.get("deviation")
    if residual is None and passes:
        residual = passes[-1]["after"]
    tol = res.get("tolerance")
    return {"tolerance": tol, "passes": passes, "residual": residual,
            "light": None if residual is None or tol is None else "ok" if residual < tol else "warn"}


def record_part(rec):
    return {"record": {k: rec.get(k) for k in ("id", "kind", "ts", "user", "role", "state", "run_id", "notes")},
            "tables": [table(rec.get("inputs"), "inputs"), table(rec.get("results"), "results")],
            "mesh": mesh_figure(rec) if rec["kind"] == "mesh.probe" else None, "level": level_figure(rec)}


def _header(kind, who, now=None):
    import machine_ops as mo
    import machine_profile
    import time
    caps = mo._caps()
    fp = machine_store.fingerprint_of(caps)
    try:
        fp["name"] = str(machine_profile.load().get("name") or "")
    except Exception:  # noqa: BLE001 - a profile that cannot be read leaves the name empty
        pass
    return {"schema": 1, "kind": kind, "generated_at": int(now if now is not None else time.time()), "generated_by": who.get("user", ""), "machine": fp}


def calibration_report(rec_id, who, now=None):
    rec = machine_store.get_record(rec_id)
    if rec is None:
        raise ApiError("not_found", M("machine_history_not_found"), reason="not_found")
    out = dict(_header("calibration", who, now), applied=(rec.get("applied") or {}).get("files"), **record_part(rec))
    out["signature"] = {"person": rec.get("user", ""), "date": rec["ts"]}
    return out


def machine_report(who, now=None):
    import machine_limits
    import machine_offsets
    import machine_ops as mo
    import machine_safety
    om, caps = mo.model(), mo._caps()
    latest = {}
    for r in reversed(machine_store.query(limit=machine_store.MAX_RECORDS)[0]):          # oldest first: the newest wins
        if r["state"] in ("done", "partial") and r["kind"] not in ("offsets.snapshot", "safety.check"):
            latest[r["kind"]] = r
    out = dict(_header("machine", who, now))
    out["records"] = [record_part(latest[k]) for k in sorted(latest)]
    out["limits"] = machine_limits.limits_view(om, mo.read_sd)
    out["offsets"] = machine_offsets.snapshot_data(om, caps)
    comp = (((om or {}).get("move") or {}).get("compensation")) or {}
    out["compensation"] = {"type": comp.get("type") or "none", "file": comp.get("file"), "fade_height": comp.get("fadeHeight")}
    out["safety"] = machine_safety.evaluate(om, caps, machine_safety._interlock_rows(om), machine_safety._guard_state(), now)
    out["signature"] = {"person": who.get("user", ""), "date": out["generated_at"]}
    return out


def _report(args, ctx):
    who = identity.actor(ctx)
    if args.get("full"):
        out = machine_report(who)
    elif args.get("id"):
        out = calibration_report(args["id"], who)
    else:
        raise ApiError("invalid_args", M("machine_report_needs_id"), field="id", reason="needs_id")
    audit.event("machine.report", {"id": args.get("id") or "", "full": bool(args.get("full"))}, who)
    return out


def ops():
    a = Arg
    return [Op("machine.report", _report, READ, {"id": a("str", desc="Record id: the report of one calibration."),
                                                 "full": a("bool", desc="true: the status report of the whole machine.")},
               "The DATA of a printable report (the page draws it): one calibration (values, who, when, the mesh grid or the level residual) or "
               "the status of the whole machine (newest record of every kind, limits, offsets, active mesh and a fresh safety check).", log=False)]
