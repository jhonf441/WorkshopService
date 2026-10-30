"""Bed view data of Machine v2: `machine.layout` (operator, read only). Contract: docs/MACHINE-LAYOUT-CONTRACT.md.

The page draws the bed at its true size and needs to know, for the mesh and for the levelling: the axis limits, where the PROBE can be (the
head has to stay inside M208 and the probe point inside the travel), where the leadscrews of M671 are, which points of a grid / levelling pass
would be taken and which would not (and why), and the last measurements. Nothing here moves a motor or sends a line to the board: it reads the
object model, the configuration files, the machine profile, the mesh library and the calibration history.

The answer carries codes and numbers (reason keys); the plugin translates them. A datum the machine does not tell is None with a `*_reason`.
"""
import time

import capabilities
import config_scan
import machine_geometry as geo
import machine_heightmap as hm
import machine_level
import machine_mesh
import machine_probe
import machine_store
from messages import M
from workshop_api import ApiError, Arg, READ, Op

VERSION = 1
EPS = 0.001
DEFAULT_MESH_MARGIN = 5.0
DEFAULT_GRID = (5, 5)
LEVEL_KINDS = ("level.g32", "level.g30", "level.measure")


def _mo():
    import machine_ops
    return machine_ops


def _bad(field):
    return ApiError("invalid_args", M("machine_layout_bad_value", field=field), field=field, reason="bad_value")


# ---- the machine: kinematics, limits, probe, reach ----

def kinematics_of(om):
    k = ((om or {}).get("move") or {}).get("kinematics")
    name = k.get("name") if isinstance(k, dict) and k.get("name") else None
    return {"name": name, "supported": None if name is None else str(name).lower() in capabilities.SUPPORTED_KINEMATICS}


def box(a, b, c, d):
    return None if None in (a, b, c, d) else {"x_min": geo.rnd(a, 3), "x_max": geo.rnd(b, 3), "y_min": geo.rnd(c, 3), "y_max": geo.rnd(d, 3)}


def bed_of(lim):
    return (box(lim["xmin"], lim["xmax"], lim["ymin"], lim["ymax"]), None) if lim else (None, "no_limits")


def probe_block(om, k):
    probe = geo.probe_of(om, k) if k is not None else None
    if probe is None:
        return None, "no_probe"
    ox, oy = geo.offsets_of(probe)
    return {"index": k, "type": probe.get("type") if isinstance(probe.get("type"), int) else None, "offset_x": geo.rnd(ox), "offset_y": geo.rnd(oy),
            "offset_z": None, "trigger_height": geo.rnd(geo.num(probe.get("triggerHeight")))}, None


def reach_block(lim, probe, kin):
    """(reach dict or None, reason)."""
    if kin["supported"] is False:
        return None, "unsupported_kinematics"
    if not lim:
        return None, "no_limits"
    if probe is None:
        return None, "no_probe"
    r = geo.reach(lim, (probe["offset_x"], probe["offset_y"]))
    return (box(r["xmin"], r["xmax"], r["ymin"], r["ymax"]), None) if r else (None, "empty_reach")


# ---- leadscrews (M671) ----

def _z_drivers(mo):
    try:
        z = (((mo._caps() or {}).get("capabilities") or {}).get("z_motors")) or {}
    except Exception:  # noqa: BLE001
        return []
    return [d.get("raw") if isinstance(d, dict) else d for d in z.get("drivers") or []]


def _config_m671(read):
    """(xs, ys, reason) from the last M671 line of config.g and the macros it calls."""
    scan = config_scan.scan(read)
    if not scan["read"]:
        return None, None, "m671_unreadable"
    if not scan["m671"]:
        return None, None, "no_m671"
    vals = config_scan._values(scan["m671"][-1]["text"])  # noqa: SLF001 - the same parser the capabilities use
    xs, ys = vals.get("X"), vals.get("Y")
    if not xs or not ys or len(xs) != len(ys):
        return None, None, "m671_unreadable"
    return xs, ys, None


