"""The catalogue of macros a person may pick for a button (operation `macros.catalog`, lote 6 of the 22-nov-2026 review).

Two groups, built here and nowhere else, so the control bar and the jog list exactly the same thing:

  mine     the person's own macros: every `.g` under 0:/macros (any depth). Action: the path relative to 0:/macros, as the buttons always stored it.
  plugins  the macros the workshop plugins ship for the person to call: those a manifest declares `audience: "user"`. Action: "plugin:<path>",
           the path relative to 0:/sys/workshop/macros. The rest of the plugin macros are helpers only the plugins call and are never listed.

The manifest of a plugin is `sys/workshop/macros/macros.<PluginId>.json` (it travels with the plugin's sd/ files):

    {"version": 1, "plugin": "WorkshopWorkbench",
     "macros": [{"file": "work/framecutarea.g", "audience": "user", "title": {"es": "...", "en": "..."}, "description": {"es": "...", "en": "..."}},
                {"file": "work/gotobed.g", "audience": "internal"}]}

A macro that no manifest declares, a manifest that does not parse, an `audience` that is not exactly "user", a file that is not on the SD and a path that
leaves the folder are all treated as `internal`: the unknown is denied, never listed. The plugin group is only for roles that may read sys/ (technician and
administrator); the others get `plugins_hidden: true` and an empty list. Pure reading: nothing is written.
"""
import json
import os

import paths

MINE_DIR = "macros"
PLUGIN_DIR = "sys/workshop/macros"
MANIFEST_PREFIX = "macros."
MANIFEST_SUFFIX = ".json"
PLUGIN_PREFIX = "plugin:"
AUDIENCES = ("user", "internal")
MAX_DEPTH = 6
MAX_MINE = 2000
MAX_MANIFEST_BYTES = 64 * 1024
MAY_SEE_PLUGINS = ("technician", "admin")


def _clean_rel(rel):
    """A relative macro path or None: forward slashes, no empty part, no `.` or `..`, ends in .g."""
    rel = str(rel or "").replace("\\", "/").strip("/")
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") for p in parts) or ":" in rel or not rel.lower().endswith(".g"):
        return None
    return "/".join(parts)


def mine(sd_root):
    """Sorted relative paths of every .g under 0:/macros (links are not followed; depth and count are capped)."""
    base = os.path.join(sd_root, MINE_DIR)
    out = []

    def walk(directory, rel, depth):
        if depth > MAX_DEPTH or len(out) >= MAX_MINE:
            return
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return
        for name in names:
            full = os.path.join(directory, name)
            if os.path.islink(full):
                continue
            here = rel + name
            if os.path.isdir(full):
                walk(full, here + "/", depth + 1)
            elif name.lower().endswith(".g") and len(out) < MAX_MINE:
                out.append(here)

    walk(base, "", 0)
    return sorted(out)


def _text(value, lang):
    """A {"es", "en"} text (or a plain string) in the asked language, falling back to the other one; at most 400 characters."""
    if isinstance(value, str):
        return value.strip()[:400]
    if isinstance(value, dict):
        for key in (lang, "en" if lang == "es" else "es"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:400]
    return ""


def read_manifest(path):
    """The parsed manifest or None (missing, too big, not JSON, not an object)."""
    try:
        if os.path.getsize(path) > MAX_MANIFEST_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def plugins(sd_root, lang="es"):
    """The macros the plugins offer to the person: [{action, plugin, file, title, description}] sorted by plugin and file. Only audience "user" whose file exists."""
    base = os.path.join(sd_root, *PLUGIN_DIR.split("/"))
    try:
        names = sorted(n for n in os.listdir(base) if n.startswith(MANIFEST_PREFIX) and n.endswith(MANIFEST_SUFFIX))
    except OSError:
        return []
    out = []
    seen = set()
    for name in names:
        doc = read_manifest(os.path.join(base, name))
        entries = doc.get("macros") if doc else None
        if not isinstance(entries, list):
            continue
        plugin = str(doc.get("plugin") or name[len(MANIFEST_PREFIX):-len(MANIFEST_SUFFIX)])[:60]
        for e in entries:
            if not isinstance(e, dict) or e.get("audience") != "user":
                continue
            rel = _clean_rel(e.get("file"))
            if rel is None or rel in seen or os.path.islink(os.path.join(base, *rel.split("/"))) or not os.path.isfile(os.path.join(base, *rel.split("/"))):
                continue
            seen.add(rel)
            out.append({"action": PLUGIN_PREFIX + rel, "plugin": plugin, "file": rel,
                        "title": _text(e.get("title"), lang) or os.path.basename(rel)[:-2], "description": _text(e.get("description"), lang)})
    return sorted(out, key=lambda m: (m["plugin"], m["file"]))


def catalog(role, lang="es", sd_root=None):
    """{mine: [rel...], plugins: [{...}], plugins_hidden: bool} for a caller with `role` (the base role: viewer, operator, technician, admin)."""
    root = sd_root or paths.SD
    allowed = str(role or "") in MAY_SEE_PLUGINS
    return {"mine": mine(root), "plugins": plugins(root, lang) if allowed else [], "plugins_hidden": not allowed}
