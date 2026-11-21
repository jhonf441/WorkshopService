"""The workshop's own logs, read like the system journal for the "System log" card (layer L1: standard library + service_log; the runs of the start-up come from a loader the caller gives, so this module does not depend on the database).

Two sources, both files or tables the service already keeps; nothing here writes and nothing needs a permission the service does not have:
  workshop-service   the service log (0:/sys/workshop/data/logs/workshop-service.log and its rotated copies .1 .2 .3), one line per event
  install            the runs of the start-up ("Puesta en marcha"): who ran it, what for and how many files each outcome got
Both answer in the same shape as journal_view.parse: rows {"t": epoch ms, "p": priority 0-7, "who", "text"}, oldest first, only the last
`lines` that match, plus a flag that says there were more. The window (since) and the level are the same choices the page offers.
"""
import re
import time

import service_log

SOURCES = ("workshop-service", "install")
WINDOW_S = {"15min": 900, "1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
MAX_PRIORITY = {"all": 7, "notice": 5, "warning": 4, "error": 3}  # a row is kept when its priority is this number or lower (0 = worst)
LEVEL_PRIORITY = {"DEBUG": 7, "WARNING": 4, "ERROR": 3, "CRITICAL": 2}  # a line with no level word is "info" (6)
MAX_TEXT = 400
INSTALL_RUNS = 200
FMT = "%Y-%m-%dT%H:%M:%S"
_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) (?:\[([^\]]{1,40})\] )?(?:(DEBUG|WARNING|ERROR|CRITICAL): )?(.*)$")


def _epoch_ms(stamp):
    return int(time.mktime(time.strptime(stamp, FMT)) * 1000)


def parse_service_log(text, since_ms, max_priority, search="", lines=200):
    """Text of the service log (oldest first) -> (rows, truncated). A line that does not start with a time (a traceback) belongs to the row above."""
    needle = (search or "").strip().lower()
    rows = []
    for raw in str(text).splitlines():
        m = _LINE.match(raw)
        if not m:
            if rows and raw.strip() and len(rows[-1]["text"]) < MAX_TEXT:
                rows[-1]["text"] = (rows[-1]["text"] + "\n" + raw.rstrip())[:MAX_TEXT]
            continue
        try:
            t = _epoch_ms(m.group(1))
        except (ValueError, OverflowError):
            continue
        rows.append({"t": t, "p": LEVEL_PRIORITY.get(m.group(3), 6), "who": m.group(2) or "", "text": m.group(4)[:MAX_TEXT]})
    rows = [r for r in rows if r["t"] >= since_ms and r["p"] <= max_priority
            and (not needle or needle in r["text"].lower() or needle in r["who"].lower())]
    return rows[-lines:], len(rows) > lines


def service_log_text(path):
    """The rotated copies and the current file, oldest first, as one text; FileNotFoundError when there is no file at all."""
    names = [f"{path}.{n}" for n in (3, 2, 1)] + [path]
    parts = []
    for name in names:
        try:
            with open(name, "rb") as fh:
                parts.append(fh.read().decode("utf-8", "replace"))
        except OSError:
            continue
    if not parts:
        raise FileNotFoundError(path)
    return "\n".join(parts)


def install_rows(runs, since_ms, max_priority, search="", lines=200):
    """Runs of install_log.list_runs (newest first) -> (rows, truncated), oldest first."""
    needle = (search or "").strip().lower()
    rows = []
    for run in reversed(list(runs)):
        try:
            t = _epoch_ms(str(run.get("ts")))
        except (ValueError, OverflowError):
            continue
        counts = [f"{k} {v}" for k, v in sorted((run.get("summary") or {}).items()) if isinstance(v, int) and not isinstance(v, bool) and v]
        failed = bool((run.get("summary") or {}).get("failed"))
        plugins = ", ".join(sorted(run.get("plugins") or {}))
        text = " ".join(x for x in (str(run.get("actor") or "-"), plugins and "(" + plugins + ")", ", ".join(counts)) if x)
        if run.get("dry_run"):
            text += " [dry run]"
        row = {"t": t, "p": 4 if failed else 6, "who": str(run.get("trigger") or ""), "text": text[:MAX_TEXT]}
        if t >= since_ms and row["p"] <= max_priority and (not needle or needle in row["text"].lower() or needle in row["who"].lower()):
            rows.append(row)
    return rows[-lines:], len(rows) > lines


def read(source, since, level, search="", lines=200, now=None, runs_loader=None):
    """(rows, truncated) of one source; `runs_loader()` gives {"rows": [...]} like install_log.list_runs; ValueError for an unknown source, window or level; FileNotFoundError when the service log is not on."""
    if source not in SOURCES or since not in WINDOW_S or level not in MAX_PRIORITY:
        raise ValueError("unknown source, window or level")
    since_ms = int(((now if now is not None else time.time()) - WINDOW_S[since]) * 1000)
    if source == "install":
        if runs_loader is None:
            raise ValueError("no loader for the start-up runs")
        return install_rows(runs_loader()["rows"], since_ms, MAX_PRIORITY[level], search, lines)
    path = service_log.path()
    if not path:
        raise FileNotFoundError("the service log is off")
    return parse_service_log(service_log_text(path), since_ms, MAX_PRIORITY[level], search, lines)
