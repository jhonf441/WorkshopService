#!/usr/bin/env python3
"""The bridge as a versioned artifact (ARCHITECTURE.md step 2): bridge/VERSION + bridge/bridge-manifest.json (version, contract, files, sha256).

    python bridge_manifest.py check    verify that VERSION, the manifest and the files agree (exit 1 and say what differs)
    python bridge_manifest.py write    rewrite the manifest from the files (run it after changing any file of the bridge)
    python bridge_manifest.py show     print name, version, contract and the file list

Nothing here changes what install.sh installs: the manifest only describes it, and tests/test_manifest.py fails when a file of the bridge
changes without the manifest (so a release is always one version, one contract, one list of hashes). Hashes are taken on the text with
line endings normalised to LF, so a checkout on Windows gives the same hash as the Pi.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "bridge-manifest.json")
VERSION_FILE = os.path.join(HERE, "VERSION")
NAME = "workshop-gcode-bridge"
# what install.sh puts on the Pi: the code (to /opt/workshop-bridge), the unit template and the installer itself
CODE = ("gcode_bridge.py", "live_resume.py", "live_stop.py")
OTHER = ("workshop-gcode-bridge.service", "install.sh")
FILES = CODE + OTHER


def sha256(path):
    with open(path, "rb") as fh:
        data = fh.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def source_value(name):
    with open(os.path.join(HERE, "gcode_bridge.py"), encoding="utf-8") as fh:
        m = re.search(r"^%s = ([0-9]+|\"[^\"]*\")" % name, fh.read(), re.M)
    if not m:
        raise SystemExit("gcode_bridge.py has no %s constant" % name)
    return json.loads(m.group(1))


def build():
    with open(VERSION_FILE, encoding="utf-8") as fh:
        version = fh.read().strip()
    return {"name": NAME, "version": version, "contract": source_value("CONTRACT"), "schema": source_value("SCHEMA"),
            "files": {f: {"sha256": sha256(os.path.join(HERE, f))} for f in FILES}}


def problems():
    """A list of what differs between VERSION, the manifest and the files; [] when everything agrees."""
    out = []
    try:
        built = build()
    except (OSError, SystemExit) as e:
        return ["cannot build the manifest: %s" % e]
    if built["version"] != source_value("VERSION"):
        out.append("VERSION says %s, gcode_bridge.VERSION says %s" % (built["version"], source_value("VERSION")))
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            have = json.load(fh)
    except (OSError, ValueError) as e:
        return out + ["bridge-manifest.json is missing or not valid: %s" % e]
    for key in ("name", "version", "contract", "schema"):
        if have.get(key) != built[key]:
            out.append("manifest %s is %r, the bridge says %r" % (key, have.get(key), built[key]))
    hf = have.get("files") or {}
    for f in sorted(set(hf) | set(built["files"])):
        if f not in hf:
            out.append("%s is not in the manifest" % f)
        elif f not in built["files"]:
            out.append("%s is in the manifest but is not a file of the bridge" % f)
        elif (hf[f] or {}).get("sha256") != built["files"][f]["sha256"]:
            out.append("%s changed since the manifest was written (run: python bridge_manifest.py write)" % f)
    return out


def write():
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(build(), fh, indent=1)
        fh.write("\n")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "write":
        write()
        print("wrote", MANIFEST)
        return 0
    if cmd == "show":
        b = build()
        print("%s %s (contract %s, schema %s)" % (b["name"], b["version"], b["contract"], b["schema"]))
        for f, d in b["files"].items():
            print("  %s  %s" % (d["sha256"][:12], f))
        return 0
    if cmd == "check":
        bad = problems()
        for p in bad:
            print("FAIL:", p)
        if not bad:
            print("manifest OK")
        return 1 if bad else 0
    print("usage: bridge_manifest.py [check|write|show]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
