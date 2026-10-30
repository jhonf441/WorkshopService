#!/usr/bin/env python3
"""Builds the STRICT release zips of WorkshopService, one per DWC line (there is no universal zip any more):

    dist/release/WorkshopService-<ver>-dwc3.6.zip   dwcVersion "3.6", sbcDsfVersion "3.6": DWC 3.6.x / DSF 3.6.x install it, nothing else does
    dist/release/WorkshopService-<ver>-dwc3.7.zip   dwcVersion "3.7", sbcDsfVersion "3.7": DWC 3.7.x / DSF 3.7.x install it, nothing else does
    dist/release/SHA256SUMS.txt

    python tools/build_release.py                 3.6 build, 3.7 build, finalize, check, sums (about 10 minutes, mostly the 3.6 webpack build)
    python tools/build_release.py --reuse         reuse dist/WorkshopService-<ver>-dwc3.6.zip and -dwc3.7.zip already built (finalize, check, sums)
    python tools/build_release.py --check         only check what is in dist/release

Steps (each can be run alone): tools/build_36.py and tools/build_37.py make the line zips under dist/ (each holds its DWC clone's
<clone>.lock); this script rewrites each one with tools/release_zips.py finalize_zip (manifest values of the line, no source maps, .gz
companions of the big bundles) into dist/release/, then checks both with check_zip and writes SHA256SUMS.txt.

Both builds read the git-tracked files of this working copy: commit (or at least git add) before building, and build both lines from
the same commit. tools/build_universal.py (one zip for both lines) is DEPRECATED and not for release.

The TallerPlugins plugins are released the same way (python build.py --dwc both there); copy both sets into one folder
(TallerPlugins/dist/release) if you want `python build.py --check-release` to check the service zips next to the plugins.
"""
import json
import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import build_37 as b37  # noqa: E402
import release_zips  # noqa: E402

RELEASE = os.path.join(ROOT, "dist", "release")


def run(script):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subprocess.check_call([sys.executable, os.path.join(TOOLS, script)], cwd=ROOT, env=env)


def source_version():
    with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
        return json.load(f)["version"]


def line_zip(version, line):
    return os.path.join(ROOT, "dist", "WorkshopService-%s-dwc%s.zip" % (version, line))


def release_path(version, line):
    return os.path.join(RELEASE, release_zips.release_name("WorkshopService", version, line))


def check(version):
    """Problems of the two release zips and of SHA256SUMS.txt (empty list = clean)."""
    perms = release_zips._sbc_permissions(os.environ.get("TALLER_DWC_SRC_36") or os.path.join(os.path.expanduser("~"), "Projects", "dwc-src"))
    problems = []
    for line in release_zips.LINES:
        path = release_path(version, line)
        if not os.path.isfile(path):
            problems.append("missing " + path)
            continue
        found, info = release_zips.check_zip(path, line, "WorkshopService", version, perms=perms)
        found += b37.check_release(path)  # the service's own rules (no source maps, nothing local, nothing unlisted)
        print("%s  zip %d KB, js %d KB, %s" % (os.path.basename(path), info.get("zip_bytes", 0) // 1024, info.get("js_bytes", 0) // 1024, "ok" if not found else "FAIL"))
        problems += [os.path.basename(path) + ": " + p for p in found]
    problems += release_zips.check_sums(RELEASE)
    return problems


def main():
    args = sys.argv[1:]
    version = source_version()
    if "--check" not in args:
        if "--reuse" not in args:
            run("build_36.py")
            run("build_37.py")
        os.makedirs(RELEASE, exist_ok=True)
        for line in release_zips.LINES:
            src = line_zip(version, line)
            if not os.path.isfile(src):
                raise SystemExit("missing " + src)
            release_zips.finalize_zip(src, release_path(version, line), line)
        release_zips.write_sums(RELEASE)
    problems = check(version)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit("release is not clean")
    print("OK " + RELEASE)


if __name__ == "__main__":
    main()
