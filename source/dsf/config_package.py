"""Configuration package (2026-10-24): the settings, zones and macros of one machine in a single zip another machine can import.

Why: a person who installs the plugins on a new machine starts with no settings, and each page only creates its file
when somebody saves it. The owner's machine is the best template: its macros show what a plugin can do and its settings
show how the pages are filled. The package carries all that, never the secrets.

What goes in (category -> where it comes from, on the SD):
  config   sys/workshop/config/*.json     (any field named like a key / topic / password is taken out, config_store.KEYS)
  zones    sys/workshop/zones/*           (work zones, cut area)
  macros   macros/**                      (the person's own macros: lights, power, laser, jog, cnc...)
  system   sys/modestate.g, sys/automodeselect.g, sys/mode*.g   (machine modes: hardware specific, reference only)

What never goes in: users and PINs, the secrets file, the camera key, the Tuya key, the database, API keys, captures,
plugin-owned macros (sys/workshop/macros come with their plugin) and config.g.

Importing (apply) follows the rule of the examples (examples.py): nothing already there is overwritten.
  - a file that does not exist is created;
  - the same content is left alone ("same");
  - a different one is kept ("conflict"); the person may ask to replace it by name, and the old one is kept as <file>.bak-import;
  - "system" files are never put in place: they are written to sys/workshop/imported/ as a reference, because they
    hold the pins and drivers of ANOTHER machine.
A preview (preview) returns the action for every file without writing anything.
"""
import base64
import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile

import config_store
import paths
from workshop_api import ADMIN, READ, Arg, ApiError, Op

FORMAT = 1
MANIFEST = "manifest.json"
CATEGORIES = ("config", "zones", "macros", "system")
IMPORTED = "sys/workshop/imported"
MAX_FILE = 256 * 1024          # bytes of one file
MAX_FILES = 500
MAX_TOTAL = 8 * 1024 * 1024    # uncompressed bytes of the whole package
MAX_ZIP = 700 * 1024           # the API request is limited to 1 MB, and base64 adds a third
MACRO_EXT = (".g", ".gcode", ".txt", ".json", ".md")
SYSTEM_FILES = re.compile(r"^sys/(modestate|automodeselect|mode[a-z0-9_]*)\.g$")
_lock = threading.Lock()


def _sd():
    return paths.SD


def _safe(rel):
    """A path under the SD without .. or absolute parts, or None."""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in (".", "..") or ":" in p for p in parts):
        return None
    return "/".join(parts)


def _category_of(rel):
    """Category of a path inside a package, or None when that path is not allowed."""
    if rel == MANIFEST:
        return None
    if rel.startswith("sys/workshop/config/") and rel.endswith(".json") and rel.count("/") == 3:
        return "config"
    if rel.startswith("sys/workshop/zones/") and rel.count("/") == 3:
        return "zones"
    if rel.startswith("macros/") and rel.lower().endswith(MACRO_EXT):
        return "macros"
    if SYSTEM_FILES.match(rel):
        return "system"
    return None


