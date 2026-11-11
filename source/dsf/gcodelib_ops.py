"""API operations gcodelib.list / info / thumbnail / layers / refresh / forget (api_ops.init registers them through build(ctx)).

None of them parses a file: they list the SD folder, join it with the cache (gcodelib_cache) and queue what is missing for the single
background worker (gcodelib_indexer). Contract for the pages: docs/GCODE-LIBRARY.md. Roles (permissions.py): list / info / thumbnail /
layers = viewer, refresh = operator, forget = admin. Layers and the layer table count from 0.
"""
import base64
import os

import gcodelib_files as files
import gcodelib_geo as geo
import gcodelib_indexer as ix
import gcodelib_kind as kind_mod
import sd_paths
from messages import M
from workshop_api import ADMIN, READ, WRITE, Arg, ApiError, Op

MAX_ROWS = 200
MAX_TABLE = 1500
MAX_BYTES = 400 * 1024       # of one answer of gcodelib.layers
TOLERANCE = {"normal": None, "low": 0.3}   # None = what the parser stored (0.05 mm)
SORTS = ("name", "modified", "size", "time")
KINDS = kind_mod.KINDS


def _root():
    return sd_paths.SD


def _file(args):
    try:
        return files.resolve_file(args["file"], _root())
    except FileNotFoundError:
        raise ApiError("invalid_args", M("gcodelib_err_not_found", file=args["file"]), field="file")
    except ValueError:
        raise ApiError("invalid_args", M("gcodelib_err_bad_path", file=args["file"]), field="file")


def _stat(real):
    st = os.stat(real)
    return st.st_size, st.st_mtime_ns


def _error_text(entry):
    err = entry.get("error") or {}
    return str(M(err.get("key", "gcodelib_err_parse"), **(err.get("params") or {})))


