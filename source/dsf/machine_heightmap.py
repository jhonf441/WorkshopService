"""Height maps for Machine v2 (phase 1): the RRF `heightmap.csv` format, its statistics, and the library of named meshes.

Format (GCODE-REFERENCE section 1, G29; verified in the documentation, not in a capture of the workshop machine):
    line 1   RepRapFirmware height map file v2 generated at <date>, min error X, max error X, mean X, deviation X
    line 2   axis0,axis1,min0,max0,min1,max1,radius,spacing0,spacing1,num0,num1
    line 3   X,Y,-139.90,140.00,-139.90,140.00,140.00,27.98,27.98,11,11
    then     one row per value of axis1 with num0 values; a plain `0` means "not probed", `0.0` is a probed zero.
The parser accepts what it can read and says why when it cannot (never raises); a malformed row is an error, not a guess.

The library lives on the SD of the Pi (the service has it on its disk, so it does not depend on whether `G29 S3 P"<sub-folder>"` is
accepted by the firmware, which the documentation does not say):

    0:/sys/workshop/data/machine/meshes/<id>.csv    the map, byte for byte as the firmware wrote it
    0:/sys/workshop/data/machine/meshes/<id>.json   metadata (who, when, probe, G31 trigger height, hash of the configuration, statistics)

The active map `0:/sys/heightmap.csv` is `current` (read only through this module, except write_current).
"""
import hashlib
import json
import math
import os
import re
import secrets
import time

import sd_paths

SCHEMA = 1
LIB_DIR = "sys/workshop/data/machine/meshes"
CURRENT = "0:/sys/heightmap.csv"
MAX_LIBRARY = 200
OLD_DAYS = 30            # a mesh older than this is "old" (a guess, like the age of the overview)
TRIGGER_TOL_MM = 0.005   # a G31 Z change bigger than this makes a stored mesh not valid for the datum
MAX_CSV_BYTES = 400000
_ID = re.compile(r"^m-\d{9,11}-[0-9a-f]{4}$")


class MeshError(ValueError):
    """.code is a short reason code the caller turns into a message."""

    def __init__(self, code, detail=""):
        super().__init__("%s%s" % (code, ": " + detail if detail else ""))
        self.code = code


# ---- parsing ----

def parse_csv(text):
    """{"ok", "error", "axes", "grid": {...}, "rows": [[float or None]], "header": {...}}. rows[j][i] = value at axis1 index j, axis0 index i."""
    out = {"ok": False, "error": None, "axes": None, "grid": None, "rows": [], "header": {}}
    try:
        lines = [ln.strip() for ln in str(text or "").replace("\r", "").split("\n")]
        lines = [ln for ln in lines if ln]
        if len(lines) < 4 or "height map" not in lines[0].lower():
            out["error"] = "not_a_heightmap"
            return out
        out["header"] = _header_stats(lines[0])
        keys = [k.strip() for k in lines[1].split(",")]
        vals = [v.strip() for v in lines[2].split(",")]
        if len(keys) != len(vals) or "num0" not in keys or "num1" not in keys:
            out["error"] = "bad_grid_header"
            return out
        d = dict(zip(keys, vals))
        grid = {"min0": float(d["min0"]), "max0": float(d["max0"]), "min1": float(d["min1"]), "max1": float(d["max1"]),
                "radius": float(d.get("radius", -1)), "spacing0": float(d["spacing0"]), "spacing1": float(d["spacing1"]),
                "num0": int(d["num0"]), "num1": int(d["num1"])}
        out["axes"] = [d.get("axis0", "X"), d.get("axis1", "Y")]
        if not (1 <= grid["num0"] <= 100 and 1 <= grid["num1"] <= 100):
            out["error"] = "bad_grid_size"
            return out
        rows = lines[3:]
        if len(rows) != grid["num1"]:
            out["error"] = "bad_row_count"
            return out
        for ln in rows:
            cells = [c.strip() for c in ln.split(",")]
            if len(cells) != grid["num0"]:
                out["error"] = "bad_row_length"
                return out
            out["rows"].append([None if c in ("0", "") else float(c) for c in cells])
        out["grid"], out["ok"] = grid, True
    except (ValueError, KeyError, IndexError):
        out.update(ok=False, error=out["error"] or "unreadable")
    return out


