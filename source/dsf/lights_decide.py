"""
Status strip, the decisions (pure): which states are active and what the status zone shows for them. No M150, no publishing, no reading of the machine: everything comes in as arguments.
"""
import time
import real_mode
import lights_config as lc
import lights_runtime as lr
from messages import M, J


LED_COUNT_DEFAULT = 10


# Colours of the special states (2026-10-09, Lights page): they can be changed in config.json
# status_light.state_colors; these are the usual ones (the same as sys/daemon.g).
STATE_COLORS_DEFAULT = {
    "stop": {"r": 255, "u": 0, "b": 0, "w": 0},
    "paused": {"r": 255, "u": 120, "b": 0, "w": 0},
    "cancelling": {"r": 255, "u": 0, "b": 255, "w": 0},  # magenta (2026-10-10: the reddish orange was confused with the stop)
    "busy": {"r": 255, "u": 255, "b": 255, "w": 0},
}


# (2026-10-10) There is no longer a heartbeat for sys/daemon.g: the strip is painted ONLY by this
# service. If it dies, the strip stays still and on returning everything is repainted. Failures of
# WorkshopRS485 (if installed): a simple number published by that plugin. Warnings (devices without
# an axis with an alarm): WorkshopRS485 1.4.0+. Separate query: if the key does not exist yet, only
# the warnings stay at 0 (not the failures).
RS485_IDS = ("WorkshopRS485", "WorkshopRS485")  # 2026-10-10: the Ids become English


def rs_discover(status):
    """(Id, has_faults, has_warnings) of the RS485 plugin that publishes data in the object model, or (None, False, False). The model is looked at instead of trying expressions: each EvaluateExpression with a field that does not exist leaves "Failed to execute EvaluateExpression" in DCS's log (2026-10-12: with the old Id WorkshopRS485 it appeared in a loop)."""
    plugins = (status or {}).get("plugins") or {}
    for rid in RS485_IDS:
        rs = ((plugins.get(rid) or {}).get("data") or {}).get("rs485")
        if isinstance(rs, dict):
            return rid, "faults" in rs, "notices" in rs
    return None, False, False


def color_for(cfg, selected_mode):
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
        base = color_for(cfg, selected_mode)
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


TEXT_OF = {e[0]: e[1] for e in STATES_DEF}


def state_cfg(slc, ident):
    est = (slc.get("states") or {}).get(ident) or {}
    old = (slc.get("state_colors") or {}).get(ident)
    default = next(e for e in STATES_DEF if e[0] == ident)
    color = est.get("color") or old or default[2]
    is_active = True if ident == "stop" else est.get("active", default[3])
    return is_active, color


def sanitize(slc):
    """Numbers of the strip config always valid integers: an odd value (e.g. "" from a field deleted on the page) must not stop the painting."""
    for k, d, lo in (("led_count", LED_COUNT_DEFAULT, 1), ("led_start", 10, 0), ("led_strip", 0, 0)):
        try:
            slc[k] = max(lo, int(round(float(slc.get(k, d)))))
        except (TypeError, ValueError):
            slc[k] = d


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


def hex_color(r, u, b, w=0):
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
        out.append([hex_color(r, u, b, w), level, int(n)])
    return out


def is_live(v):
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


def whole_zone(slc, status, extras, output, forced, t, n, info):
    """The states that take the WHOLE zone whatever the combine mode: the emergency stop, crash, risk and the no-limits jog. Returns (segments, text, ui_color), or None when none of them applies."""
    if status == "halted" and lc.state_full(slc, "stop")["outputs"].get(output, True):
        f = lc.state_full(slc, "stop")
        col = f["color"]
        if info is not None:
            info["activeList"] = [("stop", col)]
            info["detail"] = [dict(f, id="stop", color=col)]
        return [(col["r"], col["u"], col["b"], col.get("w", 0), 255, n)], TEXT_OF["stop"], None
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
            return [(0, 0, 0, 0, 0, n)], TEXT_OF[ident], None
        return [(col["r"], col["u"], col["b"], col.get("w", 0), level, n)], TEXT_OF[ident], None
    return None


def active_states(slc, status, extras, output, freeze, info):
    """The combinable states that are active now, in the priority chosen in the page: ([(id, colour)], {id: full state}). With info, it receives activeList and detail."""
    active = []
    detail = {}

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
    return active, detail


def segment(detail, t, ident, col, cant, blink=True):
    """The stretch of one state: every state has its own effect (steady, slow / medium / fast blink, double flash, pulse); the old ones keep theirs: paused slow, crash fast."""
    level, switched_on = lr.effect_level(detail[ident]["effect"], t) if blink and ident in detail else (255, True)
    if not switched_on:
        return [(0, 0, 0, 0, 0, cant)]
    return [(col["r"], col["u"], col["b"], col.get("w", 0), level, cant)]


