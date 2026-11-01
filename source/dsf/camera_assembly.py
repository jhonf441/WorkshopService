"""Assembling the video of a timelapse with ffmpeg: `tl_arm` takes the folder of stills of a session and writes the videos (one per camera, a mosaic
or alternating cameras) with their .json and thumbnail. The filters of the cinema controls come from timelapse_look.py."""
import json
import os
import shutil
import subprocess

import timelapse_look as look
import camera_context
from camera_config import ARMED, PRESET_KEYS


TL_TITLE_S = 2.5
SOURCE_TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


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
    os.makedirs(camera_context.TIMELAPSE_DIR, exist_ok=True)
    base = os.path.join(camera_context.TIMELAPSE_DIR, os.path.basename(d))
    last = lambda c: os.path.join(d, c, f"{n:05d}.jpg")
    entry = lambda c, ini=1: ["-framerate", fps, "-start_number", str(ini), "-i", os.path.join(d, c, "%05d.jpg")]
    done_items = []
    grade = ",".join(look.grade_filters(cfg, camera_context.LUTS_DIR))
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
                camera_context.log(f"camera: could not keep the frames ({e!r})")
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
            chain, (ow, oh) = look.look_filters(cfg, w, h, n, camera_context.LUTS_DIR)
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
