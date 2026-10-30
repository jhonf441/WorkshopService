"""
Lights and status: the pure logic of the extra features (no DSF, no network,
testable on a PC):

  effect_level      on/off and brightness of an effect at a given time
  night_factor      night dimming schedule
  estimate_ma       power estimate of what is painted on the strip
  StateHistory      the last state changes (kept in memory)
  WorkLightAuto     work light: auto-off after N quiet minutes, auto-on when a
                    job starts
  build_indicator   the payload of the on-screen status indicator
  board_leds_ui     the board LEDs as the page shows them

status_light.py calls these from its loop; handlers/lights.py uses a few.
"""
import math

import lights_config as lc
from messages import M


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------
DOUBLE_CYCLE_S = 1.6
PULSE_CYCLE_S = 2.4


# time value that asks for the frozen, fully lit frame (see effect_level)
UI_FRAME_T = -1.0


def effect_level(effect, t):
    """(brightness 0..255, lit) of an effect at time t (seconds, any clock).
    Blink effects are fully on or fully off; "steady" is always on; "pulse"
    never goes fully dark (it must keep showing the colour).
    t < 0 (UI_FRAME_T): the frozen frame the screens get: every effect is lit at full level, so the
    mirror of the strip does not change with the phase (the screens animate the effect themselves)."""
    if t < 0:
        return 255, True
    if effect in lc.EFFECT_PERIOD:
        lit = int(t / lc.EFFECT_PERIOD[effect]) % 2 == 0
        return (255 if lit else 0), lit
    if effect == "double":
        ph = t % DOUBLE_CYCLE_S
        lit = ph < 0.3 or 0.5 <= ph < 0.8
        return (255 if lit else 0), lit
    if effect == "pulse":
        lvl = 0.2 + 0.8 * (0.5 - 0.5 * math.cos(2 * math.pi * t / PULSE_CYCLE_S))
        return int(255 * lvl), True
    return 255, True


def next_change(effects, t):
    """Seconds until the level of any of these effects changes (t = the same clock as effect_level). Blinks and the
    double flash change at exact edges; a pulse changes all the time, so it asks for 50 ms steps. Used when the Pi
    paints the strip itself: there each frame costs no call to the board, so the effects can be complete."""
    best = 1.0
    for e in effects:
        if e in lc.EFFECT_PERIOD:
            p = lc.EFFECT_PERIOD[e]
            best = min(best, p - (t % p))
        elif e == "double":
            ph = t % DOUBLE_CYCLE_S
            edges = (0.3, 0.5, 0.8, DOUBLE_CYCLE_S)
            best = min(best, next((x - ph for x in edges if x > ph + 1e-6), DOUBLE_CYCLE_S - ph))
        elif e == "pulse":
            best = min(best, 0.05)
    return max(0.02, best)


def needs_fast_tick(effects):
    """Does any of these effects need the loop to run faster than usual?"""
    return any(e in ("blink", "blink_fast", "double", "pulse") for e in effects)


# ---------------------------------------------------------------------------
# Night dimming
# ---------------------------------------------------------------------------
def in_night(night, minutes_now):
    """Is `minutes_now` (minutes since midnight) inside from..to? The window
    may cross midnight (22:00 -> 07:00). from == to means "never"."""
    a = lc.parse_hhmm(night.get("from"), 22 * 60)
    b = lc.parse_hhmm(night.get("to"), 7 * 60)
    if a == b:
        return False
    if a < b:
        return a <= minutes_now < b
    return minutes_now >= a or minutes_now < b


def night_factor(night, minutes_now):
    """1.0 outside the window (or switched off); level/100 inside."""
    if not isinstance(night, dict) or not night.get("enabled"):
        return 1.0
    if not in_night(night, minutes_now):
        return 1.0
    return max(0.01, min(1.0, float(night.get("level", 25)) / 100.0))


def scale_segments(segments, factor):
    """Scales the brightness (P) of every (r,u,b,w,p,n) tramo."""
    if factor >= 0.999:
        return list(segments)
    out = []
    for r, u, b, w, p, n in segments:
        out.append((r, u, b, w, max(1, int(round(p * factor))) if p > 0 else 0, n))
    return out


# ---------------------------------------------------------------------------
# Power estimate
# ---------------------------------------------------------------------------
def estimate_ma(segments, ma_per_channel=20):
    """Estimated current of what is painted: every channel (R,G,B,W) of an
    SK6812 RGBW takes up to ~20 mA at full brightness; P scales all of them.
    tramos = [(r,u,b,w,p,n), ...]. A rough number for sizing the supply, not a
    measurement."""
    total = 0.0
    for r, u, b, w, p, n in segments:
        if n <= 0 or p <= 0:
            continue
        ch = (r + u + b + w) / 255.0
        total += n * ch * ma_per_channel * (p / 255.0)
    return int(round(total))


def worst_case_ma(total_leds, ma_per_channel=20):
    """Every LED at full white on all four channels."""
    return int(total_leds) * 4 * int(ma_per_channel)


