#!/usr/bin/env python3
"""Builds WorkshopService (service page + Python backend) for DuetWebControl 3.6 (Vue 2, Vuetify 2, Vuex, webpack).

    python tools/build_36.py --stage     only lay the plugin out in dist/stage36/WorkshopService
    python tools/build_36.py             stage, build with the DWC 3.6 clone, rewrite the zip, copy it to dist/WorkshopService-<ver>-dwc3.6.zip

Mirror of tools/build_37.py (read its docstring for the why). What is different here:
  * the page is dwc36/ (Vue 2), staged as dwc-src/ because that is the name scripts/build-plugin.js looks for; the catalogs are plain
    (vue-i18n 8 has no '|' '@' escaping rule for these texts, the 3.6 page always shipped them unescaped);
  * scripts/build-plugin.js (DWC 3.6) copies the WHOLE dsf/ folder of the plugin into the zip and ships plugin.json untouched, so
    the stage holds only the files listed in plugin.json dsfFiles that git tracks (no tests, fixtures, golden, secrets, config.json),
    and the manifest dsfFiles is written by this script in the same order the 3.7 packager produces (directory order of Windows,
    names compared upper-case, files and folders interleaved) with config.json removed, so universal_zip.py sees identical manifests;
  * the zip is rewritten after the build: manifest with dwcVersion "3.6", dwcFiles = the js / css the build made (no .gz, no .map),
    dsfFiles as above; entries are plugin.json, dwc/..., dsf/... and nothing else.

Environment: TALLER_DWC_SRC_36 (default ~/Projects/dwc-src, WITH node_modules), TALLER_DWC_LOCK_36 (default <clone>.lock).
The clone is shared: the build holds <clone>.lock (mkdir/rmdir) and never removes a lock it did not create. The 3.6 packager copies the
plugin into the clone's src/plugins/WorkshopService and removes it again; src/plugins/imports.ts must already import it (it does in the
owner's clone: that uncommitted edit is not touched by this script).
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_37 as b37  # noqa: E402

ROOT = b37.ROOT
DWC = os.environ.get("TALLER_DWC_SRC_36") or os.path.join(os.path.expanduser("~"), "Projects", "dwc-src")
LOCK = os.environ.get("TALLER_DWC_LOCK_36") or DWC + ".lock"
STAGE = os.path.join(ROOT, "dist", "stage36", "WorkshopService")
DWC_VERSION = "3.6"
PAGE_DIR = "dwc36"


def listing_order(directory, prefix=""):
    """Relative file paths of `directory` in the order the DWC packaging script (readdir on Windows) lists them: per folder, names
    upper-cased and compared, folders walked in place."""
    out = []
    for name in sorted(os.listdir(directory), key=lambda n: n.upper()):
        full = os.path.join(directory, name)
        rel = prefix + name
        if os.path.isdir(full):
            out.extend(listing_order(full, rel + "/"))
        else:
            out.append(rel)
    return out


def stage(guard=True):
    """Lays the plugin out for the DWC 3.6 build in dist/stage36/WorkshopService and returns that path."""
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)
    with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    for rel in b37.tracked(PAGE_DIR):
        dst = os.path.join(STAGE, "dwc-src", rel[len(PAGE_DIR) + 1:])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, rel), dst)

    in_git = set(b37.tracked("dsf"))
    for rel in manifest.get("dsfFiles", []):
        if "dsf/" + rel in in_git:
            dst = os.path.join(STAGE, "dsf", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, "dsf", rel), dst)
        else:
            print("not shipped (not tracked by git): dsf/" + rel, file=sys.stderr)

    manifest = b37.release_zips.line_manifest(manifest, DWC_VERSION)  # dwcVersion and sbcDsfVersion exactly "3.6"
    manifest["dwcFiles"] = []
    manifest["dsfFiles"] = listing_order(os.path.join(STAGE, "dsf"))
    manifest["rrfFiles"] = []
    with open(os.path.join(STAGE, "plugin.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if guard:
        b37.release_zips.stage_guard(STAGE, manifest["id"], DWC_VERSION)  # run-time guard: imported first by the page's index.js
    return STAGE


def rewrite_zip(built, out):
    """Rewrites the zip of scripts/build-plugin.js: plugin.json (dwcFiles filled), the js / css, the dsf/ files; no .gz, .map, folder entries."""
    with zipfile.ZipFile(built) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        manifest = json.loads(z.read("plugin.json").decode("utf-8"))
        dwc = sorted(n for n in names if n.startswith("dwc/") and n.endswith((".js", ".css")))
        dsf = [n for n in names if n.startswith("dsf/")]
        other = [n for n in names if n != "plugin.json" and not n.startswith(("dwc/", "dsf/"))]
        if other:
            raise SystemExit("unexpected entries in the 3.6 zip: " + ", ".join(other))
        listed = ["dsf/" + r for r in manifest["dsfFiles"]]
        if sorted(dsf) != sorted(listed):
            raise SystemExit("the 3.6 zip dsf/ does not match dsfFiles: " + str(sorted(set(dsf) ^ set(listed))[:10]))
        manifest["dwcFiles"] = [n[4:] for n in dwc]
        tmp = out + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as o:
            o.writestr("plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for n in dwc + listed:
                o.writestr(n, z.read(n))
    os.replace(tmp, out)


def build():
    stage()
    with open(os.path.join(STAGE, "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    b37.take_lock(lock=LOCK)
    try:
        subprocess.check_call(["node", os.path.join("scripts", "build-plugin.js"), STAGE], cwd=DWC, env=env)
        built = os.path.join(DWC, "dist", "WorkshopService-%s.zip" % version)
        if not os.path.isfile(built):
            raise SystemExit("scripts/build-plugin.js made no " + built + " (it reports its errors and still exits 0)")
        out = os.path.join(ROOT, "dist", "WorkshopService-%s-dwc%s.zip" % (version, DWC_VERSION))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        rewrite_zip(built, out)
    finally:
        os.rmdir(LOCK)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=DWC).decode("utf-8").strip()
    if dirty:
        print("note: the DWC 3.6 clone has uncommitted changes (check they are not from this build):\n" + dirty, file=sys.stderr)
    problems = b37.check_release(out)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit("the zip is not clean: " + out)
    print("OK " + out)
    return out


if __name__ == "__main__":
    if "--stage" in sys.argv[1:]:
        print(stage(guard="--no-guard" not in sys.argv[1:]))
    else:
        build()
