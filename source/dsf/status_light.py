"""
Paints the WHOLE LED strip from the Pi: the status zone (mode, states, progress bar), the lighting and the extra zones, in the order of the Lights page. It is the ONLY one that paints (2026-10-10): sys/daemon.g no longer sends M150 and the light macros (lighton/lightoff/statusledoff) only change their variable; this loop sees the change and repaints.

Since 2026-10-12 this module does NOT poll DSF: it reads the shared subscription model of machine_state.py (in memory, global.** included) and decides again only when that model changes (machine_state.on_change) or, while an animation needs frames, on a short timer that needs no IPC. It sends M150 only when the frame really changed and publishes plugin data only when a payload changed. Counters of what it still asks (ipc_stats) go to servicesInternal.luces. Before: one evaluate_expression every 0.4 s (2.5 calls/s) plus the RS485 reads (about 1 call/s).

If this process dies, the strip keeps the last frame (nobody else paints, at the user's request: a single owner of the strip). On reconnecting, it repaints everything at once.

"""
import paths
import os
import time

import heartbeats
import lights_config as lc
import lights_runtime as lr
import service_modules
import pi_leds
import viewers

from dsf.connections import CommandConnection
from messages import M, J

LED_COUNT_DEFAULT = 10
POLL_INTERVAL_S = 0.4

# Colours of the special states (2026-10-09, Lights page): they can be changed in config.json
# status_light.state_colors; these are the usual ones (the same as sys/daemon.g).
STATE_COLORS_DEFAULT = {
    "stop": {"r": 255, "u": 0, "b": 0, "w": 0},
    "paused": {"r": 255, "u": 120, "b": 0, "w": 0},
    "cancelling": {"r": 255, "u": 0, "b": 255, "w": 0},  # magenta (2026-10-10: the reddish orange was confused with the stop)
    "busy": {"r": 255, "u": 255, "b": 255, "w": 0},
}

# handlers/lights.py (C"probar") paints the strip by hand for a few seconds to count LEDs: while
# time.time() < PAUSE_UNTIL this loop does not paint, and when it ends it repaints everything.
PAUSE_UNTIL = 0.0

# (2026-10-10) There is no longer a heartbeat for sys/daemon.g: the strip is painted ONLY by this
# service. If it dies, the strip stays still and on returning everything is repainted. Failures of
# WorkshopRS485 (if installed): a simple number published by that plugin. Warnings (devices without
# an axis with an alarm): WorkshopRS485 1.4.0+. Separate query: if the key does not exist yet, only
# the warnings stay at 0 (not the failures).
RS485_IDS = ("WorkshopRS485", "WorkshopRS485")  # 2026-10-10: the Ids become English


def _rs_discover(status):
    """(Id, has_faults, has_warnings) of the RS485 plugin that publishes data in the object model, or (None, False, False). The model is looked at instead of trying expressions: each EvaluateExpression with a field that does not exist leaves "Failed to execute EvaluateExpression" in DCS's log (2026-10-12: with the old Id WorkshopRS485 it appeared in a loop)."""
    plugins = (status or {}).get("plugins") or {}
    for rid in RS485_IDS:
        rs = ((plugins.get(rid) or {}).get("data") or {}).get("rs485")
        if isinstance(rs, dict):
            return rid, "faults" in rs, "notices" in rs
    return None, False, False


# Same file main.py uses (they live in the same directory) -- so the entries of both are interleaved
# in chronological order in a single log.
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop-service.log")


def log_file(msg):
    """Routine connection/polling diagnosis -- only to the local file, never as a pop-up notification in DWC (see main.py:log_file)."""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [status_light] {msg}\n")
    except Exception:
        pass


def _color_for(cfg, selected_mode):
    colors = cfg.get("mode_colors", {})
    return dict(colors.get(selected_mode, colors.get("FFF", {"r": 0, "u": 0, "b": 0, "w": 0})))


def compute_state(config, selected_mode, disabled, illum, status, job_file_position, job_file_size):
    """Replicates the logic of sys/daemon.g. Returns (r,g,b,w,p,litCount,text,ui_color). ui_color is None except when the real colour that is PAINTED should not be the one SHOWN in the plugin's UI -- see the "disabled" case below: the strip paints the real colour of "Light" (illum), but the UI reports a fixed yellow so the "manual/lighting" state is recognised at a glance without being confused with whatever colour "Light" has at that moment (e.g. lighton.g's white+blue ceiling looks like CNC's solid blue). Confirmed by the user 2026-10-06: the yellow is only for the interface, the strip must keep showing the real lighting colour.
    """
    cfg = config.get("status_light", {})
    led_count = cfg.get("led_count", LED_COUNT_DEFAULT)

    r = u = b = w = 0
    p = 255
    lit = led_count
    text = ""
    ui_color = None

    if disabled:
        # "Light" takes these 17 as well while the automatic is off: they are painted with the REAL
        # lighting colour (illum = lightZoneColor), not a fixed black nor an invented colour.
        r, u, b, w, p = illum[0], illum[1], illum[2], illum[3], illum[4]
        if r == 0 and u == 0 and b == 0 and w == 0:
            # "Light" is really off (illum in {0,0,0,0,0}) -- do not show "lighting"/yellow if
            # nothing is lit. Reported by the user 2026-10-07: before it said "Manual (lighting)" in
            # yellow ALWAYS when the automatic was off, whatever Light itself was doing. ui_color is
            # left None (default) so the real painted colour (black) is shown, not an invented
            # colour.
            text = M("status_light_manual_off")
        else:
            text = M("status_light_manual_lighting")
            # 2026-10-09: a fixed yellow is NO longer reported; the interface shows the real colour
            # of the lighting, like the strip.
    else:
        base = _color_for(cfg, selected_mode)
        r, u, b, w = base.get("r", 0), base.get("u", 0), base.get("b", 0), base.get("w", 0)

        states = dict(STATE_COLORS_DEFAULT)
        states.update(cfg.get("state_colors") or {})

        def _of(label):
            c = states.get(label) or STATE_COLORS_DEFAULT[label]
            return c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0)

        if status == "halted":
            r, u, b, w = _of("stop")
            text = M("lights_config_emergency_stop")
        elif status in ("paused", "pausing", "resuming"):
            r, u, b, w = _of("paused")
            text = M("lights_config_paused")
        elif status == "cancelling":
            r, u, b, w = _of("cancelling")
            text = M("lights_config_cancelling")
        elif status in ("busy", "changingTool"):
            r, u, b, w = _of("busy")
            text = M("lights_config_busy_homing_macro")
        elif status in ("processing", "simulating"):
            fraction = 0.0
            if job_file_size and job_file_size > 0:
                fraction = (job_file_position or 0) / job_file_size
            lit = min(led_count, int(fraction * led_count))
            pct = round(fraction * 100)
            text = M("status_light_simulating_pct_mode" if status == "simulating" else "status_light_working_pct_mode", pct=pct, mode=selected_mode)
        else:
            p = cfg.get("idle_brightness", 40)
            text = M("status_light_idle_mode", mode=selected_mode)

    return r, u, b, w, p, lit, text, ui_color


# E number of each strip whose output is a pin of the Pi -> that pin (set on every tick from the configuration)
_PI_BY_E = {}


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
    _PI_BY_E.clear()
    _PI_BY_E.update(by_e)


def pi_paints(slc):
    """True when the strip that shows the status zone has its output on a pin of the Pi: there the effects are complete
    (a paint costs no call to the board)."""
    try:
        type_name, e, _, _, _ = zone_state(slc)
    except Exception:
        return False
    if type_name == "main":
        s = (slc or {}).get("output")
    elif type_name == "led_strip":
        s = next((t.get("output") for t in ((slc or {}).get("strips_extra") or []) if isinstance(t, dict) and str(t.get("led_strip")) == str(e)), None)
    else:
        return False
    return isinstance(s, dict) and s.get("kind") == "pi"


def _send_batch(bridge, cmds):
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


def _paint(bridge, illum, r, u, b, w, p, lit, led_count, start=10, strip=0):
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
    _send_batch(bridge, cmds)


# ---------------------------------------------------------------------------
# Simultaneous states (2026-10-09, Lights page > States)
# ---------------------------------------------------------------------------
# Known states, in order of priority. Each one can be active or not and has its colour (config.json
# status_light.estados). When there are several at once, status_light.combinar.modo decides how they
# look:
# "prioridad": only the most important (as always)
# "turnos": they alternate, each one turn_s seconds
# "dividir": the status zone is split into stretches, one per state
# The emergency stop always takes the whole zone.
# The catalogue lives in lights_config.STATES (id, text, colour, active by default, type, effect).
# Here remains the usual list for whoever imports it: (id, text, default colour, active by default),
# in order of importance.
# Colour notes (2026-10-10): palette without repeated colours (before Laser = stop, cancelling ~
# stop, FFF ~ live job, CNC ~ RS485 warning); the Lights page warns if two colours in use look
# alike. The switched-off supply (M81, state.status "off") leaves motors and laser without power
# even if the board is alive; crash / no-limits jog / risk take the whole zone (the pattern tells
# them apart from the stop, which is steady).
STATES_DEF = [(s[0], s[1], s[2], s[3]) for s in lc.STATES]
_TEXT = {e[0]: e[1] for e in STATES_DEF}


def _state_cfg(slc, ident):
    est = (slc.get("states") or {}).get(ident) or {}
    old = (slc.get("state_colors") or {}).get(ident)
    default = next(e for e in STATES_DEF if e[0] == ident)
    color = est.get("color") or old or default[2]
    is_active = True if ident == "stop" else est.get("active", default[3])
    return is_active, color


def _sanitize(slc):
    """Numbers of the strip config always valid integers: an odd value (e.g. "" from a field deleted on the page) must not stop the painting."""
    for k, d, lo in (("led_count", LED_COUNT_DEFAULT, 1), ("led_start", 10, 0), ("led_strip", 0, 0)):
        try:
            slc[k] = max(lo, int(round(float(slc.get(k, d)))))
        except (TypeError, ValueError):
            slc[k] = d


CONFIG_G = paths.CONFIG_G
_declared = {"ts": 0.0, "es": set()}