def _summary(entry, size, mtime_ns):
    out = dict(entry.get("summary") or {})
    out["size"], out["modified"] = size, int(mtime_ns // 1_000_000_000)
    return out


def _sort_key(sort):
    def time_of(r):
        s = r.get("summary") or {}
        return s.get("time_s") if s.get("time_s") is not None else s.get("time_calc_s")
    if sort == "time":
        return lambda r: (time_of(r) is None, time_of(r) or 0)
    if sort == "name":
        return lambda r: r["name"].lower()
    return lambda r: r[sort]


def _rows(ix_, found, root, auto):
    rows, queued = [], 0
    for f in found:
        state, entry = ix_.state_of(f["path"], f["size"], f["mtime_ns"])
        row = {"name": f["name"], "path": files.display(f["path"], root), "size": f["size"], "modified": int(f["mtime_ns"] // 1_000_000_000),
               "state": state}
        if entry and state == "error":
            row["error"] = _error_text(entry)
        elif entry:
            row["summary"] = _summary(entry, f["size"], f["mtime_ns"])
        elif auto and not ix_.is_queued(f["path"]):
            ix_.enqueue(f["path"], mtime_ns=f["mtime_ns"])
            queued += 1
        rows.append(row)
    return rows


def _kinds(args):
    """The `kind` filter as a set (a string may hold several kinds separated by commas); an unknown kind is invalid_args."""
    raw = args.get("kind")
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    kinds = {str(k).strip().lower() for k in items if str(k).strip()}
    bad = sorted(kinds - set(KINDS))
    if bad:
        raise ApiError("invalid_args", M("gcodelib_err_bad_kind", kind=", ".join(bad), kinds=", ".join(KINDS)), field="kind")
    return kinds


def _counts(rows):
    """{fff, laser, cnc, travel, unknown}: the ready files of the folder by kind (a summary without a kind counts as unknown)."""
    out = {k: 0 for k in KINDS}
    for r in rows:
        if r["state"] == "ready":
            k = (r.get("summary") or {}).get("kind")
            out[k if k in out else "unknown"] += 1
    return out


def _matches(row, q):
    if q in row["name"].lower():
        return True
    return any(q in t for t in (row.get("summary") or {}).get("tags", ()))


def _list(args, _c):
    ix_ = ix.instance()
    root = _root()
    try:
        real = files.resolve_dir(args.get("dir") or files.DEFAULT_DIR, root)
    except FileNotFoundError:
        raise ApiError("invalid_args", M("gcodelib_err_not_found", file=args.get("dir") or files.DEFAULT_DIR), field="dir")
    except ValueError:
        raise ApiError("invalid_args", M("gcodelib_err_bad_path", file=args.get("dir")), field="dir")
    shown = files.display(real, root)
    ix_.dirs.add(shown)
    found, dirs = files.scan(real)
    q = str(args.get("query") or "").strip().lower()
    kinds = _kinds(args)
    cfg = ix_.settings()
    rows = _rows(ix_, found, root, cfg["enabled"] and cfg["auto_index"])
    counts = _counts(rows)  # over every file of the folder, whatever the query and the kind filter
    if q:
        rows = [r for r in rows if _matches(r, q)]
    if kinds:
        rows = [r for r in rows if (r.get("summary") or {}).get("kind", "unknown") in kinds and r["state"] == "ready"]
    sort = args.get("sort") or "name"
    rows.sort(key=_sort_key(sort), reverse=bool(args.get("desc")))
    limit = min(int(args.get("limit") or 50), MAX_ROWS)
    offset = max(0, int(args.get("offset") or 0))
    return {"dir": shown, "dirs": dirs, "rows": rows[offset:offset + limit], "total": len(rows), "pending": ix_.pending_count(),
            "cache_bytes": ix_.cache.total_bytes(), "counts": counts}


def _ready(args):
    """(indexer, real path, size, mtime, entry, detail) of a requested file; when it is not ready it is queued first in line and the
    second value is the answer to give: {"state": ...}."""
    ix_ = ix.instance()
    real = _file(args)
    size, mtime = _stat(real)
    state, entry = ix_.state_of(real, size, mtime)
    if state == "error":
        return ix_, {"state": "error", "error": _error_text(entry)}, None, None
    detail = ix_.cache.detail(real) if state == "ready" else None
    if detail is None:
        ix_.enqueue(real, urgent=True, mtime_ns=mtime)  # not read yet (or evicted): it goes first
        return ix_, {"state": "working" if state == "working" else "pending"}, None, None
    ix_.cache.touch(real)
    return ix_, real, (size, mtime, entry), detail


def _info(args, _c):
    ix_, real, meta, detail = _ready(args)
    if meta is None:
        return real
    size, mtime, entry = meta
    table = detail["layers"]
    return {"state": "ready", "file": files.display(real, _root()), "summary": _summary(entry, size, mtime), "header": detail["header"],
            "temps": detail["temps"], "layers_table": table[:MAX_TABLE], "layers_table_truncated": len(table) > MAX_TABLE,
            "types": detail["types"], "plane": detail.get("plane", "3d")}


def _thumbnail(args, _c):
    ix_, real, meta, detail = _ready(args)
    if meta is None:
        return real
    got = ix_.cache.read_thumb(real, detail, args.get("width"))
    if got is None:
        return {"none": True}
    out = {"width": got[0], "height": got[1], "png_base64": base64.b64encode(got[2]).decode("ascii")}
    if got[3]:
        out["synthetic"] = True  # drawn by the service from the toolpath: the file has no thumbnail of its own
    return out


def _round(arr):
    return [round(v, 2) for v in arr]


def _layer_json(blob, names, tol):
    lay = geo.unpack_layer(blob)
    segs, coords = {}, 0
    for t, polys in lay["segments"].items():
        out = []
        for p in polys:
            q = geo.simplify(p, tol) if tol else p
            if len(q) >= 4:
                out.append(_round(q))
                coords += len(q)
        if out:
            segs[names[t] if t < len(names) else str(t)] = out
    item = {"z": round(lay["z"], 4), "segments": segs}
    if not tol and len(lay["travel"]):
        item["travel"] = _round(lay["travel"])
        coords += len(lay["travel"])
    return item, coords


def _layers(args, _c):
    ix_, real, meta, detail = _ready(args)
    if meta is None:
        return real
    total = len(detail["layers"])
    first = max(0, int(args["from"]))
    last = min(int(args["to"]), total - 1)
    tol = TOLERANCE[args.get("detail") or "normal"]
    names, out, spent = detail["types"], [], 0
    plane = detail.get("plane", "3d")
    truncated = False
    for i, blob in ix_.cache.read_blobs(real, detail, first, last):
        row = detail["layers"][i]
        item, coords = _layer_json(blob, names, tol) if blob else ({"z": row["z"], "segments": {}}, 0)
        if plane == "2d":
            item["z"] = row.get("z")  # the blob stores no Z for a flat toolpath (null: not meaningful)
            item["name"] = row.get("name")
        if out and spent + coords * 8 > MAX_BYTES:
            truncated = True
            break
        item["layer"] = i
        out.append(item)
        spent += coords * 8
    return {"state": "ready", "from": first, "to": out[-1]["layer"] if out else first - 1, "total": total, "types": names, "plane": plane, "layers": out,
            "truncated": truncated or (bool(out) and out[-1]["layer"] < last), "detail": args.get("detail") or "normal"}


def _refresh(args, _c):
    ix_ = ix.instance()
    if args.get("file"):
        real = _file(args)
        size, mtime = _stat(real)
        ix_.cache.drop(real)
        ix_.enqueue(real, urgent=True, mtime_ns=mtime)
        return {"queued": 1}
    return {"queued": ix_.rescan(force=True)}


def _forget(args, _c):
    ix_ = ix.instance()
    if args.get("file"):
        return {"removed": 1 if ix_.cache.drop(_file(args)) else 0}
    return {"removed": ix_.cache.clear()}


def build(ctx):
    a = Arg
    f = a("str", True, desc="Path of the G-code file, e.g. 0:/gcodes/part.gcode (inside the SD; .g .gcode .gco .nc .gc .ngc .tap).")
    return [
        Op("gcodelib.list", _list, READ,
           {"dir": a("str", False, desc="Folder (default 0:/gcodes)."), "query": a("str", False, desc="Text the name or a tag must contain."),
            "kind": a("list", False, desc="Only these kinds: fff | laser | cnc | travel | unknown (a list or a comma separated string)."),
            "sort": a("str", False, choices=SORTS, desc="name | modified | size | time."), "desc": a("bool", False, desc="Descending."),
            "limit": a("int", False, min=1, max=MAX_ROWS, desc="Rows per page (default 50, at most 200)."),
            "offset": a("int", False, min=0, desc="Rows to skip.")},
           "The G-code files of a folder joined with the library cache: {dir, dirs, rows: [{name, path, size, modified, state: ready | pending | working | "
           "error, error?, summary?}], total, pending, cache_bytes, counts: {fff, laser, cnc, travel, unknown}}. It never parses: files without a cache entry are queued for the background worker.",
           log=False),
        Op("gcodelib.info", _info, READ, {"file": f},
           "Everything the library knows about one file: {state: ready, summary, header, temps, layers_table, types} or {state: pending | working | "
           "error}. A file that is not read yet is queued first in line.", log=False),
        Op("gcodelib.thumbnail", _thumbnail, READ, {"file": f, "width": a("int", False, min=16, max=2000, desc="Wanted width in pixels.")},
           "{width, height, png_base64, synthetic?}, the embedded thumbnail or else a small one drawn from the toolpath (synthetic: true); {none: true} when there is nothing to draw, or {state: pending | working | error}.", log=False),
        Op("gcodelib.layers", _layers, READ,
           {"file": f, "from": a("int", True, min=0, desc="First layer (0-based)."), "to": a("int", True, min=0, desc="Last layer (inclusive)."),
            "detail": a("str", False, choices=("low", "normal"), desc="low = fewer points (0.3 mm), normal = 0.05 mm and the travel moves.")},
           "The path of a window of layers: {from, to, total, types, plane: 3d | 2d, layers: [{layer, z (null in 2d), name? (2d), segments: {type: [[x0, y0, x1, y1, ...]]}, travel?}], truncated}. "
           "An answer holds about 400 KB: when it is cut, `to` is the last layer sent and truncated is true.", log=False),
        Op("gcodelib.refresh", _refresh, WRITE, {"file": a("str", False, desc="One file to read again; without it the folder is scanned.")},
           "Reads a file again (its entry is dropped and it goes first), or scans the watched folders for new, changed and deleted files: {queued}.", exclusive=False),
        Op("gcodelib.forget", _forget, ADMIN, {"file": a("str", False, desc="One file; without it the whole cache is cleared.")},
           "Deletes cache entries: {removed}. With auto_index on, the files are read again by the worker.", exclusive=False),
    ]
