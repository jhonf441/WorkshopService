"""The image settings of the ESP32-cameras (informe 06, B-P6): camera.image.get / camera.image.set, and the loop that keeps them applied.

The ESP32-camera (CameraWebServer firmware) FORGETS everything when it restarts. What a technician chooses (a profile, a fine value, "follow the
job") is saved for every screen in 0:/sys/workshop/config/camera.json, written by this module only:

    {"version": 2, "cameras": {"<camera id>": {"profile": "balanced" | null, "auto": false, "settings": {"brightness": 1, ...}}}}

and the SERVICE applies it again (`image_tick`, the loop of the relay): when the camera reconnects, when it is found different from what is saved, and,
with "auto", when the profile that fits what the machine is doing changes (laser job running: "cut", else "balanced"). It used to be the browser's
(a timer and a re-apply of the viewer): it only worked with a screen looking, and two screens could undo each other. The numbers of the resolutions are
told by the service (`resolutions`), the page keeps no table of them.

A profile is a whole set of values; a fine value is one setting over it (choosing a profile drops the fine values, as the page always did).
"""
import json
import time

import camera_context
import camera_control
import camera_sources
import settings_store
from camera_context import MAIN
from messages import M

NAME = "camera"          # the settings store file (camera.json)
IMAGE_CHECK_S = 30       # a camera nobody is watching is asked how it is every this many seconds (a restarted camera is at its factory values)

# framesize of the firmware: the new one (esp32-camera >= 2.0, its /status carries "xclk") added 96x96, 128x128, 240x240 and 320x320 and shifted the
# numbers. Measured on the workshop camera 2026-10-09: 6=320x240 9=480x320 10=640x480 11=800x600 12=1024x768 13=1280x720 14=1280x1024; 15 (UXGA)
# and above fail with it. Vision keeps the same numbers (vision.py FS_SIZE: test_camera_image.py ties them).
FS_NEW = {"QQVGA": 1, "QVGA": 6, "CIF": 8, "HVGA": 9, "VGA": 10, "SVGA": 11, "XGA": 12, "HD": 13, "SXGA": 14, "UXGA": 15}
FS_OLD = {"QQVGA": 0, "QVGA": 4, "CIF": 5, "VGA": 6, "SVGA": 7, "XGA": 8, "SXGA": 9, "UXGA": 10}
FS_SIZE = {"QQVGA": (160, 120), "QVGA": (320, 240), "CIF": (400, 296), "HVGA": (480, 320), "VGA": (640, 480), "SVGA": (800, 600), "XGA": (1024, 768),
           "HD": (1280, 720), "SXGA": (1280, 1024), "UXGA": (1600, 1200)}
OFFERED = ("QVGA", "CIF", "VGA", "SVGA", "XGA", "HD", "SXGA")  # what a person may choose

# what may be sent to the camera: variable -> (lowest, highest); framesize goes by name. Nothing else reaches /control from here.
RANGES = {"quality": (8, 40), "brightness": (-2, 2), "contrast": (-2, 2), "saturation": (-2, 2), "ae_level": (-2, 2), "gainceiling": (0, 6),
          "awb": (0, 1), "aec": (0, 1), "aec2": (0, 1), "agc": (0, 1), "hmirror": (0, 1), "vflip": (0, 1), "lenc": (0, 1), "bpc": (0, 1), "wpc": (0, 1),
          "raw_gma": (0, 1)}


def _profile(framesize, quality, brightness, contrast, saturation, aec2, ae_level, gainceiling):
    return {"framesize": framesize, "quality": quality, "brightness": brightness, "contrast": contrast, "saturation": saturation, "awb": 1, "aec": 1,
            "aec2": aec2, "ae_level": ae_level, "agc": 1, "gainceiling": gainceiling, "lenc": 1, "bpc": 1, "wpc": 1, "raw_gma": 1}


