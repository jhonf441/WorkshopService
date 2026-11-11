"""What a G-code file IS and the 2D toolpath of the files that are not 3D prints (PURE: no I/O).

    Flat(tol, name)            one per parse; the parser feeds it every move, comment and M-code it reads
    Flat.decide(has_fff_layers) -> "fff" | "laser" | "cnc" | "travel" | "unknown"
    Flat.tags(kind, slicer)    short strings the UI shows as chips
    Flat.deliver(on_layer)     hands the 2D layers to the caller one by one, returns their infos (layer table)
    flat_summary(flat, kind, p) the summary of a non-fff file (lengths, power, feed, bbox, layers, time)

Kinds (decided from the content, never from the folder):
  fff      extruding moves (positive E with XY motion);
  laser    G1 moves that carry S power with no E, or a LightBurn / LaserGRBL / Inkscape header, or macros under /macros/laser/;
  cnc      spindle M3/M4 (or a .nc / .ngc / .tap file) plus G1 moves that change Z;
  travel   only G0/G1 without extrusion, power or spindle (test and utility files);
  unknown  nothing that moves.
2D layers: one per `;Layer Cxx` comment (LightBurn, the name is kept), for cnc one per cut depth, else one layer "all". Segment types:
cut (tool on), travel (G0 or tool off), plunge (cnc, Z going down). Everything is simplified while it is read (gcodelib_geo.PolyBuilder),
only the layers that are closed are kept (a laser job has a handful), and the geometry is capped so a huge file cannot fill the memory.
"""
import math
import os
import re

import gcodelib_geo as geo

CUT, TRAVEL, PLUNGE = 0, 1, 2
TYPE_NAMES = ("cut", "travel", "plunge")
KINDS = ("fff", "laser", "cnc", "travel", "unknown")
CNC_EXT = (".nc", ".ngc", ".tap")
MAX_LAYERS = 500
MAX_FLOATS = 4_000_000     # coordinates kept for the whole file (16 MB as float32)
MAX_POLY_POINTS = 100_000  # a longer run is cut in two polylines
EXTRUDE_MIN = 3            # extruding moves that make a file fff (and let the 2D collector go)
MAX_TAGS = 10
RAPID_MM_MIN = 3000.0     # estimate for a G0 without F (the real rapid depends on the machine limits)
_LAYER = re.compile(r"^layer\s+(\S+)", re.I)
_VERSION = re.compile(r"(\d+(?:\.\d+)+)")
_S = re.compile(rb"[Ss]\s*(-?\d*\.?\d+)")
_APPS = (("lightburn", "LightBurn", True), ("lasergrbl", "LaserGRBL", True), ("inkscape", "Inkscape", True),
         ("estlcam", "Estlcam", False), ("fusion", "Fusion 360", False), ("carbide create", "Carbide Create", False),
         ("pcb2gcode", "pcb2gcode", False), ("flatcam", "FlatCAM", False))


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def _grow(box, x, y):
    if box is None:
        return [x, y, x, y]
    if x < box[0]:
        box[0] = x
    elif x > box[2]:
        box[2] = x
    if y < box[1]:
        box[1] = y
    elif y > box[3]:
        box[3] = y
    return box


