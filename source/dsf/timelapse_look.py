"""Cinema controls of the timelapse: output format, framing, grade, speed of the shutter and the interval ramp.

Pure functions (no ffmpeg run, no files except `list_luts` / `pack_frames`): `camera_relay.py` calls them while it records and assembles, and
`test_timelapse_look.py` checks the filter strings. Every key lives in the `timelapse` block of `camera_service` (the defaults of the
service) and can also be given for ONE take (`overrides`), which is frozen when the take starts.

    cd dsf && PYTHONDONTWRITEBYTECODE=1 python -m unittest test_timelapse_look -v
"""
import csv
import io
import os
import re
import shutil
import zipfile

CODECS = ("h264", "h265", "prores", "dnxhr")
# 1 draft, 2 standard, 3 high, 4 master (what each one means depends on the codec)
H264_CRF = {1: 28, 2: 23, 3: 18, 4: 12}
H265_CRF = {1: 32, 2: 27, 3: 22, 4: 16}
PRORES_PROFILE = {1: 1, 2: 2, 3: 3, 4: 4}  # lt, standard, hq, 4444
DNXHR_PROFILE = {1: "dnxhr_lb", 2: "dnxhr_sq", 3: "dnxhr_hq", 4: "dnxhr_hqx"}
ASPECTS = {"source": None, "16:9": 16 / 9, "1.85:1": 1.85, "2:1": 2.0, "2.39:1": 2.39, "4:3": 4 / 3, "1:1": 1.0, "4:5": 0.8, "9:16": 9 / 16}
RESOLUTIONS = (0, 720, 1080, 1440, 2160)  # height of the output; 0 = the one of the camera
FPS_MIN, FPS_MAX = 5.0, 120.0
BLEND_MAX = 8
LUT_MAX_BYTES = 6 * 1024 * 1024
LUT_NAME = re.compile(r"^[\w .()-]{1,60}\.cube$")

DEFAULTS = {
    "codec": "h264",
    "quality": 2,
    "bit10": False,          # 10-bit pixels (h265 / h264); prores and dnxhr choose their own
    "resolution": 0,
    "aspect": "source",
    "pan_x": 0.5,            # 0 left .. 1 right: where the crop sits when the aspect cuts the width
    "pan_y": 0.5,
    "zoom_start": 1.0,       # Ken Burns over the whole video
    "zoom_end": 1.0,
    "end_x": 0.5,            # where the centre of the frame ends (0..1); it starts at pan_x / pan_y
    "end_y": 0.5,
    "brightness": 0.0,       # -0.3 .. 0.3
    "contrast": 1.0,         # 0.5 .. 2
    "saturation": 1.0,       # 0 .. 3
    "gamma": 1.0,            # 0.3 .. 3
    "lut": "",
    "blend": 1,              # frames averaged (virtual shutter): 1 = off
    "stabilize": 0,          # 0 off, 1 light, 2 strong: smooths the shake between stills (deshake; only in the one-video-per-camera mode)
    "fade_in_s": 0.0,
    "fade_out_s": 0.0,
    "each_end_s": 0,         # interval ramp: 0 = no ramp, else the interval reached at the end of ramp_min
    "ramp_min": 60,
    "keep_frames": False,    # also keep the stills (zip with frames.csv) for the editor
}


