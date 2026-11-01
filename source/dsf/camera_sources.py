"""The cameras the relay serves: each one is a `_Source` (its connection, opened only while somebody watches, the last photo and its numbers),
the screens watching are `Client`s, the list is cameras.json (`camera_list`, the one list, read through the settings store), and `detect` asks a
camera whether it is an ESP32-camera with a flash. Also `machine_context` (job, state and position of the machine for the captures) and
`cap_screens` (how many remote screens one camera accepts now)."""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import net_guard
import ports
import settings_store
import camera_context
from camera_config import service
from camera_context import JOB_ACTIVE, MAIN
from messages import M


UPSTREAM_RETRY_DELAY = 2.0
UPSTREAM_READ_CHUNK = 8192
SNAPSHOT_MAX_AGE = 2.0
sources = {}  # id -> _Source
sources_lock = threading.Lock()
flash_since = {}  # camera id -> when its flash was switched on (camera_control.py is the only one that changes it)
_cameras_mtime = [None]
_sync_lock = threading.Lock()


def base_of(url):
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


def cap_screens():
    cap = int(service.get("screens_max") or 0)
    if camera_context.load["level"] >= 2:
        cap = min(cap, 2) if cap else 2
    return cap


class Client:
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

    def cut(self, reason):
        self.shut = reason
        self.new.set()

    def summary(self):
        return {"ip": self.ip, "local": self.local, "since_s": int(time.time() - self.since), "sent": self.sent}


class Null:
    """Fake client: keeps a camera's video open without /capture (non-ESP32) while recording, so there is always a recent frame."""

    null = True
    local = True
    shut = None
    since = 0.0

    def put(self, _frame):
        pass

    def cut(self, _reason):
        pass

    def summary(self):
        return {}


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
        self.flash = None  # whether the camera has a flash (detect), None = not known yet; whether it is on is flash_since
        self.last_view = 0.0  # the last time a screen asked this camera for a photo or opened its video
        # after a /control (e.g. Vision changes framesize) the saved photo and the frames still on
        # their way are from the old setting
        self.invalidated_en = 0.0

    @property
    def base(self):
        return base_of(self.url)

    def seen(self):
        """A screen asked for this camera (photo or video): somebody is looking."""
        self.last_view = time.time()

    def watched(self):
        """True while a screen has the video open."""
        with self.lock:
            return any(not c.null for c in self.clients)

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
        cap = cap_screens()
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
                    old.cut(M("camera_relay_cut_same_computer_opened_another_tab", label=self.label, cap=cap))
                else:
                    if time.time() - _kicked.get(cli.ip, 0) < THROWN_WAIT_S:
                        return False
                    old = remote[0]
                    _kicked[old.ip] = time.time()
                    old.cut(M("camera_relay_cut_too_many_screens_watching_maximum", label=self.label, cap=cap))
                    camera_context.log(f"camera {self.id}: limit of {cap} screens, the oldest one is cut ({old.ip})")
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
                    camera_context.log(f"camera {self.id}: connection error ({e!r}), retrying")
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
            self.last_error = f"photo: {type(e).__name__}: {e}"
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
            "flash": {"capable": self.flash, "on": self.id in flash_since},
        }


def _served(c):
    """True when THIS relay opens the video of the camera `c` of the list: it has an address the relay can reach (not a [HOSTNAME] one, which
    only a browser can resolve, and not one that already points at the relay itself), the person did not ask for the direct way (`relay` false),
    and it is the main camera or an ESP32-camera. The ONE place that says which cameras go through the relay: the screens, Vision and the
    timelapse read the answer (`via_relay`), none of them repeats the rule."""
    url = c["url"]
    if not url.lower().startswith("http") or "[HOSTNAME]" in url:
        return False
    try:
        if urllib.parse.urlsplit(url).port == ports.CAMERA_RELAY:
            return False
    except ValueError:
        return False
    return c["relay"] and (c["esp32"] or c["id"] == MAIN)


def _entry(c):
    """One record of cameras.json as the rest of the service sees it, or None when it has no usable id."""
    if not isinstance(c, dict):
        return None
    cid = re.sub(r"[^A-Za-z0-9_-]", "", str(c.get("id") or ""))[:40]
    if not cid:
        return None
    name = str(c.get("name") or "").strip()[:30] or (str(M("camera_relay_main_camera_name")) if cid == MAIN else cid)
    out = {"id": cid, "name": name, "url": str(c.get("url") or "").strip(), "photo": str(c.get("photo") or "").strip(), "esp32": bool(c.get("esp32")),
           "relay": c.get("relay") is not False, "flash_source": "strip" if c.get("flash_source") == "strip" else "camera",
           "open": "video" if c.get("open") == "video" else "photo"}
    out["via_relay"] = _served(out)
    return out


