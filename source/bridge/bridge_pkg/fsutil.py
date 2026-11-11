"""Files of the bridge: the paths under the SD, atomic JSON writing and reading."""


import json
import os
import threading


SD_DIR = os.environ.get("BRIDGE_SD_DIR", "/opt/dsf/sd")


class Paths:
    """Every file the bridge reads or writes, under one SD directory."""

    def __init__(self, sd_dir=None):
        root = sd_dir or SD_DIR
        sysdir = os.path.join(root, "sys")
        self.config = os.path.join(sysdir, "workshop", "config", "bridge.json")
        self.state = os.path.join(sysdir, "workshop", "data", "bridge-state.json")
        self.action = os.path.join(sysdir, "workshop", "data", "bridge-action.json")
        self.viewer = os.path.join(sysdir, "workshop", "data", "bridge-viewer.json")
        # the local key of the service lives outside the SD (DWC serves the SD)
        self.api_token = os.path.join(os.path.dirname(os.path.abspath(root)), "conf", "workshop-api-token")
        self.interrupted = os.path.join(sysdir, "workshop", "data", "live-interrupted.json")


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _sync_dir(path):
    """fsync of the folder, so the rename itself reaches the card. A no-op on Windows (a folder cannot be opened that way)."""
    if os.name == "nt":
        return
    try:
        fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_json_atomic(path, data, mode=0o664, indent=None, durable=True):
    """Temporary file of its own (process and thread in the name), flushed to the card (`durable`), then swapped in with os.replace: a
    power cut leaves the old file or the new one. The same recipe as dsf/fs_atomic.write_bytes (the bridge runs apart from the service
    and cannot import dsf). The state file passes durable=False: it is rewritten every few seconds and is worth nothing after a reboot."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp-%d-%d" % (path, os.getpid(), threading.get_ident())
    _remove_quiet(tmp)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            if durable:
                os.fsync(f.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        _remove_quiet(tmp)
        raise
    if durable:
        _sync_dir(path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ensure_action_file(paths, log=print):
    """The page saves its actions to this file: it must exist from the start. Returns what was done."""
    done = []
    if not os.path.exists(paths.action):
        try:
            write_json_atomic(paths.action, {"seq": None})
            done.append(f"created {paths.action}")
        except OSError as e:
            log(f"Could not create {paths.action}: {e}")
    return done
