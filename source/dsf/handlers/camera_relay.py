"""
Internal implementation of the API operation(s) camera.status, camera.start, camera.stop, camera.detect, camera.flash, camera.image.get, camera.image.set, camera.service, camera.capture, camera.burst, camera.remove, camera.keep, camera.rename,
camera.edit, camera.rerender, camera.timelapse, camera.schedule, camera.token (api_ops.py maps their named
arguments to the one-letter parameters below).

Stops/starts the camera relay (see camera_relay.py, it runs INSIDE this
plugin since 2026-10-09 -- before it was a systemd --user service of
another user and a sudo rule was needed; no longer).

Usage: <params> S"stop" | S"start" | S"state"
     <params> S"detect" U"http://<ip>:81/stream"  asks a camera whether it is an ESP32-camera with a flash
     <params> S"flash" [C"<camera>"] O"1"|O"0"   flash of a camera on / off
     <params> S"image" [C"<camera>"]              image settings of an ESP32-camera: saved and live
     <params> S"image_set" [C"<camera>"] [P"<profile>"] [J"<json>"] [A"1"|A"0"]   applies and saves them
     <params> S"service" [J"<hex json>"]        service config (photo in
                                                             notices, drop, timelapse)
     <params> S"capture" [C"<camera>"]          saves a dated photo
     <params> S"burst" [C"<camera>"] N<count> G<gap s>   several photos in a row
     <params> S"remove" F"<file>" | S"keep" F"<file>" V1|0 | S"rename" F"<file>" N"<name>"   a photo or a video
     <params> S"edit" F"<video>" D<since s> [U<until s>] E<speed>  | S"rerender" F"<video>" [J"<json>"]   a new video from one
     <params> S"timelapse" [C"begin" N"<name>" [J"<json>"] | C"stop"]  timelapse by hand
     <params> S"schedule" C"schedule" D<since> U<until> [N"<name>"] | C"unschedule"  timelapse at a time
     <params> S"token"                         key of the day for the relay (with password)

It stops/starts the relay for EVERYONE who is watching it at that moment
-- meant for a button with a warning in the bar (not for closing the camera
panel of ONE screen, which must not touch the process). It does not change
config.json: when the plugin restarts it goes back to whatever
config["camera_relay"]["active"] says.

"""
import json

import camera_relay
from messages import M


def _object(raw):
    """A JSON object given as a dict or as its text: the dict, None when there is none, False when it is not an object."""
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return False
    return raw if isinstance(raw, dict) else False


def _write(action, params):
    """The writes of the relay that used to be POST routes of :8090 (remove, keep, rename, edit, rerender, burst): the same code, now behind the API, so each
    one is in the history and the audit with who did it and the role is the one of the operation."""
    file = str(params.get("F", "")).strip()
    cid = str(params.get("C", "")).strip() or camera_relay.MAIN
    try:
        if action == "remove":
            return camera_relay.remove(file)
        if action == "keep":
            return camera_relay.keep(file, str(params.get("V", "1")).strip().lower() in ("1", "true", "on", "yes"))
        if action == "rename":
            return camera_relay.rename(file, str(params.get("N", "")))
        if action == "burst":
            return camera_relay.burst(cid, params.get("N", 5), params.get("G", 1))
        if action == "edit":
            return camera_relay.edit(file, params.get("D", 0), params.get("U"), params.get("E", 1))
        over = _object(params.get("J"))
        if over is False:
            return {"ok": False, "error": M("camera_relay_invalid_numbers")}
        return camera_relay.rerender(file, over or {})
    except (TypeError, ValueError):
        return {"ok": False, "error": M("camera_relay_invalid_numbers")}


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
    if action == "detect":
        url = str(params.get("U", "")).strip()
        if not url.lower().startswith(("http://", "https://")):
            return M("camera_relay_error_address_has_start_http_e")
        return json.dumps(camera_relay.detect(url))
    if action == "flash":
        on = str(params.get("O", "")).strip().lower() in ("1", "true", "on", "yes")
        return json.dumps(camera_relay.flash(str(params.get("C", "")).strip() or camera_relay.MAIN, on))
    if action == "image":
        return json.dumps(camera_relay.image_get(str(params.get("C", "")).strip() or camera_relay.MAIN))
    if action == "image_set":
        profile = str(params.get("P", "")).strip() or None
        auto = None if "A" not in params else str(params.get("A")).strip().lower() in ("1", "true", "on", "yes")
        settings = params.get("J")
        if isinstance(settings, str):
            try:
                settings = json.loads(settings) if settings.strip() else None
            except ValueError:
                return "Error: the settings must be a JSON object"
        return json.dumps(camera_relay.image_set(str(params.get("C", "")).strip() or camera_relay.MAIN, profile, settings, auto))
    if action == "service":
        # without J: returns the service config; with J"<hex json>": changes it
        # (drop notice, limits, timelapse...) and saves it
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
        # C"begin" [N"<name>"] [J<settings of this take>] | C"stop" | (without C: state)
        c = str(params.get("C", "")).strip().lower()
        if c == "begin":
            over = _object(params.get("J"))
            if over is False:
                return json.dumps({"ok": False, "error": M("camera_relay_invalid_numbers")})
            return json.dumps(camera_relay.tl_begin_by_hand(str(params.get("N", "")), over))
        if c == "stop":
            return json.dumps(camera_relay.tl_stop())
        return json.dumps(camera_relay.tl_state())
    if action == "schedule":
        c = str(params.get("C", "")).strip().lower()
        if c == "unschedule":
            return json.dumps(camera_relay.tl_unschedule())
        if c != "schedule":
            return json.dumps(dict(camera_relay.tl_state(), ok=False, error=M("camera_relay_timelapse_action_must_be")))
        return json.dumps(camera_relay.tl_schedule(params.get("D"), params.get("U"), str(params.get("N", ""))))
    if action in ("remove", "keep", "rename", "edit", "rerender", "burst"):
        return json.dumps(_write(action, params))
    if action == "capture":
        return json.dumps(camera_relay.capture(str(params.get("C", camera_relay.MAIN)) or camera_relay.MAIN))
    return "Error: unknown camera action"
