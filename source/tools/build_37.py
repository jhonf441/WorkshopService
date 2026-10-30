#!/usr/bin/env python3
"""Builds WorkshopService (service page + Python backend) for DuetWebControl 3.7 (Vue 3, Vuetify 4, Pinia, Vite).

    python tools/build_37.py --stage     only lay the plugin out in dist/stage37/WorkshopService (what the render tests use)
    python tools/build_37.py             stage, build with the DWC 3.7 clone, check the zip, copy it to dist/

Why a staging folder and not `node scripts/build-plugin.js <repo>` on the repo itself:
  * the DWC 3.7 build copies the WHOLE dsf/ folder into the zip. In a working copy that folder holds files that must never ship
    (the local config.json, secrets*.json, __pycache__, logs); the staging folder gets only the files listed in plugin.json
    `dsfFiles` that git tracks, so nothing local can get in;
  * vue-i18n 11 (DWC 3.7) reads '|' and '@' in a message as plural / link syntax: the staged catalogs have them written
    as {'|'} and {'@'} (the same rule as TallerPlugins build.py i18n_escape); the source catalogs stay plain text because
    dsf/published_texts.py writes the area "svc" of them and a test compares it;
  * the 3.7 manifest says dwcVersion 3.7 and its file lists (dwcFiles, dsfFiles) are filled by the DWC packaging script
    (scripts/build-plugin-pkg.js), not copied from the 3.6 build. The source plugin.json stays as it is.

The DWC clone is shared with the other port builds: only one build at a time. The build takes the lock folder
<clone>.lock (mkdir is atomic), waits for it when another build holds it, and always removes it (try/finally); it
never removes a lock it did not create. Afterwards `git status` of the clone must be empty (the build writes nothing there).

(The 3.6 line is tools/build_36.py and the whole chain is tools/build_universal.py; see docs/DWC-LINES.md.)

One zip for both DWC lines (what the owner installs): the other plugins depend on WorkshopService, and DWC 3.7 refuses a
manifest whose dwcVersion is "3.6" (prefix comparison), so the service must ship ONE zip with dwcVersion "3". Source plugin.json
says dwcVersion "3" and sbcDsfVersion "3" (DSF checks sbcDsfVersion with the same prefix rule in InstallPlugin.cs and
StartPlugin.cs, so "3" passes on 3.6 and on 3.7; "3.6" is refused by 3.7). Steps:
  1. 3.6 line zip: in the DWC 3.6.3 clone (dwc-src), `node scripts/build-plugin.js <this repo>` -> dwc-src/dist/WorkshopService-<ver>.zip
  2. 3.7 line zip: `python tools/build_37.py` -> dist/WorkshopService-<ver>-dwc3.7.zip
  3. combine (TallerPlugins branch dwc-3.7, tools/universal_zip.py; it drops .map and .map.gz, a stable release must have none):
     python tools/universal_zip.py <dwc-src>/dist/WorkshopService-<ver>.zip dist/WorkshopService-<ver>-dwc3.7.zip -o dist/WorkshopService-<ver>.zip
  4. check: python tools/build_37.py --check-release dist/WorkshopService-<ver>.zip   (no source maps, nothing local, nothing unlisted)
The combiner refuses the merge if the manifests or the dsf/ payload differ, so both builds must come from the same commit.

Environment: TALLER_DWC_SRC (default ~/Projects/dwc-src-37, WITH node_modules), TALLER_DWC_LOCK (default <clone>.lock).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_zips  # noqa: E402  (strict per-line manifest, run-time guard; copy of TallerPlugins tools/release_zips.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DWC = os.environ.get("TALLER_DWC_SRC") or os.path.join(os.path.expanduser("~"), "Projects", "dwc-src-37")
LOCK = os.environ.get("TALLER_DWC_LOCK") or DWC + ".lock"
STAGE = os.path.join(ROOT, "dist", "stage37", "WorkshopService")
DWC_VERSION = "3.7"

# names that must never be inside the zip (checked on the finished archive)
FORBIDDEN = re.compile(
    r"(^|/)(__pycache__/|[^/]*\.pyc$|[^/]*secret[^/]*$|[^/]*\.log$|[^/]*\.db$|[^/]*\.bak$|config\.json$|workshop-users[^/]*$|"
    r"test_[^/]*\.py$|\.git[^/]*$|node_modules/|[^/]*\.map$)"
)


def i18n_escape(text):
    """'|' and '@' become the literal placeholders {'|'} and {'@'} ('<' too: vue-i18n 11 warns about messages that look like HTML,
    e.g. "BRIDGE USE <name>"); placeholders like {name} stay as they are."""
    parts = re.split(r"(\{[^{}]*\})", text)
    return "".join(p if (p.startswith("{") and p.endswith("}")) else p.replace("|", "{'|'}").replace("@", "{'@'}").replace("<", "{'<'}") for p in parts)


def i18n_escape_tree(node):
    if isinstance(node, str):
        return i18n_escape(node)
    if isinstance(node, dict):
        return {k: i18n_escape_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [i18n_escape_tree(v) for v in node]
    return node


def tracked(path):
    """Files under `path` (relative to the repo) that git tracks."""
    out = subprocess.check_output(["git", "ls-files", "--", path], cwd=ROOT).decode("utf-8")
    return [line for line in out.splitlines() if line]


def stage(guard=True):
    """Lays the plugin out for the DWC build in dist/stage37/WorkshopService and returns that path."""
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)
    with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    # the page: every tracked file of dwc-src/, the catalogs with '|' and '@' written as vue-i18n 11 wants
    for rel in tracked("dwc-src"):
        src = os.path.join(ROOT, rel)
        dst = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if rel.startswith("dwc-src/i18n/") and rel.endswith(".json"):
            with open(src, encoding="utf-8") as f:
                data = json.load(f)
            with open(dst, "w", encoding="utf-8", newline="\n") as f:
                json.dump(i18n_escape_tree(data), f, ensure_ascii=False, indent="\t")
        else:
            shutil.copyfile(src, dst)

    # the backend: only what the manifest lists AND git tracks (config.json is the local configuration of a machine)
    in_git = set(tracked("dsf"))
    files = []
    for rel in manifest.get("dsfFiles", []):
        if "dsf/" + rel in in_git:
            files.append(rel)
            dst = os.path.join(STAGE, "dsf", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, "dsf", rel), dst)
        else:
            print("not shipped (not tracked by git): dsf/" + rel, file=sys.stderr)

    # the 3.7 manifest: dwcVersion and sbcDsfVersion exactly "3.7" (DWC and DSF compare by prefix: this is what makes them refuse the
    # other lines); the file lists are filled by the DWC packaging script
    manifest = release_zips.line_manifest(manifest, DWC_VERSION)
    manifest["dwcFiles"] = []
    manifest["dsfFiles"] = []
    manifest["rrfFiles"] = []
    with open(os.path.join(STAGE, "plugin.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if guard:  # the render tests stage without it: their fake host has no window.DWC.version
        release_zips.stage_guard(STAGE, manifest["id"], DWC_VERSION)  # run-time guard: imported first by the page's index.js
    return STAGE


def check_zip(path):
    """The archive holds the manifest, the page bundle and the listed backend files, and nothing local. Returns the problems."""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        manifest = json.loads(z.read("plugin.json").decode("utf-8"))
    for n in names:
        if FORBIDDEN.search(n):
            problems.append("must not ship: " + n)
    for rel in manifest.get("dsfFiles", []):
        if "dsf/" + rel not in names:
            problems.append("listed in dsfFiles but missing: dsf/" + rel)
    for rel in manifest.get("dwcFiles", []):
        if "dwc/" + rel not in names:
            problems.append("listed in dwcFiles but missing: dwc/" + rel)
    for n in names:
        if n.endswith("/") or n == "plugin.json":
            continue
        if n.startswith("dsf/"):
            if n[4:] not in manifest.get("dsfFiles", []):
                problems.append("in the zip but not listed in dsfFiles: " + n)
        elif n.startswith("dwc/"):
            if n[4:] not in manifest.get("dwcFiles", []):
                problems.append("in the zip but not listed in dwcFiles: " + n)
        else:
            problems.append("unexpected entry: " + n)
    if manifest.get("dwcVersion") != DWC_VERSION:
        problems.append("dwcVersion is %r" % manifest.get("dwcVersion"))
    if not any(n.startswith("dwc/js/WorkshopService") for n in names):
        problems.append("no page bundle dwc/js/WorkshopService-*.js")
    return problems


def check_release(path):
    """A zip meant to be installed (the combined one, or a line zip): no source maps, nothing local, nothing unlisted. Returns the problems.
    `python tools/build_37.py --check-release <zip>`"""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        manifest = json.loads(z.read("plugin.json").decode("utf-8"))
    for n in names:
        if n.endswith((".map", ".map.gz")):
            problems.append("source map in a release zip: " + n)
        elif FORBIDDEN.search(n):
            problems.append("must not ship: " + n)
    for rel in manifest.get("dwcFiles", []):
        if rel.endswith((".map", ".map.gz")):
            problems.append("dwcFiles lists a source map: " + rel)
    for rel in manifest.get("dsfFiles", []):
        if "dsf/" + rel not in names:
            problems.append("listed in dsfFiles but missing: dsf/" + rel)
    return problems


def take_lock(wait_s=1800, lock=None):
    """mkdir is atomic: whoever creates the folder builds. Waits while another build holds it. `lock` defaults to the 3.7 clone's."""
    lock = lock or LOCK
    end = time.time() + wait_s
    while True:
        try:
            os.mkdir(lock)
            return
        except FileExistsError:
            if time.time() > end:
                raise SystemExit("another build holds %s for more than %d s: not touching it" % (lock, wait_s))
            print("waiting: another build holds " + lock, flush=True)
            time.sleep(15)


