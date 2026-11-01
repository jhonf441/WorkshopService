"""
Camera service of the workshop: a 1-to-many MJPEG relay, photos, dated captures, timelapse of the jobs and a warning if a camera goes down. It runs INSIDE the plugin's
backend (it used to be ~/camera-relay/camera_relay.py as a systemd --user service, and WorkshopService stopped/started it with sudo).

Why it exists: the ESP32-camera (stock firmware app_httpd.cpp) only serves ONE /stream client at a time reliably. The relay opens ONE connection to each camera (only while
someone is watching) and forwards the same bytes to every browser.

2026-10-10 ("refine and improve the camera service"): several cameras at once, state and statistics, a warning if one goes down, a photo in the notifications,
dated captures and timelapse.

The code is split by layers, each module imports only the ones above it in this list (test_camera_modules.py checks it):
  camera_context    folders, id of the main camera, the globals everybody reads (main address, log, bridge, load), the notice
  camera_config     service settings: defaults, validation, the settings of one timelapse take
  camera_sources    the cameras (connection, last photo, numbers), the screens watching, the list, detect, machine context
  camera_limits     free space and the caps of captures and videos (what is about to be deleted)
  camera_assembly   assembling the video of a timelapse (ffmpeg)
  camera_captures   photos: capture, burst, lists, rename / keep / delete
  camera_timelapse  the one recording session, schedule, tick, state, cinema looks, edit and rerender of a video
  camera_notice     drop watch, load watch, photo and video for the phone notices, text frame
  camera_control    what is done to a camera itself, not to its video: the flash
  camera_image      the image settings of an ESP32-camera: what is saved (camera.json), applied again when it restarts, the profile that fits the job
  camera_key        the key of the day for the remote screens
  camera_http       the HTTP server (routes below)
  camera_relay      this file: configure / request / status / run_loop and the public face the API handler, notifier.py and main.py use

Cameras (one list, camera_sources.camera_list):
  0:/sys/workshop/config/cameras.json (the settings store, written by the Camera page): every camera of the list, `main` included with its own
  address. The relay serves the main one and the ESP32-CAMs that have an address of their own and "relay" != false (`via_relay`).
  service.json "camera_relay": {"active", "bind"}: whether the relay starts by itself and where it listens (the port is fixed: ports.py).

Routes (CORS only for the own DWC origin, port 8090). The contract is versioned: /state carries `proto` (camera_proto.py). This port SERVES media and
reads; everything that changes something is an operation of the API (camera.capture, burst, remove, keep, rename, edit, rerender, timelapse, schedule,
flash, image.set...: handlers/camera_relay.py), with its role and its line in the audit:
  /stream /snapshot /control /status      the main one (as always: Vision and the screens use these)
                                          /snapshot?fresh=1: always a new photo; after a /control only frames that arrived more than 1 s later count
  /c/<id>/stream|snapshot|control|status  another camera of the list
  /state                                  JSON: proto, each camera (connected / reconnecting / down, fps, kB/s, photo delay, clients) + config, timelapse, load
  /captures  /captures/<file>             list (JSON) and the image
  /per_delete                             what is about to be deleted by itself (caps, with a warning)
  /timelapses  /timelapses/<file>         list (JSON) and the video / thumbnail (?download=1 -> as a file)
  /key?t=<key>  (only from the Pi)        {"requires", "ok"}: so other services (Vision :8095) ask for the same key
  GET /timelapse/last?c=<camera>          last photo of what is being recorded (live)
  /timelapse/preview?c=&cfg=              a photo with the look of the studio applied
  /luts                                   the look files (.cube) that were uploaded
  POST /luts?name=  POST /luts/remove?name=   the only writes of this port: a look file is up to 6 MB and the body of the API is 1 MB

Only ONE timelapse session exists at a time (the global `camera_timelapse._tl`): the one of a job and the manual one share it. A manual start is refused
while one is recording, and the one of a job does not start while a manual one runs. Separating them would need one `_tl` per session,
its own frames folder and its own assembly slot; not done on purpose (the ffmpeg assembly is also one at a time on this Pi).

Files in /opt/dsf/sd/workshop/camera/ (they survive reinstalling the plugin; before /opt/dsf/sd/camara/): captures/ (jpg + json), timelapse/ (mp4 + jpg thumbnail), frames/ (temporary).

Screens and load (2026-10-10: "what happens if many requests reach the relay, can the DWC password be used, is there a purge"):
  - each screen receives the last frame at its own pace (own thread): a slow screen no longer slows down the others or the camera; if it accepts nothing for 5 s it is dropped
  - cap on remote screens per camera ("screens_max"): when exceeded the oldest is cut (it gets a frame with the reason); one that was cut less than 60 s ago cannot kick another out (no ping-pong)
  - load (temperature, CPU, kB/s going out; temperature and CPU are NOT measured here: camera_load.py reads what health_poller publishes): loaded -> the remote screens receive "load_fps" frames/s; critical -> 2 per camera remain. It is noted in Activity (type camera_load)
  - with a password in DWC (M551) and "clave" active, the remote screens need the day's key (?t= or cookie workshop_camera): the API (camera_relay) gives it S"token", which requires the DWC session
  - local (127.0.0.1: kiosk, Vision, timelapse) does not count, is not cut and asks for no key

Service config: service.json "camera_service" (see SERVICE_DEFAULT).
Control: the API, camera.* (handlers/camera_relay.py): status, start, stop, detect, service, token and the writes listed above.

"""
import os
import shutil
import time