PROFILES = {
    "balanced": _profile("SVGA", 12, 0, 0, 0, 0, 0, 2),       # good and smooth, for everyday use
    "cut": _profile("SVGA", 12, -1, 1, -1, 0, -2, 0),         # less exposure: the laser dot does not burn out the image
    "detail": _profile("XGA", 10, 0, 1, 0, 0, 0, 2),          # more resolution to align or focus
    "little_light": _profile("SVGA", 12, 1, 0, 0, 1, 2, 4),   # more exposure and gain, some noise
    "smooth": _profile("QVGA", 15, 0, 0, 0, 0, 0, 2),         # small light image for a weak Wi-Fi
}
_runtime = {}  # camera id -> {"connected": connected_since last applied at, "checked": when, "suggested": the profile last applied by "auto"}


def table_of(status):
    """The name -> number table of the firmware that answered `status` (the new one when it does not say: it is the one the workshop camera has)."""
    return FS_OLD if isinstance(status, dict) and status.get("xclk") is None else FS_NEW


def resolutions(status):
    """What the page offers as resolutions for that camera: [{name, number, width, height}]."""
    table = table_of(status)
    return [{"name": n, "number": table[n], "width": FS_SIZE[n][0], "height": FS_SIZE[n][1]} for n in OFFERED if n in table]


def clean_settings(raw):
    """(the settings a person may send, the name of the first one that is not valid or None): numbers clamped to their range, framesize by name."""
    out = {}
    for name, value in (raw.items() if isinstance(raw, dict) else []):
        if name == "framesize":
            if value not in FS_NEW:
                return {}, name
            out[name] = value
        elif name in RANGES:
            try:
                low, high = RANGES[name]
                out[name] = max(low, min(high, int(value)))
            except (TypeError, ValueError):
                return {}, name
        else:
            return {}, name
    return out, None


def _record(raw):
    """One camera of camera.json as it is used: profile (an id or None), auto, the fine settings that are valid."""
    raw = raw if isinstance(raw, dict) else {}
    settings, _bad = clean_settings(raw.get("settings"))
    return {"profile": raw.get("profile") if raw.get("profile") in PROFILES else None, "auto": bool(raw.get("auto")), "settings": settings}


def saved_all():
    """({camera id: record}, the revision camera.json was read at)."""
    got = settings_store.get(NAME)
    cams = got["value"].get("cameras") if isinstance(got["value"], dict) else None
    return {str(cid): _record(r) for cid, r in (cams.items() if isinstance(cams, dict) else [])}, got["rev"]


def _save(cid, record):
    """Writes the record of one camera (another camera's stays); once more if somebody saved in between."""
    for _ in range(2):
        got = settings_store.get(NAME)
        value = got["value"] if isinstance(got["value"], dict) else {}
        cams = dict(value.get("cameras") if isinstance(value.get("cameras"), dict) else {})
        cams[cid] = record
        try:
            settings_store.set(NAME, {"version": 2, "cameras": cams}, got["rev"])
            return
        except settings_store.Conflict:
            continue
    raise settings_store.Conflict(None, None)


def job_laser():
    """True while a laser job is running (the profile "cut" fits it)."""
    try:
        import machine_state
        st = (machine_state.get_status(timeout=3).get("state")) or {}
    except Exception:  # noqa: BLE001  no model yet: the machine is not doing anything we know of
        return False
    return st.get("status") == "processing" and st.get("machineMode") == "Laser"


def suggested_now():
    return "cut" if job_laser() else "balanced"


def wanted(record, suggested=None):
    """What the camera should have: the profile (the one that fits the machine now when "auto" is on), the fine settings over it."""
    profile = suggested if record["auto"] and suggested else record["profile"]
    out = dict(PROFILES.get(profile) or {})
    out.update(record["settings"])
    return out


def read_status(entry):
    """(the /status of the camera as a dict, None) or (None, why not)."""
    body, error = camera_control.ask(entry, "/status")
    if body is None:
        return None, error
    try:
        st = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return None, M("camera_control_not_answered", error="ValueError")
    return (st, None) if isinstance(st, dict) else (None, M("camera_control_not_answered", error="TypeError"))


