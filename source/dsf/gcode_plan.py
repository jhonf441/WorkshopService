"""
PLANNED path of a file job (2026-10-10: "when it records a job in progress in work zones the shapes do not come out well built").

job_trace.py samples the machine position (today once per second): between
samples the head travels several mm, so circles came out as polygons,
corners cut and the laser start/end shifted. For a FILE job the G-code is read
and the exact path is built (G0/G1 lines and G2/G3 arcs), in MACHINE coordinates
(the same as the samples), each vertex with its position in the file: the page
draws done / remaining by comparing with job.filePosition.

What it understands: G0-G3 (arcs with I/J or R), G90/G91, G53 (that line in
machine coords), G54..G59.3 (offsets of the object model), G20/G21, G92,
M82/M83 (extrusion), M3/M4/M5 (spindle / laser) and persistent S (as a
live job). What happens inside macros (M98) is not seen: the samples
cover that.

Output (list of runs; a run = same type, power and layer):
    {"w": 1|0 work or travel, "v": power 0..1 (laser) | Z (CNC),
     "c": layer (FFF), "f": [file position of each vertex],
     "p": [x0, y0, x1, y1, ...]}
The first vertex of a run is the last of the previous one.

"""
import math
import re

MAX_VERTICES = 400000  # more than this: it is simplified (huge job)
ARC_MM = 0.5  # length of each small piece when converting arcs

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_WCS = {"54": 0, "55": 1, "56": 2, "57": 3, "58": 4, "59": 5, "59.1": 6, "59.2": 7, "59.3": 8}


def _words(line):
    out = []
    for m in _WORD.finditer(line):
        try:
            out.append((m.group(1).upper(), float(m.group(2))))
        except ValueError:
            pass
    return out


class _Run:
    __slots__ = ("w", "v", "c", "f", "p", "t", "fd")

    def __init__(self, w, v, c, x, y, fpos, t=0.0, fd=0.0):
        self.w, self.v, self.c = w, v, c
        self.fd = fd  # feed (mm/min) of a work run, only when the stats are asked for (laser layers: power + feed)
        self.f = [fpos]
        self.p = [x, y]
        self.t = [t]  # seconds since the start of the job at each vertex (only sent when stats are asked for)


def offset_tool(om):
    """{X, Y, Z}: machine position minus user position minus the offset of the active zone = what the tool adds.
    Only valid while the machine is NOT moving: while it moves the machine and user positions come from different
    moments and differ by several mm (measured 2026-10-16: Y changed 7 mm in 3 s), which shifted the whole toolpath."""
    mv = (om or {}).get("move") or {}
    n = int(mv.get("workplaceNumber") or 0)
    out = {}
    for a in mv.get("axes") or []:
        a = a or {}
        L = a.get("letter")
        if L not in ("X", "Y", "Z"):
            continue
        o = a.get("workplaceOffsets") or []
        w = float(o[n]) if n < len(o) and o[n] is not None else 0.0
        out[L] = float(a.get("machinePosition") or 0) - float(a.get("userPosition") or 0) - w
    return out


