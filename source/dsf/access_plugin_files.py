"""
access_plugin_files -- reads the permissions.json of the installed plugins, validates them (access_plugin_manifest) and registers the profiles of the
valid ones in access_base (phase 5 of informes/control-acceso/PLAN-ACCESO.md). The only module of the phase that touches files.

Where: <plugins folder>/<Id>/dsf/permissions.json, the place DSF puts the `dsf/` files of the zip of a plugin. The folder is paths.PLUGINS, or the
one in the environment variable WORKSHOP_PLUGINS_DIR (tests, other machines). Nothing is written. A manifest with an error registers NO profile (the people
who had its profiles attached keep nothing from them, which is the safe side); a plugin without a manifest has no profiles and is not governed.
"""
import json
import os

import access_base
import access_plugin_manifest as apm
import access_profile
import paths

FILE = os.path.join("dsf", "permissions.json")


def plugins_dir():
    return os.environ.get("WORKSHOP_PLUGINS_DIR") or paths.PLUGINS


def read_manifests(root=None):
    """({plugin Id: manifest}, findings): every <root>/<Id>/dsf/permissions.json that exists. A file that is too big or is not JSON is a finding."""
    root = root or plugins_dir()
    manifests, findings = {}, []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return manifests, findings
    for pid in names:
        path = os.path.join(root, pid, FILE)
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > apm.MAX_BYTES:
                raise ValueError("the file is bigger than %d bytes" % apm.MAX_BYTES)
            with open(path, encoding="utf-8") as f:
                manifests[pid] = json.load(f)
        except (OSError, ValueError) as e:
            findings.append({"plugin": pid, "code": "invalid_json", "severity": "error", "detail": str(e)[:200]})
    return manifests, findings


def refresh(known_ops, root=None):
    """Reads, validates and registers. Returns the report of access.plugins.validate: summary, findings, one row per plugin (its profiles) and the
    ids registered."""
    manifests, findings = read_manifests(root)
    findings = findings + apm.validate_all(manifests, known_ops)
    bad = {f["plugin"] for f in findings if f["severity"] == "error"}
    docs, rows = {}, []
    for pid, m in sorted(manifests.items()):
        mine = {}
        if pid not in bad and isinstance(m, dict):
            try:
                mine = apm.build_profiles(m)
            except access_profile.ProfileError as e:
                findings.append({"plugin": pid, "code": "invalid_manifest", "severity": "error", "detail": str(e)[:200]})
        docs.update(mine)
        rows.append({"plugin": pid, "namespace": m.get("namespace") if isinstance(m, dict) else None, "profiles": sorted(mine),
                     "valid": bool(mine), "operations": len(m.get("operations") or []) if isinstance(m, dict) else 0})
    access_base.set_plugin_profiles(docs)
    out = {"folder": root or plugins_dir(), "plugins": rows, "registered": sorted(docs), "findings": findings}
    out.update(apm.summary(findings))
    return out