def _e_declared(e):
    """Is strip E<e> in config.g (M950 E<e>)? Undeclared, M150 would give an error on every command: that extra strip is not painted. 10 s cache."""
    import re
    if time.time() - _declared["ts"] > 10:
        es = set()
        try:
            with open(CONFIG_G, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^\s*M950\s+E(\d+)", line)
                    if m:
                        es.add(int(m.group(1)))
        except OSError:
            pass
        _declared.update(ts=time.time(), es=es)
    return int(e) in _declared["es"]


def zone_state(slc):
    """Where the state is painted (Lights page, status_light.zone_state, 2026-10-10 "with several strips or zones choose which one is the state one"):
      "principal"      the status zone of the main strip (as always)
      "<strip>:<zone>"  a zone of an extra strip (ids of extra_strips)
      "ninguna"        no LED: the state is only seen on the screens
    Returns (type, E, strip id, zone id, number of LEDs). A zone that no longer exists goes back to "principal". With the virtual strip there are no extra strips (2026-10-11): a zone of another strip goes back to "principal"."""
    z = str(slc.get("zone_state") or "main")
    if z == "none":
        return "none", None, None, None, slc.get("led_count", LED_COUNT_DEFAULT)
    if ":" in z and not slc.get("virtual"):
        tid, _, zid = z.partition(":")
        for t in (slc.get("strips_extra") or []):
            if not isinstance(t, dict) or str(t.get("id")) != tid:
                continue
            for zz in (t.get("zones") or []):
                if isinstance(zz, dict) and str(zz.get("id")) == zid:
                    try:
                        return "led_strip", int(t.get("led_strip")), tid, zid, max(1, int(zz.get("n", 1)))
                    except (TypeError, ValueError):
                        break
    return "main", None, None, None, slc.get("led_count", LED_COUNT_DEFAULT)


def config_state(config):
    """config with led_count = LEDs of the chosen status zone: compute() builds the progress bar, split, etc. for THAT zone."""
    slc = config.get("status_light") or {}
    n = zone_state(slc)[4]
    if n == slc.get("led_count", LED_COUNT_DEFAULT):
        return config
    c2 = dict(config)
    c2["status_light"] = dict(slc, led_count=n)
    return c2


def strips_extra_segments(slc, secs_state=None):
    """Extra strips of the Lights page: [(E, [(r,g,b,w,p,n), ...])] with their zones in order (switched off in black). If the status zone is in one of them, that zone carries segs_state (the state's stretches)."""
    type_name, _, tid_e, zid_e, _ = zone_state(slc)
    out = []
    if slc.get("virtual"):
        # 2026-10-11 ("if the strip is virtual, limit it to just one"): a virtual strip is a single
        # one; the saved extra ones are ignored
        return out
    for t in (slc.get("strips_extra") or []):
        try:
            e = int(t.get("led_strip"))
        except (TypeError, ValueError, AttributeError):
            continue
        segments = []
        for z in (t.get("zones") or []):
            try:
                n = max(0, int(z.get("n", 0)))
            except (TypeError, ValueError, AttributeError):
                continue
            if type_name == "led_strip" and secs_state is not None and str(t.get("id")) == tid_e and str(z.get("id")) == zid_e:
                segments += [tuple(x) for x in secs_state if x[5] > 0]
                continue
            c = z.get("color") or {}
            if z.get("on", True):
                segments.append((c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0), c.get("p", 255), n))
            else:
                segments.append((0, 0, 0, 0, 0, n))
        segments = [x for x in segments if x[5] > 0]
        if segments:
            out.append((e, segments))
    return out


def _paint_segments(bridge, e, segments):
    pin = _PI_BY_E.get(int(e))
    if pin is not None:
        pi_leds.paint(pin, segments)
        return
    cmds = []
    for i, (r, u, b, w, p, n) in enumerate(segments):
        f1 = " F1" if i < len(segments) - 1 else ""
        cmds.append(f"M150 E{int(e)} R{r} U{u} B{b} W{w} P{p} S{n}{f1}")
    _send_batch(bridge, cmds)


def layout(slc):
    """Order of the zones on the strip and the stretch of each extra zone (Lights page): {"orden": ["estado", "ilum", "z1", ...], "extra": {id: (r,g,b,w,p,n)}}. The switched-off extra ones go in black. With no saved order: state/lighting according to "orden" and the extra ones at the end."""
    extra, ids = {}, []
    for z in (slc.get("zones_extra") or []):
        try:
            n = max(0, int(z.get("n", 0)))
            zid = str(z.get("id") or "z%d" % (len(ids) + 1))
        except (TypeError, ValueError, AttributeError):
            continue
        c = z.get("color") or {}
        if z.get("on", True):
            extra[zid] = (c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0), c.get("p", 255), n)
        else:
            extra[zid] = (0, 0, 0, 0, 0, n)
        ids.append(zid)
    all_items = ["state", "lighting"] + ids
    order = [i for i in (slc.get("order_zones") or []) if i in all_items]
    if not order or len(set(order)) != len(order):
        order = ["state", "lighting"] if slc.get("order") == "state_first" else ["lighting", "state"]
    order += [i for i in all_items if i not in order]
    return {"order": order, "extra": extra}


# Current estimate (mA) of what was last painted on the main strip: the loop
# publishes it in lightsInfo.power (Lights page > Summary)
_POWER = {"ma_channel": 20, "ma": 0}


def _paint_segment_list(bridge, illum, secs, start=10, strip=0, order=None, disp=None, secs_pub=None, dim=None, secs_mirror=None):
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
    pin = _PI_BY_E.get(int(strip))
    if pin is not None:
        pi_leds.paint(pin, segments)
        cmds = []
    _send_batch(bridge, cmds)
    ms = secs if secs_mirror is None else secs_mirror
    blocks_m = dict(blocks, state=[tuple(x) for x in ms if x[5] > 0])
    segments_m = [t for i in ids for t in blocks_m.get(i, [])]
    _POWER["ma"] = lr.estimate_ma(segments_m, _POWER["ma_channel"])
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
        _paint_segment_list(bridge, illum, secs, ini, led_strip, order, disp, dim=dim, secs_mirror=secs_mirror)
        return
    off = [(0, 0, 0, 0, 0, slc.get("led_count", LED_COUNT_DEFAULT))]
    _paint_segment_list(bridge, illum, off, ini, led_strip, order, disp, secs_pub=secs if secs_mirror is None else secs_mirror, dim=dim)
    if type_name == "led_strip" and with_extra and _e_declared(e):
        for e_, segments_ in strips_extra_segments(slc, secs):
            if e_ == e:
                _paint_segments(bridge, e_, segments_)


# Last ledStrip published (2026-10-11): the board's status strip travels inside ledStrip
# ("stripState") so as not to declare another plugin data key (plugin.json "data" +
# WorkshopService.json); when only it changes ledStrip is published again with the main strip that
# was already there.
_pub_strip = {"secs": [], "state": [0, 0], "strip_state": None}


def publish_strip(bridge, segments, state_since=0, state_n=0):
    """ledStrip = {segs: [[hex, level, n], ...] of the WHOLE main strip in order from the connector, estado: [first LED, count] of the status zone, stripState: virtual status strip of the board (or absent)}. stretches = [(r,g,b,w,p,n), ...]."""
    _pub_strip["secs"] = secs_ui(segments)
    _pub_strip["state"] = [int(state_since), int(state_n)]
    _send_led_strip(bridge)


def _send_led_strip(bridge):
    v = {"secs": _pub_strip["secs"], "state": _pub_strip["state"]}
    if _pub_strip["strip_state"] is not None:
        v["stripState"] = _pub_strip["strip_state"]
    try:
        bridge.set_status("ledStrip", v)
    except Exception:
        pass


def publish_strip_state(bridge, te):
    """Publishes (or removes, te=None) the board's virtual status strip."""
    _pub_strip["strip_state"] = te
    _send_led_strip(bridge)


def _hex(r, u, b, w=0):
    # the white channel (W) lightens the colour, as seen on the RGBW strip (e.g. blue lighting +
    # white = light blue, not pure blue)
    def c(v):
        return min(255, int(v) + int(int(w) * 0.7))
    if not (r or u or b) and w:
        return "#ffffff"
    return f"#{c(r):02x}{c(u):02x}{c(b):02x}"


def secs_ui(secs):
    """The stretches as they are painted in the status zone, for the interface to copy them: [[hex, level 0..1, count], ...] (level 0 = off)."""
    out = []
    for r, u, b, w, p, n in secs:
        if n <= 0:
            continue
        level = 0 if not (r or u or b or w) else round(max(0, min(255, p)) / 255, 2)
        out.append([_hex(r, u, b, w), level, int(n)])
    return out


def _jog_free_active():
    try:
        import jog_move

        return jog_move.free_active()
    except Exception:
        return False


def _jog_free_color():
    try:
        import jog_move

        return jog_move.free_color()
    except Exception:
        return None


def _jog_alert_limits():
    try:
        import jog_move

        return jog_move.alert_limits()
    except Exception:
        return False


def _in_live(v):
    """liveJob is {active, name, since} (or None)."""
    if isinstance(v, dict):
        return bool(v.get("active"))
    return bool(v)


# 2026-10-13: while a job runs (file or live) the strip and the board LEDs keep colours but not effects:
# every blink phase is one M150 for the Duet (measured ~74 per minute, each one slow when the Duet is busy).
# The states that must call attention keep their effect. The screens animate by themselves (no cost).
EFFECTS_IN_JOB = ("without_effects", "with_effects")
ALWAYS_WITH_EFFECT = ("stop", "crash", "risk", "jog_free", "cancelling", "paused")
MIN_BETWEEN_PAINTED_JOB_S = 0.5   # at most 2 paints per second during a job
MAX_BETWEEN_PAINTED_SLOW_S = 3.0     # and slower still when the Duet takes long to answer a paint


# Effects that need a new frame many times a second: on the Duet each frame is a set of codes to the board, so the
# strip of the Duet does not show them (it stays steady); when the Pi paints the strip they are complete.
DUET_WITHOUT_EFFECT = ("double", "pulse")


def effects_frozen(slc, status, extras):
    """True: no effects on the strip / board LEDs now (a job is running and the user did not ask for them).
    Never when the Pi paints: there the effects are complete."""
    if pi_paints(slc):
        return False
    if (slc or {}).get("effects_in_job", "without_effects") != "without_effects":
        return False
    return status in ("processing", "simulating") or bool((extras or {}).get("in_live"))


