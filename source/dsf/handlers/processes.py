"""
Internal implementation of the API operations processes.pause, processes.resume, processes.restart (api_ops.py maps their named
arguments to the one-letter parameters below). Only the processes of process_catalog.PAUSABLE (data processes with a plain per-pass loop).

    <params> C"pause"|"resume"|"restart" P"<process>"

The controls are cooperative and in memory (heartbeats.py): the loop sees them at the top of its next pass. A thread blocked inside a call
cannot answer a restart: the answer says requested=true and the page watches restart_pending_s grow.

Answer: {"ok": true, "process": id, "action": ..., "requested": bool, "status": {...}} or {"ok": false, "error": <message>}.
"""
import json

import heartbeats
import process_catalog
import service_modules
import viewers
from messages import M


def _status(pid):
    st = dict(service_modules.status().get(pid) or {})
    snap = heartbeats.snapshot().get(pid) or {}
    for k in ("paused", "restart_pending", "restart_pending_s", "pausable"):
        st[k] = snap.get(k)
    return st


def run(params, bridge, config):
    action = str(params.get("C", "")).strip().lower()
    pid = str(params.get("P", "")).strip()
    if action not in ("pause", "resume", "restart"):
        return json.dumps({"ok": False, "error": "unknown action"})
    if not process_catalog.is_pausable(pid):
        return json.dumps({"ok": False, "error": M("processes_not_pausable", process=pid)})
    requested = True
    if action == "pause":
        heartbeats.pause(pid)
    elif action == "resume":
        heartbeats.resume(pid)
    else:
        effective, _ = heartbeats.launch_decision(pid)
        heartbeats.resume(pid)  # a restart brings it back running
        if effective == "idle":
            requested = False  # at rest (its plugin is not active): nothing is running to restart
        else:
            heartbeats.request_restart(pid)
    try:
        viewers.wake("health")  # publish the new state now: the page would otherwise see it at the next period (up to PUBLISH_S)
    except Exception:  # noqa: BLE001
        pass
    return json.dumps({"ok": True, "process": pid, "action": action, "requested": requested, "status": _status(pid)})
