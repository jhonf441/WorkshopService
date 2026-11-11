"""Wall and monotonic time in one place, and the timing statistics of the Duet answers."""


import time


class Clock:
    """Wall and monotonic time in one place so the tests can drive them."""

    def wall(self):
        return time.time()

    def mono(self):
        return time.monotonic()


class Timing:
    """Exponential average and 5 minute maximum of the Duet answer time."""

    def __init__(self, clock):
        self.clock = clock
        self.avg_ms = None
        self.max_ms = 0.0
        self.window = clock.mono()

    def add(self, ms):
        now = self.clock.mono()
        self.avg_ms = ms if self.avg_ms is None else 0.9 * self.avg_ms + 0.1 * ms
        if now - self.window > 300:
            self.window = now
            self.max_ms = ms
        elif ms > self.max_ms:
            self.max_ms = ms
