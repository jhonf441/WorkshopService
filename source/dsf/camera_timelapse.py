"""Timelapse: the ONE recording session (a job's or a manual one), its schedule, the tick that takes a photo every so often, the state published
to the pages, the cinema looks (preview, LUTs, encoders) and the two things done to a finished video (`edit`, `rerender`)."""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import timelapse_look as look
import camera_assembly
import camera_captures
import camera_config
import camera_context
import camera_limits
import camera_sources
from camera_captures import burst_state
from camera_config import PRESET_KEYS, TL_MAX_CAMERAS, service
from camera_context import MAIN, VIDEO_EXT
from messages import M


# It records from one or several cameras at once (frames/<session>/<camera>/00001.jpg, the same
# number = the same moment in all of them) and when done assembles the video according to "armed":
# separate: one video per camera
# mosaic: all at once in a grid (up to 4)
# toggle: a single video that passes from one camera to another every "segment_s" seconds of video,
# with a fade of "fade_s" (0 = cut)
# "title": banner at the start with the name and the date (over the first still frame); "final_s":
# it stays still on the last frame.
# It starts by itself with each job ("active") or by hand (POST /timelapse).
TL_MAX_FRAMES = 20000
# ONE timelapse session at a time: a job's and a manual one share this global (see the docstring of camera_relay.py).
_tl = {"dir": None, "job": None, "start": None, "n": 0, "last": 0.0, "cameras": [], "manual": False,
       "assembling": None, "taking": False, "skip": None, "nulls": {}, "layer_last": None, "last_frames": {},
       "cfg": None, "times": []}


def _tl_cfg():
    """Settings of the take being recorded (frozen); the service defaults when nothing is recorded."""
    return _tl["cfg"] or service["timelapse"]


def last_frame(cid):
    """Last photo of the timelapse being recorded for the camera `cid` (the live view), or None."""
    return _tl["last_frames"].get(cid) if _tl["dir"] else None


def _tl_cameras():
    tl = _tl["cfg"] or service["timelapse"]
    ids = [str(c or MAIN) for c in (tl.get("cameras") or []) if camera_sources.source(c) is not None] or [str(tl.get("camera") or MAIN)]
    if camera_sources.source(ids[0]) is None:
        ids = [MAIN]
    return ids[:TL_MAX_CAMERAS]


def _tl_begin(label, manual=False, overrides=None):
    os.makedirs(camera_context.FRAMES_DIR, exist_ok=True)
    _tl["cfg"] = camera_config.take_cfg(overrides)
    folder = time.strftime("%Y%m%d-%H%M%S") + "-" + (re.sub(r"[^\w-]+", "_", os.path.splitext(label)[0])[:40] or "timelapse")
    d = os.path.join(camera_context.FRAMES_DIR, folder)
    cams = _tl_cameras()
    nulls = {}
    for cid in cams:
        os.makedirs(os.path.join(d, cid), exist_ok=True)
        f = camera_sources.source(cid)
        if f is not None and not f.base:
            n = camera_sources.Null()
            with f.lock:
                f.clients.append(n)
            f.ensure()
            nulls[cid] = n
    _tl.update(dir=d, job=label, start=time.time(), n=0, last=0.0, cameras=cams, manual=bool(manual), nulls=nulls,
               layer_last=None, last_frames={}, times=[])
    camera_context.log(f"camera: timelapse of {label} starts ({', '.join(cams)}{', by hand' if manual else ''})")


def _tl_release_nulls():
    for cid, n in list(_tl["nulls"].items()):
        f = camera_sources.source(cid)
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
        f = camera_sources.source(cid)
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
    current_time = camera_context.now()
    for cid, jpg in photos.items():
        if stamp:
            f = camera_sources.source(cid)
            jpg = camera_captures.mark(jpg, [current_time + "  " + (f.label if f is not None else cid) + ("  " + str(M("camera_relay_stamp_layer", layer=_tl["layer_last"])) if _tl["layer_last"] is not None else "")])
        with open(os.path.join(d, cid, f"{_tl['n']:05d}.jpg"), "wb") as fh:
            fh.write(jpg)
        _tl["last_frames"][cid] = jpg  # live view (GET /timelapse/last)


def _tl_take():
    try:
        _tl_frame()
    except Exception as e:
        camera_context.log(f"camera: timelapse frame failed ({e!r})")
    finally:
        _tl["taking"] = False