def leadscrews_block(om, mo):
    """(list, reason, source)."""
    tilt = geo.tilt_of(om)
    if tilt and None not in tilt["x"] + tilt["y"]:
        xs, ys, source = tilt["x"], tilt["y"], "model"
    else:
        xs, ys, why = _config_m671(mo.read_sd)
        if why:
            return [], why, None
        source = "config"
    motors = _z_drivers(mo)
    motors = motors if len(motors) == len(xs) else [None] * len(xs)
    return [{"index": i, "x": geo.rnd(x), "y": geo.rnd(y), "motor": motors[i]} for i, (x, y) in enumerate(zip(xs, ys))], None, source


# ---- classification of one point ----

def classify(x, y, lim, off, margin):
    """(status, reason) of a probe point. lim is the M208 box, off the probe offsets, margin the band kept from the edge of the reach."""
    if not (lim["xmin"] - EPS <= x <= lim["xmax"] + EPS and lim["ymin"] - EPS <= y <= lim["ymax"] + EPS):
        return "out_of_reach", "outside_bed"
    hx, hy = geo.head_of((x, y), off)
    bad_x = not lim["xmin"] - EPS <= hx <= lim["xmax"] + EPS
    bad_y = not lim["ymin"] - EPS <= hy <= lim["ymax"] + EPS
    if bad_x or bad_y:
        return "out_of_reach", "head_outside_" + ("xy" if bad_x and bad_y else "x" if bad_x else "y")
    if margin > 0:
        inner = geo.reach(lim, off, margin)
        if inner is None or not (inner["xmin"] - EPS <= x <= inner["xmax"] + EPS and inner["ymin"] - EPS <= y <= inner["ymax"] + EPS):
            return "clipped", "inside_margin"
    return "in", None


def _with(row, status, reason):
    row["status"] = status
    if reason:
        row["reason"] = reason
    return row


# ---- mesh ----

def _region_arg(args):
    keys = ("x0", "x1", "y0", "y1")
    given = [k for k in keys if args.get(k) is not None]
    if not given:
        return None
    if len(given) != 4:
        raise _bad("region")
    return {k: float(args[k]) for k in keys}


def _grid_of(args, prof):
    nx, ny = args.get("nx"), args.get("ny")
    for name, v in (("nx", nx), ("ny", ny)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 2 <= v <= 31):
            raise _bad(name)
    if nx is not None or ny is not None:
        d = (prof.get("mesh") or {}).get("default_points") or DEFAULT_GRID
        return nx or d[0], ny or d[1], "asked"
    d = (prof.get("mesh") or {}).get("default_points")
    return (d[0], d[1], "profile") if d else (DEFAULT_GRID[0], DEFAULT_GRID[1], "default")


def _clipped_region(req, area):
    """(region or None, reason): the requested region against the reach minus the margin (what mesh.probe would accept)."""
    if req is None or area is None:
        return None, "out_of_reach"
    if req["x0"] >= req["x1"] or req["y0"] >= req["y1"]:
        return None, "bad_region"
    x0, x1 = max(req["x0"], area["xmin"]), min(req["x1"], area["xmax"])
    y0, y1 = max(req["y0"], area["ymin"]), min(req["y1"], area["ymax"])
    if x0 >= x1 or y0 >= y1:
        return None, "out_of_reach"
    return {"x0": geo.rnd(x0, 3), "x1": geo.rnd(x1, 3), "y0": geo.rnd(y0, 3), "y1": geo.rnd(y1, 3)}, None


