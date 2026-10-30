"""
Piece bigger than the cutting area (2026-10-10: "I want an assistant for
pieces that are bigger than the cutting area, based on the camera, as
automatic as possible").

A laser G-code (live job) is cut in parts. Between parts the user moves the
piece by hand; before moving it the laser burns 3 small crosses that the
assistant places by itself (on the material, away from the design lines, on
the side of what is missing) and afterwards the camera (or the pointer) finds
them: with that it is known how far it moved and rotated.

Coordinates:
  design  those of the file, as they are (X/Y of the G0-G3 lines)
  bed     where the beam lands (= pointer position, as in Zones)
  machine bed + laser correction (G53)
Each part k has its T_k (design -> bed): rotation a + translation (tx, ty).
Part k cuts what of the design falls inside the cutting area with T_k and
did NOT fall inside in the earlier parts (with their T_j): a line that
crosses the edge is cut exactly at the edge, with no gaps or double passes.

What is copied from the file: power (S) and speed (F) of each line,
M42 (air), M98 airon/airoff, M106/M107. The travels are built here (S0).

"""
import paths
import json
import math
import os
import re

import gcode_plan
from messages import M

SD_ROOT = paths.SD
PREVIEW = "sys/workshop/data/big-part.json"  # drawing for the map (design coords)
TRAVEL_F = 6000
MAX_SEC = 600000
CROSS_MM = 5.0
_cache = {"path": None, "mtime": None, "data": None}


def path_sd(fname):
    f = str(fname)
    if len(f) > 2 and f[1] == ":":
        f = f[2:]
    return os.path.join(SD_ROOT, f.lstrip("/"))


# ---------------------------------------------------------------- lectura

def read_in(fname):
    """Events of the file: ("s", x0, y0, x1, y1, S, F) laser segment and
    ("c", text) command that is copied. Cached by the file's date."""
    route = path_sd(fname)
    mt = os.path.getmtime(route)
    if _cache["path"] == route and _cache["mtime"] == mt:
        return _cache["data"]
    ev = []
    x = y = 0.0
    rel = False
    unit = 1.0
    s = 0.0
    f = 1000.0
    m5 = False
    nseg = 0
    g53 = 0
    with open(route, "rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace")
            k = line.find(";")
            if k >= 0:
                line = line[:k]
            if not line.strip():
                continue
            up = line.strip().upper()
            ws = gcode_plan._words(line)
            gs = [round(v, 1) for c, v in ws if c == "G"]
            ms = [int(v) for c, v in ws if c == "M"]
            d = {c: v for c, v in ws if c not in ("G", "M")}
            for m in ms:
                if m in (3, 4):
                    m5 = False
                    if "S" in d:
                        s = d["S"]
                elif m == 5:
                    m5 = True
                elif m == 42 or m in (106, 107):
                    ev.append(("c", up))
                elif m == 98 and re.search(r"AIR(ON|OFF)", up):
                    ev.append(("c", line.strip()))
            if ms:
                continue
            mov = None
            for g in gs:
                if g in (0, 1, 2, 3):
                    mov = int(g)
                elif g == 90:
                    rel = False
                elif g == 91:
                    rel = True
                elif g == 20:
                    unit = 25.4
                elif g == 21:
                    unit = 1.0
                elif g == 53:
                    g53 += 1
            if "F" in d:
                f = d["F"] * unit
            if "S" in d:
                s = d["S"]
            if mov is None:
                continue
            nx = (x + d["X"] * unit if rel else d["X"] * unit) if "X" in d else x
            ny = (y + d["Y"] * unit if rel else d["Y"] * unit) if "Y" in d else y
            if mov != 0 and s > 0 and not m5:
                if mov in (2, 3) and ("I" in d or "J" in d or "R" in d):
                    pts = gcode_plan._arc({"X": x, "Y": y}, {"X": nx, "Y": ny}, d, mov == 2, unit)
                else:
                    pts = [(nx, ny)]
                px, py = x, y
                for (qx, qy) in pts:
                    if qx != px or qy != py:
                        ev.append(("s", px, py, qx, qy, s, f))
                        nseg += 1
                    px, py = qx, qy
                if nseg > MAX_SEC:
                    raise ValueError(M("big_piece_file_too_big_more_than_segments", MAX_SEC=int(MAX_SEC)))
            x, y = nx, ny
    if g53:
        raise ValueError(M("big_piece_file_uses_g53_machine_coordinates_export"))
    secs = [e for e in ev if e[0] == "s"]
    if not secs:
        raise ValueError(M("big_piece_file_has_no_lines_laser"))
    xs = [e[1] for e in secs] + [e[3] for e in secs]
    ys = [e[2] for e in secs] + [e[4] for e in secs]
    smax = max(e[5] for e in secs)
    payload = {"ev": ev, "bbox": [min(xs), min(ys), max(xs), max(ys)], "smax": smax,
             "length": sum(math.hypot(e[3] - e[1], e[4] - e[2]) for e in secs), "n": len(secs)}
    _cache.update(path=route, mtime=mt, data=payload)
    return payload


