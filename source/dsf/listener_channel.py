"""
One listener of the model, with its own bounded queue (phase 3c of the redesign, finding D-12). machine_state keeps one
ListenerChannel per function registered with on_change(); this module only holds the queue, it starts no thread itself:
whoever builds the channel passes `spawn(name, target)` (machine_state passes heartbeats.spawn_daemon, a thread of L2).
"""
import threading
from collections import deque

import service_log


def log_file(msg):
    service_log.log(msg, "state_machine")


LISTENER_QUEUE_MAX = 1000  # patches kept for ONE listener; when full the oldest of that listener is dropped


class ListenerChannel:
    """Bounded queue and delivery thread of ONE listener. put() never blocks: when the queue is full the oldest patch of this
    listener is dropped and counted. Delivery order is the order of put(). An exception of the listener is logged and the next
    patch is delivered. The thread starts with the first patch (`spawn(name, target)` makes it; the tests pass their own)."""

    def __init__(self, fn, spawn, maxlen=LISTENER_QUEUE_MAX):
        self.fn = fn
        self.name = getattr(fn, "__name__", None) or repr(fn)
        self.maxlen = maxlen
        self._spawn = spawn
        self._queue = deque()
        self._cond = threading.Condition()
        self._started = False
        self._busy = False
        self._closed = False
        self.delivered = 0
        self.dropped = 0
        self.errors = 0

    def put(self, patch, full):
        with self._cond:
            if self._closed:
                return
            if len(self._queue) >= self.maxlen:
                self._queue.popleft()
                self.dropped += 1
            self._queue.append((patch, full))
            start = not self._started
            self._started = True
            self._cond.notify_all()
        if start:
            try:
                self._spawn("listener-" + self.name, self.run)
            except Exception:
                with self._cond:
                    self._started = False
                raise

    def run(self):
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._queue or self._closed)
                if self._closed:
                    return
                patch, full = self._queue.popleft()
                self._busy = True
            self.deliver_one(patch, full)

    def deliver_one(self, patch, full):
        try:
            self.fn(patch, full)
            self.delivered += 1
        except Exception as e:
            self.errors += 1
            log_file(f"listener {self.name}: {type(e).__name__}: {e}")
        finally:
            with self._cond:
                self._busy = False
                self._cond.notify_all()

    def pending(self):
        with self._cond:
            return len(self._queue) + (1 if self._busy else 0)

    def wait_idle(self, timeout):
        with self._cond:
            return self._cond.wait_for(lambda: not self._queue and not self._busy, timeout)

    def close(self):
        with self._cond:
            self._closed = True
            self._queue.clear()
            self._cond.notify_all()

    def stats(self):
        with self._cond:
            return {"name": self.name, "queued": len(self._queue), "delivered": self.delivered,
                    "dropped": self.dropped, "errors": self.errors}
