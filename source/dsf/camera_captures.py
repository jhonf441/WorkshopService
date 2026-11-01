"""Photos: the dated capture (`capture`, `burst`), the lists of captures and of videos, and what is done to a file of either kind (rename, keep,
delete). `mark` writes the lines below a photo."""
import glob
import json
import os
import re
import threading
import time

import camera_context
import camera_limits
import camera_sources
from camera_context import MAIN, SIDE_FILES, VIDEO_EXT
from messages import M


def mark(jpeg, lines):
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
        camera_context.log(f"camera: could not mark the photo ({e!r})")
        return jpeg


def _text_pos(pos):
    if not pos:
        return ""
    return " ".join(f"{k}{v:.2f}" for k, v in pos.items() if isinstance(v, (int, float)))


def capture(cid=MAIN, max_age=1.0):
    f = camera_sources.source(cid)
    if f is None:
        return {"ok": False, "error": M("camera_relay_camera_does_not_exist")}
    r = f.photo(max_age=max_age)
    if not r:
        return {"ok": False, "error": M("camera_relay_camera_did_not_answer")}
    m = camera_sources.machine_context()
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
    img = mark(r[0], lines)
    os.makedirs(camera_context.CAPTURES_DIR, exist_ok=True)
    base = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)) + "-" + f.id
    n, file = 0, base + ".jpg"
    while os.path.exists(os.path.join(camera_context.CAPTURES_DIR, file)):
        n += 1
        file = f"{base}-{n}.jpg"
    with open(os.path.join(camera_context.CAPTURES_DIR, file), "wb") as fh:
        fh.write(img)
    meta = {"file": file, "ts": date, "camera": f.id, "camera_name": f.label, "job": m["job"], "pos": m["pos"], "bytes": len(img)}
    with open(os.path.join(camera_context.CAPTURES_DIR, file[:-4] + ".json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    camera_limits.check_limits()
    return dict(meta, ok=True)


BURST_MAX = 30
burst_state = {"left": 0}


def burst(cid=MAIN, count=5, gap=1.0):
    """`count` captures in a row, `gap` seconds apart, made in the background (the answer comes at once, the photos appear in the gallery)."""
    try:
        count, gap = int(count), float(gap)
    except (TypeError, ValueError):
        return {"ok": False, "error": M("camera_relay_invalid_numbers")}
    count, gap = max(2, min(BURST_MAX, count)), max(0.3, min(10.0, gap))
    if camera_sources.source(cid) is None:
        return {"ok": False, "error": M("camera_relay_camera_does_not_exist")}
    if burst_state["left"]:
        return {"ok": False, "error": M("camera_relay_burst_running")}
    burst_state["left"] = count

    def _do():
        try:
            for i in range(count):
                t0 = time.time()
                capture(cid, max_age=min(1.0, gap * 0.6))  # a still that is not older than the gap: two photos are never the same one
                burst_state["left"] = count - i - 1
                if i < count - 1:
                    time.sleep(max(0.0, gap - (time.time() - t0)))
        except Exception as e:
            camera_context.log(f"camera: burst failed ({e!r})")
        finally:
            burst_state["left"] = 0

    threading.Thread(target=_do, daemon=True, name="camera-burst").start()
    return {"ok": True, "count": count, "gap_s": gap}


def list_items_captures():
    out = []
    for j in sorted(glob.glob(os.path.join(camera_context.CAPTURES_DIR, "*.json")), reverse=True):
        try:
            with open(j, encoding="utf-8") as fh:
                m = json.load(fh)
        except Exception:
            continue
        pb = camera_limits.pb_read().get(m.get("file"))
        if pb:
            m["pending_delete_until"] = pb["until"]
        out.append(m)
    return out


def list_items_timelapses():
    out = []
    for v in sorted(camera_limits.videos_list(), reverse=True):
        meta = {}
        try:
            with open(v[:-4] + ".json", encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            pass
        meta.update(file=os.path.basename(v), bytes=os.path.getsize(v), thumbnail=os.path.basename(v)[:-4] + ".jpg")
        pb = camera_limits.pb_read().get(meta["file"])
        if pb:
            meta["pending_delete_until"] = pb["until"]
        out.append(meta)
    return out


def meta_of(file):
    """(path of the .json, dict) of a capture or a timelapse; (None, None) if it does not exist."""
    file = os.path.basename(file or "")
    if not re.match(r"^[\w.-]+\.(jpg|mp4|mov)$", file):
        return None, None
    for folder in (camera_context.TIMELAPSE_DIR, camera_context.CAPTURES_DIR):
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
    j, meta = meta_of(file)
    if j is None:
        return {"ok": False, "error": M("camera_relay_file_does_not_exist")}
    meta["name"] = re.sub(r"\s+", " ", str(label or "")).strip()[:80]
    with open(j, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    return {"ok": True, "name": meta["name"]}


def delete(file):
    file = os.path.basename(file or "")
    if not re.match(r"^[\w.-]+\.(jpg|mp4|mov)$", file):
        return False
    done = False
    for folder in (camera_context.CAPTURES_DIR, camera_context.TIMELAPSE_DIR):
        p = os.path.join(folder, file)
        if os.path.exists(p):
            for ext in SIDE_FILES + VIDEO_EXT:
                try:
                    os.remove(os.path.splitext(p)[0] + ext)
                    done = True
                except OSError:
                    pass
    return done


def remove(file):
    """Deletes a photo or a video with what travels with it and forgets it in the list of what was about to be deleted by itself: {ok}."""
    ok = delete(file)
    if camera_limits.pb_read().pop(os.path.basename(file or ""), None) is not None:
        camera_limits.pb_save()
    camera_context.log(f"camera: deleted {os.path.basename(file or '')}" if ok else f"camera: asked to delete {file} (it does not exist)")
    return {"ok": ok}


def keep(file, value=True):
    """Marks or unmarks keep (never deleted by itself) and checks the caps again."""
    j, meta = meta_of(file)
    if j is None:
        return {"ok": False, "error": M("camera_relay_file_does_not_exist")}
    meta["keep"] = bool(value)
    with open(j, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    camera_limits.check_limits()
    return {"ok": True, "keep": meta["keep"], "per_delete": camera_limits.by_delete()}