def preview(fname, write_out=True):
    """Summary + drawing (polylines in design coords) for the page."""
    d = read_in(fname)
    lines, cur = [], None
    for e in d["ev"]:
        if e[0] != "s":
            continue
        if cur is not None and abs(cur[-2] - e[1]) < 1e-6 and abs(cur[-1] - e[2]) < 1e-6:
            cur += [round(e[3], 2), round(e[4], 2)]
        else:
            cur = [round(e[1], 2), round(e[2], 2), round(e[3], 2), round(e[4], 2)]
            lines.append(cur)
    out = {"file": fname, "bbox": [round(v, 2) for v in d["bbox"]], "length": round(d["length"], 1), "segments": d["n"],
           "pct_max": round(d["smax"] / 2.55, 1), "lines": lines}
    if write_out:
        p = path_sd(PREVIEW)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(out, fh, separators=(",", ":"))
    return {k: v for k, v in out.items() if k != "lines"}


# ---------------------------------------------------------------- geometria

def _T(t):
    a = math.radians(float(t.get("rotation", 0)))
    return math.cos(a), math.sin(a), float(t.get("tx", 0)), float(t.get("ty", 0))


def apply(t, x, y):
    c, s, tx, ty = _T(t)
    return c * x - s * y + tx, s * x + c * y + ty


def inverse(t, x, y):
    c, s, tx, ty = _T(t)
    x, y = x - tx, y - ty
    return c * x + s * y, -s * x + c * y


def region(t, area, margin=0.0):
    """The cutting area (bed) seen in design coords: convex counterclockwise
    quadrilateral."""
    x0, x1, y0, y1 = area["xmin"] + margin, area["xmax"] - margin, area["ymin"] + margin, area["ymax"] - margin
    return [inverse(t, x0, y0), inverse(t, x1, y0), inverse(t, x1, y1), inverse(t, x0, y1)]


def _inside_t(poly, ax, ay, bx, by):
    """Interval [t0, t1] of the segment inside the convex polygon (Cyrus-Beck)."""
    t0, t1 = 0.0, 1.0
    dx, dy = bx - ax, by - ay
    n = len(poly)
    for i in range(n):
        px, py = poly[i]
        qx, qy = poly[(i + 1) % n]
        ex, ey = qx - px, qy - py
        nx, ny = ey, -ex  # normal hacia afuera (poligono antihorario)
        num = nx * (ax - px) + ny * (ay - py)
        den = nx * dx + ny * dy
        if abs(den) < 1e-12:
            if num > 0:
                return None
            continue
        t = -num / den
        if den > 0:
            t1 = min(t1, t)
        else:
            t0 = max(t0, t)
        if t0 >= t1:
            return None
    return (t0, t1)


def _subtract(iv, drop):
    out = [iv]
    for q in drop:
        new = []
        for a, b in out:
            if q[1] <= a or q[0] >= b:
                new.append((a, b))
                continue
            if q[0] > a:
                new.append((a, q[0]))
            if q[1] < b:
                new.append((q[1], b))
        out = new
    return [(a, b) for a, b in out if b - a > 1e-9]


def parts_of(e, current, previous):
    """Pieces [(t0, t1)] of segment e that the current part cuts."""
    iv = _inside_t(current, e[1], e[2], e[3], e[4])
    if iv is None:
        return []
    drop = [q for q in (_inside_t(p, e[1], e[2], e[3], e[4]) for p in previous) if q]
    return _subtract(iv, drop)


def _pt(e, t):
    return e[1] + (e[3] - e[1]) * t, e[2] + (e[4] - e[2]) * t


