"""
Internal implementation of the API operations bridge.service and bridge.service.set (api_ops.py maps their named
arguments to the one-letter parameters below): state of the bridge unit of this Pi and start / stop of it.

Uso: <params> S"estado" | S"encender" | S"apagar"
"""
import json

import bridge_service
import live_job


def run(params, bridge, config):
    action = str(params.get("S", "state")).strip().lower()
    if action == "state":
        return json.dumps(bridge_service.status())
    if action in ("turnon", "poweroff"):
        if action == "poweroff" and live_job.read_in():
            # stopping the bridge cuts the program that is sending a live job
            return json.dumps({"ok": False, "error": "live_job", "state": bridge_service.status()})
        return json.dumps(bridge_service.put(action == "turnon"))
    return json.dumps({"ok": False, "error": "unknown action"})