def compute(config, mode, disabled, illum, status, file_pos, file_size, extras, info=None, output="strip", current_time=None):
    """Returns (segments, text, ui_color). extras: laser_pwm, homed, aire,
    in_live, rs485_faults, rs485_notices, pi_hot, motors_loose,
    in_live_still, shutdown_dirty. If info (a dict) is given, it receives
    info["activos"] = the active states [(id, color)] for the interface and
    info["detalle"] = the same with their effect and outputs.

    salida: which output is being computed: "strip" (the physical strip),
    "screen" (the on-screen indicator) or "board" (the board LEDs). Every state
    says on which of them it is shown (the Strip / Screen / Board checkboxes
    of the Lights page).
    ahora: clock (seconds) used by the effects; time.monotonic() by default."""
    slc = config.get("status_light", {})
    n = slc.get("led_count", LED_COUNT_DEFAULT)
    t = time.monotonic() if current_time is None else current_time
    r, u, b, w, p, lit, text, ui_color = compute_state(config, mode, disabled, illum, status, file_pos, file_size)
    # 2026-10-10: the no-limits jog (and a crash) show in the zone even if the automatic status
    # lights are off, unless it is switched off in Lights (effects.free_jog_always).
    forced = disabled and (slc.get("effects") or {}).get("jog_free_always", True) and bool(extras.get("jog_free") or extras.get("crash") or extras.get("risk"))
    if forced:
        disabled = False
    if disabled:
        return [(r, u, b, w, p, lit), (0, 0, 0, 0, 0, n - lit)], text, ui_color

    active = []
    detail = {}
    freeze = output != "screen" and effects_frozen(slc, status, extras)

    def put(ident, cond):
        if cond:
            f = lc.state_full(slc, ident)
            if freeze and ident not in ALWAYS_WITH_EFFECT and f.get("effect") != "steady":
                f = dict(f, effect="steady")
            if output != "screen" and f.get("effect") in DUET_WITHOUT_EFFECT and not pi_paints(slc):
                f = dict(f, effect="steady")
            if f["active"] and f["outputs"].get(output, True):
                active.append((ident, f["color"]))
                detail[ident] = f

    if status == "halted" and lc.state_full(slc, "stop")["outputs"].get(output, True):
        f = lc.state_full(slc, "stop")
        col = f["color"]
        if info is not None:
            info["activeList"] = [("stop", col)]
            info["detail"] = [dict(f, id="stop", color=col)]
        return [(col["r"], col["u"], col["b"], col.get("w", 0), 255, n)], _TEXT["stop"], None
    # 2026-10-10 ("if the jog is red, the status LEDs must take that state and colour while it is
    # active"): crash and no-limits jog take the WHOLE zone, whatever the combine mode. The
    # no-limits jog uses the colour chosen in the jog (extras["jog_free_color"]).
    for ident in ("crash", "risk", "jog_free"):
        if not extras.get(ident):
            continue
        f = lc.state_full(slc, ident)
        if not f["outputs"].get(output, True):
            continue
        if not f["active"] and not forced:  # forced: it was asked to always see it
            continue
        col = f["color"]
        if ident == "jog_free" and extras.get("jog_free_color"):
            col = extras["jog_free_color"]
        if info is not None:
            info["activeList"] = [(ident, col)]
            info["detail"] = [dict(f, id=ident, color=col)]
        level, switched_on = lr.effect_level(f["effect"], t)
        if not switched_on:
            return [(0, 0, 0, 0, 0, n)], _TEXT[ident], None
        return [(col["r"], col["u"], col["b"], col.get("w", 0), level, n)], _TEXT[ident], None
    # supply off: the most important combinable state (priority: it wins; split: the biggest
    # stretch; turns: a turn like the others)
    in_live = bool(extras.get("in_live"))
    put("psu_off", status == "off")
    put("cancelling", status == "cancelling")
    put("paused", status in ("paused", "pausing", "resuming"))
    put("rs485", (extras.get("rs485_faults") or 0) > 0)
    put("rs485_notice", (extras.get("rs485_notices") or 0) > 0)
    put("pi_hot", bool(extras.get("pi_hot")))
    # A live job keeps the machine "busy" all the time (they are movements that arrive through the
    # bridge): that "busy" IS the job, so it does not cover the live job's green (reported
    # 2026-10-09).
    put("busy", status in ("busy", "changingTool") and not in_live)
    put("laser", (extras.get("laser_pwm") or 0) > 0)
    put("air", bool(extras.get("air")))
    still = bool(extras.get("in_live_still"))
    put("in_live", in_live and status not in ("processing", "simulating") and not still)
    put("live_quiet", in_live and still)
    put("without_homing", not extras.get("homed", True) and status == "idle")
    put("motors_released", bool(extras.get("motors_loose")))
    put("unclean_shutdown", bool(extras.get("shutdown_dirty")))
    # priority chosen in the page (the fixed states above never move)
    order = {i: k for k, i in enumerate(lc.state_order(slc))}
    active.sort(key=lambda a: order.get(a[0], 99))
    if info is not None:
        info["activeList"] = list(active)
        info["detail"] = [dict(detail[i], id=i, color=c) for i, c in active]

    # base: colour of the mode (progress bar if there is a job from a file)
    mc = _color_for(slc, mode)
    working = status in ("processing", "simulating")
    base_p = 255 if working else slc.get("idle_brightness", 40)
    frac = (file_pos or 0) / file_size if working and file_size else (1.0 if not working else 0.0)
    base_txt = text if working else M("status_light_idle_mode", mode=mode)

    def segment(ident, col, cant, blink=True):
        # every state has its own effect (steady, slow / medium / fast blink,
        # double flash, pulse); the old ones keep theirs: paused slow, crash fast
        level, switched_on = lr.effect_level(detail[ident]["effect"], t) if blink and ident in detail else (255, True)
        if not switched_on:
            return [(0, 0, 0, 0, 0, cant)]
        return [(col["r"], col["u"], col["b"], col.get("w", 0), level, cant)]

    def segment_base(cant, full=False):
        on = min(cant, int(round(frac * cant)))
        # full (split mode): the zone ALWAYS stays all lit. The mode's stretch is the last and the
        # smallest: with the resting brightness (40) it looked off on the strip (reported
        # 2026-10-09), so in split it goes with visible brightness and what is missing of the
        # progress, dim.
        p_on = max(base_p, 120) if full else base_p
        rest_p = max(60, int(base_p * 0.35)) if full else 0
        rest = (mc.get("r", 0), mc.get("u", 0), mc.get("b", 0), mc.get("w", 0), rest_p, cant - on) if full else (0, 0, 0, 0, 0, cant - on)
        return [(mc.get("r", 0), mc.get("u", 0), mc.get("b", 0), mc.get("w", 0), p_on, on), rest]

    if not active:
        return segment_base(n), base_txt, None
    comb = slc.get("combine") or {}
    kind = comb.get("mode", "priority")
    names = J([_TEXT[i] for i, _ in active])
    # A zone of n LEDs shows at most n - 1 states at once in "dividir" (the last LED is the mode
    # colour). With more states active than fit: "turnos" (default) rotates all of them, nothing is
    # lost; "ocultar" keeps the most important ones and reports the rest in info["capacidad"].
    fits = max(1, n - 1)
    rotating = False
    if kind == "split" and len(active) > fits and comb.get("si_no_fit", "turns") == "turns":
        kind = "turns"
        rotating = True
    if kind == "turns" and freeze:
        # a job is running and the user did not ask for effects: the turns are an animation too, so the strip and
        # the board LEDs show the states split in zones (or only the first one if they do not fit)
        kind = "split" if len(active) <= fits else "priority"
        rotating = False
    if info is not None:
        info["capacidad"] = {"leds": n, "fits": fits, "activeList": len(active), "rotating": rotating,
                             "hidden": [i for i, _ in active[fits:]] if kind == "split" else []}
    if kind == "turns":
        items = active + [("base", None)]
        turn = max(0.5, float(comb.get("turn_s", 1.5)))
        ident, col = items[0 if t < 0 else int(t / turn) % len(items)]
        if ident == "base":
            return segment_base(n), M("status_light_names_in_turns", names=names), None
        return segment(ident, col, n), M("status_light_names_in_turns", names=names), None
    if kind == "split":
        # The whole zone stays lit and the most important states (first in the priority) receive
        # more LEDs: weight k, k-1, ..., and the mode/base 1.
        items = active[: max(1, n - 1)] + [("base", None)]
        k = len(items)
        weights = [k - i for i in range(k - 1)] + [1]
        total = float(sum(weights))
        raw = [n * w / total for w in weights]
        length = [max(1, int(c)) for c in raw]
        # mayor resto primero hasta completar exactamente n LEDs
        order_rest = sorted(range(k), key=lambda i: raw[i] - int(raw[i]), reverse=True)
        j = 0
        while sum(length) < n:
            length[order_rest[j % k]] += 1
            j += 1
        while sum(length) > n:
            i_max = max(range(k), key=lambda i: length[i])
            length[i_max] -= 1
        secs = []
        for (ident, col), cant in zip(items, length):
            secs += segment_base(cant, full=True) if ident == "base" else segment(ident, col, cant)
        return secs, f"{names} + {base_txt}", None
    # prioridad
    ident, col = active[0]
    return segment(ident, col, n), _TEXT[ident], None


# ---------------------------------------------------------------------------
# Board LEDs (2026-10-11, Lights page > "Board LEDs at the end")
# ---------------------------------------------------------------------------
# Copy of the LEDs the Duet 3 6HC has soldered on the board, with the same colour and the same
# behaviour. Colours: bill of materials of Duet3D's schematics
# (github.com/Duet3D/Duet3-Mainboard-6HC v1.02, Power.kicad_sch and Processor.kicad_sch): V_FUSED
# blue (150060BS75000), 12V+ amber (150060AS75000), 5V+ red (150060RS75000), 3.3V green
# (150060VS75000), STATUS red, ACT green. The EXP3HC / EXP1XD / TOOL1LC expansions use the same
# colours (VIN blue, 12V amber, 5V red, 3.3V green, STATUS red, ACT green). The 6HC does NOT have a
# 4 V LED: the "4V" asked for is the VIN input (V_FUSED, after the fuse).
#
# STATUS (the CAN communication LED), from RRF's code (src/CAN/CanInterface.cpp UpdateStatusLed and
# Duet3Expansion Platform.cpp):
# - main board: it blinks with the step clock, bit 19 of 750 kHz = 0.70 s on / 0.70 s off (~0.7 Hz);
# - expansion synchronised by CAN: the SAME blink, at the same time as the main one;
# - expansion not synchronised (no CAN messages): bit 17 = 0.175 s / 0.175 s (4 times faster);
# - firmware not running: off (or steady).
# Here: slow if all the CAN boards are "running", fast if some CAN board is not "running" or stopped
# appearing in boards[] (it disappears when it stops sending messages), off if there is no data from
# the board (the Pi does not read it). The phase is NOT the board's (its clock cannot be read): the
# Pi's clock is used with the same period.
LASER_HOLD_S = 4.0   # the "laser firing" state stays this long after the last PWM > 0
STATUS_MIDDLE_SYNC_S = (1 << 19) / 750000.0   # 0,699 s
STATUS_MIDDLE_WITHOUT_SYNC_S = (1 << 17) / 750000.0  # 0,175 s
# On the strip (physical or virtual) the loop does not repaint faster than ~0.2 s: the fast blink is
# painted with 0.2 s instead of 0.175 s (2.5 Hz instead of 2.9 Hz). The board's status strip
# (screens) uses the real value.
MIDDLE_MIN_STRIP_S = 0.2
VIN_MIN_V = 4.5   # less than this: without VIN (the board lives on USB / external 5 V)
V12_MIN_V = 6.0
_NETWORK = {"r": 255, "u": 0, "b": 0, "w": 0}
_GREEN = {"r": 0, "u": 255, "b": 0, "w": 0}
_BLUE = {"r": 0, "u": 0, "b": 255, "w": 0}
_AMBER = {"r": 255, "u": 150, "b": 0, "w": 0}
LEDS_BOARD_DEF = [
    # id, name (as the board says), colour
    ("can", M("status_light_status_can_communication"), _NETWORK),
    ("vin", "VIN (V_FUSED)", _BLUE),
    ("v12", "12 V", _AMBER),
    ("v5", "5 V", _NETWORK),
    ("v3_3", "3,3 V", _GREEN),
]
LEDS_BOARD_IDS = [x[0] for x in LEDS_BOARD_DEF]
_boards_views = set()  # CAN addresses seen since the service started