def _num(value, low, high, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(default)
    if v != v:  # nan
        v = float(default)
    return max(low, min(high, v))


def normalise(tl):
    """Fills and limits the cinema keys of a `timelapse` dict (in place) and returns it."""
    d = DEFAULTS
    tl["codec"] = tl.get("codec") if tl.get("codec") in CODECS else d["codec"]
    tl["quality"] = int(_num(tl.get("quality"), 1, 4, d["quality"]))
    tl["bit10"] = bool(tl.get("bit10"))
    try:
        res = int(tl.get("resolution") or 0)
    except (TypeError, ValueError):
        res = 0
    tl["resolution"] = res if res in RESOLUTIONS else 0
    tl["aspect"] = tl.get("aspect") if tl.get("aspect") in ASPECTS else "source"
    for k in ("pan_x", "pan_y", "end_x", "end_y"):
        tl[k] = round(_num(tl.get(k), 0.0, 1.0, d[k]), 3)
    tl["zoom_start"] = round(_num(tl.get("zoom_start"), 1.0, 3.0, 1.0), 3)
    tl["zoom_end"] = round(_num(tl.get("zoom_end"), 1.0, 3.0, 1.0), 3)
    tl["brightness"] = round(_num(tl.get("brightness"), -0.3, 0.3, 0.0), 3)
    tl["contrast"] = round(_num(tl.get("contrast"), 0.5, 2.0, 1.0), 3)
    tl["saturation"] = round(_num(tl.get("saturation"), 0.0, 3.0, 1.0), 3)
    tl["gamma"] = round(_num(tl.get("gamma"), 0.3, 3.0, 1.0), 3)
    tl["lut"] = tl.get("lut") if isinstance(tl.get("lut"), str) and (not tl.get("lut") or LUT_NAME.match(tl["lut"])) else ""
    tl["blend"] = int(_num(tl.get("blend"), 1, BLEND_MAX, 1))
    tl["stabilize"] = int(_num(tl.get("stabilize"), 0, 2, 0))
    tl["fade_in_s"] = round(_num(tl.get("fade_in_s"), 0.0, 10.0, 0.0), 2)
    tl["fade_out_s"] = round(_num(tl.get("fade_out_s"), 0.0, 10.0, 0.0), 2)
    tl["each_end_s"] = int(_num(tl.get("each_end_s"), 0, 3600, 0))
    tl["ramp_min"] = int(_num(tl.get("ramp_min"), 1, 1440, 60))
    tl["keep_frames"] = bool(tl.get("keep_frames"))
    return tl


def fps_value(tl):
    """Frame rate as ffmpeg wants it: the broadcast ones are exact fractions (23.976 -> 24000/1001)."""
    f = _num(tl.get("fps"), FPS_MIN, FPS_MAX, 15)
    for exact, text in ((23.976, "24000/1001"), (29.97, "30000/1001"), (59.94, "60000/1001")):
        if abs(f - exact) < 0.01:
            return text
    return f"{f:g}"


def fps_float(tl):
    text = fps_value(tl)
    if "/" in text:
        a, b = text.split("/")
        return int(a) / int(b)
    return float(text)


def interval_now(tl, elapsed_s):
    """Seconds between photos right now: constant, or sliding linearly from each_s to each_end_s along ramp_min minutes."""
    start = max(2, int(tl.get("each_s") or 10))
    end = int(tl.get("each_end_s") or 0)
    if end < 2:
        return start
    k = max(0.0, min(1.0, elapsed_s / (max(1, int(tl.get("ramp_min") or 60)) * 60.0)))
    return max(2.0, start + (end - start) * k)


def extension(tl):
    return "mov" if tl.get("codec") in ("prores", "dnxhr") else "mp4"


def encoder_args(tl):
    """ffmpeg arguments for the codec: what comes after the filters. Colour is tagged Rec.709 so an editor does not guess."""
    q = int(tl.get("quality") or 2)
    codec = tl.get("codec") or "h264"
    tags = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    if codec == "prores":
        pix = "yuv444p10le" if q == 4 else "yuv422p10le"
        return ["-c:v", "prores_ks", "-profile:v", str(PRORES_PROFILE[q]), "-vendor", "apl0", "-pix_fmt", pix] + tags
    if codec == "dnxhr":
        pix = "yuv422p10le" if q == 4 else "yuv422p"
        return ["-c:v", "dnxhd", "-profile:v", DNXHR_PROFILE[q], "-pix_fmt", pix] + tags
    pix = "yuv420p10le" if tl.get("bit10") else "yuv420p"
    if codec == "h265":
        return ["-c:v", "libx265", "-preset", "veryfast", "-crf", str(H265_CRF[q]), "-tag:v", "hvc1", "-pix_fmt", pix,
                "-movflags", "+faststart"] + tags
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(H264_CRF[q]), "-pix_fmt", pix, "-movflags", "+faststart"] + tags