def segment_base(base, cant, full=False):
    """The stretch of the mode colour (progress bar): base = (mode colour, brightness, fraction done)."""
    mc, base_p, frac = base
    on = min(cant, int(round(frac * cant)))
    # full (split mode): the zone ALWAYS stays all lit. The mode's stretch is the last and the
    # smallest: with the resting brightness (40) it looked off on the strip (reported
    # 2026-10-09), so in split it goes with visible brightness and what is missing of the
    # progress, dim.
    p_on = max(base_p, 120) if full else base_p
    rest_p = max(60, int(base_p * 0.35)) if full else 0
    rest = (mc.get("r", 0), mc.get("u", 0), mc.get("b", 0), mc.get("w", 0), rest_p, cant - on) if full else (0, 0, 0, 0, 0, cant - on)
    return [(mc.get("r", 0), mc.get("u", 0), mc.get("b", 0), mc.get("w", 0), p_on, on), rest]


def split_lengths(k, n):
    """LEDs of each of the k stretches of the zone of n LEDs: the first states weigh more, the mode/base 1."""
    weights = [k - i for i in range(k - 1)] + [1]
    total = float(sum(weights))
    raw = [n * w / total for w in weights]
    length = [max(1, int(c)) for c in raw]
    # biggest remainder first until exactly n LEDs are used
    order_rest = sorted(range(k), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    j = 0
    while sum(length) < n:
        length[order_rest[j % k]] += 1
        j += 1
    while sum(length) > n:
        i_max = max(range(k), key=lambda i: length[i])
        length[i_max] -= 1
    return length


def combine_states(slc, active, detail, base, base_txt, t, n, freeze, info):
    """Several states at once: priority (the first), turns (one at a time) or split (the zone in stretches). Returns (segments, text, ui_color)."""
    comb = slc.get("combine") or {}
    kind = comb.get("mode", "priority")
    names = J([TEXT_OF[i] for i, _ in active])
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
            return segment_base(base, n), M("status_light_names_in_turns", names=names), None
        return segment(detail, t, ident, col, n), M("status_light_names_in_turns", names=names), None
    if kind == "split":
        # The whole zone stays lit and the most important states (first in the priority) receive
        # more LEDs: weight k, k-1, ..., and the mode/base 1.
        items = active[: max(1, n - 1)] + [("base", None)]
        length = split_lengths(len(items), n)
        secs = []
        for (ident, col), cant in zip(items, length):
            secs += segment_base(base, cant, full=True) if ident == "base" else segment(detail, t, ident, col, cant)
        return secs, f"{names} + {base_txt}", None
    # prioridad
    ident, col = active[0]
    return segment(detail, t, ident, col, n), TEXT_OF[ident], None


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

    freeze = output != "screen" and effects_frozen(slc, status, extras)
    whole = whole_zone(slc, status, extras, output, forced, t, n, info)
    if whole is not None:
        return whole
    active, detail = active_states(slc, status, extras, output, freeze, info)

    # base: colour of the mode (progress bar if there is a job from a file)
    working = status in ("processing", "simulating")
    base_p = 255 if working else slc.get("idle_brightness", 40)
    frac = (file_pos or 0) / file_size if working and file_size else (1.0 if not working else 0.0)
    base = (color_for(slc, mode), base_p, frac)
    base_txt = text if working else M("status_light_idle_mode", mode=mode)
    if not active:
        return segment_base(base, n), base_txt, None
    return combine_states(slc, active, detail, base, base_txt, t, n, freeze, info)


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
    mode = real_mode.pick(g.get("selectedMode"), st.get("machineMode")) or "FFF"
    illum = g.get("lightZoneColor")
    if not (isinstance(illum, list) and len(illum) >= 5):
        illum = [0, 0, 0, 0, 0]
    cm = mv.get("currentMove") if isinstance(mv.get("currentMove"), dict) else {}
    axes = [a for a in (mv.get("axes") or [])[:2] if isinstance(a, dict)]
    homed = all(bool(a.get("homed")) for a in axes) if axes else True
    return (str(mode), bool(g.get("statusLedDisabled", False)), [int(x or 0) for x in illum[:5]],
            st.get("status") or "idle", job.get("filePosition") or 0, (job.get("file") or {}).get("size") or 0,
            cm.get("laserPwm") or 0, homed, bool(g.get("ledAnimating", False)))


def rs_values(status):
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
