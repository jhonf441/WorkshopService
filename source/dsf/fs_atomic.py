"""The atomic write of a file, ONE implementation (the review of 2026-10-29 found about 13 copies of tmp + fsync + os.replace): the data is
written to a temporary file next to the target, flushed to the card (fsync) and only then swapped in with os.replace, so a power cut leaves
the old file or the new one, never half of it. The modules with extra rules (config_store's .bak and permissions, settings_store's
revision, the config history) keep them on top of this; the plain ones call it directly.
"""
import json
import os


def _tmp(path):
    return path + ".tmp-" + str(os.getpid())


def write_bytes(path, data, make_dirs=True):
    """Writes `data` (bytes) to `path` atomically. Creates the folder when it is missing."""
    if make_dirs:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
    tmp = _tmp(path)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())  # to the card before the rename (power cut)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_text(path, text, make_dirs=True):
    write_bytes(path, text.encode("utf-8"), make_dirs)


def write_json(path, obj, make_dirs=True, **dump_args):
    """json.dump arguments pass through (separators, indent, sort_keys, ensure_ascii)."""
    write_text(path, json.dumps(obj, **dump_args), make_dirs)
