"""
health_history -- history of the Pi health in the service database (F3-H of the 2026-10 redesign).

Before this, the Pi health charts were built in each browser from the moment DWC was opened, so a new phone saw them empty. Now
health_poller records one row per cycle in the table `health_samples` of duet.db (cpu, temp, ram, disk, wifi, all in the same
units the page charts: % or degrees C) and the operation health.history returns the series, averaged on the server.

  - the last RECENT_H hours are kept complete; older rows are thinned to one per THIN_S seconds by `maintain()`;
  - rows older than RETENTION_DAYS (setting health.history_days of config.json, default 7) are deleted by `maintain()`,
    called by the database maintenance (db_backup) next to the rest of the purges.
"""
import time

import db
from workshop_api import READ, Arg, Op

SERIES = ("cpu", "temp", "ram", "disk", "wifi")
MIN_GAP_S = 5          # no two rows closer than this
RECENT_H = 2           # complete rows for this long
THIN_S = 30            # one row per this many seconds for the older ones
RETENTION_DAYS = 7
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
MAX_LIMIT = 1000
FMT = "%Y-%m-%dT%H:%M:%S"
_last = [0.0]


def ensure_table(conn):
    """Schema 5 -> 6 (idempotent): the table of samples. Called by db.init_db."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS health_samples (
            ts TEXT PRIMARY KEY,
            cpu REAL, temp REAL, ram REAL, disk REAL, wifi REAL
        );
        """
    )


def set_retention(days):
    global RETENTION_DAYS
    try:
        RETENTION_DAYS = max(1, min(int(days), 90))
    except (TypeError, ValueError):
        pass


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 1) if v == v and abs(v) != float("inf") else None


def record(sample, now=None):
    """Saves one sample {cpu, temp, ram, disk, wifi} (missing or None values stay empty). Returns True if it was saved."""
    now = time.time() if now is None else now
    if now - _last[0] < MIN_GAP_S:
        return False
    values = [_num((sample or {}).get(k)) for k in SERIES]
    if all(v is None for v in values):
        return False
    _last[0] = now
    with db._lock, db._connect() as conn:
        conn.execute("INSERT OR REPLACE INTO health_samples (ts, cpu, temp, ram, disk, wifi) VALUES (?, ?, ?, ?, ?, ?)",
                     (time.strftime(FMT, time.localtime(now)), *values))
    return True


def maintain(now=None):
    """Thins what is older than RECENT_H hours and deletes what is older than the retention. Returns (thinned, deleted)."""
    now = time.time() if now is None else now
    old = time.strftime(FMT, time.localtime(now - RETENTION_DAYS * 86400))
    recent = time.strftime(FMT, time.localtime(now - RECENT_H * 3600))
    with db._lock, db._connect() as conn:
        deleted = conn.execute("DELETE FROM health_samples WHERE ts < ?", (old,)).rowcount
        rows = conn.execute("SELECT ts FROM health_samples WHERE ts < ? ORDER BY ts", (recent,)).fetchall()
        drop, bucket = [], None
        for (ts,) in rows:
            b = int(time.mktime(time.strptime(ts, FMT))) // THIN_S
            if b == bucket:
                drop.append((ts,))
            bucket = b
        conn.executemany("DELETE FROM health_samples WHERE ts = ?", drop)
    return len(drop), deleted


def history(range_name="1h", limit=300, now=None):
    """{range, since, step_s, retention_days, series: {name: [{t: epoch ms, y: value}]}}. The rows of the range are averaged in
    `limit` buckets at most; a bucket without a value for a series gives no point for it."""
    seconds = RANGES.get(range_name) or RANGES["1h"]
    limit = max(10, min(int(limit), MAX_LIMIT))
    now = time.time() if now is None else now
    since = now - seconds
    step = max(1, seconds // limit)
    with db._lock, db._connect() as conn:
        rows = conn.execute("SELECT ts, cpu, temp, ram, disk, wifi FROM health_samples WHERE ts >= ? ORDER BY ts",
                            (time.strftime(FMT, time.localtime(since)),)).fetchall()
    acc = {k: {} for k in SERIES}
    for row in rows:
        t = time.mktime(time.strptime(row[0], FMT))
        b = int((t - since) // step)
        for k, v in zip(SERIES, row[1:]):
            if v is not None:
                s = acc[k].setdefault(b, [0.0, 0, 0.0])
                s[0] += v
                s[1] += 1
                s[2] += t
    series = {k: [{"t": int(s[2] / s[1] * 1000), "y": round(s[0] / s[1], 1)} for _, s in sorted(acc[k].items())] for k in SERIES}
    return {"range": range_name if range_name in RANGES else "1h", "since": time.strftime(FMT, time.localtime(since)), "step_s": step,
            "retention_days": RETENTION_DAYS, "series": series}


def _op(args, ctx):
    return history(args.get("range") or "1h", args.get("limit") or 300)


def ops():
    return [
        Op("health.history", _op, READ,
           {"range": Arg("str", choices=tuple(RANGES), desc="How far back: 1h (default), 6h, 24h or 7d (the retention is 7 days by default)."),
            "limit": Arg("int", min=10, max=MAX_LIMIT, desc="Most points per series (default 300); the samples are averaged in buckets.")},
           "Returns the history of the Pi health kept by the service: series cpu (% use), temp (C), ram (% in use), disk (% in use) and wifi "
           "(% signal, 0 when down), each a list of {t: epoch milliseconds, y: value} averaged in buckets of step_s seconds.", log=False),
    ]
