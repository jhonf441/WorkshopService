"""
Camera service of the workshop: a 1-to-many MJPEG relay, photos, dated captures, timelapse of the jobs and a warning if a camera goes down. It runs INSIDE the plugin's
backend (it used to be ~/camera-relay/camera_relay.py as a systemd --user service, and WorkshopService stopped/started it with sudo).

Why it exists: the ESP32-camera (stock firmware app_httpd.cpp) only serves ONE /stream client at a time reliably. The relay opens ONE connection to each camera (only while
someone is watching) and forwards the same bytes to every browser.

2026-10-10 ("refine and improve the camera service"): several cameras at once, state and statistics, a warning if one goes down, a photo in the notifications,
dated captures and timelapse.

Cameras:
  main       config.json "camera_relay": {"activo", "url", "puerto": 8090}
  others     0:/sys/workshop/config/cameras.json (the viewer's list, WorkshopCamera plugin): the ones that are ESP32-CAMs with their own address (and "relay" != false)

Routes (CORS only for the own DWC origin, port 8090). The contract is versioned: /state carries `proto` (camera_proto.py); the old Spanish
names (/estado, /capturar, /borrar, ?archivo=, ?accion=empezar...) are still accepted through camera_proto.upgrade():
  /stream /snapshot /control /status      the main one (as always: Vision and the screens use these)
                                          /snapshot?fresh=1: always a new photo; after a /control only frames that arrived more than 1 s later count
  /c/<id>/stream|snapshot|control|status  another camera of the list
  /state                                  JSON: proto, each camera (connected / reconnecting / down, fps, kB/s, photo delay, clients) + config, timelapse, load
  /detect?url=<stream>                    JSON: whether it is an ESP32-camera and whether it has a flash
  POST /capture?c=<id>                    saves a photo with date, camera, job and position -> JSON
  /captures  /captures/<file>             list (JSON) and the image
  POST /remove?file=<file>                deletes a capture or a timelapse
  POST /rename?file=&name=                the visible name (capture or timelapse)
  GET /per_delete  POST /keep?file=&value=1|0   what is about to be deleted by itself (caps, with a warning) and keeping (never deleted by itself)
  POST /edit?file=&since=&until=&speed=   NEW video, trimmed / with another speed (the original stays)
  /timelapses  /timelapses/<file>         list (JSON) and the video / thumbnail (?download=1 -> as a file)
  /key?t=<key>  (only from the Pi)        {"requires", "ok"}: so other services (Vision :8095) ask for the same key
  POST /timelapse?action=schedule&since=&until=[&name=]  start / stop at a time
  POST /timelapse?action=unschedule       (epoch in seconds; schedule.json)
  GET /timelapse/last?c=<camera>          last photo of what is being recorded (live)
  POST /timelapse?action=begin[&name=]    manual timelapse (without a job; up to max_min) with the cameras and the assembly of the config; stopping assembles the video
  POST /timelapse?action=stop

Only ONE timelapse session exists at a time (the global `_tl`): the one of a job and the manual one share it. A manual start is refused
while one is recording, and the one of a job does not start while a manual one runs. Separating them would need one `_tl` per session,
its own frames folder and its own assembly slot; not done on purpose (the ffmpeg assembly is also one at a time on this Pi).

Files in /opt/dsf/sd/workshop/camera/ (they survive reinstalling the plugin; before /opt/dsf/sd/camara/): captures/ (jpg + json), timelapse/ (mp4 + jpg thumbnail), frames/ (temporary).

Screens and load (2026-10-10: "what happens if many requests reach the relay, can the DWC password be used, is there a purge"):
  - each screen receives the last frame at its own pace (own thread): a slow screen no longer slows down the others or the camera; if it accepts nothing for 5 s it is dropped
  - cap on remote screens per camera ("screens_max"): when exceeded the oldest is cut (it gets a frame with the reason); one that was cut less than 60 s ago cannot kick another out (no ping-pong)
  - load (temperature, CPU, kB/s going out; temperature and CPU are NOT measured here: camera_load.py reads what health_poller publishes): loaded -> the remote screens receive "load_fps" frames/s; critical -> 2 per camera remain. It is noted in Activity (type camera_load)
  - with a password in DWC (M551) and "clave" active, the remote screens need the day's key (?t= or cookie workshop_camera): the API (camera_relay) gives it S"token", which requires the DWC session
  - local (127.0.0.1: kiosk, Vision, timelapse) does not count, is not cut and asks for no key

Service config: config.json "camera_service" (see SERVICE_DEFAULT).
Control: the API (camera_relay) S"stop"|"start"|"estado"|"url"|"servicio".

"""
import job_states
import paths
import glob
import hashlib
import hmac
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import camera_access
import camera_load
import camera_proto
import heartbeats
import service_modules
import messages
import net_guard
import timelapse_look as look
from messages import M, J, B, of_row, dumps_params

UPSTREAM_RETRY_DELAY = 2.0
BOUNDARY = b"123456789000000000000987654321"  # the same as the ESP32-camera's
UPSTREAM_READ_CHUNK = 8192
SNAPSHOT_MAX_AGE = 2.0
DEFAULT_PORT = 8090
CAMERAS_FILE = paths.CONFIG_DIR + "/cameras.json"
# outside 0:/sys on purpose (2026-10-11): videos and photos weigh GB and must not show in DWC's
# System editor or in the copies of sys/; the camera does not need to lock files
DATA_DIR = paths.CAMERA_DIR
# The relay's key does NOT go on the card (DWC's file API would serve it): it goes in DSF's
# configuration folder, which the web does not serve and which uninstalling a plugin does not delete
# (2026-10-11, "how passwords are managed").
KEY_FILE = paths.CONF + "/workshop-camera.key"
MAIN = "main"
CAPTURES_DIR = os.path.join(DATA_DIR, "captures")
TIMELAPSE_DIR = os.path.join(DATA_DIR, "timelapse")
FRAMES_DIR = os.path.join(DATA_DIR, "frames")
LUTS_DIR = os.path.join(DATA_DIR, "luts")
VIDEO_EXT = (".mp4", ".mov")  # h264 / h265 go in mp4, ProRes / DNxHR in mov (timelapse_look.extension)
SIDE_FILES = (".jpg", ".json", "-frames.zip")  # what travels with a video: thumbnail, data, kept stills
JOB_ACTIVE = job_states.CAMERA_ACTIVE

SERVICE_DEFAULT = {
    "photo_notice": True,         # photo attached to the end / error / pause notices
    "notice_camera": "main",     # camera of the notices' photo / video (each type can choose another: notifier.py)
    "notice_drop": True,        # warn if a camera stops answering
    "drop_s": 120,             # ... for more than this many seconds
    "captures_max": 300,        # the oldest are deleted
    "timelapses_max": 30,
    "screens_max": 4,         # remote screens per camera (0 = no cap)
    "load_fps": 5,             # frames/s to the remote ones with the system loaded
    "load_kbps": 3000,         # kB/s going out to screens: more = loaded
    "key": True,              # with a password in DWC, the remote ones ask for a key
    # camaras: lista (vacia = solo "camara"); armado: separados | mosaico | alternar
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

_cfg = {"url": "", "port": DEFAULT_PORT, "bind": "0.0.0.0"}
_service = json.loads(json.dumps(SERVICE_DEFAULT))
_want = [False]  # what was asked for (config or API call start/stop)
_server = [None]
_log = [print]
_bridge = [None]
_sources = {}  # id -> _Fuente
_sources_lock = threading.Lock()
_cameras_mtime = [None]


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _base_of(url):
    """Where /capture /control /status are. On the ESP32-camera the video goes through :81 and the rest through :80; other cameras have it on the same port."""
    u = urllib.parse.urlsplit(url or "")
    if not u.hostname:
        return ""
    port_name = f":{u.port}" if u.port and u.port != 81 else ""
    return f"{u.scheme or 'http'}://{u.hostname}{port_name}"


LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
THROWN_WAIT_S = 60
_kicked = {}  # ip -> when one of its screens was cut because of the cap
_echo_same = {}  # ip -> when a screen of its own cut another from the same ip
_load = camera_load.new_state()


class _Client:
    """A screen watching: it keeps only the last frame (if it is slow it skips frames instead of falling behind or slowing down the others)."""

    null = False

    def __init__(self, ip):
        self.ip = ip
        self.local = ip in LOCAL
        self.since = time.time()
        self.frame = None
        self.new = threading.Event()
        self.shut = None  # None or the reason (text) why it is cut
        self.sent = 0
        self.bytes_sec = []  # (t, n) of what was sent
        self.last_sending = 0.0

    def put(self, frame):
        self.frame = frame
        self.new.set()

    def echar(self, reason):
        self.shut = reason
        self.new.set()

    def summary(self):
        return {"ip": self.ip, "local": self.local, "since_s": int(time.time() - self.since), "sent": self.sent}


class _Source:
    """A camera: its connection (only while someone watches), the last photo and its numbers."""

    def __init__(self, cid, label, url):
        self.id = cid
        self.label = label or cid
        self.url = url
        self.lock = threading.Lock()
        self.clients = []
        self.running = False
        self.snap = {"bytes": None, "kind": "image/jpeg", "ts": 0.0}
        self.snap_lock = threading.Lock()
        # numbers (state of the relay, not of the camera: with nobody watching nothing is measured)
        self.status = "without_use"  # without_use | conectando | conectada | reconectando
        self.last_error = None
        self.connected_since = None
        self.frames_sec = []  # times of the last frames (for fps)
        self.bytes_sec = []  # (t, n)
        self.frames_total = 0
        self.last_frame = 0.0
        self.delay_photo_ms = None
        self.reconnects = 0
        # down (measured by the watchdog even if nobody watches)
        self.last_ok = time.time()
        self.drop_notified = False
        self.esp32 = None
        self.flash = None
        # after a /control (e.g. Vision changes framesize) the saved photo and the frames still on
        # their way are from the old setting
        self.invalidated_en = 0.0

    @property
    def base(self):
        return _base_of(self.url)

    # ---- video ----
    def _broadcast(self, frame):
        with self.lock:
            cs = list(self.clients)
        for c in cs:
            c.put(frame)

    def allow(self, cli):
        """Adds a screen respecting the cap. False = it does not get in (one was cut recently and it cannot kick another out)."""
        if cli.null or cli.local:
            with self.lock:
                self.clients.append(cli)
            return True
        cap = _cap_screens()
        with self.lock:
            remote = sorted((c for c in self.clients if not c.null and not c.local and not c.shut), key=lambda c: c.since)
            while cap and len(remote) >= cap:
                # first an old one from the SAME screen (it reloaded the page)
                same = [c for c in remote if c.ip == cli.ip]
                if same:
                    # several tabs of the same PC that reconnect by themselves (the map, the viewer)
                    # would kick each other out non-stop: once per minute
                    if time.time() - _echo_same.get(cli.ip, 0) < THROWN_WAIT_S:
                        return False
                    _echo_same[cli.ip] = time.time()
                    old = same[0]
                    old.echar(M("camera_relay_cut_same_computer_opened_another_tab", label=self.label, cap=cap))
                else:
                    if time.time() - _kicked.get(cli.ip, 0) < THROWN_WAIT_S:
                        return False
                    old = remote[0]
                    _kicked[old.ip] = time.time()
                    old.echar(M("camera_relay_cut_too_many_screens_watching_maximum", label=self.label, cap=cap))
                    _log[0](f"camera {self.id}: limit of {cap} screens, the oldest one is cut ({old.ip})")
                remote.remove(old)
            self.clients.append(cli)
        return True

    def drop(self, cli):
        with self.lock:
            if cli in self.clients:
                self.clients.remove(cli)

    def _count(self, buf, chunk):
        """Splits the JPEGs of the stream: counts frames and keeps the last (so the photo comes from the video that already arrives, without asking the camera for another)."""
        t = time.time()
        self.bytes_sec.append((t, len(chunk)))
        buf += chunk
        while True:
            i = buf.find(b"\xff\xd8")
            if i < 0:
                return b""
            j = buf.find(b"\xff\xd9", i + 2)
            if j < 0:
                return buf[i:] if len(buf) - i < 2_000_000 else b""
            frame = buf[i:j + 2]
            buf = buf[j + 2:]
            self.frames_total += 1
            self.last_frame = t
            self.last_ok = t
            self.frames_sec.append(t)
            with self.snap_lock:
                self.snap.update(bytes=frame, kind="image/jpeg", ts=t)
            self._broadcast(frame)

    def _loop(self):
        try:
            while True:
                with self.lock:
                    if not self.clients:
                        return
                try:
                    self.status = "connecting" if self.status == "without_use" else "reconnecting"
                    with urllib.request.urlopen(urllib.request.Request(self.url), timeout=10) as resp:
                        self.status = "connected"
                        self.connected_since = time.time()
                        self.last_error = None
                        buf = b""
                        while True:
                            with self.lock:
                                if not self.clients:
                                    return
                            chunk = resp.read(UPSTREAM_READ_CHUNK)
                            if not chunk:
                                break
                            buf = self._count(buf, chunk)
                except Exception as e:
                    self.last_error = f"{type(e).__name__}: {e}"
                    self.reconnects += 1
                    self.status = "reconnecting"
                    _log[0](f"camera {self.id}: connection error ({e!r}), retrying")
                    time.sleep(UPSTREAM_RETRY_DELAY)
        finally:
            with self.lock:
                self.running = False
                self.status = "without_use"
                self.connected_since = None

    def ensure(self):
        with self.lock:
            if self.running:
                return
            self.running = True
        threading.Thread(target=self._loop, daemon=True, name=f"cam-{self.id}").start()

    # ---- foto ----
    def invalidate(self):
        self.invalidated_en = time.time()

    def photo(self, max_age=SNAPSHOT_MAX_AGE, timeout=5, fresh=False):
        """(bytes, type) of a recent photo; None if the camera does not answer. fresh=True: always a new one from the camera (/capture)."""
        with self.snap_lock:
            age = time.time() - self.snap["ts"]
            cache, type_name = self.snap["bytes"], self.snap["kind"]
            current = self.snap["ts"] > self.invalidated_en + 1.0
        if not fresh and cache is not None and current and age < max_age:
            return cache, type_name
        if not self.base:
            return (cache, type_name) if cache and current and not fresh else None
        t0 = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + "/capture"), timeout=timeout) as resp:
                body = resp.read()
                type_name = resp.headers.get("Content-Type", "image/jpeg")
        except Exception as e:
            self.last_error = f"foto: {type(e).__name__}: {e}"
            return (cache, type_name) if cache and current and not fresh else None
        self.delay_photo_ms = int((time.time() - t0) * 1000)
        self.last_ok = time.time()
        with self.snap_lock:
            self.snap.update(bytes=body, kind=type_name, ts=time.time())
        return body, type_name

    # ---- numeros ----
    def summary(self):
        t = time.time()
        self.frames_sec = [x for x in self.frames_sec if t - x < 5]
        self.bytes_sec = [x for x in self.bytes_sec if t - x[0] < 5]
        with self.lock:
            n = len(self.clients)
        watching = self.status == "connected"
        drop_s = t - self.last_ok
        return {
            "id": self.id,
            "name": self.label,
            "url": self.url,
            "state": self.status,
            "clients": n,
            "screens": [c.summary() for c in list(self.clients) if not c.null],
            "fps": round(len(self.frames_sec) / 5.0, 1) if watching else None,
            "kbps": round(sum(b for _, b in self.bytes_sec) / 5.0 / 1024, 1) if watching else None,
            "frames": self.frames_total,
            "last_frame_s": round(t - self.last_frame, 1) if self.last_frame else None,
            "delay_photo_ms": self.delay_photo_ms,
            "connected_s": int(t - self.connected_since) if self.connected_since else None,
            "reconnections": self.reconnects,
            "last_error": self.last_error,
            "without_response_s": int(drop_s) if drop_s > 45 else 0,
            "drop": self.drop_notified,
            "esp32": self.esp32,
            "flash": self.flash,
        }