def _tl_finish():
    d, n, label, begin, cams, manual = _tl["dir"], _tl["n"], _tl["job"], _tl["start"], list(_tl["cameras"]), _tl["manual"]
    cfg, times = json.loads(json.dumps(_tl_cfg())), list(_tl["times"])
    _tl_release_nulls()
    _tl.update(dir=None, job=None, start=None, n=0, cameras=[], manual=False, cfg=None, times=[])
    if not d:
        return
    if n < 3:
        shutil.rmtree(d, ignore_errors=True)
        camera_context.log(f"camera: timelapse of {label} discarded (less than 3 frames)")
        return
    names = {}
    for cid in cams:
        f = camera_sources.source(cid)
        names[cid] = f.label if f is not None else cid
    _tl["assembling"] = os.path.basename(d)

    def _arm():
        try:
            ready = camera_assembly.tl_arm(d, cams, names, n, cfg, {"job": label, "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(begin)),
                                                          "duration_s": int(time.time() - begin), "manual": manual}, times)
            camera_limits.check_limits()
            camera_context.log(f"camera: timelapse ready ({', '.join(ready) or 'nothing'})")
        except Exception as e:
            camera_context.log(f"camera: could not build the timelapse ({e!r})")
        finally:
            shutil.rmtree(d, ignore_errors=True)
            _tl["assembling"] = None

    threading.Thread(target=_arm, daemon=True, name="camera-timelapse").start()


_editing = {"file": None}