def _header_stats(line):
    out = {}
    for key, rx in (("min_error", r"min error\s+(-?[0-9.eE+-]+)"), ("max_error", r"max error\s+(-?[0-9.eE+-]+)"),
                    ("mean", r"mean\s+(-?[0-9.eE+-]+)"), ("deviation", r"deviation\s+(-?[0-9.eE+-]+)")):
        m = re.search(rx, line, re.I)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                pass
    return out


def points_of(parsed):
    """[(x, y, z)] of the probed cells; x along axis0, y along axis1 (Cartesian grids)."""
    g = parsed["grid"]
    out = []
    for j, row in enumerate(parsed["rows"]):
        y = g["min1"] + j * g["spacing1"]
        for i, z in enumerate(row):
            if z is not None:
                out.append((g["min0"] + i * g["spacing0"], y, z))
    return out


def stats(parsed, quality=None):
    """Mesh quality metrics over the probed cells: counts, min / max / range (peak to valley), mean, RMS, standard deviation, share of
    points over each threshold of the profile (`quality` = {"warn_range_mm", "bad_range_mm"}) and the traffic light by range."""
    g = parsed["grid"]
    total = g["num0"] * g["num1"]
    zs = [z for _, _, z in points_of(parsed)]
    out = {"cells": total, "probed": len(zs), "unprobed": total - len(zs), "min": None, "max": None, "range": None, "mean": None,
           "rms": None, "stdev": None, "over_warn_pct": None, "over_bad_pct": None, "light": "unknown"}
    if not zs:
        return out
    mean = sum(zs) / len(zs)
    out.update(min=min(zs), max=max(zs), range=max(zs) - min(zs), mean=mean, rms=math.sqrt(sum(z * z for z in zs) / len(zs)),
               stdev=math.sqrt(sum((z - mean) ** 2 for z in zs) / len(zs)))
    q = quality or {}
    warn, bad = q.get("warn_range_mm"), q.get("bad_range_mm")
    if warn is not None and bad is not None:
        out["over_warn_pct"] = round(100.0 * sum(1 for z in zs if abs(z - mean) > warn) / len(zs), 1)
        out["over_bad_pct"] = round(100.0 * sum(1 for z in zs if abs(z - mean) > bad) / len(zs), 1)
        out["light"] = "bad" if out["range"] > bad else "warn" if out["range"] > warn else "ok"
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def gate(parsed, stats_, expected_points=None):
    """Quality gate: [] when the mesh is acceptable, else reason codes. A map with unprobed cells (points the probe could not reach, a probing
    error) is partial and is not activated; a bad range is reported (the light) but it is the person who decides."""
    reasons = []
    if not parsed.get("ok"):
        return ["unreadable"]
    if stats_["probed"] == 0:
        reasons.append("no_points")
    if stats_["unprobed"] > 0:
        reasons.append("partial")
    if expected_points is not None and stats_["probed"] < expected_points:
        reasons.append("fewer_points_than_asked")
    return reasons


# ---- validity and age ----

def config_fingerprint(read, scan=None):
    """Short hash of the configuration text a mesh depends on (config.g and the macros it calls, bed.g): a mesh made before a change of
    those files may no longer match the machine. `read(path)` -> text or None."""
    import config_scan
    sc = scan if scan is not None else config_scan.scan(read)
    h = hashlib.sha1()
    for path in list(sc.get("files") or []) + ([config_scan.BED] if sc.get("bed_g") else []):
        try:
            text = read(path)
        except Exception:  # noqa: BLE001
            text = None
        h.update(path.encode() + b"\0" + (text or "").encode("utf-8", "replace") + b"\0")
    return h.hexdigest()[:12]