class Flat:
    def __init__(self, tol=0.05, name=None):
        self.tol = tol
        self.ext = os.path.splitext(str(name or "").lower())[1]
        self.active = True       # the 2D geometry is collected (dropped as soon as the file turns out to be fff)
        self.app = None          # {"name", "version"} of a laser / CAM program that signed the header
        self.laser_app = False
        self.flags = set()       # tag names: macro-calls, laser-macros, live-job-markers, user-script
        self.n_extrude = self.n_g0 = self.n_g1 = self.n_power = self.n_zmove = 0
        self.spindle_seen = self.spindle_on = self.m4 = False
        self.s, self.s_on_g1, self.power_max = 0.0, False, 0.0
        self.cut_feed = None
        self.cut_mm = self.travel_mm = 0.0
        self.zmin = self.zmax = None
        self.bbox_cut = self.bbox_all = None
        self.layers, self.cur, self.named, self.n_moves = [], None, False, 0
        self.by_z = {}           # cut depth -> layer: a depth that is cut again goes back to its layer
        self.rapid = False
        self.floats, self.truncated = 0, False
        self.poly, self.drawing, self.seg_type, self.last = geo.PolyBuilder(tol), False, None, None
        self.g0, self.on = False, False
        self.layers_done = False

    # ---- comments and M-codes ----
    def comment(self, body, low):
        m = _LAYER.match(body)
        if m:
            return self._marker(m.group(1)[:30])
        if low.startswith("user start script"):
            self.flags.add("user-script")
        if self.app is None and self.n_moves == 0:
            for key, label, laser in _APPS:
                if low.startswith(key) or (key in low and "generated" in low):
                    v = _VERSION.search(body)
                    self.app = {"name": label, "version": v.group(1) if v else None}
                    self.laser_app = laser
                    break

    def note_code(self, word, raw):
        """M98 (macro call) and M118 (message) lines: they say a lot about who wrote the file."""
        low = raw.lower()
        if word == b"M98":
            self.flags.add("macro-calls")
            if b"/macros/laser/" in low:
                self.flags.add("laser-macros")
        elif b"bridge job start" in low or b"bridge job end" in low:
            self.flags.add("live-job-markers")

    def spindle(self, word, raw):
        if word[:2] == b"M5":
            self.spindle_on = False
            return
        self.spindle_seen = self.spindle_on = True
        self.m4 = self.m4 or word in (b"M4", b"M04")
        m = _S.search(raw)
        if m:
            self.s = float(m.group(1))

    def note_extrude(self):
        self.n_extrude += 1
        if self.n_extrude >= EXTRUDE_MIN and self.active:
            self.active = False
            self.layers, self.cur, self.drawing, self.by_z = [], None, False, {}
            self.poly = geo.PolyBuilder(self.tol)

    # ---- moves ----
    def begin_move(self, g0, args):
        self.n_moves += 1
        self.g0 = g0
        self.rapid = g0 and "F" not in args
        if g0:
            self.n_g0 += 1
        else:
            self.n_g1 += 1
        if "S" in args:
            self.s = args["S"]
            self.s_on_g1 = self.s_on_g1 or not g0
        if g0:
            self.on = False
        elif self.s_on_g1 or self.m4:
            self.on = self.s > 0 and (self.spindle_on or not self.spindle_seen)
        elif self.spindle_seen:
            self.on = self.spindle_on
        else:
            self.on = True
        if self.on and self.s > 0 and (self.s_on_g1 or self.m4):
            self.n_power += 1
            self.power_max = max(self.power_max, self.s)

    def _depth_layers(self):
        return (self.ext in CNC_EXT or self.spindle_seen) and not self.m4 and not self.s_on_g1 and not self.named

    def step(self, px, py, pz, x, y, z, feed):
        dx, dy, dz = x - px, y - py, z - pz
        xy = math.hypot(dx, dy)
        dist = math.sqrt(xy * xy + dz * dz)
        if dist == 0.0:
            return
        if self.cur is None:
            self.cur = self._new_state(None, None)
        if not self.g0 and dz != 0.0:
            self.n_zmove += 1
        if self.g0 or not self.on or (dz > 0.0 and xy == 0.0):
            typ = TRAVEL
            self.travel_mm += dist
        else:
            typ = PLUNGE if dz < 0.0 and xy < -dz else CUT
            self.cut_mm += dist
            self._cut_extras(typ, x, y, z, feed)
            self.bbox_cut = _grow(_grow(self.bbox_cut, px, py), x, y)
        self.bbox_all = _grow(self.bbox_all, x, y)
        speed = RAPID_MM_MIN if self.rapid else feed
        if speed > 0:
            self.cur["t"] += dist / (speed / 60.0)
        if typ == TRAVEL and xy == 0.0:
            return
        self._draw(typ, px, py, x, y)

    def _cut_extras(self, typ, x, y, z, feed):
        if typ == CUT and self.cut_feed is None and feed > 0:
            self.cut_feed = feed
        self.zmin = z if self.zmin is None else min(self.zmin, z)
        self.zmax = z if self.zmax is None else max(self.zmax, z)
        if not self._depth_layers():
            return
        cz = self.cur["z"]
        if cz is None:
            self.cur["z"] = z
        elif abs(z - cz) > 0.001:
            self._new_layer(None, z)

    def _draw(self, typ, px, py, x, y):
        if self.drawing and (typ != self.seg_type or self.last != (px, py)):
            self._close_poly()
        if not self.drawing:
            self.poly.start(px, py)
            self.drawing, self.seg_type = True, typ
        self.poly.add(x, y)
        self.last = (x, y)
        if len(self.poly.pts) >= 2 * MAX_POLY_POINTS:
            self._close_poly()

    # ---- layers ----
    def _new_state(self, name, z):
        """A new layer, kept in `layers` from the start (the empty ones are dropped at the end)."""
        lay = {"name": name, "z": z, "t": 0.0, "segs": {}}
        self.layers.append(lay)
        if z is not None:
            self.by_z[round(z, 3)] = lay
        return lay

    def _close_poly(self):
        if not self.drawing:
            return
        self.drawing = False
        arr = self.poly.close()
        if arr is None or self.cur is None:
            return
        if self.floats + len(arr) > MAX_FLOATS:
            self.truncated = True
            return
        self.floats += len(arr)
        self.cur["segs"].setdefault(self.seg_type, []).append(arr)

    def _new_layer(self, name, z):
        self._close_poly()
        known = self.by_z.get(round(z, 3)) if z is not None else None
        if known is not None:
            self.cur = known
        elif len(self.layers) < MAX_LAYERS:
            self.cur = self._new_state(name, z)

    def _marker(self, name):
        if not self.active:
            return
        self._close_poly()
        self.named = True
        cur = self.cur
        if cur is None or (cur["name"] is None and not cur["segs"].get(CUT) and not cur["segs"].get(PLUNGE)):
            if cur is None:
                self.cur = cur = self._new_state(name, None)
            cur["name"] = name  # the travel before the first marker belongs to that first layer
            return
        self._new_layer(name, None)

    # ---- the verdict ----
    def decide(self, has_fff_layers):
        if has_fff_layers or self.n_extrude >= EXTRUDE_MIN:
            return "fff"
        cnc = self.n_zmove > 0 and (self.spindle_seen or self.ext in CNC_EXT)
        if (self.laser_app or "laser-macros" in self.flags) and not cnc:
            return "laser"
        if cnc:
            return "cnc"
        if self.n_power > 0:
            return "laser"
        return "travel" if self.n_g0 + self.n_g1 > 0 else "unknown"

    def tags(self, kind, slicer_name=None, has_thumb=False):
        out = []
        if self.app:
            out.append(slug(self.app["name"]))
        elif slicer_name:
            out.append(slug(slicer_name))
        if kind == "cnc" and self.spindle_seen:
            out.append("spindle")
        for flag in ("laser-macros", "macro-calls", "live-job-markers", "user-script"):
            if flag in self.flags:
                out.append(flag)
        if has_thumb:
            out.append("has-thumbnail")
        if kind != "fff" and self.truncated:
            out.append("preview-truncated")
        return [t for i, t in enumerate(out) if t and t not in out[:i]][:MAX_TAGS]

    def type_names(self):
        used = {t for lay in self.layers for t in lay["segs"]}
        return list(TYPE_NAMES[:3 if PLUNGE in used else 2])

    def finish(self):
        """Closes the last polyline and layer; afterwards `layers` is final (names filled in)."""
        if self.layers_done:
            return
        self.layers_done = True
        if not self.active:
            self.layers = []
            return
        self._close_poly()
        self.cur = None
        self.layers = [lay for lay in self.layers if lay["segs"] or lay["t"] > 0]
        for i, lay in enumerate(self.layers):
            if lay["name"] is None:
                lay["name"] = "all" if len(self.layers) == 1 else ("z=%g" % lay["z"] if lay["z"] is not None else str(i + 1))

    def deliver(self, on_layer):
        """Hands every layer to `on_layer(info, segs, travel)`; returns the infos (the layer table of the file)."""
        infos = []
        for i, lay in enumerate(self.layers):
            info = {"layer": i, "z": None if lay["z"] is None else round(lay["z"], 4), "name": lay["name"], "est_time_s": round(lay["t"], 1),
                    "features": sorted(TYPE_NAMES[t] for t in lay["segs"])}
            infos.append(info)
            on_layer(info, lay["segs"], [])
        self.layers = []
        return infos


