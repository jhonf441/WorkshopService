#!/usr/bin/env python3
"""DEPRECATED, NOT FOR RELEASE. Use tools/build_release.py: one strict zip per DWC line.

Builds the ONE zip of WorkshopService that installs on DWC 3.6 and DWC 3.7: dist/WorkshopService-<ver>.zip (dwcVersion "3"). DWC 3.5, 3.8 and
any later 3.x accept a dwcVersion "3" as well, which is why it is not released any more (owner decision 2026-10-26).
Since the line builders now write sbcDsfVersion "3.6" / "3.7", the merger refuses their manifests: this script is kept as history only.

    python tools/build_universal.py                 3.6 build, 3.7 build, merge, release check
    python tools/build_universal.py --combine-only  reuse dist/WorkshopService-<ver>-dwc3.6.zip and -dwc3.7.zip, merge and check

Steps (each is a script of this repo or the merger):
  1. python tools/build_36.py                      -> dist/WorkshopService-<ver>-dwc3.6.zip   (DWC 3.6 clone, its own lock)
  2. python tools/build_37.py                      -> dist/WorkshopService-<ver>-dwc3.7.zip   (DWC 3.7 clone, its own lock)
  3. universal_zip.py <3.6 zip> <3.7 zip> -o ...   -> dist/WorkshopService-<ver>.zip
  4. python tools/build_37.py --check-release ...  (no source maps, nothing local, nothing unlisted)

Both builds read the git-tracked files of this working copy: commit (or at least git add) before building, and build the two lines
from the same commit; the merger refuses manifests or dsf/ payloads that differ.

Environment: TALLER_UNIVERSAL_ZIP = path of the merger (default ~/Projects/TallerPlugins/tools/universal_zip.py, the
TallerPlugins tools/universal_zip.py of branch dwc-lines/dwc-3.7); TALLER_DWC_SRC_36 / TALLER_DWC_SRC: the two DWC clones.
"""
import json
import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
MERGER = os.environ.get("TALLER_UNIVERSAL_ZIP") or os.path.join(
    os.path.expanduser("~"), "Projects", "_worktrees-37", "integration", "tools", "universal_zip.py")


def run(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subprocess.check_call([sys.executable, *args], cwd=ROOT, env=env)


def main():
    print("WARNING: build_universal.py is deprecated and NOT for release (dwcVersion 3 is accepted by any 3.x DWC). Release with tools/build_release.py.", file=sys.stderr)
    with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    dist = os.path.join(ROOT, "dist")
    z36 = os.path.join(dist, "WorkshopService-%s-dwc3.6.zip" % version)
    z37 = os.path.join(dist, "WorkshopService-%s-dwc3.7.zip" % version)
    out = os.path.join(dist, "WorkshopService-%s.zip" % version)
    if not os.path.isfile(MERGER):
        raise SystemExit("merger not found: %s (set TALLER_UNIVERSAL_ZIP)" % MERGER)
    if "--combine-only" not in sys.argv[1:]:
        run(os.path.join(TOOLS, "build_36.py"))
        run(os.path.join(TOOLS, "build_37.py"))
    for z in (z36, z37):
        if not os.path.isfile(z):
            raise SystemExit("missing " + z)
    run(MERGER, z36, z37, "-o", out)
    run(os.path.join(TOOLS, "build_37.py"), "--check-release", out)
    print("OK " + out)


if __name__ == "__main__":
    main()
