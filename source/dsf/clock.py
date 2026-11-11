"""
The two clocks of the service, in one place (plan item 9, finding A7 of the developer's report).

  mono()  time.monotonic(): for DURATIONS inside the process (ages of a heartbeat, deadlines, waits, windows). It never jumps: a
          Raspberry Pi has no battery clock, boots with the hour of its last shutdown and NTP corrects it all at once.
  wall()  time.time(): for DATES that are shown or stored (hours on a screen, activity dates, epochs published as JSON, file marks).
          It can jump forward or backward; never subtract two of them to decide something.

Rule: a monotonic reading is only meaningful inside the process that took it, so it is never saved or published. Whatever must
survive a restart stores wall time (or seconds remaining plus a boot id).

Tests inject a fake clock with set_for_tests(FakeClock()) and restore the real one with reset(); there is no other global state.
Standard library only (layer L0).
"""
import time


class FakeClock:
    """A clock the test moves by hand: advance() moves both readings, jump_wall() moves only the wall clock (an NTP step)."""

    def __init__(self, mono=1000.0, wall=1_800_000_000.0):
        self._mono = float(mono)
        self._wall = float(wall)

    def mono(self):
        return self._mono

    def wall(self):
        return self._wall

    def advance(self, seconds):
        self._mono += seconds
        self._wall += seconds

    def jump_wall(self, seconds):
        self._wall += seconds


_source = None  # None = the real clocks


def mono():
    return time.monotonic() if _source is None else _source.mono()


def wall():
    return time.time() if _source is None else _source.wall()


def set_for_tests(fake):
    """Replace both readings with the ones of `fake` (an object with mono() and wall()). Undo with reset()."""
    global _source
    _source = fake
    return fake


def reset():
    global _source
    _source = None