def flash_of(entry):
    """{capable, on} of a camera of the list: `capable` is True for the work lights as flash, what `detect` found for the LED of an ESP32-camera the
    relay serves, None when it is not known; `on` is what camera_control switched on."""
    if entry["flash_source"] == "strip":
        capable = True
    else:
        f = sources.get(entry["id"])
        capable = f.flash if f is not None else None
    return {"capable": capable, "on": entry["id"] in flash_since}


def read_list():
    """(the list, the revision of cameras.json it was read at): `camera_list` with the revision a writer sends back (settings.set base_rev) so a
    page that was open with an old copy cannot erase what somebody else saved."""
    try:
        got = settings_store.get("cameras")
    except settings_store.SettingsError:
        return [], settings_store.NO_FILE_REV
    value = got["value"]
    seen, out = set(), []
    for c in (value.get("cameras") if isinstance(value, dict) else None) or []:
        e = _entry(c)
        if e and e["id"] not in seen:
            seen.add(e["id"])
            e["flash"] = flash_of(e)
            out.append(e)
    return out, got["rev"]


def camera_list():
    """THE list of cameras: the records of cameras.json (the settings store, written by the Camera page) in the order of the file, each with
    `via_relay`. The relay, the screens (camera.status) and Vision (camera.status) all read this one list; `main` is one more record, with its
    own address. Empty while there is no file."""
    return read_list()[0]


def sync_sources(force=False):
    """Makes `sources` the cameras of the list that the relay serves (when cameras.json changed, or `force`). One caller at a time: a second one
    that arrives while the first rebuilds waits, so nobody sees a list that is half made (the loop of the relay would stop the server)."""
    with _sync_lock:
        _sync_sources(force)


def _sync_sources(force):
    try:
        mt = os.path.getmtime(settings_store.path_of("cameras"))
    except OSError:
        mt = None
    if not force and mt == _cameras_mtime[0]:
        return
    _cameras_mtime[0] = mt
    want = {c["id"]: (c["name"], c["url"]) for c in camera_list() if c["via_relay"]}
    with sources_lock:
        for cid in list(sources):
            if cid not in want or sources[cid].url != want[cid][1]:
                f = sources.pop(cid)
                with f.lock:
                    cs = list(f.clients)
                    f.clients.clear()  # the browsers reconnect by themselves
                for c in cs:
                    c.cut("")
        for cid, (label, url) in want.items():
            if cid not in sources:
                sources[cid] = _Source(cid, label, url)
            else:
                sources[cid].label = label


def source(cid):
    with sources_lock:
        return sources.get(str(cid or MAIN))


def configured():
    """True when the main camera has an address the relay can serve (the relay has nothing to open before that). It follows the file: a main
    address saved a moment ago counts."""
    sync_sources()
    return source(MAIN) is not None


def detect(url):
    """Asks the camera whether it is an ESP32-camera (CameraWebServer: /status with framesize) and whether it has a flash (led_intensity in /status)."""
    base = base_of(url)
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


def detect_sources():
    """Once per source: esp32 / flash for the viewer."""
    with sources_lock:
        fs = list(sources.values())
    for f in fs:
        if f.esp32 is None:
            d = detect(f.url)
            # an answer only counts when the camera answered: one failed /status (the camera's Wi-Fi drops, it is busy
            # streaming) used to be stored as "not an ESP32, no flash" for good and the viewer hid the flash button
            if d.get("ok") and d.get("reachable", True):
                f.esp32, f.flash = d.get("esp32"), d.get("flash")


def machine_context():
    """{job, status, pos} from the object model of the single subscription (machine_state)."""
    try:
        import machine_state
        st = machine_state.get_status(timeout=3, max_age_s=3)
    except Exception:
        return {"job": None, "state": None, "pos": None, "layer": None}
    status = (st.get("state") or {}).get("status")
    label = (((st.get("job") or {}).get("file") or {}).get("fileName")) or None
    live = None
    b = camera_context.bridge[0]
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
