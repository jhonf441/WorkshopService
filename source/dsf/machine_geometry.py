"""Pure geometry and decision rules of the Machine procedures (phase 1): reach of the probe, points of a levelling pass, the reading of bed.g,
the convergence / divergence rules of the old browser logic (46-level-logic*.js) and the descent limit. No I/O, no board: every function takes
the object model (a dict) or numbers, so it is tested without a connection.

Coordinates: a probe point (x, y) is where the PROBE touches; the head goes to (x - offset_x, y - offset_y) and has to stay inside M208.
"""
import math
import re

import config_scan

MAX_LEVEL_POINTS = 32
MIN_POINT_DISTANCE = 1.0


def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def rnd(v, d=3):
    return None if v is None else round(float(v), d)


# ---- object model ----

def axes_by_letter(om):
    out = {}
    for a in ((om or {}).get("move") or {}).get("axes") or []:
        if isinstance(a, dict) and a.get("letter") and a["letter"] not in out:
            out[a["letter"]] = a
    return out


def probe_of(om, k):
    probes = ((om or {}).get("sensors") or {}).get("probes") or []
    p = probes[k] if isinstance(k, int) and 0 <= k < len(probes) else None
    return p if isinstance(p, dict) and p.get("type") not in (None, 0) else None


def first_probe_index(om):
    for i, p in enumerate(((om or {}).get("sensors") or {}).get("probes") or []):
        if isinstance(p, dict) and p.get("type") not in (None, 0):
            return i
    return None


def offsets_of(probe):
    o = (probe or {}).get("offsets") or []
    return (num(o[0]) or 0.0 if len(o) > 0 else 0.0, num(o[1]) or 0.0 if len(o) > 1 else 0.0)


def limits(om):
    """{"xmin","xmax","ymin","ymax","zmin","zmax"} of M208 from the model, or None when X or Y are unknown."""
    ax = axes_by_letter(om)
    out = {}
    for letter in "XYZ":
        a = ax.get(letter) or {}
        out[letter.lower() + "min"], out[letter.lower() + "max"] = num(a.get("min")), num(a.get("max"))
    if any(out[k] is None for k in ("xmin", "xmax", "ymin", "ymax")):
        return None
    return out


def tilt_of(om):
    """Leadscrews of M671 as the model reports them: {"x": [], "y": [], "s", "p", "f", "last"} or None."""
    tc = (((om or {}).get("move") or {}).get("kinematics") or {}).get("tiltCorrection")
    if not isinstance(tc, dict):
        return None
    xs, ys = tc.get("screwX"), tc.get("screwY")
    if not (isinstance(xs, list) and isinstance(ys, list) and len(xs) >= 2 and len(xs) == len(ys)):
        return None
    return {"x": [num(v) for v in xs], "y": [num(v) for v in ys], "s": num(tc.get("maxCorrection")), "p": num(tc.get("screwPitch")),
            "f": num(tc.get("correctionFactor")), "last": [num(v) for v in tc.get("lastCorrections") or []]}


def z_position(om):
    return num((axes_by_letter(om).get("Z") or {}).get("machinePosition"))


def axis_index(om, letter, default=2):
    """Position of an axis in move.axes (the model is searched by letter, nothing assumes Z is the third)."""
    for i, a in enumerate(((om or {}).get("move") or {}).get("axes") or []):
        if isinstance(a, dict) and a.get("letter") == letter:
            return i
    return default


# ---- reach and points ----

def reach(lim, offsets, margin=0.0):
    """Where the probe can touch: the head (point - offset) inside M208, and the point itself inside the travel (the idea of the bed there is)."""
    if not lim:
        return None
    ox, oy = offsets
    r = {"xmin": max(lim["xmin"] + ox, lim["xmin"]) + margin, "xmax": min(lim["xmax"] + ox, lim["xmax"]) - margin,
         "ymin": max(lim["ymin"] + oy, lim["ymin"]) + margin, "ymax": min(lim["ymax"] + oy, lim["ymax"]) - margin}
    return None if r["xmin"] > r["xmax"] or r["ymin"] > r["ymax"] else r


def head_of(point, offsets):
    return (point[0] - offsets[0], point[1] - offsets[1])


def head_inside(point, lim, offsets, eps=0.001):
    hx, hy = head_of(point, offsets)
    return lim["xmin"] - eps <= hx <= lim["xmax"] + eps and lim["ymin"] - eps <= hy <= lim["ymax"] + eps


def validate_points(points, om, k, leadscrews=0, max_points=MAX_LEVEL_POINTS):
    """[] when the points can be probed; else [{"code", "point"}]: no_points, too_many_points, too_few_points (fewer than leadscrews), no_limits,
    out_of_reach (the head would leave M208), duplicate_point (closer than 1 mm to another)."""
    errors = []
    pts = list(points or [])
    if not pts:
        return [{"code": "no_points", "point": None}]
    if len(pts) > min(max_points, MAX_LEVEL_POINTS):
        errors.append({"code": "too_many_points", "point": None})
    if leadscrews and len(pts) < leadscrews:
        errors.append({"code": "too_few_points", "point": None})
    lim, probe = limits(om), probe_of(om, k)
    if lim is None:
        return errors + [{"code": "no_limits", "point": None}]
    off = offsets_of(probe)
    for i, p in enumerate(pts):
        if not head_inside((p["x"], p["y"]), lim, off):
            errors.append({"code": "out_of_reach", "point": i})
        for j in range(i):
            if abs(pts[j]["x"] - p["x"]) < MIN_POINT_DISTANCE and abs(pts[j]["y"] - p["y"]) < MIN_POINT_DISTANCE:
                errors.append({"code": "duplicate_point", "point": i})
    return errors


