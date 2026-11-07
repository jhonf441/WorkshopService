"""Real geometry of the bed zones: validation of the optional `geometry` block and the free place of a zone that has none.

Layout and view only: the heating (bed_zones.py, bed_zones_intercept.py) never reads this. Coordinates are millimetres in MAP space (origin at
the top-left corner of the bed seen from above, x to the right, y downwards). The geometry is the size of the bed and a rect per zone, exactly as the
user left them: nothing here moves a zone that already has a rect. The page has the same free-spot search in
vue/WorkshopPrinting/dwc36/dwc-src/bed-zones-drag.js; both are tested against the same golden cases.
"""
import math

BED_MIN = 10.0
BED_MAX = 5000.0
EPS = 1e-6
SNAP_MM = 5.0  # the grid a free spot is searched on
MIN_ZONE_MM = 5.0  # a placed zone is never made smaller than this


def _r(v):
    """Rounds to 0.1 mm the same way in JS and Python (no banker's rounding)."""
    return math.floor(v * 10 + 0.5) / 10


def _num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and lo <= v <= hi


def clean_geometry(raw):
    """(geometry, problems): `problems` is a list of (field, key, params) for the caller to turn into messages.

    Only the bed size is kept. A config saved by an older version may carry mode / gap / align / mirror / size (the old automatic layout): they are
    ignored when read, so such a config loads without error and its rects, already resolved, are respected as they are."""
    if not isinstance(raw, dict):
        return None, [("geometry", "bed_zones_err_geometry", {})]
    bed = raw.get("bed")
    if isinstance(bed, dict) and _num(bed.get("width"), BED_MIN, BED_MAX) and _num(bed.get("length"), BED_MIN, BED_MAX):
        return {"bed": {"width": float(bed["width"]), "length": float(bed["length"])}}, []
    return None, [("geometry.bed", "bed_zones_err_geometry_bed", {"lo": BED_MIN, "hi": BED_MAX})]


def free_spot(rects, w, h, bed, step=SNAP_MM):
    """The first free place (reading order, scanning every `step` mm) for a w x h rect that touches no other, or None."""
    y = 0.0
    while y + h <= bed["length"] + EPS:
        x = 0.0
        while x + w <= bed["width"] + EPS:
            cand = {"x": x, "y": y, "w": w, "h": h}
            if all(j != len(rects) for _, j in overlaps(rects + [cand])):
                return cand
            x += step
        y += step
    return None


def place_missing(zones, bed):
    """Gives every zone WITHOUT a rect a free place, once; the zones that have one are not touched. False when some zone has no room.

    The size is the one of the last zone that has a rect, else a quarter of the shorter side (rounded to 0.1 mm); when it does not fit, it is halved
    until it does (never below MIN_ZONE_MM)."""
    have = [z["rect"] for z in zones if "rect" in z]
    last = have[-1] if have else None
    side = _r(min(bed["width"], bed["length"]) / 4)
    for z in zones:
        if "rect" in z:
            continue
        w, h = (last["w"], last["h"]) if last else (side, side)
        spot = free_spot(have, w, h, bed)
        while spot is None and (w > MIN_ZONE_MM or h > MIN_ZONE_MM):
            w, h = _r(max(MIN_ZONE_MM, w / 2)), _r(max(MIN_ZONE_MM, h / 2))
            spot = free_spot(have, w, h, bed)
        if spot is None:
            return False
        z["rect"] = spot
        have.append(spot)
    return True


def clean_rect(raw):
    """A clean {x, y, w, h} (floats) or None when it is not a rect with w, h > 0."""
    if not isinstance(raw, dict):
        return None
    if not (_num(raw.get("x"), -BED_MAX, BED_MAX) and _num(raw.get("y"), -BED_MAX, BED_MAX)
            and _num(raw.get("w"), EPS, BED_MAX) and _num(raw.get("h"), EPS, BED_MAX)):
        return None
    return {"x": float(raw["x"]), "y": float(raw["y"]), "w": float(raw["w"]), "h": float(raw["h"])}


def overlaps(rects):
    """Pairs (i, j), i < j, of rects that share area (touching edges is not an overlap)."""
    out = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if a["x"] < b["x"] + b["w"] - EPS and b["x"] < a["x"] + a["w"] - EPS and a["y"] < b["y"] + b["h"] - EPS and b["y"] < a["y"] + a["h"] - EPS:
                out.append((i, j))
    return out


def outside(rect, bed):
    """True when the rect is not completely inside the bed."""
    return (rect["x"] < -EPS or rect["y"] < -EPS or rect["x"] + rect["w"] > bed["width"] + EPS or rect["y"] + rect["h"] > bed["length"] + EPS)
