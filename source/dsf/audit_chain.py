"""
audit_chain -- the verification chain of the activity record (phase 4 of informes/control-acceso/PLAN-ACCESO.md, section 4.3).

Every row of the table `audit` gets a link in the table `audit_chain`, written in the SAME transaction (db_conn.write): there is never an
audit row without its link nor a link without its row. A link holds the hash of the row together with the hash of the previous link:

    hash = SHA-256( prev_hash + "\\n" + canonical(row) )          canonical = JSON array of the id and the stored columns of the audit row,
                                                                  plus the text of its `audit_detail` row ("" when it has none)

THE CHAIN IS ONE AND ORDERED (by audit id). The first link uses the fixed seed SEED as its prev_hash. A row of `audit` that is OLDER than the chain
(the history that existed when this version was first started: its id is smaller than the id of the first element of the chain) stays OUTSIDE the
chain and `verify` does not look at it: the chain starts at its first link. Nothing about the table `audit` itself was changed (no column, no
user_version): this module only creates NEW tables, with CREATE TABLE IF NOT EXISTS, which a service of an earlier version simply ignores. A row
that an earlier service writes after a downgrade has no link: `verify` names it as a row without a link (the honest answer).

Tables (all new):
    audit_chain(audit_id PK, kind 'link'|'cut', ts, prev_hash, hash)   no UPDATE, no DELETE of an element younger than the retention (triggers)
    audit_detail(audit_id PK, target, decision, detail JSON)           the data of an event that the old columns do not hold (no secrets)
    audit_alarm_state(name PK, state, ts)                               debounce of the alarms of audit_alarms.py, survives a restart

THE PURGE by age (db.AUDIT_DAYS, the maintenance; there is no API operation for it) keeps what is left verifiable: each run of old consecutive
elements is replaced by ONE element of kind 'cut' with audit_id = the last purged id, prev_hash = the prev_hash of the first purged link and
hash = the hash of the last purged link ("cut point"). The next link still chains to that hash, and a cut chains to the element before it, so
the continuity is still checked; the content of what was purged is of course no longer there to check.

Standard library only; the connection or the path is given on each call (layer L1).
"""
import hashlib
import json
import time

import clock
import db_conn

SEED = hashlib.sha256(b"workshop-audit-chain-v1").hexdigest()  # prev_hash of the first link ever; fixed, so that anybody can recompute the chain
DETAIL_MAX = 1800
VERIFY_MAX_ROWS = 5000  # most links one verify call looks at (the Pi must not be blocked by a long chain)
DENIED_CODES = ("forbidden", "login_required")

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_chain (
    audit_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('link', 'cut')),
    ts TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_chain_ts ON audit_chain(ts);