def arm(path, kind, om, smax=255.0, stats=None, rapid=6000.0, tool0=None, wcs0=None):
    """Path of the file `path`. `om` = object model at the start of the
    job (to go from zone coords to machine coords).
    `stats` (a dict, optional): it is filled with the numbers of the job (time estimated from the feed of each move,
    distances, feed range...) and every vertex gets its time ("t" in each run); `rapid` = mm/min of the G0 moves."""
    mv = (om or {}).get("move") or {}
    axes = {a.get("letter"): a for a in (mv.get("axes") or []) if a}
    wcs_n = int(mv.get("workplaceNumber") or 0)
    if wcs0 is not None:
        wcs_n = int(wcs0)  # the zone the job started in (a rebuild in the middle of the job reads the zone of that moment)

    def wp(letter, n):
        a = axes.get(letter) or {}
        o = a.get("workplaceOffsets") or []
        return float(o[n]) if n < len(o) and o[n] is not None else 0.0

    # machine - user includes zone + tool; the tool part is
    # kept when changing zone.
    tool = {}
    pos = {}
    for L in "XYZ":
        a = axes.get(L) or {}
        mp, up = float(a.get("machinePosition") or 0), float(a.get("userPosition") or 0)
        tool[L] = (mp - up) - wp(L, int(mv.get("workplaceNumber") or 0))
        if tool0 and L in tool0:
            tool[L] = tool0[L]  # taken while the machine was still: not skewed by the movement
        pos[L] = mp  # current position in MACHINE coords

    def off(L, n):
        return wp(L, n) + tool[L]

    rel = False
    rel_e = False
    mm_unit = 1.0
    s = 0.0  # S persistente
    spindle = False
    e_abs = 0.0
    layer, z_layer = 0, None
    runs = []
    cur = None
    nvert = 0
    feed = 1000.0  # mm/min of the last F (G1/G2/G3)
    clock = [0.0]  # seconds since the start
    if stats is not None:
        stats.update(time_s=0.0, dist_cut=0.0, dist_travel=0.0, f_min=None, f_max=None, pieces=0, layers=0,
                     z_min=None, z_max=None, v_min=None, v_max=None)

    def add(x, y, z, w, v, fpos, dt=0.0, fd=0.0):
        nonlocal cur, nvert
        v = round(v, 2)
        clock[0] += dt
        fd = round(fd) if (stats is not None and w) else 0
        if cur is None or cur.w != w or cur.v != v or cur.c != layer or cur.fd != fd:
            px, py = (cur.p[-2], cur.p[-1]) if cur is not None else (pos["X"], pos["Y"])
            cur = _Run(w, v, layer, round(px, 2), round(py, 2), fpos, clock[0] - dt, fd)
            runs.append(cur)
            nvert += 1
        cur.p.append(round(x, 2))
        cur.p.append(round(y, 2))
        cur.f.append(fpos)
        cur.t.append(round(clock[0], 2))
        nvert += 1

    fpos = 0
    with open(path, "rb") as fh:
        for raw in fh:
            line_pos = fpos
            fpos += len(raw)
            line = raw.decode("utf-8", "replace")
            k = line.find(";")
            if k >= 0:
                line = line[:k]
            line = line.split("(")[0] if "(" in line and not line.lstrip().upper().startswith("M") else line
            if not line.strip():
                continue
            ws = _words(line)
            if not ws:
                continue
            gs = [v for c, v in ws if c == "G"]
            ms = [v for c, v in ws if c == "M"]
            d = {c: v for c, v in ws if c not in ("G", "M")}
            g53 = False
            mov = None
            for g in gs:
                gi = round(g, 1)
                if gi in (0, 1, 2, 3):
                    mov = int(gi)
                elif gi == 90:
                    rel = False
                elif gi == 91:
                    rel = True
                elif gi == 20:
                    mm_unit = 25.4
                elif gi == 21:
                    mm_unit = 1.0
                elif gi == 53:
                    g53 = True
                elif 54 <= gi <= 59.3:
                    key = ("%g" % gi)
                    if key in _WCS:
                        wcs_n = _WCS[key]
                elif gi == 92:
                    if "E" in d:
                        e_abs = d["E"]
            for m in ms:
                mi = int(m)
                if mi in (3, 4):
                    spindle = True
                    if "S" in d:
                        s = d["S"]
                elif mi == 5:
                    spindle = False
                elif mi == 82:
                    rel_e = False
                elif mi == 83:
                    rel_e = True
            if ms or (gs and 92 in [round(g) for g in gs]):
                continue
            if mov is None:
                continue
            if "S" in d:
                s = d["S"]
            if "F" in d and d["F"] > 0:
                feed = d["F"] * mm_unit
            tgt = dict(pos)
            for L in "XYZ":
                if L in d:
                    val = d[L] * mm_unit
                    if rel:
                        tgt[L] = pos[L] + val
                    elif g53:
                        tgt[L] = val
                    else:
                        tgt[L] = val + off(L, wcs_n)
            # extrusion (FFF)
            extrudes = False
            if "E" in d:
                if rel_e:
                    extrudes = d["E"] > 0.0001
                else:
                    extrudes = d["E"] - e_abs > 0.0001
                    e_abs = d["E"]
            if kind == "FFF":
                if extrudes and (z_layer is None or tgt["Z"] > z_layer + 0.01):
                    layer += 1
                    z_layer = tgt["Z"]
                w = 1 if extrudes else 0
                v = 0.0
            elif kind == "CNC":
                w = 1 if spindle and tgt["Z"] < 0.2 else 0
                v = tgt["Z"] if w else 0.0
            else:
                pwm = min(1.0, max(0.0, s / smax)) if smax > 0 else 0.0
                w = 1 if mov != 0 and pwm > 0.001 else 0
                v = pwm if w else 0.0
            if mov in (2, 3) and ("I" in d or "J" in d or "R" in d):
                pts = _arc(pos, tgt, d, mov == 2, mm_unit)
            else:
                pts = [(tgt["X"], tgt["Y"])]
            if tgt["X"] != pos["X"] or tgt["Y"] != pos["Y"] or w:
                ax_, ay_ = pos["X"], pos["Y"]
                velocity = max(1.0, rapid if mov == 0 else feed)  # mm/min
                for (x, y) in pts:
                    length = math.hypot(x - ax_, y - ay_)
                    dt = length / velocity * 60.0
                    if stats is not None:
                        stats["time_s"] += dt
                        stats["dist_cut" if w else "dist_travel"] += length
                        if w and length > 0:
                            stats["f_min"] = velocity if stats["f_min"] is None else min(stats["f_min"], velocity)
                            stats["f_max"] = velocity if stats["f_max"] is None else max(stats["f_max"], velocity)
                    add(x, y, tgt["Z"], w, v, line_pos, dt, velocity)
                    ax_, ay_ = x, y
                if stats is not None and w:
                    for k_, val_ in (("z", tgt["Z"]), ("v", v)):
                        stats[k_ + "_min"] = val_ if stats[k_ + "_min"] is None else min(stats[k_ + "_min"], val_)
                        stats[k_ + "_max"] = val_ if stats[k_ + "_max"] is None else max(stats[k_ + "_max"], val_)
            pos = tgt
    plan = [{"w": r.w, "v": r.v, "c": r.c, "f": r.f, "p": r.p} for r in runs if len(r.f) > 1]
    if stats is not None:
        for r, d_ in zip([r for r in runs if len(r.f) > 1], plan):
            d_["t"] = r.t
            d_["fd"] = r.fd
        # pieces = groups of work runs separated by a travel longer than 1 mm
        pieces, previous = 0, None
        for r in plan:
            if r["w"]:
                if previous is None or previous != "w":
                    pieces += 1
            previous = "w" if r["w"] else "t"
        stats["pieces"] = pieces
        stats["layers"] = max([r["c"] for r in plan] or [0])
        stats["time_s"] = round(stats["time_s"], 1)
        stats["dist_cut"] = round(stats["dist_cut"], 1)
        stats["dist_travel"] = round(stats["dist_travel"], 1)
    if nvert > MAX_VERTICES:
        plan = _simplify(plan, nvert)
    return plan


