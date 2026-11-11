"""The single service log: one line format, one file with size-based rotation, best effort.

Line format (unchanged from the per-module copies it replaces): "<YYYY-MM-DDTHH:MM:SS> [<tag>] <text>", or without the
"[<tag>] " part when no tag is given. A level other than "info" adds "<LEVEL>: " before the text. The file sink is off until
configure(path) is called (main.py does it at start), so tests and tools that import a module never write a log by accident.

Writing never raises to the caller: a failure (full disk, permissions) is counted in failures() and the line is dropped.
Standard library only, no import of any service module.
"""
import os
import sys
import threading
import time

DEFAULT_MAX_BYTES = 1024 * 1024
DEFAULT_BACKUPS = 3
LEVELS = ("debug", "info", "warning", "error")

_lock = threading.Lock()
_state = {"path": None, "max_bytes": DEFAULT_MAX_BYTES, "backups": DEFAULT_BACKUPS, "failures": 0, "rotations": 0}


def configure(path, max_bytes=DEFAULT_MAX_BYTES, backups=DEFAULT_BACKUPS):
    """Turns the file sink on at path (None turns it off). Rotation: path -> path.1 -> ... -> path.<backups>."""
    with _lock:
        _state.update(path=path, max_bytes=int(max_bytes), backups=max(0, int(backups)))


def path():
    return _state["path"]


def failures():
    """How many lines could not be written to the file since the start (public counter, never reset by the service)."""
    return _state["failures"]


def rotations():
    return _state["rotations"]


def format_line(text, tag="", level="info", now=None):
    """The line without the line break."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", now) if now else time.strftime("%Y-%m-%dT%H:%M:%S")
    marker = "" if level == "info" else level.upper() + ": "
    return f"{stamp} {'[' + tag + '] ' if tag else ''}{marker}{text}"


def _rotate(file_path, backups):
    if backups <= 0:
        os.remove(file_path)
    else:
        for n in range(backups, 0, -1):
            src = file_path if n == 1 else f"{file_path}.{n - 1}"
            if os.path.exists(src):
                dst = f"{file_path}.{n}"
                if os.path.exists(dst):
                    os.remove(dst)  # rename does not overwrite on Windows
                os.rename(src, dst)
    _state["rotations"] += 1


def _append(line):
    """Caller holds _lock. Never raises."""
    file_path = _state["path"]
    if not file_path:
        return
    try:
        data = (line + "\n").encode("utf-8", "replace")
        folder = os.path.dirname(file_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        try:
            size = os.path.getsize(file_path)
        except OSError:
            size = 0
        if size and size + len(data) > _state["max_bytes"]:
            _rotate(file_path, _state["backups"])
        with open(file_path, "ab") as f:
            f.write(data)
    except Exception:  # noqa: BLE001 - best effort by design: the log must never break the caller
        _state["failures"] += 1


def log(text, tag="", level="info", to_stdout=False):
    """Writes one line to the file (when configured) and, if to_stdout, to the console/journal too.
    to_stdout=True is the actionable channel that DWC shows as a pop-up: use it with care."""
    try:
        line = format_line(str(text), tag, level)
    except Exception:  # noqa: BLE001
        _state["failures"] += 1
        return
    if to_stdout:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        _append(line)


def for_tag(tag):
    """A log_file(msg) function for one module: the same signature the per-module copies had."""
    def log_file(msg):
        log(msg, tag)
    return log_file
