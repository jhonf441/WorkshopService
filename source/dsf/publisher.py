"""
Publisher of plugin data (set_plugin_data) with change detection and rate
limit (2026-10-12, DCS load). Every set_plugin_data is an IPC call that costs
DuetControlServer time (JSON parse, object model patch, notification to every
subscriber), and the pollers used to send the same values over and over (a
timestamp field made each value "new").

Publisher.set(key, value, ...):
  - compares the value with the last one SENT (deep compare through its JSON,
    ignoring the top-level fields in `volatile`, e.g. "updated_at"); if nothing
    changed it is dropped (the value is kept so keepalive_s can resend it);
  - a changed value is queued and sent by the publisher thread, never by the
    caller: the interceptor and the pollers never wait for the DCS socket or
    for the bridge lock;
  - at most one send per key every `min_interval` seconds (the newest value
    wins: a burst of changes becomes one call);
  - keepalive_s: resend the latest value after that long even without changes
    (fresh timestamps for pages that show an age).
bridge.datos (the readers inside the service) is updated by the caller at once.
"""
import copy
import json
import threading
import time

import ipc_stats

DEFAULT_MIN_INTERVAL_S = 0.0
RETRY_S = 2.0

# keys that change with every intercepted code: at most once per second
MIN_INTERVAL = {
    "lastCode": 1.0,
    "lastCodeTime": 1.0,
    "lastCommands": 1.0,
    "jogFree": 1.0,
}


def _signature(value, volatile=()):
    if volatile and isinstance(value, dict):
        value = {k: v for k, v in value.items() if k not in volatile}
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


class Publisher:
    def __init__(self, send, clock=time.monotonic, log=None, min_interval=None):
        """send(key, value): the real set_plugin_data (may raise)."""
        self._send = send
        self._clock = clock
        self._log = log or (lambda m: None)
        self._min = dict(MIN_INTERVAL if min_interval is None else min_interval)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._last = {}     # key -> (signature, time sent)
        self._latest = {}   # key -> (value, volatile, keepalive_s)
        self._pending = {}  # key -> due time (clock)
        self._thread = None

    # ---- caller side ----

    def set(self, key, value, min_interval=None, volatile=(), keepalive_s=None):
        """Queue `value` for `key` if it changed. Returns True if queued."""
        now = self._clock()
        sig = _signature(value, volatile)
        with self._lock:
            last = self._last.get(key)
            interval = self._min.get(key, DEFAULT_MIN_INTERVAL_S) if min_interval is None else min_interval
            self._latest[key] = (copy.deepcopy(value), tuple(volatile), keepalive_s)
            if last is not None and last[0] == sig:
                self._pending.pop(key, None)  # back to the published value: nothing to send
                return False
            due = now if last is None else max(now, last[1] + interval)
            if key in self._pending:
                due = min(self._pending[key], due)
            self._pending[key] = due
        self._wake.set()
        return True

    # ---- publisher side ----

    def flush(self, now=None):
        """Send what is due. Returns the number of sends made."""
        now = self._clock() if now is None else now
        with self._lock:
            todo = [k for k, due in self._pending.items() if due <= now]
            for key, (value, volatile, keepalive) in self._latest.items():
                last = self._last.get(key)
                if keepalive and key not in self._pending and last is not None and now - last[1] >= keepalive:
                    todo.append(key)
        sent = 0
        for key in todo:
            with self._lock:
                value, volatile, keepalive = self._latest[key]
            try:
                self._send(key, value)
            except Exception as e:
                self._log(f"publisher: could not send '{key}' ({e}); retry in {RETRY_S:.0f}s")
                with self._lock:
                    self._pending[key] = now + RETRY_S
                continue
            sent += 1
            with self._lock:
                self._last[key] = (_signature(value, volatile), now)
                self._pending.pop(key, None)
        return sent

    def next_wait_s(self, now=None):
        """Seconds until something is due (None: nothing queued)."""
        now = self._clock() if now is None else now
        with self._lock:
            dues = list(self._pending.values())
            for key, (value, volatile, keepalive) in self._latest.items():
                last = self._last.get(key)
                if keepalive and key not in self._pending and last is not None:
                    dues.append(last[1] + keepalive)
        return max(0.0, min(dues) - now) if dues else None

    def pending(self):
        with self._lock:
            return sorted(self._pending)

    def run(self, stop=lambda: False):
        while not stop():
            try:
                self.flush()
            except Exception as e:
                self._log(f"publisher: {e}")
            wait = self.next_wait_s()
            self._wake.wait(30.0 if wait is None else max(0.05, min(wait, 30.0)))
            self._wake.clear()

    def start(self, name="publisher"):
        if self._thread is None:
            self._thread = threading.Thread(target=self.run, name=name, daemon=True)
            self._thread.start()
        return self._thread


def instrument(send):
    """Wrap a set_plugin_data sender: every call is counted in ipc_stats by key."""

    def wrapped(key, value):
        return ipc_stats.call("plugin_data", key, send, key, value)

    return wrapped