# ---------------- camera list ----------------

def _read_cameras_extra():
    try:
        with open(CAMERAS_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return []
    out = []
    for c in (d or {}).get("cameras") or []:
        cid = str(c.get("id") or "")
        url = str(c.get("url") or "").strip()
        if not cid or _id(cid) == MAIN or not c.get("esp32") or c.get("relay") is False:
            continue
        if not url.lower().startswith("http") or "[HOSTNAME]" in url:
            continue
        if urllib.parse.urlsplit(url).port == int(_cfg["port"]):
            continue  # it is already this relay
        out.append((re.sub(r"[^A-Za-z0-9_-]", "", cid)[:40], str(c.get("name") or cid), url))
    return out


def _sync_sources(force=False):
    try:
        mt = os.path.getmtime(CAMERAS_FILE)
    except OSError:
        mt = None
    if not force and mt == _cameras_mtime[0]:
        return
    _cameras_mtime[0] = mt
    want = {}
    if _cfg["url"]:
        want[MAIN] = ("Principal", _cfg["url"])
    for cid, label, url in _read_cameras_extra():
        want[cid] = (label, url)
    with _sources_lock:
        for cid in list(_sources):
            if cid not in want or _sources[cid].url != want[cid][1]:
                f = _sources.pop(cid)
                with f.lock:
                    cs = list(f.clients)
                    f.clients.clear()  # the browsers reconnect by themselves
                for c in cs:
                    c.echar("")
        for cid, (label, url) in want.items():
            if cid not in _sources:
                _sources[cid] = _Source(cid, label, url)
            else:
                _sources[cid].label = label


def _id(cid):
    """Camera Id with the old alias: "principal" (or empty) -> "main"."""
    cid = str(cid or "")
    return MAIN if cid in ("", "main") else cid


def source(cid):
    with _sources_lock:
        return _sources.get(_id(cid))


# ---------------- ESP32: deteccion ----------------

def detect(url):
    """Asks the camera whether it is an ESP32-camera (CameraWebServer: /status with framesize) and whether it has a flash (led_intensity in /status)."""
    base = _base_of(url)
    if not base or not net_guard.check_camera_url(base)[0]:
        return {"ok": False, "error": M("camera_relay_invalid_address")}
    try:
        with urllib.request.urlopen(base + "/status", timeout=4) as r:
            st = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        # "reachable": False = the camera did not answer (busy, Wi-Fi drop, rebooting): that says nothing about what the camera is
        return {"ok": True, "reachable": False, "esp32": False, "flash": False, "detail": M("camera_relay_no_status_endpoint", error=type(e).__name__)}
    es = isinstance(st, dict) and "framesize" in st
    # the firmware reports led_intensity -1 when the board has no flash LED (ESP32-S3 cameras)
    flash = es and isinstance(st.get("led_intensity"), (int, float)) and st["led_intensity"] >= 0
    return {"ok": True, "reachable": True, "esp32": bool(es), "flash": bool(flash), "framesize": st.get("framesize") if es else None}


def _detect_sources():
    """Once per source: esp32 / flash for the viewer."""
    with _sources_lock:
        fs = list(_sources.values())
    for f in fs:
        if f.esp32 is None:
            d = detect(f.url)
            # an answer only counts when the camera answered: one failed /status (the camera's Wi-Fi drops, it is busy
            # streaming) used to be stored as "not an ESP32, no flash" for good and the viewer hid the flash button
            if d.get("ok") and d.get("reachable", True):
                f.esp32, f.flash = d.get("esp32"), d.get("flash")


# ---------------- servicio: config ----------------

def _mix(base, new):
    out = json.loads(json.dumps(base))
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def service_cfg():
    return json.loads(json.dumps(_service))


def _clean_tl(tl):
    """Validates a `timelapse` dict in place (the service defaults and the settings of ONE take share it)."""
    tl["each_s"] = max(2, min(600, int(tl.get("each_s") or 10)))
    tl["fps"] = round(look.fps_float(tl), 3)  # 5 to 120, also 23.976 / 29.97 / 59.94
    tl["active"] = bool(tl.get("active"))
    tl["camera"] = _id(tl.get("camera"))
    cams = []
    for c in tl.get("cameras") or []:
        c = _id(re.sub(r"[^A-Za-z0-9_-]", "", str(c))[:40])
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
    s = _mix(_service, changes)
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
    for k in ("photo_notice", "notice_drop", "key"):
        s[k] = bool(s.get(k))
    s["notice_camera"] = _id(re.sub(r"[^A-Za-z0-9_-]", "", str(s.get("notice_camera") or ""))[:40])
    config["camera_service"] = s
    _service.clear()
    _service.update(s)
    return service_cfg()


# ---------------- machine state (for captures / timelapse) ----------------

def _machine():
    """{job, status, pos} from the object model of the single subscription (machine_state)."""
    try:
        import machine_state
        st = machine_state.get_status(timeout=3, max_age_s=3)
    except Exception:
        return {"job": None, "state": None, "pos": None, "layer": None}
    status = (st.get("state") or {}).get("status")
    label = (((st.get("job") or {}).get("file") or {}).get("fileName")) or None
    live = None
    b = _bridge[0]
    if b is not None:
        tv = (getattr(b, "payload", {}) or {}).get("liveJob") or {}
        if tv.get("active"):
            import live_job
            live = live_job.shown_name(tv.get("name"))
    pos = {}
    for a in ((st.get("move") or {}).get("axes") or []):
        if a and a.get("visible", True) and a.get("letter") in ("X", "Y", "Z"):
            pos[a["letter"]] = a.get("machinePosition")
    job = None
    if status in JOB_ACTIVE and label:
        job = os.path.basename(label)
    elif live and status == "busy":
        job = live
    layer = (st.get("job") or {}).get("layer")
    return {"job": job, "state": status, "pos": pos, "layer": layer}


# ---------------- capturas ----------------

def _mark(jpeg, lines):
    """Writes the lines below the photo (PIL). If it fails, the photo stays as it is."""
    try:
        import io
        from PIL import Image, ImageDraw, ImageFont
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
        w, h = im.size
        length = max(12, int(h / 34))
        try:
            source_ = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", length)
        except Exception:
            try:
                source_ = ImageFont.load_default(size=length)
            except TypeError:
                source_ = ImageFont.load_default()
        height = (length + 6) * len(lines) + 8
        layer = Image.new("RGBA", (w, height), (0, 0, 0, 150))
        im.paste(layer, (0, h - height), layer)
        d = ImageDraw.Draw(im)
        y = h - height + 5
        for ln in lines:
            d.text((8, y), ln, fill=(255, 255, 255), font=source_)
            y += length + 6
        out = io.BytesIO()
        im.save(out, "JPEG", quality=90)
        return out.getvalue()
    except Exception as e:
        _log[0](f"camera: could not mark the photo ({e!r})")
        return jpeg


def _text_pos(pos):
    if not pos:
        return ""
    return " ".join(f"{k}{v:.2f}" for k, v in pos.items() if isinstance(v, (int, float)))


def capture(cid=MAIN, max_age=1.0):
    f = source(cid)
    if f is None:
        return {"ok": False, "error": M("camera_relay_camera_does_not_exist")}
    r = f.photo(max_age=max_age)
    if not r:
        return {"ok": False, "error": M("camera_relay_camera_did_not_answer")}
    m = _machine()
    ts = time.time()
    date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    lines = [date + "  " + f.label]
    extra = []
    if m["job"]:
        extra.append(str(M("camera_relay_photo_job", job=m["job"])))
    if m["pos"]:
        extra.append(_text_pos(m["pos"]))
    if extra:
        lines.append("  ".join(extra))
    img = _mark(r[0], lines)
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    base = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)) + "-" + f.id
    n, file = 0, base + ".jpg"
    while os.path.exists(os.path.join(CAPTURES_DIR, file)):
        n += 1
        file = f"{base}-{n}.jpg"
    with open(os.path.join(CAPTURES_DIR, file), "wb") as fh:
        fh.write(img)
    meta = {"file": file, "ts": date, "camera": f.id, "camera_name": f.label, "job": m["job"], "pos": m["pos"], "bytes": len(img)}
    with open(os.path.join(CAPTURES_DIR, file[:-4] + ".json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    _check_limits()
    return dict(meta, ok=True)


BURST_MAX = 30
_burst = {"left": 0}


def burst(cid=MAIN, count=5, gap=1.0):
    """`count` captures in a row, `gap` seconds apart, made in the background (the answer comes at once, the photos appear in the gallery)."""
    try:
        count, gap = int(count), float(gap)
    except (TypeError, ValueError):
        return {"ok": False, "error": M("camera_relay_invalid_numbers")}
    count, gap = max(2, min(BURST_MAX, count)), max(0.3, min(10.0, gap))
    if source(cid) is None:
        return {"ok": False, "error": M("camera_relay_camera_does_not_exist")}
    if _burst["left"]:
        return {"ok": False, "error": M("camera_relay_burst_running")}
    _burst["left"] = count

    def _do():
        try:
            for i in range(count):
                t0 = time.time()
                capture(cid, max_age=min(1.0, gap * 0.6))  # a still that is not older than the gap: two photos are never the same one
                _burst["left"] = count - i - 1
                if i < count - 1:
                    time.sleep(max(0.0, gap - (time.time() - t0)))
        except Exception as e:
            _log[0](f"camera: burst failed ({e!r})")
        finally:
            _burst["left"] = 0

    threading.Thread(target=_do, daemon=True, name="camera-burst").start()
    return {"ok": True, "count": count, "gap_s": gap}


def list_items_captures():
    out = []
    for j in sorted(glob.glob(os.path.join(CAPTURES_DIR, "*.json")), reverse=True):
        try:
            with open(j, encoding="utf-8") as fh:
                m = json.load(fh)
        except Exception:
            continue
        pb = _pb_read().get(m.get("file"))
        if pb:
            m["pending_delete_until"] = pb["until"]
        out.append(m)
    return out


def _videos_list():
    return [v for e in VIDEO_EXT for v in glob.glob(os.path.join(TIMELAPSE_DIR, "*" + e))]


def list_items_timelapses():
    out = []
    for v in sorted(_videos_list(), reverse=True):
        meta = {}
        try:
            with open(v[:-4] + ".json", encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            pass
        meta.update(file=os.path.basename(v), bytes=os.path.getsize(v), thumbnail=os.path.basename(v)[:-4] + ".jpg")
        pb = _pb_read().get(meta["file"])
        if pb:
            meta["pending_delete_until"] = pb["until"]
        out.append(meta)
    return out


def _meta_of(file):
    """(path of the .json, dict) of a capture or a timelapse; (None, None) if it does not exist."""
    file = os.path.basename(file or "")
    if not re.match(r"^[\w.-]+\.(jpg|mp4|mov)$", file):
        return None, None
    for folder in (TIMELAPSE_DIR, CAPTURES_DIR):
        if os.path.exists(os.path.join(folder, file)):
            j = os.path.join(folder, file[:-4] + ".json")
            try:
                with open(j, encoding="utf-8") as fh:
                    return j, json.load(fh)
            except Exception:
                return j, {}
    return None, None


def rename(file, label):
    """Changes the visible name (the file stays the same)."""
    j, meta = _meta_of(file)
    if j is None:
        return {"ok": False, "error": M("camera_relay_file_does_not_exist")}
    meta["name"] = re.sub(r"\s+", " ", str(label or "")).strip()[:80]
    with open(j, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    return {"ok": True, "name": meta["name"]}


_editing = {"file": None}


def edit(file, since=0.0, until=None, speed=1.0):
    """New video (the original stays): trimmed [from, to] seconds and with another speed (0.25 to 8). It is assembled in the background."""
    file = os.path.basename(file or "")
    src = os.path.join(TIMELAPSE_DIR, file)
    if not file.endswith(VIDEO_EXT) or not os.path.isfile(src):
        return {"ok": False, "error": "no existe ese video"}
    if _editing["file"]:
        return {"ok": False, "error": M("camera_relay_another_video_already_being_edited")}
    if _without_space():
        return {"ok": False, "error": M("camera_relay_little_space_left_system_less")}
    since = max(0.0, float(since or 0))
    until = float(until) if until not in (None, "") else None
    velocity = max(0.25, min(8.0, float(speed or 1)))
    if until is not None and until <= since + 0.2:
        return {"ok": False, "error": M("camera_relay_end_has_after_start")}
    n = 1
    while os.path.exists(os.path.join(TIMELAPSE_DIR, f"{file[:-4]}-ed{n}.mp4")):
        n += 1
    output = os.path.join(TIMELAPSE_DIR, f"{file[:-4]}-ed{n}.mp4")
    _, meta = _meta_of(file)
    meta = dict(meta or {})
    _editing["file"] = os.path.basename(output)

    def _do():
        try:
            cmd = ["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{since:.2f}"]
            if until is not None:
                cmd += ["-to", f"{until:.2f}"]
            cmd += ["-i", src, "-an", "-vf", f"setpts=PTS/{velocity:g}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", output]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if r.returncode != 0 or not os.path.exists(output):
                _log[0](f"camera: could not edit {file} ({(r.stderr or '')[-300:]})")
                return
            shutil.copyfile(src[:-4] + ".jpg", output[:-4] + ".jpg") if os.path.exists(src[:-4] + ".jpg") else None
            label = (meta.get("name") or meta.get("job") or file[:-4])
            parts = []
            if since > 0 or until is not None:
                parts.append(f"{since:g}-{until:g} s" if until is not None else str(M("camera_relay_edited_from_second", since=since)))
            if abs(velocity - 1) > 1e-6:
                parts.append(f"x{velocity:g}")
            meta.update(name=f"{label} ({', '.join(parts) or M('camera_relay_edited_copy')})", editado_de=file)
            with open(output[:-4] + ".json", "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False)
            _check_limits()
            _log[0](f"camera: video edited {os.path.basename(output)}")
        except Exception as e:
            _log[0](f"camera: could not edit {file} ({e!r})")
        finally:
            _editing["file"] = None

    threading.Thread(target=_do, daemon=True, name="camera-edit").start()
    return {"ok": True, "file": os.path.basename(output)}


def rerender(file, overrides=None):
    """New video (the original stays) from the stills kept with it, with another look: codec, framing, grade, speed, stabilization. Assembled in the background.
    It starts from the settings the original was made with (`look` in its .json) and applies `overrides` on top."""
    file = os.path.basename(file or "")
    if not re.match(r"^[\w.-]+\.(mp4|mov)$", file) or not os.path.isfile(os.path.join(TIMELAPSE_DIR, file)):
        return {"ok": False, "error": M("camera_relay_file_does_not_exist")}
    zip_path = os.path.join(TIMELAPSE_DIR, file[:-4] + "-frames.zip")
    if not os.path.isfile(zip_path):
        return {"ok": False, "error": M("camera_relay_frames_not_kept")}
    if _editing["file"] or _tl["assembling"]:
        return {"ok": False, "error": M("camera_relay_another_video_already_being_edited")}
    if _without_space():
        return {"ok": False, "error": M("camera_relay_little_space_left_system_less")}
    _, meta = _meta_of(file)
    meta = dict(meta or {})
    wanted = dict(meta.get("look") or {})
    wanted.update({k: v for k, v in (overrides or {}).items() if k in PRESET_KEYS})
    cfg = _take_cfg(wanted)
    cfg["keep_frames"] = False  # the zip of the original is already there
    n = 1
    while any(os.path.exists(os.path.join(TIMELAPSE_DIR, f"{file[:-4]}-rr{n}{e}")) for e in VIDEO_EXT):
        n += 1
    stem = f"{file[:-4]}-rr{n}"
    d = os.path.join(FRAMES_DIR, stem)
    _editing["file"] = stem

    def _do():
        try:
            cams, count, times = look.unpack_frames(zip_path, d)
            if not count:
                raise RuntimeError("the zip has no stills")
            labels = list(meta.get("cameras") or [])
            names = {c: (labels[i] if len(labels) == len(cams) else c) for i, c in enumerate(cams)}
            info = {k: meta[k] for k in ("job", "start", "duration_s", "manual") if k in meta}
            info.update(name=f"{meta.get('name') or meta.get('job') or file[:-4]} ({M('camera_relay_new_look')})", rerendered_from=file)
            made = tl_arm(d, cams, names, count, cfg, info, times)
            _check_limits()
            _log[0](f"camera: video rebuilt from {file} ({', '.join(made) or 'nothing'})")
        except Exception as e:
            _log[0](f"camera: could not rebuild {file} ({e!r})")
        finally:
            shutil.rmtree(d, ignore_errors=True)
            _editing["file"] = None

    threading.Thread(target=_do, daemon=True, name="camera-rerender").start()
    return {"ok": True, "file": stem}


def delete(file):
    file = os.path.basename(file or "")
    if not re.match(r"^[\w.-]+\.(jpg|mp4|mov)$", file):
        return False
    done = False
    for folder in (CAPTURES_DIR, TIMELAPSE_DIR):
        p = os.path.join(folder, file)
        if os.path.exists(p):
            for ext in SIDE_FILES + VIDEO_EXT:
                try:
                    os.remove(os.path.splitext(p)[0] + ext)
                    done = True
                except OSError:
                    pass
    return done


# ---------------- timelapse ----------------
# It records from one or several cameras at once (frames/<session>/<camera>/00001.jpg, the same
# number = the same moment in all of them) and when done assembles the video according to "armado":
# separados one video per camera
# mosaico all at once in a grid (up to 4)
# alternar a single video that passes from one camera to another every "segment_s" seconds of video,
# with a fade of "fade_s" (0 = cut)
# "titulo": banner at the start with the name and the date (over the first still frame); "final_s":
# it stays still on the last frame.
# It starts by itself with each job ("activo") or by hand (POST /timelapse).

ARMED = ("separate", "mosaic", "toggle")
TL_MAX_FRAMES = 20000
TL_MAX_CAMERAS = 4
TL_TITLE_S = 2.5
TL_DISK_MIN = 2 * 1024 ** 3  # with less free it does not start and it stops what is recording


def _disk_free():
    try:
        return shutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else "/").free
    except OSError:
        return None


def _without_space():
    idle = _disk_free()
    return idle is not None and idle < TL_DISK_MIN
SOURCE_TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ONE timelapse session at a time: a job's and a manual one share this global (see the module docstring).
_tl = {"dir": None, "job": None, "start": None, "n": 0, "last": 0.0, "cameras": [], "manual": False,
       "assembling": None, "tomando": False, "skip": None, "nulls": {}, "layer_last": None, "last_frames": {},
       "cfg": None, "times": []}


class _Null:
    """Fake client: keeps a camera's video open without /capture (non-ESP32) while recording, so there is always a recent frame."""

    null = True
    local = True
    shut = None
    since = 0.0

    def put(self, _frame):
        pass

    def echar(self, _reason):
        pass

    def summary(self):
        return {}


TAKE_KEYS = ("cameras", "each_s", "fps", "armed", "segment_s", "fade_s", "title", "title_style", "final_s", "max_min", "stamp", "deflicker") + tuple(look.DEFAULTS)


def _take_cfg(overrides=None):
    """Settings of ONE take: the service defaults plus what the person chose for this take, frozen when it starts."""
    tl = json.loads(json.dumps(_service["timelapse"]))
    for k, v in (overrides or {}).items():
        if k in TAKE_KEYS:
            tl[k] = v
    return _clean_tl(tl)


def _tl_cfg():
    """Settings of the take being recorded (frozen); the service defaults when nothing is recorded."""
    return _tl["cfg"] or _service["timelapse"]


def _tl_cameras():
    tl = _tl["cfg"] or _service["timelapse"]
    ids = [_id(c) for c in (tl.get("cameras") or []) if source(c) is not None] or [_id(tl.get("camera"))]
    if source(ids[0]) is None:
        ids = [MAIN]
    return ids[:TL_MAX_CAMERAS]


def _tl_begin(label, manual=False, overrides=None):
    os.makedirs(FRAMES_DIR, exist_ok=True)
    _tl["cfg"] = _take_cfg(overrides)
    folder = time.strftime("%Y%m%d-%H%M%S") + "-" + (re.sub(r"[^\w-]+", "_", os.path.splitext(label)[0])[:40] or "timelapse")
    d = os.path.join(FRAMES_DIR, folder)
    cams = _tl_cameras()
    nulls = {}
    for cid in cams:
        os.makedirs(os.path.join(d, cid), exist_ok=True)
        f = source(cid)
        if f is not None and not f.base:
            n = _Null()
            with f.lock:
                f.clients.append(n)
            f.ensure()
            nulls[cid] = n
    _tl.update(dir=d, job=label, start=time.time(), n=0, last=0.0, cameras=cams, manual=bool(manual), nulls=nulls,
               layer_last=None, last_frames={}, times=[])
    _log[0](f"camera: timelapse of {label} starts ({', '.join(cams)}{', by hand' if manual else ''})")


def _tl_release_nulls():
    for cid, n in list(_tl["nulls"].items()):
        f = source(cid)
        if f is not None:
            with f.lock:
                if n in f.clients:
                    f.clients.remove(n)
    _tl["nulls"] = {}


def _tl_frame():
    """One photo from each camera, in parallel (a slow one does not delay the others)."""
    d, cams = _tl["dir"], list(_tl["cameras"])
    photos = {}

    def a(cid):
        f = source(cid)
        r = f.photo(max_age=1.5, timeout=4) if f is not None else None
        if r:
            photos[cid] = r[0]

    threads = [threading.Thread(target=a, args=(c,), daemon=True) for c in cams]
    for h in threads:
        h.start()
    for h in threads:
        h.join(6)
    if not photos or _tl["dir"] != d:
        return
    _tl["n"] += 1
    _tl["times"].append(time.time())
    stamp = _tl_cfg().get("stamp")
    current_time = _now()
    for cid, jpg in photos.items():
        if stamp:
            f = source(cid)
            jpg = _mark(jpg, [current_time + "  " + (f.label if f is not None else cid) + ("  capa " + str(_tl["layer_last"]) if _tl["layer_last"] is not None else "")])
        with open(os.path.join(d, cid, f"{_tl['n']:05d}.jpg"), "wb") as fh:
            fh.write(jpg)
        _tl["last_frames"][cid] = jpg  # live view (GET /timelapse/ultimo)


def _tl_take():
    try:
        _tl_frame()
    except Exception as e:
        _log[0](f"camera: timelapse frame failed ({e!r})")
    finally:
        _tl["tomando"] = False


def _tl_finish():
    d, n, label, begin, cams, manual = _tl["dir"], _tl["n"], _tl["job"], _tl["start"], list(_tl["cameras"]), _tl["manual"]
    cfg, times = json.loads(json.dumps(_tl_cfg())), list(_tl["times"])
    _tl_release_nulls()
    _tl.update(dir=None, job=None, start=None, n=0, cameras=[], manual=False, cfg=None, times=[])
    if not d:
        return
    if n < 3:
        shutil.rmtree(d, ignore_errors=True)
        _log[0](f"camera: timelapse of {label} discarded (less than 3 frames)")
        return
    names = {}
    for cid in cams:
        f = source(cid)
        names[cid] = f.label if f is not None else cid
    _tl["assembling"] = os.path.basename(d)

    def _arm():
        try:
            ready = tl_arm(d, cams, names, n, cfg, {"job": label, "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(begin)),
                                                          "duration_s": int(time.time() - begin), "manual": manual}, times)
            _check_limits()
            _log[0](f"camera: timelapse ready ({', '.join(ready) or 'nothing'})")
        except Exception as e:
            _log[0](f"camera: could not build the timelapse ({e!r})")
        finally:
            shutil.rmtree(d, ignore_errors=True)
            _tl["assembling"] = None

    threading.Thread(target=_arm, daemon=True, name="camera-timelapse").start()


# ---- video assembly (ffmpeg) ----

def _fill(folder, n):
    """Fills 1..n: where a camera did not answer the previous frame goes (or the next one, at the start). False if the camera has none."""
    any_present = sorted(int(os.path.splitext(x)[0]) for x in os.listdir(folder) if x.endswith(".jpg"))
    if not any_present:
        return False
    has = set(any_present)
    previous = any_present[0]
    for i in range(1, n + 1):
        if i in has:
            previous = i
            continue
        dst = os.path.join(folder, f"{i:05d}.jpg")
        src = os.path.join(folder, f"{previous:05d}.jpg")
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
    return True


def _text(d, label, content):
    """drawtext reads the text from a file: no fighting with ffmpeg's escaping (the path only has letters, numbers, - and _)."""
    route = os.path.join(d, "_" + label + ".txt")
    with open(route, "w", encoding="utf-8") as fh:
        fh.write(str(content))
    return route


def _measure(folder):
    """Size of the stills (the camera's own: the resolution of the video is chosen in the cinema controls)."""
    try:
        from PIL import Image
        with Image.open(os.path.join(folder, "00001.jpg")) as im:
            w, h = im.size
    except Exception:
        w, h = 800, 600
    return w // 2 * 2, h // 2 * 2


def _smooth(cfg):
    """ffmpeg filter against light flicker (average brightness of 10 frames), if chosen; it goes before scaling."""
    return "deflicker=mode=pm:size=10," if cfg.get("deflicker") else ""


def _fit(w, h):
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def _label(d, cid, label, h):
    """Name of the camera in the corner (mosaic / alternate)."""
    length = max(14, h // 24)
    return (f"drawtext=fontfile={SOURCE_TTF}:expansion=none:textfile={_text(d, 'cam-' + cid, label)}:x={length // 2}:y={length // 2}:fontsize={length}:fontcolor=white"
            f":box=1:boxcolor=black@0.45:boxborderw={length // 3}")


def _close(d, cfg, meta, h):
    """Title (name and date) and still final frame, over the already assembled video. Small title: bottom right during the first seconds, without stopping the video. Big title: banner in the centre over the first still frame."""
    tit = bool(cfg.get("title"))
    large = tit and cfg.get("title_style") == "large"
    end = float(cfg.get("final_s") or 0)
    parts = []
    if large or end > 0:
        parts.append(f"tpad=start_mode=clone:start_duration={TL_TITLE_S if large else 0}:stop_mode=clone:stop_duration={end}")
    if large:
        t1, t2 = max(22, h // 12), max(14, h // 26)
        a = f"if(lt(t,{TL_TITLE_S - 0.6}),1,max(0,({TL_TITLE_S}-t)/0.6))"
        parts.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill:enable='lt(t,{TL_TITLE_S})'")
        parts.append(f"drawtext=fontfile={SOURCE_TTF}:expansion=none:textfile={_text(d, 'title', meta.get('job') or 'Timelapse')}"
                      f":fontsize={t1}:fontcolor=white:x=(w-tw)/2:y=(h/2)-{t1}:alpha='{a}'")
        parts.append(f"drawtext=fontfile={SOURCE_TTF}:expansion=none:textfile={_text(d, 'date', meta.get('start') or '')}"
                      f":fontsize={t2}:fontcolor=white@0.85"
                      f":x=(w-tw)/2:y=(h/2)+{t2 // 2}:alpha='{a}'")
    elif tit:
        t1 = max(12, h // 36)
        m = max(8, h // 60)
        lasts = 4.0
        a = f"if(lt(t,{lasts - 0.8}),1,max(0,({lasts}-t)/0.8))"
        raw_text = (meta.get("job") or "Timelapse") + "  " + (meta.get("start") or "")[:16]
        parts.append(f"drawtext=fontfile={SOURCE_TTF}:expansion=none:textfile={_text(d, 'title', raw_text)}"
                      f":fontsize={t1}:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw={max(4, t1 // 3)}"
                      f":x=w-tw-{m}:y=h-th-{m}:alpha='{a}':enable='lt(t,{lasts})'")
    return parts


def _ffmpeg(args, output, cfg):
    cmd = ["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error"] + args + look.encoder_args(cfg) + [output]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
    if r.returncode != 0 or not os.path.exists(output):
        raise RuntimeError("ffmpeg: " + (r.stderr or "")[-400:])


def _thumbnail(video, backup):
    jpg = video[:-4] + ".jpg"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.6", "-i", video, "-frames:v", "1", "-update", "1", jpg],
                       capture_output=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(jpg):
        shutil.copyfile(backup, jpg)


def tl_arm(d, cams, names, n, cfg, meta, times=None):
    """Assembles the videos of a session. Returns the files created (mp4 or mov, by codec)."""
    cfg = look.normalise(dict(cfg))
    fps = look.fps_value(cfg)
    fpsf = look.fps_float(cfg)
    ext = look.extension(cfg)
    cams = [c for c in cams if os.path.isdir(os.path.join(d, c)) and _fill(os.path.join(d, c), n)]
    if not cams:
        return []
    armed = cfg.get("armed") if cfg.get("armed") in ARMED else "separate"
    if len(cams) == 1:
        armed = "separate"
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    base = os.path.join(TIMELAPSE_DIR, os.path.basename(d))
    last = lambda c: os.path.join(d, c, f"{n:05d}.jpg")
    entry = lambda c, ini=1: ["-framerate", fps, "-start_number", str(ini), "-i", os.path.join(d, c, "%05d.jpg")]
    done_items = []
    grade = ",".join(look.grade_filters(cfg, LUTS_DIR))
    blend = [f"tmix=frames={cfg['blend']}"] if cfg["blend"] > 1 else []

    def save(output, extra, folders):
        payload = dict(meta, frames=n, fps=fpsf, armed=armed, cameras=[names.get(c, c) for c in cams], codec=cfg["codec"],
                       quality=cfg["quality"], look={k: cfg[k] for k in PRESET_KEYS if k in cfg}, **extra)
        if cfg.get("keep_frames") and times:
            zip_path = output[:-4] + "-frames.zip"
            try:
                look.pack_frames({k: os.path.join(d, v) for k, v in folders.items()}, zip_path, times)
                payload["frames_zip"] = os.path.basename(zip_path)
            except OSError as e:
                _log[0](f"camera: could not keep the frames ({e!r})")
        with open(output[:-4] + ".json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        done_items.append(os.path.basename(output))

    def tail(duration, h):
        """Title and end card, then the fades over the whole video (the length of the title and of the card is added to the duration)."""
        more = (TL_TITLE_S if cfg.get("title") and cfg.get("title_style") == "large" else 0) + float(cfg.get("final_s") or 0)
        return _close(d, cfg, meta, h) + look.fade_filters(cfg, duration + more)

    if armed == "separate":
        for c in cams:
            output = base + (f"-{c}" if len(cams) > 1 else "") + "." + ext
            w, h = _measure(os.path.join(d, c))
            chain, (ow, oh) = look.look_filters(cfg, w, h, n, LUTS_DIR)
            filter_spec = _smooth(cfg) + ",".join(chain + tail(n / fpsf, oh))
            _ffmpeg(entry(c) + ["-vf", filter_spec], output, cfg)
            _thumbnail(output, last(c))
            save(output, {"camera": names.get(c, c), "size": f"{ow}x{oh}"}, {"": c})
        return done_items

    output = base + "." + ext
    every = {c: c for c in cams}
    if armed == "mosaic":
        cw, ch = 640, 480
        args, steps = [], []
        for i, c in enumerate(cams):
            args += entry(c)
            steps.append(f"[{i}:v]{_smooth(cfg)}{_fit(cw, ch)},{_label(d, c, names.get(c, c), ch)}{',' + grade if grade else ''}[v{i}]")
        k = len(cams)
        if k == 2:
            steps.append("[v0][v1]hstack=inputs=2[m]")
            height = ch
        else:
            if k == 3:
                steps.append(f"color=c=black:s={cw}x{ch}:r={fps}[v3]")
            steps.append(f"[v0][v1][v2][v3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0:shortest=1[m]")
            height = ch * 2
        steps.append("[m]" + ",".join(["null"] + blend + tail(n / fpsf, height)) + "[out]")
        _ffmpeg(args + ["-filter_complex", ";".join(steps), "-map", "[out]"], output, cfg)
        _thumbnail(output, last(cams[0]))
        save(output, {}, every)
        return done_items

    # alternate: segments of "segment_s" seconds, one per camera per turn; each segment is stretched
    # by the length of the fade so the time does not jump
    w, h = _measure(os.path.join(d, cams[0]))
    segment = max(1, int(round(float(cfg.get("segment_s") or 4) * fpsf)))
    while n / segment > 60:  # no more than 60 segments (ffmpeg opens one input per segment)
        segment *= 2
    fade = float(cfg.get("fade_s") or 0)
    fcuad = int(round(fade * fpsf))
    if fcuad >= segment // 2:
        fcuad = max(0, segment // 2 - 1)
    fade = fcuad / fpsf
    segments = []
    ini = 1
    while ini <= n:
        end = min(n, ini + segment - 1)
        segments.append((ini, end))
        ini = end + 1
    if len(segments) > 1 and segments[-1][1] - segments[-1][0] + 1 <= fcuad:
        a, _ = segments.pop()  # the last one was shorter than the fade: it is added to the previous one
        segments[-1] = (segments[-1][0], n)
    args, steps, long = [], [], []
    for i, (a, b) in enumerate(segments):
        c = cams[i % len(cams)]
        many = b - a + 1 + (fcuad if i < len(segments) - 1 and fcuad else 0)
        many = min(many, n - a + 1)
        args += entry(c, a)
        steps.append(f"[{i}:v]trim=end_frame={many},setpts=PTS-STARTPTS,{_smooth(cfg)}{_fit(w, h)},{_label(d, c, names.get(c, c), h)}{',' + grade if grade else ''},fps={fps},format=yuv420p[t{i}]")
        long.append(many / fpsf)
    if len(segments) == 1:
        steps.append("[t0]null[m]")
    elif fcuad:
        previous, acum = "t0", long[0]
        for i in range(1, len(segments)):
            sal = "m" if i == len(segments) - 1 else f"x{i}"
            steps.append(f"[{previous}][t{i}]xfade=transition=fade:duration={fade:.3f}:offset={acum - fade:.3f}[{sal}]")
            acum += long[i] - fade
            previous = sal
    else:
        steps.append("".join(f"[t{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[m]")
    steps.append("[m]" + ",".join(["null"] + blend + tail(sum(long) - fade * max(0, len(segments) - 1), h)) + "[out]")
    _ffmpeg(args + ["-filter_complex", ";".join(steps), "-map", "[out]"], output, cfg)
    _thumbnail(output, last(cams[(len(segments) - 1) % len(cams)]))
    save(output, {"segment_s": round(segment / fpsf, 2), "fade_s": round(fade, 2)}, every)
    return done_items


def _videos_bytes():
    total = 0
    for f in glob.glob(os.path.join(TIMELAPSE_DIR, "*")):
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total


# ---- deleting by itself, with a warning (2026-10-10: "the videos and photos that are going to be
# deleted must send notifications so the user decides; if they do nothing it is deleted anyway")
# ----
# When a cap is exceeded (number of videos or captures, space for videos) the oldest are NOT deleted
# at that moment: they are left "to delete" with a deadline (delete_wait_h), a notice arrives on the
# phone (type camera_deleted) and on the Timelapses and captures page they can be kept, downloaded
# or deleted right away. If nobody does anything, they are deleted at expiry. The kept ones are
# never deleted by themselves.

BY_DELETE = os.path.join(DATA_DIR, "per_delete.json")
_pb = {"list": None}


def _pb_read():
    if _pb["list"] is None:
        try:
            with open(BY_DELETE, encoding="utf-8") as fh:
                _pb["list"] = json.load(fh)
        except Exception:
            _pb["list"] = {}
    return _pb["list"]


def _pb_save():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BY_DELETE, "w", encoding="utf-8") as fh:
            json.dump(_pb["list"] or {}, fh, ensure_ascii=False)
    except OSError as e:
        _log[0](f"camera: could not save the list to delete ({e!r})")


def _kept(route):
    try:
        with open(os.path.splitext(route)[0] + ".json", encoding="utf-8") as fh:
            return bool(json.load(fh).get("keep"))
    except Exception:
        return False


def _delete_already(route):
    for ext in SIDE_FILES + VIDEO_EXT:
        try:
            os.remove(os.path.splitext(route)[0] + ext)
        except OSError:
            pass


def _candidates():
    """{file: (type, reason)} of what exceeds the caps, the oldest first, not counting the kept ones."""
    out = {}
    vmax = int(_service.get("timelapses_max") or 30)
    videos = sorted(_videos_list())
    free = [v for v in videos if not _kept(v)]
    for v in free[:max(0, len(videos) - vmax)]:
        out[os.path.basename(v)] = ("video", M("cam_limit_videos", n=vmax))
    gb = float(_service.get("timelapses_gb") or 5)
    total = _videos_bytes()
    for v in free:
        if total <= gb * 1024 ** 3:
            break
        total -= sum(os.path.getsize(v[:-4] + e) for e in SIDE_FILES + (v[-4:],) if os.path.exists(v[:-4] + e))
        out.setdefault(os.path.basename(v), ("video", M("cam_limit_video_space", gb=gb)))
    fmax = int(_service.get("captures_max") or 300)
    photos = sorted(glob.glob(os.path.join(CAPTURES_DIR, "*.jpg")))
    for f in [x for x in photos if not _kept(x)][:max(0, len(photos) - fmax)]:
        out[os.path.basename(f)] = ("photo", M("cam_limit_captures", n=fmax))
    return out


def _check_limits():
    """Marks what exceeds (with a warning), unmarks what no longer exceeds and deletes what expired."""
    pb = _pb_read()
    cand = _candidates()
    current_time = time.time()
    waiting = int(_service.get("delete_wait_h") or 24) * 3600
    new = []
    for a, (type_name, reason) in cand.items():
        if a not in pb:
            # hours as integers: dsf-python changes json to write floats with 6 digits (1.79169e+09
            # = the time rounded to ~15 min)
            pb[a] = {"kind": type_name, "reason": str(reason), "reason_key": reason.key, "reason_params": dumps_params(reason),
                     "since": int(current_time), "until": int(current_time + waiting)}
            new.append(a)
    loose = [a for a in pb if a not in cand]
    for a in loose:
        del pb[a]  # it was kept, deleted by hand or no longer exceeds
    expired = [a for a, d in pb.items() if d["until"] <= current_time]
    for a in expired:
        d = pb.pop(a)
        _delete_already(os.path.join(TIMELAPSE_DIR if d["kind"] == "video" else CAPTURES_DIR, a))
        _log[0](f"camera: deleted {a} ({d['reason']}; notified and nobody kept it)")
    if new or expired or loose:
        _pb_save()
    if new:
        nv = sum(1 for a in new if pb[a]["kind"] == "video")
        nf = len(new) - nv
        that = M("cam_files_both", videos=nv, photos=nf) if nv and nf else (M("cam_files_videos", n=nv) if nv else M("cam_files_photos", n=nf))
        when = time.strftime("%d/%m %H:%M", time.localtime(current_time + waiting))
        _notify("camera_deleted", M("cam_about_to_delete", what=that, when=when, reason=of_row(pb[new[0]].get("reason_key"), pb[new[0]].get("reason_params")) or pb[new[0]]["reason"]))


def by_delete():
    pb = _pb_read()
    # reason as {"key", "params"} (the gallery shows it in the language of its DWC); an old entry: its text as it is
    return {"items": [dict(d, file=a, reason=messages.data(of_row(d.get("reason_key"), d.get("reason_params")) or d.get("reason")))
                      for a, d in sorted(pb.items(), key=lambda x: x[1]["until"])],
            "wait_h": int(_service.get("delete_wait_h") or 24)}


def keep(file, value=True):
    """Marks or unmarks keep (never deleted by itself) and checks the caps again."""
    j, meta = _meta_of(file)
    if j is None:
        return {"ok": False, "error": M("camera_relay_file_does_not_exist")}
    meta["keep"] = bool(value)
    with open(j, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    _check_limits()
    return {"ok": True, "keep": meta["keep"], "per_delete": by_delete()}


def tl_begin_by_hand(label="", overrides=None):
    try:
        _take_cfg(overrides)
    except (TypeError, ValueError, AttributeError):
        return {"ok": False, "error": M("camera_relay_invalid_numbers")}
    if _tl["dir"]:
        return {"ok": False, "error": M("camera_relay_timelapse_already_being_recorded", job=str(_tl["job"]))}
    if _without_space():
        return {"ok": False, "error": M("camera_relay_little_space_left_system_less_delete")}
    label = re.sub(r"[\r\n\"]+", " ", str(label or "")).strip()[:60] or ("Timelapse " + time.strftime("%H:%M"))
    _tl_begin(label, manual=True, overrides=overrides)
    return dict(tl_state(), ok=True)


def tl_stop():
    if not _tl["dir"]:
        return {"ok": False, "error": M("camera_relay_no_timelapse_being_recorded")}
    m = _machine()
    if m["job"]:
        _tl["skip"] = m["job"]  # stopped by hand: it does not start again by itself with this job
    if _prog_read().get("started"):
        _prog_save({})  # stopped by hand: the schedule no longer runs
    _tl_finish()
    return dict(tl_state(), ok=True)


# Scheduled (2026-10-10, "advanced functions"): start and/or stop at a time. It is saved in
# sd/camera/schedule.json (it survives a restart).
SCHEDULED = os.path.join(DATA_DIR, "schedule.json")
_prog = {"data": None}


def _prog_read():
    if _prog["data"] is None:
        try:
            with open(SCHEDULED, encoding="utf-8") as fh:
                _prog["data"] = json.load(fh) or {}
        except Exception:
            _prog["data"] = {}
    return _prog["data"]


def _prog_save(d):
    _prog["data"] = d
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SCHEDULED, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    except OSError as e:
        _log[0](f"camera: could not save the schedule ({e!r})")


def tl_schedule(since, until, label=""):
    """from / to: epoch seconds (0 or empty = none). Without from: it starts right away if a to was given (it records until that time)."""
    current_time = time.time()
    try:
        since = float(since or 0)
        until = float(until or 0)
    except ValueError:
        return {"ok": False, "error": M("camera_relay_invalid_times")}
    if not since and not until:
        return {"ok": False, "error": M("camera_relay_start_or_stop_time_missing")}
    if until and until <= max(current_time, since) + 30:
        return {"ok": False, "error": M("camera_relay_stop_time_has_after_start_time")}
    if since and since < current_time - 60:
        return {"ok": False, "error": M("camera_relay_start_time_already_passed")}
    label = re.sub(r"\s+", " ", str(label or "")).strip()[:60]
    # integers: see _check_limits (floats come out with 6 digits through dsf-python)
    _prog_save({"since": int(since) or None, "until": int(until) or None, "name": label, "creado": int(current_time)})
    _log[0](f"camera: timelapse scheduled from {time.strftime('%d/%m %H:%M', time.localtime(since)) if since else 'now'} until {time.strftime('%d/%m %H:%M', time.localtime(until)) if until else 'it is stopped'}")
    return dict(tl_state(), ok=True)


def tl_unschedule():
    _prog_save({})
    return dict(tl_state(), ok=True)


def _prog_tick():
    p = _prog_read()
    if not p:
        return
    current_time = time.time()
    if p.get("since") and current_time >= p["since"] and not p.get("started"):
        p["started"] = True
        _prog_save(p)
        if _tl["dir"]:
            _log[0]("camera: scheduled timelapse did not start: another one was already recording")
        else:
            r = tl_begin_by_hand(p.get("name") or M("camera_relay_scheduled_timelapse_name", time=time.strftime("%H:%M")))
            if not r.get("ok"):
                _notify("camera", M("cam_tl_scheduled_failed", error=str(r.get("error"))))
    if not p.get("since") and not p.get("started"):
        p["started"] = True  # only a stop time: it starts right away
        _prog_save(p)
        if not _tl["dir"]:
            tl_begin_by_hand(p.get("name") or M("camera_relay_scheduled_timelapse_name", time=time.strftime("%H:%M")))
    if p.get("until") and current_time >= p["until"]:
        if _tl["dir"] and _tl["manual"]:
            _log[0]("camera: scheduled timelapse: stop time reached")
            _tl_finish()
        _prog_save({})


_encoders_found = [None]


def encoders():
    """Which cinema codecs this ffmpeg can write (asked once): the page greys out what is missing."""
    if _encoders_found[0] is None:
        want = {"h264": "libx264", "h265": "libx265", "prores": "prores_ks", "dnxhr": "dnxhd"}
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _encoders_found[0] = {k: (v in out) for k, v in want.items()} if out else {k: k == "h264" for k in want}
    return dict(_encoders_found[0])


def look_preview(cid, overrides):
    """One still of the camera (or of the take being recorded) with the framing and the grade of the cinema controls: what the video will look like."""
    f = source(_id(cid))
    jpg = _tl["last_frames"].get(_id(cid)) if _tl["dir"] else None
    if jpg is None and f is not None:
        got = f.photo(max_age=2.0, timeout=5)
        jpg = got[0] if got else None
    if not jpg:
        return None
    cfg = _take_cfg(overrides)
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(jpg)) as im:
            w, h = im.size
    except Exception:
        return None
    ow, oh = look.output_size(w, h, cfg)
    scale = min(1.0, 960.0 / ow)  # preview at most 960 wide
    chain = []
    crop = look.crop_filter(w, h, cfg)
    if crop:
        chain.append(crop)
    chain += look.grade_filters(cfg, LUTS_DIR)
    chain.append(f"scale={max(2, int(ow * scale) // 2 * 2)}:{max(2, int(oh * scale) // 2 * 2)}:flags=lanczos")
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-vf", ",".join(chain), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg",
                        "-q:v", "3", "pipe:1"], input=jpg, capture_output=True, timeout=30)
    return r.stdout if r.returncode == 0 and r.stdout else None


def lut_save(name, data):
    name = os.path.basename(str(name or ""))
    if not look.LUT_NAME.match(name):
        return {"ok": False, "error": M("camera_relay_lut_name_invalid")}
    if not look.valid_lut(data):
        return {"ok": False, "error": M("camera_relay_lut_not_valid")}
    os.makedirs(LUTS_DIR, exist_ok=True)
    with open(os.path.join(LUTS_DIR, name), "wb") as fh:
        fh.write(data)
    return {"ok": True, "luts": look.list_luts(LUTS_DIR)}


def lut_remove(name):
    name = os.path.basename(str(name or ""))
    if not look.LUT_NAME.match(name):
        return {"ok": False, "error": M("camera_relay_lut_name_invalid")}
    try:
        os.remove(os.path.join(LUTS_DIR, name))
    except OSError:
        pass
    return {"ok": True, "luts": look.list_luts(LUTS_DIR)}


def tl_state():
    return {"recording": bool(_tl["dir"]), "job": _tl["job"], "frames": _tl["n"], "assembling": _tl["assembling"],
            "manual": _tl["manual"], "cameras": list(_tl["cameras"]),
            "since_s": int(time.time() - _tl["start"]) if _tl["start"] else None,
            "disk_free_gb": round((_disk_free() or 0) / 1024 ** 3, 1),
            "videos_gb": round(_videos_bytes() / 1024 ** 3, 2),
            "max_min": _tl_cfg().get("max_min", 720),
            "editing": _editing["file"], "burst": _burst["left"],
            "scheduled": {k: v for k, v in _prog_read().items() if k in ("since", "until", "name", "started")} or None,
            "layer": _tl["layer_last"], "trigger": _tl_cfg().get("trigger", "time"),
            "take": ({k: _tl["cfg"].get(k) for k in ("codec", "quality", "fps", "each_s", "each_end_s", "aspect", "resolution", "keep_frames")}
                     if _tl["cfg"] else None),
            "interval_s": round(look.interval_now(_tl_cfg(), time.time() - _tl["start"]), 1) if _tl["start"] else None}


def _tl_clean_leftovers():
    """At startup nothing is recorded: whatever is in frames/ was left by a cut (the Pi was switched off in the middle of a recording or of the assembly)."""
    try:
        leftovers = [os.path.join(FRAMES_DIR, x) for x in os.listdir(FRAMES_DIR)]
    except OSError:
        return
    for d in leftovers:
        shutil.rmtree(d, ignore_errors=True)
    if leftovers:
        _log[0](f"camera: deleted {len(leftovers)} leftovers of unfinished timelapses")


def _tl_tick():
    _prog_tick()
    cfg = _service["timelapse"]
    m = _machine()
    job = m["job"]
    paused = m["state"] in ("paused", "pausing")
    if _tl["skip"] and _tl["skip"] != job:
        _tl["skip"] = None
    if _tl["dir"] and _without_space():
        _notify("camera", M("cam_tl_stopped_space", job=_tl["job"]))
        _tl_finish()
        return
    if _tl["dir"] and time.time() - _tl["start"] > _tl_cfg().get("max_min", 720) * 60:
        _notify("camera", M("cam_tl_stopped_max", job=_tl["job"], minutes=_tl_cfg().get("max_min", 720)))
        if not _tl["manual"]:
            _tl["skip"] = _tl["job"]  # it does not start again with the same job
        _tl_finish()
        return
    if _tl["dir"]:
        if not _tl["manual"] and (not cfg["active"] or not job or job != _tl["job"]):
            _tl_finish()
    if not _tl["dir"] and cfg["active"] and job and job != _tl["skip"] and not _without_space():
        _tl_begin(job)
    by_layer = _tl["dir"] and not _tl["manual"] and _tl_cfg().get("trigger") == "layer" and m.get("layer") is not None
    if by_layer:
        # one photo per layer (3D printing): when job.layer changes
        if m["layer"] != _tl["layer_last"] and not _tl["tomando"] and _tl["n"] < TL_MAX_FRAMES:
            _tl["layer_last"] = m["layer"]
            _tl["last"] = time.time()
            _tl["tomando"] = True
            threading.Thread(target=_tl_take, daemon=True, name="camera-tl-frame").start()
        return
    if (_tl["dir"] and not _tl["tomando"] and (_tl["manual"] or not paused)
            and time.time() - _tl["last"] >= look.interval_now(_tl_cfg(), time.time() - _tl["start"]) and _tl["n"] < TL_MAX_FRAMES):
        _tl["last"] = time.time()
        _tl["tomando"] = True
        threading.Thread(target=_tl_take, daemon=True, name="camera-tl-frame").start()


# ---------------- vigilante: camaras caidas ----------------

def _watch():
    if not _service.get("notice_drop"):
        return
    with _sources_lock:
        fs = list(_sources.values())
    t = time.time()
    for f in fs:
        if f.status == "connected" and t - f.last_frame < 10:
            f.last_ok = t
        elif t - f.last_ok > 40:
            # nobody watches it (or the video was cut): a light question
            try:
                with urllib.request.urlopen(f.base + "/status" if f.base else f.url, timeout=4) as r:
                    r.read(64)
                f.last_ok = t
            except Exception:
                pass
        drop = t - f.last_ok > _service["drop_s"]
        if drop and not f.drop_notified:
            f.drop_notified = True
            _notify("camera", M("cam_not_responding", name=f.label, since=time.strftime("%H:%M", time.localtime(f.last_ok))),
                    {"camera": f.id, "name": f.label, "url": f.url, "silent_s": round(t - f.last_ok)})
        elif not drop and f.drop_notified:
            f.drop_notified = False
            _notify("camera", M("cam_responding", name=f.label), {"camera": f.id, "name": f.label, "url": f.url})


def _notify(type_name, raw_text, detail=None):
    _log[0]("camera: " + raw_text)
    b = _bridge[0]
    if b is None:
        return
    try:
        import activity
        activity.log_event(b, type_name, raw_text, detail=detail)
    except Exception as e:
        _log[0](f"camera: could not record the notice ({e!r})")


# ---------------- photo for the notifications ----------------

def _camera_notice(cid=None):
    """Source for a notification: the chosen camera, else the notifications default,
    else the main one (a camera that no longer exists falls back to the main one)."""
    return source(cid or _service.get("notice_camera") or MAIN) or source(MAIN)


def photo_for_notice(cid=None):
    """JPEG (bytes) of the notices' camera with the date, or None. Used by notifier.py."""
    if not _service.get("photo_notice"):
        return None
    f = _camera_notice(cid)
    if f is None:
        return None
    r = f.photo(max_age=2.0, timeout=5)
    if not r:
        return None
    return _mark(r[0], [_now() + "  " + f.label])


# ---- short video for the notices (2026-10-12, pending item 21) ----
# A few seconds of the main camera, AFTER the event (there is no buffer from before: that would
# require keeping the camera's video open all the time, and the Pi is already loaded). The frames
# are taken from the same video the relay forwards (one more client, like the timelapse) and ffmpeg
# assembles a small mp4. One at a time; with the Pi under critical load, without ffmpeg or if the
# camera sends no frames: None (the notice goes out with the photo).
CLIP_MIN_S = 2
CLIP_MAX_S = 10
CLIP_WIDTH_MAX = 640
CLIP_MAX_BYTES = 8 * 1024 * 1024  # ntfy.sh accepts up to 15 MB per attachment
CLIP_WAIT_FIRST_S = 6  # the camera takes a while to open the video if nobody was watching
_clip_lock = threading.Lock()


class _Recorder(_Null):
    """Fake client that keeps the frames that arrive (with their time)."""

    def __init__(self, maximum):
        self.frames = []
        self.maximum = maximum
        self.arrived = threading.Event()

    def put(self, frame):
        if len(self.frames) < self.maximum:
            self.frames.append((time.time(), frame))
        self.arrived.set()


def _clip_record(f, seconds):
    """[(t, jpeg)] of `seconds` of video from the source f (from the first frame)."""
    g = _Recorder(int(seconds * 30) + 10)
    with f.lock:
        f.clients.append(g)
    try:
        f.ensure()
        if not g.arrived.wait(CLIP_WAIT_FIRST_S):
            return []
        end = time.time() + seconds
        while time.time() < end and len(g.frames) < g.maximum:
            time.sleep(0.1)
        return list(g.frames)
    finally:
        with f.lock:
            if g in f.clients:
                f.clients.remove(g)


def _clip_arm(frames, folder):
    """mp4 (bytes) with the frames, or None."""
    if len(frames) < 3:
        return None
    lasts = max(0.5, frames[-1][0] - frames[0][0])
    fps = max(1, min(30, int(round((len(frames) - 1) / lasts)) or 1))
    os.makedirs(folder, exist_ok=True)
    for i, (_t, jpg) in enumerate(frames, 1):
        with open(os.path.join(folder, f"{i:05d}.jpg"), "wb") as fh:
            fh.write(jpg)
    output = os.path.join(folder, "clip.mp4")
    cmd = ["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
           "-i", os.path.join(folder, "%05d.jpg"),
           "-vf", f"scale='min({CLIP_WIDTH_MAX},iw)':-2", "-an",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output]
    if not shutil.which("nice"):
        cmd = cmd[3:]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(output):
        _log[0]("camera: could not build the notice video (" + (r.stderr or "")[-200:] + ")")
        return None
    with open(output, "rb") as fh:
        payload = fh.read()
    if len(payload) > CLIP_MAX_BYTES:
        _log[0](f"camera: the notice video weighs {len(payload) // 1024} kB, only the photo is sent")
        return None
    return payload


def video_for_notice(seconds=5, cid=None):
    """MP4 (bytes) of a few seconds of the notices' camera, or None. Used by notifier.py. It respects "photo_notice" (if the photos in the notices are off, there is no video either)."""
    if not _service.get("photo_notice"):
        return None
    if _load["level"] >= 2 or not shutil.which("ffmpeg"):
        return None
    f = _camera_notice(cid)
    if f is None:
        return None
    if not _clip_lock.acquire(blocking=False):
        return None  # another one is already recording: that notice goes with the photo
    folder = os.path.join(FRAMES_DIR, "aviso-" + time.strftime("%Y%m%d-%H%M%S"))
    try:
        sec = max(CLIP_MIN_S, min(CLIP_MAX_S, float(seconds or 5)))
        return _clip_arm(_clip_record(f, sec), folder)
    except Exception as e:
        _log[0](f"camera: notice video failed ({e!r})")
        return None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        _clip_lock.release()


# ---------------- load of the Pi and screens ----------------

def _cap_screens():
    cap = int(_service.get("screens_max") or 0)
    if _load["level"] >= 2:
        cap = min(cap, 2) if cap else 2
    return cap


def _watch_load():
    """Every ~5 s: level 0 normal, 1 loaded (fewer frames to the remote ones), 2 critical (2 remote screens per camera). To go down, 30 s without load are needed.
    Temperature and CPU come from the service's own health data (camera_load.reading); only the kB/s going out are measured here."""
    t = time.time()
    b = _bridge[0]
    temp, cpu = camera_load.reading(getattr(b, "payload", None), t)
    with _sources_lock:
        fs = list(_sources.values())
    total = 0
    for f in fs:
        with f.lock:
            cs = [c for c in f.clients if not c.null and not c.local]
        for c in cs:
            c.bytes_sec = [x for x in c.bytes_sec if t - x[0] < 5]
            total += sum(b_ for _, b_ in c.bytes_sec)
    kbps = total / 5.0 / 1024
    old, level, reasons = camera_load.step(_load, temp, cpu, kbps, _service.get("load_kbps", 3000), t)
    if level == old:
        return
    raw_text = {0: M("cam_load_normal"),
                1: M("cam_load_high", reason=_load["reason"], fps=_service.get("load_fps", 5)),
                2: M("cam_load_critical", reason=_load["reason"] or M("cam_load_still"))}[level]
    if camera_load.notify_worthy(reasons) and camera_load.notice_due(_load, level, t):
        _notify("camera_load", raw_text, {"level": level, "reason": _load["reason"], "cpu_pct": _load["cpu"], "temp_c": _load["temp"],
                                        "kbps": _load["kbps"], "fps_remote": _service.get("load_fps", 5)})  # _notify also notes it in the log; it reaches the phone through notifier.py
    else:
        _log[0]("camera: " + raw_text)
    if level == 2:
        for f in fs:
            with f.lock:
                remote = sorted((c for c in f.clients if not c.null and not c.local and not c.shut), key=lambda c: c.since)
            for c in remote[:-2] if len(remote) > 2 else []:
                c.echar(M("camera_relay_cut_system_heavily_loaded_tap_see", p=_load['reason'] or M("camera_relay_high_load")))


# ---- key for the remote screens (with a password in DWC) ----

_key = {"has": False, "ts": 0.0, "secret": None}


def _has_password():
    if time.time() - _key["ts"] < 30:
        return _key["has"]
    _key["ts"] = time.time()
    try:
        import ipc_stats
        from dsf.connections import CommandConnection
        c = CommandConnection()
        c.connect()
        try:
            # same as http_api.py: without a password DSF accepts any key
            r = ipc_stats.call("other", "camera_relay", c.check_password, "workshop-without-key-9f3k")
            _key["has"] = not bool(getattr(r, "result", r))
        finally:
            c.close()
    except Exception:
        _key["has"] = True  # if it cannot be known, a key is asked for
    return _key["has"]


def _secret():
    if _key["secret"] is None:
        route = KEY_FILE
        try:
            with open(route, "rb") as fh:
                sec = fh.read()
            if len(sec) < 16:
                raise OSError
        except OSError:
            sec = os.urandom(32)
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(route, "wb") as fh:
                fh.write(sec)
            os.chmod(route, 0o600)
        _key["secret"] = sec
    return _key["secret"]


def _token(day):
    return hmac.new(_secret(), day.encode(), hashlib.sha256).hexdigest()[:32]


def token():
    """Key of the day (valid today and tomorrow). The page asks for it with the API (camera_relay) S"token", which already requires the DWC session."""
    return _token(time.strftime("%Y%m%d"))


def _token_valid(t):
    if not t:
        return False
    today = time.time()
    for day in (time.strftime("%Y%m%d", time.localtime(today)), time.strftime("%Y%m%d", time.localtime(today - 86400))):
        if hmac.compare_digest(t, _token(day)):
            return True
    return False


_notices_jpg = {}


def _frame_notice(raw_text):
    """640x480 JPEG with a text (the last thing a cut screen sees)."""
    if raw_text in _notices_jpg:
        return _notices_jpg[raw_text]
    try:
        import io
        import textwrap
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGB", (640, 480), (22, 28, 32))
        d = ImageDraw.Draw(im)
        try:
            fu = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except Exception:
            fu = ImageFont.load_default()
        lines = textwrap.wrap(raw_text, 38)
        y = 240 - len(lines) * 17
        for ln in lines:
            d.text((320, y), ln, fill=(236, 239, 241), font=fu, anchor="ma")
            y += 34
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85)
        _notices_jpg[raw_text] = out.getvalue()
    except Exception:
        _notices_jpg[raw_text] = None
    return _notices_jpg[raw_text]


# ---------------- HTTP ----------------

class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        """CORS only for the own DWC (the Origin whose host is the host asked, any port); nobody else may read."""
        o = net_guard.cors_origin(self.headers.get("Origin"), self.headers.get("Host"))
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")

    def _foreign_origin(self):
        """True if the request comes from a page of another site (Origin present and not the own DWC)."""
        o = self.headers.get("Origin")
        return bool(o) and net_guard.cors_origin(o, self.headers.get("Host")) is None

    def _empty(self, code):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, route, type_name, download=False):
        if not os.path.isfile(route):
            return self._empty(404)
        length = os.path.getsize(route)
        self.send_response(200)
        self.send_header("Content-Type", type_name)
        self._cors()
        self.send_header("Content-Length", str(length))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(route)}"')
        self.end_headers()
        with open(route, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 65536)

    def _path(self):
        u = urllib.parse.urlsplit(self.path)
        return camera_proto.upgrade(u.path, urllib.parse.parse_qs(u.query))  # old Spanish names -> current ones

    def do_OPTIONS(self):
        if self._foreign_origin():
            return self._empty(403)
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Workshop-Token, X-Workshop-Device")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._empty(200)  # liveness probe of the sidebar (HEAD /emergencyfab-ping, no-cors: any answer means alive); 200 keeps the network log quiet

    def _ip(self):
        return self.client_address[0] if self.client_address else ""

    def _allowed(self, q):
        """Local always; remote asks for the key only if DWC has a password."""
        if self._ip() in LOCAL or not _service.get("key", True) or not _has_password():
            return True
        t = (q.get("t") or [""])[0]
        if not t:
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "workshop_camera":
                    t = v
        return _token_valid(t)

    def _without_key(self):
        body = json.dumps({"ok": False, "error": M("camera_relay_dwc_key_password_needed")}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refused(self, method, path, q):
        """True (and the answer sent) when the roles of camera_access.py do not let this call through."""
        ok, status, code = camera_access.authorize(self.headers, self._ip(), method, path, q, _token_valid)
        if ok:
            return False
        self._json({"ok": False, "code": code, "error": M("camera_relay_" + code)}, status)
        return True

    def do_POST(self):
        if self._foreign_origin():
            return self._empty(403)
        path, q = self._path()
        if not self._allowed(q):
            return self._without_key()
        if self._refused("POST", path, q):
            return
        if path == "/capture":
            return self._json(capture((q.get("c") or [MAIN])[0]))
        if path == "/remove":
            a = (q.get("file") or [""])[0]
            ok = delete(a)
            if _pb_read().pop(os.path.basename(a), None) is not None:
                _pb_save()
            _log[0](f"camera: deleted {os.path.basename(a)} as asked by {self._ip()}" if ok else f"camera: {self._ip()} asked to delete {a} (it does not exist)")
            return self._json({"ok": ok})
        if path == "/keep":
            return self._json(keep((q.get("file") or [""])[0], (q.get("value") or ["1"])[0] not in ("0", "")))
        if path == "/rename":
            return self._json(rename((q.get("file") or [""])[0], (q.get("name") or [""])[0]))
        if path in ("/luts", "/luts/remove"):
            name = (q.get("name") or [""])[0]
            if path == "/luts/remove":
                return self._json(lut_remove(name))
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = 0
            if size <= 0 or size > look.LUT_MAX_BYTES:
                return self._json({"ok": False, "error": M("camera_relay_lut_not_valid")}, 400)
            return self._json(lut_save(name, self.rfile.read(size)))
        if path == "/burst":
            return self._json(burst((q.get("c") or [MAIN])[0], (q.get("count") or ["5"])[0], (q.get("gap") or ["1"])[0]))
        if path == "/rerender":
            try:
                over = json.loads((q.get("cfg") or ["{}"])[0])
            except ValueError:
                over = None
            if not isinstance(over, dict):
                return self._json({"ok": False, "error": M("camera_relay_invalid_numbers")}, 400)
            return self._json(rerender((q.get("file") or [""])[0], over))
        if path == "/edit":
            try:
                return self._json(edit((q.get("file") or [""])[0], (q.get("since") or ["0"])[0],
                                         (q.get("until") or [None])[0], (q.get("speed") or ["1"])[0]))
            except ValueError:
                return self._json({"ok": False, "error": M("camera_relay_invalid_numbers")}, 400)
        if path == "/timelapse":
            action = (q.get("action") or [""])[0]
            if action == "begin":
                try:
                    over = json.loads((q.get("cfg") or ["{}"])[0])
                except ValueError:
                    over = None
                if not isinstance(over, dict):
                    return self._json({"ok": False, "error": M("camera_relay_invalid_numbers")}, 400)
                return self._json(tl_begin_by_hand((q.get("name") or [""])[0], over))
            if action == "stop":
                return self._json(tl_stop())
            if action == "schedule":
                return self._json(tl_schedule((q.get("since") or ["0"])[0], (q.get("until") or ["0"])[0], (q.get("name") or [""])[0]))
            if action == "unschedule":
                return self._json(tl_unschedule())
            return self._json(dict(tl_state(), ok=False, error=M("camera_relay_timelapse_action_must_be")), 400)
        return self._empty(404)

    def do_GET(self):
        if self._foreign_origin():
            return self._empty(403)
        path, q = self._path()
        if not self._allowed(q):
            return self._without_key()
        if self._refused("GET", path, q):
            return
        m = re.match(r"^/c/([A-Za-z0-9_-]+)(/.*)?$", path)
        cid, rest = (MAIN, path) if not m else (_id(m.group(1)), m.group(2) or "/stream")
        if rest in ("/stream", "/", "/snapshot") or rest.startswith("/control") or rest.startswith("/status"):
            f = source(cid)
            if f is None:
                return self._empty(404)
            if rest.startswith("/control"):
                f.invalidate()  # the next photo has to be from the new setting
            if rest.startswith("/control") or rest.startswith("/status"):
                return self._proxy(f, rest + ("?" + urllib.parse.urlsplit(self.path).query if urllib.parse.urlsplit(self.path).query else ""))
            if rest == "/snapshot":
                return self._photo(f, fresh=(q.get("fresh") or ["0"])[0] not in ("0", ""))
            return self._stream(f)
        if path == "/key" and self._ip() in LOCAL:
            # for other services of the Pi (Vision :8095): same rule as the relay
            requires = bool(_service.get("key", True)) and _has_password()
            t = (q.get("t") or [""])[0]
            return self._json({"requires": requires, "ok": (not requires) or _token_valid(t)})
        if path == "/state":
            with _sources_lock:
                fs = [f.summary() for f in _sources.values()]
            return self._json({**camera_proto.describe(), "cameras": fs, "service": service_cfg(), "timelapse": tl_state(),
                               "encoders": encoders(), "luts": look.list_luts(LUTS_DIR),
                               "load": {k: _load[k] for k in ("level", "temp", "cpu", "kbps", "reason")},
                               "stop_screens": _cap_screens()})
        if path == "/detect":
            return self._json(detect((q.get("url") or [""])[0]))
        if path == "/captures":
            return self._json(list_items_captures())
        if path == "/per_delete":
            return self._json(by_delete())
        if path.startswith("/captures/"):
            return self._file(os.path.join(CAPTURES_DIR, os.path.basename(path)), "image/jpeg", "download" in q)
        if path == "/timelapses":
            return self._json(list_items_timelapses())
        if path == "/luts":
            return self._json(look.list_luts(LUTS_DIR))
        if path == "/timelapse/preview":
            try:
                over = json.loads((q.get("cfg") or ["{}"])[0])
                jpg = look_preview((q.get("c") or [MAIN])[0], over if isinstance(over, dict) else {})
            except (ValueError, TypeError, AttributeError):
                jpg = None
            if not jpg:
                return self._empty(404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self._cors()
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)
            return
        if path == "/timelapse/last":
            # last photo of the timelapse being recorded (live view)
            jpg = _tl["last_frames"].get((q.get("c") or [""])[0]) if _tl["dir"] else None
            if not jpg:
                return self._empty(404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self._cors()
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)
            return
        if path.startswith("/timelapses/"):
            a = os.path.basename(path)
            kind = {".mp4": "video/mp4", ".mov": "video/quicktime", ".zip": "application/zip", ".json": "application/json"}.get(os.path.splitext(a)[1], "image/jpeg")
            return self._file(os.path.join(TIMELAPSE_DIR, a), kind, "download" in q)
        return self._empty(404)

    def _part(self, frame):
        self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n")
        self.wfile.write(frame)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _stream(self, f):
        """Each screen in its thread: it waits for the last frame and sends it. If it is slow it skips frames; if it accepts nothing for 5 s it is dropped."""
        cli = _Client(self._ip())
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=" + BOUNDARY.decode())
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()
        self.connection.settimeout(5)
        if not f.allow(cli):
            notice = _frame_notice(M("camera_relay_too_many_screens_watching_wait_minute", label=f.label))
            try:
                if notice:
                    self._part(notice)
            except Exception:
                pass
            return
        f.ensure()
        try:
            while True:
                cli.new.wait(15)
                cli.new.clear()
                if cli.shut is not None:
                    notice = _frame_notice(cli.shut) if cli.shut else None
                    if notice:
                        self._part(notice)
                    break
                frame, cli.frame = cli.frame, None
                if frame is None:
                    with f.lock:
                        if cli not in f.clients:
                            break  # the camera was removed or changed address
                    continue
                if not cli.local and _load["level"] >= 1:
                    missing = 1.0 / max(1, _service.get("load_fps", 5)) - (time.time() - cli.last_sending)
                    if missing > 0:
                        time.sleep(missing)
                        frame = cli.frame or frame  # the newest that has arrived
                        cli.frame = None
                self._part(frame)
                cli.sent += 1
                cli.last_sending = time.time()
                if not cli.local:
                    cli.bytes_sec.append((cli.last_sending, len(frame)))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError):
            pass
        finally:
            f.drop(cli)

    def _proxy(self, f, rest):
        try:
            with urllib.request.urlopen(f.base + rest, timeout=5) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "text/plain"))
                self._cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception:
            self._empty(502)

    def _photo(self, f, fresh=False):
        r = f.photo(fresh=fresh)
        if not r:
            return self._empty(502)
        body, type_name = r
        self.send_response(200)
        self.send_header("Content-Type", type_name)
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # The client closed the connection in the middle of an answer (camera panel closed, page
        # reloaded): it is normal. Without this socketserver prints the traceback and DSF shows it
        # as a WorkshopService error in DWC (2026-10-09).
        import sys

        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def _start_server():
    srv = _Server((_cfg["bind"], int(_cfg["port"])), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _server[0] = srv
    _log[0](f"camera: relay listening on {_cfg['bind']}:{_cfg['port']} -> {_cfg['url']}")


def _stop_server():
    srv = _server[0]
    _server[0] = None
    if srv:
        srv.shutdown()
        srv.server_close()
        with _sources_lock:
            for f in _sources.values():
                with f.lock:
                    cs = list(f.clients)
                    f.clients.clear()
                for c in cs:
                    c.echar("")
        _log[0]("camera: relay stopped")


def configure(config):
    c = config.get("camera_relay") or {}
    _cfg["url"] = str(c.get("url") or "").strip()
    try:
        _cfg["port"] = int(c.get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        _cfg["port"] = DEFAULT_PORT
    _cfg["bind"] = str(c.get("bind") or "0.0.0.0").strip() or "0.0.0.0"  # "127.0.0.1" keeps the relay on this Pi
    _want[0] = bool(c.get("active")) and bool(_cfg["url"])
    _service.clear()
    _service.update(_mix(SERVICE_DEFAULT, config.get("camera_service") or {}))
    tl = _service.get("timelapse") or {}
    tl["camera"] = _id(tl.get("camera"))
    tl["cameras"] = [_id(c) for c in tl.get("cameras") or []]
    _sync_sources(force=True)


def request(is_active):
    """API call start/stop: no cambia config.json."""
    if is_active and not _cfg["url"]:
        return False
    _want[0] = bool(is_active)
    return True


def requirements(folder=None, current_time=None):
    """What captures and timelapse need on THIS Pi, for the start-up card of the Camera page (nothing is changed here):
    ffmpeg (builds the video), Pillow (writes the date / position on the photo), a writable folder with free space, and a clock that
    is not stuck in the past (a Pi without internet at boot may start in 1970: the names and stamps of the files would be wrong)."""
    import importlib.util
    d = folder or DATA_DIR
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    try:
        idle = shutil.disk_usage(d).free // (1024 * 1024)
    except OSError:
        idle = None
    t = time.localtime(current_time if current_time is not None else time.time())
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "pillow": importlib.util.find_spec("PIL") is not None,
        "folder_ok": bool(d) and os.access(d, os.W_OK),
        "free_mb": idle,
        "hour_ok": t.tm_year >= 2024,
    }


def status():
    f = source(MAIN)
    n = 0
    if f:
        with f.lock:
            n = len(f.clients)
    with _sources_lock:
        other = [x for x in _sources if x != MAIN]
        cameras = [{"id": x, "name": _sources[x].label} for x in [MAIN] + other if x in _sources]
    return {"cameras": cameras, "configured": bool(_cfg["url"]), "running": _server[0] is not None, "requested": _want[0], "port": _cfg["port"], "clients": n,
            "url": _cfg["url"], "other": other, "service": service_cfg(), "requirements": requirements()}


def change_url(config, url):
    """New address of the main camera (2026-10-10: the Main camera of the Camera panel did not show where the video comes from). It is saved in config.json and the relay restarts with the new one (the screens reconnect by themselves)."""
    c = config.setdefault("camera_relay", {})
    c["url"] = url
    c["active"] = True
    configure(config)
    _stop_server()  # run_loop opens it again with the new url


def run_loop(bridge, config, log=None):
    """Supervised process (heartbeats): it starts/stops the server according to _want, keeps the list of cameras, the timelapse and the watchdog."""
    if log:
        _log[0] = log
    _bridge[0] = bridge
    configure(config)
    _tl_clean_leftovers()
    turn = 0
    while True:
        try:
            # The relay is shared: the Camera plugin, Vision and the camera layer of the Work table use it. It rests only
            # when none of them is enabled (Settings > Plugins). The timelapse and the watcher are of the Camera plugin
            # alone. The choice _want is kept: everything comes back by itself when a plugin is enabled (service_modules.py)
            camera_on = service_modules.is_active(service_modules.CAMERA)
            if not (camera_on or service_modules.is_active(service_modules.VISION) or service_modules.is_active(service_modules.WORKBENCH)):
                if _server[0] is not None:
                    _stop_server()
                heartbeats.detail("camera", M("camera_relay_at_rest_neither_camera_vision_nor"))
                heartbeats.ok("camera")
                turn += 1
                time.sleep(3)
                continue
            if _want[0] and _server[0] is None:
                try:
                    _start_server()
                except OSError as e:
                    _log[0](f"camera: could not open port {_cfg['port']} ({e}); retrying in 10 s")
                    time.sleep(10)
            elif not _want[0] and _server[0] is not None:
                _stop_server()
            if turn % 5 == 0:
                _sync_sources()
            if turn % 30 == 5:
                _detect_sources()
            if camera_on:
                if turn % 2 == 0:
                    _tl_tick()
                if turn % 15 == 10:
                    _watch()
                if turn % 5 == 3:
                    _watch_load()
                if turn % 60 == 30:
                    _check_limits()
            heartbeats.ok("camera")
        except Exception as e:
            heartbeats.error("camera", e)
        turn += 1
        time.sleep(1)
