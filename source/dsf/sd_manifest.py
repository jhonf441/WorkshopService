"""
sd_manifest -- the single source of truth of the SD files of the workshop plugins (SD-LAYOUT.md B.4, phase 1).

The data is `sd_manifest.json` next to this module (built from the released plugin zips by tools/gen_sd_manifest.py). Each file
of the SD that the workshop ships, owns, generates or merely expects is one entry with a path (relative to 0:/), a kind, the
factory sha256 and who uses it. This module only READS and validates it: nothing here writes to the SD.

Kinds (the only five; "legacy" is a state, not a kind):
  workshop-owned     shipped by the plugin's sdFiles; DSF overwrites it at every install; the person must not edit it
  template           staged by the plugin and copied ONCE by examples.py; after the copy it is the person's
  native-managed     a Duet-native file the person owns that carries workshop lines (hooks); only informational in phase 1
  generated          written at run time by the service (generator + mark)
  expected-external  the code of ours calls it but nobody ships it (the person provides it)
"""
import json
import os

KINDS = ("workshop-owned", "template", "native-managed", "generated", "expected-external")
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sd_manifest.json")
# Duet / RRF / DWC names that the platform calls itself: never `workshop-owned` (DSF would delete them when uninstalling).
NATIVE_NAMES = frozenset({
    "sys/config.g", "sys/config-override.g", "sys/daemon.g", "sys/bed.g", "sys/cancel.g", "sys/stop.g", "sys/pause.g", "sys/resume.g",
    "sys/start.g", "sys/sleep.g", "sys/homeall.g", "sys/homex.g", "sys/homey.g", "sys/homez.g", "sys/deployprobe.g", "sys/retractprobe.g",
    "sys/mesh.g", "sys/driver-stall.g", "sys/tpre0.g", "sys/tpost0.g", "sys/tfree0.g", "sys/runonce.g", "sys/resurrect.g",
    "sys/resurrect-prologue.g", "sys/dwc-settings.json", "sys/dwc-plugins.json",
})
_cache = {}


class ManifestError(ValueError):
    pass


def validate(data):
    """Raises ManifestError listing every problem; returns the manifest when it is sound."""
    problems = []
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ManifestError("schema must be 1")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError("files must be a non empty list")
    seen = set()
    for e in files:
        p = e.get("path") if isinstance(e, dict) else None
        if not isinstance(p, str) or not p or p.startswith("/") or ".." in p.split("/") or "\\" in p:
            problems.append("bad path: %r" % (p,))
            continue
        if p in seen:
            problems.append("path twice: " + p)
        seen.add(p)
        kind = e.get("kind")
        if kind not in KINDS:
            problems.append("%s: unknown kind %r" % (p, kind))
            continue
        if kind in ("workshop-owned", "template"):
            sha = e.get("sha256")
            if not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
                problems.append("%s: sha256 missing or malformed" % p)
        if kind == "workshop-owned" and p in NATIVE_NAMES:
            problems.append("%s: a native name cannot be workshop-owned" % p)
        if kind == "template" and not str(e.get("stage") or "").startswith("sys/workshop/examples/"):
            problems.append("%s: a template needs its stage under sys/workshop/examples/" % p)
        if kind == "generated" and not e.get("generator"):
            problems.append("%s: generated needs a generator" % p)
    if problems:
        raise ManifestError("; ".join(problems))
    return data


def load(path=None, fresh=False):
    """The validated manifest (cached by path)."""
    path = path or FILE
    if fresh or path not in _cache:
        with open(path, encoding="utf-8") as f:
            _cache[path] = validate(json.load(f))
    return _cache[path]


def entries(kind=None, plugin=None, path=None):
    out = load(path)["files"]
    if kind:
        out = [e for e in out if e["kind"] == kind]
    if plugin:
        out = [e for e in out if e.get("plugin") == plugin]
    return out


def find(rel, path=None):
    for e in load(path)["files"]:
        if e["path"] == rel:
            return e
    return None


def workshop_folders(path=None):
    """Folders of the SD in which every file must be in the manifest (used to report `unknown-extra`): the ones DSF fills
    from our sdFiles under sys/workshop/macros and sys/workshop/examples."""
    return ("sys/workshop/macros", "sys/workshop/examples")
