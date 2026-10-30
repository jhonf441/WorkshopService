"""
Lights and status: configuration model (pure code, no DSF, no network).

The "Lights and status" page controls THREE independent outputs:

  strip   a physical LED strip (only on machines that have one),
  screen  the status indicator shown in the DWC page header, the sidebar,
          the DWC chip and the jog header (always available),
  board   the copy of the Duet board LEDs (CAN, VIN, 12 V, 5 V, 3.3 V).

Every machine state (emergency, paused, laser firing...) says on which of
these outputs it is shown, with which colour and with which effect.

This module owns:
  - the catalogue of states (STATES) and the effects (EFFECTS),
  - the defaults of everything added by the redesign,
  - the normalisation of the saved config (normalize_new), which also
    migrates configs saved before the redesign: a config without the new keys
    behaves exactly as it did before (same states, colours, blink patterns,
    board LEDs and "strip present" derived from the old `activo`/`virtual`).

Old keys that are kept as they were: activo, virtual, estados[id].activo/color,
state_colors, leds_board.activo/leds/brillo, efectos.blink_pause,
order_zones... (see handlers/lights.py).
"""
import re
from messages import M

# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------
# steady      always on
# blink_slow  0.8 s on / 0.8 s off
# blink       0.6 s on / 0.6 s off
# blink_fast  0.4 s on / 0.4 s off
# double      two short flashes, then a pause (1.6 s cycle)
# pulse       brightness goes up and down smoothly (2.4 s cycle)
EFFECTS = ("steady", "blink_slow", "blink", "blink_fast", "double", "pulse")
EFFECT_PERIOD = {"blink_slow": 0.8, "blink": 0.6, "blink_fast": 0.4}
OUTPUTS = ("strip", "screen", "board")

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
# kind:
#   emergency   always on, always the whole zone, cannot be turned off
#   exclusive   takes the whole zone and wins over everything else, whatever
#               the "when several at once" mode is (fixed on top of the list)
#   combinable  combined with the others (priority / turns / split)
# id, Spanish name (user-visible, published to the screens), default colour,
# default active, kind, default effect
_C = lambda r, u, b, w=0: {"r": r, "u": u, "b": b, "w": w}  # noqa: E731
STATES = [
    ("stop", M("lights_config_emergency_stop"), _C(255, 0, 0), True, "emergency", "steady"),
    ("psu_off", M("lights_config_power_supply_off_no_power_motors"), _C(0, 255, 150), True, "combinable", "blink_slow"),
    ("crash", M("lights_config_crash_or_axis_beyond_limits"), _C(255, 100, 100), True, "exclusive", "double"),
    ("jog_free", M("lights_config_jog_without_limits_active"), _C(0, 0, 0, 255), True, "exclusive", "blink_slow"),
    ("risk", M("lights_config_active_risk_without_protection"), _C(255, 0, 120), True, "exclusive", "blink"),
    ("cancelling", M("lights_config_cancelling"), _C(255, 0, 255), True, "combinable", "double"),
    ("paused", M("lights_config_paused"), _C(255, 120, 0), True, "combinable", "pulse"),
    ("rs485", M("lights_config_fault_rs485_device"), _C(200, 60, 255), True, "combinable", "blink"),
    ("rs485_notice", M("lights_config_rs485_warning_device_no_axis"), _C(0, 100, 255), True, "combinable", "blink_fast"),
    # Colors, effects and which states are on are the owner's machine (2026-10-24): a new install starts like it.
    ("pi_hot", M("lights_config_high_equipment_temperature"), _C(255, 190, 0), False, "combinable", "blink"),
    ("busy", M("lights_config_busy_homing_macro"), _C(255, 255, 255), True, "combinable", "steady"),
    ("laser", M("lights_config_laser_firing"), _C(255, 255, 120), True, "combinable", "blink_slow"),
    ("air", M("lights_config_air_on"), _C(0, 200, 255), True, "combinable", "double"),
    ("in_live", M("lights_config_live_job_running"), _C(150, 255, 0), True, "combinable", "pulse"),
    ("live_quiet", M("lights_config_live_job_open_idle"), _C(80, 255, 80), False, "combinable", "pulse"),
    ("without_homing", M("lights_config_homing_missing"), _C(169, 94, 106), True, "combinable", "blink"),
    ("motors_released", M("lights_config_loose_motors_no_power"), _C(140, 100, 255), False, "combinable", "steady"),
    ("unclean_shutdown", M("lights_config_last_shutdown_was_not_clean"), _C(255, 140, 200), False, "combinable", "double"),
]
STATE_IDS = [s[0] for s in STATES]
STATE_KIND = {s[0]: s[4] for s in STATES}
STATE_TEXT = {s[0]: s[1] for s in STATES}
_STATE = {s[0]: s for s in STATES}
# the ones the user can reorder (the others are fixed on top)
COMBINABLE_IDS = [s[0] for s in STATES if s[4] == "combinable"]