def _arc(a, b, d, cw, unit):
    x0, y0, x1, y1 = a["X"], a["Y"], b["X"], b["Y"]
    if "R" in d and "I" not in d and "J" not in d:
        r = d["R"] * unit
        dx, dy = x1 - x0, y1 - y0
        q = math.hypot(dx, dy)
        if q == 0 or abs(r) < q / 2:
            return [(x1, y1)]
        h = math.sqrt(max(0.0, r * r - q * q / 4))
        sgn = (-1 if cw else 1) * (1 if r > 0 else -1)
        cx = (x0 + x1) / 2 - sgn * h * dy / q
        cy = (y0 + y1) / 2 + sgn * h * dx / q
    else:
        cx, cy = x0 + d.get("I", 0) * unit, y0 + d.get("J", 0) * unit
    r = math.hypot(x0 - cx, y0 - cy)
    t0 = math.atan2(y0 - cy, x0 - cx)
    t1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        if t1 >= t0:
            t1 -= 2 * math.pi
    else:
        if t1 <= t0:
            t1 += 2 * math.pi
    n = max(2, min(720, int(abs(t1 - t0) * r / ARC_MM)))
    pts = [(cx + r * math.cos(t0 + (t1 - t0) * i / n), cy + r * math.sin(t0 + (t1 - t0) * i / n)) for i in range(1, n)]
    pts.append((x1, y1))
    return pts


def _simplify(plan, nvert):
    """Huge job: vertices are discarded until under MAX_VERTICES
    (the first and the last of each run stay)."""
    step = int(math.ceil(nvert / float(MAX_VERTICES)))
    for r in plan:
        n = len(r["f"])
        if n <= 2:
            continue
        idx = list(range(0, n - 1, step)) + [n - 1]
        r["f"] = [r["f"][i] for i in idx]
        if "t" in r:
            r["t"] = [r["t"][i] for i in idx]
        r["p"] = [c for i in idx for c in (r["p"][2 * i], r["p"][2 * i + 1])]
    return plan