def suggest_points(om, k, margin=10.0):
    """One point per leadscrew, as close as possible and inside the reach (port of tnvSuggestPoints)."""
    tilt, lim = tilt_of(om), limits(om)
    if not tilt or not lim or None in tilt["x"] + tilt["y"]:
        return []
    area = reach(lim, offsets_of(probe_of(om, k)), margin)
    if not area:
        return []
    same_y = len(tilt["x"]) == 2 and abs(tilt["y"][0] - tilt["y"][1]) < 0.01
    mid = round((area["ymin"] + area["ymax"]) / 2, 1)
    clamp = lambda v, a, b: max(a, min(b, v))  # noqa: E731
    return [{"x": round(clamp(sx, area["xmin"], area["xmax"]), 1), "y": mid if same_y else round(clamp(tilt["y"][i], area["ymin"], area["ymax"]), 1)}
            for i, sx in enumerate(tilt["x"])]


def grid_region(om, k, margin=5.0, region=None):
    """The rectangle a mesh probes: the asked one, or the whole reach of the probe minus a margin. None when it is not possible;
    ("out_of_reach") when the asked one leaves the reach."""
    lim = limits(om)
    area = reach(lim, offsets_of(probe_of(om, k)), margin) if lim else None
    if not area:
        return None, "no_limits"
    if not region:
        return area, None
    eps = 0.001
    if region["x0"] >= region["x1"] or region["y0"] >= region["y1"]:
        return None, "bad_region"
    if region["x0"] < area["xmin"] - eps or region["x1"] > area["xmax"] + eps or region["y0"] < area["ymin"] - eps or region["y1"] > area["ymax"] + eps:
        return None, "out_of_reach"
    return {"xmin": region["x0"], "xmax": region["x1"], "ymin": region["y0"], "ymax": region["y1"]}, None


# ---- descent limit ----

def descent_bound(om, k, z=None, zmin=None):
    """Largest distance the head can go down in one G30 from where it is: from the current Z to the lowest point the firmware allows
    (M208 Z min minus the first dive height, plus the trigger height; GCODE-REFERENCE section 1). `z` / `zmin` replace the model's numbers
    (a fresh reading from the board). None when a number is missing."""
    probe = probe_of(om, k)
    z = z if z is not None else z_position(om)
    zmin = zmin if zmin is not None else num((axes_by_letter(om).get("Z") or {}).get("min"))
    if not probe or z is None or zmin is None:
        return None
    dives = probe.get("diveHeights")
    dive = num(dives[0]) if isinstance(dives, list) and dives else num(probe.get("diveHeight"))
    trig = num(probe.get("triggerHeight")) or 0.0
    if dive is None:
        return None
    floor = zmin - dive + trig
    return max(0.0, z - floor)


# ---- bed.g ----

_PARAM = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])\s*(\{[^{}]*\}|\"[^\"]*\"|[-+]?(?:\d+\.?\d*|\.\d+))")


def bed_points(text):
    """The first set of `G30 Pn ... ` lines of bed.g up to the one with S (like the old tnvReadBedG), without evaluating expressions:
    {"count", "points": [{"x","y"} or None], "k", "s", "closed", "readable"}. A line with a {expression} gives None for that coordinate."""
    pts, k, s, closed = [], 0, None, False
    for raw in str(text or "").splitlines():
        line = config_scan.strip_comment(raw)
        if not re.match(r"^G30\b", line, re.I):
            continue
        params = {m.group(1).upper(): m.group(2) for m in _PARAM.finditer(re.sub(r"^G30", "", line, flags=re.I))}
        if "P" not in params or closed:
            continue
        def val(key):
            v = params.get(key)
            try:
                return float(v) if v is not None and not v.startswith(("{", '"')) else None
            except ValueError:
                return None
        x, y = val("X"), val("Y")
        pts.append({"x": x, "y": y} if x is not None and y is not None else None)
        if "K" in params:
            try:
                k = int(float(params["K"]))
            except ValueError:
                pass
        if "S" in params:
            s, closed = val("S"), True
    return {"count": len(pts), "points": pts, "k": k, "s": s, "closed": closed, "readable": bool(pts) and all(pts)}


# ---- the rules of the pass loop (old browser logic) ----

def divergence(passes):
    """With 2 or more passes that moved the motors: the measured deviation GROWS (RRF docs: the leadscrews of M671 are probably in the
    wrong order). Port of tnvDivergence: last > first * 1.3 + 0.005."""
    ds = [p["before"]["deviation"] for p in passes if p.get("kind") == "setting" and (p.get("before") or {}).get("deviation") is not None]
    return len(ds) >= 2 and ds[-1] > ds[0] * 1.3 + 0.005


def decide(result, passes, n, max_passes, tolerance):
    """What to do after pass `n` gave `result` (a parse_g32 item): "converged", "diverging", "limit", "next", "manual", "measured",
    "exceeds", "failed". `passes` holds every result so far (this one included)."""
    kind = (result or {}).get("kind")
    if kind == "setting":
        dev = (result.get("before") or {}).get("deviation")
        if dev is not None and dev < tolerance:
            return "converged"
        if divergence(passes):
            return "diverging"
        return "limit" if n >= max_passes else "next"
    return {"manual": "manual", "heights": "measured", "exceeds": "exceeds"}.get(kind, "failed")


def spread(values):
    """Statistics of the measured heights (None for a point that could not be read): n, mean, deviation (root mean square about the mean,
    like the figure the firmware reports), range."""
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return {"n": 0, "mean": None, "deviation": None, "range": None}
    mean = sum(xs) / len(xs)
    return {"n": len(xs), "mean": rnd(mean, 4), "deviation": rnd(math.sqrt(sum((v - mean) ** 2 for v in xs) / len(xs)), 4),
            "range": rnd(max(xs) - min(xs), 4)}
