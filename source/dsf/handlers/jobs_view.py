"""
Internal implementation of the API operation(s) jobs.preview (api_ops.py maps their named
arguments to the one-letter parameters below).

Reads a G-code file of 0:/gcodes WITHOUT running it and returns what the Work table needs to show it before deciding
anything (see it on the map, frame it, simulate it): the planned path (gcode_plan.py, in MACHINE coordinates of the
active work zone), the numbers of the job (estimated time from the feed of each move, distances, feed range, pieces,
layers, power or depth range), its bounding box and the convex hull of what it works on (to frame the outline).

    <params> F"<file under 0:/gcodes>" [N<max vertices>] [M"<mode>"]

The path is simplified to at most N vertices (default 30000) so the answer stays small; the numbers are exact.
Only one file is read at a time and nothing is kept in memory afterwards.
"""
import json
import os
import threading

import gcode_plan
import sd_paths

MAX_BYTES = 60 * 1024 * 1024  # a bigger file is refused (the Pi would be busy for minutes)
_lock = threading.Lock()


def _hull(points):
    """Convex hull (monotone chain) of [(x, y)]; returns the closed list of vertices without repeating the first."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    low = []
    for p in pts:
        while len(low) >= 2 and cross(low[-2], low[-1], p) <= 0:
            low.pop()
        low.append(p)
    height = []
    for p in reversed(pts):
        while len(height) >= 2 and cross(height[-2], height[-1], p) <= 0:
            height.pop()
        height.append(p)
    return [list(p) for p in low[:-1] + height[:-1]]


def _budget(plan, max_vertices):
    """Over the vertex budget after thinning each stretch (a file made of tens of thousands of tiny separate strokes keeps
    2 vertices per stroke, so thinning alone cannot get under the budget: a 4.4 MB engraving gave a 9 MB answer that
    took 40 s and left the Workbench on "Reading..."). Travel moves go first; then the SHORTEST strokes, so the outline
    stays. The order of what is kept does not change. The numbers of the job are computed before and are not touched."""
    total = sum(len(r["f"]) for r in plan)
    if total <= max_vertices:
        return plan
    job = [r for r in plan if r["w"]]
    if sum(len(r["f"]) for r in job) <= max_vertices:
        return job  # only the travel moves go
    def length(r):
        p = r["p"]
        return sum(abs(p[i] - p[i - 2]) + abs(p[i + 1] - p[i - 1]) for i in range(2, len(p), 2))
    order = sorted(range(len(job)), key=lambda i: length(job[i]), reverse=True)
    remaining = set()
    used = 0
    for i in order:
        n = len(job[i]["f"])
        if used + n > max_vertices:
            continue
        remaining.add(i)
        used += n
    return [r for i, r in enumerate(job) if i in remaining]


def summary(path, kind, om, max_vertices=30000):
    """The answer of the operation for a file on disk (separate from the handler so it can be tested)."""
    stats = {}
    om_min = {"move": (om or {}).get("move") or {}}
    axes = {a.get("letter"): a for a in ((om_min["move"].get("axes")) or []) if a}
    fast = [float((axes.get(L) or {}).get("speed") or 0) for L in "XY"]
    fast = min([r for r in fast if r > 0] or [6000.0])
    plan = gcode_plan.arm(path, kind, om_min, stats=stats, rapid=fast)
    job = []
    all_items = []
    for r in plan:
        p = r["p"]
        pairs = [(p[i], p[i + 1]) for i in range(0, len(p), 2)]
        all_items.extend(pairs)
        if r["w"]:
            job.extend(pairs)
    base = job or all_items
    box = None
    if base:
        xs = [q[0] for q in base]
        ys = [q[1] for q in base]
        box = {"xmin": min(xs), "xmax": max(xs), "ymin": min(ys), "ymax": max(ys)}
    n = sum(len(r["f"]) for r in plan)
    if n > max_vertices:
        plan = gcode_plan._simplify(plan, n / float(max_vertices) * gcode_plan.MAX_VERTICES)
    plan = _budget(plan, max_vertices)
    return {"ok": True, "mode": kind, "stats": stats, "bbox": box, "hull": _hull(base) if base else [],
            "segments": plan, "vertices": sum(len(r["f"]) for r in plan), "vertices_total": n,
            "fast_mm_min": fast}


def run(params, bridge, config):
    file = str(params.get("F", "")).strip().replace("\\", "/")
    parts = [x for x in file.split("/") if x]
    if not parts or any(x in (".", "..") for x in parts):
        return json.dumps({"ok": False, "error": "file needed (a path under 0:/gcodes)"})
    route = sd_paths.sd("0:/gcodes/" + "/".join(parts))
    if not os.path.isfile(route):
        return json.dumps({"ok": False, "error": "that file does not exist"})
    if os.path.getsize(route) > MAX_BYTES:
        return json.dumps({"ok": False, "error": "the file is too big to preview (more than 60 MB)"})
    try:
        nmax = max(2000, min(100000, int(params.get("N", 30000))))
    except (TypeError, ValueError):
        nmax = 30000
    om = {}
    try:
        import machine_state
        om = machine_state.get_status(timeout=2) or {}
    except Exception:
        om = {}
    kind = str(params.get("M", "")).strip() or str(((om.get("global") or {}).get("selectedMode")) or "Laser")
    if kind not in ("Laser", "CNC", "FFF"):
        kind = "Laser"
    if not _lock.acquire(blocking=False):
        return json.dumps({"ok": False, "error": "another preview is being read; try again in a few seconds"})
    try:
        r = summary(route, kind, om, nmax)
        r["file"] = "/".join(parts)
        r["bytes"] = os.path.getsize(route)
        return json.dumps(r)
    except Exception as e:
        return json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
    finally:
        _lock.release()
