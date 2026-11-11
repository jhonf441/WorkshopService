"""
Example files that a plugin offers once (2026-10-15, the "start-up rule" of the workshop plugins).

Three kinds of file live on the SD of the machine:
  - the plugin's OWN files (sdFiles of the plugin: updated with it, deleted when it is uninstalled);
  - EXAMPLES: commented macros that the person edits (the lights on / off of the jog, for instance). They are NOT in
    sdFiles: the plugin ships them in a staging folder and this module copies each one ONCE to its place;
  - the person's own files.

Staging folder (an sdFile of the plugin):  0:/sys/workshop/examples/<PluginId>/<path under 0:/>
    0:/sys/workshop/examples/WorkshopJog/macros/jog-examples/light-on.g   ->   0:/macros/jog-examples/light-on.g

Rules:
  - an example is created only if its destination does not exist AND it was never created before (the registry
    0:/sys/workshop/data/examples.json remembers it): a person who deleted one does not see it come back by itself;
  - an existing file is NEVER overwritten (not even by "create again");
  - "create again" (recrear) copies a missing example on request, even if it was created before;
  - the state of an expected file: "configured" (it has at least one line that is not a comment), "example" (all of it
    is commented: it still has to be configured) or "missing" (it does not exist).
"""
import paths
import sd_paths
import json
import os
import threading
import time

SD_ROOT = paths.SD
STAGING = "sys/workshop/examples"
RECORD = "sys/workshop/data/examples.json"
_lock = threading.Lock()


def _safe(rel):
    """A path under the SD without .. or absolute parts, or None."""
    try:
        return sd_paths.clean_rel(rel, allow_absolute_sd=False) or None
    except sd_paths.SdPathError:
        return None


def _read_record(sd):
    try:
        with open(os.path.join(sd, RECORD), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_record(sd, d):
    route = os.path.join(sd, RECORD)
    os.makedirs(os.path.dirname(route), exist_ok=True)
    tmp = route + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, route)


def state_file(route):
    """configured / example / missing for a file on disk."""
    try:
        with open(route, encoding="utf-8", errors="replace") as f:
            for line in f:
                t = line.strip()
                if t and not t.startswith(";"):
                    return "configured"
        return "example"
    except OSError:
        return "missing"


def available(plugin, sd=None):
    """[(destination relative to the SD, staging path)] offered by a plugin."""
    sd = sd or SD_ROOT
    plugin = _safe(plugin)
    if not plugin or "/" in plugin:
        return []
    base = os.path.join(sd, STAGING, plugin)
    out = []
    for root, _dirs, files in os.walk(base):
        for n in sorted(files):
            route = os.path.join(root, n)
            rel = os.path.relpath(route, base).replace(os.sep, "/")
            if _safe(rel):
                out.append((rel, route))
    return sorted(out)


def list_items(plugin, sd=None):
    """What a plugin offers, with the state of each file: [{"archivo", "estado", "creado_antes"}]."""
    sd = sd or SD_ROOT
    reg = _read_record(sd)
    return [{"file": rel, "state": state_file(os.path.join(sd, rel)), "created_before": rel in reg}
            for rel, _src in available(plugin, sd)]


def _create_new(dest, payload):
    """Writes `payload` to a temporary file next to `dest`, flushes it to the card and only then gives it its name WITHOUT overwriting
    (a hard link; where the card cannot link, a check plus os.replace under the module lock). A power cut leaves no half file at `dest`.
    FileExistsError when `dest` is already there."""
    tmp = dest + ".tmp-%d-%d" % (os.getpid(), threading.get_ident())
    try:
        with open(tmp, "xb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, dest)
        except FileExistsError:
            raise
        except OSError:           # no hard links on this file system (FAT)
            if os.path.lexists(dest):
                raise FileExistsError(dest)
            os.replace(tmp, dest)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def install(plugin, sd=None, recreate=None, current_time=None, only=None):
    """Creates the examples of a plugin that are missing and were never created. recrear = list of destinations that
    are created again on request (even if they were created before). Never overwrites. Returns
    {"creados": [...], "omitidos": {destination: reason}}. `only` (a list of destinations) limits it to those: the start-up wizard
    creates the files the person ticked, one by one."""
    sd = sd or SD_ROOT
    only = None if only is None else {_safe(o) for o in only}
    recreate = {_safe(r) for r in (recreate or [])}
    created, skipped = [], {}
    with _lock:
        reg = _read_record(sd)
        for rel, src in available(plugin, sd):
            if only is not None and rel not in only:
                continue
            dest = os.path.join(sd, rel)
            if os.path.exists(dest):
                skipped[rel] = "exists"
                continue
            if rel in reg and rel not in recreate:
                skipped[rel] = "created_before"
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(src, "rb") as f:
                    payload = f.read()
                _create_new(dest, payload)
            except FileExistsError:
                skipped[rel] = "exists"
                continue
            except OSError as e:
                skipped[rel] = "error: %s" % e
                continue
            reg[rel] = {"plugin": _safe(plugin), "creado": int(current_time if current_time is not None else time.time())}
            created.append(rel)
        if created:
            _save_record(sd, reg)
    return {"created": created, "skipped": skipped}
