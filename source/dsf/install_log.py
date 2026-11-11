"""
install_log -- the report of every run of the start-up ("Puesta en marcha") on the SD (SD-LAYOUT.md E.2, phase 1).

Two append-only tables of the service database (duet.db, schema 7):
  install_runs     one row per run: who, how, when, which plugins, counts per outcome
  install_actions  one row per file the run looked at: what happened and why, sha before and after, backup, diff

Phase 1 only RECORDS what the service already does (the creation of the example files of a plugin, examples.py); it does not add
a single write to the SD and it never changes what the start-up does: every call here is wrapped by the caller so that a failure
of the log can never break the operation that is being logged.

Nothing is ever edited: the triggers refuse every UPDATE, and a row younger than RETENTION_DAYS cannot be deleted (the purge
removes only older runs beyond the newest RETENTION_RUNS, and never the last run of a plugin).
"""
import json
import os
import re
import secrets
import time

import db

FMT = "%Y-%m-%dT%H:%M:%S"
RETENTION_DAYS = 365
RETENTION_RUNS = 500
DIFF_MAX = 40 * 1024
TRIGGERS = ("wizard", "plugin-install", "plugin-update", "hook-install", "integrity-restore", "migration")
ACTIONS = ("created", "updated", "unchanged", "skipped_user_content", "skipped_exists", "skipped_created_before", "backed_up", "restored",
           "quarantined", "moved", "hook_inserted", "hook_updated", "hook_removed", "hook_adopted", "drift_detected", "failed")

# config.g can hold the DWC password and the network credentials: these never reach the table. A COMMENTED line (`; M551 P"..."`) is
# masked too: the person comments a secret out and it is still the secret
_SECRET_LINE = re.compile(r"^(\s*(?:[+-]\s*)?(?:;\s*)?M(?:551|552|553|554|587|588|589)\b).*$", re.I | re.M)


def ensure_tables(conn):
    """Schema 6 -> 7 (idempotent). Called by db.init_db."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS install_runs (
            run_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            trigger TEXT NOT NULL,
            actor TEXT, role TEXT, device TEXT, via TEXT,
            dry_run INTEGER NOT NULL DEFAULT 0,
            plugins TEXT,
            summary TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_install_runs_ts ON install_runs(ts);
        CREATE TABLE IF NOT EXISTS install_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES install_runs(run_id),
            plugin TEXT, path TEXT NOT NULL, kind TEXT,
            action TEXT NOT NULL,
            reason TEXT,
            sha_before TEXT, sha_after TEXT, size_before INTEGER, size_after INTEGER,
            backup_path TEXT,
            diff TEXT,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_install_actions_run ON install_actions(run_id);
        CREATE INDEX IF NOT EXISTS idx_install_actions_path ON install_actions(path);
        CREATE TRIGGER IF NOT EXISTS install_runs_no_update BEFORE UPDATE ON install_runs
        BEGIN SELECT RAISE(ABORT, 'install log is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS install_actions_no_update BEFORE UPDATE ON install_actions
        BEGIN SELECT RAISE(ABORT, 'install log is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS install_runs_no_delete BEFORE DELETE ON install_runs
        WHEN OLD.ts >= strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime', '-365 days')
        BEGIN SELECT RAISE(ABORT, 'install log is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS install_actions_no_delete BEFORE DELETE ON install_actions
        WHEN (SELECT ts FROM install_runs WHERE run_id = OLD.run_id) >= strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime', '-365 days')
        BEGIN SELECT RAISE(ABORT, 'install log is append-only'); END;
        """
    )


def redact(text, limit=DIFF_MAX):
    """A diff or a line of a configuration file safe to store: the arguments of every M551 / M552-M554 / M587-M589 line (password,
    network, WiFi) are replaced by ***, and the text is cut at `limit` bytes. Other P"..." arguments are paths and stay."""
    text = _SECRET_LINE.sub(lambda m: m.group(1) + " ***", str(text or ""))
    if len(text.encode("utf-8")) > limit:
        text = text.encode("utf-8")[:limit].decode("utf-8", "ignore") + "\n[... cut]"
    return text


