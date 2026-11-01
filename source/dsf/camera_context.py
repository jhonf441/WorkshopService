"""What every module of the camera service shares: the folders, the id of the main camera, and the few globals they all read (the address the
relay listens on, the log, the bridge, the load level of the Pi) with the notice function. It imports no other camera module (the lowest layer:
test_camera_modules.py checks the layers).

The folders are read as `camera_context.CAPTURES_DIR` (not copied by name) on purpose: whoever moves one moves it for every module (the tests
point them to a temporary folder).
"""
import os
import time

import camera_load
import job_states
import paths

_log = [print]


def log(msg):
    """Writes to the log of the service (the one run_loop was given, else the console)."""
    _log[0](msg)


def set_log(fn):
    _log[0] = fn


MAIN = "main"
# outside 0:/sys on purpose (2026-10-11): videos and photos weigh GB and must not show in DWC's
# System editor or in the copies of sys/; the camera does not need to lock files
DATA_DIR = paths.CAMERA_DIR
CAPTURES_DIR = os.path.join(DATA_DIR, "captures")
TIMELAPSE_DIR = os.path.join(DATA_DIR, "timelapse")
FRAMES_DIR = os.path.join(DATA_DIR, "frames")
LUTS_DIR = os.path.join(DATA_DIR, "luts")
VIDEO_EXT = (".mp4", ".mov")  # h264 / h265 go in mp4, ProRes / DNxHR in mov (timelapse_look.extension)
SIDE_FILES = (".jpg", ".json", "-frames.zip")  # what travels with a video: thumbnail, data, kept stills
JOB_ACTIVE = job_states.CAMERA_ACTIVE
cfg = {"bind": "0.0.0.0"}
bridge = [None]
load = camera_load.new_state()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def notify(type_name, raw_text, detail=None):
    log("camera: " + raw_text)
    b = bridge[0]
    if b is None:
        return
    try:
        import activity
        activity.log_event(b, type_name, raw_text, detail=detail)
    except Exception as e:
        log(f"camera: could not record the notice ({e!r})")
