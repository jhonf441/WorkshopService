"""Run any test command with a throwaway temp folder, then delete it.

Why: many tests create folders in the system temp (tempfile.mkdtemp / fs.mkdtempSync) and some
never remove them (module-level mkdtemp whose tearDownModule does not run, setUp without cleanup,
empty sub-folders left behind). Thousands piled up in %LOCALAPPDATA%\\Temp (oct-nov 2026) and the
Windows user profile service walked all of them at every sign-in (335 s of black screen).
Python (TMP / TEMP / TMPDIR) and Node (os.tmpdir) both honour these variables, so one wrapper
covers every test without touching them.

Usage (from the repo root; run ONE test file per process as CLAUDE.md asks):

    python tools/run_tests.py --cwd dsf -- python -m unittest test_identity
    python tools/run_tests.py -- node tests/lines-frozen.test.js
    python tools/run_tests.py --keep -- python -m unittest test_x     # keep the folder to debug

The exit code is the one of the command. The folder is removed even when the command fails or is
interrupted (Ctrl+C); only a hard kill leaves it behind (the weekly Temp cleanup takes it).
"""
import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile


def _rm_readonly(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cwd", default=None, help="folder where the command runs (default: current)")
    ap.add_argument("--keep", action="store_true", help="do not delete the temp folder afterwards")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- command to run")
    args = ap.parse_args(argv)
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        ap.error("missing command (put it after --)")

    root = tempfile.mkdtemp(prefix="wsvc-run-")
    env = dict(os.environ, TMP=root, TEMP=root, TMPDIR=root)
    try:
        return subprocess.call(cmd, cwd=args.cwd, env=env)
    except KeyboardInterrupt:
        return 130
    finally:
        left = sum(len(d) + len(f) for _, d, f in os.walk(root))
        if args.keep:
            print("run_tests: temp folder kept: %s" % root, file=sys.stderr)
        else:
            shutil.rmtree(root, onerror=_rm_readonly)
            if os.path.exists(root):
                print("run_tests: could not remove %s (in use?)" % root, file=sys.stderr)
            elif left:
                print("run_tests: removed %d leftover temp entries" % left, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
