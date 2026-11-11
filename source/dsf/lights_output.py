"""
Status strip, what leaves the process: M150 to the board (in ONE batch per paint), the Pi's own SPI strips (pi_leds), the plugin data the screens mirror, the traffic wrapper and the log. M150 semantics (empirical): F1 accumulates without transmitting, a call without F transmits the frame and resets the cursor, so the LAST call of any painting sequence goes without F.
"""
import os
import re
import time
import paths
import service_log
import pi_leds
import lights_runtime as lr
from lights_counters import count
from lights_decide import LED_COUNT_DEFAULT, layout, secs_ui, strips_extra_segments, zone_state


# Same file main.py uses (they live in the same directory) -- so the entries of both are interleaved
# in chronological order in a single log.


def log_file(msg):
    service_log.log(msg, "status_light")


# E number of each strip whose output is a pin of the Pi -> that pin (set on every tick from the configuration)
PI_BY_E = {}


def configure_outputs(slc):
    """Which strips have their output on a pin of the Pi (main strip and additional ones) ."""
    wanted, by_e = {}, {}
    candidates = [(slc.get("led_strip", 0), slc.get("output"))] + [(t.get("led_strip"), t.get("output")) for t in (slc.get("strips_extra") or []) if isinstance(t, dict)]
    for e, raw in candidates:
        s = pi_leds.normalize_output(raw)
        try:
            e = int(e)
        except (TypeError, ValueError):
            continue
        if s["kind"] == "pi" and pi_leds.pin_strip_valid(s["pin"]) is None:
            wanted[s["pin"]] = s
            by_e[e] = s["pin"]
    pi_leds.configure_strips(wanted)
    PI_BY_E.clear()
    PI_BY_E.update(by_e)


def send_batch(bridge, cmds):
    """The M150 of one paint go to the board in ONE call (one round trip instead of 3 or 4: measured
    58 ms against 230 ms for 3 codes). A bridge without send_lote (tests, old code) gets them one by one."""
    if not cmds:
        return
    batch = getattr(bridge, "send_batch", None)
    if callable(batch):
        batch(list(cmds))
    else:
        for c in cmds:
            bridge.send(c)


def paint_block(bridge, illum, r, u, b, w, p, lit, led_count, start=10, strip=0):
    # 2026-10-09 (publishing): strip (E) and start index configurable in config.json status_light
    # {"tira": 0, "led_start": 10, "led_count": 10}.
    unlit = led_count - lit

    # Resends the current lighting colour to advance the cursor to LED 20 without transmitting (F1)
    # -- the same trick as daemon.g, needed because M150 no longer accepts a start index (RRF
    # 3.5.1+).
    E = f"E{int(strip)}"
    cmds = []
    if start > 0:
        cmds.append(f'M150 {E} R{illum[0]} U{illum[1]} B{illum[2]} W{illum[3]} P{illum[4]} S{int(start)} F1')

    if lit > 0 and unlit > 0:
        cmds.append(f'M150 {E} R{r} U{u} B{b} W{w} P{p} S{lit} F1')
        cmds.append(f'M150 {E} R0 U0 B0 W0 P0 S{unlit}')
    elif lit > 0:
        cmds.append(f'M150 {E} R{r} U{u} B{b} W{w} P{p} S{lit}')
    else:
        cmds.append(f'M150 {E} R0 U0 B0 W0 P0 S{led_count}')
    send_batch(bridge, cmds)


CONFIG_G = paths.CONFIG_G


DECLARED = {"ts": 0.0, "es": set()}