def mesh_block(args, om, lim, probe, prof, kin):
    margin = float(args["margin"]) if args.get("margin") is not None else DEFAULT_MESH_MARGIN
    region = _region_arg(args)
    nx, ny, gsrc = _grid_of(args, prof)
    ok = lim is not None and probe is not None and kin["supported"] is not False
    off = (probe["offset_x"], probe["offset_y"]) if probe else (0.0, 0.0)
    area = geo.reach(lim, off, margin) if ok else None
    if region is None and area:
        requested, source = {"x0": area["xmin"], "x1": area["xmax"], "y0": area["ymin"], "y1": area["ymax"]}, "default"
    else:
        requested, source = region, "asked"
    why = "unsupported_kinematics" if kin["supported"] is False else "no_limits" if lim is None else "no_probe"
    clipped, clipped_reason = _clipped_region(requested, area) if ok else (None, why)
    points, spacing = [], None
    if requested and requested["x0"] < requested["x1"] and requested["y0"] < requested["y1"]:
        dx, dy = (requested["x1"] - requested["x0"]) / (nx - 1), (requested["y1"] - requested["y0"]) / (ny - 1)
        spacing = {"x": geo.rnd(dx), "y": geo.rnd(dy)}
        for j in range(ny):
            for i in range(nx):
                x, y = requested["x0"] + i * dx, requested["y0"] + j * dy
                row = {"i": i, "j": j, "x": geo.rnd(x), "y": geo.rnd(y)}
                _with(row, *(classify(x, y, lim, off, margin) if ok else (None, why)))
                points.append(row)
    counts = {"in": 0, "out_of_reach": 0, "clipped": 0, "unknown": 0}
    for p in points:
        counts[p["status"] or "unknown"] += 1
    limit = min((prof.get("safety") or {}).get("max_points_per_run", 100), machine_mesh.MAX_FIRMWARE_POINTS)
    return {"region_source": source, "requested_region": None if requested is None else {k: geo.rnd(v, 3) for k, v in requested.items()},
            "margin": margin, "grid": {"nx": nx, "ny": ny, "total": nx * ny, "source": gsrc}, "spacing": spacing, "points": points,
            "counts": counts, "clipped_region": clipped, "clipped_reason": clipped_reason, "too_many_points": nx * ny > limit,
            "estimated_seconds": None, "estimate_reason": "no_estimate"}


# ---- level ----

def _points_arg(args):
    pts = args.get("points")
    if pts is None:
        return None
    if not isinstance(pts, list) or not 1 <= len(pts) <= geo.MAX_LEVEL_POINTS:
        raise _bad("points")
    out = []
    for p in pts:
        ok = isinstance(p, dict) and set(p) == {"x", "y"} and all(isinstance(p[k], (int, float)) and not isinstance(p[k], bool) and p[k] == p[k] for k in p)
        if not ok:
            raise _bad("points")
        out.append({"x": float(p["x"]), "y": float(p["y"])})
    return out


def _nearest(x, y, screws):
    best = None
    for s in screws:
        d = ((s["x"] - x) ** 2 + (s["y"] - y) ** 2) ** 0.5
        if best is None or d < best["distance"]:
            best = {"index": s["index"], "distance": geo.rnd(d, 2)}
    return best


