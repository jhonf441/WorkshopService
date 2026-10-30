"""
Who is looking at what (2026-10-12, DCS load): a page sends a heartbeat while
it is visible (the same pattern as the trace view, handlers/trace.py) and the
poller that feeds only that page works at full speed while heartbeats keep
arriving. Without a heartbeat for TTL_S seconds nobody is looking: the poller
sleeps or slows to a long period (every IPC call costs DuetControlServer time,
see ipc_stats.py and docs-internal/DCS-LOAD.md in TallerPlugins).

Topics: "motors" (Motors page: M122 / M569 / M569.2 reads), "health" (System
health and Services pages), "power" (Consumption page),
"lights_board" (Lights page, Advanced tab: the board signals panel). Heartbeat sources:
the API (motors) S"watch" and the API (viewing) S"<topic>" (handlers/viewing.py),
every ~10 s from the visible page.
"""
import threading
import time

TTL_S = 30.0
TOPICS = ("motors", "health", "power", "lights_board")

_lock = threading.Lock()
_last = {}   # topic -> monotonic time of the last heartbeat
_wake = {}   # topic -> Event set when a heartbeat arrives while nobody was looking
_clock = time.monotonic  # tests replace it


def _event(topic):
    ev = _wake.get(topic)
    if ev is None:
        ev = _wake[topic] = threading.Event()
    return ev


def heartbeat(topic, now=None):
    """Someone is looking at `topic`. True if it was idle before (wakes the poller)."""
    now = _clock() if now is None else now
    with _lock:
        before = _last.get(topic)
        _last[topic] = now
        was_idle = before is None or now - before >= TTL_S
        if was_idle:
            _event(topic).set()
    return was_idle


def active(topic, now=None):
    now = _clock() if now is None else now
    with _lock:
        t = _last.get(topic)
    return t is not None and now - t < TTL_S


def age_s(topic, now=None):
    """Seconds since the last heartbeat (None: never)."""
    now = _clock() if now is None else now
    with _lock:
        t = _last.get(topic)
    return None if t is None else now - t


def sleep(topic, seconds):
    """Wait up to `seconds`, or less if a heartbeat arrives from an idle state
    (so the page does not wait a whole idle period for its first data)."""
    with _lock:
        ev = _event(topic)
    woke = ev.wait(seconds)
    if woke:
        ev.clear()
    return woke
