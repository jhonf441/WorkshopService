"""Free space and the caps of the captures and the videos: what exceeds a cap is NOT deleted at that moment but left "to delete" with a deadline
and a notice (see the comment above BY_DELETE); `check_limits` marks, unmarks and deletes what expired."""
import glob
import json
import os
import shutil
import time

import messages
import camera_context
from camera_config import service
from camera_context import SIDE_FILES, VIDEO_EXT
from messages import M, of_row, dumps_params


TL_DISK_MIN = 2 * 1024 ** 3  # with less free it does not start and it stops what is recording


def disk_free():
    try:
        return shutil.disk_usage(camera_context.DATA_DIR if os.path.isdir(camera_context.DATA_DIR) else "/").free
    except OSError:
        return None


def without_space():
    idle = disk_free()
    return idle is not None and idle < TL_DISK_MIN


def videos_list():
    return [v for e in VIDEO_EXT for v in glob.glob(os.path.join(camera_context.TIMELAPSE_DIR, "*" + e))]


def videos_bytes():
    total = 0
    for f in glob.glob(os.path.join(camera_context.TIMELAPSE_DIR, "*")):
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
BY_DELETE = os.path.join(camera_context.DATA_DIR, "per_delete.json")
_pb = {"list": None}


def pb_read():
    if _pb["list"] is None:
        try:
            with open(BY_DELETE, encoding="utf-8") as fh:
                _pb["list"] = json.load(fh)
        except Exception:
            _pb["list"] = {}
    return _pb["list"]


def pb_save():
    try:
        os.makedirs(camera_context.DATA_DIR, exist_ok=True)
        with open(BY_DELETE, "w", encoding="utf-8") as fh:
            json.dump(_pb["list"] or {}, fh, ensure_ascii=False)
    except OSError as e:
        camera_context.log(f"camera: could not save the list to delete ({e!r})")


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
    vmax = int(service.get("timelapses_max") or 30)
    videos = sorted(videos_list())
    free = [v for v in videos if not _kept(v)]
    for v in free[:max(0, len(videos) - vmax)]:
        out[os.path.basename(v)] = ("video", M("cam_limit_videos", n=vmax))
    gb = float(service.get("timelapses_gb") or 5)
    total = videos_bytes()
    for v in free:
        if total <= gb * 1024 ** 3:
            break
        total -= sum(os.path.getsize(v[:-4] + e) for e in SIDE_FILES + (v[-4:],) if os.path.exists(v[:-4] + e))
        out.setdefault(os.path.basename(v), ("video", M("cam_limit_video_space", gb=gb)))
    fmax = int(service.get("captures_max") or 300)
    photos = sorted(glob.glob(os.path.join(camera_context.CAPTURES_DIR, "*.jpg")))
    for f in [x for x in photos if not _kept(x)][:max(0, len(photos) - fmax)]:
        out[os.path.basename(f)] = ("photo", M("cam_limit_captures", n=fmax))
    return out


def check_limits():
    """Marks what exceeds (with a warning), unmarks what no longer exceeds and deletes what expired."""
    pb = pb_read()
    cand = _candidates()
    current_time = time.time()
    waiting = int(service.get("delete_wait_h") or 24) * 3600
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
        _delete_already(os.path.join(camera_context.TIMELAPSE_DIR if d["kind"] == "video" else camera_context.CAPTURES_DIR, a))
        camera_context.log(f"camera: deleted {a} ({d['reason']}; notified and nobody kept it)")
    if new or expired or loose:
        pb_save()
    if new:
        nv = sum(1 for a in new if pb[a]["kind"] == "video")
        nf = len(new) - nv
        that = M("cam_files_both", videos=nv, photos=nf) if nv and nf else (M("cam_files_videos", n=nv) if nv else M("cam_files_photos", n=nf))
        when = time.strftime("%d/%m %H:%M", time.localtime(current_time + waiting))
        camera_context.notify("camera_deleted", M("cam_about_to_delete", what=that, when=when, reason=of_row(pb[new[0]].get("reason_key"), pb[new[0]].get("reason_params")) or pb[new[0]]["reason"]))


def by_delete():
    pb = pb_read()
    # reason as {"key", "params"} (the gallery shows it in the language of its DWC); an old entry: its text as it is
    return {"items": [dict(d, file=a, reason=messages.data(of_row(d.get("reason_key"), d.get("reason_params")) or d.get("reason")))
                      for a, d in sorted(pb.items(), key=lambda x: x[1]["until"])],
            "wait_h": int(service.get("delete_wait_h") or 24)}