class Run:
    """The actions of one run, kept in memory and written in ONE transaction by finish() (a run that never finishes leaves nothing)."""

    def __init__(self, trigger, actor="", role="", device="", via="", dry_run=False, plugins=None):
        if trigger not in TRIGGERS:
            raise ValueError("unknown trigger " + str(trigger))
        self.run_id = "%s-%s" % (time.strftime("%Y%m%dT%H%M%S"), secrets.token_hex(3))
        self.ts = time.strftime(FMT)
        self.head = (trigger, actor or "", role or "", device or "", via or "", 1 if dry_run else 0)
        self.plugins = dict(plugins or {})
        self.actions = []

    def add(self, plugin, path, action, kind=None, reason=None, sha_before=None, sha_after=None, size_before=None, size_after=None,
            backup_path=None, diff=None, error=None):
        if action not in ACTIONS and not str(action).startswith("would_"):
            raise ValueError("unknown action " + str(action))
        self.actions.append((plugin, str(path), kind, action, reason, sha_before, sha_after, size_before, size_after, backup_path,
                             redact(diff) if diff else None, str(error)[:500] if error else None))
        if plugin and plugin not in self.plugins:
            self.plugins[plugin] = ""

    def summary(self):
        out = {}
        for a in self.actions:
            out[a[3]] = out.get(a[3], 0) + 1
        return out

    def finish(self):
        """Writes the run and its actions. Returns the run_id."""
        trigger, actor, role, device, via, dry_run = self.head
        insert_run(run_id=self.run_id, ts=self.ts, trigger=trigger, actor=actor, role=role, device=device, via=via, dry_run=dry_run,
                   plugins=json.dumps(self.plugins, sort_keys=True), summary=json.dumps(self.summary(), sort_keys=True), actions=self.actions)
        return self.run_id


# ---- the tables install_runs / install_actions: the only place that holds their SQL ----

