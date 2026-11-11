"""
sd_integrity -- READ ONLY integrity report of the SD against the manifest (SD-LAYOUT.md F.5, phase 1).

It compares what is on the SD with sd_manifest.json and tells the state of every file. It NEVER writes, never restores, never
deletes and never changes a file's mode: the only calls on the SD are listing and opening for reading (a test checks it).
Restoring is a later phase (6) and will always be an explicit act of an administrator.

States per kind
  workshop-owned     ok | edited | deleted
  template           ok | missing   (+ created_before: the registry examples.json says it was made once; + stage: ok | edited | missing)
  native-managed     ok | missing   (+ hooks {text: bool}: whether each workshop line is in the file; informational)
  generated          ok | absent (not generated yet: normal) | mark-mismatch | legacy-mark (carries the mark of an old version)
  expected-external  ok (has active lines) | comments-only | missing
  (a file in a workshop folder that no entry lists)   unknown-extra: reported, never deleted
"""
import hashlib
import json
import os

import paths
import sd_manifest

MAX_BYTES = 4 * 1024 * 1024
MAX_EXTRA = 200
REGISTRY = "sys/workshop/data/examples.json"
# marks an older version of the service wrote and a later one does not recognise (SD-LAYOUT.md A.1.1): reported, not touched
LEGACY_MARKS = {"sys/driver-stall.g": ("TALLER-JOG-LIBRE",)}
# the states that need a person to look; the rest is fine or informational
ATTENTION = frozenset({"edited", "deleted", "mark-mismatch", "legacy-mark", "unknown-extra"})
SAFETY = frozenset({"sys/driver-stall.g", "sys/workshop/macros/work/jogFreeFailsafe.g"})


def _read(route):
    """(bytes | None, problem | None): opens for reading only; a file too big or unreadable is a problem, not a crash."""
    try:
        if os.path.islink(route) or not os.path.isfile(route):
            return None, ("absent" if not os.path.lexists(route) else "not-a-file")
        if os.path.getsize(route) > MAX_BYTES:
            return None, "too-large"
        with open(route, "rb") as f:
            return f.read(), None
    except OSError as e:
        return None, "unreadable: %s" % e


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _registry(sd):
    try:
        with open(os.path.join(sd, REGISTRY), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _has_active(data):
    for line in data.decode("utf-8", "replace").splitlines():
        t = line.strip()
        if t and not t.startswith(";"):
            return True
    return False


def _owned(e, data, problem):
    if data is None:
        return ("deleted" if problem == "absent" else "unreadable"), {}
    sha = _sha(data)
    return ("ok" if sha == e["sha256"] else "edited"), {"sha_found": sha}


def _template(e, data, problem, sd, reg):
    stage_data, stage_problem = _read(os.path.join(sd, e["stage"]))
    if stage_data is None:
        stage = "missing"
    else:
        stage = "ok" if _sha(stage_data) == e["sha256"] else "edited"
    extra = {"created_before": e["path"] in reg, "stage": stage}
    if data is None:
        return ("missing" if problem == "absent" else "unreadable"), extra
    if e.get("hooks"):
        text = data.decode("utf-8", "replace")
        extra["hooks"] = {h: (h in text) for h in e["hooks"]}
    return "ok", extra


def _native(e, data, problem):
    if data is None:
        return ("missing" if problem == "absent" else "unreadable"), {}
    text = data.decode("utf-8", "replace")
    return "ok", {"hooks": {h: (h in text) for h in e.get("hooks", [])}}


def _generated(e, data, problem):
    if data is None:
        return ("absent" if problem == "absent" else "unreadable"), {}
    text = data.decode("utf-8", "replace")
    mark = e.get("mark") or ""
    if not mark or mark in text:
        return "ok", {}
    for old in LEGACY_MARKS.get(e["path"], ()):
        if old in text:
            return "legacy-mark", {"found_mark": old, "expected_mark": mark}
    return "mark-mismatch", {"expected_mark": mark}


def _external(e, data, problem):
    if data is None:
        return ("missing" if problem == "absent" else "unreadable"), {}
    return ("ok" if _has_active(data) else "comments-only"), {}


def _extras(sd, known):
    """Files under the workshop folders that no entry lists (never deleted, only reported)."""
    out = []
    for folder in sd_manifest.workshop_folders():
        base = os.path.join(sd, folder)
        for root, _dirs, files in os.walk(base):
            for n in sorted(files):
                rel = os.path.relpath(os.path.join(root, n), sd).replace(os.sep, "/")
                if rel not in known:
                    out.append(rel)
                    if len(out) >= MAX_EXTRA:
                        return out
    return out


def check(sd=None, manifest=None):
    """The report. `sd` is the root of the SD (0:/), `manifest` a path of a manifest (tests). Read only."""
    sd = sd or paths.SD
    data = sd_manifest.load(manifest)
    reg = _registry(sd)
    rows, known = [], set()
    for e in data["files"]:
        known.add(e["path"])
        if e.get("stage"):
            known.add(e["stage"])
        body, problem = _read(os.path.join(sd, e["path"]))
        kind = e["kind"]
        if kind == "workshop-owned":
            state, extra = _owned(e, body, problem)
        elif kind == "template":
            state, extra = _template(e, body, problem, sd, reg)
        elif kind == "native-managed":
            state, extra = _native(e, body, problem)
        elif kind == "generated":
            state, extra = _generated(e, body, problem)
        else:
            state, extra = _external(e, body, problem)
        row = {"path": e["path"], "kind": kind, "plugin": e.get("plugin"), "state": state, "used_by": e.get("used_by", []),
               "safety": e["path"] in SAFETY}
        if e.get("sha256"):
            row["sha_expected"] = e["sha256"]
        if e.get("breaks_if_missing") and state in ("missing", "comments-only"):
            row["breaks_if_missing"] = e["breaks_if_missing"]
        row.update(extra)
        rows.append(row)
    for rel in _extras(sd, known):
        rows.append({"path": rel, "kind": "unknown", "plugin": None, "state": "unknown-extra", "used_by": [], "safety": False})
    return {"read_only": True, "manifest_schema": data["schema"], "plugins": data.get("plugins", {}),
            "summary": summarize(rows), "files": rows}


def summarize(rows):
    states, kinds, attention = {}, {}, []
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
        k = kinds.setdefault(r["kind"], {})
        k[r["state"]] = k.get(r["state"], 0) + 1
        if r["state"] in ATTENTION:
            attention.append(r["path"])
    # a plugin whose every shipped file is gone is not installed: say so once instead of one line per file
    absent = []
    for plugin in sorted({r["plugin"] for r in rows if r["kind"] in ("workshop-owned", "template") and r["plugin"]}):
        mine = [r for r in rows if r["plugin"] == plugin and r["kind"] == "workshop-owned"]
        if mine and all(r["state"] == "deleted" for r in mine):
            absent.append(plugin)
    return {"total": len(rows), "by_state": states, "by_kind": kinds, "attention": len(attention), "attention_paths": attention[:50],
            "plugins_without_files": absent, "clean": not attention}