def e_declared(e):
    """Is strip E<e> in config.g (M950 E<e>)? Undeclared, M150 would give an error on every command: that extra strip is not painted. 10 s cache."""
    if time.time() - DECLARED["ts"] > 10:
        es = set()
        try:
            with open(CONFIG_G, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^\s*M950\s+E(\d+)", line)
                    if m:
                        es.add(int(m.group(1)))
        except OSError:
            pass
        DECLARED.update(ts=time.time(), es=es)
    return int(e) in DECLARED["es"]


def paint_segments(bridge, e, segments):
    pin = PI_BY_E.get(int(e))
    if pin is not None:
        pi_leds.paint(pin, segments)
        return
    cmds = []
    for i, (r, u, b, w, p, n) in enumerate(segments):
        f1 = " F1" if i < len(segments) - 1 else ""
        cmds.append(f"M150 E{int(e)} R{r} U{u} B{b} W{w} P{p} S{n}{f1}")
    send_batch(bridge, cmds)


# Current estimate (mA) of what was last painted on the main strip: the loop
# publishes it in lightsInfo.power (Lights page > Summary)
POWER = {"ma_channel": 20, "ma": 0}


def paint_segment_list(bridge, illum, secs, start=10, strip=0, order=None, disp=None, secs_pub=None, dim=None, secs_mirror=None):
    """segs = [(r,g,b,w,p,count), ...] of the status zone. They are chained with F1 and the last one transmits (M150 with no start index since RRF 3.5.1). start = LEDs of lighting. order "state_first": the status zone goes at the start of the strip and the lighting after (Lights page). dim = (factor, include the work light): night dimming (Lights > Lighting); lowers the brightness (P) of what is sent to the strip. secs_mirror: the same zone as the screens see it (frozen frame, UI_FRAME_T): the mirror published for the pages (statusLightSecs, ledStrip, the power estimate) comes from it, so a blinking effect repaints the strip but does not publish a new value per phase. Without it the mirror is the painted frame."""
    E = f"E{int(strip)}"
    if dim and dim[0] < 0.999:
        f, with_light = dim
        secs = lr.scale_segments(secs, f)
        if secs_mirror is not None:
            secs_mirror = lr.scale_segments(secs_mirror, f)
        if with_light:
            illum = list(illum[:4]) + [max(1, int(round(illum[4] * f))) if illum[4] > 0 else 0]
        if disp:
            disp = {"order": disp["order"], "extra": {k: lr.scale_segments([v], f)[0] for k, v in disp["extra"].items()}}
    blocks = {
        "state": [tuple(s) for s in secs if s[5] > 0],
        "lighting": [(illum[0], illum[1], illum[2], illum[3], illum[4], int(start))] if start > 0 else [],
    }
    if disp:
        # all the zones in the order of the Lights page (extra ones anywhere)
        for zid, t in disp["extra"].items():
            blocks[zid] = [tuple(t)] if t[5] > 0 else []
        ids = disp["order"]
    else:
        ids = ["state", "lighting"] if order == "state_first" else ["lighting", "state"]
    segments = [t for i in ids for t in blocks.get(i, [])]
    cmds = []
    for i, (r, u, b, w, p, n) in enumerate(segments):
        f1 = " F1" if i < len(segments) - 1 else ""
        cmds.append(f"M150 {E} R{r} U{u} B{b} W{w} P{p} S{n}{f1}")
    # A strip whose output is a pin of the Pi gets the whole frame (all its zones, in order) from the Pi and nothing
    # goes to the Duet
    pin = PI_BY_E.get(int(strip))
    if pin is not None:
        pi_leds.paint(pin, segments)
        cmds = []
    send_batch(bridge, cmds)
    ms = secs if secs_mirror is None else secs_mirror
    blocks_m = dict(blocks, state=[tuple(x) for x in ms if x[5] > 0])
    segments_m = [t for i in ids for t in blocks_m.get(i, [])]
    POWER["ma"] = lr.estimate_ma(segments_m, POWER["ma_channel"])
    # The interface copies the strip (sidebar, chip, jog, Lights): EVERYTHING painted in the status
    # zone goes through here and is published at the same moment -- normal state, previews,
    # end-of-job effect -- so screen and LEDs always stay synchronised.
    try:
        bridge.set_status("statusLightSecs", secs_ui(ms if secs_pub is None else secs_pub))
    except Exception:
        pass
    # The COMPLETE strip (all the zones in order, 2026-10-10): so the interface sees the lighting
    # switch on/off and the real number of LEDs, also when the lighting takes the status LEDs.
    since = 0
    for i in ids:
        if i == "state":
            break
        since += sum(t[5] for t in blocks.get(i, []))
    publish_strip(bridge, segments_m, since, sum(t[5] for t in blocks_m["state"]))


def paint_state(bridge, illum, secs, slc, with_extra=True, dim=None, secs_mirror=None):
    """Paints the status zone where the Lights page chose it (zone_state) and publishes it for the screens (statusLightSecs = that zone). With the state on another strip or on none, the status LEDs of the main strip stay off. with_extra=False: the extra strip is painted by the loop (extra_strips_stretches with segs_state, only when it changes)."""
    type_name, e, _, _, _ = zone_state(slc)
    ini, led_strip, order, disp = slc.get("led_start", 10), slc.get("led_strip", 0), slc.get("order"), layout(slc)
    if type_name == "main":
        paint_segment_list(bridge, illum, secs, ini, led_strip, order, disp, dim=dim, secs_mirror=secs_mirror)
        return
    off = [(0, 0, 0, 0, 0, slc.get("led_count", LED_COUNT_DEFAULT))]
    paint_segment_list(bridge, illum, off, ini, led_strip, order, disp, secs_pub=secs if secs_mirror is None else secs_mirror, dim=dim)
    if type_name == "led_strip" and with_extra and e_declared(e):
        for e_, segments_ in strips_extra_segments(slc, secs):
            if e_ == e:
                paint_segments(bridge, e_, segments_)


# Last ledStrip published (2026-10-11): the board's status strip travels inside ledStrip
# ("stripState") so as not to declare another plugin data key (plugin.json "data" +
# WorkshopService.json); when only it changes ledStrip is published again with the main strip that
# was already there.
PUB_STRIP = {"secs": [], "state": [0, 0], "strip_state": None}


def publish_strip(bridge, segments, state_since=0, state_n=0):
    """ledStrip = {segs: [[hex, level, n], ...] of the WHOLE main strip in order from the connector, estado: [first LED, count] of the status zone, stripState: virtual status strip of the board (or absent)}. stretches = [(r,g,b,w,p,n), ...]."""
    PUB_STRIP["secs"] = secs_ui(segments)
    PUB_STRIP["state"] = [int(state_since), int(state_n)]
    send_led_strip(bridge)


def send_led_strip(bridge):
    v = {"secs": PUB_STRIP["secs"], "state": PUB_STRIP["state"]}
    if PUB_STRIP["strip_state"] is not None:
        v["stripState"] = PUB_STRIP["strip_state"]
    try:
        bridge.set_status("ledStrip", v)
    except Exception:
        pass


def publish_strip_state(bridge, te):
    """Publishes (or removes, te=None) the board's virtual status strip."""
    PUB_STRIP["strip_state"] = te
    send_led_strip(bridge)


def effect_end_job(bridge, config, illum):
    """Blink of the status zone when a job ends (Lights page, status_light.efectos.end_job)."""
    slc = config.get("status_light", {})
    ft = (slc.get("effects") or {}).get("end_job") or {}
    if not ft.get("active", True):
        return
    c = ft.get("color") or {"r": 0, "u": 255, "b": 0, "w": 0}
    n = zone_state(slc)[4]
    # start dark: when the state that was showing is the same colour as the notice (the green of a live
    # job) the first flash melted into it and only N - 1 flashes were seen
    paint_state(bridge, illum, [(0, 0, 0, 0, 0, n)], slc)
    time.sleep(0.25)
    for _ in range(max(1, min(10, int(ft.get("times", 3))))):
        paint_state(bridge, illum, [(c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0), 255, n)], slc)
        time.sleep(0.3)
        paint_state(bridge, illum, [(0, 0, 0, 0, 0, n)], slc)
        time.sleep(0.25)