def _guard_degraded():
    """True while a protection is down or the guard stopped ticking (protection_guard.degraded)."""
    try:
        import protection_guard
        return protection_guard.degraded()
    except Exception:
        return False


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def state_board(om):
    """What the board's LEDs say, from the complete object model (/machine/status). Returns {ok, vin, v12, can, boards, missing}: can = "sync" (slow) | "no_sync" (fast) | "off"; boards = the expansion ones [{addr, name, state, vin, v12, can}]. 5 V and 3.3 V have no measurement in the object model: if the board answers, they are present."""
    boards = (om or {}).get("boards") or []
    if not boards or not isinstance(boards[0], dict):
        return {"ok": False, "vin": None, "v12": None, "can": "shutdown", "boards": [], "missing": []}
    b0 = boards[0]
    board_list = []
    for b in boards[1:]:
        if not isinstance(b, dict) or b.get("canAddress") in (None, 0):
            continue
        addr = int(b.get("canAddress"))
        _boards_views.add(addr)
        st = b.get("state")
        board_list.append({
            "addr": addr, "name": b.get("shortName") or b.get("name") or "",
            "state": st,
            "vin": _num((b.get("vIn") or {}).get("current")),
            "v12": _num((b.get("v12") or {}).get("current")),
            # without "state" (old firmware) it is taken as synchronised
            "can": "sync" if st in (None, "running") else "without_sync",
        })
    present = {p["addr"] for p in board_list}
    missing = sorted(_boards_views - present)
    can = "sync" if all(p["can"] == "sync" for p in board_list) and not missing else "without_sync"
    return {
        "ok": True,
        "vin": _num((b0.get("vIn") or {}).get("current")),
        "v12": _num((b0.get("v12") or {}).get("current")),
        "can": can, "boards": board_list, "missing": missing,
    }


def thresholds_board(lp):
    """Thresholds of the VIN and 12 V board LEDs (Lights page > Outputs >
    Board LEDs): below vin_min / v12_min the LED goes off, like the real one.
    Unset, the usual values apply (VIN_MIN_V, V12_MIN_V)."""
    lp = lp if isinstance(lp, dict) else {}
    out = {}
    for k, d in (("vin_min", VIN_MIN_V), ("v12_min", V12_MIN_V)):
        try:
            out[k] = float(lp.get(k, d))
        except (TypeError, ValueError):
            out[k] = d
    out["can_always"] = lp.get("can_blink") == "always"
    return out


def led_board(ident, ep, thresholds=None):
    """(colour, half blink period in s or 0 = steady, lit?, text) of a main board LED according to board_state()."""
    um = thresholds or {}
    vin_min = um.get("vin_min", VIN_MIN_V)
    v12_min = um.get("v12_min", V12_MIN_V)
    col = next(c for i, _, c in LEDS_BOARD_DEF if i == ident)
    if not ep.get("ok"):
        return col, 0, False, M("status_light_no_board_data")
    if ident == "can":
        if ep["can"] == "sync":
            # 2026-10-13: the slow blink of the board STATUS LED costs ~2 M150 per half period (measured 182
            # commands per minute): by default it stays lit while the CAN is fine and blinks only on a problem
            if not um.get("can_always"):
                return col, 0, True, M("status_light_steady_can_communication_fine") if ep["boards"] else M("status_light_steady_firmware_running")
            return col, STATUS_MIDDLE_SYNC_S, True, M("status_light_slow_blink_can_communication_fine") if ep["boards"] else M("status_light_slow_blink_firmware_running")
        bad = [str(p["addr"]) for p in ep["boards"] if p["can"] != "sync"] + [str(a) for a in ep["missing"]]
        return col, STATUS_MIDDLE_WITHOUT_SYNC_S, True, M("status_light_fast_blink_no_can_communication_board", boards=", ".join(bad))
    if ident == "vin":
        v = ep.get("vin")
        on = v is not None and v >= vin_min
        return col, 0, on, ("%.1f V" % v) if v is not None else M("status_light_no_measurement")
    if ident == "v12":
        v = ep.get("v12")
        on = v is not None and v >= v12_min
        return col, 0, on, ("%.1f V" % v) if v is not None else M("status_light_no_measurement")
    # 5 V and 3.3 V: no measurement in the object model; the board answers = present
    return col, 0, True, M("status_light_present_board_answers_no_measurement")


def _on(middle, on, t):
    if not on:
        return False
    if not middle or t < 0:
        return True
    return int(t / middle) % 2 == 0


def leds_board_segments(lp, ep, t=None, take=None):
    """Stretches (r,g,b,w,p,1) of the board LEDs chosen in Lights, in the order of BOARD_LEDS_DEF. taken = (colour, effect): a state with its "Board" checkbox on is active and takes the positions of the board LEDs while it lasts (for instance the emergency stop filling the whole zone)."""
    t = time.time() if t is None else t
    chosen = set(lp.get("leds") or LEDS_BOARD_IDS)
    p = max(1, min(255, int(lp.get("brightness", 120) or 120)))
    um = thresholds_board(lp)
    out = []
    for ident in LEDS_BOARD_IDS:
        if ident not in chosen:
            continue
        if take:
            c, effect = take
            level, enc = lr.effect_level(effect, t)
            out.append((c["r"], c["u"], c["b"], c.get("w", 0), level, 1) if enc else (0, 0, 0, 0, 0, 1))
            continue
        col, middle, on, _ = led_board(ident, ep, um)
        if _on(middle and max(middle, MIDDLE_MIN_STRIP_S), on, t):
            out.append((col["r"], col["u"], col["b"], col["w"], p, 1))
        else:
            out.append((0, 0, 0, 0, 0, 1))
    return out


def apply_leds_board(config, ep, t=None, take=None):
    """With status_light.leds_board.activo, the last LEDs of the status zone are the board's: the zone does NOT grow (the physical strip has the LEDs it has and growing would shift the lighting and the extra zones), they are subtracted from the end. At least 1 LED always remains for the state: with a very small zone fewer board LEDs fit (the first ones in the list). Returns (config with a reduced led_count, board stretches)."""
    slc = config.get("status_light") or {}
    lp = slc.get("leds_board") or {}
    if not lp.get("active") or ep is None:
        return config, []
    segments = leds_board_segments(lp, ep, t, take)
    n = int(slc.get("led_count", LED_COUNT_DEFAULT))
    segments = segments[:max(0, n - 1)]
    if not segments:
        return config, []
    c2 = dict(config)
    c2["status_light"] = dict(slc, led_count=n - len(segments))
    return c2, segments


def next_change_board(slc, ep, t=None):
    """Seconds until the next change of the STATUS LED's blink (so the loop repaints in time), or None if nothing blinks."""
    lp = slc.get("leds_board") or {}
    te = slc.get("strip_state") or {}
    uses = (lp.get("active") and "can" in (lp.get("leds") or LEDS_BOARD_IDS)) or te.get("active")
    if not uses or not ep or not ep.get("ok"):
        return None
    # the CAN LED stays lit while the communication is fine (unless the user wants the slow blink): nothing to repaint
    if ep.get("can") == "sync" and lp.get("can_blink") != "always" and not te.get("active"):
        return None
    t = time.time() if t is None else t
    middle = max(MIDDLE_MIN_STRIP_S, STATUS_MIDDLE_SYNC_S if ep["can"] == "sync" else STATUS_MIDDLE_WITHOUT_SYNC_S)
    return middle - (t % middle)


# ---------------------------------------------------------------------------
# Board status strip (2026-10-11): ONLY virtual, never M150
# ---------------------------------------------------------------------------
# A second strip the service builds by itself, one LED per thing of the object model, for the
# screens (ledStrip.stripState). Groups chosen in Lights.
GROUPS_STRIP_STATE = ("board", "final", "probes", "fans", "heaters", "laser", "outputs")
_HEX_SHUTDOWN = "#000000"


def _sec(ident, group, label, hexc, level, blink=0.0, fault=False):
    """fault = a real problem (a heater in fault, a CAN board that stopped answering): the screens count it, not the colour (the board LEDs are red by design)."""
    return {"id": ident, "group": group, "label": label, "hex": hexc,
            "level": round(max(0.0, min(1.0, float(level))), 2), "blink": round(float(blink or 0), 3), "fault": bool(fault)}


def _hexc(c):
    return _hex(c["r"], c["u"], c["b"], c.get("w", 0))