def build():
    stage()
    with open(os.path.join(STAGE, "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    take_lock()
    try:
        # on Windows `node` is found through PATH; the script is DWC's own packaging script (it fills dwcFiles / dsfFiles)
        subprocess.check_call(["node", os.path.join("scripts", "build-plugin-pkg.js"), STAGE], cwd=DWC, env=env)
    finally:
        os.rmdir(LOCK)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=DWC).decode("utf-8").strip()
    if dirty:
        print("WARNING: the DWC clone is not clean after the build:\n" + dirty, file=sys.stderr)
    built = os.path.join(STAGE, "WorkshopService-%s.zip" % version)
    problems = check_zip(built)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit("the zip is not clean: " + built)
    out = os.path.join(ROOT, "dist", "WorkshopService-%s-dwc%s.zip" % (version, DWC_VERSION))
    shutil.copyfile(built, out)
    print("OK " + out)
    return out


if __name__ == "__main__":
    if "--check-release" in sys.argv[1:]:
        found = check_release(sys.argv[sys.argv.index("--check-release") + 1])
        print(chr(10).join(found) if found else "release zip is clean")
        sys.exit(1 if found else 0)
    if "--stage" in sys.argv[1:]:
        print(stage(guard="--no-guard" not in sys.argv[1:]))
    else:
        build()