class WithoutM150:
    """Virtual strip: the same bridge, but without sending M150 to the board (everything else, including publishing the state for the screens, stays the same)."""

    def __init__(self, real):
        self._real = real

    def send(self, cmd, *a, **k):
        if str(cmd).lstrip().upper().startswith("M150"):
            return ""
        return self._real.send(cmd, *a, **k)

    def send_batch(self, cmds):
        rest = [c for c in cmds if not str(c).lstrip().upper().startswith("M150")]
        return self._real.send_batch(rest) if rest else ""

    def __getattr__(self, label):
        return getattr(self._real, label)


def power_off_state(bridge, illum, config):
    """Rest (WorkshopLights stopped, service_modules.py): it switches off the status zone (the lighting stays as it was) and leaves the screens without a strip."""
    slc = config.get("status_light", {}) or {}
    n = slc.get("led_count", LED_COUNT_DEFAULT)
    off = [(0, 0, 0, 0, 0, n)]
    try:
        paint_state(bridge, illum, off, slc, with_extra=True)
        for e_, segments_ in strips_extra_segments(slc, None):
            if e_declared(e_):
                paint_segments(bridge, e_, segments_)
    except Exception as e:
        log_file(f"idle: could not turn the status zone off ({e})")
    publish_strip_state(bridge, None)
    for k, v in (("statusLightSecs", []), ("statusLightActive", []), ("statusLightModes", {}),
                 ("statusIndicator", None), ("lightsInfo", None),
                 ("statusLightColor", "#616161"), ("statusLightPiActive", False),
                 ("statusLightText", "")):
        try:
            bridge.set_status(k, v)
        except Exception:
            pass



class CountedBridge:
    """The real bridge with its traffic counted (send = G-code to the board,
    set_status = plugin data)."""

    def __init__(self, real):
        self._real = real

    def send(self, cmd, *a, **k):
        count("commands")
        return self._real.send(cmd, *a, **k)

    def send_batch(self, cmds):
        """Several codes in one call to the board (the counter counts the codes, not the call)."""
        for _ in cmds:
            count("commands")
        return self._real.send(chr(10).join(cmds))

    def set_status(self, k, v):
        count("publishes")
        return self._real.set_status(k, v)

    def __getattr__(self, label):
        return getattr(self._real, label)