def strip_state(om, groups=None, ep=None):
    """List of LEDs [{id, group, label, hex, level 0..1, blink (half period in s, 0 = steady)}] from the complete object model. What is not in the object model does not appear (see the Lights page report)."""
    om = om or {}
    groups = set(GROUPS_STRIP_STATE if groups is None else groups)
    ep = ep if ep is not None else state_board(om)
    out = []
    if "board" in groups:
        for ident, label, _ in LEDS_BOARD_DEF:
            col, middle, on, txt = led_board(ident, ep, {"can_always": True})  # the screens blink by CSS: no cost
            out.append(_sec("board_" + ident, "board", M("status_light_main_board_led", label=label, text=txt),
                            _hexc(col), 1 if on else 0, middle if on else 0, fault=ident == "can" and ep.get("ok") and ep.get("can") != "sync"))
        for p in ep.get("boards") or []:
            nom = M("status_light_can_board", addr=p["addr"])
            if p["name"]:
                nom = J([nom, p["name"]], sep=" ")
            sync = p["can"] == "sync"
            out.append(_sec("can_%d" % p["addr"], "board",
                            M("status_light_board_status_led", board=nom, text=M("status_light_slow_blink_can_communication_fine") if sync else M("status_light_fast_blink_not_synced_state", state=str(p["state"]))),
                            _hexc(_NETWORK), 1, STATUS_MIDDLE_SYNC_S if sync else STATUS_MIDDLE_WITHOUT_SYNC_S, fault=not sync))
            if p["vin"] is not None:
                out.append(_sec("vin_%d" % p["addr"], "board", M("status_light_board_vin", board=nom, v=p["vin"]),
                                _hexc(_BLUE), 1 if p["vin"] >= VIN_MIN_V else 0))
        for a in ep.get("missing") or []:
            out.append(_sec("can_%d" % a, "board", M("status_light_can_board_not_answering", addr=a),
                            _hexc(_NETWORK), 1, STATUS_MIDDLE_WITHOUT_SYNC_S, fault=True))
    sensors = om.get("sensors") or {}
    axes = (om.get("move") or {}).get("axes") or []
    if "final" in groups:
        for i, e in enumerate(sensors.get("endstops") or []):
            if not isinstance(e, dict):
                continue
            letter = (axes[i] or {}).get("letter") if i < len(axes) and isinstance(axes[i], dict) else None
            act = bool(e.get("triggered"))
            out.append(_sec("final_%d" % i, "final",
                            M("status_light_endstop", axis=letter or i, state=M("status_light_triggered_m" if act else "status_light_not_triggered")),
                            "#ffb300" if act else "#4caf50", 1 if act else 0.25))
    if "probes" in groups:
        glob = om.get("global") or {}
        for i, p in enumerate(sensors.get("probes") or []):
            if not isinstance(p, dict) or p.get("type") in (None, 0):
                continue
            val = p.get("value") or [0]
            try:
                v0 = float(val[0] if isinstance(val, list) else val)
            except (TypeError, ValueError, IndexError):
                v0 = 0.0
            threshold = _num(p.get("threshold")) or 500
            act = v0 >= threshold
            out.append(_sec("probe_%d" % i, "probes",
                            M("status_light_probe", i=i, state=M("status_light_triggered_f" if act else "status_light_not_triggered"), value=v0, threshold=threshold),
                            "#ffb300" if act else "#4caf50", 1 if act else 0.25))
            if p.get("type") == 9:
                # BLTouch: the object model does not say whether the pin is out. global.probePinOut
                # is used (marked by deployprobe.g / retractprobe.g on this machine) and if it does
                # not exist, deployedByUser (only M401).
                if "probePinOut" in glob:
                    outside, source = bool(glob.get("probePinOut")), "global.probePinOut"
                else:
                    outside, source = bool(p.get("deployedByUser")), "M401 (deployedByUser)"
                out.append(_sec("bltouch_%d" % i, "probes",
                                M("status_light_bltouch_pin_according", i=int(i), p=M("status_light_pin_down_out") if outside else M("status_light_pin_up_stowed"), source=source),
                                "#e040fb" if outside else "#7e57c2", 1 if outside else 0.25))
    if "fans" in groups:
        for i, f in enumerate(om.get("fans") or []):
            if not isinstance(f, dict):
                continue
            v = _num(f.get("currentValue")) or 0.0
            nom = f.get("name") or M("status_light_fan", i=i)
            out.append(_sec("fan_%d" % i, "fans", M("status_light_fan_pct", name=nom, pct=round(v * 100)),
                            "#29b6f6", v if v > 0 else 0))
    if "heaters" in groups:
        for i, h in enumerate((om.get("heat") or {}).get("heaters") or []):
            if not isinstance(h, dict):
                continue
            st = h.get("state") or "off"
            cur = _num(h.get("current"))
            obj = _num(h.get("active")) if st == "active" else _num(h.get("standby")) if st == "standby" else None
            temp = ("%.0f" % cur) if cur is not None else "?"
            raw_text = {"off": M("status_light_heater_off"), "standby": M("status_light_heater_standby"), "active": M("status_light_heater_active"),
                        "fault": M("status_light_heater_fault"), "tuning": M("status_light_heater_tuning_pid"),
                        "offline": M("status_light_no_connection")}.get(st, st)
            # 2026-10-13: a heater whose sensor is not connected reads about -273 C (RRF calls it a fault, or
            # "off" with -273). In Laser / CNC mode nobody uses it: it is not listed at all (a thing that is not
            # configured for the mode in use is not shown). In FFF mode the same reading is a real fault.
            mode_machine = (om.get("state") or {}).get("machineMode")
            if cur is not None and cur < -250 and st in ("fault", "off") and mode_machine in ("Laser", "CNC"):
                continue
            et = M("status_light_heater_target", i=i, state=raw_text, temp=temp, target=obj) if obj is not None else M("status_light_heater", i=i, state=raw_text, temp=temp)
            if st == "fault":
                out.append(_sec("heater_%d" % i, "heaters", et, "#ff0000", 1, 0.25, fault=True))
            elif st in ("active", "tuning"):
                out.append(_sec("heater_%d" % i, "heaters", et, "#ff5722", 1, 0.5 if st == "tuning" else 0))
            elif st == "standby":
                out.append(_sec("heater_%d" % i, "heaters", et, "#ffb300", 0.5))
            else:
                out.append(_sec("heater_%d" % i, "heaters", et, _HEX_SHUTDOWN, 0))
    if "laser" in groups:
        cm = (om.get("move") or {}).get("currentMove") or {}
        kind = (om.get("state") or {}).get("machineMode")
        if kind == "Laser" or cm.get("laserPwm") is not None:
            pwm = _num(cm.get("laserPwm")) or 0.0
            out.append(_sec("laser", "laser", M("status_light_laser", round=round(pwm * 100)) if pwm > 0 else M("status_light_laser_off"),
                            "#ffeb3b", pwm if pwm > 0 else 0))
        for i, s in enumerate(om.get("spindles") or []):
            if not isinstance(s, dict) or s.get("state") in (None, "unconfigured"):
                continue
            st = s.get("state")
            rpm = _num(s.get("current")) or 0
            raw_text = {"stopped": M("status_light_spindle_stopped"), "forward": M("status_light_spindle_turning"), "reverse": M("status_light_turning_reverse")}.get(st, st)
            out.append(_sec("spindle_%d" % i, "laser", M("status_light_spindle", i=i, state=raw_text, rpm=int(rpm)),
                            "#00e676", 1 if st in ("forward", "reverse") else 0))
    if "outputs" in groups:
        for i, g in enumerate((om.get("state") or {}).get("gpOut") or []):
            if not isinstance(g, dict):
                continue
            v = _num(g.get("pwm")) or 0.0
            out.append(_sec("gpout_%d" % i, "outputs", M("status_light_output", i=i, state=("%d %%" % round(v * 100)) if 0 < v < 1 else M("status_light_output_on" if v > 0 else "status_light_output_off")),
                            "#ffffff", v if v > 0 else 0))
    return out


MODES_COMBINE = ("priority", "turns", "split")


def modes_ui(config, *args, **kw):
    """The REAL state computed with each combine mode (Lights page, "When there are several at once"): {mode: secs_ui}. The Pi computes it with the same compute() that paints the strip, so the interface does not repeat the logic and each example is exactly what would be seen with that mode."""
    slc = config.get("status_light", {})
    out = {}
    for m in MODES_COMBINE:
        cfg = dict(config)
        cfg["status_light"] = dict(slc, combine=dict(slc.get("combine") or {}, mode=m))
        out[m] = secs_ui(compute(cfg, *args, **kw)[0])
    return out


def _effect_end_job(bridge, config, illum):
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


class _WithoutM150:
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
            if _e_declared(e_):
                _paint_segments(bridge, e_, segments_)
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


# ---------------------------------------------------------------------------
# Data of the new states (all of it already published by other parts of the
# service: no new reads of the machine)
# ---------------------------------------------------------------------------
def pi_hot(payload, limit_c):
    """Pi temperature (health_poller publishes it in healthPi) at or over the limit."""
    cpu = ((payload or {}).get("healthPi") or {}).get("cpu") or {}
    try:
        return float(cpu.get("temp_c")) >= float(limit_c)
    except (TypeError, ValueError):
        return False


def motors_released(payload):
    """Some motor is released (M18): motor_poller publishes in motorReport the list "released" (readings of the drivers
    and requests of the API, kept up to date also without the Motors page). An older report without the list: some
    driver with "enabled" false (None = unknown, not counted)."""
    rep = (payload or {}).get("motorReport")
    if not isinstance(rep, dict):
        return False
    if isinstance(rep.get("released"), list):
        return bool(rep["released"])
    for e in rep.get("entries") or []:
        for d in (e or {}).get("drivers") or []:
            if isinstance(d, dict) and d.get("enabled") is False:
                return True
    return False


def unclean_shutdown(payload):
    """The black box found the last shutdown was not clean and the report has
    not been seen yet (box_black.publicar)."""
    rep = ((payload or {}).get("boxBlack") or {}).get("report")
    return isinstance(rep, dict) and not rep.get("seen")


# Test of a state ("Test this state" button of the page): shows the state on
# the chosen outputs for a few seconds, then everything goes back by itself.
TEST = {"id": None, "until": 0.0, "outputs": (), "color": None, "effect": None}
TEST_SECONDS = 6


def probe_state(ident, seconds=TEST_SECONDS, outputs=None, current_time=None, color=None, effect=None):
    """Starts the test of a state. Returns the test dict, or None if the state
    does not exist. salidas: subset of strip/screen/board (all by default).
    color / effect: what the page has on screen (not saved yet); by default the
    saved ones are used."""
    if ident not in lc.STATE_IDS:
        return None
    current_time = time.time() if current_time is None else current_time
    sal = tuple(o for o in lc.OUTPUTS if o in (outputs or lc.OUTPUTS))
    TEST.update(id=ident, until=current_time + max(2, min(20, float(seconds))), outputs=sal,
                  color=color, effect=effect if effect in lc.EFFECTS else None)
    return dict(TEST)


def test_active(current_time=None):
    current_time = time.time() if current_time is None else current_time
    if TEST["id"] and current_time < TEST["until"]:
        return TEST
    return None


def _state_test(slc, trial):
    """The state under test: saved config, with the colour / effect the page
    has on screen if it sent them."""
    f = dict(lc.state_full(slc, trial["id"]))
    if trial.get("color"):
        f["color"] = lc._color(trial["color"], f["color"])
    if trial.get("effect") and lc.STATE_KIND[trial["id"]] != "emergency":
        f["effect"] = trial["effect"]
    return f


