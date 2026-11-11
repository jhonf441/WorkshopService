"""Debug mode: the in-memory ring buffer and the on / off / renew logic of the Bridge."""


import collections
import os
import threading
import time

from bridge_pkg.log import LOG


DEBUG_RING_LINES = 300
DEBUG_TEXT_MAX = 200


class DebugRing:
    def __init__(self, clock, maxlen=DEBUG_RING_LINES):
        self.clock = clock
        self.lock = threading.Lock()
        self.lines = collections.deque(maxlen=maxlen)
        self.next_id = 1
        self.active = False

    def add(self, client, kind, text):
        if not self.active:
            return
        text = str(text)
        if len(text) > DEBUG_TEXT_MAX:
            text = text[:DEBUG_TEXT_MAX] + "..."
        wall = self.clock.wall()
        stamp = time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int((wall % 1) * 1000):03d}"
        with self.lock:
            self.lines.append({"id": self.next_id, "t": stamp, "c": client, "k": kind, "x": text})
            self.next_id += 1

    def clear(self):
        with self.lock:
            self.lines.clear()

    def snapshot(self):
        with self.lock:
            return list(self.lines)

    @property
    def last_id(self):
        with self.lock:
            return self.next_id - 1


class DebugMixin:
    """Debug mode of the bridge (mixed into Bridge)."""

    # -- debug mode --
    @property
    def debug_active(self):
        return self.debug_ring.active

    def set_debug(self, on, persist=True):
        """Turn the in-memory debug on or off. While on it renews itself from the
        page's heartbeat (when debug_renew is on) and switches itself off after debug_timeout_min."""
        minutes = self.settings.get("debug_timeout_min")
        if on:
            if not self.debug_ring.active:
                self.debug_ring.clear()
            self.debug_ring.active = True
            self.debug_until = self.clock.mono() + minutes * 60
            self.event("info", "debug_on", f"Debug on (turns off by itself after {minutes} min without being viewed)", minutes=minutes)
        else:
            was = self.debug_ring.active
            self.debug_ring.active = False
            self.debug_until = None
            if was:
                self.event("info", "debug_off", "Debug off")
        if persist and self.settings.get("debug") != bool(on):
            try:
                self.settings.modify(lambda d: d.update(debug=bool(on)))
            except OSError as e:
                LOG.warning("could not save the debug setting: %s", e)

    def debug_tick(self):
        cfg_debug = bool(self.settings.get("debug"))
        if cfg_debug and not self.debug_ring.active:
            self.set_debug(True, persist=False)
        elif not cfg_debug and self.debug_ring.active:
            self.set_debug(False, persist=False)
        if not self.debug_ring.active:
            return
        try:
            m = os.path.getmtime(self.paths.viewer)
        except OSError:
            m = None
        if m is not None and m != self.viewer_mtime:
            self.viewer_mtime = m
            self.viewer_seen_at = self.clock.wall()
            if self.settings.get("debug_renew"):
                self.debug_until = self.clock.mono() + self.settings.get("debug_timeout_min") * 60
        if self.debug_until is not None and self.clock.mono() >= self.debug_until:
            self.set_debug(False)
