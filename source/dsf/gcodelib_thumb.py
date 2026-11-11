"""Synthetic thumbnail of a G-code file that has none of its own (PURE: no I/O, no PIL: a zlib + struct PNG encoder).

    Sampler().add_layer(info, segs, travel)    fed layer by layer by the indexer while it parses (bounded memory)
    Sampler().render(plane, type_names, w=192, h=144) -> PNG bytes or None (nothing to draw)
    png_size(png) -> (width, height)

The sampler keeps at most MAX_SEGMENTS segments spread evenly over the whole file (when the list is full it keeps every second one and
doubles its stride), so a multi-MB file costs a fixed amount of memory and time. Views: fff = orthographic projection with a fixed yaw / pitch
of 35 degrees of ALL layers (lower layers darker, the top lighter, one colour per feature type when the file has several); 2D files (laser,
cnc, travel) = top view, travel dim under the cut, over the bbox rectangle. An 8-bit palette PNG on the dark background #1b1b1f with the bed
outline; the same input always gives the same bytes.
"""
import math
import struct
import zlib
from array import array

MAX_SEGMENTS = 30000
WIDTH, HEIGHT, MARGIN = 192, 144, 8
LEVELS = 8
FEATURE_COLORS = ((255, 150, 60), (255, 230, 77), (120, 220, 120), (240, 100, 120), (200, 120, 240), (255, 125, 56), (176, 120, 70), (200, 200, 200))  # warm and green tones, no light blue (the owner dislikes it)
BG, BED, TRAVEL, CUT, PLUNGE = 0, 1, 2, 3, 4
_YAW, _PITCH = math.radians(35.0), math.radians(35.0)


def _palette():
    pal = [(0x1b, 0x1b, 0x1f), (0x3c, 0x3c, 0x48), (0x3a, 0x3a, 0x46), (255, 179, 0), (229, 57, 53), (0, 0, 0), (0, 0, 0), (0, 0, 0)]
    for r, g, b in FEATURE_COLORS:
        for lvl in range(LEVELS):
            k = 0.35 + 0.65 * lvl / (LEVELS - 1)
            pal.append((int(r * k), int(g * k), int(b * k)))
    return pal


PALETTE = _palette()


def encode_png(pixels, w, h):
    """8-bit palette PNG of `pixels` (bytes, one palette index per pixel, row by row)."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(pixels[y * w:(y + 1) * w]) for y in range(h))
    plte = b"".join(bytes(c) for c in PALETTE)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)) + chunk(b"PLTE", plte) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def png_size(png):
    return struct.unpack(">II", png[16:24])


def _line(buf, w, x0, y0, x1, y1, c):
    """Hard 1 px line (the points are already inside the canvas)."""
    dx, dy = x1 - x0, y1 - y0
    n = max(abs(dx), abs(dy))
    if n == 0:
        buf[y0 * w + x0] = c
        return
    sx, sy = dx / n, dy / n
    x, y = x0 + 0.5, y0 + 0.5
    for _ in range(n + 1):
        buf[int(y) * w + int(x)] = c
        x += sx
        y += sy


class Sampler:
    def __init__(self, max_segments=MAX_SEGMENTS):
        self.cap = max_segments
        self.items = []   # (x0, y0, x1, y1, z, type index)
        self.stride = 1
        self.count = 0    # segments seen (the stride picks every stride-th one)
        self._bed_box = None

    def add_layer(self, info, segs, travel=None):
        z = info.get("z")
        z = 0.0 if z is None else z
        items = self.items
        for t, polys in segs.items():
            for p in polys:
                n = len(p) // 2 - 1
                if n <= 0:
                    continue
                stride, g, end = self.stride, -(-self.count // self.stride) * self.stride, self.count + n
                while g < end:
                    j = g - self.count
                    items.append((p[2 * j], p[2 * j + 1], p[2 * j + 2], p[2 * j + 3], z, t))
                    if len(items) > self.cap:
                        del items[1::2]   # keeps the multiples of the doubled stride
                        stride = self.stride = stride * 2
                    g = (g // stride + 1) * stride
                self.count = end

    def render(self, plane, type_names, w=WIDTH, h=HEIGHT):
        if not self.items:
            return None
        segs, order = self._project_2d(type_names) if plane == "2d" else self._project_3d(type_names)
        bed = self._bed(segs)
        allp = segs + bed
        x0 = min(min(s[0], s[2]) for s in allp)
        x1 = max(max(s[0], s[2]) for s in allp)
        y0 = min(min(s[1], s[3]) for s in allp)
        y1 = max(max(s[1], s[3]) for s in allp)
        scale = min((w - 2 * MARGIN) / max(x1 - x0, 1e-6), (h - 2 * MARGIN) / max(y1 - y0, 1e-6))
        ox = (w - scale * (x1 - x0)) / 2 - scale * x0
        oy = (h - scale * (y1 - y0)) / 2 - scale * y0
        buf = bytearray(w * h)
        for group in [bed] + order(segs):
            for a in group:
                _line(buf, w, int(ox + scale * a[0]), int(h - 1 - (oy + scale * a[1])), int(ox + scale * a[2]), int(h - 1 - (oy + scale * a[3])), a[4])
        return encode_png(buf, w, h)

    def _bed(self, segs):
        """The outline rectangle (in the plane of the view) the model sits on."""
        if self._bed_box is None:
            return []
        bx0, by0, bx1, by1, z, proj = self._bed_box
        pts = [proj(bx0, by0, z), proj(bx1, by0, z), proj(bx1, by1, z), proj(bx0, by1, z)]
        return [(pts[i][0], pts[i][1], pts[(i + 1) % 4][0], pts[(i + 1) % 4][1], BED) for i in range(4)]

    def _extent(self):
        it = self.items
        return (min(min(i[0], i[2]) for i in it), min(min(i[1], i[3]) for i in it), max(max(i[0], i[2]) for i in it), max(max(i[1], i[3]) for i in it))

    def _project_2d(self, names):
        def flat(x, y, z):
            return x, y
        x0, y0, x1, y1 = self._extent()
        self._bed_box = (x0, y0, x1, y1, 0.0, flat)
        colour = {"cut": CUT, "travel": TRAVEL, "plunge": PLUNGE}
        segs = [(a, b, c, d, colour.get(names[t] if t < len(names) else "cut", CUT)) for a, b, c, d, _z, t in self.items]
        return segs, lambda sg: [[s for s in sg if s[4] == TRAVEL], [s for s in sg if s[4] != TRAVEL]]

    def _project_3d(self, names):
        cy, sy, cp, sp = math.cos(_YAW), math.sin(_YAW), math.cos(_PITCH), math.sin(_PITCH)

        def proj(x, y, z):
            return x * cy - y * sy, (x * sy + y * cy) * sp + z * cp
        x0, y0, x1, y1 = self._extent()
        zs = [i[4] for i in self.items]
        zmin, zmax = min(zs), max(zs)
        self._bed_box = (x0, y0, x1, y1, zmin if zmax > zmin else 0.0, proj)
        multi = len({t for *_r, t in self.items}) > 1 and len(names) > 1
        span = (zmax - zmin) or 1.0
        out = []
        for a, b, c, d, z, t in self.items:
            lvl = LEVELS - 1 if zmax == zmin else min(LEVELS - 1, int((LEVELS - 1) * (z - zmin) / span + 0.5))
            p, q = proj(a, b, z), proj(c, d, z)
            out.append((p[0], p[1], q[0], q[1], 8 + ((t % 8) if multi else 0) * LEVELS + lvl))
        return out, lambda sg: [sg]
