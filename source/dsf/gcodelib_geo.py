"""Geometry helpers of the G-code library (pure: no I/O, no service imports).

    PolyBuilder(tol)            builds ONE polyline point by point, dropping collinear points on the fly (online, O(1) per point)
    simplify(flat, tol)         the same rule applied to a finished flat list [x0, y0, x1, y1, ...] (used to serve the "low" detail)
    pack_layer(z, types, segs, travel) -> bytes     one layer as a compact zlib blob (float32 coordinates)
    unpack_layer(blob) -> {"z", "segments": {type index: [array('f'), ...]}, "travel": array('f')}

The blob layout (little endian): float32 z, uint16 number of types; per type: uint16 type index, uint32 number of polylines; per polyline
uint32 number of coordinates (2 per point) + float32 values; then uint32 number of travel coordinates + float32 values (flat pairs of
points: x0, y0, x1, y1 per travel move). The whole blob is zlib compressed. A reader only needs the byte range of the layers it wants
(the cache keeps the offset of every layer), so a page asks a window of layers without reading the rest.
"""
import math
import struct
import sys
import zlib
from array import array

_LE = sys.byteorder == "little"


class PolyBuilder:
    """Points of one polyline. `add` keeps the polyline free of collinear points within `tol` mm: when the new point lies on the line
    from the point before the last one (within tol) the last point is replaced instead of kept (a long straight run stays 2 points)."""

    __slots__ = ("pts", "tol")

    def __init__(self, tol):
        self.pts = []
        self.tol = tol

    def start(self, x, y):
        self.pts = [x, y]

    def add(self, x, y):
        p = self.pts
        n = len(p)
        if n >= 4:
            ax, ay, bx, by = p[n - 4], p[n - 3], p[n - 2], p[n - 1]
            ux, uy = x - ax, y - ay
            span = ux * ux + uy * uy
            if span > 0.0:
                # distance of b to the line a-p, and b must lie between a and p (no fold-back)
                cross = (bx - ax) * uy - (by - ay) * ux
                along = (bx - ax) * ux + (by - ay) * uy
                if cross * cross <= self.tol * self.tol * span and 0.0 <= along <= span:
                    p[n - 2], p[n - 1] = x, y
                    return
        p.append(x)
        p.append(y)

    def close(self):
        """The finished polyline as array('f') (None when it has fewer than two points)."""
        out = array("f", self.pts) if len(self.pts) >= 4 else None
        self.pts = []
        return out


def simplify(flat, tol):
    """A new array('f') with the collinear points of `flat` dropped within `tol` (a second pass over a stored polyline)."""
    b = PolyBuilder(tol)
    n = len(flat)
    if n < 4:
        return array("f", flat)
    b.start(flat[0], flat[1])
    for i in range(2, n, 2):
        b.add(flat[i], flat[i + 1])
    out = array("f", b.pts)
    return out


def length(flat):
    """Length in mm of a flat polyline."""
    total = 0.0
    for i in range(2, len(flat), 2):
        total += math.hypot(flat[i] - flat[i - 2], flat[i + 1] - flat[i - 1])
    return total


def _put(parts, arr):
    parts.append(struct.pack("<I", len(arr)))
    if arr:
        a = array("f", arr)
        if not _LE:
            a.byteswap()
        parts.append(a.tobytes())


def pack_layer(z, segs, travel):
    """segs = {type index (int): [array('f') polylines]}, travel = array('f') flat pairs of points. Returns the zlib blob."""
    parts = [struct.pack("<fH", z if z is not None else 0.0, len(segs))]
    for t, polys in segs.items():
        parts.append(struct.pack("<HI", t, len(polys)))
        for poly in polys:
            _put(parts, poly)
    _put(parts, travel or [])
    return zlib.compress(b"".join(parts), 3)


def _take(buf, pos):
    (n,) = struct.unpack_from("<I", buf, pos)
    pos += 4
    a = array("f")
    if n:
        a.frombytes(buf[pos:pos + 4 * n])
        if not _LE:
            a.byteswap()
    return a, pos + 4 * n


def unpack_layer(blob):
    buf = zlib.decompress(blob)
    z, ntypes = struct.unpack_from("<fH", buf, 0)
    pos = 6
    segs = {}
    for _ in range(ntypes):
        t, npoly = struct.unpack_from("<HI", buf, pos)
        pos += 6
        polys = []
        for _ in range(npoly):
            a, pos = _take(buf, pos)
            polys.append(a)
        segs[t] = polys
    travel, pos = _take(buf, pos)
    return {"z": z, "segments": segs, "travel": travel}
