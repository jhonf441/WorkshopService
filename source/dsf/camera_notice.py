"""The camera in the notices: the watch that warns when a camera stops answering (`watch`), the load of the Pi (`watch_load`), the photo and the
short video for a phone notice (`snapshot`, `clip`, used by notifier.py: they only TAKE the picture of a camera; whether a notice carries one, of which
camera and of what kind is the notifier's policy) and the text frame a cut screen receives."""
import os
import shutil
import subprocess
import threading
import time
import urllib.request

import camera_load
import camera_captures
import camera_context
import camera_sources
from camera_config import service
from camera_context import MAIN
from camera_sources import sources, sources_lock
from messages import M


def watch():
    if not service.get("notice_drop"):
        return
    with sources_lock:
        fs = list(sources.values())
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
        drop = t - f.last_ok > service["drop_s"]
        if drop and not f.drop_notified:
            f.drop_notified = True
            camera_context.notify("camera", M("cam_not_responding", name=f.label, since=time.strftime("%H:%M", time.localtime(f.last_ok))),
                    {"camera": f.id, "name": f.label, "url": f.url, "silent_s": round(t - f.last_ok)})
        elif not drop and f.drop_notified:
            f.drop_notified = False
            camera_context.notify("camera", M("cam_responding", name=f.label), {"camera": f.id, "name": f.label, "url": f.url})


def _source_of(cid=None):
    """The camera of a picture for a notice: the one asked, else the main one (a camera that no longer exists falls back to the main one)."""
    return camera_sources.source(cid or MAIN) or camera_sources.source(MAIN)


def snapshot(cid=None):
    """JPEG (bytes) of the camera `cid` (the main one by default) with the date, or None. Used by notifier.py."""
    f = _source_of(cid)
    if f is None:
        return None
    r = f.photo(max_age=2.0, timeout=5)
    if not r:
        return None
    return camera_captures.mark(r[0], [camera_context.now() + "  " + f.label])


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


class _Recorder(camera_sources.Null):
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
        camera_context.log("camera: could not build the notice video (" + (r.stderr or "")[-200:] + ")")
        return None
    with open(output, "rb") as fh:
        payload = fh.read()
    if len(payload) > CLIP_MAX_BYTES:
        camera_context.log(f"camera: the notice video weighs {len(payload) // 1024} kB, only the photo is sent")
        return None
    return payload


def clip(seconds=5, cid=None):
    """MP4 (bytes) of a few seconds of the camera `cid` (the main one by default), or None. Used by notifier.py."""
    if camera_context.load["level"] >= 2 or not shutil.which("ffmpeg"):
        return None
    f = _source_of(cid)
    if f is None:
        return None
    if not _clip_lock.acquire(blocking=False):
        return None  # another one is already recording: that notice goes with the photo
    folder = os.path.join(camera_context.FRAMES_DIR, "aviso-" + time.strftime("%Y%m%d-%H%M%S"))
    try:
        sec = max(CLIP_MIN_S, min(CLIP_MAX_S, float(seconds or 5)))
        return _clip_arm(_clip_record(f, sec), folder)
    except Exception as e:
        camera_context.log(f"camera: notice video failed ({e!r})")
        return None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        _clip_lock.release()


def watch_load():
    """Every ~5 s: level 0 normal, 1 loaded (fewer frames to the remote ones), 2 critical (2 remote screens per camera). To go down, 30 s without load are needed.
    Temperature and CPU come from the service's own health data (camera_load.reading); only the kB/s going out are measured here."""
    t = time.time()
    b = camera_context.bridge[0]
    temp, cpu = camera_load.reading(getattr(b, "payload", None), t)
    with sources_lock:
        fs = list(sources.values())
    total = 0
    for f in fs:
        with f.lock:
            cs = [c for c in f.clients if not c.null and not c.local]
        for c in cs:
            c.bytes_sec = [x for x in c.bytes_sec if t - x[0] < 5]
            total += sum(b_ for _, b_ in c.bytes_sec)
    kbps = total / 5.0 / 1024
    old, level, reasons = camera_load.step(camera_context.load, temp, cpu, kbps, service.get("load_kbps", 3000), t)
    if level == old:
        return
    raw_text = {0: M("cam_load_normal"),
                1: M("cam_load_high", reason=camera_context.load["reason"], fps=service.get("load_fps", 5)),
                2: M("cam_load_critical", reason=camera_context.load["reason"] or M("cam_load_still"))}[level]
    if camera_load.notify_worthy(reasons) and camera_load.notice_due(camera_context.load, level, t):
        camera_context.notify("camera_load", raw_text, {"level": level, "reason": camera_context.load["reason"], "cpu_pct": camera_context.load["cpu"], "temp_c": camera_context.load["temp"],
                                        "kbps": camera_context.load["kbps"], "fps_remote": service.get("load_fps", 5)})  # camera_context.notify also notes it in the log; it reaches the phone through notifier.py
    else:
        camera_context.log("camera: " + raw_text)
    if level == 2:
        for f in fs:
            with f.lock:
                remote = sorted((c for c in f.clients if not c.null and not c.local and not c.shut), key=lambda c: c.since)
            for c in remote[:-2] if len(remote) > 2 else []:
                c.cut(M("camera_relay_cut_system_heavily_loaded_tap_see", p=camera_context.load['reason'] or M("camera_relay_high_load")))


_notices_jpg = {}


def frame_notice(raw_text):
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
