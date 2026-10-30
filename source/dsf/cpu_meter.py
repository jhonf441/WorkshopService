"""CPU use of the Pi in percent, from two readings of /proc/stat.

One owner: health_poller.py measures it and publishes it in the `healthPi` data (cpu.use_pct); the camera relay reads it from there
(camera_load.py) instead of measuring on its own. The load average is no use here: on this Pi it sits at 6-7 with the CPU at half.
"""


def parse_stat(text):
    """(total, idle) jiffies from the first line of /proc/stat, or None."""
    try:
        v = [int(x) for x in str(text).split("\n", 1)[0].split()[1:]]
    except (ValueError, IndexError):
        return None
    if len(v) < 4:
        return None
    return sum(v), v[3] + (v[4] if len(v) > 4 else 0)


class CpuMeter:
    """sample(text) -> % busy since the previous sample (None the first time or when the counters did not advance)."""

    def __init__(self):
        self.previous = None

    def sample(self, text):
        now = parse_stat(text)
        if now is None:
            return None
        previous, self.previous = self.previous, now
        if not previous or now[0] <= previous[0]:
            return None
        return max(0.0, min(100.0, 100.0 * (1 - (now[1] - previous[1]) / (now[0] - previous[0]))))

    def read(self, path="/proc/stat"):
        try:
            with open(path) as fh:
                return self.sample(fh.readline())
        except OSError:
            return None