def edit(file, since=0.0, until=None, speed=1.0):
    """New video (the original stays): trimmed [from, to] seconds and with another speed (0.25 to 8). It is assembled in the background."""
    file = os.path.basename(file or "")
    src = os.path.join(camera_context.TIMELAPSE_DIR, file)
    if not file.endswith(VIDEO_EXT) or not os.path.isfile(src):
        return {"ok": False, "error": M("camera_relay_video_does_not_exist")}
    if _editing["file"]:
        return {"ok": False, "error": M("camera_relay_another_video_already_being_edited")}
    if camera_limits.without_space():
        return {"ok": False, "error": M("camera_relay_little_space_left_system_less")}
    since = max(0.0, float(since or 0))
    until = float(until) if until not in (None, "") else None
    velocity = max(0.25, min(8.0, float(speed or 1)))
    if until is not None and until <= since + 0.2:
        return {"ok": False, "error": M("camera_relay_end_has_after_start")}
    n = 1
    while os.path.exists(os.path.join(camera_context.TIMELAPSE_DIR, f"{file[:-4]}-ed{n}.mp4")):
        n += 1
    output = os.path.join(camera_context.TIMELAPSE_DIR, f"{file[:-4]}-ed{n}.mp4")
    _, meta = camera_captures.meta_of(file)
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
                camera_context.log(f"camera: could not edit {file} ({(r.stderr or '')[-300:]})")
                return
            shutil.copyfile(src[:-4] + ".jpg", output[:-4] + ".jpg") if os.path.exists(src[:-4] + ".jpg") else None
            label = (meta.get("name") or meta.get("job") or file[:-4])
            parts = []
            if since > 0 or until is not None:
                parts.append(f"{since:g}-{until:g} s" if until is not None else str(M("camera_relay_edited_from_second", since=since)))
            if abs(velocity - 1) > 1e-6:
                parts.append(f"x{velocity:g}")
            meta.update(name=f"{label} ({', '.join(parts) or M('camera_relay_edited_copy')})")
            with open(output[:-4] + ".json", "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False)
            camera_limits.check_limits()
            camera_context.log(f"camera: video edited {os.path.basename(output)}")
        except Exception as e:
            camera_context.log(f"camera: could not edit {file} ({e!r})")
        finally:
            _editing["file"] = None

    threading.Thread(target=_do, daemon=True, name="camera-edit").start()
    return {"ok": True, "file": os.path.basename(output)}


def rerender(file, overrides=None):
    """New video (the original stays) from the stills kept with it, with another look: codec, framing, grade, speed, stabilization. Assembled in the background.
    It starts from the settings the original was made with (`look` in its .json) and applies `overrides` on top."""
    file = os.path.basename(file or "")
    if not re.match(r"^[\w.-]+\.(mp4|mov)$", file) or not os.path.isfile(os.path.join(camera_context.TIMELAPSE_DIR, file)):
        return {"ok": False, "error": M("camera_relay_file_does_not_exist")}
    zip_path = os.path.join(camera_context.TIMELAPSE_DIR, file[:-4] + "-frames.zip")
    if not os.path.isfile(zip_path):
        return {"ok": False, "error": M("camera_relay_frames_not_kept")}
    if _editing["file"] or _tl["assembling"]:
        return {"ok": False, "error": M("camera_relay_another_video_already_being_edited")}
    if camera_limits.without_space():
        return {"ok": False, "error": M("camera_relay_little_space_left_system_less")}
    _, meta = camera_captures.meta_of(file)
    meta = dict(meta or {})
    wanted = dict(meta.get("look") or {})
    wanted.update({k: v for k, v in (overrides or {}).items() if k in PRESET_KEYS})
    cfg = camera_config.take_cfg(wanted)
    cfg["keep_frames"] = False  # the zip of the original is already there
    n = 1
    while any(os.path.exists(os.path.join(camera_context.TIMELAPSE_DIR, f"{file[:-4]}-rr{n}{e}")) for e in VIDEO_EXT):
        n += 1
    stem = f"{file[:-4]}-rr{n}"
    d = os.path.join(camera_context.FRAMES_DIR, stem)
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
            made = camera_assembly.tl_arm(d, cams, names, count, cfg, info, times)
            camera_limits.check_limits()
            camera_context.log(f"camera: video rebuilt from {file} ({', '.join(made) or 'nothing'})")
        except Exception as e:
            camera_context.log(f"camera: could not rebuild {file} ({e!r})")
        finally:
            shutil.rmtree(d, ignore_errors=True)
            _editing["file"] = None

    threading.Thread(target=_do, daemon=True, name="camera-rerender").start()
    return {"ok": True, "file": stem}


def tl_begin_by_hand(label="", overrides=None):
    try:
        camera_config.take_cfg(overrides)
    except (TypeError, ValueError, AttributeError):
        return {"ok": False, "error": M("camera_relay_invalid_numbers")}
    if _tl["dir"]:
        return {"ok": False, "error": M("camera_relay_timelapse_already_being_recorded", job=str(_tl["job"]))}
    if camera_limits.without_space():
        return {"ok": False, "error": M("camera_relay_little_space_left_system_less_delete")}
    label = re.sub(r"[\r\n\"]+", " ", str(label or "")).strip()[:60] or ("Timelapse " + time.strftime("%H:%M"))
    _tl_begin(label, manual=True, overrides=overrides)
    return dict(tl_state(), ok=True)


def tl_stop():
    if not _tl["dir"]:
        return {"ok": False, "error": M("camera_relay_no_timelapse_being_recorded")}
    m = camera_sources.machine_context()
    if m["job"]:
        _tl["skip"] = m["job"]  # stopped by hand: it does not start again by itself with this job
    if _prog_read().get("started"):
        _prog_save({})  # stopped by hand: the schedule no longer runs
    _tl_finish()
    return dict(tl_state(), ok=True)


# Scheduled (2026-10-10, "advanced functions"): start and/or stop at a time. It is saved in
# sd/camera/schedule.json (it survives a restart).
SCHEDULED = os.path.join(camera_context.DATA_DIR, "schedule.json")
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
        os.makedirs(camera_context.DATA_DIR, exist_ok=True)
        with open(SCHEDULED, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    except OSError as e:
        camera_context.log(f"camera: could not save the schedule ({e!r})")


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
    # integers: see camera_limits.check_limits (floats come out with 6 digits through dsf-python)
    _prog_save({"since": int(since) or None, "until": int(until) or None, "name": label})
    camera_context.log(f"camera: timelapse scheduled from {time.strftime('%d/%m %H:%M', time.localtime(since)) if since else 'now'} until {time.strftime('%d/%m %H:%M', time.localtime(until)) if until else 'it is stopped'}")
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
            camera_context.log("camera: scheduled timelapse did not start: another one was already recording")
        else:
            r = tl_begin_by_hand(p.get("name") or M("camera_relay_scheduled_timelapse_name", time=time.strftime("%H:%M")))
            if not r.get("ok"):
                camera_context.notify("camera", M("cam_tl_scheduled_failed", error=str(r.get("error"))))
    if not p.get("since") and not p.get("started"):
        p["started"] = True  # only a stop time: it starts right away
        _prog_save(p)
        if not _tl["dir"]:
            tl_begin_by_hand(p.get("name") or M("camera_relay_scheduled_timelapse_name", time=time.strftime("%H:%M")))
    if p.get("until") and current_time >= p["until"]:
        if _tl["dir"] and _tl["manual"]:
            camera_context.log("camera: scheduled timelapse: stop time reached")
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
    f = camera_sources.source(cid)
    jpg = last_frame(str(cid or MAIN))
    if jpg is None and f is not None:
        got = f.photo(max_age=2.0, timeout=5)
        jpg = got[0] if got else None
    if not jpg:
        return None
    cfg = camera_config.take_cfg(overrides)
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
    chain += look.grade_filters(cfg, camera_context.LUTS_DIR)
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
    os.makedirs(camera_context.LUTS_DIR, exist_ok=True)
    with open(os.path.join(camera_context.LUTS_DIR, name), "wb") as fh:
        fh.write(data)
    return {"ok": True, "luts": look.list_luts(camera_context.LUTS_DIR)}


def lut_remove(name):
    name = os.path.basename(str(name or ""))
    if not look.LUT_NAME.match(name):
        return {"ok": False, "error": M("camera_relay_lut_name_invalid")}
    try:
        os.remove(os.path.join(camera_context.LUTS_DIR, name))
    except OSError:
        pass
    return {"ok": True, "luts": look.list_luts(camera_context.LUTS_DIR)}


def tl_state():
    return {"recording": bool(_tl["dir"]), "job": _tl["job"], "frames": _tl["n"], "assembling": _tl["assembling"],
            "manual": _tl["manual"], "cameras": list(_tl["cameras"]),
            "since_s": int(time.time() - _tl["start"]) if _tl["start"] else None,
            "disk_free_gb": round((camera_limits.disk_free() or 0) / 1024 ** 3, 1),
            "videos_gb": round(camera_limits.videos_bytes() / 1024 ** 3, 2),
            "max_min": _tl_cfg().get("max_min", 720),
            "editing": _editing["file"], "burst": burst_state["left"],
            "scheduled": {k: v for k, v in _prog_read().items() if k in ("since", "until", "name", "started")} or None,
            "layer": _tl["layer_last"], "trigger": _tl_cfg().get("trigger", "time"),
            "take": ({k: _tl["cfg"].get(k) for k in ("codec", "quality", "fps", "each_s", "each_end_s", "aspect", "resolution", "keep_frames")}
                     if _tl["cfg"] else None),
            "interval_s": round(look.interval_now(_tl_cfg(), time.time() - _tl["start"]), 1) if _tl["start"] else None}


def tl_clean_leftovers():
    """At startup nothing is recorded: whatever is in frames/ was left by a cut (the Pi was switched off in the middle of a recording or of the assembly)."""
    try:
        leftovers = [os.path.join(camera_context.FRAMES_DIR, x) for x in os.listdir(camera_context.FRAMES_DIR)]
    except OSError:
        return
    for d in leftovers:
        shutil.rmtree(d, ignore_errors=True)
    if leftovers:
        camera_context.log(f"camera: deleted {len(leftovers)} leftovers of unfinished timelapses")


def tl_tick():
    _prog_tick()
    cfg = service["timelapse"]
    m = camera_sources.machine_context()
    job = m["job"]
    paused = m["state"] in ("paused", "pausing")
    if _tl["skip"] and _tl["skip"] != job:
        _tl["skip"] = None
    if _tl["dir"] and camera_limits.without_space():
        camera_context.notify("camera", M("cam_tl_stopped_space", job=_tl["job"]))
        _tl_finish()
        return
    if _tl["dir"] and time.time() - _tl["start"] > _tl_cfg().get("max_min", 720) * 60:
        camera_context.notify("camera", M("cam_tl_stopped_max", job=_tl["job"], minutes=_tl_cfg().get("max_min", 720)))
        if not _tl["manual"]:
            _tl["skip"] = _tl["job"]  # it does not start again with the same job
        _tl_finish()
        return
    if _tl["dir"]:
        if not _tl["manual"] and (not cfg["active"] or not job or job != _tl["job"]):
            _tl_finish()
    if not _tl["dir"] and cfg["active"] and job and job != _tl["skip"] and not camera_limits.without_space():
        _tl_begin(job)
    by_layer = _tl["dir"] and not _tl["manual"] and _tl_cfg().get("trigger") == "layer" and m.get("layer") is not None
    if by_layer:
        # one photo per layer (3D printing): when job.layer changes
        if m["layer"] != _tl["layer_last"] and not _tl["taking"] and _tl["n"] < TL_MAX_FRAMES:
            _tl["layer_last"] = m["layer"]
            _tl["last"] = time.time()
            _tl["taking"] = True
            threading.Thread(target=_tl_take, daemon=True, name="camera-tl-frame").start()
        return
    if (_tl["dir"] and not _tl["taking"] and (_tl["manual"] or not paused)
            and time.time() - _tl["last"] >= look.interval_now(_tl_cfg(), time.time() - _tl["start"]) and _tl["n"] < TL_MAX_FRAMES):
        _tl["last"] = time.time()
        _tl["taking"] = True
        threading.Thread(target=_tl_take, daemon=True, name="camera-tl-frame").start()
