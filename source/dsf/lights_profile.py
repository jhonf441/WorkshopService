"""The saved lights configuration (config.json "status_light"): its defaults, its cleaning, the state the Lights page reads and the two
files of the board that depend on it (sys/workshop/macros/system/lights.g and the M950 lines of sys/config.g). lights_edit and
lights_probe use it; lights_ops registers their operations.

LED strip configuration (Lights page, WorkshopLights plugin): how many LEDs, how many are lighting and how many are status, colors of the
light, of each mode and of each special state. It is saved in config.json "status_light" (used by status_light.py) and in
0:/sys/workshop/macros/system/lights.g, which declares the globals read by the light macros and sys/daemon.g (ledLightingN, ledStateN,
ledStrip, lightOnColor) -- ledstartup.g calls it at startup, so the values survive a board restart.

The strip is always [lighting: 0..ledLightingN-1][status: ledLightingN..]: with RRF >= 3.5.1 M150 has no start index, painting goes in
order from 0.
"""
import functools
import json
import os
import re

import lights_board
import lights_config as lc
import messages
import paths
import pi_leds
import service_modules
from messages import M

SD = paths.SD
CONFIG_G = os.path.join(SD, "sys", "config.g")
LIGHTS_G = os.path.join(SD, "sys", "workshop", "macros", "system", "lights.g")

DEFAULTS = {
    "active": True,
    # Virtual strip (2026-10-11, "so that you can keep using the lights even if
    # you have no strip"): everything is computed and shown on the screens (bar,
    # Lights, no-limits jog), but no M150 is sent to the board.
    "virtual": False,
    "led_strip": 0,
    "led_start": 10,
    "led_count": 10,
    "order": "lighting_first",  # or "state_first": which zone goes at the start of the strip
    "idle_brightness": 40,
    "effects_in_job": "without_effects",
    "light_color": {"r": 0, "u": 0, "b": 255, "w": 255, "p": 255},
    "mode_colors": {
        "Laser": {"r": 140, "u": 0, "b": 255, "w": 0},  # violet: the red is the stop's
        "CNC": {"r": 0, "u": 0, "b": 255, "w": 0},
        "FFF": {"r": 0, "u": 255, "b": 0, "w": 0},
    },
    "state_colors": {
        "stop": {"r": 255, "u": 0, "b": 0, "w": 0},
        "paused": {"r": 255, "u": 120, "b": 0, "w": 0},
        "cancelling": {"r": 255, "u": 0, "b": 255, "w": 0},
        "busy": {"r": 255, "u": 255, "b": 255, "w": 0},
    },
    # startup animation (sys/ledstartup.g): bar | blink | center | rainbow
    "animation": {"active": True, "kind": "bar", "color": {"r": 0, "u": 180, "b": 255, "w": 0}, "step": 6},
    # effects during use (status_light.py)
    "effects": {
        "end_job": {"active": True, "color": {"r": 0, "u": 255, "b": 0, "w": 0}, "times": 3},
        "blink_pause": True,
        # no-limits jog / crash: they show in the status zone even if the automatic
        # status lights are off (2026-10-10)
        "jog_free_always": True,
    },
    # extra zones (2026-10-09): at the END of the strip, after lighting and
    # status, each with its own color and switch. The board macros
    # (lighton.g, daemon.g) only paint the first two zones and do not touch them.
    "zones_extra": [],
    # additional strips (2026-10-10): each with its E number (M950 E<n> in
    # config.g), its name and its zones (color + switch). Status and
    # lighting live only on the main strip.
    "strips_extra": [],
    # Board LEDs at the end of the status zone (2026-10-11): a copy of the
    # Duet's LEDs (STATUS/CAN, VIN, 12 V, 5 V, 3.3 V) with their colors and their
    # blinking; they are subtracted from the end of the zone (lights_board.apply_leds_board)
    "leds_board": {"active": False, "leds": ["can", "vin", "v12", "v5", "v3_3"], "brightness": 120},
    # Board status strip (2026-10-11): VIRTUAL ONLY (screens), one LED
    # per thing of the object model (lights_board.state_board)
    "strip_state": {"active": False, "groups": ["board", "final", "probes", "fans", "heaters", "laser", "outputs"]},
    # Output of the main strip: the Duet (default) or a pin of the Pi (advanced, experimental; pi_leds.py). The additional
    # strips carry their own "salida".
    "output": {"kind": "duet", "pin": 20, "order": "GRBW", "brightness": 60},
}
DEFAULTS.update({
    "strip": {"present": True},
    "order_states": [],
    "work_light": lc.DEFAULT_WORK,
    "night": lc.DEFAULT_NIGHT,
    "power": lc.DEFAULT_POWER,
    "pi_hot_c": lc.DEFAULT_PI_HOT_C,
    "live_quiet_s": lc.DEFAULT_LIVE_QUIET_S,
})
# What belongs to the hardware of THIS machine (not to a lighting profile)
HARDWARE_KEYS = ("strip", "active", "virtual", "led_strip", "led_start", "led_count", "order", "order_zones", "zones_extra",
                 "strips_extra", "zone_state", "leds_board", "strip_state", "output", "power")
