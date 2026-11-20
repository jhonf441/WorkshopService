#!/usr/bin/env python3
"""Builds the service page (fast mode) and keeps the compiled DWC of that build for the simulator: dist/sim/<name>.

    set TALLER_DWC_SRC_36=C:\\Users\\<you>\\Projects\\dwc-src-slot3      (a FREE clone of the DWC 3.6 pool; never the default one blindly)
    python tools/dev/sim_build.py [name]         the compiled DWC goes to dist/sim/<name> (default: work)

Why: tools/dev/dwc_sim.js serves a real DWC, and DWC only loads the page as a chunk of its own build. scripts/build-plugin.js builds the
whole DWC with the page in it and leaves it in <clone>/dist; this script copies that folder out and puts the clone back as git has it
(src/plugins/imports.ts), which tools/build_36.py does not do. The zip of the build stays in dist/ as always; it is a test build: it is
not a release and is not copied anywhere else. `git add` new files of dwc36/ first (only tracked files are built).
The build takes the lock of the clone (<clone>.lock) as every build does. The copy runs right after the lock is released.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SIM = os.path.join(ROOT, "dist", "sim")


def main(argv):
    # one folder per build that somebody is looking at: `work` is the developer's, a validation point gets its own name (v1, v2 ...) and is
    # not written again, so a tester never finds another page under the one being tested
    name = argv[0] if argv else "work"
    if not name.replace("-", "").replace("_", "").isalnum():
        print("sim_build: the name of the build is letters, digits, - and _", file=sys.stderr)
        return 2
    out = os.path.join(SIM, name)
    clone = os.environ.get("TALLER_DWC_SRC_36")
    if not clone:
        print("sim_build: set TALLER_DWC_SRC_36 to a free clone of the DWC 3.6 pool (for example ...\\Projects\\dwc-src-slot3)", file=sys.stderr)
        return 2
    if os.path.isdir(clone.rstrip("/\\") + ".lock"):
        print("sim_build: %s.lock exists: another build holds that clone (or left it); choose another one" % clone, file=sys.stderr)
        return 2
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "src"], cwd=clone).decode("utf-8").strip()
    if dirty:
        print("sim_build: the clone has changes in src/ that are not from this build; not touching it:\n" + dirty, file=sys.stderr)
        return 2
    code = subprocess.call([sys.executable, os.path.join(ROOT, "tools", "build_36.py")], cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        if code == 0:
            built = os.path.join(clone, "dist")
            if not os.path.isfile(os.path.join(built, "index.html")):
                print("sim_build: the build left no compiled DWC in " + built, file=sys.stderr)
                return 1
            if os.path.isdir(out):
                shutil.rmtree(out)
            shutil.copytree(built, out, ignore=shutil.ignore_patterns("*.zip"))
            print("sim_build: compiled DWC with the page in " + out + "  (python tools/dev/run_sim.py --build " + name + ")")
    finally:
        # the packager registers the page in imports.ts and leaves it there: a clone with changes is skipped by the next build of the pool
        subprocess.call(["git", "checkout", "--", "src/plugins/imports.ts"], cwd=clone)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
