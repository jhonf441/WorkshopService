"""CPU and memory of a few chosen processes, from /proc (layer L1: standard library only).

What it is for: the "System health" page shows how much CPU and memory the Duet servers and this service use, so a slowdown can be blamed on
the right program. Two ways, chosen so the AppArmor profile of the service never has anything to deny (a denial is a DENIED line in the kernel
log every time, and it hides the real ones the owner looks for):
  - CPU of a UNIT: UnitCpuMeter, from the `CPUUsageNSec` counter systemd keeps (one `systemctl show`), also for a unit of another user;
  - CPU and memory of THIS process: ProcessMeter.read, from its own /proc/self-style files (nothing else is asked of the kernel);
  - memory of another process: ProcessMeter.rss_mb, from `statm` only. Never `stat` of another process: that is what makes the kernel ask AppArmor
    for a ptrace permission (measured on the Pi, 2026-11-21: one DENIED line per reading).
It never walks /proc to find processes, and a list of the heaviest processes of the whole Pi is not offered because of it.

CPU is the percentage of ONE core since the previous reading (like `top`: two busy threads show 200). The first reading has no CPU yet.
A process that restarted starts over. A read the kernel refuses is remembered for that pid and never repeated.
"""
import os
import time

DEFAULT_CLK_TCK = 100
DEFAULT_PAGE_SIZE = 4096


def system_constants():
    """(clock ticks per second, page size in bytes); the usual values when the system does not tell."""
    try:
        return int(os.sysconf("SC_CLK_TCK")), int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return DEFAULT_CLK_TCK, DEFAULT_PAGE_SIZE


def parse_stat(text):
    """(utime + stime in clock ticks, start time in ticks since boot, number of threads) from the text of /proc/<pid>/stat, or None.
    The name of the program sits between parentheses and may hold spaces and parentheses, so the fields are counted after the LAST ")"."""
    try:
        rest = str(text).rsplit(")", 1)[1].split()
        # rest[0] is the state (field 3 of proc(5)); utime is field 14, stime 15, num_threads 20, starttime 22
        return int(rest[11]) + int(rest[12]), int(rest[19]), int(rest[17])
    except (IndexError, ValueError):
        return None


def parse_statm(text):
    """Resident set size in pages (second field of /proc/<pid>/statm), or None."""
    try:
        return int(str(text).split()[1])
    except (IndexError, ValueError):
        return None


class UnitCpuMeter:
    """CPU of a systemd UNIT in percent of one core, from the counter `CPUUsageNSec` that systemd keeps for the unit (all its processes):
    no /proc of another process is read, so the AppArmor profile of the service has nothing to deny. sample(unit, usage_ns) gives the percent
    since the previous sample of the same unit; None the first time, when the counter is missing, or when it went down (the unit restarted)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.previous = {}  # unit -> (nanoseconds, time of the reading)

    def sample(self, unit, usage_ns):
        now = self.clock()
        if usage_ns is None:
            self.previous.pop(unit, None)
            return None
        before = self.previous.get(unit)
        self.previous[unit] = (usage_ns, now)
        if not before or usage_ns < before[0] or now <= before[1]:
            return None
        return round(100.0 * (usage_ns - before[0]) / 1e9 / (now - before[1]), 1)


class ProcessMeter:
    """read(pid) -> {"pid", "cpu_pct", "rss_mb", "threads"} or {"pid", "error": "gone" | "denied"}. One instance keeps the previous reading of each pid."""

    def __init__(self, proc="/proc", clock=time.monotonic, constants=None):
        self.proc = proc
        self.clock = clock
        self.ticks_per_s, self.page_size = constants or system_constants()
        self.previous = {}  # pid -> (ticks, start, time of the reading)
        self.denied = set()

    def _text(self, pid, name):
        with open(os.path.join(self.proc, str(pid), name)) as fh:
            return fh.read()

    def read(self, pid):
        if pid in self.denied:
            return {"pid": pid, "error": "denied"}
        try:
            stat = parse_stat(self._text(pid, "stat"))
            rss = parse_statm(self._text(pid, "statm"))
        except PermissionError:
            self.denied.add(pid)
            self.previous.pop(pid, None)
            return {"pid": pid, "error": "denied"}
        except OSError:  # the process is gone
            self.previous.pop(pid, None)
            return {"pid": pid, "error": "gone"}
        if stat is None or rss is None:
            return {"pid": pid, "error": "gone"}
        ticks, start, threads = stat
        now = self.clock()
        before = self.previous.get(pid)
        self.previous[pid] = (ticks, start, now)
        cpu = None
        if before and before[1] == start and now > before[2] and ticks >= before[0]:
            cpu = round(100.0 * (ticks - before[0]) / self.ticks_per_s / (now - before[2]), 1)
        return {"pid": pid, "cpu_pct": cpu, "rss_mb": round(rss * self.page_size / 1048576, 1), "threads": threads}

    def rss_mb(self, pid):
        """Resident memory in MB from `statm` ONLY (never `stat`: reading `stat` of another process makes the kernel ask AppArmor for a ptrace
        permission the service's profile does not grant, and it logs a DENIED line every time). None when it cannot be read; a refused pid is
        remembered and not tried again."""
        if pid in self.denied:
            return None
        try:
            rss = parse_statm(self._text(pid, "statm"))
        except PermissionError:
            self.denied.add(pid)
            return None
        except OSError:
            return None
        return None if rss is None else round(rss * self.page_size / 1048576, 1)

    def forget_others(self, pids):
        """Drop what is kept for pids that are not measured any more (a unit that restarted has a new pid)."""
        keep = set(pids)
        for pid in [p for p in self.previous if p not in keep]:
            del self.previous[pid]