def arm_frame(config, mode, disabled, illum, status, file_pos, file_size, extras, ep=None, current_time=None, trial=None):
    """Everything the three outputs show right now, from the machine data.

    Returns {present, segs, text, ui_color, info, screen: {detalle, text,
    segs}, secs_board, toma, disabled}. segs / text / info are for the strip
    (or, on a machine without strip, for the screen); screen is the on-screen
    indicator. Pure: no painting, no network."""
    slc = config.get("status_light", {}) or {}
    present = lc.has_strip(slc)
    if not present:
        disabled = False  # nothing else uses the strip: the automatic status is always on
    t = time.monotonic() if current_time is None else current_time
    cfg_e = config if disabled else config_state(config)
    output_main = "strip" if present else "screen"

    # a state with the "Board" checkbox takes over the positions of the board LEDs
    take = None
    if trial and "board" in trial["outputs"]:
        f = _state_test(slc, trial)
        take = (f["color"], f["effect"])
    elif present and not disabled:
        info_b = {}
        compute(cfg_e, mode, disabled, illum, status, file_pos, file_size, extras, info_b, output="board", current_time=t)
        det = info_b.get("detail") or []
        if det:
            take = (det[0]["color"], det[0]["effect"])
    # leds_board.with_lighting: "mantener" (default) = the board LEDs keep showing the board while
    # the lighting takes the rest of the status zone; "as_zone" = they do what the zone does (they
    # light up or go off together with the lighting)
    follows_zone = disabled and (slc.get("leds_board") or {}).get("with_lighting") == "as_zone"
    if present and not follows_zone:
        # the STATUS LED of the board blinks: during a job it stays lit (no repaint per phase)
        cfg_s, secs_board = apply_leds_board(cfg_e, ep, 0.0 if effects_frozen(slc, status, extras) else t, take)
    else:
        cfg_s, secs_board = cfg_e, []

    info = {}
    secs, text, ui_color = compute(cfg_s, mode, disabled, illum, status, file_pos, file_size, extras, info, output=output_main, current_time=t)
    secs = list(secs) + list(secs_board)
    # the on-screen indicator: same machine data, the states marked "Screen"
    info_p = {}
    if present:
        secs_p, text_p, _ = compute(cfg_e, mode, disabled, illum, status, file_pos, file_size, extras, info_p, output="screen", current_time=t)
    else:
        secs_p, text_p, info_p = secs, text, info

    if trial:
        f = _state_test(slc, trial)
        col = f["color"]
        level, enc = lr.effect_level(f["effect"], t)
        label = lc.STATE_TEXT[trial["id"]]
        if "strip" in trial["outputs"] and present:
            n_s = cfg_s.get("status_light", {}).get("led_count", LED_COUNT_DEFAULT)
            secs = [(col["r"], col["u"], col["b"], col.get("w", 0), level, n_s) if enc else (0, 0, 0, 0, 0, n_s)] + secs_board
            text = M("status_light_testing", state=label)
            info = {"activeList": [(trial["id"], col)], "detail": [dict(f, id=trial["id"], color=col)]}
        if "screen" in trial["outputs"]:
            text_p = M("status_light_testing", state=label)
            info_p = {"activeList": [(trial["id"], col)], "detail": [dict(f, id=trial["id"], color=col)]}
        if not present:
            secs, text, info = secs_p, text_p, info_p
    return {"present": present, "secs": secs, "text": text, "ui_color": ui_color, "info": info,
            "screen": {"detail": info_p.get("detail") or [], "text": text_p, "secs": list(secs_p)},
            "secs_board": secs_board, "take": take, "disabled": disabled, "cfg_s": cfg_s, "cfg_e": cfg_e}


def detail_ui(detail):
    """[{id, color, effect}] -> [{id, nombre, hex, effect}] for the screens."""
    out = []
    for d in detail or []:
        c = d.get("color") or {}
        out.append({"id": d["id"], "name": _TEXT.get(d["id"], d["id"]), "effect": d.get("effect", "steady"),
                    "hex": _hex(c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0))})
    return out


# ---------------------------------------------------------------------------
# IPC counters (published in servicesInternal.luces)
# ---------------------------------------------------------------------------
# What this module asks of DSF / the board, to measure the cost on the Pi:
#   reads     spot reads of the object model (leer_puntual, RS485 data) and the
#             one-off M98 that tells daemon.g the Pi paints
#   commands  G-code sent to the board (M150, macros)
#   publishes plugin data written (set_status)
# The idle paint loop makes none of them: it reads the shared subscription
# (state_machine, in memory) and only talks when a frame really changed.
_COUNTER = {"reads": 0, "commands": 0, "publishes": 0, "since": time.time()}
_COUNTER_TS = {"reads": [], "commands": [], "publishes": []}
_COUNTER_LOCK = None


def count(type_name, n=1, current_time=None):
    import threading
    global _COUNTER_LOCK
    if _COUNTER_LOCK is None:
        _COUNTER_LOCK = threading.Lock()
    current_time = time.time() if current_time is None else current_time
    with _COUNTER_LOCK:
        _COUNTER[type_name] += n
        _COUNTER_TS[type_name].extend([current_time] * n)
        # keep only the last minute
        cut = current_time - 60
        while _COUNTER_TS[type_name] and _COUNTER_TS[type_name][0] < cut:
            _COUNTER_TS[type_name].pop(0)


def ipc_stats(current_time=None):
    """{reads_min, commands_min, publishes_min, total_*}: calls of the last
    minute and since the service started."""
    current_time = time.time() if current_time is None else current_time
    out = {"since_s": int(current_time - _COUNTER["since"])}
    for k in ("reads", "commands", "publishes"):
        out[k + "_min"] = len([x for x in _COUNTER_TS[k] if x >= current_time - 60])
        out["total_" + k] = _COUNTER[k]
    return out


def counters_a_zero():
    """For tests."""
    for k in ("reads", "commands", "publishes"):
        _COUNTER[k] = 0
        _COUNTER_TS[k].clear()
    _COUNTER["since"] = time.time()


class _Counter:
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


# ---------------------------------------------------------------------------
# What the loop reads: the shared model (no IPC)
# ---------------------------------------------------------------------------
def read_input(om):
    """(mode, disabled, illum, status, file_pos, file_size, laser_pwm, homed,
    animating) from the shared object model (state_machine). Every workshop
    global is optional (a published plugin must work on a printer with one
    simple config.g): without global.selectedMode the machine mode of RRF
    (state.machineMode: FFF, CNC, Laser) is used; the other globals fall back
    to "off / nothing painted"."""
    om = om if isinstance(om, dict) else {}
    g = om.get("global") if isinstance(om.get("global"), dict) else {}
    st = om.get("state") if isinstance(om.get("state"), dict) else {}
    job = om.get("job") if isinstance(om.get("job"), dict) else {}
    mv = om.get("move") if isinstance(om.get("move"), dict) else {}
    mode = g.get("selectedMode") or st.get("machineMode") or "FFF"
    illum = g.get("lightZoneColor")
    if not (isinstance(illum, list) and len(illum) >= 5):
        illum = [0, 0, 0, 0, 0]
    cm = mv.get("currentMove") if isinstance(mv.get("currentMove"), dict) else {}
    axes = [a for a in (mv.get("axes") or [])[:2] if isinstance(a, dict)]
    homed = all(bool(a.get("homed")) for a in axes) if axes else True
    return (str(mode), bool(g.get("statusLedDisabled", False)), [int(x or 0) for x in illum[:5]],
            st.get("status") or "idle", job.get("filePosition") or 0, (job.get("file") or {}).get("size") or 0,
            cm.get("laserPwm") or 0, homed, bool(g.get("ledAnimating", False)))


def _rs_values(status):
    """(faults, warnings) from a plugins.* answer, or None if the RS485 plugin
    publishes nothing."""
    plugins = (status or {}).get("plugins") or {}
    for rid in RS485_IDS:
        rs = ((plugins.get(rid) or {}).get("data") or {}).get("rs485")
        if isinstance(rs, dict):
            try:
                return int(rs.get("faults") or 0), int(rs.get("notices") or 0)
            except (TypeError, ValueError):
                return 0, 0
    return None


class ReaderRs485:
    """Reads the RS485 plugin data (faults / warnings) rarely and in its own
    thread, never in the paint loop. plugins.* is not in the shared
    subscription (it would echo our own plugin data back as patches), so this
    is a spot read: every RS485_CADA_S if the plugin is installed, every
    RS485_SIN_PLUGIN_S if it is not."""
    RS485_EACH_S = 5
    RS485_WITHOUT_PLUGIN_S = 60

    def __init__(self, read_in=None):
        self.faults = 0
        self.notices = 0
        self._read = read_in

    def _read_one_shot(self):
        import machine_state
        count("reads")
        return {"plugins": machine_state.read_plugins(max_age=4.0)}

    def run_once(self):
        """One spot read. Returns the seconds to wait before the next one."""
        try:
            v = _rs_values((self._read or self._read_one_shot)())
            if v is None:
                self.faults = self.notices = 0
                return self.RS485_WITHOUT_PLUGIN_S
            self.faults, self.notices = v
            return self.RS485_EACH_S
        except Exception as e:
            self.faults = self.notices = 0
            log_file(f"RS485 read failed: {e}")
            return 30


def _run_reader_rs485(reader):
    while True:
        time.sleep(max(1, reader.run_once()))