def _even(v):
    return max(2, int(round(v)) // 2 * 2)


def output_size(src_w, src_h, tl):
    """(w, h) of the video: the crop of the aspect first, then the height asked (never above the pixels: it only scales up when the user asks)."""
    w, h = float(src_w), float(src_h)
    ratio = ASPECTS.get(tl.get("aspect") or "source")
    if ratio:
        if w / h > ratio:
            w = h * ratio
        else:
            h = w / ratio
    target = int(tl.get("resolution") or 0)
    if target:
        w, h = w * target / h, float(target)
    return _even(w), _even(h)


def crop_filter(src_w, src_h, tl):
    """crop to the aspect with the position chosen (pan_x / pan_y); '' when the aspect is the camera's."""
    ratio = ASPECTS.get(tl.get("aspect") or "source")
    if not ratio:
        return ""
    w, h = float(src_w), float(src_h)
    if w / h > ratio:
        cw, ch = h * ratio, h
    else:
        cw, ch = w, w / ratio
    cw, ch = _even(cw), _even(ch)
    x = int(round((w - cw) * float(tl.get("pan_x", 0.5))))
    y = int(round((h - ch) * float(tl.get("pan_y", 0.5))))
    return f"crop={cw}:{ch}:{x}:{y}"


def grade_filters(tl, luts_dir):
    """LUT first (it expects the camera's colour), then the eq adjustments. Empty when nothing is changed."""
    out = []
    lut = tl.get("lut") or ""
    if lut and LUT_NAME.match(lut) and os.path.isfile(os.path.join(luts_dir, lut)):
        out.append("lut3d=file='" + os.path.join(luts_dir, lut).replace("\\", "/").replace("'", "") + "'")
    b, c, s, g = (float(tl.get(k, v)) for k, v in (("brightness", 0.0), ("contrast", 1.0), ("saturation", 1.0), ("gamma", 1.0)))
    if abs(b) > 1e-6 or abs(c - 1) > 1e-6 or abs(s - 1) > 1e-6 or abs(g - 1) > 1e-6:
        out.append(f"eq=brightness={b:g}:contrast={c:g}:saturation={s:g}:gamma={g:g}")
    return out


def zoom_filter(tl, out_w, out_h, frames, fps):
    """Slow push / pull with a drift of the centre (Ken Burns), one output frame per input frame. '' when there is no movement."""
    zs, ze = float(tl.get("zoom_start", 1.0)), float(tl.get("zoom_end", 1.0))
    x0, y0 = float(tl.get("pan_x", 0.5)), float(tl.get("pan_y", 0.5))
    x1, y1 = float(tl.get("end_x", x0)), float(tl.get("end_y", y0))
    if abs(zs - 1) < 1e-6 and abs(ze - 1) < 1e-6 and abs(x1 - x0) < 1e-6 and abs(y1 - y0) < 1e-6:
        return ""
    last = max(1, int(frames) - 1)
    t = f"(on/{last})"
    z = f"{zs:g}+({ze:g}-{zs:g})*{t}"
    px = f"{x0:g}+({x1:g}-{x0:g})*{t}"
    py = f"{y0:g}+({y1:g}-{y0:g})*{t}"
    return f"zoompan=z='{z}':x='(iw-iw/zoom)*({px})':y='(ih-ih/zoom)*({py})':d=1:s={out_w}x{out_h}:fps={fps}"


STABILIZE = {1: "deshake=rx=16:ry=16:edge=mirror", 2: "deshake=rx=48:ry=48:edge=mirror"}


def look_filters(tl, src_w, src_h, frames, luts_dir):
    """Whole chain for one camera in 'separate' mode (before the title / end card): (filters, (out_w, out_h))."""
    out_w, out_h = output_size(src_w, src_h, tl)
    fps = fps_value(tl)
    f = []
    if STABILIZE.get(int(tl.get("stabilize") or 0)):
        f.append(STABILIZE[int(tl["stabilize"])])  # first: it looks at the whole picture, before the crop
    crop = crop_filter(src_w, src_h, tl)
    if crop:
        f.append(crop)
    f += grade_filters(tl, luts_dir)
    zoom = zoom_filter(tl, out_w, out_h, frames, fps)
    if zoom:
        f.append(f"scale={out_w * 2}:{out_h * 2}:flags=lanczos")  # a bigger picture makes zoompan move by sub-pixels, not by jumps
        f.append(zoom)
    f.append(f"scale={out_w}:{out_h}:flags=lanczos,setsar=1")
    if int(tl.get("blend") or 1) > 1:
        f.append(f"tmix=frames={int(tl['blend'])}")
    return f, (out_w, out_h)


def fade_filters(tl, total_s):
    """Fade from / to black over the final video (title and end card included)."""
    out = []
    fi, fo = float(tl.get("fade_in_s") or 0), float(tl.get("fade_out_s") or 0)
    if fi > 0:
        out.append(f"fade=t=in:st=0:d={fi:g}")
    if fo > 0 and total_s > fo:
        out.append(f"fade=t=out:st={total_s - fo:.3f}:d={fo:g}")
    return out


def list_luts(luts_dir):
    try:
        return sorted(x for x in os.listdir(luts_dir) if LUT_NAME.match(x))
    except OSError:
        return []


def valid_lut(data):
    """A .cube file is text with a LUT_3D_SIZE (or LUT_1D_SIZE) line and numbers; nothing else is saved."""
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > LUT_MAX_BYTES:
        return False
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        return False
    head = text[:4000]
    return bool(re.search(r"^\s*LUT_(3D|1D)_SIZE\s+\d+", head, re.M))


def pack_frames(folders, zip_path, times):
    """zip (stored, jpg does not compress) of the stills with frames.csv: frame, epoch seconds, clock time. folders = {name inside the zip: folder}."""
    rows = io.StringIO()
    w = csv.writer(rows)
    w.writerow(["frame", "epoch_s", "time"])
    for i, t in enumerate(times, 1):
        w.writerow([i, f"{t:.3f}", _clock(t)])
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("frames.csv", rows.getvalue())
        for name, folder in folders.items():
            for f in sorted(os.listdir(folder)):
                if f.endswith(".jpg"):
                    z.write(os.path.join(folder, f), (name + "/" if name else "") + f)
    return zip_path


def unpack_frames(zip_path, dest):
    """Inverse of pack_frames: writes dest/<camera>/NNNNN.jpg (a zip without folders is the camera "main"). Returns ([cameras in zip order], number of frames, [epoch seconds])."""
    cams, n, times = [], 0, []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if info.filename == "frames.csv":
                rows = csv.reader(io.StringIO(z.read(info).decode("utf-8")))
                next(rows, None)
                times = [float(r[1]) for r in rows if len(r) >= 2]
                continue
            if len(parts) > 2 or not re.match(r"^\d{5}\.jpg$", parts[-1]):
                continue
            cam = parts[0] if len(parts) == 2 else "main"
            if not re.match(r"^[A-Za-z0-9_-]{1,40}$", cam):
                continue
            os.makedirs(os.path.join(dest, cam), exist_ok=True)
            with z.open(info) as src, open(os.path.join(dest, cam, parts[-1]), "wb") as out:
                shutil.copyfileobj(src, out)
            if cam not in cams:
                cams.append(cam)
            n = max(n, int(parts[-1][:5]))
    return cams, n, times


def _clock(t):
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
