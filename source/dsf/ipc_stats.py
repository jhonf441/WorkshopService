"""
Counter of the calls this process makes to DuetControlServer (DCS) over the
IPC socket: G-codes (perform_simple_code), expressions (evaluate_expression),
object model reads, set_plugin_data, messages. Every call goes through
call() / measure(), which keeps:
  - total calls, total time and slowest call per (type, who);
  - the calls of the last minute (a ring of timestamps) -> per_minute().
Every call costs DCS time (parsing, channel locks and, for M122 / M569 /
M569.2, round trips to the drivers), so this is the number to watch when the
Pi is slow while idle. snapshot() is published in servicesInternal.ipc (see
heartbeats.py) and per_minute() is a field of the black box line (ipc=<n>).

Types: "code" (G-code), "expr" (evaluate_expression), "model" (object model
read), "plugin_data" (set_plugin_data), "message" (write_message), "http"
(HTTP endpoint answer), "other". `who` is the module that asked (or the plugin
data key): one counter per (type, who), at most MAX_KEYS (the rest go to
"others").
The same module is copied in WorkshopVision/dsf and WorkshopRS485/dsf.
"""
import threading
import time
from collections import deque

WINDOW_S = 60.0
MAX_KEYS = 80
MAX_EVENTS = 20000  # memory cap of the window (above ~300 calls/s it undercounts)

_lock = threading.Lock()
_totals = {}  # (type, who) -> [calls, seconds, max_seconds]
_events = deque()  # (t, key)
_clock = time.monotonic  # tests replace it
_start = [None]


def _key(kind, who):
    k = (str(kind), str(who or ""))
    if k not in _totals and len(_totals) >= MAX_KEYS:
        k = (str(kind), "others")
    return k


def count(kind, who, dur_s=0.0):
    """Record a call that already happened (dur_s = how long it took)."""
    now = _clock()
    with _lock:
        if _start[0] is None:
            _start[0] = now
        k = _key(kind, who)
        t = _totals.setdefault(k, [0, 0.0, 0.0])
        t[0] += 1
        t[1] += dur_s
        if dur_s > t[2]:
            t[2] = dur_s
        _events.append((now, k))
        _prune(now)


def _prune(now):
    # _lock held
    while _events and (now - _events[0][0] > WINDOW_S or len(_events) > MAX_EVENTS):
        _events.popleft()


def call(kind, who, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) and count it (also when it raises)."""
    t0 = _clock()
    try:
        return fn(*args, **kwargs)
    finally:
        count(kind, who, _clock() - t0)


class measure:
    """with ipc_stats.measure("code", __name__): ..."""

    def __init__(self, kind, who=""):
        self.kind, self.who = kind, who

    def __enter__(self):
        self.t0 = _clock()
        return self

    def __exit__(self, *a):
        count(self.kind, self.who, _clock() - self.t0)
        return False


def per_minute(now=None):
    """Calls of the last WINDOW_S seconds, scaled to one minute."""
    now = _clock() if now is None else now
    with _lock:
        _prune(now)
        n = len(_events)
        t0 = _start[0]
    if t0 is not None and now - t0 < WINDOW_S:  # just started: the window is not full yet
        return int(round(n * 60.0 / max(now - t0, 5.0)))
    return int(round(n * 60.0 / WINDOW_S))


def snapshot(now=None):
    now = _clock() if now is None else now
    with _lock:
        _prune(now)
        recent = {}
        for _, k in _events:
            recent[k] = recent.get(k, 0) + 1
        kinds = {}
        for (kind, who), (n, sec, mx) in _totals.items():
            kinds[kind + "|" + who] = {
                "n": n, "ms": round(sec * 1000.0, 1), "max_ms": round(mx * 1000.0, 1),
                "last_min": recent.get((kind, who), 0),
            }
        total = sum(v["n"] for v in kinds.values())
    return {"per_min": per_minute(now), "total": total, "types": kinds}


def reset():
    with _lock:
        _totals.clear()
        _events.clear()
        _start[0] = None
