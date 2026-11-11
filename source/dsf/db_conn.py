"""
SQLite connections of the service database (item 16 of the developer backlog). The file is in WAL mode, so:

- WRITES are serialized by ONE write lock and each one commits before the caller gets control back: a row that was acknowledged
  survives a power cut (nothing is queued in memory). `BEGIN IMMEDIATE` plus a busy timeout and a bounded number of attempts: if
  another process keeps the file locked the caller gets `DatabaseBusy` (clear message) instead of hanging.
- READS take no lock: each one opens its own read-only connection (`PRAGMA query_only`) and works on one consistent snapshot, so
  a long summary never holds back an insert or another read.
- Every connection is closed always (try / finally), also when the body raises.

The path is given on each call (db.py owns `DB_FILE`, which tests and `_check_schema` may change).
"""
import sqlite3
import threading
from contextlib import contextmanager

WRITE_LOCK = threading.Lock()
BUSY_TIMEOUT_S = 5.0  # how long SQLite waits for another process's lock inside one attempt
BUSY_RETRIES = 3  # attempts to start a write transaction (about BUSY_TIMEOUT_S each) before a clear error


class DatabaseBusy(sqlite3.OperationalError):
    """The database stayed locked by another process longer than the bounded wait."""


def connect(path):
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=NORMAL")  # with WAL: safe against power cuts and lighter on the SD
    except BaseException:
        conn.close()
        raise
    return conn


def _is_busy(e):
    text = str(e).lower()
    return "locked" in text or "busy" in text


def _busy_error(path):
    return DatabaseBusy(f"database is locked: gave up after {max(1, BUSY_RETRIES)} attempts of {BUSY_TIMEOUT_S:g} s ({path})")


@contextmanager
def write(path):
    """Write transaction: under the write lock, `BEGIN IMMEDIATE` (bounded attempts on `database is locked`), commit on a normal exit,
    rollback on an exception, connection always closed. When the block ends the rows are confirmed in the file."""
    attempts = max(1, BUSY_RETRIES)
    with WRITE_LOCK:
        try:
            conn = connect(path)
        except sqlite3.OperationalError as e:
            if _is_busy(e):
                raise _busy_error(path) from e
            raise
        try:
            for attempt in range(attempts):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as e:
                    if not _is_busy(e):
                        raise
                    if attempt + 1 >= attempts:
                        raise _busy_error(path) from e
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        finally:
            conn.close()


@contextmanager
def read(path):
    """Read without the write lock: its own connection, `query_only`, one deferred transaction so that all the SELECTs of the block
    see the same snapshot (WAL: a write in the middle does not reach it). Always closed."""
    try:
        conn = connect(path)
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            try:
                yield conn
            finally:
                conn.rollback()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        if _is_busy(e) and not isinstance(e, DatabaseBusy):
            raise _busy_error(path) from e
        raise