def validity(meta, current, now=None):
    """Does a stored mesh still match the machine? meta = its metadata; current = {"trigger_height", "config_sha", "probe_index"} now
    (a missing key is not compared). Returns {"valid", "old", "age_days", "reasons"}: reasons are codes (partial, trigger_height_changed,
    config_changed, probe_changed); `old` is only age."""
    now = int(now if now is not None else time.time())
    reasons = []
    if meta.get("partial"):
        reasons.append("partial")
    probe = meta.get("probe") or {}
    th, cur_th = probe.get("trigger_height"), (current or {}).get("trigger_height")
    if th is not None and cur_th is not None and abs(float(th) - float(cur_th)) > TRIGGER_TOL_MM:
        reasons.append("trigger_height_changed")
    if meta.get("config_sha") and (current or {}).get("config_sha") and meta["config_sha"] != current["config_sha"]:
        reasons.append("config_changed")
    if probe.get("index") is not None and (current or {}).get("probe_index") is not None and probe["index"] != current["probe_index"]:
        reasons.append("probe_changed")
    created = meta.get("created")
    age = max(0, (now - int(created)) // 86400) if isinstance(created, int) else None
    return {"valid": not reasons, "old": bool(age is not None and age > OLD_DAYS), "age_days": age, "reasons": reasons}


# ---- library on the SD ----

def _dir():
    return sd_paths.sd(LIB_DIR)


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def new_id(now=None):
    return "m-%d-%s" % (int(now if now is not None else time.time()), secrets.token_hex(2))


def valid_id(ident):
    s = str(ident or "")
    return bool(_ID.match(s) or s == "current")


def save(csv_text, meta, now=None):
    """Writes a new library entry. `meta` comes from the caller (who, probe, ...); the grid and the statistics are filled here from the
    text. Returns the metadata written. MeshError for a map that cannot be read or a full library."""
    text = str(csv_text or "")
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise MeshError("too_large")
    parsed = parse_csv(text)
    if not parsed["ok"]:
        raise MeshError("unreadable", parsed["error"] or "")
    if len(_ids()) >= MAX_LIBRARY:
        raise MeshError("library_full")
    now = int(now if now is not None else time.time())
    ident = new_id(now)
    quality = (meta or {}).get("quality_thresholds")
    out = dict(meta or {}, schema=SCHEMA, id=ident, created=now, grid=parsed["grid"], axes=parsed["axes"], stats=stats(parsed, quality))
    out.pop("quality_thresholds", None)
    base = os.path.join(_dir(), ident)
    _write_atomic(base + ".csv", text.encode("utf-8"))
    _write_atomic(base + ".json", json.dumps(out, separators=(",", ":")).encode("utf-8"))
    return out


def _ids():
    try:
        names = os.listdir(_dir())
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and _ID.match(n[:-5]))


def _read_text(real):
    try:
        if os.path.getsize(real) > MAX_CSV_BYTES:
            return None
        with open(real, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _current_meta(real):
    text = _read_text(real)
    parsed = parse_csv(text) if text else {"ok": False}
    try:
        created = int(os.path.getmtime(real))
    except OSError:
        created = None
    out = {"schema": SCHEMA, "id": "current", "name": "heightmap", "created": created}
    if parsed.get("ok"):
        out.update(grid=parsed["grid"], axes=parsed["axes"], stats=stats(parsed))
    return out


def meta_of(ident):
    """Metadata of one entry (library or current); None when there is none."""
    ident = str(ident or "")
    if not valid_id(ident):
        return None
    if ident == "current":
        real = sd_paths.sd(CURRENT)
        return _current_meta(real) if os.path.isfile(real) else None
    try:
        with open(os.path.join(_dir(), ident + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def csv_of(ident):
    """Text of the map of an entry, or None."""
    ident = str(ident or "")
    if not valid_id(ident):
        return None
    if ident == "current":
        return _read_text(sd_paths.sd(CURRENT))
    return _read_text(os.path.join(_dir(), ident + ".csv"))


def listing():
    """The library, newest first. The active map is not listed here."""
    out = [m for m in (meta_of(i) for i in _ids()) if m]
    out.sort(key=lambda m: m.get("created") or 0, reverse=True)
    return out


def delete(ident):
    """Removes a library entry (never the active map). MeshError("not_found" / "read_only")."""
    ident = str(ident or "")
    if not _ID.match(ident):
        raise MeshError("read_only" if valid_id(ident) else "not_found")
    if ident not in _ids():
        raise MeshError("not_found")
    for ext in (".csv", ".json"):
        try:
            os.remove(os.path.join(_dir(), ident + ext))
        except OSError:
            pass
    return True


def write_current(csv_text):
    """Puts a map into the place `G29 S1` reads by default (sys/heightmap.csv). The one that was there is kept as the `previous` slot
    of the library folder first (one slot, overwritten each time). Returns True when a previous map was kept."""
    real = sd_paths.sd(CURRENT)
    kept = False
    old = _read_text(real)
    if old is not None and old != csv_text:
        _write_atomic(os.path.join(_dir(), "previous.csv"), old.encode("utf-8"))
        kept = True
    _write_atomic(real, str(csv_text).encode("utf-8"))
    return kept
