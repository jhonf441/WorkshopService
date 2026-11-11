#!/usr/bin/env python3
"""dsf/RELEASE.json inside the service release zip (plan F1, D-36): version, DWC line, commit and sha256 + size of every dsf/ and dwc/ file.

tools/install_service.sh verifies the zip against it before copying and checks the installed tree against it afterwards.
Service only (it is not part of tools/release_zips.py, which is mirrored byte for byte in TallerPlugins and serves every plugin).

    python tools/release_json.py <zip>      adds (or replaces) dsf/RELEASE.json in a finalized release zip and lists it in dsfFiles

tools/build_release.py calls add_to_zip() right after release_zips.finalize_zip().
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "RELEASE.json"
SCHEMA = 1
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # the same as release_zips: the same sources give the same bytes


def git_state(root=ROOT):
    """(commit, dirty) of the working copy; ("unknown", None) when git cannot answer. Never raises."""
    try:
        run = lambda *a: subprocess.check_output(["git", *a], cwd=root, stderr=subprocess.DEVNULL).decode("utf-8").strip()  # noqa: E731
        return run("rev-parse", "HEAD"), bool(run("status", "--porcelain", "--untracked-files=no"))
    except Exception:  # noqa: BLE001 - a missing git must not stop a build
        return "unknown", None


def release_manifest(manifest, files, commit, dirty=None):
    """`files` is {zip entry name: bytes}; only dsf/ and dwc/ entries are listed (not plugin.json, which the installer rewrites, nor this file)."""
    return {
        "schema": SCHEMA, "id": manifest.get("id"), "version": manifest.get("version"), "dwcVersion": manifest.get("dwcVersion"),
        "commit": commit, "dirty": dirty,
        "files": [{"path": n, "sha256": hashlib.sha256(d).hexdigest(), "size": len(d)}
                  for n, d in sorted(files.items()) if n.startswith(("dsf/", "dwc/")) and n != "dsf/" + NAME],
    }


def add_to_zip(path, root=ROOT):
    """Rewrites the zip at `path` with dsf/RELEASE.json (and "RELEASE.json" at the end of dsfFiles). Returns the RELEASE.json dict."""
    with zipfile.ZipFile(path) as z:
        files = {i.filename: z.read(i.filename) for i in z.infolist() if not i.filename.endswith("/")}
    manifest = json.loads(files["plugin.json"].decode("utf-8"))
    files.pop("dsf/" + NAME, None)
    commit, dirty = git_state(root)
    rel = release_manifest(manifest, files, commit, dirty)
    manifest["dsfFiles"] = [n for n in manifest.get("dsfFiles", []) if n != NAME] + [NAME]
    files["plugin.json"] = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    files["dsf/" + NAME] = (json.dumps(rel, indent=2) + "\n").encode("utf-8")
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ["plugin.json"] + sorted(k for k in files if k != "plugin.json"):
            zi = zipfile.ZipInfo(n, ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, files[n])
    os.replace(tmp, path)
    return rel


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    r = add_to_zip(sys.argv[1])
    print("RELEASE.json: %s %s commit %s, %d files" % (r["id"], r["version"], r["commit"], len(r["files"])))
