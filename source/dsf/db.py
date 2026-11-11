"""
Lightweight SQLite database for WorkshopService -- a single file
(duet.db) next to the rest of the plugin, with no server and no new
dependencies (sqlite3 is stdlib). Three tables: the activity history (jobs
started/finished, power actions, mode changes), the consumption history of
the meters and the log of the commands received through the API.

All dates are stored as ISO text "%Y-%m-%dT%H:%M:%S" (the same format the
rest of the plugin already uses) -- that format sorts lexicographically the
same as chronologically, so the period filters are simple string comparisons
(`WHERE ts >= ?`).

"""
import paths
import calendar
import json
import os
import re
import sqlite3
import time

import audit_chain
import audit_store
import db_conn
import db_schema
from db_dates import FMT_TS, ts_iso  # noqa: F401 -- tolerated dates (db_dates.py)
from db_dates import ts_of as _ts_of, ts_for_save as _ts_for_save  # noqa: F401

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- where the database lives ----
# On the DSF SD (0:/sys/workshop/duet.db), which is not touched when installing plugins; next to the code only when the SD cannot be written.
BASE_OLD = os.path.join(BASE_DIR, "duet.db")
# 2026-10-11: the database file goes in 0:/sys/workshop/: with the new Id the
# service runs under an AppArmor profile and SQLite needs to lock the file
# (permission "k"), which the profile only grants in 0:/sys and in the plugin
# folder. The backups go there too (FOLDER_DATA): the whole workshop in one
# folder (2026-10-11).
BASE_NEW = os.environ.get("WORKSHOP_DB") or paths.WORKSHOP + "/duet.db"
FOLDER_DATA = paths.WORKSHOP
VERSION_SCHEMA = 7  # current schema (PRAGMA user_version); a database is created at this version, never altered from another one
AUDIT_DAYS = 90  # the audit is kept this long; only older rows may be deleted (a trigger refuses the rest)
CONSUMPTION_DETAIL_DAYS = 90  # readings every 30 s; older ones are kept once per hour


def _place():
    """Where the database lives: the file of the SD (0:/sys/workshop), or next to the code when the SD cannot be written (tests on another PC)."""
    folder = os.path.dirname(BASE_NEW)
    try:
        os.makedirs(folder, exist_ok=True)
        trial = os.path.join(folder, ".writable")
        with open(trial, "w") as fh:
            fh.write("ok")
        os.remove(trial)
    except OSError:
        return BASE_OLD  # no DSF SD (tests on another PC)
    return BASE_NEW


DB_FILE = _place()

# Connections (db_conn.py): one write lock, every write confirmed before it returns; reads without it; every connection closed.
_lock = db_conn.WRITE_LOCK  # the write lock (the tests of the table modules take it with _connect)
DatabaseBusy = db_conn.DatabaseBusy


def _connect():
    return db_conn.connect(DB_FILE)


def session():
    """What the table modules (health_history, install_log) use to WRITE: a write transaction (lock, commit, rollback, closed)."""
    return db_conn.write(DB_FILE)


def read_session():
    """The same for reading: no write lock, read-only connection, one snapshot, closed always."""
    return db_conn.read(DB_FILE)


def _check_schema():
    """Before the tables are created: a database of a newer schema or an unreadable one is set aside (db_schema.py) and the service
    starts with a new one; DB_FILE may change only if the original could not be moved."""
    global DB_FILE
    DB_FILE = db_schema.check(DB_FILE, VERSION_SCHEMA)


take_notices = db_schema.take_notices  # the notices of a database set aside, for db_backup.launch


def _rows(rows):
    out = []
    for r in rows:
        d = dict(r)
        if "ts" in d:
            d["ts"] = ts_iso(d["ts"])
        out.append(d)
    return out


TABLES_WITH_DATE = ("activity", "consumption", "commands")
_WELL = ("typeof(ts) = 'text' AND length(ts) = 19 AND "
         "ts GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'")


