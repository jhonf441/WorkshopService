#!/usr/bin/env python3
"""Builds WorkshopService (service page + Python backend) for DuetWebControl 3.6 (Vue 2, Vuetify 2, Vuex, webpack).

    python tools/build_36.py --stage     only lay the plugin out in dist/stage36/WorkshopService
    python tools/build_36.py             FAST build (default): stage, build with the DWC 3.6 clone using tools/vue.config.fast.js (webpack cache,
                                         no maps, no .gz, no service worker), rewrite the zip, copy it to dist/WorkshopService-<ver>-dwc3.6.zip
    python tools/build_36.py --completa  the same with DWC's own config (also TALLER_BUILD_COMPLETO=1): the one to use before publishing
    python tools/build_36.py --reuse-bundle [--from <ver>]
                                         NO webpack: the js / css of an earlier 3.6 release zip plus the current dsf/ files and manifest.
                                         Only valid when the page did not change since that version (reuse_check); otherwise it refuses.
                                         The earlier zip is looked for in dist/release and TallerPlugins/releases/WorkshopService.
    Every zip gets dist/WorkshopService-<ver>-dwc3.6.mode (rapida | completa | reuse:<ver>); only 'completa' is meant for publishing.

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
FAST_CFG = os.path.join(ROOT, "tools", "vue.config.fast.js")
# what changes the js / css besides the page itself: the run-time guard that release_zips stages. (The fast config only drops maps, .gz and the
# service worker, which never reach the release zip, so a change of it does not invalidate a bundle.)
BUNDLE_INPUTS = ("dwc36", "tools/release_zips.py")


def build_mode(args=None):
    """'completa' (DWC's config) with --completa / TALLER_BUILD_COMPLETO=1 or when the fast config is missing, else 'rapida'."""
    args = sys.argv[1:] if args is None else args
    if "--completa" in args or os.environ.get("TALLER_BUILD_COMPLETO") == "1" or not os.path.isfile(FAST_CFG):
        return "completa"
    return "rapida"


def _version_key(v):
    return tuple(int(p) for p in v.split("."))


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def bundle_zips():
    """{version: path} of the 3.6 release zips found in dist/release and in TallerPlugins/releases/WorkshopService."""
    found = {}
    # TallerPlugins sits next to this repo, or two levels up when this is a worktree under Projects/_worktrees-agents; TALLER_RELEASES overrides
    folders = [os.path.join(ROOT, "dist", "release")]
    if os.environ.get("TALLER_RELEASES"):
        folders.append(os.environ["TALLER_RELEASES"])
    for up in (os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
        folders.append(os.path.join(up, "TallerPlugins", "releases", "WorkshopService"))
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.startswith("WorkshopService-") and name.endswith("-dwc3.6.zip"):
                found.setdefault(name[len("WorkshopService-"):-len("-dwc3.6.zip")], os.path.join(folder, name))
    return found


def reuse_check(base_version, git=_git):
    """Problems that forbid reusing the bundle of `base_version` (empty list = the page is the same). The release commit is the first one
    that wrote that version in plugin.json; the page inputs must be identical there and now, and clean in the working tree."""
    problems = []
    commits = git("log", "--reverse", "--format=%H", "-S" + '"version": "%s"' % base_version, "--", "plugin.json").splitlines()
    if not commits:
        return ["no commit set version %s in plugin.json, so the page of that bundle is unknown" % base_version]
    changed = git("diff", "--name-only", commits[0], "HEAD", "--", *BUNDLE_INPUTS).splitlines()
    if changed:
        problems.append("the page changed since %s (%s): build it in fast mode (%s)" % (base_version, commits[0][:8], ", ".join(changed[:8])))
    dirty = git("status", "--porcelain", "--", *BUNDLE_INPUTS).splitlines()
    if dirty:
        problems.append("uncommitted changes in the page inputs: " + ", ".join(l[3:] for l in dirty[:8]))
    return problems


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


def write_mode(version, mode):
    """dist/WorkshopService-<ver>-dwc3.6.mode: how the zip was made. Only 'completa' is meant for publishing."""
    with open(os.path.join(ROOT, "dist", "WorkshopService-%s-dwc%s.mode" % (version, DWC_VERSION)), "w", encoding="utf-8") as f:
        f.write(mode)


def reuse_bundle(from_version=None):
    """No webpack: the js / css of an earlier release zip, the dsf/ files and the manifest of the current tree. Returns the zip made."""
    stage(guard=False)
    with open(os.path.join(STAGE, "plugin.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    version = manifest["version"]
    zips = bundle_zips()
    earlier = sorted((v for v in zips if _version_key(v) < _version_key(version)), key=_version_key)
    base = from_version or (earlier[-1] if earlier else None)
    if not base or base not in zips:
        raise SystemExit("no earlier 3.6 zip to take the bundle from (looked for %s in dist/release and TallerPlugins/releases)" % (base or "any version"))
    problems = reuse_check(base)
    if problems:
        raise SystemExit("cannot reuse the bundle of %s:\n  %s" % (base, "\n  ".join(problems)))
    with zipfile.ZipFile(zips[base]) as z:
        dwc = sorted(n for n in z.namelist() if n.startswith("dwc/") and n.endswith((".js", ".css")))
        data = {n: z.read(n) for n in dwc}
    manifest["dwcFiles"] = [n[4:] for n in dwc]
    listed = ["dsf/" + r for r in manifest["dsfFiles"]]
    out = os.path.join(ROOT, "dist", "WorkshopService-%s-dwc%s.zip" % (version, DWC_VERSION))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as o:
        o.writestr("plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for n in dwc:
            o.writestr(n, data[n])
        for n in listed:
            with open(os.path.join(STAGE, n), "rb") as fh:
                o.writestr(n, fh.read())
    os.replace(tmp, out)
    problems = b37.check_release(out)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit("the zip is not clean: " + out)
    write_mode(version, "reuse:" + base)
    print("OK (bundle of %s reused, no webpack) %s" % (base, out))
    return out


def build(mode="completa"):
    stage()
    with open(os.path.join(STAGE, "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if mode == "rapida":
        env["VUE_CLI_SERVICE_CONFIG_PATH"] = FAST_CFG
        env["TALLER_DWC_SRC"] = DWC  # tools/vue.config.fast.js reads the clone from here
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
    write_mode(version, mode)
    print("OK (%s) %s" % (mode, out))
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--stage" in args:
        print(stage(guard="--no-guard" not in args))
    elif "--reuse-bundle" in args:
        reuse_bundle(args[args.index("--from") + 1] if "--from" in args else None)
    else:
        build(build_mode(args))
