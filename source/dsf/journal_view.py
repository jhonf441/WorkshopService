"""Read-only viewer of the system journal for the "System health" page (the `journal.read` operation).

What it does: asks `journalctl` for the lines of ONE unit of a closed list (or the kernel), over a fixed time window and level, and
returns them as plain data. It never changes anything and it never passes text typed by a person to a program:
  - the unit, the window and the level are CHOICES that map to fixed arguments (a value outside the choices is refused by the Arg check
    before this module runs, and `read()` re-checks it);
  - the search text is applied here, in Python, on the lines already read (no `--grep`, so it is data, never an argument);
  - the program is launched through os_gateway (closed list of executables, argv list, timeout), never through a shell.

Answers, never raises: {"readable": False, "reason": "no_permission" | "failed" | "no_journalctl"} when the journal cannot be read
(the page translates the reason); otherwise {"readable": True, "lines": [...], ...}.
Layer L1 (standard library + os_gateway, which is L0). The operation itself is registered by journal_ops.py (layer L5).
"""
import json
import time

import os_gateway

# id shown on the page -> arguments of journalctl that choose it. A new unit is a security decision: add it here and nowhere else.
UNITS = {
    "duetcontrolserver": ["-u", "duetcontrolserver"],
    "duetwebserver": ["-u", "duetwebserver"],
    "duetpluginservice": ["-u", "duetpluginservice"],
    "workshop-gcode-bridge": ["-u", "workshop-gcode-bridge"],
    "NetworkManager": ["-u", "NetworkManager"],
    "ssh": ["-u", "ssh"],
    "kernel": ["-k"],  # AppArmor denials and low-voltage messages live here
}
# window id -> value of --since
WINDOWS = {"15min": "-15min", "1h": "-1h", "6h": "-6h", "24h": "-24h", "7d": "-7d"}
# level id -> value of -p (that priority and the worse ones); "all" adds no -p
LEVELS = {"all": None, "notice": "notice", "warning": "warning", "error": "err"}
PRIORITY_NAMES = {0: "emerg", 1: "alert", 2: "crit", 3: "err", 4: "warning", 5: "notice", 6: "info", 7: "debug"}

DEFAULT_LINES = 200
MAX_LINES = 500
FETCH_LINES = 3000      # what journalctl is asked for before the text filter is applied
MAX_TEXT = 400          # characters kept of each line
MAX_SEARCH = 80
TIMEOUT_S = 12

_NO_PERMISSION = ("No journal files were opened", "insufficient permissions", "not seeing messages from other users")


def _text(message):
    """MESSAGE of a journal entry as text: journalctl gives a list of byte values when the line is not valid UTF-8."""
    if isinstance(message, list):
        try:
            return bytes(message).decode("utf-8", "replace")
        except (TypeError, ValueError):
            return ""
    return message if isinstance(message, str) else ""


def parse(stdout, search="", lines=DEFAULT_LINES):
    """`journalctl -o json` output -> (rows, truncated). Rows are the LAST `lines` that contain `search` (case-insensitive), oldest first:
    {"t": epoch milliseconds, "p": priority 0-7, "who": syslog identifier, "text": message}."""
    needle = (search or "").strip().lower()
    rows = []
    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        text = _text(e.get("MESSAGE")).replace("\r", "").strip()
        who = e.get("SYSLOG_IDENTIFIER") or e.get("_COMM") or ""
        if needle and needle not in text.lower() and needle not in str(who).lower():
            continue
        try:
            t = int(int(e.get("__REALTIME_TIMESTAMP")) / 1000)
            p = int(e.get("PRIORITY", 6))
        except (TypeError, ValueError):
            continue
        rows.append({"t": t, "p": p if 0 <= p <= 7 else 6, "who": str(who)[:60], "text": text[:MAX_TEXT]})
    truncated = len(rows) > lines
    return rows[-lines:], truncated


def build_argv(unit, since, level):
    """The argv list for journalctl, from CHOICES only; ValueError for anything else."""
    if unit not in UNITS or since not in WINDOWS or level not in LEVELS:
        raise ValueError("unknown unit, window or level")
    argv = ["journalctl", *UNITS[unit], "--since", WINDOWS[since], "--no-pager", "-o", "json", "-n", str(FETCH_LINES)]
    if LEVELS[level]:
        argv += ["-p", LEVELS[level]]
    return argv


def read(unit="duetcontrolserver", since="1h", level="all", search="", lines=DEFAULT_LINES):
    """One read of the journal, as described at the top. Never raises."""
    try:
        argv = build_argv(unit, since, level)
        lines = max(10, min(int(lines), MAX_LINES))
    except (ValueError, TypeError):
        return {"readable": False, "reason": "failed"}
    base = {"unit": unit, "since": since, "level": level, "search": (search or "")[:MAX_SEARCH]}
    try:
        r = os_gateway.run(argv, timeout=TIMEOUT_S, text=False)
    except FileNotFoundError:
        return dict(base, readable=False, reason="no_journalctl")
    except Exception:  # noqa: BLE001 -- timeout, policy refusal: the page only needs to know it failed
        return dict(base, readable=False, reason="failed")
    err = (r.stderr or b"").decode("utf-8", "replace")
    out = (r.stdout or b"").decode("utf-8", "replace")
    if any(s in err for s in _NO_PERMISSION) and not out.strip():
        return dict(base, readable=False, reason="no_permission")
    if r.returncode != 0 and not out.strip():
        return dict(base, readable=False, reason="failed")
    rows, truncated = parse(out, base["search"], lines)
    return dict(base, readable=True, lines=rows, truncated=truncated, read_at=int(time.time() * 1000))