def _bounds(lower):
    """[x0, y0, x1, y1] of the LightBurn-style `;Bounds: X3 Y3 to X589 Y504` header, or None."""
    text = (lower or {}).get("bounds")
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text or "")
    return [float(n) for n in nums[:4]] if len(nums) >= 4 else None


def flat_summary(flat, kind, p, infos):
    """The summary of a laser / cnc / travel / unknown file (the same keys the fff summary uses where they mean the same thing)."""
    s = {"kind": kind, "plane": "2d", "layers": len(infos)}
    app = flat.app or p.slicer
    if app:
        s["slicer"] = app["name"]
        if app.get("version"):
            s["slicer_version"] = app["version"]
    s["features"] = sorted({f for i in infos for f in i["features"]})
    box = _bounds(p.lower) or flat.bbox_cut or flat.bbox_all
    if box:
        z0, z1 = (round(flat.zmin, 3), round(flat.zmax, 3)) if kind == "cnc" and flat.zmin is not None else (0.0, 0.0)
        s["bbox"] = {"min": [round(box[0], 2), round(box[1], 2), z0], "max": [round(box[2], 2), round(box[3], 2), z1]}
    if flat.n_g0 + flat.n_g1:
        s["cut_mm"], s["travel_mm"] = round(flat.cut_mm, 1), round(flat.travel_mm, 1)
    if flat.power_max > 0:
        s["power_max"] = flat.power_max
    if flat.cut_feed:
        s["feed_mm_min"] = flat.cut_feed
    t = sum(i["est_time_s"] for i in infos)
    if t:
        s["time_calc_s"] = int(round(t))
    s["has_thumbnail"] = bool(p.thumbs)
    s["tags"] = flat.tags(kind, None, bool(p.thumbs))
    if p.object_name:
        s["object"] = p.object_name
    return {k: v for k, v in s.items() if v is not None and v != []}