def level_block(args, om, mo, lim, probe, prof, screws, kin):
    margin = float(args["margin"]) if args.get("margin") is not None else 0.0
    k = probe["index"] if probe else None
    params = {"points": _points_arg(args)}
    if k is not None:
        pts, source = machine_level.resolve_points(params, prof, om, k, mo.read_sd("0:/sys/bed.g"))
    else:       # without a probe nothing can be suggested (the reach is unknown): only the points that were given
        pts, source = (params["points"], "params") if params["points"] else ([], None)
    ok = lim is not None and probe is not None and kin["supported"] is not False
    off = (probe["offset_x"], probe["offset_y"]) if probe else (0.0, 0.0)
    why = "unsupported_kinematics" if kin["supported"] is False else "no_limits" if lim is None else "no_probe"
    rows = []
    for i, p in enumerate(pts):
        row = {"index": i, "x": geo.rnd(p["x"]), "y": geo.rnd(p["y"])}
        status, reason = classify(p["x"], p["y"], lim, off, margin) if ok else (None, why)
        if status == "in" and any(abs(q["x"] - p["x"]) < geo.MIN_POINT_DISTANCE and abs(q["y"] - p["y"]) < geo.MIN_POINT_DISTANCE for q in pts[:i]):
            status, reason = "duplicate", "duplicate_point"
        _with(row, status, reason)
        row["near_leadscrew"] = _nearest(p["x"], p["y"], screws)
        rows.append(row)
    if probe is None:
        errors = [{"code": "no_probe", "point": None}]
    else:
        limit = (prof.get("safety") or {}).get("max_points_per_run", 100)
        errors = geo.validate_points(pts, om, k, leadscrews=len(screws), max_points=limit)
    bound = geo.descent_bound(om, k) if k is not None else None
    cap = (prof.get("safety") or {}).get("max_probe_descent_mm")
    return {"source": source, "suggested": source == "suggested", "margin": margin, "points": rows, "errors": errors, "leadscrew_count": len(screws),
            "descent": {"bound": geo.rnd(bound), "limit": geo.rnd(geo.num(cap)), "ok": None if bound is None or cap is None else bound <= cap}}


# ---- last measurements ----

def last_mesh():
    """(block or None, reason)."""
    for meta in hm.listing():
        if not meta.get("id"):
            continue
        text = hm.csv_of(meta["id"])
        parsed = hm.parse_csv(text) if text else {"ok": False}
        if not parsed["ok"]:
            continue
        g = parsed["grid"]
        pts = [{"i": i, "j": j, "x": geo.rnd(g["min0"] + i * g["spacing0"]), "y": geo.rnd(g["min1"] + j * g["spacing1"]), "z": z}
               for j, row in enumerate(parsed["rows"]) for i, z in enumerate(row)]
        st = meta.get("stats") or hm.stats(parsed)
        return {"id": meta["id"], "name": meta.get("name") or "", "ts": meta.get("created"), "user": meta.get("user") or "",
                "probe_index": (meta.get("probe") or {}).get("index"),
                "grid": {"nx": g["num0"], "ny": g["num1"], "min_x": g["min0"], "max_x": g["max0"], "min_y": g["min1"], "max_y": g["max1"]},
                "stats": {k: st.get(k) for k in ("probed", "unprobed", "min", "max", "range", "mean", "rms", "stdev", "light")}, "points": pts}, None
    return None, "no_mesh"


def _run_with_heights(mo):
    for r in mo.view(full=True)["runs"]:
        res = r.get("result") or {}
        if r.get("kind") in LEVEL_KINDS and r.get("state") in ("done", "partial") and (res.get("verified") or {}).get("heights"):
            return r
    return None


def _record_numbers(rec):
    res = rec.get("results") or {}
    ver = (res.get("verified") or {}).get("spread") or {}
    passes = res.get("passes") or []
    before = (passes[-1].get("before") or {}) if passes and isinstance(passes[-1], dict) else {}
    dev = ver.get("deviation") if ver.get("deviation") is not None else before.get("deviation")
    mean = ver.get("mean") if ver.get("deviation") is not None else before.get("mean")
    return res.get("outcome"), dev, mean