ZONE_EXTRA_COLOR = {"r": 255, "u": 255, "b": 255, "w": 0, "p": 255}

KINDS_ANIMATION = ("bar", "blink", "center", "rainbow")
MODES_COMBINE = ("priority", "turns", "split")


def answer(obj):
    """The answer of an operation: every message in the language of the request (the state names are made at import time), as JSON data."""
    return json.loads(json.dumps(messages.localize(obj, messages.current_language())))


def needs_lights(fn):
    """The operation refuses while the lights plugin is stopped or disabled (service_modules.py): the service does not touch the lights;
    only the query keeps answering."""
    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        if not service_modules.is_active(service_modules.LIGHTS):
            return answer({"ok": False, "error": M("lights_lights_states_stopped_settings_plugins_lights")})
        return fn(*args, **kwargs)
    return guarded


def no_strip():
    return answer({"ok": False, "code": "no_strip", "error": "This machine has no LED strip: nothing to send to the board"})


def byte(v, default=0):
    try:
        return max(0, min(255, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def color(c, default, with_brightness=False):
    c = c if isinstance(c, dict) else {}
    out = {k: byte(c.get(k, default.get(k, 0))) for k in ("r", "u", "b", "w")}
    if with_brightness:
        out["p"] = byte(c.get("p", default.get("p", 255)), 255)
    return out


def integer(v, default, minimum=None, maximum=None):
    # an empty or odd field of the page ("" from a deleted input) breaks nothing
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        n = default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


def _name(raw, default_key):
    return str(raw or "").strip()[:30] or str(M(default_key))


def _unique_id(raw, prefix, used):
    """The id of a zone or strip: the one given if it has the prefix and is free, else the first free <prefix><n>."""
    ident = str(raw or "")
    if not ident.startswith(prefix) or ident in used:
        ident = next("%s%d" % (prefix, k) for k in range(1, 50) if "%s%d" % (prefix, k) not in used)
    used.add(ident)
    return ident


def _clean_zones(sl):
    zones, used = [], set()
    for z in (sl.get("zones_extra") or [])[:6]:
        if not isinstance(z, dict):
            continue
        n = integer(z.get("n"), 1, 1, 200)
        zones.append({
            "id": _unique_id(z.get("id"), "z", used),
            "name": _name(z.get("name"), "lights_zone_default_name"),
            "n": n,
            "color": color(z.get("color"), ZONE_EXTRA_COLOR, True),
            "on": bool(z.get("on", True)),
        })
    return zones


def _clean_strip_zones(t):
    zones, used = [], set()
    for z in (t.get("zones") or [])[:8]:
        if not isinstance(z, dict):
            continue
        zones.append({
            "id": _unique_id(z.get("id"), "z", used),
            "name": _name(z.get("name"), "lights_zone_default_name"),
            "n": integer(z.get("n"), 1, 1, 200),
            "color": color(z.get("color"), ZONE_EXTRA_COLOR, True),
            "on": bool(z.get("on", True)),
        })
    return zones


def _clean_strips(sl):
    strips, used = [], set()
    for t in (sl.get("strips_extra") or [])[:4]:
        if not isinstance(t, dict):
            continue
        tid = _unique_id(t.get("id"), "t", used)
        zones = _clean_strip_zones(t)
        strips.append({
            "id": tid,
            "name": _name(t.get("name"), "lights_strip_default_name"),
            "led_strip": integer(t.get("led_strip"), 1, 0, 9),
            "output": pi_leds.normalize_output(t.get("output")),
            "zones": zones,
        })
    return strips


def _order_zones(sl, out):
    """Order of ALL zones on the strip, from the connector (2026-10-10: the extra zones can be placed anywhere). Without a saved order:
    the one of "order" (status/lighting) and the extra ones at the end, as before."""
    ids = ["state", "lighting"] + [z["id"] for z in out["zones_extra"]]
    request = [i for i in (sl.get("order_zones") or []) if i in ids]
    if len(set(request)) != len(request) or not request:
        request = (["state", "lighting"] if out["order"] == "state_first" else ["lighting", "state"])
    return request + [i for i in ids if i not in request]


def _zone_state(sl, out):
    """Status zone (2026-10-10): "main", "none" or "<strip>:<zone>" of an additional strip. If that zone no longer exists it goes back to
    "main"."""
    ze = str(sl.get("zone_state") or "main")
    valid = ["main", "none"] + ["%s:%s" % (t["id"], z["id"]) for t in out["strips_extra"] for z in t["zones"]]
    ze = ze if ze in valid else "main"
    if out["virtual"] and ":" in ze:
        ze = "main"  # without a strip there are no zones on other strips
    return ze


def _leds_board(sl, nw):
    """Board LEDs (2026-10-11)."""
    lp = sl.get("leds_board") if isinstance(sl.get("leds_board"), dict) else {}
    leds = lp.get("leds") if isinstance(lp.get("leds"), list) else DEFAULTS["leds_board"]["leds"]
    return {
        "active": bool(lp.get("active", False)),
        "leds": [i for i in lights_board.LEDS_BOARD_IDS if i in leds],  # fixed order, no repeated or unknown ones
        "brightness": integer(lp.get("brightness"), DEFAULTS["leds_board"]["brightness"], 1, 255),
        # what the board LEDs do when the lighting takes the status zone (2026-10-13: it was never saved)
        "with_lighting": "as_zone" if lp.get("with_lighting") == "as_zone" else "keep",
        # the CAN LED of the board: lit while the CAN is fine ("falla", default) or the slow blink of the board ("siempre")
        "can_blink": "always" if lp.get("can_blink") == "always" else "fault",
        "vin_min": nw["board_thresholds"]["vin_min"],
        "v12_min": nw["board_thresholds"]["v12_min"],
    }


def _strip_state(sl):
    """Board status strip (2026-10-11)."""
    te = sl.get("strip_state") if isinstance(sl.get("strip_state"), dict) else {}
    gr = te.get("groups") if isinstance(te.get("groups"), list) else DEFAULTS["strip_state"]["groups"]
    return {"active": bool(te.get("active", False)), "groups": [g for g in lights_board.GROUPS_STRIP_STATE if g in gr]}


def _animation(sl):
    an = sl.get("animation") if isinstance(sl.get("animation"), dict) else {}
    try:
        step = max(1, min(60, int(an.get("step", 6))))
    except (TypeError, ValueError):
        step = 6
    return {
        "active": bool(an.get("active", True)),
        "kind": an.get("kind") if an.get("kind") in KINDS_ANIMATION else "bar",
        "color": color(an.get("color"), DEFAULTS["animation"]["color"]),
        "step": step,
    }


def _combine(sl):
    cb = sl.get("combine") if isinstance(sl.get("combine"), dict) else {}
    try:
        turn = max(0.5, min(10.0, float(cb.get("turn_s", 1.5))))
    except (TypeError, ValueError):
        turn = 1.5
    return {"mode": cb.get("mode") if cb.get("mode") in MODES_COMBINE else "priority", "turn_s": turn,
            "si_no_fit": cb.get("si_no_fit") if cb.get("si_no_fit") in ("turns", "hide") else "turns"}


def _effects(sl, states):
    ef = sl.get("effects") if isinstance(sl.get("effects"), dict) else {}
    ft = ef.get("end_job") if isinstance(ef.get("end_job"), dict) else {}
    dft = DEFAULTS["effects"]["end_job"]
    try:
        times = max(1, min(10, int(ft.get("times", dft["times"]))))
    except (TypeError, ValueError):
        times = dft["times"]
    return {
        "end_job": {"active": bool(ft.get("active", dft["active"])), "color": color(ft.get("color"), dft["color"]), "times": times},
        # the old "blink while paused" switch is now the effect of the Paused state
        "blink_pause": states["paused"]["effect"] != "steady",
        "jog_free_always": bool(ef.get("jog_free_always", DEFAULTS["effects"]["jog_free_always"])),
    }


def clean(config):
    """The configuration of the lights in `config`, complete and with every value in range (the same cleaning on every read and save)."""
    sl = config.get("status_light") or {}
    nw = lc.normalize_new(sl)
    out = {
        # the screen indicator is always available; "virtual" now just means "no physical strip"
        "strip": nw["strip"],
        "active": True,
        "virtual": not nw["strip"]["present"],
        "led_strip": integer(sl.get("led_strip"), DEFAULTS["led_strip"], 0, 9),
        "order": "state_first" if sl.get("order") == "state_first" else "lighting_first",
        "led_start": integer(sl.get("led_start"), DEFAULTS["led_start"], 0, 400),
        "led_count": integer(sl.get("led_count"), DEFAULTS["led_count"], 1, 400),
        "idle_brightness": byte(sl.get("idle_brightness", DEFAULTS["idle_brightness"]), 40),
        # during a job the strip keeps its colours but not its blinks (see lights_decide.effects_frozen)
        "effects_in_job": "with_effects" if sl.get("effects_in_job") == "with_effects" else "without_effects",
        "light_color": color(sl.get("light_color"), DEFAULTS["light_color"], True),
        "mode_colors": {},
        "state_colors": {},
    }
    for k, d in DEFAULTS["mode_colors"].items():
        out["mode_colors"][k] = color((sl.get("mode_colors") or {}).get(k), d)
    for k, d in DEFAULTS["state_colors"].items():
        out["state_colors"][k] = color((sl.get("state_colors") or {}).get(k), d)
    out["zones_extra"] = _clean_zones(sl)
    out["strips_extra"] = _clean_strips(sl)
    out["order_zones"] = _order_zones(sl, out)
    out["order"] = "state_first" if out["order_zones"].index("state") < out["order_zones"].index("lighting") else "lighting_first"
    out["zone_state"] = _zone_state(sl, out)
    out["leds_board"] = _leds_board(sl, nw)
    out["strip_state"] = _strip_state(sl)
    out["output"] = pi_leds.normalize_output(sl.get("output"))
    out["animation"] = _animation(sl)
    # known states (lights_config.STATES): colour, effect, and the outputs (strip / screen / board) each one is shown on; old configs
    # without the new keys give exactly what they always did
    out["states"] = nw["states"]
    out["order_states"] = nw["order_states"]
    out["work_light"] = nw["work_light"]
    out["night"] = nw["night"]
    out["power"] = nw["power"]
    out["pi_hot_c"] = nw["pi_hot_c"]
    out["live_quiet_s"] = nw["live_quiet_s"]
    out["combine"] = _combine(sl)
    out["effects"] = _effects(sl, out["states"])
    return out


def m950(led_strip):
    """M950 E<strip> line of config.g and its U (declared number of LEDs)."""
    try:
        with open(CONFIG_G, encoding="utf-8") as f:
            for line in f:
                if re.match(rf"^\s*M950\s+E{int(led_strip)}\b", line):
                    m = re.search(r"\bU(\d+)", line.split(";")[0])
                    return {"line": line.rstrip("\n"), "total": int(m.group(1)) if m else None}
    except OSError:
        pass
    return {"line": None, "total": None}


def _lights_g_lines(c):
    lc_ = c["light_color"]
    an = c["animation"]
    ac = an["color"]
    return [
        "; sys/workshop/macros/system/lights.g -- generated by the Lights page (lights_profile.py). Do not edit by hand:",
        "; it is rewritten on every save. sys/ledstartup.g calls it at startup.",
        # "There is an LED strip on this machine" (2026-10-09): with false, daemon.g,
        # ledstartup.g and the light macros send no M150 (there is no strip)
        "if !exists(global.ledHasStrip)\n  global ledHasStrip = true",
        f"set global.ledHasStrip = {'true' if c['strip']['present'] else 'false'}",  # without a strip the board paints nothing
        f"if !exists(global.ledLightingN)\n  global ledLightingN = {c['led_start']}",
        f"if !exists(global.ledStateN)\n  global ledStateN = {c['led_count']}",
        f"if !exists(global.ledStrip)\n  global ledStrip = {c['led_strip']}",
        "if !exists(global.ledOrder)\n  global ledOrder = 0",
        f"if !exists(global.lightOnColor)\n  global lightOnColor = {{0, 0, 0, 0, 0}}",
        f"set global.ledLightingN = {c['led_start']}",
        f"set global.ledStateN = {c['led_count']}",
        f"set global.ledStrip = {c['led_strip']}",
        f"set global.ledOrder = {1 if c['order'] == 'state_first' else 0}",
        f"set global.lightOnColor = {{{lc_['r']}, {lc_['u']}, {lc_['b']}, {lc_['w']}, {lc_['p']}}}",
        "if !exists(global.ledAnimActive)\n  global ledAnimActive = true",
        "if !exists(global.ledAnimColor)\n  global ledAnimColor = {0, 0, 0, 0}",
        "if !exists(global.ledAnimStep)\n  global ledAnimStep = 6",
        f"set global.ledAnimActive = {'true' if an['active'] else 'false'}",
        f"set global.ledAnimColor = {{{ac['r']}, {ac['u']}, {ac['b']}, {ac['w']}}}",
        f"set global.ledAnimStep = {an['step']}",
        "if !exists(global.ledAnimKind)\n  global ledAnimKind = \"barra\"",
        f"set global.ledAnimKind = \"{an['kind']}\"",
        # mode colors for sys/daemon.g when it paints on its own (fallback)
        *[ln for m in ("FFF", "Laser", "CNC") for ln in (
            "if !exists(global.ledColor%s)\n  global ledColor%s = {0, 0, 0}" % (m, m),
            "set global.ledColor%s = {%d, %d, %d}" % (m, c["mode_colors"][m]["r"], c["mode_colors"][m]["u"], c["mode_colors"][m]["b"]))],
        "if exists(global.statusLedKey)\n  set global.statusLedKey = \"\"",
        "",
    ]


def write_lights_g(c):
    """Writes lights.g (the globals of the board) for the cleaned configuration `c`."""
    os.makedirs(os.path.dirname(LIGHTS_G), exist_ok=True)
    tmp = LIGHTS_G + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(_lights_g_lines(c)))
        f.flush()
        os.fsync(f.fileno())  # to the card before the rename (power cut)
    os.replace(tmp, LIGHTS_G)


def state(config):
    """What the Lights page reads: the cleaned configuration, the M950 lines and what it needs to know about the states."""
    c = clean(config)
    # the M950 line of each configured strip (main and additional)
    everything = {str(e): m950(e) for e in [c["led_strip"]] + [t["led_strip"] for t in c["strips_extra"]]}
    return {"ok": True, "config": c, "m950": m950(c["led_strip"]), "m950_all": everything, "lights_g": os.path.isfile(LIGHTS_G),
            # what the page needs to know about the states (kind, defaults) and the options
            "catalog": lc.catalog(), "effects": list(lc.EFFECTS), "outputs": list(lc.OUTPUTS), "max_scenes": lc.MAX_SCENES}


def strip_of(c, strip):
    """Strip requested with its E number (the page's tools); without it, the main one. Returns (E, extra_strip or None)."""
    try:
        e = int(float(strip))
    except (TypeError, ValueError):
        return c["led_strip"], None
    return e, next((t for t in c["strips_extra"] if t["led_strip"] == e), None)
