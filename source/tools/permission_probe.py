#!/usr/bin/env python3
"""Exercises, through the public API, every feature of the service that needs a DSF permission and counts the AppArmor denials the kernel logs.

    python tools/permission_probe.py [--host <ip of the Pi>] [--ssh user@host]

Used to find the minimal set of sbcPermissions: remove ONE permission from the installed manifest, reload the plugin, run this, and read which
features fail. Everything it calls is a read, except two writes that store the value they just read (no net change).
Feature -> permission it should need:
  process  (launchProcesses)   : bridge.service (systemctl), lights.pi_pins (pinctrl), camera.status (ffmpeg probe), preflight.run
  system   (read/writeSystem)  : settings.get/merge of files under 0:/sys/workshop, jobs.preview (0:/gcodes)
  files    (fileSystemAccess)  : health.history (/proc, /sys), preflight.run, energy.period (database in /opt/dsf/conf), history.list
"""
import argparse
import json
import subprocess
import urllib.request

PROBES = [
    ("process", "bridge.service", {}),
    ("process", "lights.pi_pins", {}),
    ("process", "camera.status", {}),
    ("process", "preflight.run", {}),
    ("system", "settings.get", {"name": "buttons"}),
    ("system", "settings.get", {"name": "machine-calibrations"}),
    ("system", "settings.merge", {"name": "bridge", "patch": {}}),
    ("files", "health.history", {"range": "1h"}),
    ("files", "energy.period", {}),
    ("files", "history.list", {"from": "2026-10-29"}),
    ("files", "trace.since", {}),
]


def call(host, op, args):
    body = json.dumps({"op": op, "args": args}).encode()
    req = urllib.request.Request("http://%s/machine/WorkshopService/api" % host, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
        return bool(j.get("ok")), json.dumps(j.get("error") or "")[:140]
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:140]


def denied(ssh):
    if not ssh:
        return None
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", ssh, "journalctl -k --since '-10 min' | grep DENIED | grep -i workshopservice | tail -15"],
                         capture_output=True, text=True).stdout.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ssh", default="")
    a = ap.parse_args()
    bad = 0
    for kind, op, args in PROBES:
        ok, note = call(a.host, op, args)
        bad += 0 if ok else 1
        print("%-8s %-4s %-22s %s" % (kind, "OK" if ok else "FAIL", op, note))
    d = denied(a.ssh)
    if d is not None:
        print("\nAppArmor denials (last 10 min):\n" + (d or "none"))
    print("\n%d failing" % bad)


if __name__ == "__main__":
    main()