import heartbeats
import ports
import service_modules
import camera_config
import camera_context
import camera_control
import camera_http
import camera_image
import camera_limits
import camera_notice
import camera_sources
import camera_timelapse
from camera_config import SERVICE_DEFAULT, service
from camera_context import MAIN
from camera_http import server
from camera_sources import sources, sources_lock
from messages import M

# The public face of the camera service: what the API handler (handlers/camera_relay.py), notifier.py and main.py call. The work is in the
# camera_* modules (test_camera_modules.py keeps their layers).
from camera_captures import burst, capture, keep, remove, rename  # noqa: F401
from camera_config import change_service, service_cfg  # noqa: F401
from camera_control import set_flash as flash  # noqa: F401
from camera_image import image_get, image_set  # noqa: F401
from camera_key import token  # noqa: F401
from camera_notice import clip, snapshot  # noqa: F401
from camera_timelapse import edit, rerender, tl_begin_by_hand, tl_schedule, tl_state, tl_stop, tl_unschedule  # noqa: F401


_want = [False]  # what was asked for (config or API call start/stop)


def configure(config):
    c = config.get("camera_relay") or {}
    camera_context.cfg["bind"] = str(c.get("bind") or "0.0.0.0").strip() or "0.0.0.0"  # "127.0.0.1" keeps the relay on this Pi
    _want[0] = bool(c.get("active", True))  # it opens the port once the main camera has an address (run_loop)
    service.clear()
    service.update(camera_config.mix(SERVICE_DEFAULT, config.get("camera_service") or {}))
    tl = service.get("timelapse") or {}
    tl["camera"] = str(tl.get("camera") or MAIN)
    tl["cameras"] = [str(c or MAIN) for c in tl.get("cameras") or []]
    camera_sources.sync_sources(force=True)


def request(is_active):
    """API call start/stop: does not change config.json."""
    if is_active and not camera_sources.configured():
        return False
    _want[0] = bool(is_active)
    return True


def requirements(folder=None, current_time=None):
    """What captures and timelapse need on THIS Pi, for the start-up card of the Camera page (nothing is changed here):
    ffmpeg (builds the video), Pillow (writes the date / position on the photo), a writable folder with free space, and a clock that
    is not stuck in the past (a Pi without internet at boot may start in 1970: the names and stamps of the files would be wrong)."""
    import importlib.util
    d = folder or camera_context.DATA_DIR
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
    """What the screens, Vision and the Camera page ask (camera.status). `cameras` is the whole list of cameras.json (camera_sources.camera_list:
    each record with `via_relay`) and `cameras_rev` the revision of cameras.json it was read at (a page writes the list back with it), `configured`
    says the main camera has an address, `running` whether the port is open."""
    f = camera_sources.source(MAIN)
    n = 0
    if f:
        with f.lock:
            n = len(f.clients)
    cameras, rev = camera_sources.read_list()
    return {"cameras": cameras, "cameras_rev": rev, "configured": camera_sources.configured(), "running": server[0] is not None, "requested": _want[0],
            "port": ports.CAMERA_RELAY, "clients": n, "service": camera_config.service_cfg(), "requirements": requirements()}


def detect(url):
    """Asks a camera (by its address) whether it is an ESP32-camera and whether it has a flash (the API operation camera.detect)."""
    return camera_sources.detect(url)


def run_loop(bridge, config, log=None):
    """Supervised process (heartbeats): it starts/stops the server according to _want, keeps the list of cameras, the timelapse and the watchdog."""
    if log:
        camera_context.set_log(log)
    camera_context.bridge[0] = bridge
    configure(config)
    camera_timelapse.tl_clean_leftovers()
    turn = 0
    while True:
        try:
            # The relay is shared: the Camera plugin, Vision and the camera layer of the Work table use it. It rests only
            # when none of them is enabled (Settings > Plugins). The timelapse and the watcher are of the Camera plugin
            # alone. The choice _want is kept: everything comes back by itself when a plugin is enabled (service_modules.py)
            camera_on = service_modules.is_active(service_modules.CAMERA)
            if not (camera_on or service_modules.is_active(service_modules.VISION) or service_modules.is_active(service_modules.WORKBENCH)):
                if server[0] is not None:
                    camera_http.stop_server()
                camera_control.flash_tick(shutdown=True)  # nobody can look at a camera any more: a flash left on goes off
                heartbeats.detail("camera", M("camera_relay_at_rest_neither_camera_vision_nor"))
                heartbeats.ok("camera")
                turn += 1
                time.sleep(3)
                continue
            if _want[0] and server[0] is None and camera_sources.configured():
                try:
                    camera_http.start_server()
                except OSError as e:
                    camera_context.log(f"camera: could not open port {ports.CAMERA_RELAY} ({e}); retrying in 10 s")
                    time.sleep(10)
            elif server[0] is not None and not (_want[0] and camera_sources.configured()):
                camera_http.stop_server()
            if turn % 30 == 5:
                camera_sources.detect_sources()
            if camera_on:
                if turn % 2 == 0:
                    camera_timelapse.tl_tick()
                if turn % 15 == 10:
                    camera_notice.watch()
                if turn % 5 == 3:
                    camera_notice.watch_load()
                if turn % 5 == 1:
                    camera_control.flash_tick()
                if turn % 5 == 2:
                    camera_image.image_tick()
                if turn % 60 == 30:
                    camera_limits.check_limits()
            heartbeats.ok("camera")
        except Exception as e:
            heartbeats.error("camera", e)
        turn += 1
        time.sleep(1)