def last_level(mo):
    rec = next((r for r in machine_store.records(limit=machine_store.MAX_RECORDS) if r.get("kind") in LEVEL_KINDS), None)
    run = _run_with_heights(mo)
    if rec is None and run is None:
        return None, "no_level"
    out = {"ts": None, "user": "", "kind": None, "outcome": None, "record_id": None, "deviation": None, "mean": None, "points": None, "points_reason": "not_stored"}
    if rec:
        outcome, dev, mean = _record_numbers(rec)
        out.update(ts=rec.get("ts"), user=rec.get("user") or "", kind=rec["kind"], outcome=outcome, record_id=rec.get("id"), deviation=dev, mean=mean)
    if run and (rec is None or (run.get("record_id") == rec.get("id") or (run.get("finished") or 0) >= (rec.get("ts") or 0))):
        v = run["result"]["verified"]
        mean = (v.get("spread") or {}).get("mean")
        if mean is None:
            mean = sum(h["z"] for h in v["heights"]) / len(v["heights"])
        out.update(ts=run.get("finished") or out["ts"], user=run.get("user") or out["user"], kind=run["kind"], points_reason=None,
                   deviation=(v.get("spread") or {}).get("deviation", out["deviation"]), mean=mean,
                   points=[{"index": i, "x": h["x"], "y": h["y"], "z": h["z"], "deviation": geo.rnd(h["z"] - mean, 4)} for i, h in enumerate(v["heights"])])
    return out, None


# ---- the operation ----

def layout(args, mo):
    om, prof = mo.model(), mo.profile_block()
    kin = kinematics_of(om)
    lim = geo.limits(om)
    k = args.get("probe")
    if k is None:
        k = machine_mesh.mesh_probe_index({}, prof, om) if args["mode"] == "mesh" else machine_probe.probe_index({}, prof, om)
    probe, probe_reason = probe_block(om, k)
    bed, bed_reason = bed_of(lim)
    reach, reach_reason = reach_block(lim, probe, kin)
    screws, screws_reason, screws_source = leadscrews_block(om, mo)
    out = {"v": VERSION, "mode": args["mode"], "generated_at": int(time.time()), "kinematics": kin, "bed": bed, "bed_reason": bed_reason,
           "probe": probe, "probe_reason": probe_reason, "reach": reach, "reach_reason": reach_reason, "leadscrews": screws,
           "leadscrews_reason": screws_reason, "leadscrews_source": screws_source, "mesh": None, "level": None}
    if args["mode"] == "mesh":
        out["mesh"] = mesh_block(args, om, lim, probe, prof, kin)
    else:
        out["level"] = level_block(args, om, mo, lim, probe, prof, screws, kin)
    lm, lm_reason = last_mesh()
    ll, ll_reason = last_level(mo)
    out["last"] = {"mesh": lm, "mesh_reason": lm_reason, "level": ll, "level_reason": ll_reason}
    return out


def _layout_op(args, ctx):
    return layout(args, _mo())


def ops():
    N, I = "num", "int"
    a = Arg
    return [Op("machine.layout", _layout_op, READ, {
        "mode": a("str", True, choices=("mesh", "level"), desc="mesh or level: which block of the answer is filled."),
        "probe": a(I, min=0, max=15, desc="Probe index (default: the profile's, else the first real probe)."),
        "x0": a(N, min=-5000, max=5000, desc="Mesh region, probe coordinates (all four of x0 x1 y0 y1, or none)."),
        "x1": a(N, min=-5000, max=5000, desc="Mesh region, maximum X."), "y0": a(N, min=-5000, max=5000, desc="Mesh region, minimum Y."),
        "y1": a(N, min=-5000, max=5000, desc="Mesh region, maximum Y."),
        "nx": a(I, min=2, max=31, desc="Mesh grid points along X."), "ny": a(I, min=2, max=31, desc="Mesh grid points along Y."),
        "points": a("obj", desc="Level: explicit probe points [{x, y}] (default: the profile's, bed.g's, else one near each leadscrew)."),
        "margin": a(N, min=0, max=50, desc="Distance kept from the edge of the reach (default 5 for mesh, 0 for level)."),
    }, "Data for the bed view of the Mesh and Level pages, read only (nothing is sent to the board): the axis limits, the probe and its offsets, "
       "where the probe can reach, the leadscrews of M671, which mesh / levelling points would be taken and why one would not, and the last "
       "measurements. Reasons are codes (docs/MACHINE-LAYOUT-CONTRACT.md).", log=False)]
