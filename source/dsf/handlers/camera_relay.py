"""
Internal implementation of the API operation(s) camera.status, camera.start, camera.stop, camera.url, camera.service, camera.capture, camera.timelapse, camera.token (api_ops.py maps their named
arguments to the one-letter parameters below).

Stops/starts the camera relay (see camera_relay.py, it runs INSIDE this
plugin since 2026-10-09 -- before it was a systemd --user service of
another user and a sudo rule was needed; no longer).

Usage: <params> S"stop" | S"start" | S"estado"
     <params> S"url" U"http://<ip>:81/stream"   changes the camera (saves)
     <params> S"servicio" [J"<hex json>"]       service config (photo in
                                                             notices, drop, timelapse)
     <params> S"capturar" [C"<camera>"]         saves a dated photo
     <params> S"timelapse" [C"empezar" N"<name>" | C"parar"]  timelapse by hand
     <params> S"token"                         key of the day for the relay (with password)

It stops/starts the relay for EVERYONE who is watching it at that moment
-- meant for a button with a warning in the bar (not for closing the camera
panel of ONE screen, which must not touch the process). It does not change
config.json: when the plugin restarts it goes back to whatever
config["camera_relay"]["activo"] says.

"""
import json

import camera_relay
import net_guard
from messages import M


def run(params, bridge, config):
    action = str(params.get("S", "")).strip().lower()
    if action == "stop":
        camera_relay.request(False)
        return M("camera_relay_camera_process_stopped_cut_everyone_who")
    if action == "start":
        if not camera_relay.request(True):
            return M("camera_relay_error_starting_relay_no_camera_configured")
        return M("camera_relay_camera_process_started_again")
    if action == "state":
        return json.dumps(camera_relay.status())
    if action == "url":
        url = str(params.get("U", "")).strip()
        if not url.lower().startswith(("http://", "https://")):
            return M("camera_relay_error_address_has_start_http_e")
        if not net_guard.check_camera_url(url)[0]:
            return M("camera_relay_error_address_not_private_network")
        camera_relay.change_url(config, url)
        bridge.save_config()
        return M("camera_relay_relay_now_reads", url=url)
    if action == "service":
        # without J: returns the service config; with J"<hex json>": changes it
        # (photo in notices, drop notice, timelapse...) and saves it
        j = params.get("J")
        if j in (None, "", {}):
            return json.dumps(camera_relay.service_cfg())
        try:
            changes = j if isinstance(j, dict) else json.loads(bytes.fromhex(str(j).strip()).decode("utf-8"))
        except Exception:
            return "Error: the changes must be a JSON object"
        cfg = camera_relay.change_service(config, changes)
        bridge.save_config()
        return json.dumps(cfg)
    if action == "token":
        # key of the day to see the relay from another screen when DWC has a
        # password (this request already went through DWC's session)
        return json.dumps({"token": camera_relay.token()})
    if action == "timelapse":
        # C"empezar" [N"<name>"] | C"parar" | (without C: state)
        c = str(params.get("C", "")).strip().lower()
        if c == "begin":
            return json.dumps(camera_relay.tl_begin_by_hand(str(params.get("N", ""))))
        if c == "stop":
            return json.dumps(camera_relay.tl_stop())
        return json.dumps(camera_relay.tl_state())
    if action == "capture":
        return json.dumps(camera_relay.capture(str(params.get("C", camera_relay.MAIN)) or camera_relay.MAIN))
    return "Error: unknown camera action"