# ---------------------------------------------------------------------------
# State history
# ---------------------------------------------------------------------------
class StateHistory:
    """The last `maxlen` changes of the set of active states. Each entry is
    [epoch (int), "id+id" ("" = none, only the mode), mode, status]. The
    duration of an entry is the difference to the next one (the page does it)."""

    def __init__(self, maxlen=50):
        self.maxlen = maxlen
        self.items = []
        self._key = None

    def observe(self, now, ids, mode, status):
        key = ("+".join(ids), str(mode), str(status))
        if key == self._key:
            return False
        self._key = key
        self.items.append([int(now), key[0], key[1], key[2]])
        if len(self.items) > self.maxlen:
            del self.items[: len(self.items) - self.maxlen]
        return True

    def as_list(self):
        return [list(x) for x in self.items]


# ---------------------------------------------------------------------------
# Work light: auto-off / auto-on
# ---------------------------------------------------------------------------
class WorkLightAuto:
    """Decides when to turn the work light off or on by itself.

    - auto-off: the light has been on, and nothing has been going on (no job,
      no live job, machine idle) for `minutes`. The time counts from the later
      of: the light turned on, the last activity. The camera photo light
      (WorkshopVision) switches the light on for a few seconds: that restarts
      the count, so it is never cut short.
    - auto-on: a job starts (file job or live job) and the light is off.
    Returns "off", "on" or None. Time is passed in (seconds), so it is testable.
    """

    def __init__(self):
        self.on_since = None
        self.last_activity = None
        self.was_working = False
        self.light_was_on = False
        self.off_sent = False

    def update(self, now, light_on, working, cfg):
        """cfg = normalised work_light config. Returns "off" | "on" | None."""
        action = None
        if light_on and not self.light_was_on:
            self.on_since = now
            self.off_sent = False
        if not light_on:
            self.on_since = None
        if working or self.last_activity is None:
            self.last_activity = now
        # job start edge
        if working and not self.was_working and not light_on and cfg.get("auto_on_job"):
            action = "on"
            self.off_sent = False
        ao = cfg.get("auto_off") or {}
        if action is None and light_on and ao.get("enabled") and not working and not self.off_sent:
            since = max(now if self.on_since is None else self.on_since, now if self.last_activity is None else self.last_activity)
            if now - since >= int(ao.get("minutes", 30)) * 60:
                action = "off"
                self.off_sent = True
        self.was_working = working
        self.light_was_on = light_on
        return action

    def seconds_left(self, now, light_on, working, cfg):
        """Seconds until the auto-off, or None if it is not going to happen."""
        ao = cfg.get("auto_off") or {}
        if not (light_on and ao.get("enabled")) or working or self.on_since is None:
            return None
        since = max(self.on_since, self.last_activity or self.on_since)
        return max(0, int(int(ao.get("minutes", 30)) * 60 - (now - since)))


# ---------------------------------------------------------------------------
# On-screen indicator
# ---------------------------------------------------------------------------
def build_indicator(detail, mode, mode_hex, status, reason, progress=None, test=None, extra=None):
    """Payload of plugin data `statusIndicator`.

    detail = [{"id", "nombre", "hex", "effect"}, ...] in priority order: the
    states active on the SCREEN output (already filtered by the per-state
    "Screen" checkbox). The first one is the current state; with none, the
    machine mode. The page and the other screens draw a badge from this; the
    effect is animated by the screen itself (CSS), so a blinking state does not
    flood the connection with updates."""
    if detail:
        first = detail[0]
        state = {"id": first["id"], "name": first["name"], "hex": first["hex"], "effect": first.get("effect", "steady")}
    else:
        state = {"id": "base", "name": M("status_light_mode", mode=str(mode)), "hex": mode_hex, "effect": "steady"}
    out = {
        "v": 1,
        "state": state,
        "active": [{"id": d["id"], "name": d["name"], "hex": d["hex"], "effect": d.get("effect", "steady")} for d in detail],
        "mode": str(mode),
        "mode_hex": mode_hex,
        "status": str(status),
        "reason": reason or "",  # a message: the pages show it in their language
        "progress": None if progress is None else round(float(progress), 2),
        "test": test,
    }
    if extra:
        out.update(extra)
    return out


def board_leds_ui(ids, ep, led_fn, thresholds=None):
    """The board LEDs as the page draws them: [{id, hex, on, blink (half
    period in s, 0 = steady), text}]. `led_fn` is status_light.led_placa."""
    out = []
    for ident in ids:
        col, middle, on, txt = led_fn(ident, ep, thresholds) if thresholds is not None else led_fn(ident, ep)
        out.append({
            "id": ident,
            "hex": "#%02x%02x%02x" % (col["r"], col["u"], col["b"]),
            "on": bool(on),
            "blink": round(float(middle), 3) if (middle and on) else 0,
            "text": txt,
        })
    return out
