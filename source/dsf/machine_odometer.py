"""The integrator of the maintenance counters (Machine v2, phase 4, design 2.10): PURE, no thread, no file, no clock of its own.

The board keeps no odometer. machine_maint_poller.py feeds this class with samples of the object model that the single subscription of
machine_state already has (nobody polls /machine/status) and flushes the result into the store `machine-maintenance` (merge_counters).

Per axis letter and for the board as a whole it counts, in seconds and millimetres (the answer converts to hours and metres):

    power_on_s    the machine was powered (status not off / disconnected / starting / updating) and the axis was not released
    moving_s      the axis machinePosition changed more than MOVE_EPS_MM between two samples
    distance_mm   ESTIMATED: the sum of |change of machinePosition| between samples. An underestimate whenever the head reverses
                  between two samples; the patches of the model arrive faster than 1 Hz while moving but the real rate is unverified
    xy_mm         (board only) the length of the XY path: sum of hypot(dx, dy); the number compared with the planned path of a job

Rules that keep the counters honest:
  - GAP: two samples more than MAX_GAP_S apart (the service was down, the subscription was lost) count NOTHING for that interval and
    do not create a jump: the next sample is only a new baseline. `gaps` goes up.
  - HOMING: when the `homed` flag of an axis changed between the two samples its position was rewritten (homing / unhoming): that
    interval counts no distance for the axis.
  - JUMP: an implied speed above MAX_SPEED_MM_S is a rewritten position (G92, a reset), not motion: ignored, `jumps` goes up.
  - Only the time between two samples that BOTH show a powered machine counts as power-on.
"""
import math

MAX_GAP_S = 10.0
MOVE_EPS_MM = 0.002
MAX_SPEED_MM_S = 2000.0
UNPOWERED = ("off", "disconnected", "starting", "updating")
FIELDS = ("power_on_s", "moving_s", "distance_mm")
BOARD_FIELDS = FIELDS + ("xy_mm",)


def _blank(fields):
    return {k: 0.0 for k in fields}


def blank_delta():
    return {"board": _blank(BOARD_FIELDS), "axes": {}, "gaps": 0, "jumps": 0}


def powered(status):
    return bool(status) and str(status).lower() not in UNPOWERED


class Odometer:
    """feed(t, status, positions, homed, released) with t in monotonic seconds; take() returns what accumulated since the last take()."""

    def __init__(self, max_gap_s=MAX_GAP_S):
        self.max_gap_s = max_gap_s
        self.prev = None
        self.pending = blank_delta()
        self.xy_total = 0.0        # since this object was made (a job's length is the difference between two reads)
        self.gaps_total = 0

    def reset_baseline(self, count_gap=False):
        """The next sample is only a new baseline (the module rested, or the subscription was lost: then count_gap=True)."""
        if count_gap and self.prev is not None:
            self.pending["gaps"] += 1
            self.gaps_total += 1
        self.prev = None

    def _axis(self, letter):
        return self.pending["axes"].setdefault(letter, _blank(FIELDS))

    def feed(self, t, status, positions, homed=None, released=()):
        cur = {"t": float(t), "status": status, "pos": dict(positions or {}), "homed": dict(homed or {})}
        prev, self.prev = self.prev, cur
        if prev is None:
            return
        dt = cur["t"] - prev["t"]
        if dt <= 0:
            return
        if dt > self.max_gap_s:
            self.pending["gaps"] += 1
            self.gaps_total += 1
            return
        on = powered(prev["status"]) and powered(cur["status"])
        board = self.pending["board"]
        if on:
            board["power_on_s"] += dt
        moved, dxy = False, {}
        for letter, pos in cur["pos"].items():
            before = prev["pos"].get(letter)
            row = self._axis(letter)
            if on and letter not in released:
                row["power_on_s"] += dt
            d = self._step(prev, cur, letter, before, pos, dt)
            if d is None:
                continue
            if d > MOVE_EPS_MM:
                row["moving_s"] += dt
                row["distance_mm"] += d
                board["distance_mm"] += d
                moved = True
                dxy[letter] = (pos - before)
        if moved:
            board["moving_s"] += dt
        if "X" in dxy or "Y" in dxy:
            step = math.hypot(dxy.get("X", 0.0), dxy.get("Y", 0.0))
            board["xy_mm"] += step
            self.xy_total += step

    def _step(self, prev, cur, letter, before, pos, dt):
        """|change| of one axis, or None when this interval says nothing about the axis (no previous value, homing, a jump)."""
        if before is None or pos is None:
            return None
        if bool(prev["homed"].get(letter)) != bool(cur["homed"].get(letter)):
            return None
        d = abs(pos - before)
        if d / dt > MAX_SPEED_MM_S:
            self.pending["jumps"] += 1
            return None
        return d

    def take(self):
        out, self.pending = self.pending, blank_delta()
        return out

    def put_back(self, delta):
        """A flush failed: the delta goes back in front of what accumulated meanwhile."""
        self.pending = add_delta(delta, self.pending)


def add_delta(a, b):
    out = blank_delta()
    for src in (a, b):
        for k, v in src["board"].items():
            out["board"][k] = out["board"].get(k, 0.0) + v
        for letter, row in src["axes"].items():
            dst = out["axes"].setdefault(letter, _blank(FIELDS))
            for k, v in row.items():
                dst[k] = dst.get(k, 0.0) + v
        out["gaps"] += src["gaps"]
        out["jumps"] += src["jumps"]
    return out


def has_content(delta):
    return any(delta["board"].values()) or delta["gaps"] or delta["jumps"] or any(any(r.values()) for r in delta["axes"].values())


def merge_counters(counters, delta, now):
    """The counters of the store with a delta added (pure). `counters` may be {} (nothing stored yet)."""
    out = {"since": counters.get("since") or int(now), "updated": int(now), "gaps": int(counters.get("gaps") or 0) + delta["gaps"],
           "jumps": int(counters.get("jumps") or 0) + delta["jumps"], "board": _blank(BOARD_FIELDS), "axes": {},
           "crosscheck": counters.get("crosscheck")}
    for k in BOARD_FIELDS:
        out["board"][k] = round(float((counters.get("board") or {}).get(k) or 0.0) + delta["board"].get(k, 0.0), 3)
    letters = set(counters.get("axes") or {}) | set(delta["axes"])
    for letter in sorted(letters):
        old, new = (counters.get("axes") or {}).get(letter) or {}, delta["axes"].get(letter) or {}
        out["axes"][letter] = {k: round(float(old.get(k) or 0.0) + new.get(k, 0.0), 3) for k in FIELDS}
    return out
