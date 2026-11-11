"""
audit_store -- reading the audit: the page query with its filters and the JSONL export (phase 4, split from db.py).

`query` with none of the new filters runs exactly the SQL it always ran (same rows, same keys, same order, same totals): the new filters only
add conditions. The target and the decision of an event live in `audit_detail` (audit_chain.py); an old row has none, so a filter on them
never matches it, while the result filter works from the columns every row has. The paths are given on each call (db.py owns DB_FILE).
"""
import json

import audit_chain
import db_conn
from db_dates import ts_iso

MAX_PAGE = 200
EXPORT_MAX_ROWS = 2000
RESULTS = ("allowed", "denied", "error")
_DENIED = ",".join("'%s'" % c for c in audit_chain.DENIED_CODES)
path_of = None  # () -> the database file now; db.py sets it (the operations of audit_ops cannot import db: import cycle)
_COLS = "id, ts, user, role, device, ip, via, op, args, ok, code, result"


def _result_sql(result):
    if result == "allowed":
        return "ok = 1"
    if result == "denied":
        return "ok = 0 AND code IN (%s)" % _DENIED
    return "ok = 0 AND COALESCE(code, '') NOT IN (%s)" % _DENIED  # error


def _where(since, until, user, op, only_errors, users, target, result, only_denied):
    where, args = "ts >= ? AND ts <= ?", [since, until]
    if user:
        where += " AND user = ?"
        args.append(user)
    if users is not None:  # the members of a group
        users = list(users)
        where += " AND user IN (%s)" % ",".join("?" * len(users)) if users else " AND 0"
        args.extend(users)
    if op:
        where += " AND op LIKE ?"
        args.append(op.replace("%", "") + "%")
    if only_errors:
        where += " AND ok = 0"
    if only_denied:
        where += " AND " + _result_sql("denied")
    if result:
        where += " AND " + _result_sql(result)
    if target:
        where += " AND id IN (SELECT audit_id FROM audit_detail WHERE target = ?)"
        args.append(target)
    return where, args


def query(path, since, until, user=None, op=None, only_errors=False, limit=50, offset=0, users=None, target=None, result=None, only_denied=False,
          with_detail=False):
    """(total, rows as dicts of sqlite rows, people of the range). `users`: list of names (the members of a group), None = no filter."""
    where, args = _where(since, until, user, op, only_errors, users, target, result, only_denied)
    limit = max(1, min(int(limit), MAX_PAGE))
    with db_conn.read(path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM audit WHERE {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT {_COLS} FROM audit WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", args + [limit, max(int(offset), 0)]).fetchall()
        who = [r[0] for r in conn.execute("SELECT user FROM audit WHERE ts >= ? AND ts <= ? AND user != '' GROUP BY user ORDER BY COUNT(*) DESC",
                                          (since, until)).fetchall()]
        details = {}
        if with_detail and rows:
            ids = [r[0] for r in rows]
            for r in conn.execute("SELECT audit_id, detail FROM audit_detail WHERE audit_id IN (%s)" % ",".join("?" * len(ids)), ids):
                details[r[0]] = json.loads(r[1])
    if with_detail:
        rows = [dict(dict(r), detail=details.get(r["id"])) for r in rows]
    return total, rows, who


def query_rows(*a, **kw):
    """query() with the dates of the rows in the form the pages read (what db.audit_query answers)."""
    total, rows, who = query(*a, **kw)
    out = []
    for r in rows:
        d = dict(r)
        d["ts"] = ts_iso(d["ts"])
        out.append(d)
    return total, out, who


def export_page(path, since, until, after=0, limit=1000):
    """One page of the export: {"jsonl", "rows", "chained", "done", "next_after"}. Each line is a JSON object with the columns of the row, its
    detail (or null) and the `prev_hash` / `hash` of its link (null for a row older than the chain). Rows go in id order from the id after
    `after`; at most `limit` (never more than EXPORT_MAX_ROWS); call again with next_after until done."""
    limit = max(1, min(int(limit or 1000), EXPORT_MAX_ROWS))
    with db_conn.read(path) as conn:
        found = conn.execute(
            "SELECT a.id, a.ts, a.user, a.role, a.device, a.ip, a.via, a.op, a.args, a.ok, a.code, a.result, d.detail, c.prev_hash, c.hash "
            "FROM audit a LEFT JOIN audit_detail d ON d.audit_id = a.id LEFT JOIN audit_chain c ON c.audit_id = a.id AND c.kind = 'link' "
            "WHERE a.id > ? AND a.ts >= ? AND a.ts <= ? ORDER BY a.id LIMIT ?", (max(int(after or 0), 0), since, until, limit + 1)).fetchall()
    more = len(found) > limit
    lines, chained = [], 0
    keys = _COLS.split(", ")
    for r in found[:limit]:
        d = dict(zip(keys, r[:12]))
        d["detail"] = json.loads(r[12]) if r[12] else None
        d["prev_hash"], d["hash"] = r[13], r[14]
        chained += 1 if r[14] else 0
        lines.append(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    last = found[min(limit, len(found)) - 1][0] if found else max(int(after or 0), 0)
    return {"jsonl": "".join(x + "\n" for x in lines), "rows": len(lines), "chained": chained, "done": not more, "next_after": last}
