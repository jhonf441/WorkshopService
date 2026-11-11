"""Where the G-code library may look: paths inside the SD tree only, G-code files only.

    resolve_file(path, sd_root) -> real path   (ValueError when it is not a G-code file inside the SD)
    resolve_dir(path, sd_root)  -> real path of a folder inside the SD
    display(real, sd_root)      -> "0:/gcodes/a.gcode"
    scan(real_dir)              -> [{"name", "path" (real), "size", "mtime_ns"}] of the G-code files directly in the folder, and the sub-folders
    scan_tree(real_dir, ...)    -> ([files], truncated) the G-code files of the folder AND its sub-folders (bounded depth and file count, no
                                   hidden folders, no symbolic links followed): what the background indexer queues

A path may be written "0:/gcodes/a.g", "/gcodes/a.g", "gcodes/a.g" (all relative to the SD) or the real path on the Pi when it is already
inside the SD. `..` and symbolic links that leave the SD are refused (the real path is resolved first). Nothing here reads a file.
"""
import os

import sd_paths

EXTENSIONS = (".g", ".gcode", ".gco", ".nc", ".gc", ".ngc", ".tap")
DEFAULT_DIR = "0:/gcodes"
MAX_DEPTH = 4  # levels of sub-folders the background indexer descends below a watched folder
MAX_FILES_PER_SCAN = 5000  # G-code files one scan of a watched folder (with its sub-folders) reports; the rest waits for a later scan


def _inside(real, root):
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def _real(path, sd_root):
    """The real path inside the SD (a real Pi path that is already inside it is accepted); SdPathError (a ValueError) if not."""
    return sd_paths.resolve(path, root=sd_root)


def resolve_file(path, sd_root):
    real = _real(path, sd_root)
    if not real.lower().endswith(EXTENSIONS):
        raise ValueError("not a G-code file")
    if not os.path.isfile(real):
        raise FileNotFoundError(path)
    return real


def resolve_dir(path, sd_root):
    real = _real(path or DEFAULT_DIR, sd_root)
    if not os.path.isdir(real):
        raise FileNotFoundError(path)
    return real


def display(real, sd_root):
    rel = os.path.relpath(real, os.path.realpath(sd_root)).replace(os.sep, "/")
    return "0:/" + ("" if rel == "." else rel)


def scan(real_dir):
    """(files, dirs) of one folder. Files that cannot be read are skipped; nothing is opened."""
    files, dirs = [], []
    try:
        with os.scandir(real_dir) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        dirs.append(e.name)
                    elif e.name.lower().endswith(EXTENSIONS) and e.is_file(follow_symlinks=False):
                        st = e.stat()
                        files.append({"name": e.name, "path": os.path.join(real_dir, e.name), "size": st.st_size, "mtime_ns": st.st_mtime_ns})
                except OSError:
                    continue
    except OSError:
        pass
    return files, sorted(dirs)


def scan_tree(real_dir, max_depth=MAX_DEPTH, max_files=MAX_FILES_PER_SCAN):
    """(files, truncated): the G-code files of `real_dir` and of its sub-folders down to `max_depth` levels. Folders whose name starts with
    a dot are skipped, symbolic links are not followed (scan() never does), the walk stops at `max_files` files (truncated = True)
    and it opens nothing. Folders are visited in name order, so the files that make the cut are the same on every scan."""
    found, pending = [], [(real_dir, 0)]
    while pending:
        folder, depth = pending.pop(0)
        here, subs = scan(folder)
        for f in here:
            if len(found) >= max_files:
                return found, True
            found.append(f)
        if depth < max_depth:
            pending.extend((os.path.join(folder, d), depth + 1) for d in subs if not d.startswith("."))
    return found, False