def _clean_json(raw):
    """The bytes of a settings file without any secret; None when it is not valid JSON."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    public, _secret = config_store._split(data)
    return json.dumps(public, indent=2, ensure_ascii=False).encode("utf-8")


def _walk(base, rel_base):
    out = []
    root = os.path.join(base, rel_base)
    for folder, _dirs, files in os.walk(root):
        for n in sorted(files):
            rel = os.path.relpath(os.path.join(folder, n), base).replace(os.sep, "/")
            out.append(rel)
    return sorted(out)


def _candidates(sd):
    out = _walk(sd, "sys/workshop/config") + _walk(sd, "sys/workshop/zones") + _walk(sd, "macros")
    out += [f for f in (os.path.join("sys", n) for n in sorted(os.listdir(os.path.join(sd, "sys")))
                        if os.path.isfile(os.path.join(sd, "sys", n))) if SYSTEM_FILES.match(f.replace(os.sep, "/"))] \
        if os.path.isdir(os.path.join(sd, "sys")) else []
    return [f.replace(os.sep, "/") for f in out]


def build(categories=None, sd=None, now=None):
    """The package as zip bytes plus its manifest. categories: subset of CATEGORIES (default all)."""
    sd = sd or _sd()
    wanted = set(categories or CATEGORIES)
    if not wanted <= set(CATEGORIES):
        raise ValueError("unknown category")
    entries, payloads, skipped = [], {}, []
    total = 0
    for rel in _candidates(sd):
        cat = _category_of(rel)
        if cat is None or cat not in wanted:
            continue
        try:
            with open(os.path.join(sd, rel), "rb") as f:
                raw = f.read(MAX_FILE + 1)
        except OSError:
            continue
        if len(raw) > MAX_FILE:
            skipped.append({"path": rel, "reason": "too_big"})
            continue
        if cat == "config":
            raw = _clean_json(raw)
            if raw is None:
                skipped.append({"path": rel, "reason": "not_json"})
                continue
        total += len(raw)
        if len(entries) >= MAX_FILES or total > MAX_TOTAL:
            skipped.append({"path": rel, "reason": "package_full"})
            continue
        payloads[rel] = raw
        entries.append({"path": rel, "category": cat, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"format": FORMAT, "created": int(now if now is not None else time.time()),
                "categories": sorted(wanted), "files": entries}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(manifest, indent=1))
        for rel, raw in payloads.items():
            z.writestr(rel, raw)
    return buf.getvalue(), manifest, skipped


def read_package(blob):
    """Opens a package (zip bytes). Returns (manifest, {path: bytes}). Raises ValueError with a short code."""
    if len(blob) > MAX_ZIP:
        raise ValueError("too_big")
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise ValueError("not_a_package")
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("files"), list):
        raise ValueError("unknown_format")
    if len(manifest["files"]) > MAX_FILES:
        raise ValueError("too_many_files")
    files, total = {}, 0
    for e in manifest["files"]:
        rel = _safe(e.get("path")) if isinstance(e, dict) else None
        if rel is None or _category_of(rel) != e.get("category"):
            raise ValueError("bad_path")
        info = z.getinfo(rel) if rel in z.namelist() else None
        if info is None or info.file_size > MAX_FILE:
            raise ValueError("bad_file")
        total += info.file_size
        if total > MAX_TOTAL:
            raise ValueError("too_big")
        raw = z.read(rel)
        if hashlib.sha256(raw).hexdigest() != e.get("sha256"):
            raise ValueError("damaged")
        files[rel] = raw
    return manifest, files


def _same(path, raw):
    try:
        with open(path, "rb") as f:
            return f.read() == raw
    except OSError:
        return False


def plan(manifest, files, sd=None, categories=None):
    """What applying would do to each file: create / same / conflict / reference (system) / skip (category not chosen)."""
    sd = sd or _sd()
    chosen = set(categories or CATEGORIES)
    items = []
    for e in manifest["files"]:
        rel, cat = e["path"], e["category"]
        if cat not in chosen:
            action = "skip"
        elif cat == "system":
            action = "reference"
        else:
            dest = os.path.join(sd, rel)
            if not os.path.exists(dest):
                action = "create"
            elif _same(dest, files[rel]):
                action = "same"
            else:
                action = "conflict"
        items.append({"path": rel, "category": cat, "size": e["size"], "action": action})
    return items


def _write_new(dest, raw):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "xb") as f:  # x: never overwrites, even in a race
        f.write(raw)


def _write_replace(dest, raw):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dest)


def apply(manifest, files, sd=None, categories=None, replace=None):
    """Applies a package. Returns {"created": [...], "replaced": [...], "kept": [...], "reference": [...], "errors": {path: reason}}."""
    sd = sd or _sd()
    replace = {_safe(r) for r in (replace or [])}
    out = {"created": [], "replaced": [], "kept": [], "same": [], "reference": [], "errors": {}}
    with _lock:
        for it in plan(manifest, files, sd, categories):
            rel, action, raw = it["path"], it["action"], files.get(it["path"])
            try:
                if action == "create":
                    _write_new(os.path.join(sd, rel), raw)
                    out["created"].append(rel)
                elif action == "same":
                    out["same"].append(rel)
                elif action == "conflict":
                    if rel in replace:
                        dest = os.path.join(sd, rel)
                        with open(dest, "rb") as f:
                            old = f.read()
                        _write_replace(dest + ".bak-import", old)
                        _write_replace(dest, raw)
                        out["replaced"].append(rel)
                    else:
                        out["kept"].append(rel)
                elif action == "reference":
                    _write_replace(os.path.join(sd, IMPORTED, rel.replace("/", "__")), raw)
                    out["reference"].append(rel)
            except FileExistsError:
                out["kept"].append(rel)
            except OSError as e:
                out["errors"][rel] = str(e)
    return out


# ---- API operations -------------------------------------------------------

def _decode(args):
    try:
        blob = base64.b64decode(args["data"], validate=False)
        return read_package(blob)
    except (ValueError, TypeError) as e:
        raise ApiError("invalid_args", "package: " + str(e), field="data")


def _export(args, ctx):
    cats = args.get("categories") or None
    try:
        blob, manifest, skipped = build(cats)
    except ValueError:
        raise ApiError("invalid_args", "unknown category", field="categories")
    if len(blob) > MAX_ZIP:
        raise ApiError("too_big", "the package is bigger than the API allows; leave a category out")
    return {"name": "workshop-config-%s.zip" % time.strftime("%Y%m%d", time.localtime(manifest["created"])),
            "data": base64.b64encode(blob).decode("ascii"), "manifest": manifest, "skipped": skipped}


def _preview(args, ctx):
    manifest, files = _decode(args)
    return {"created": manifest.get("created"), "items": plan(manifest, files, categories=args.get("categories") or None)}


def _apply(args, ctx):
    manifest, files = _decode(args)
    return apply(manifest, files, categories=args.get("categories") or None, replace=args.get("replace") or None)


def ops():
    a = Arg
    cats = {"categories": a("list", desc="Which kinds of file: config, zones, macros, system (default all).")}
    return [
        Op("package.export", _export, READ, dict(cats),
           "Builds the configuration package: the settings of the pages, the work zones, the macros of the person and the machine "
           "modes, in a zip (base64 in data). Secrets, users, keys and the database never go in.", log=False),
        Op("package.preview", _preview, READ, dict(cats, data=a("str", True, desc="The package, base64.")),
           "Says what importing a package would do to each file (create, same, conflict, reference, skip) without writing anything.", log=False),
        Op("package.apply", _apply, ADMIN,
           dict(cats, data=a("str", True, desc="The package, base64."),
                replace=a("list", desc="Paths (as listed by package.preview) to replace although they differ; the old file is kept as <file>.bak-import.")),
           "Imports a package. It creates the files that are missing, never overwrites one (it keeps yours and reports the conflict) "
           "unless named in replace, and leaves the machine modes as references in sys/workshop/imported/."),
    ]