CREATE TRIGGER IF NOT EXISTS audit_chain_no_update BEFORE UPDATE ON audit_chain
BEGIN SELECT RAISE(ABORT, 'audit chain is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_chain_no_delete BEFORE DELETE ON audit_chain
WHEN OLD.ts >= strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime', '-90 days')
BEGIN SELECT RAISE(ABORT, 'audit chain is append-only'); END;
CREATE TABLE IF NOT EXISTS audit_detail (
    audit_id INTEGER PRIMARY KEY,
    target TEXT,
    decision TEXT,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_detail_target ON audit_detail(target);
CREATE TRIGGER IF NOT EXISTS audit_detail_no_update BEFORE UPDATE ON audit_detail
BEGIN SELECT RAISE(ABORT, 'audit detail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_detail_no_delete BEFORE DELETE ON audit_detail
WHEN EXISTS (SELECT 1 FROM audit WHERE id = OLD.audit_id)
BEGIN SELECT RAISE(ABORT, 'audit detail is append-only'); END;
CREATE TABLE IF NOT EXISTS audit_alarm_state (
    name TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    ts INTEGER NOT NULL
);
"""

AUDIT_COLUMNS = "id, ts, user, role, device, ip, via, op, args, ok, code, result"


def ensure_tables(conn):
    """The new tables and their triggers (idempotent). Called by db.init_db inside its transaction."""
    conn.executescript(SCHEMA)


def canonical(values, detail_text):
    """The text that is hashed for a row: `values` = the stored columns of the audit row in AUDIT_COLUMNS order."""
    return json.dumps([*values, detail_text or ""], ensure_ascii=False, separators=(",", ":"))


def link_hash(prev_hash, canon):
    return hashlib.sha256((prev_hash + "\n" + canon).encode("utf-8")).hexdigest()


def tail(conn):
    """The hash the next link chains to: the one of the last element, or SEED."""
    r = conn.execute("SELECT hash FROM audit_chain ORDER BY audit_id DESC LIMIT 1").fetchone()
    return r[0] if r else SEED


def _clip(v, n):
    return (v or "")[:n]


def _write_link(conn, aid, ts, values, detail_text):
    prev = tail(conn)
    conn.execute("INSERT INTO audit_chain (audit_id, kind, ts, prev_hash, hash) VALUES (?, 'link', ?, ?, ?)",
                 (aid, ts, prev, link_hash(prev, canonical(values, detail_text))))


def insert(conn, ts, user, role, device, ip, via, op, args, ok, code, result, detail=None):
    """Inside an open write transaction: the audit row, its detail (when there is one) and its link. `ts` is already in the stored form.
    Returns the id of the audit row."""
    row = (ts, user or "", role or "", device or "", ip or "", via or "", op, _clip(args, 600), 1 if ok else 0, code or "", _clip(result, 300))
    aid = conn.execute("INSERT INTO audit (ts, user, role, device, ip, via, op, args, ok, code, result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       row).lastrowid
    detail_text = ""
    if detail:
        detail_text = json.dumps(detail, ensure_ascii=False, separators=(",", ":"), sort_keys=True)[:DETAIL_MAX]
        conn.execute("INSERT INTO audit_detail (audit_id, target, decision, detail) VALUES (?, ?, ?, ?)",
                     (aid, _clip(str(detail.get("target") or ""), 140) or None, _clip(str(detail.get("decision") or ""), 12) or None, detail_text))
    _write_link(conn, aid, ts, (aid, *row), detail_text)
    return aid


def limit_ts(days):
    """The date before which a row is old (the same form as the stored ones), by the clock of the service."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(clock.wall() - days * 86400))


def purge(conn, limit):
    """Inside an open write transaction: deletes the audit rows older than `limit` (the triggers refuse the younger ones) and leaves a cut point
    for each run of old chained rows. Returns how many audit rows were deleted."""
    first = conn.execute("SELECT MIN(audit_id) FROM audit_chain").fetchone()[0]
    if first is None:
        return conn.execute("DELETE FROM audit WHERE ts < ?", (limit,)).rowcount
    deleted = conn.execute("DELETE FROM audit WHERE id < ? AND ts < ?", (first, limit)).rowcount  # the history older than the chain
    top = conn.execute("SELECT MAX(audit_id) FROM audit_chain WHERE ts < ?", (limit,)).fetchone()[0]
    if top is None:
        return deleted
    run = []
    for e in conn.execute("SELECT audit_id, kind, ts, prev_hash, hash FROM audit_chain WHERE audit_id <= ? ORDER BY audit_id", (top,)).fetchall():
        if e[2] < limit:
            run.append(tuple(e))
        else:
            deleted += _cut(conn, run)
            run = []
    return deleted + _cut(conn, run)


def _cut(conn, run):
    if not run or (len(run) == 1 and run[0][1] == "cut"):
        return 0
    links = [(e[0],) for e in run if e[1] == "link"]
    ids = [(e[0],) for e in run]
    n = 0
    for (i,) in links:
        n += conn.execute("DELETE FROM audit WHERE id = ?", (i,)).rowcount
    conn.executemany("DELETE FROM audit_detail WHERE audit_id = ?", links)
    conn.executemany("DELETE FROM audit_chain WHERE audit_id = ?", ids)
    last = run[-1]
    conn.execute("INSERT INTO audit_chain (audit_id, kind, ts, prev_hash, hash) VALUES (?, 'cut', ?, ?, ?)", (last[0], last[2], run[0][3], last[4]))
    return n


def verify(path, after=0, limit=2000):
    """Walks the chain from the element after `after` (0 = from the start) over at most `limit` elements.
    {"ok", "broken": None | {"audit_id", "reason"}, "checked", "done", "next_after", "links", "cuts", "pre_chain_rows"}: when `done` is False call
    again with after = next_after. Reasons: chain_break (prev_hash is not the hash of the element before: an element was deleted or changed),
    hash_mismatch (the row or its detail or the hash was changed), missing_row (a link whose audit row is gone), missing_link (an audit row that
    belongs to the chain but has no link). It reads on its own connection and holds no lock."""
    limit = max(1, min(int(limit or 2000), VERIFY_MAX_ROWS))
    after = max(int(after or 0), 0)
    with db_conn.read(path) as conn:
        first = conn.execute("SELECT MIN(audit_id) FROM audit_chain").fetchone()[0]
        if first is None:
            return _answer(conn, None, 0, True, after, None)
        expected = SEED
        if after:
            r = conn.execute("SELECT hash FROM audit_chain WHERE audit_id = ?", (after,)).fetchone()
            expected = r[0] if r else None  # the element was purged meanwhile: the first one of the page is not compared with it
        elems = conn.execute("SELECT audit_id, kind, ts, prev_hash, hash FROM audit_chain WHERE audit_id > ? ORDER BY audit_id LIMIT ?",
                             (after, limit + 1)).fetchall()
        more = len(elems) > limit
        page = elems[:limit]
        bad = None
        if page:
            rows = _rows(conn, page[0][0], page[-1][0])
            for e in page:
                reason = _check(e, expected, rows)
                if reason:
                    bad = (e[0], reason)
                    break
                expected = e[4]
        hi = page[-1][0] if (more and page) else None
        orphan = conn.execute("SELECT a.id FROM audit a LEFT JOIN audit_chain c ON c.audit_id = a.id WHERE a.id > ? AND a.id > ? AND c.audit_id IS NULL"
                              + (" AND a.id <= ?" if hi is not None else "") + " ORDER BY a.id LIMIT 1",
                              (after, first) + ((hi,) if hi is not None else ())).fetchone()
        if orphan and (bad is None or orphan[0] < bad[0]):
            bad = (orphan[0], "missing_link")
        done = bad is not None or not more
        return _answer(conn, bad, len(page), done, page[-1][0] if page else after, first)


def _rows(conn, lo, hi):
    out = {}
    for r in conn.execute("SELECT a.id, a.ts, a.user, a.role, a.device, a.ip, a.via, a.op, a.args, a.ok, a.code, a.result, d.detail "
                          "FROM audit a LEFT JOIN audit_detail d ON d.audit_id = a.id WHERE a.id BETWEEN ? AND ?", (lo, hi)):
        out[r[0]] = (tuple(r[:12]), r[12] or "")
    return out


def _check(e, expected, rows):
    aid, kind, _ts, prev, h = e
    if expected is not None and prev != expected:
        return "chain_break"
    if kind == "cut":
        return None
    got = rows.get(aid)
    if got is None:
        return "missing_row"
    return None if link_hash(prev, canonical(*got)) == h else "hash_mismatch"


def _answer(conn, bad, checked, done, next_after, first):
    out = {"ok": bad is None, "broken": {"audit_id": bad[0], "reason": bad[1]} if bad else None, "checked": checked, "done": done,
           "next_after": next_after}
    if done and first is not None:
        out["links"] = conn.execute("SELECT COUNT(*) FROM audit_chain WHERE kind = 'link'").fetchone()[0]
        out["cuts"] = conn.execute("SELECT COUNT(*) FROM audit_chain WHERE kind = 'cut'").fetchone()[0]
        out["pre_chain_rows"] = conn.execute("SELECT COUNT(*) FROM audit WHERE id < ?", (first,)).fetchone()[0]
    elif done:
        out.update(links=0, cuts=0, pre_chain_rows=conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0])
    return out