# ---------------------------------------------------------------------------
# The painter: one tick = one decision from the model (no IPC while idle)
# ---------------------------------------------------------------------------
class Painter:
    """Everything the old polling loop did, as a function of the model: tick(om)
    reads nothing, asks nothing, and only sends to the board / publishes when
    the frame or the payload really changed. run_loop() calls it when the
    shared model changes and on a timer only while an animation needs frames."""

    def __init__(self, bridge_real, config, rs=None, announce=None):
        self.config = config
        self.bridge_real = _Counter(bridge_real)
        self.rs = rs
        self.announce = announce if announce is not None else self._announce_real
        self.conn = None
        self.last_key = None
        self.last_key_strip = None
        self.keys_extra = {}
        self.announced = False
        self.reconnected = False
        self.prev_status = None
        self.prev_in_live = False
        self.animating_since = None
        self.auto_published = None
        self.te_pub = None
        self.te_last = 0.0
        self.history = lr.StateHistory(50)
        self.light_auto = lr.WorkLightAuto()
        self.still_since = None
        self.pub = {"indicator": None, "info": None}
        self.last_painted = None  # monotonic time of the last paint of the strip
        self.paint_s = 0.0      # how long the last paint took (the Duet answering slowly = paint less)

    # -- one-off, counted: tells daemon.g that the Pi paints (strip only) --
    def _announce_real(self):
        import communication
        count("reads")
        if self.conn is None:
            self.conn = CommandConnection()
            self.conn.connect()
        # same own channel as Bridge.send (communication.py)
        self.conn.perform_simple_code('M98 P"0:/sys/workshop/macros/enable_pi_status.g"', channel=communication.channel_plugin())

    def forget(self):
        """The subscription (re)connected: paint everything again."""
        self.last_key = None
        self.keys_extra.clear()
        self.announced = False
        self.pub["indicator"] = self.pub["info"] = self.pub["light"] = None

    def _light_of_job(self, turn_on):
        """Same as handlers/light.py: the macros keep the colour and brightness."""
        macro = "lighton.g" if turn_on else "lightoff.g"
        real = self.bridge_real

        def _thread():
            try:
                real.send(f'M98 P"0:/macros/light/{macro}"')
                real.set_status("lightOn", bool(turn_on))
            except Exception:
                pass

        import threading
        threading.Thread(target=_thread, daemon=True).start()

    def power_off(self, om):
        """The module was stopped: switch the status zone off once."""
        cfg = self.config
        illum = read_input(om)[2]
        real = self.bridge_real
        pi_leds.power_off_all()
        power_off_state(_WithoutM150(real) if not lc.has_strip(cfg.get("status_light") or {}) else real, illum, cfg)

    def tick(self, om, mono=None, wall=None, minutes=None):
        """One decision from the model `om`. Returns the seconds to wait for
        the next tick if nothing changes (short while an animation runs)."""
        mono = time.monotonic() if mono is None else mono
        wall = time.time() if wall is None else wall
        if minutes is None:
            lt = time.localtime(wall)
            minutes = lt.tm_hour * 60 + lt.tm_min
        config = self.config
        if isinstance(config.get("status_light"), dict):
            _sanitize(config["status_light"])
        slc_p = config.get("status_light", {}) or {}
        present = lc.has_strip(slc_p)
        bridge = self.bridge_real if present else _WithoutM150(self.bridge_real)

        # board LEDs / board status strip need the model (already in memory)
        lp_c = slc_p.get("leds_board") or {}
        te_c = slc_p.get("strip_state") or {}
        om_p = om if (lp_c.get("active") or te_c.get("active")) else None
        ep_p = state_board(om_p) if om_p is not None else None
        try:
            self._tick_strip_state(bridge, slc_p, om_p, ep_p)
        except Exception as e:
            log_file(f"board status strip: {e}")
        if not present:
            heartbeats.detail("status_light", M("status_light_no_led_strip_status_on_screens"))

        mode, disabled, illum, status, file_pos, file_size, laser_pwm, homed, animating = read_input(om)

        # start-up animation / page preview in progress: do not paint; after it
        # everything is painted again. A stuck flag is ignored after 30 s.
        if animating:
            if self.animating_since is None:
                self.animating_since = mono
            elif mono - self.animating_since > 30:
                animating = False
        else:
            self.animating_since = None
        if (animating or wall < PAUSE_UNTIL) and present:
            self.last_key = None
            self.keys_extra.clear()
            heartbeats.ok("status_light")
            return POLL_INTERVAL_S

        if not self.announced:
            if present:
                try:
                    self.announce()
                except Exception as e:
                    # a machine without the workshop's macros: the strip is still painted
                    log_file(f"enable_pi_status.g not available ({e}): carrying on without telling daemon.g")
            bridge.set_status("statusLightPiActive", True)
            self.announced = True
            self.last_key = None
            self.keys_extra.clear()

        if not present:
            disabled = False
        # statusLightAuto comes from the REAL state (global.statusLedDisabled)
        if self.auto_published is not (not disabled):
            self.auto_published = not disabled
            try:
                bridge.set_status("statusLightAuto", self.auto_published)
            except Exception:
                pass

        datos0 = getattr(bridge, "payload", {}) or {}
        in_live_now = _in_live(datos0.get("liveJob"))
        ended_file = self.prev_status in ("processing", "simulating") and status == "idle"
        # live job: the machine stays "busy", not "processing", so the end is
        # detected when liveJob turns off
        ended_in_live = self.prev_in_live and not in_live_now and status != "halted"
        if (ended_file or ended_in_live) and not disabled:
            try:
                _effect_end_job(bridge, config, illum)
                self.keys_extra.clear()
            except Exception as e:
                log_file(f"end-of-job effect: {e}")
            self.last_key = None
        self.prev_status = status
        self.prev_in_live = in_live_now

        payload = getattr(bridge, "payload", {}) or {}
        new = lc.normalize_new(slc_p)
        if in_live_now and status == "idle":
            if self.still_since is None:
                self.still_since = mono
        else:
            self.still_since = None
        in_live_still = self.still_since is not None and mono - self.still_since >= new["live_quiet_s"]
        rs_f, rs_a = (self.rs.faults, self.rs.notices) if self.rs is not None else (0, 0)
        # The laser PWM goes to 0 between cuts and in every rapid move: the state "laser firing" would switch on and off
        # every second and, in "dividir", every change would re-split the whole strip (reported 2026-10-16 with a live
        # job). It is held for LASER_SOSTENER_S after the last shot, so the strip only changes when the laser really stops.
        if laser_pwm:
            self.laser_seen = mono
        elif getattr(self, "laser_seen", None) is not None and mono - self.laser_seen < LASER_HOLD_S:
            laser_pwm = 1
        extras = {"laser_pwm": laser_pwm, "homed": homed, "air": payload.get("airAssist"),
                  "in_live": in_live_now, "rs485_faults": rs_f,
                  "jog_free": _jog_free_active(), "crash": _jog_alert_limits(),
                  # free jog has its own state and colour: it does not count as "risk"
                  # a safety process down (protection_guard.py) must never leave the strip on "ready"
                  "risk": any((r or {}).get("id") != "jog_free" for r in (payload.get("riskActive") or [])) or _guard_degraded(),
                  "jog_free_color": _jog_free_color(),
                  "rs485_notices": rs_a,
                  "pi_hot": pi_hot(payload, new["pi_hot_c"]),
                  "motors_loose": motors_released(payload),
                  "in_live_still": in_live_still,
                  "shutdown_dirty": unclean_shutdown(payload)}

        trial = test_active(wall)
        frame = arm_frame(config, mode, disabled, illum, status, file_pos, file_size, extras, ep_p, current_time=mono, trial=trial)
        secs, text, ui_color, info = frame["secs"], frame["text"], frame["ui_color"], frame["info"]
        secs_board = frame["secs_board"]
        # What the pages mirror is the frozen frame (every effect lit): the strip repaints with the phase of a
        # blink, the pages animate it themselves (statusIndicator) and must not get a new value per phase
        frame_ui = arm_frame(config, mode, disabled, illum, status, file_pos, file_size, extras, ep_p,
                                 current_time=lr.UI_FRAME_T, trial=trial)
        secs_mirror = frame_ui["secs"]
        ui_color = frame_ui["ui_color"]
        modes = modes_ui(frame["cfg_s"], mode, disabled, illum, status, file_pos, file_size, extras,
                         output="strip" if present else "screen", current_time=lr.UI_FRAME_T)
        if secs_board:
            modes = {m: v + secs_ui(frame_ui["secs_board"]) for m, v in modes.items()}
        mc = slc_p.get("mode_colors", {}) or {}
        mode_colors = {m: _hex(c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0)) for m, c in mc.items() if isinstance(c, dict)}
        active_ui = detail_ui(info.get("detail")) if info.get("detail") else [
            {"id": i, "name": _TEXT.get(i, i), "hex": _hex(c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0))} for i, c in info.get("activeList", [])]
        jog_above = disabled and bool(info.get("activeList")) and info["activeList"][0][0] in ("crash", "risk", "jog_free")
        mcol = _color_for(slc_p, mode)
        mode_hex = _hex(mcol.get("r", 0), mcol.get("u", 0), mcol.get("b", 0), mcol.get("w", 0))
        if disabled and not jog_above:
            # automatic status lights off: the work light takes these LEDs
            on = any(illum[:4])
            active_ui = [{"id": "lighting", "name": M("status_light_lighting_automatic_off" if on else "status_light_lighting_off_automatic_off"),
                           "hex": _hex(*illum[:4]) if on else "#333333"}]
        elif not (active_ui and active_ui[0]["id"] in ("stop", "crash", "risk", "jog_free")):
            # emergency / crash / free jog take the WHOLE zone: the mode is not
            # shown in the legend (2026-10-10)
            active_ui.append({"id": "base", "name": M("status_light_mode_progress_bar" if status in ("processing", "simulating") else "status_light_mode", mode=mode),
                               "hex": mode_hex})
        slc0 = slc_p
        configure_outputs(slc0)
        self.pi_fast = pi_paints(slc0)
        led_count = slc0.get("led_count", LED_COUNT_DEFAULT)
        # night dimming: only the physical strip
        factor = lr.night_factor(new["night"], minutes) if present else 1.0
        dim = (factor, new["night"]["include_work_light"]) if factor < 0.999 else None
        _POWER["ma_channel"] = new["power"]["ma_per_channel"]
        where = ("main",) if disabled else zone_state(slc0)
        # the strip is repainted only when what the STRIP shows changes; the previews of the page (activos_ui,
        # modos, colours of the modes) change with their own effects and must not cost M150 (2026-10-13: ~180
        # M150 per minute with nothing changing on the strip)
        key_strip = f"{secs},{led_count},{slc0.get('led_start', 10)},{slc0.get('led_strip', 0)},{slc0.get('order')},{illum},{layout(slc0)},{where},{dim}"
        key = f"{key_strip},{active_ui},{modes},{mode_colors}"

        # job running: at most 2 paints per second, and fewer when the Duet takes long to answer
        # (the paints are queued behind the job's own traffic on the same link)
        in_job = status in ("processing", "simulating") or in_live_now
        gap = MIN_BETWEEN_PAINTED_JOB_S if in_job else 0.0
        if self.paint_s > 0.3:
            gap = max(gap, min(MAX_BETWEEN_PAINTED_SLOW_S, 4 * self.paint_s))
        if pi_paints(slc0):
            gap = 0.0  # a paint from the Pi costs no call to the board: no pacing
        defer = bool(key != self.last_key and self.last_painted is not None and gap > 0 and mono - self.last_painted < gap and not trial)
        if key != self.last_key and not defer:
            repaint = self.last_key is None or key_strip != self.last_key_strip
            if repaint and os.path.exists("/tmp/workshop-debug-lights"):
                log_file("DEBUG repaint: %s || before: %s" % (key_strip[:400], str(self.last_key_strip)[:400]))
            self.last_key = key
            self.last_key_strip = key_strip
            t_paint = time.monotonic()
            try:
                if not repaint:
                    pass  # only a preview of the page changed: publish below, no M150
                elif not present:
                    # no strip: only what the screens copy (statusLightSecs, ledStrip)
                    _paint_segment_list(bridge, illum, secs, slc0.get("led_start", 10), slc0.get("led_strip", 0), slc0.get("order"), layout(slc0), secs_mirror=secs_mirror)
                elif disabled:
                    _paint_segment_list(bridge, illum, secs, slc0.get("led_start", 10), slc0.get("led_strip", 0), slc0.get("order"), layout(slc0), dim=dim, secs_mirror=secs_mirror)
                else:
                    paint_state(bridge, illum, secs, slc0, with_extra=False, dim=dim, secs_mirror=secs_mirror)
            except Exception as e:
                log_file(f"error painting: {e}")
            self.paint_s = time.monotonic() - t_paint
            self.last_painted = mono
            col = next((h for h, level, _ in secs_ui(secs_mirror) if level > 0), "#000000")
            bridge.set_status("statusLightColor", ui_color or col)
            ini0 = slc0.get('led_start', 10)
            if not present:
                heartbeats.detail("status_light", M("status_light_no_led_strip_screens_only", text=text))
            elif where[0] == "main":
                heartbeats.detail("status_light", M("status_light_leds_of_strip", first=ini0, last=ini0 + led_count - 1, n=led_count, strip=slc0.get('led_strip', 0), text=text))
            elif where[0] == "led_strip":
                heartbeats.detail("status_light", M("status_light_status_in_zone_of_strip", strip=where[1], n=where[4], text=text))
            else:
                heartbeats.detail("status_light", M("status_light_no_status_zone_screens_only", text=text))
            bridge.set_status("statusLightText", text)
            bridge.set_status("statusLightActive", active_ui)
            bridge.set_status("statusLightModes", modes)
            bridge.set_status("statusLightModeColors", mode_colors)

        # additional strips (Lights page): fixed colours per zone, painted only
        # when they change and only if their E is declared in config.g
        for e_, segments_ in (strips_extra_segments(slc0, None if disabled else secs) if present else []):
            k_ = repr(segments_)
            if self.keys_extra.get(e_) != k_:
                self.keys_extra[e_] = k_
                if _e_declared(e_):
                    try:
                        _paint_segments(bridge, e_, segments_)
                    except Exception as ex:
                        log_file(f"error painting strip E{e_}: {ex}")
                else:
                    log_file(f"strip E{e_} has no M950 in config.g: not painted")

        # --- on-screen indicator (statusIndicator) and extra info (lightsInfo) ---
        try:
            screen = frame["screen"]
            det_p = detail_ui(screen["detail"])
            if disabled and not jog_above:
                det_p = [d for d in active_ui if d["id"] == "lighting"]
            prog = None
            if status in ("processing", "simulating") and file_size:
                prog = int(((file_pos or 0) / file_size) * 20) / 20.0
            comb_p = slc0.get("combine") or {}
            mode_c = comb_p.get("mode", "priority")
            if mode_c == "split" and (info.get("capacidad") or {}).get("rotating"):
                mode_c = "turns"  # more states than LEDs: they take turns
            ind = lr.build_indicator(det_p, mode, mode_hex, status, screen["text"], prog,
                                     test=(trial["id"] if trial else None),
                                     extra={"combine": mode_c, "turn_s": max(0.5, float(comb_p.get("turn_s", 1.5)))})
            k_ind = repr(ind)
            if k_ind != self.pub["indicator"]:
                self.pub["indicator"] = k_ind
                bridge.set_status("statusIndicator", ind)
            if not trial:
                self.history.observe(int(wall), [d["id"] for d in det_p if d["id"] != "lighting"], mode, status)
            light_on = any(illum[:4]) and illum[4] > 0
            # lightOn (the Light on / Light off buttons) follows the real zone colour, so a light switched
            # on or off by any other path (Lights page, macro, daemon) never leaves the buttons stale
            if self.pub.get("light") != bool(light_on):
                self.pub["light"] = bool(light_on)
                bridge.set_status("lightOn", bool(light_on))
            working = status not in ("idle", "off") or in_live_now
            action = self.light_auto.update(wall, light_on, working, new["work_light"]) if present and not disabled else None
            if action == "off":
                log_file("work light: switched off by itself after the quiet time")
                self._light_of_job(False)
            elif action == "on":
                log_file("work light: switched on by itself, a job started")
                self._light_of_job(True)
            board_ui = None
            if lp_c.get("active") and ep_p is not None:
                board_ui = lr.board_leds_ui(lp_c.get("leds") or LEDS_BOARD_IDS, ep_p, led_board, thresholds_board(lp_c))
            subtracts = self.light_auto.seconds_left(wall, light_on, working, new["work_light"]) if present else None
            info_pub = {
                "strip": present,
                "history": self.history.as_list(),
                "power": {"ma": int(round(_POWER["ma"] / 10.0)) * 10 if present else 0, "limit": new["power"]["limit_ma"],
                          "over": bool(present and new["power"]["limit_ma"] and _POWER["ma"] > new["power"]["limit_ma"])},
                "night": {"on": factor < 0.999, "level": int(round(factor * 100))},
                "auto_off_min": None if subtracts is None else int((subtracts + 59) // 60),
                "board": board_ui,
                # how many LEDs the status zone has, how many states fit at once and what did not fit
                "capacity": dict(info.get("capacidad") or {}, board_leds=len(frame["secs_board"]),
                                 board_wanted=len((lp_c.get("leds") if lp_c.get("leds") is not None else LEDS_BOARD_IDS)) if lp_c.get("active") else 0),
            }
            k_inf = repr(info_pub)
            if k_inf != self.pub["info"]:
                self.pub["info"] = k_inf
                bridge.set_status("lightsInfo", info_pub)
        except Exception as e:
            log_file(f"on-screen indicator: {e}")

        heartbeats.ok("status_light")
        # Animations are the only reason to wake up on a timer (no IPC):
        # the board STATUS LED blinking (0.7 s slow; fast = MEDIO_MIN_TIRA_S),
        # blinking / pulsing states, turns between several states.
        waiting = IDLE_WAIT_S
        frozen = effects_frozen(slc0, status, extras)
        prox = next_change_board(slc0, ep_p) if lp_c.get("active") and not frozen else None
        if prox is not None:
            waiting = min(waiting, max(0.05, prox + 0.01))
        effects = [d.get("effect") for d in (info.get("detail") or [])]
        if trial or any(e != "steady" for e in effects):
            if pi_paints(slc0) and not trial:
                waiting = min(waiting, lr.next_change([e for e in effects if e], mono) + 0.005)
            else:
                waiting = min(waiting, 0.2 if lr.needs_fast_tick(effects) or trial else POLL_INTERVAL_S)
        if (slc0.get("combine") or {}).get("mode") in ("turns",) and len(info.get("activeList") or []) > 1 and not frozen:
            waiting = min(waiting, POLL_INTERVAL_S)
        if (slc0.get("combine") or {}).get("mode") == "split" and effects and any(e != "steady" for e in effects):
            waiting = min(waiting, 0.2)
        if defer:  # a change is waiting for its turn: come back when the gap is over
            waiting = min(waiting, max(0.1, gap - (mono - self.last_painted) + 0.02))
        return waiting

    def _tick_strip_state(self, bridge, slc, om, ep):
        te = slc.get("strip_state") or {}
        # only the Lights page (Advanced tab) reads this copy: nobody there, nothing is worked out or published
        if not te.get("active") or not viewers.active("lights_board"):
            if self.te_pub is not None:
                self.te_pub = None
                publish_strip_state(bridge, None)
            return
        val = {"secs": strip_state(om, te.get("groups"), ep), "ok": om is not None}
        k = repr(val)
        # The virtual strip copies live outputs (the laser LED follows every on/off of the beam): during a cut
        # that is a change several times per second, and each one is a call to the board's server. A copy that
        # is two seconds old is as good for the screens, so a changed copy waits for the next tick after that.
        mono = time.monotonic()
        if k != self.te_pub and (self.te_pub is None or mono - self.te_last >= STRIP_STATE_MIN_S):
            self.te_pub = k
            self.te_last = mono
            publish_strip_state(bridge, val)


# the idle wait: nothing animates, so the loop only wakes on a model change
# (state.upTime changes every second) or after this
IDLE_WAIT_S = 1.0
STRIP_STATE_MIN_S = 2.0  # at most one copy of the board's virtual strip every 2 s
MIN_BETWEEN_TURNS_S = 0.2


def run_loop(bridge_real, config):
    """Event driven: wakes up when the shared model changes (state_machine.
    on_change) and, only while an animation needs frames, on a short timer.
    Reads nothing from DSF itself."""
    import threading

    import machine_state

    event = threading.Event()
    rs = ReaderRs485()
    threading.Thread(target=_run_reader_rs485, args=(rs,), daemon=True, name="lights-rs485").start()
    painter = Painter(bridge_real, config, rs)

    def _change(patch, full):
        if full:
            painter.reconnected = True
        event.set()

    machine_state.on_change(_change)
    in_idle = False
    last = 0.0
    while True:
        try:
            om = machine_state.get_status(timeout=3)
        except Exception as e:
            heartbeats.detail("status_light", M("status_light_waiting_machine_state_dsf_subscription"))
            log_file(f"no model yet ({e})")
            time.sleep(2)
            continue
        # "Lights and status" (WorkshopLights) stopped or disabled: this module
        # does not run (service_modules.py). The status zone is switched off once and
        # the loop waits; when it is enabled again everything is painted.
        if not service_modules.is_active(service_modules.LIGHTS):
            if not in_idle:
                try:
                    painter.power_off(om)
                    in_idle = True
                    painter.forget()
                    log_file("Lights and status stopped: status zone off, the service does not paint")
                except Exception as e:
                    log_file(f"rest: could not switch the status zone off ({e}), retrying")
                    time.sleep(5)
                    continue
            heartbeats.detail("status_light", M("status_light_at_rest_lights_states_plugin_stopped"))
            heartbeats.ok("status_light")
            time.sleep(3)
            continue
        if in_idle:
            in_idle = False
            painter.forget()
            log_file("Lights and status active again: the service paints again")
        if painter.reconnected:
            painter.reconnected = False
            painter.forget()
        # at most ~5 decisions per second, however many patches arrive (25 when the Pi paints: no call to the board)
        missing = (0.04 if getattr(painter, "pi_fast", False) else MIN_BETWEEN_TURNS_S) - (time.monotonic() - last)
        if missing > 0:
            time.sleep(missing)
        event.clear()
        try:
            waiting = painter.tick(om)
        except Exception as e:
            log_file(f"tick failed: {type(e).__name__}: {e}")
            heartbeats.error("status_light", e)
            waiting = 2.0
        last = time.monotonic()
        event.wait(waiting)