def counts(fname, t, area, done):
    """Length this part cuts and what remains afterwards (without generating anything)."""
    d = read_in(fname)
    act = region(t, area)
    prev = [region(h, area) for h in done]
    this = missing = 0.0
    box = None
    for e in d["ev"]:
        if e[0] != "s":
            continue
        L = math.hypot(e[3] - e[1], e[4] - e[2])
        done_items = [q for q in (_inside_t(p, e[1], e[2], e[3], e[4]) for p in prev + [act]) if q]
        for a, b in parts_of(e, act, prev):
            this += L * (b - a)
        for a, b in _subtract((0.0, 1.0), done_items):
            missing += L * (b - a)
            for tt in (a, b):
                x, y = _pt(e, tt)
                box = [x, y, x, y] if box is None else [min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
    return {"this_mm": round(this, 1), "missing_mm": round(missing, 1), "missing_box": [round(v, 2) for v in box] if box else None}


# ---------------------------------------------------------------- trabajos

def _header(title, pct):
    return ("; Workshop - %s, generated by WorkshopService (big_piece.py) %s\n" % (title, __import__("time").strftime("%Y-%m-%d %H:%M:%S")) +
            'M98 P"0:/sys/workshop/macros/cutguard.g" S%s   ; aborts and cancels the job if anything is not right\n' % max(1, min(100, int(math.ceil(pct)))) +
            "G90\n")


def generate_part(fname, t, area, done, correction, destination, n):
    """G-code of part n (G53, machine coords) -> destination. Returns counts."""
    d = read_in(fname)
    act = region(t, area)
    prev = [region(h, area) for h in done]
    cx, cy = float(correction[0]), float(correction[1])
    lines = []
    pos = None
    length = 0.0
    smax = 0.0
    for e in d["ev"]:
        if e[0] == "c":
            lines.append(e[1])
            continue
        for a, b in parts_of(e, act, prev):
            x0, y0 = apply(t, *_pt(e, a))
            x1, y1 = apply(t, *_pt(e, b))
            x0, y0, x1, y1 = x0 + cx, y0 + cy, x1 + cx, y1 + cy
            if pos is None or math.hypot(pos[0] - x0, pos[1] - y0) > 0.005:
                lines.append("G53 G1 X%.3f Y%.3f F%d S0" % (x0, y0, TRAVEL_F))
            lines.append("G53 G1 X%.3f Y%.3f F%d S%.1f" % (x1, y1, round(e[6]), e[5]))
            pos = (x1, y1)
            length += math.hypot(x1 - x0, y1 - y0)
            smax = max(smax, e[5])
    if length <= 0:
        return {"ok": False, "error": M("big_piece_part_has_nothing_cut_inside_cut")}
    turn = float(t.get("rotation", 0))
    txt = _header("LARGE PART part %d of %s" % (n, os.path.basename(fname)), smax / 2.55)
    txt += "; design -> bed: rotation %.3f degrees, shift X%.3f Y%.3f; machine = bed + correction X%.3f Y%.3f\n" % (turn, t.get("tx", 0), t.get("ty", 0), cx, cy)
    txt += "\n".join(lines) + "\nM400\n"
    with open(path_sd(destination), "w", encoding="utf-8") as fh:
        fh.write(txt)
    return dict(counts(fname, t, area, done), ok=True, file=destination, cortado_mm=round(length, 1), pct_max=round(smax / 2.55, 1))


def _free(d, area_poly, bbox, margin_lines=6.0, step=4.0):
    """Candidate points (design coords) inside area_poly and the design,
    more than margin_lines away from any line and outside the closed
    contours (that falls off when cutting)."""
    secs = [e for e in d["ev"] if e[0] == "s"]
    cell = margin_lines
    grid = {}
    for e in secs:
        L = math.hypot(e[3] - e[1], e[4] - e[2])
        n = max(1, int(L / (cell * 0.5)))
        for i in range(n + 1):
            x, y = _pt(e, i / float(n))
            grid.setdefault((int(math.floor(x / cell)), int(math.floor(y / cell))), []).append((x, y))
    # closed contours: chains of consecutive segments that return to the start
    loops, cur = [], []
    for e in secs:
        if cur and abs(cur[-1][0] - e[1]) < 1e-3 and abs(cur[-1][1] - e[2]) < 1e-3:
            cur.append((e[3], e[4]))
        else:
            if len(cur) > 3 and math.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 0.05:
                loops.append(cur)
            cur = [(e[1], e[2]), (e[3], e[4])]
    if len(cur) > 3 and math.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 0.05:
        loops.append(cur)
    boxes = [(min(p[0] for p in l), min(p[1] for p in l), max(p[0] for p in l), max(p[1] for p in l)) for l in loops]

    def inside_loop(x, y):
        for l, c in zip(loops, boxes):
            if not (c[0] <= x <= c[2] and c[1] <= y <= c[3]):
                continue
            inside = False
            for i in range(len(l) - 1):
                (ax, ay), (bx, by) = l[i], l[i + 1]
                if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
                    inside = not inside
            if inside:
                return True
        return False

    def near(x, y):
        gx, gy = int(math.floor(x / cell)), int(math.floor(y / cell))
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for (px, py) in grid.get((gx + i, gy + j), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < margin_lines ** 2:
                        return True
        return False

    xs = [p[0] for p in area_poly]
    ys = [p[1] for p in area_poly]
    x0, x1 = max(min(xs), bbox[0] + 5), min(max(xs), bbox[2] - 5)
    y0, y1 = max(min(ys), bbox[1] + 5), min(max(ys), bbox[3] - 5)
    out = []
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            if _inside_t(area_poly, x, y, x + 1e-6, y) is not None and not near(x, y) and not inside_loop(x, y):
                out.append((x, y))
            x += step
        y += step
    return out


def choose_marks(fname, t, area, done, n=3):
    """Where to burn the crosses: on the material (inside the design), in what
    this part reaches, as close as possible to what is missing (after moving
    the piece they have to stay in view) and apart from each other."""
    d = read_in(fname)
    c = counts(fname, t, area, done)
    box = c["missing_box"]
    act_small = region(t, area, margin=8.0)  # away from the edge of the area
    cand = _free(d, act_small, d["bbox"])
    if len(cand) < n:
        return {"ok": False, "error": M("big_piece_there_no_free_place_marks_whole")}
    if box:
        # direction: from the center of what is cut now toward the center of what is missing
        reg = region(t, area)
        rcx, rcy = sum(p[0] for p in reg) / 4, sum(p[1] for p in reg) / 4
        fx, fy = (box[0] + box[2]) / 2 - rcx, (box[1] + box[3]) / 2 - rcy
        L = math.hypot(fx, fy) or 1.0
        ux, uy = fx / L, fy / L
    else:
        ux, uy = 1.0, 0.0
    proy = [(p[0] * ux + p[1] * uy, p) for p in cand]
    cap = max(q for q, _ in proy)
    band = [p for q, p in proy if q >= cap - 60]
    # apart: the first at one end of the strip, the second at the other,
    # the third the farthest from both (in the middle, it breaks the symmetry)
    vx, vy = -uy, ux
    band.sort(key=lambda p: p[0] * vx + p[1] * vy)
    chosen = [band[0], band[-1]]
    if n > 2:
        rest = [p for p in band if p not in chosen] or [p for _, p in proy if p not in chosen]
        if rest:
            chosen.append(max(rest, key=lambda p: min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in chosen)))
    if math.hypot(chosen[0][0] - chosen[1][0], chosen[0][1] - chosen[1][1]) < 40:
        # short strip: the most separated ones of everything free are taken
        chosen = [min(cand, key=lambda p: p[0] * vx + p[1] * vy), max(cand, key=lambda p: p[0] * vx + p[1] * vy)]
        if n > 2:
            chosen.append(max(cand, key=lambda p: min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in chosen)))
    return {"ok": True, "marks": [[round(p[0], 3), round(p[1], 3)] for p in chosen]}