def apply_settings(entry, settings, status=None):
    """Sends to the camera what differs from what it has now, one at a time (the ESP32 serves one request at a time), the resolution first (it
    restarts part of the sensor). (ok, error)."""
    if status is None:
        status, error = read_status(entry)
        if status is None:
            return False, error
    table = table_of(status)
    todo = []
    for name in sorted(settings, key=lambda k: k != "framesize"):
        value = table.get(settings[name]) if name == "framesize" else settings[name]
        if value is not None and status.get(name) != value:
            todo.append((name, value))
    for name, value in todo:
        _body, error = camera_control.ask(entry, f"/control?var={name}&val={value}", timeout=5, changes=True)
        if error is not None:
            return False, error
    return True, None


def _entry(cid):
    for c in camera_sources.camera_list():
        if c["id"] == cid:
            return c
    return None


def image_get(cid):
    """{ok, camera, reachable, profile, auto, settings, live, suggested, profiles, resolutions}: what is saved and what the camera says now."""
    cid = str(cid or MAIN)
    entry = _entry(cid)
    if entry is None:
        return {"ok": False, "error": M("camera_control_unknown_camera")}
    if not entry["esp32"]:
        return {"ok": False, "error": M("camera_image_not_esp32")}
    record = saved_all()[0].get(cid) or _record(None)
    live, _error = read_status(entry)
    return {"ok": True, "camera": cid, "reachable": live is not None, "profile": record["profile"], "auto": record["auto"], "settings": record["settings"],
            "live": live, "suggested": suggested_now(), "profiles": [{"id": k, "settings": v} for k, v in PROFILES.items()], "resolutions": resolutions(live)}


def image_set(cid, profile=None, settings=None, auto=None):
    """Applies and saves: `profile` (an id: it sets the profile and drops the fine values), `settings` (fine values over it), `auto` (follow the job).
    Nothing is saved when the camera did not take it. Answers like image_get."""
    cid = str(cid or MAIN)
    entry = _entry(cid)
    if entry is None:
        return {"ok": False, "error": M("camera_control_unknown_camera")}
    if not entry["esp32"]:
        return {"ok": False, "error": M("camera_image_not_esp32")}
    if profile is not None and profile not in PROFILES:
        return {"ok": False, "error": M("camera_image_unknown_profile")}
    fine, bad = clean_settings(settings)
    if bad:
        return {"ok": False, "error": M("camera_image_bad_setting", name=bad)}
    record = saved_all()[0].get(cid) or _record(None)
    now = {}
    if profile is not None:
        record["profile"], record["settings"] = profile, {}
        now.update(PROFILES[profile])
    if fine:
        record["settings"] = dict(record["settings"], **fine)
        now.update(fine)
    if auto is not None:
        record["auto"] = bool(auto)
    if now:
        ok, error = apply_settings(entry, now)
        if not ok:
            return {"ok": False, "error": error}
    _save(cid, record)
    _runtime.pop(cid, None)  # the loop looks at this camera again
    camera_context.log(f"camera {cid}: image settings saved")
    return image_get(cid)


def image_tick():
    """The loop of the relay (every few seconds): puts back what was saved on a camera that reconnected or that is not as saved, and follows the
    job with "auto". Only the cameras the relay serves (it sees them reconnect) and that have something saved."""
    saved, _rev = saved_all()
    if not saved:
        return
    now = time.time()
    suggested = None
    entries = {c["id"]: c for c in camera_sources.camera_list()}
    for cid, record in saved.items():
        entry, f = entries.get(cid), camera_sources.source(cid)
        if entry is None or f is None or not entry["esp32"] or not (record["profile"] or record["settings"] or record["auto"]):
            continue
        if suggested is None:
            suggested = suggested_now()
        st = _runtime.setdefault(cid, {"connected": None, "checked": 0.0, "suggested": None})
        reconnected = f.connected_since is not None and f.connected_since != st["connected"]
        due = not f.watched() and now - st["checked"] > IMAGE_CHECK_S
        followed = record["auto"] and suggested != st["suggested"]
        if not (reconnected or due or followed):
            continue
        st.update(connected=f.connected_since, checked=now, suggested=suggested)
        ok, error = apply_settings(entry, wanted(record, suggested))
        if not ok:
            camera_context.log(f"camera {cid}: could not apply the saved image settings ({error})")