def init_db():
    """Creates the tables if they do not exist. It must be called only once when the
    plugin starts, before using any other function of this module. A database of a newer schema or an unreadable one is set aside
    first (see _check_schema); an older one gets the idempotent creation below, as it always did."""
    _check_schema()
    with db_conn.write(DB_FILE) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                mode TEXT,
                description TEXT NOT NULL,
                duration_s REAL,
                consumption_kwh REAL,
                detail TEXT,
                message_key TEXT,
                message_params TEXT,
                user TEXT,
                role TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);
            CREATE TABLE IF NOT EXISTS consumption (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                voltage_v REAL,
                current_a REAL,
                power_w REAL,
                energy_kwh REAL,
                meter TEXT NOT NULL DEFAULT 'general'
            );
            CREATE INDEX IF NOT EXISTS idx_consumption_ts ON consumption(ts);
            CREATE INDEX IF NOT EXISTS idx_consumption_meter_ts ON consumption(meter, ts);
            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                name TEXT NOT NULL,
                code TEXT NOT NULL,
                ok INTEGER NOT NULL,
                ms INTEGER,
                response TEXT,
                via TEXT,
                origin TEXT,
                channel TEXT,
                origin_kind TEXT,
                plugin TEXT,
                result TEXT,
                reading INTEGER,
                user TEXT,
                role TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_commands_ts ON commands(ts);
            -- append-only: nobody can change or delete an audit row (not even through SQL of the service); the triggers refuse
            -- every UPDATE and every DELETE of a row younger than AUDIT_DAYS; the maintenance only purges by age
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user TEXT,
                role TEXT,
                device TEXT,
                ip TEXT,
                via TEXT,
                op TEXT NOT NULL,
                args TEXT,
                ok INTEGER NOT NULL,
                code TEXT,
                result TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
            BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
            WHEN OLD.ts >= strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime', '-90 days')
            BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
            """
        )
        import health_history  # here: it imports this module
        health_history.ensure_table(conn)  # schema 6
        import install_log
        install_log.ensure_tables(conn)  # schema 7
        audit_chain.ensure_tables(conn)  # new tables only (CREATE IF NOT EXISTS): the schema version and the tables above are not touched
        conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
    # WAL: reads and writes at the same time and consistent backups with the
    # backup API. journal_mode does not change inside a transaction: separate connection.
    k = sqlite3.connect(DB_FILE, timeout=10, isolation_level=None)
    try:
        k.execute("PRAGMA journal_mode=WAL")
    finally:
        k.close()


# ---- activity ----

def insert_activity(ts, type_name, description, kind=None, duration_s=None, consumption_kwh=None, detail=None, user=None, role=None):
    """`description` is a messages.Msg (the usual case: key + parameters are stored next to its Spanish text) or a plain text
    that is not ours (a line of the firmware, something a user typed): then only the text is stored."""
    import messages
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))[:4000] if detail else None
    key = params = None
    if isinstance(description, messages.Msg):
        key, params = description.key, messages.dumps_params(description)
    with db_conn.write(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO activity (ts, kind, mode, description, duration_s, consumption_kwh, detail, message_key, message_params, user, role) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_ts_for_save(ts), type_name, kind, description.text("es") if key else str(description), duration_s, consumption_kwh, detail, key, params,
             user or None, role or None),
        )


def activity_since(ts_iso, limit=200):
    with db_conn.read(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT ts, kind, mode, description, duration_s, consumption_kwh, message_key, message_params FROM activity "
            "WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            (ts_iso, limit),
        ).fetchall()
    return _rows(rows)


def _detail_json(d):
    try:
        return json.loads(d) if d else None
    except (TypeError, ValueError):
        return None


def activity_query(since_iso, until_iso, type_name=None, limit=50, offset=0, exclude=None, raw_text=None, user=None):
    """Paginated/filterable version of activity_since, for the real table
    of the plugin's UI (dwc-src/WorkshopService.vue) -- unlike the text
    panels of BtnCmd, this scales to any number of events because it only
    fetches one page at a time. Returns (total, rows)."""
    where, args = _activity_where(since_iso, until_iso, type_name, exclude, raw_text, user)
    with db_conn.read(DB_FILE) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM activity WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, ts, kind, mode, description, duration_s, consumption_kwh, detail, message_key, message_params, user, role FROM activity "
            f"WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
    out = _rows(rows)
    for r in out:
        r["detail"] = _detail_json(r.get("detail"))
    return total, out


def activity_summary(since_iso, until_iso, exclude=None, user=None):
    """Counts and totals of the activity of a range, for the summary of the Activity page: events per
    type, jobs started / finished / cancelled, seconds and kWh of the finished jobs, the finished jobs
    themselves (newest first, up to 30), the last failures (error and emergency, up to 8) and the first
    and last event."""
    where, args = _activity_where(since_iso, until_iso, None, exclude, None, user)
    with db_conn.read(DB_FILE) as conn:
        by_kind = {r[0]: r[1] for r in conn.execute(f"SELECT kind, COUNT(*) FROM activity WHERE {where} GROUP BY kind", args).fetchall()}
        cancelled = conn.execute(
            f"SELECT COUNT(*) FROM activity WHERE {where} AND kind = 'job_end' AND (message_key IN ('job_cancelled', 'live_job_end_cancel', 'live_job_end_file_cancelled', 'live_job_end_interrumpido'))",
            args).fetchone()[0]
        sec, kwh = conn.execute(
            f"SELECT COALESCE(SUM(duration_s), 0), COALESCE(SUM(consumption_kwh), 0) FROM activity WHERE {where} AND kind = 'job_end'",
            args).fetchone()
        jobs = conn.execute(
            f"SELECT id, ts, mode, description, duration_s, consumption_kwh, message_key, message_params FROM activity WHERE {where} AND kind = 'job_end' ORDER BY ts DESC LIMIT 30",
            args).fetchall()
        faults = conn.execute(
            f"SELECT id, ts, kind, description, message_key, message_params FROM activity WHERE {where} AND kind IN ('error', 'emergency') ORDER BY ts DESC LIMIT 8",
            args).fetchall()
        first, last, total = conn.execute(f"SELECT MIN(ts), MAX(ts), COUNT(*) FROM activity WHERE {where}", args).fetchone()
    end = by_kind.get("job_end", 0)
    return {
        "total": total, "first": first, "last": last, "per_kind": by_kind,
        "started": by_kind.get("job_start", 0), "finished": max(0, end - cancelled), "cancelled": cancelled,
        "emergencies": by_kind.get("emergency", 0), "errors": by_kind.get("error", 0), "notices": by_kind.get("notice", 0),
        "seconds": round(sec or 0), "kwh": round(kwh or 0, 3),
        "jobs": _rows(jobs), "faults": _rows(faults),
    }


def _activity_where(since_iso, until_iso, type_name=None, exclude=None, raw_text=None, user=None):
    where = "ts >= ? AND ts <= ?"
    args = [since_iso, until_iso]
    if user:
        where += " AND user = ?"
        args.append(user)
    if raw_text:
        # free text: in the description, the type or the detail JSON (case-insensitive for ASCII)
        like = "%" + str(raw_text).replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        where += " AND (description LIKE ? ESCAPE '!' OR kind LIKE ? ESCAPE '!' OR COALESCE(detail, '') LIKE ? ESCAPE '!')"
        args.extend([like, like, like])
    if type_name:
        where += " AND kind = ?"
        args.append(type_name)
    if exclude:
        where += " AND kind NOT IN (" + ",".join("?" * len(exclude)) + ")"
        args.extend(exclude)
    return where, args


def activity_delete(ids):
    """Deletes events by id (Activity page: the Delete button of a row)."""
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    with db_conn.write(DB_FILE) as conn:
        cur = conn.execute("DELETE FROM activity WHERE id IN (" + ",".join("?" * len(ids)) + ")", ids)
        return cur.rowcount


def activity_delete_where(since_iso, until_iso, type_name=None, exclude=None, raw_text=None):
    """Deletes EVERYTHING that matches the filter (Activity page: Delete what is filtered)."""
    where, args = _activity_where(since_iso, until_iso, type_name, exclude, raw_text)
    with db_conn.write(DB_FILE) as conn:
        cur = conn.execute(f"DELETE FROM activity WHERE {where}", args)
        return cur.rowcount


def activity_kinds():
    with db_conn.read(DB_FILE) as conn:
        rows = conn.execute("SELECT DISTINCT kind FROM activity ORDER BY kind").fetchall()
    return [r["kind"] for r in rows]


# ---- consumption ----

def consumption_by_summarize(day_count=CONSUMPTION_DETAIL_DAYS):
    """How many readings older than `days` would disappear when summarizing by hour."""
    limit = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - day_count * 86400))
    with db_conn.read(DB_FILE) as conn:
        total, hours = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT meter || substr(ts, 1, 13)) FROM consumption WHERE ts < ?", (limit,)).fetchone()
    return total - hours


def prune_consumption(day_count=CONSUMPTION_DETAIL_DAYS, before_of=None):
    """Meter readings older than `days`: ONE per meter and hour is left (the
    last one, with the kWh counter of that moment, so the kWh reports per
    day, month and year do not change) with the average power, voltage and
    current of that hour. One reading every 30 s was ~1 million rows per year."""
    limit = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(before_of if before_of else time.time() - day_count * 86400))
    with db_conn.write(DB_FILE) as conn:
        conn.execute("DROP TABLE IF EXISTS temp.horas")
        conn.execute(
            "CREATE TEMP TABLE horas AS SELECT MAX(id) AS id, AVG(power_w) AS p, AVG(voltage_v) AS v, AVG(current_a) AS a, COUNT(*) AS n "
            "FROM consumption WHERE ts < ? GROUP BY meter, substr(ts, 1, 13) HAVING n > 1", (limit,))
        conn.execute(
            "UPDATE consumption SET power_w = (SELECT p FROM horas WHERE horas.id = consumption.id), "
            "voltage_v = (SELECT v FROM horas WHERE horas.id = consumption.id), current_a = (SELECT a FROM horas WHERE horas.id = consumption.id) "
            "WHERE id IN (SELECT id FROM horas)")
        deleted = conn.execute(
            "DELETE FROM consumption WHERE ts < ? AND id NOT IN (SELECT MAX(id) FROM consumption WHERE ts < ? GROUP BY meter, substr(ts, 1, 13))",
            (limit, limit)).rowcount
        conn.execute("DROP TABLE IF EXISTS temp.horas")
    return deleted


def compact(min_mb=1.0):
    """VACUUM if there are more than min_mb of unused space inside. Returns MB freed."""
    with db_conn.read(DB_FILE) as conn:
        idle = conn.execute("PRAGMA freelist_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0] / 1048576
    if idle < min_mb:
        return 0.0
    before = os.path.getsize(DB_FILE)
    with _lock:  # VACUUM is a write: it waits for the writers; the readers (WAL) go on
        conn = sqlite3.connect(DB_FILE, timeout=30, isolation_level=None)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
    return round((before - os.path.getsize(DB_FILE)) / 1048576, 2)


def insert_consumption(ts, voltage_v, current_a, power_w, energy_kwh, meter="general"):
    with db_conn.write(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO consumption (ts, voltage_v, current_a, power_w, energy_kwh, meter) VALUES (?, ?, ?, ?, ?, ?)",
            (_ts_for_save(ts), voltage_v, current_a, power_w, energy_kwh, meter or "general"),
        )


def consumption_since(ts_iso, meter="general"):
    with db_conn.read(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT ts, voltage_v, current_a, power_w, energy_kwh FROM consumption "
            "WHERE meter = ? AND ts >= ? ORDER BY ts ASC",
            (meter, ts_iso),
        ).fetchall()
    return _rows(rows)


def consumption_last(meter="general"):
    with db_conn.read(DB_FILE) as conn:
        row = conn.execute(
            "SELECT ts, voltage_v, current_a, power_w, energy_kwh FROM consumption WHERE meter = ? ORDER BY ts DESC LIMIT 1",
            (meter,),
        ).fetchone()
    return _rows([row])[0] if row else None


def consumption_query(since_iso, until_iso, limit=50, offset=0, meter="general"):
    """Paginated version of the consumption history for the real table of the
    plugin's UI (dwc-src/Consumption.vue) -- the same pattern as
    activity_query, but without a "type" filter (the consumption table has no
    such column). It replaces the sliding-window BtnCmdChart that restarted
    empty on every page load."""
    with db_conn.read(DB_FILE) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM consumption WHERE meter = ? AND ts >= ? AND ts <= ?",
            (meter, since_iso, until_iso),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT ts, voltage_v, current_a, power_w, energy_kwh FROM consumption "
            "WHERE meter = ? AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT ? OFFSET ?",
            (meter, since_iso, until_iso, limit, offset),
        ).fetchall()
    return total, _rows(rows)


def consumption_serial(since_iso, until_iso, max_points=2000, meter="general"):
    """Series (ts, power_w, voltage_v, current_a) in chronological order for
    the trend charts of dwc-src/Consumption.vue (power, voltage and current share
    the same range/sampling, so a single query is enough for the three) --
    unlike consumption_query (paginated for the table), this always covers the
    WHOLE range. Up to max_points rows come as they were read. With more, the
    rows are averaged in equal time buckets (not trimmed: keeping only the most
    recent ones showed 16 hours of a 30-day range). Returns (rows, step_s):
    step_s is the width of a bucket in seconds, 0 when the rows are the raw
    readings; the chart uses it to tell a real gap (no readings) from two
    neighbour buckets."""
    return _serial(
        "SELECT ts, power_w, voltage_v, current_a FROM consumption WHERE meter = ? AND ts >= ? AND ts <= ?",
        [meter, since_iso, until_iso], max_points)


def _serial(source_sql, params, max_points):
    """source_sql: SELECT of ts, power_w, voltage_v, current_a (one row per ts) with ? marks for params."""
    max_points = max(2, int(max_points))
    with db_conn.read(DB_FILE) as conn:
        n, first, last = conn.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM (" + source_sql + ")", params).fetchone()
        if n <= max_points:
            rows = conn.execute("SELECT * FROM (" + source_sql + ") ORDER BY ts ASC", params).fetchall()
            return _rows(rows), 0
        span_s = max(1, _epoch_s(last) - _epoch_s(first))
        step_s = max(1, -(-span_s // (max_points - 1)))  # ceil: at most max_points buckets
        rows = conn.execute(
            "SELECT MIN(ts) AS ts, AVG(power_w) AS power_w, AVG(voltage_v) AS voltage_v, AVG(current_a) AS current_a "
            "FROM (" + source_sql + ") GROUP BY CAST(strftime('%s', ts) AS INTEGER) / ? ORDER BY ts ASC",
            params + [step_s],
        ).fetchall()
    out = _rows(rows)
    for r in out:
        for k, nd in (("power_w", 1), ("voltage_v", 1), ("current_a", 3)):
            if r[k] is not None:
                r[k] = round(r[k], nd)
    return out, step_s


def _epoch_s(ts_iso):
    """Seconds of an ISO text as sqlite reads it (strftime('%s')): the same scale of the buckets."""
    return calendar.timegm(time.strptime(ts_iso[:19], FMT_TS)) if ts_iso else 0


# ---- robust kWh (2026-10-10: "in the year view no data or costs show") ----
# The meter's counter (dp 1) sometimes arrives as 0 for ONE reading (2.6 -> 0 ->
# 2.6) and sometimes really resets (3.83 -> 0, 0.01, 0.02...). Subtracting
# "last - first" gave negative -> 0 in month and year. Now only the increases
# between accepted readings are added: a drop that is not confirmed in the
# next reading is discarded (read failure); if it is confirmed, it is a reset
# and it continues from the new value (without counting the jump).
LOW_KWH = 0.02  # a small drop is rounding noise


def _sum_increases(rows, bucket_of):
    """rows: [(ts, energy)] sorted. bucket_of(ts) -> index or None.
    Returns {index: kwh} and the indices that had readings."""
    out = {}
    seen = set()
    ref = None  # ultimo valor aceptado
    pending = None  # (ts, value) of a drop not yet confirmed
    for ts, e in rows:
        if e is None:
            continue
        i = bucket_of(ts)
        if i is not None:
            seen.add(i)
        if ref is None:
            ref = e
            continue
        if e < ref - LOW_KWH:
            if pending is None:
                pending = (ts, e)
                continue
            # segunda lectura baja seguida: reinicio real -> seguir desde aca
            ref = e
            pending = None
            continue
        pending = None
        if e > ref:
            if i is not None:
                out[i] = out.get(i, 0.0) + (e - ref)
            ref = e
    return out, seen


def consumption_kwh_buckets(limits_iso, meter="general"):
    """kWh of each bucket [limits[i], limits[i+1]) adding increases (see
    above). None in the buckets without any reading."""
    if len(limits_iso) < 2:
        return []
    with db_conn.read(DB_FILE) as conn:
        prev = conn.execute("SELECT MAX(ts) FROM consumption WHERE meter = ? AND ts < ?", (meter, limits_iso[0])).fetchone()[0]
        rows = conn.execute(
            "SELECT ts, energy_kwh FROM consumption WHERE meter = ? AND ts >= ? AND ts < ? ORDER BY ts ASC",
            (meter, prev or limits_iso[0], limits_iso[-1]),
        ).fetchall()
    import bisect

    def bucket_of(ts):
        if ts < limits_iso[0]:
            return None
        k = bisect.bisect_right(limits_iso, ts) - 1
        return k if 0 <= k < len(limits_iso) - 1 else None

    sums, seen = _sum_increases([(r["ts"], r["energy_kwh"]) for r in rows], bucket_of)
    return [round(sums.get(i, 0.0), 4) if i in seen else None for i in range(len(limits_iso) - 1)]


def consumption_serial_total(since_iso, until_iso, keys, max_points=2000):
    """Summed power of several meters (the ones on their own line) at each
    reading: the poller uses the same ts for all of them in a round.
    Same answer as consumption_serial: (rows, step_s)."""
    if not keys:
        return [], 0
    marks = ",".join("?" for _ in keys)
    return _serial(
        "SELECT ts, SUM(power_w) AS power_w, AVG(voltage_v) AS voltage_v, SUM(current_a) AS current_a FROM consumption "
        "WHERE meter IN (" + marks + ") AND ts >= ? AND ts <= ? GROUP BY ts",
        list(keys) + [since_iso, until_iso], max_points)


def _energy_at_or_before(conn, ts_iso, meter="general"):
    """Last energy_kwh value with ts <= ts_iso (snapshot of the meter's
    accumulated counter at that instant), or None if there are no readings up
    to that point. Used by consumption_period to telescope the "buckets"
    (hours/days/months) by the difference of consecutive snapshots instead of
    adding deltas row by row -- so the bucket in progress (e.g. the current
    hour) always reflects what has accumulated up to "now" with no special
    cases, just as consumption_span_summary does with the whole range
    (last - first)."""
    row = conn.execute(
        "SELECT energy_kwh FROM consumption WHERE meter = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
        (meter, ts_iso),
    ).fetchone()
    return row["energy_kwh"] if row else None


def consumption_period(boundaries_iso, meter="general"):
    """Snapshot of energy_kwh at each limit of "boundaries_iso" (ascending list
    of ISO timestamps, len = number of buckets + 1), for the Tuya-style bar
    chart of dwc-src/Consumption.vue. The consumption of bucket i is computed by
    consumo_periodo.py as snapshots[i+1] - snapshots[i]."""
    with db_conn.read(DB_FILE) as conn:
        return [_energy_at_or_before(conn, ts, meter) for ts in boundaries_iso]


def consumption_span_summary(since_iso, until_iso, meter="general"):
    """Summary (kWh consumed, peak, average) of the WHOLE range -- not just the
    visible page -- subtracting energy_kwh between the first and last row of the
    range (like consumption_period.py) plus MAX/AVG of power_w via SQL, without
    bringing all the rows of the range into the process."""
    with db_conn.read(DB_FILE) as conn:
        first = conn.execute(
            "SELECT energy_kwh FROM consumption WHERE meter = ? AND ts >= ? AND ts <= ? ORDER BY ts ASC LIMIT 1",
            (meter, since_iso, until_iso),
        ).fetchone()
        last = conn.execute(
            "SELECT energy_kwh FROM consumption WHERE meter = ? AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (meter, since_iso, until_iso),
        ).fetchone()
        agg = conn.execute(
            "SELECT MAX(power_w), AVG(power_w), COUNT(*) FROM consumption WHERE meter = ? AND ts >= ? AND ts <= ?",
            (meter, since_iso, until_iso),
        ).fetchone()
    if first is None or last is None:
        return None
    peak, average, samples = agg
    kwh = consumption_kwh_buckets([since_iso, until_iso + "~"], meter)[0]  # "~" > cualquier hora: incluye hasta_iso
    return {
        "consumption_kwh": kwh if kwh is not None else 0.0,
        "peak_w": peak or 0.0,
        "average_w": average or 0.0,
        "samples": samples or 0,
    }


# ---- History of the received API calls (WorkshopService, WorkshopRS485), Services page ----
# 2026-10-09. They are stored already MASKED (see api_ops.record). COMMANDS_DAYS
# days are kept and at most COMMANDS_MAX rows. Reads (the pages ask often)
# only READINGS_DAYS, so they do not push out the commands that change
# something.
COMMANDS_DAYS = 30
READINGS_DAYS = 1
COMMANDS_MAX = 20000
_commands_inserted = [0]


def command_insert(ts, label, code, ok, ms, response, via="", reading=False, origin=None, user=None, role=None):
    """origin: dict from origen.describe_api (optional; saved in the same row)."""
    o = origin if isinstance(origin, dict) else {}
    with db_conn.write(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO commands (ts, name, code, ok, ms, response, via, reading, origin, channel, origin_kind, plugin, result, user, role) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_ts_for_save(ts), label, code, 1 if ok else 0, ms, response, via or "", 1 if reading else 0,
             json.dumps(o, ensure_ascii=False, separators=(",", ":")) if o else None,
             o.get("channel"), o.get("kind"), o.get("plugin"), o.get("result"), user or None, role or None),
        )
        _commands_inserted[0] += 1
        if _commands_inserted[0] % 200 == 1:
            import time as _t
            limit = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(_t.time() - COMMANDS_DAYS * 86400))
            conn.execute("DELETE FROM commands WHERE ts < ?", (limit,))
            limit_l = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(_t.time() - READINGS_DAYS * 86400))
            conn.execute("DELETE FROM commands WHERE reading = 1 AND ts < ?", (limit_l,))
            conn.execute(
                "DELETE FROM commands WHERE id <= (SELECT id FROM commands ORDER BY id DESC LIMIT 1 OFFSET ?)",
                (COMMANDS_MAX,),
            )


def commands_query(since_iso, until_iso, label=None, only_errors=False, raw_text=None, limit=50, offset=0, type_name=0, via=None,
                   channel=None, kind=None, plugin=None, result=None):
    """type: 0 all, 1 only those that change something, 2 only reads.
    channel / kind / plugin / result filter by origin ("-" = rows without data)."""
    where = "ts >= ? AND ts <= ?"
    args = [since_iso, until_iso]
    for col, val in (("channel", channel), ("origin_kind", kind), ("plugin", plugin), ("result", result)):
        if val:
            if val == "-":
                where += f" AND COALESCE({col}, '') = ''"
            else:
                where += f" AND {col} = ?"
                args.append(val)
    if type_name == 1:
        where += " AND COALESCE(reading, 0) = 0"
    elif type_name == 2:
        where += " AND reading = 1"
    if via:
        where += " AND via = ?"
        args.append(via)
    if label:
        where += " AND name = ?"
        args.append(label)
    if only_errors:
        where += " AND ok = 0"
    if raw_text:
        where += " AND (code LIKE ? OR response LIKE ?)"
        args += [f"%{raw_text}%", f"%{raw_text}%"]
    with db_conn.read(DB_FILE) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM commands WHERE {where}", args).fetchone()[0]
        errors = conn.execute(f"SELECT COUNT(*) FROM commands WHERE {where} AND ok = 0", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, ts, name, code, ok, ms, response, via, reading, origin, user, role FROM commands WHERE {where} "
            f"ORDER BY id DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
        names = [r[0] for r in conn.execute(
            "SELECT name FROM commands WHERE ts >= ? AND ts <= ? GROUP BY name ORDER BY COUNT(*) DESC",
            (since_iso, until_iso),
        ).fetchall()]
        # summary of the range (without the type/name filters): for the numbers above
        res = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN reading = 1 THEN 1 ELSE 0 END), SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END), "
            "CAST(AVG(ms) AS INTEGER), MAX(ms) FROM commands WHERE ts >= ? AND ts <= ?",
            (since_iso, until_iso),
        ).fetchone()
        ways = [r[0] for r in conn.execute(
            "SELECT via FROM commands WHERE ts >= ? AND ts <= ? AND via != '' GROUP BY via ORDER BY COUNT(*) DESC",
            (since_iso, until_iso),
        ).fetchall()]
    summary = {"all": res[0] or 0, "readings": res[1] or 0, "errors": res[2] or 0, "ms_avg": res[3], "ms_max": res[4], "ways": ways}
    # values available for the origin filters (whole range, ignoring the other filters)
    for key, col in (("channels", "channel"), ("kinds", "origin_kind"), ("plugins", "plugin"), ("results", "result")):
        with db_conn.read(DB_FILE) as conn:
            summary[key] = [r[0] for r in conn.execute(
                f"SELECT {col} FROM commands WHERE ts >= ? AND ts <= ? AND COALESCE({col}, '') != '' "
                f"GROUP BY {col} ORDER BY COUNT(*) DESC", (since_iso, until_iso)).fetchall()]
    out = _rows(rows)
    for d in out:
        d["origin"] = _origin_dict(d.get("origin"))
    return total, errors, out, names, summary


def _origin_dict(raw):
    """The saved origin JSON as a dict ({} for old rows without data)."""
    try:
        v = json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def commands_delete(since_iso, until_iso):
    with db_conn.write(DB_FILE) as conn:
        return conn.execute("DELETE FROM commands WHERE ts >= ? AND ts <= ?", (since_iso, until_iso)).rowcount


def commands_last(n):
    """The n most recent, to fill in 'Last received commands' of Services at
    startup (they used to be lost on every restart)."""
    with db_conn.read(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT ts, code, ok, ms, response, via, origin FROM commands ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [{"hour": ts_iso(r["ts"])[11:19], "date": ts_iso(r["ts"])[:10], "code": r["code"][:160], "ok": bool(r["ok"]),
             "response": (r["response"] or "")[:300], "ms": r["ms"], "via": r["via"] or "",
             "origin": _origin_dict(r["origin"])} for r in rows]


# ---- audit (append-only, 2026-10-21) ----
# Who did what: user, role, device (random id of the browser), address, operation, arguments without secrets and result.
# There is no function to delete or change a row except audit_purge (by age, maintenance); the triggers of init_db back it up.
# Phase 4: every row gets its link of the verification chain in the same transaction (audit_chain.py); the queries are in audit_store.py.
AUDIT_MAX_PAGE = audit_store.MAX_PAGE
audit_store.path_of = lambda: DB_FILE
_audit_inserted = [0]


def audit_insert(ts, user, role, device, ip, via, op, args, ok, code, result, detail=None):
    with db_conn.write(DB_FILE) as conn:
        audit_chain.insert(conn, _ts_for_save(ts), user, role, device, ip, via, op, args, ok, code, result, detail)
        _audit_inserted[0] += 1
        if _audit_inserted[0] % 500 == 1:
            audit_chain.purge(conn, audit_chain.limit_ts(AUDIT_DAYS))


def audit_purge():
    """Maintenance: deletes the rows older than AUDIT_DAYS (the triggers refuse anything younger) and leaves the cut points of the chain."""
    with db_conn.write(DB_FILE) as conn:
        return audit_chain.purge(conn, audit_chain.limit_ts(AUDIT_DAYS))


def audit_query(since_iso, until_iso, user=None, op=None, only_errors=False, limit=50, offset=0, **filters):
    return audit_store.query_rows(DB_FILE, since_iso, until_iso, user, op, only_errors, limit, offset, **filters)


# ---- Database state (Pi Health page, 2026-10-10: "I want a state of the
# database that is created; only shown if the database was created") ----
_TS_OF = {"activity": "ts", "consumption": "ts", "commands": "ts", "audit": "ts", "health_samples": "ts"}


def state_base():
    """None if the database does not exist yet. If it exists: file, sizes, rows
    per table with the oldest and newest date, backups and a quick check."""
    if not os.path.exists(DB_FILE):
        return None
    import glob
    import time as _t

    out = {
        "file": DB_FILE,
        "mb": round(os.path.getsize(DB_FILE) / 1048576, 2),
        "wal_mb": round(os.path.getsize(DB_FILE + "-wal") / 1048576, 2) if os.path.exists(DB_FILE + "-wal") else 0,
        "modified": _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(os.path.getmtime(DB_FILE))),
        "tables": [],
        "backups": [],
        "location": "sd" if DB_FILE == BASE_NEW else "plugin",
        "version_schema": None,
        "consumption_detail_days": CONSUMPTION_DETAIL_DAYS,
    }
    with db_conn.read(DB_FILE) as conn:
        for (label,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            row = {"name": label, "rows": conn.execute(f'SELECT COUNT(*) FROM "{label}"').fetchone()[0]}
            col = _TS_OF.get(label)
            if col and row["rows"]:
                # only well-formed dates; the others are counted separately (2026-10-10:
                # a consumption row had its date with leading null bytes)
                well = _WELL.replace("ts", col)
                r = conn.execute(f'SELECT MIN({col}), MAX({col}) FROM "{label}" WHERE {well}').fetchone()
                row["since"], row["until"] = r[0], r[1]
                row["date_odd"] = conn.execute(f'SELECT COUNT(*) FROM "{label}" WHERE NOT ({well})').fetchone()[0]
            out["tables"].append(row)
        out["check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
        out["version_schema"] = conn.execute("PRAGMA user_version").fetchone()[0]
        out["mode_daily"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
        out["page_kb"] = round(conn.execute("PRAGMA page_size").fetchone()[0] / 1024, 1)
        out["free_mb"] = round(conn.execute("PRAGMA freelist_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0] / 1048576, 2)
    for f in sorted(glob.glob(DB_FILE + ".bak*") + glob.glob(BASE_OLD + ".bak*") + glob.glob(BASE_OLD + ".migrada-*")):
        out["backups"].append({"file": os.path.basename(f), "mb": round(os.path.getsize(f) / 1048576, 2),
                                 "date": _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(os.path.getmtime(f)))})
    # respaldos automaticos (db_backup.py): activo, ultimo, carpeta, lista
    try:
        import db_backup
        out["backup"] = db_backup.status()
    except Exception as e:
        out["backup"] = {"active": False, "error": str(e)}
    return out
