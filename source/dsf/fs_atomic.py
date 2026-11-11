"""The atomic write of a file, ONE implementation (the review of 2026-10-29 found about 13 copies of tmp + fsync + os.replace): the data is
written to a temporary file next to the target, flushed to the card (fsync) and only then swapped in with os.replace, so a power cut leaves
the old file or the new one, never half of it. The modules with extra rules (config_store's .bak and permissions, settings_store's
revision, the config history) keep them on top of this; the plain ones call it directly.
"""
import json
import os
import threading


def _tmp(path):
    """One temporary name per writer (process AND thread): two threads writing the same target at once must not share it."""
    return path + ".tmp-%d-%d" % (os.getpid(), threading.get_ident())


def _sync_dir(path):
    """fsync of the folder that holds `path`, so the rename itself reaches the card (a power cut right after os.replace can otherwise
    bring the old name back). Not possible on Windows (a folder cannot be opened that way): there it is a no-op."""
    if os.name == "nt":
        return
    folder = os.path.dirname(os.path.abspath(path))
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_tmp(tmp, data, mode):
    """Writes `data` to the temporary file `tmp`, created exclusively with `mode` from the start (a secret is never briefly readable)."""
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())  # to the card before the rename (power cut)


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


def write_bytes(path, data, make_dirs=True, mode=0o666):
    """Writes `data` (bytes) to `path` atomically. Creates the folder when it is missing. `mode` is the file mode (0o600 for secrets)."""
    if make_dirs:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
    tmp = _tmp(path)
    _remove_quiet(tmp)  # a leftover of an earlier crash of the same pid/thread number
    try:
        _write_tmp(tmp, data, mode)
        os.replace(tmp, path)
    except BaseException:
        _remove_quiet(tmp)
        raise
    _sync_dir(path)


def write_with_backup(path, data, validate=None, mode=0o666, make_dirs=True):
    """write_bytes plus a rolling copy: the file that is there NOW stays as <path>.bak, but only if `validate(old_bytes)` accepts it
    (raises ValueError or returns False to refuse; default: it parses as JSON), so a damaged file never replaces a healthy .bak. The copy is written atomically and synced too.
    The new content goes through its own temporary file (one per writer) and the swap is the last step: a cut anywhere before it
    leaves the old file, and the .bak is always a complete file."""
    if validate is None:
        validate = _is_json
    if make_dirs:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
    tmp = _tmp(path)
    _remove_quiet(tmp)
    try:
        _write_tmp(tmp, data, mode)  # the new content is complete on the card before anything else is touched
        try:
            with open(path, "rb") as fh:
                old = fh.read()
            healthy = validate(old) is not False  # raising ValueError or returning False means damaged
        except (OSError, ValueError):
            healthy = False
        if healthy:
            try:
                write_bytes(path + ".bak", old, make_dirs=False, mode=mode)
            except OSError:
                pass  # the copy is best effort: the new file is what matters
        os.replace(tmp, path)
    except BaseException:
        _remove_quiet(tmp)
        raise
    _sync_dir(path)


def _is_json(raw):
    try:
        json.loads(raw.decode("utf-8-sig"))
        return True
    except ValueError:
        return False


def write_text(path, text, make_dirs=True):
    write_bytes(path, text.encode("utf-8"), make_dirs)


def write_json(path, obj, make_dirs=True, **dump_args):
    """json.dump arguments pass through (separators, indent, sort_keys, ensure_ascii)."""
    write_text(path, json.dumps(obj, **dump_args), make_dirs)
