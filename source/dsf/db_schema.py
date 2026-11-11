"""
db_schema -- the schema version check of the database at start (phase 2e, split from db.py).

The database of the real machine holds data that is never lost and never overwritten. At start the file is looked at before
anything is created in it: the same version continues, an older one gets the idempotent creation of db.init_db (as always), and a
NEWER one (written by a later service, then the service went back a version) or an unreadable file is never opened for writing:
it is set aside under a name with the reason and the date (a rename: nothing is deleted or rewritten), and the service starts with
a new empty database. The notice for the person waits in this module until db_backup.launch shows it (Activity + phone).
"""
import os
import shutil
import sqlite3
import time

import service_log

NEW, CURRENT, OLDER, NEWER, UNREADABLE = "new", "current", "older", "newer", "unreadable"
_SQLITE_MAGIC = b"SQLite format 3\x00"
_notices = []  # [(message key, params)]


def schema_status(path, current):
    """(status, user_version) of the database file at `path` against the schema `current`, read without ever writing to it:
    status is "new" (no file or an empty one), "current", "older", "newer" or "unreadable". The file is opened read only."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return NEW, 0
    try:
        with open(path, "rb") as fh:
            head = fh.read(100)
    except OSError:
        return UNREADABLE, None
    if len(head) < 100 or head[:16] != _SQLITE_MAGIC:
        return UNREADABLE, None
    version = int.from_bytes(head[60:64], "big")  # stands if the read only open below cannot be done (locks)
    conn = None
    try:
        uri = "file:" + path.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as e:
        if not (type(e) is sqlite3.OperationalError and "malformed" not in str(e)):
            return UNREADABLE, None
    finally:
        if conn is not None:
            conn.close()
    if version > current:
        return NEWER, version
    return (CURRENT if version == current else OLDER), version


def aside_name(path, label):
    """A name next to `path` with the reason and the date that does not exist yet."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{path}.{label}-{stamp}"
    n = 1
    while os.path.exists(name):
        n += 1
        name = f"{path}.{label}-{stamp}-{n}"
    return name


def set_aside(path, label):
    """Moves the database (and its -wal / -shm) to a name with the reason and the date. A rename; a copy if the rename fails (the
    original is then removed only after the copy is whole). Returns the new name, or None if neither worked (the original stays)."""
    target = aside_name(path, label)
    parts = [""] + [s for s in ("-wal", "-shm") if os.path.exists(path + s)]
    try:
        for s in parts:
            os.rename(path + s, target + s)
        return target
    except OSError:
        pass
    try:
        for s in parts:
            if not os.path.exists(target + s):
                shutil.copy2(path + s, target + s)
        for s in parts:
            os.remove(path + s)
        return target
    except OSError:
        return None


def check(path, current):
    """Runs before the tables are created. Returns the path the service must use: `path`, or, when the file was set aside, `path`
    again (now free for a new database), or a fresh name when the original could not be moved (it stays untouched)."""
    status, version = schema_status(path, current)
    if status not in (NEWER, UNREADABLE):
        return path
    label = f"newer-v{version}" if status == NEWER else "unreadable"
    moved = set_aside(path, label)
    if moved is None:
        path = aside_name(os.path.splitext(path)[0], "fresh") + ".db"
        moved = os.path.basename(path)
        service_log.log(f"database {status}: could not set it aside, using {path} and leaving the original untouched", "db", "error")
    else:
        found = f" (schema {version}, this service is {current})" if status == NEWER else ""
        service_log.log(f"database {status}{found}: set aside as {moved}, starting with a new database", "db", "error")
    _notices.append(("db_set_aside_newer" if status == NEWER else "db_set_aside_unreadable",
                     {"file": os.path.basename(moved), "found": version, "expected": current}))
    return path


def take_notices():
    """[(message key, params)] queued by check for the person (a database set aside); the list is emptied. db_backup.launch shows
    them in Activity and on the phone, the mechanism the other database warnings use."""
    out = list(_notices)
    del _notices[:]
    return out
