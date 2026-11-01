"""Settings of the camera service (service.json "camera_service"): the defaults, the validation, and the settings of ONE timelapse take.
`service` is the one dictionary every module reads; it is changed in place (never rebound), so a module may hold it by name."""
import json
import re

import timelapse_look as look
from camera_context import MAIN


SERVICE_DEFAULT = {
    "notice_drop": True,        # warn if a camera stops answering
    "drop_s": 120,             # ... for more than this many seconds
    "captures_max": 300,        # the oldest are deleted
    "timelapses_max": 30,
    "screens_max": 4,         # remote screens per camera (0 = no cap)
    "load_fps": 5,             # frames/s to the remote ones with the system loaded
    "load_kbps": 3000,         # kB/s going out to screens: more = loaded
    "key": True,              # with a password in DWC, the remote ones ask for a key
    # timelapse.cameras: list of camera ids (empty = only timelapse.camera); armed: separate | mosaic | toggle
    "timelapse": {"active": False, "each_s": 10, "camera": "main", "cameras": [], "fps": 15,
                  "armed": "separate", "segment_s": 4, "fade_s": 0.8, "title": True, "final_s": 2,
                  "title_style": "small",  # "small" bottom right | "big" banner in the centre
                  "max_min": 720,       # maximum duration of a recording (manual or of a job)
                  "trigger": "time",  # "time" (every every_s) | "layer" (one photo per layer, 3D printing)
                  "stamp": False,       # date and time written on every photo
                  "deflicker": False,   # smooth out light changes (flicker) when assembling
                  **look.DEFAULTS},      # cinema controls: codec, framing, grade, shutter blend, interval ramp (timelapse_look.py)
    "presets": {},              # cinema presets saved by people: name -> the cinema keys of `timelapse` (timelapse_look.py)
    "timelapses_gb": 5,         # space for the videos: the oldest are deleted
    "delete_wait_h": 24,      # warning before deleting by itself (because of the caps): it is deleted if nobody does anything
}
service = json.loads(json.dumps(SERVICE_DEFAULT))


def mix(base, new):
    """`base` with the keys of `new` over it; only the keys `base` has are taken (a key of an older version is not carried)."""
    out = json.loads(json.dumps(base))
    for k, v in (new or {}).items():
        if k not in out:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def service_cfg():
    return json.loads(json.dumps(service))


ARMED = ("separate", "mosaic", "toggle")
TL_MAX_CAMERAS = 4


def _clean_tl(tl):
    """Validates a `timelapse` dict in place (the service defaults and the settings of ONE take share it)."""
    tl["each_s"] = max(2, min(600, int(tl.get("each_s") or 10)))
    tl["fps"] = round(look.fps_float(tl), 3)  # 5 to 120, also 23.976 / 29.97 / 59.94
    tl["active"] = bool(tl.get("active"))
    tl["camera"] = str(tl.get("camera") or MAIN)
    cams = []
    for c in tl.get("cameras") or []:
        c = re.sub(r"[^A-Za-z0-9_-]", "", str(c))[:40] or MAIN
        if c and c not in cams:
            cams.append(c)
    tl["cameras"] = cams[:TL_MAX_CAMERAS]
    if tl["cameras"]:
        tl["camera"] = tl["cameras"][0]
    tl["armed"] = tl.get("armed") if tl.get("armed") in ARMED else "separate"
    tl["segment_s"] = max(1.0, min(60.0, float(tl.get("segment_s") or 4)))
    tl["fade_s"] = max(0.0, min(3.0, float(tl.get("fade_s") or 0)))
    tl["title"] = bool(tl.get("title"))
    # 2026-10-10 ("the name at the start is huge: configurable or small at the bottom right"): small
    # (bottom right, goes away by itself) | big (banner in the centre)
    tl["title_style"] = tl.get("title_style") if tl.get("title_style") in ("small", "large") else "small"
    tl["final_s"] = max(0.0, min(10.0, float(tl.get("final_s") or 0)))
    tl["max_min"] = max(5, min(1440, int(tl.get("max_min") or 720)))
    tl["trigger"] = tl.get("trigger") if tl.get("trigger") in ("time", "layer") else "time"
    tl["stamp"] = bool(tl.get("stamp"))
    tl["deflicker"] = bool(tl.get("deflicker"))
    look.normalise(tl)
    return tl


PRESETS_MAX = 24
PRESET_KEYS = ("each_s", "fps", "armed", "title", "title_style", "final_s", "deflicker", "stamp") + tuple(look.DEFAULTS)


def _clean_presets(presets):
    """{name: settings}: at most PRESETS_MAX, names of 40 characters, only the keys a take may carry, each one validated like the defaults."""
    out = {}
    for name, v in (presets.items() if isinstance(presets, dict) else []):
        name = re.sub(r"\s+", " ", str(name)).strip()[:40]
        if not name or not isinstance(v, dict) or len(out) >= PRESETS_MAX:
            continue
        try:
            out[name] = {k: x for k, x in _clean_tl(dict({k: v[k] for k in v if k in PRESET_KEYS})).items() if k in PRESET_KEYS}
        except (TypeError, ValueError):
            continue
    return out


def change_service(config, changes):
    """Saves config.json "camera_service" (validating it)."""
    s = mix(service, changes)
    _clean_tl(s["timelapse"])
    s["presets"] = _clean_presets((changes or {}).get("presets", s.get("presets")))
    s["timelapses_gb"] = max(0.5, min(100.0, float(s.get("timelapses_gb") or 5)))
    s["delete_wait_h"] = max(1, min(168, int(s.get("delete_wait_h") or 24)))
    s["drop_s"] = max(30, min(3600, int(s.get("drop_s") or 120)))
    s["captures_max"] = max(10, min(5000, int(s.get("captures_max") or 300)))
    s["timelapses_max"] = max(1, min(500, int(s.get("timelapses_max") or 30)))
    s["screens_max"] = max(0, min(50, int(s.get("screens_max") if s.get("screens_max") is not None else 4)))
    s["load_fps"] = max(1, min(30, int(s.get("load_fps") or 5)))
    s["load_kbps"] = max(200, min(100000, int(s.get("load_kbps") or 3000)))
    for k in ("notice_drop", "key"):
        s[k] = bool(s.get(k))
    s = {k: v for k, v in s.items() if k in SERVICE_DEFAULT}  # nothing else is kept (the photo in the notices is the notifier's: notifier.py)
    config["camera_service"] = s
    service.clear()
    service.update(s)
    return service_cfg()


TAKE_KEYS = ("cameras", "each_s", "fps", "armed", "segment_s", "fade_s", "title", "title_style", "final_s", "max_min", "stamp", "deflicker") + tuple(look.DEFAULTS)


def take_cfg(overrides=None):
    """Settings of ONE take: the service defaults plus what the person chose for this take, frozen when it starts."""
    tl = json.loads(json.dumps(service["timelapse"]))
    for k, v in (overrides or {}).items():
        if k in TAKE_KEYS:
            tl[k] = v
    return _clean_tl(tl)