def generate_marks(marks, t, correction, pct, velocity, destination):
    """Job that burns a cross at each mark (design coords)."""
    cx, cy = float(correction[0]), float(correction[1])
    h = CROSS_MM / 2
    S = pct * 2.55
    txt = _header("LARGE PART registration marks (%d crosses of %g mm)" % (len(marks), CROSS_MM), pct)
    for (mx, my) in marks:
        bx, by = apply(t, mx, my)
        x, y = bx + cx, by + cy
        txt += "; mark in the design X%.3f Y%.3f -> bed X%.3f Y%.3f\n" % (mx, my, bx, by)
        txt += "G53 G1 X%.3f Y%.3f F%d S0\nG53 G1 X%.3f Y%.3f F%d S%.1f\n" % (x - h, y, TRAVEL_F, x + h, y, velocity, S)
        txt += "G53 G1 X%.3f Y%.3f F%d S0\nG53 G1 X%.3f Y%.3f F%d S%.1f\n" % (x, y - h, TRAVEL_F, x, y + h, velocity, S)
    txt += "M400\n"
    with open(path_sd(destination), "w", encoding="utf-8") as fh:
        fh.write(txt)
    return {"ok": True, "file": destination, "bed": [[round(v, 3) for v in apply(t, *m)] for m in marks]}


def adjust(design, bed):
    """Rotation + translation (no scale) that takes the design marks to where they
    were measured on the bed (least squares). Returns T and the error of each."""
    n = len(design)
    if n < 2 or n != len(bed):
        raise ValueError(M("big_piece_at_least_2_measured_marks_needed"))
    dx = sum(p[0] for p in design) / n
    dy = sum(p[1] for p in design) / n
    mx = sum(p[0] for p in bed) / n
    my = sum(p[1] for p in bed) / n
    sxx = sxy = 0.0
    for (ax, ay), (bx, by) in zip(design, bed):
        ax, ay, bx, by = ax - dx, ay - dy, bx - mx, by - my
        sxx += ax * bx + ay * by
        sxy += ax * by - ay * bx
    a = math.atan2(sxy, sxx)
    c, s = math.cos(a), math.sin(a)
    t = {"rotation": math.degrees(a), "tx": mx - (c * dx - s * dy), "ty": my - (s * dx + c * dy)}
    errs = []
    for p, q in zip(design, bed):
        x, y = apply(t, *p)
        errs.append(round(math.hypot(x - q[0], y - q[1]), 3))
    t = {k: round(v, 4) for k, v in t.items()}
    return {"T": t, "errors": errs, "error_max": max(errs)}