# Defaults of the numbers used by the new states
DEFAULT_PI_HOT_C = 75          # same as the Pi health alert
DEFAULT_LIVE_QUIET_S = 60      # live job open and the machine idle this long


def default_outputs(ident):
    """Where a state is shown by default. Board: off for all (the board LED
    positions keep showing the board LEDs, as before the redesign)."""
    return {"strip": True, "screen": True, "board": False}


def default_effect(ident, blink_pause=True):
    """Default effect of a state. "pausado" followed the old switch "blink
    while paused" (efectos.blink_pause)."""
    eff = _STATE[ident][5]
    if ident == "paused" and not blink_pause:
        return "steady"
    return eff


def catalog():
    """What the page needs to know about every state."""
    return {
        s[0]: {"text": s[1], "kind": s[4], "color": dict(s[2]), "active": s[3], "effect": s[5], "outputs": default_outputs(s[0])}
        for s in STATES
    }


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------
def _byte(v, default=0):
    try:
        return max(0, min(255, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _int(v, default, lo=None, hi=None):
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def _float(v, default, lo=None, hi=None):
    try:
        n = float(v)
    except (TypeError, ValueError):
        n = default
    if n != n:  # NaN
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def _color(c, default, with_brightness=False):
    c = c if isinstance(c, dict) else {}
    out = {k: _byte(c.get(k, default.get(k, 0))) for k in ("r", "u", "b", "w")}
    if with_brightness:
        out["p"] = _byte(c.get("p", default.get("p", 255)), 255)
    return out


_HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def parse_hhmm(v, default):
    """"22:30" -> minutes since midnight; anything odd -> default."""
    m = _HHMM.match(str(v or ""))
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return default
    return h * 60 + mi


def fmt_hhmm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


# ---------------------------------------------------------------------------
# Strip present
# ---------------------------------------------------------------------------
def has_strip(slc):
    """Does this machine have a physical LED strip?

    New configs: strip.present. Old configs: the old switch "this machine has
    an LED strip" (activo) with the old "virtual strip" (virtual) meaning "no
    strip, screens only". Without a strip nothing is sent to the board."""
    slc = slc or {}
    st = slc.get("strip")
    if isinstance(st, dict) and "present" in st:
        return bool(st["present"])
    return bool(slc.get("active", True)) and not bool(slc.get("virtual", False))


# ---------------------------------------------------------------------------
# States: normalisation
# ---------------------------------------------------------------------------
def state_full(slc, ident):
    """Complete configuration of a state, from a raw (possibly old) config:
    {active, color, effect, outputs{strip,screen,board}}. Works with configs
    that were saved before the redesign."""
    slc = slc or {}
    d = _STATE[ident]
    est = (slc.get("states") or {}).get(ident)
    est = est if isinstance(est, dict) else {}
    old = (slc.get("state_colors") or {}).get(ident)
    color = est.get("color") or old or d[2]
    active = True if ident == "stop" else bool(est.get("active", d[3]))
    pp = (slc.get("effects") or {}).get("blink_pause", True)
    effect = est.get("effect")
    if effect not in EFFECTS:
        effect = default_effect(ident, bool(pp))
    kind = d[4]
    if kind == "emergency":
        effect = "steady"
    outs = est.get("outputs") if isinstance(est.get("outputs"), dict) else {}
    dflt = default_outputs(ident)
    outputs = {k: bool(outs.get(k, dflt[k])) for k in OUTPUTS}
    if kind == "emergency":
        outputs["strip"] = outputs["screen"] = True  # the emergency is always shown
    return {"active": active, "color": _color(color, d[2]), "effect": effect, "outputs": outputs}


def state_order(slc):
    """The combinable states from the most to the least important. Unknown ids
    are ignored; missing ones go where the catalogue puts them."""
    want = [i for i in ((slc or {}).get("order_states") or []) if i in COMBINABLE_IDS]
    seen = []
    for i in want:
        if i not in seen:
            seen.append(i)
    out = list(seen)
    for i in COMBINABLE_IDS:
        if i not in out:
            # keep the catalogue position relative to the neighbours already placed
            pos = COMBINABLE_IDS.index(i)
            before = [x for x in COMBINABLE_IDS[:pos] if x in out]
            out.insert(out.index(before[-1]) + 1 if before else 0, i)
    return out


# ---------------------------------------------------------------------------
# Work light, night dimming, power, board thresholds
# ---------------------------------------------------------------------------
# The names are message keys: a new install saves them in DWC's language (default_scenes()), and the pages show a
# name that is still one of these defaults (in either language) in their own language (DEFAULT_NAME_KEYS).
DEFAULT_SCENES = [
    {"id": "job", "name": "lights_scene_job", "color": {"r": 0, "u": 0, "b": 255, "w": 255, "p": 255}},
    {"id": "photo", "name": "lights_scene_photo", "color": {"r": 0, "u": 0, "b": 0, "w": 255, "p": 255}},
    {"id": "inspeccion", "name": "lights_config_inspection", "color": {"r": 255, "u": 255, "b": 255, "w": 255, "p": 255}},
    {"id": "dim", "name": "lights_scene_dim", "color": {"r": 60, "u": 20, "b": 0, "w": 255, "p": 70}},
]
# every default name of the Lights page (scenes, extra zones, extra strips): the page translates these
DEFAULT_NAME_KEYS = [s["name"] for s in DEFAULT_SCENES] + ["lights_scene_default_name", "lights_zone_default_name", "lights_strip_default_name"]


def default_scenes():
    """The factory scenes with their names in the language of the caller (DWC's outside a request)."""
    return [dict(s, name=str(M(s["name"]))) for s in DEFAULT_SCENES]
MAX_SCENES = 8
DEFAULT_WORK = {"scene": "", "auto_off": {"enabled": False, "minutes": 30}, "auto_on_job": False}
DEFAULT_NIGHT = {"enabled": False, "from": "22:00", "to": "07:00", "level": 25, "include_work_light": True}
DEFAULT_POWER = {"ma_per_channel": 20, "limit_ma": 0}
DEFAULT_BOARD_THRESHOLDS = {"vin_min": 4.5, "v12_min": 6.0}


def normalize_scenes(raw):
    out, used = [], set()
    src = raw if isinstance(raw, list) else default_scenes()
    for s in src[:MAX_SCENES]:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "")
        sid = re.sub(r"[^a-z0-9_]", "", sid.lower())
        if not sid or sid in used:
            sid = next("s%d" % k for k in range(1, 99) if "s%d" % k not in used)
        used.add(sid)
        out.append({
            "id": sid,
            "name": str(s.get("name") or "").strip()[:24] or str(M("lights_scene_default_name")),
            "color": _color(s.get("color"), {"r": 0, "u": 0, "b": 0, "w": 255, "p": 255}, True),
        })
    return out


def normalize_new(sl):
    """Everything the redesign added to the saved config, cleaned and with
    defaults. `sl` is the raw status_light config (old or new). Pure."""
    sl = sl if isinstance(sl, dict) else {}
    out = {}
    present = has_strip(sl)
    out["strip"] = {"present": present}
    # the old switches mean the same thing: activo is always on (the screen
    # indicator is always available); virtual = "no physical strip"
    out["active"] = True
    out["virtual"] = not present
    # states
    est = {}
    for ident in STATE_IDS:
        f = state_full(sl, ident)
        est[ident] = {"text": STATE_TEXT[ident], "active": f["active"], "color": f["color"], "effect": f["effect"], "outputs": f["outputs"]}
    out["states"] = est
    out["order_states"] = state_order(sl)
    # board LEDs (kept in leds_board): thresholds
    lp = sl.get("leds_board") if isinstance(sl.get("leds_board"), dict) else {}
    out["board_thresholds"] = {
        "vin_min": _float(lp.get("vin_min"), DEFAULT_BOARD_THRESHOLDS["vin_min"], 0.0, 60.0),
        "v12_min": _float(lp.get("v12_min"), DEFAULT_BOARD_THRESHOLDS["v12_min"], 0.0, 30.0),
    }
    # work light
    wl = sl.get("work_light") if isinstance(sl.get("work_light"), dict) else {}
    scenes = normalize_scenes(wl.get("scenes") if "scenes" in wl else None)
    ao = wl.get("auto_off") if isinstance(wl.get("auto_off"), dict) else {}
    scene = str(wl.get("scene") or "")
    out["work_light"] = {
        "scenes": scenes,
        "scene": scene if scene in [s["id"] for s in scenes] else "",
        "auto_off": {
            "enabled": bool(ao.get("enabled", DEFAULT_WORK["auto_off"]["enabled"])),
            "minutes": _int(ao.get("minutes"), DEFAULT_WORK["auto_off"]["minutes"], 1, 600),
        },
        "auto_on_job": bool(wl.get("auto_on_job", DEFAULT_WORK["auto_on_job"])),
    }
    # night dimming
    ng = sl.get("night") if isinstance(sl.get("night"), dict) else {}
    out["night"] = {
        "enabled": bool(ng.get("enabled", DEFAULT_NIGHT["enabled"])),
        "from": fmt_hhmm(parse_hhmm(ng.get("from"), parse_hhmm(DEFAULT_NIGHT["from"], 1320))),
        "to": fmt_hhmm(parse_hhmm(ng.get("to"), parse_hhmm(DEFAULT_NIGHT["to"], 420))),
        "level": _int(ng.get("level"), DEFAULT_NIGHT["level"], 1, 100),
        "include_work_light": bool(ng.get("include_work_light", DEFAULT_NIGHT["include_work_light"])),
    }
    # power estimate
    pw = sl.get("power") if isinstance(sl.get("power"), dict) else {}
    out["power"] = {
        "ma_per_channel": _int(pw.get("ma_per_channel"), DEFAULT_POWER["ma_per_channel"], 1, 60),
        "limit_ma": _int(pw.get("limit_ma"), DEFAULT_POWER["limit_ma"], 0, 100000),
    }
    # thresholds of the new states
    out["pi_hot_c"] = _int(sl.get("pi_hot_c"), DEFAULT_PI_HOT_C, 40, 95)
    out["live_quiet_s"] = _int(sl.get("live_quiet_s"), DEFAULT_LIVE_QUIET_S, 10, 3600)
    return out


def merge_into(sl, cleaned_new):
    """Writes the normalised new keys into the raw config `sl` (a dict that
    will be saved). leds_board keeps its old keys and gets the thresholds."""
    sl = sl if isinstance(sl, dict) else {}
    for k in ("strip", "active", "virtual", "order_states", "work_light", "night", "power", "pi_hot_c", "live_quiet_s"):
        sl[k] = cleaned_new[k]
    lp = sl.get("leds_board") if isinstance(sl.get("leds_board"), dict) else {}
    lp = dict(lp)
    lp.update(cleaned_new["board_thresholds"])
    sl["leds_board"] = lp
    return sl