def insert_run(*, run_id, ts, trigger, actor="", role="", device="", via="", dry_run=0, plugins="{}", summary="{}", actions=()):
    """Writes one run and its actions in ONE transaction. `plugins` and `summary` are JSON text; each action is the tuple
    (plugin, path, kind, action, reason, sha_before, sha_after, size_before, size_after, backup_path, diff, error)."""
    with db.session() as conn:
        conn.execute("INSERT INTO install_runs (run_id, ts, trigger, actor, role, device, via, dry_run, plugins, summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (run_id, ts, trigger, actor, role, device, via, dry_run, plugins, summary))
        conn.executemany(
            "INSERT INTO install_actions (run_id, plugin, path, kind, action, reason, sha_before, sha_after, size_before, size_after, "
            "backup_path, diff, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [(run_id,) + tuple(a) for a in actions])


def _run_row(r):
    d = dict(r)
    d["dry_run"] = bool(d["dry_run"])
    for k in ("plugins", "summary"):
        try:
            d[k] = json.loads(d[k] or "{}")
        except ValueError:
            d[k] = {}
    return d


def list_runs(limit=50, offset=0, plugin=None):
    """Summaries, newest first (no paths): {"total", "rows"}."""
    where, args = "", []
    if plugin:
        where = "WHERE EXISTS (SELECT 1 FROM install_actions a WHERE a.run_id = install_runs.run_id AND a.plugin = ?)"
        args.append(plugin)
    with db.read_session() as conn:
        total = conn.execute("SELECT COUNT(*) FROM install_runs " + where, args).fetchone()[0]
        rows = conn.execute("SELECT * FROM install_runs %s ORDER BY ts DESC, run_id DESC LIMIT ? OFFSET ?" % where,
                            args + [max(1, min(int(limit), 200)), max(0, int(offset))]).fetchall()
    return {"total": total, "rows": [_run_row(r) for r in rows]}


def get_run(run_id, with_diff=False):
    """One run with its actions, or None. The diff text is returned only when `with_diff` (administrator); otherwise `has_diff`."""
    with db.read_session() as conn:
        r = conn.execute("SELECT * FROM install_runs WHERE run_id = ?", (str(run_id),)).fetchone()
        if r is None:
            return None
        acts = conn.execute("SELECT * FROM install_actions WHERE run_id = ? ORDER BY id", (str(run_id),)).fetchall()
    out = _run_row(r)
    out["actions"] = []
    for a in acts:
        d = dict(a)
        d["has_diff"] = bool(d.get("diff"))
        if not with_diff:
            d.pop("diff", None)
        out["actions"].append(d)
    return out


def last_action_by_path(plugin=None):
    """{path: last action row without diff}: the small "what happened" line of each card."""
    q = ("SELECT a.path, a.plugin, a.action, a.reason, a.sha_after, r.ts, r.run_id, r.trigger, r.actor FROM install_actions a JOIN install_runs r USING (run_id) "
         "WHERE a.id IN (SELECT MAX(id) FROM install_actions GROUP BY path)")
    args = []
    if plugin:
        q += " AND a.plugin = ?"
        args.append(plugin)
    with db.read_session() as conn:
        return {r["path"]: dict(r) for r in conn.execute(q, args).fetchall()}


def purge(*, retention_days=None, keep_runs=None):
    """Maintenance: removes the runs older than `retention_days` (default RETENTION_DAYS) that are beyond the newest `keep_runs`
    (default RETENTION_RUNS), never the last run of a plugin. Returns how many runs went."""
    retention_days = RETENTION_DAYS if retention_days is None else retention_days
    keep_runs = RETENTION_RUNS if keep_runs is None else keep_runs
    limit = time.strftime(FMT, time.localtime(time.time() - retention_days * 86400))
    with db.session() as conn:
        keep = {r[0] for r in conn.execute("SELECT run_id FROM install_runs ORDER BY ts DESC, run_id DESC LIMIT ?", (keep_runs,))}
        for (plugin,) in conn.execute("SELECT DISTINCT plugin FROM install_actions WHERE plugin IS NOT NULL").fetchall():
            last = conn.execute("SELECT r.run_id FROM install_runs r JOIN install_actions a USING (run_id) WHERE a.plugin = ? "
                                "ORDER BY r.ts DESC, r.run_id DESC LIMIT 1", (plugin,)).fetchone()
            if last:
                keep.add(last[0])
        old = [r[0] for r in conn.execute("SELECT run_id FROM install_runs WHERE ts < ?", (limit,)).fetchall() if r[0] not in keep]
        for rid in old:
            conn.execute("DELETE FROM install_actions WHERE run_id = ?", (rid,))
            conn.execute("DELETE FROM install_runs WHERE run_id = ?", (rid,))
    return len(old)


# ---- the one place that writes a run today: the creation of the example files (examples.install) ----

def _file_facts(route):
    try:
        with open(route, "rb") as f:
            data = f.read(4 * 1024 * 1024)
        import hashlib
        return hashlib.sha256(data).hexdigest(), os.path.getsize(route)
    except OSError:
        return None, None


def record_examples(plugin, result, actor=None, sd=None, dry_run=False):
    """Writes the run of one `examples.install` result ({"created": [...], "skipped": {dest: reason}}). Never raises: the log must not
    break the start-up. Returns the run_id or None."""
    try:
        import paths
        sd = sd or paths.SD
        actor = actor or {}
        run = Run("wizard", actor.get("user", ""), actor.get("role", ""), actor.get("device", ""), actor.get("via", "api"), dry_run, {plugin: ""})
        for rel in result.get("created", []):
            sha, size = _file_facts(os.path.join(sd, rel))
            run.add(plugin, rel, "created", "template", "file_absent", sha_after=sha, size_after=size)
        for rel, why in sorted((result.get("skipped") or {}).items()):
            if why == "exists":
                sha, size = _file_facts(os.path.join(sd, rel))
                run.add(plugin, rel, "skipped_exists", "template", "file_exists", sha_before=sha, size_before=size)
            elif why == "created_before":
                run.add(plugin, rel, "skipped_created_before", "template", "registry_says_created")
            else:
                run.add(plugin, rel, "failed", "template", "write_error", error=why)
        if not run.actions:
            return None  # nothing to say: an empty call is not a run
        return run.finish()
    except Exception:  # noqa: BLE001 -- by design: a failure of the log never reaches the person
        return None
