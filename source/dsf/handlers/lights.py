"""
Internal implementation of the API operation(s) lights.get, lights.save, lights.test, lights.identify, lights.animation, lights.preview, lights.apply_m950, lights.zone, lights.test_state, lights.scene, lights.schedule, lights.import (api_ops.py maps their named
arguments to the one-letter parameters below).

LED strip configuration (Lights page, WorkshopLights plugin): how many LEDs,
how many are lighting and how many are status, colors of the light, of each
mode and of each special state. It is saved in config.json "status_light"
(used by status_light.py) and in 0:/sys/workshop/macros/lights.g, which
declares the globals read by the light macros and sys/daemon.g
(ledLightingN, ledStateN, ledStrip, lightOnColor) -- ledstartup.g calls it at
startup, so the values survive a board restart.

The strip is always [lighting: 0..ledLightingN-1][status: ledLightingN..]: with
RRF >= 3.5.1 M150 has no start index, painting goes in order from 0.

Usage: <params>                        -> query (JSON)
     <params> C"guardar" J"<hex json>" -> saves (config JSON, in hex
                                                because quotes do not pass in G-code)
     <params> C"probar" N<n> D<sec>    -> lights the first n LEDs for a few
                                                seconds (to count them)
     <params> C"identificar" D<sec>    -> paints each zone a color
     <params> C"animacion"             -> runs the startup animation now
     <params> C"apply_m950" N<total> -> changes U<total> in the M950 line of
                                                sys/config.g (with a copy); M999 is needed

Redesign (2026-10-12), new English actions:
     <params> C"test_state" S"<state id>" [D<s>] [O"strip,screen,board"] [J{color,effect}]
                                             -> shows one state for a few seconds on
                                                the chosen outputs (default: the ones
                                                the state is checked for)
     <params> C"scene" S"<scene id>"  -> work light scene, one tap (or J = a colour)
     <params> C"schedule" S1|S0       -> night dimming on / off
     <params> C"import" J|F [H1]      -> checks a profile exported by the page and
                                                returns it normalised WITHOUT saving
                                                (H1 also takes the hardware layout)

"""
import paths
import json
import os
import re
import shutil
import time

import activity
import lights_config as lc
import service_modules
import messages
from messages import M, J, B


def _dumps(obj):
    """JSON of the answer with every message in the language of the request (the state names are made at import time)."""
    return json.dumps(messages.localize(obj, messages.current_language()))


SD = paths.SD
CONFIG_G = os.path.join(SD, "sys", "config.g")
LIGHTS_G = os.path.join(SD, "sys", "workshop", "macros", "lights.g")

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
    # blinking; they are subtracted from the end of the zone (status_light.apply_leds_board)
    "leds_board": {"active": False, "leds": ["can", "vin", "v12", "v5", "v3_3"], "brightness": 120},
    # Board status strip (2026-10-11): VIRTUAL ONLY (screens), one LED
    # per thing of the object model (status_light.state_board)
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



# 2026-10-10 ("Could not apply: Unexpected token 'E'"): the JSON in hex
# inside the command (J"...") exceeded the maximum length of a DSF code
# ("Failed to serialize code (too long?)") with several strips and zones. Now
# the page, if it is long, writes it to SENDING_FILE and sends F"0:/sys/..." (only
# that file); J still serves for small ones.
SENDING_FILE = "0:/sys/workshop/data/lights-send.json"
SENDING_PATH = paths.DATA_DIR + "/lights-send.json"


def _has_json(params):
    j = params.get("J")
    return (j is not None and j != "") or str(params.get("F", "")).strip() == SENDING_FILE


def _json_param(params):
    if str(params.get("F", "")).strip() == SENDING_FILE:
        with open(SENDING_PATH, encoding="utf-8") as f:
            return json.loads(f.read())
    j = params.get("J")
    if isinstance(j, (dict, list)):
        return j  # API: the object itself
    return json.loads(bytes.fromhex(str(j or "")).decode("utf-8"))


def _byte(v, default=0):
    try:
        return max(0, min(255, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _color(c, default, with_brightness=False):
    c = c if isinstance(c, dict) else {}
    out = {k: _byte(c.get(k, default.get(k, 0))) for k in ("r", "u", "b", "w")}
    if with_brightness:
        out["p"] = _byte(c.get("p", default.get("p", 255)), 255)
    return out


def _integer(v, default, minimum=None, maximum=None):
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


def _cfg(config):
    sl = config.get("status_light") or {}
    nw = lc.normalize_new(sl)
    out = {
        # the screen indicator is always available; "virtual" now just means "no physical strip"
        "strip": nw["strip"],
        "active": True,
        "virtual": not nw["strip"]["present"],
        "led_strip": _integer(sl.get("led_strip"), DEFAULTS["led_strip"], 0, 9),
        "order": "state_first" if sl.get("order") == "state_first" else "lighting_first",
        "led_start": _integer(sl.get("led_start"), DEFAULTS["led_start"], 0, 400),
        "led_count": _integer(sl.get("led_count"), DEFAULTS["led_count"], 1, 400),
        "idle_brightness": _byte(sl.get("idle_brightness", DEFAULTS["idle_brightness"]), 40),
        # during a job the strip keeps its colours but not its blinks (see status_light.efectos_congelados)
        "effects_in_job": "with_effects" if sl.get("effects_in_job") == "with_effects" else "without_effects",
        "light_color": _color(sl.get("light_color"), DEFAULTS["light_color"], True),
        "mode_colors": {},
        "state_colors": {},
    }
    for k, d in DEFAULTS["mode_colors"].items():
        out["mode_colors"][k] = _color((sl.get("mode_colors") or {}).get(k), d)
    for k, d in DEFAULTS["state_colors"].items():
        out["state_colors"][k] = _color((sl.get("state_colors") or {}).get(k), d)
    out["zones_extra"] = []
    used = set()
    for z in (sl.get("zones_extra") or [])[:6]:
        if not isinstance(z, dict):
            continue
        n = _integer(z.get("n"), 1, 1, 200)
        zid = str(z.get("id") or "")
        if not zid.startswith("z") or zid in used:
            zid = next("z%d" % k for k in range(1, 50) if "z%d" % k not in used)
        used.add(zid)
        out["zones_extra"].append({
            "id": zid,
            "name": str(z.get("name") or "").strip()[:30] or str(M("lights_zone_default_name")),
            "n": n,
            "color": _color(z.get("color"), ZONE_EXTRA_COLOR, True),
            "on": bool(z.get("on", True)),
        })
    import pi_leds as _pl
    out["strips_extra"] = []
    tusados = set()
    for t in (sl.get("strips_extra") or [])[:4]:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "")
        if not tid.startswith("t") or tid in tusados:
            tid = next("t%d" % k for k in range(1, 50) if "t%d" % k not in tusados)
        tusados.add(tid)
        zones, zusados = [], set()
        for z in (t.get("zones") or [])[:8]:
            if not isinstance(z, dict):
                continue
            zid = str(z.get("id") or "")
            if not zid.startswith("z") or zid in zusados:
                zid = next("z%d" % k for k in range(1, 50) if "z%d" % k not in zusados)
            zusados.add(zid)
            zones.append({
                "id": zid,
                "name": str(z.get("name") or "").strip()[:30] or str(M("lights_zone_default_name")),
                "n": _integer(z.get("n"), 1, 1, 200),
                "color": _color(z.get("color"), ZONE_EXTRA_COLOR, True),
                "on": bool(z.get("on", True)),
            })
        out["strips_extra"].append({
            "id": tid,
            "name": str(t.get("name") or "").strip()[:30] or str(M("lights_strip_default_name")),
            "led_strip": _integer(t.get("led_strip"), 1, 0, 9),
            "output": _pl.normalize_output(t.get("output")),
            "zones": zones,
        })
    # Order of ALL zones on the strip, from the connector (2026-10-10: the extra
    # zones can be placed anywhere). Without a saved order: the one of "orden"
    # (status/lighting) and the extra ones at the end, as before.
    ids = ["state", "lighting"] + [z["id"] for z in out["zones_extra"]]
    request = [i for i in (sl.get("order_zones") or []) if i in ids]
    if len(set(request)) != len(request) or not request:
        request = (["state", "lighting"] if out["order"] == "state_first" else ["lighting", "state"])
    out["order_zones"] = request + [i for i in ids if i not in request]
    out["order"] = "state_first" if out["order_zones"].index("state") < out["order_zones"].index("lighting") else "lighting_first"
    # Status zone (2026-10-10): "principal", "ninguna" or "<strip>:<zone>" of an
    # additional strip. If that zone no longer exists it goes back to "principal".
    ze = str(sl.get("zone_state") or "main")
    valid = ["main", "none"] + ["%s:%s" % (t["id"], z["id"]) for t in out["strips_extra"] for z in t["zones"]]
    out["zone_state"] = ze if ze in valid else "main"
    if out["virtual"] and ":" in out["zone_state"]:
        # without a strip there are no zones on other strips
        out["zone_state"] = "main"
    # Board LEDs and board status strip (2026-10-11)
    import status_light as _sl
    lp = sl.get("leds_board") if isinstance(sl.get("leds_board"), dict) else {}
    leds = lp.get("leds") if isinstance(lp.get("leds"), list) else DEFAULTS["leds_board"]["leds"]
    out["leds_board"] = {
        "active": bool(lp.get("active", False)),
        "leds": [i for i in _sl.LEDS_BOARD_IDS if i in leds],  # fixed order, no repeated or unknown ones
        "brightness": _integer(lp.get("brightness"), DEFAULTS["leds_board"]["brightness"], 1, 255),
        # what the board LEDs do when the lighting takes the status zone (2026-10-13: it was never saved)
        "with_lighting": "as_zone" if lp.get("with_lighting") == "as_zone" else "keep",
        # the CAN LED of the board: lit while the CAN is fine ("falla", default) or the slow blink of the board ("siempre")
        "can_blink": "always" if lp.get("can_blink") == "always" else "fault",
        "vin_min": nw["board_thresholds"]["vin_min"],
        "v12_min": nw["board_thresholds"]["v12_min"],
    }
    te = sl.get("strip_state") if isinstance(sl.get("strip_state"), dict) else {}
    gr = te.get("groups") if isinstance(te.get("groups"), list) else DEFAULTS["strip_state"]["groups"]
    out["strip_state"] = {
        "active": bool(te.get("active", False)),
        "groups": [g for g in _sl.GROUPS_STRIP_STATE if g in gr],
    }
    out["output"] = _pl.normalize_output(sl.get("output"))
    an = sl.get("animation") if isinstance(sl.get("animation"), dict) else {}
    try:
        step = max(1, min(60, int(an.get("step", 6))))
    except (TypeError, ValueError):
        step = 6
    type_name = an.get("kind") if an.get("kind") in KINDS_ANIMATION else "bar"
    out["animation"] = {
        "active": bool(an.get("active", True)),
        "kind": type_name,
        "color": _color(an.get("color"), DEFAULTS["animation"]["color"]),
        "step": step,
    }
    # known states (lights_config.STATES): colour, effect, and the outputs
    # (strip / screen / board) each one is shown on; old configs without the
    # new keys give exactly what they always did
    out["states"] = nw["states"]
    out["order_states"] = nw["order_states"]
    out["work_light"] = nw["work_light"]
    out["night"] = nw["night"]
    out["power"] = nw["power"]
    out["pi_hot_c"] = nw["pi_hot_c"]
    out["live_quiet_s"] = nw["live_quiet_s"]
    cb = sl.get("combine") if isinstance(sl.get("combine"), dict) else {}
    try:
        turn = max(0.5, min(10.0, float(cb.get("turn_s", 1.5))))
    except (TypeError, ValueError):
        turn = 1.5
    out["combine"] = {"mode": cb.get("mode") if cb.get("mode") in MODES_COMBINE else "priority", "turn_s": turn,
                       "si_no_fit": cb.get("si_no_fit") if cb.get("si_no_fit") in ("turns", "hide") else "turns"}
    ef = sl.get("effects") if isinstance(sl.get("effects"), dict) else {}
    ft = ef.get("end_job") if isinstance(ef.get("end_job"), dict) else {}
    dft = DEFAULTS["effects"]["end_job"]
    try:
        times = max(1, min(10, int(ft.get("times", dft["times"]))))
    except (TypeError, ValueError):
        times = dft["times"]
    out["effects"] = {
        "end_job": {"active": bool(ft.get("active", dft["active"])), "color": _color(ft.get("color"), dft["color"]), "times": times},
        # the old "blink while paused" switch is now the effect of the Paused state
        "blink_pause": out["states"]["paused"]["effect"] != "steady",
        "jog_free_always": bool(ef.get("jog_free_always", DEFAULTS["effects"]["jog_free_always"])),
    }
    return out


def _m950(led_strip):
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


def _write_lights_g(c):
    lc = c["light_color"]
    an = c["animation"]
    ac = an["color"]
    lines = [
        "; sys/workshop/macros/lights.g -- generated by the Lights page (handlers/lights.py). Do not edit by hand:",
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
        f"set global.lightOnColor = {{{lc['r']}, {lc['u']}, {lc['b']}, {lc['w']}, {lc['p']}}}",
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
    os.makedirs(os.path.dirname(LIGHTS_G), exist_ok=True)
    tmp = LIGHTS_G + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.flush()
        os.fsync(f.fileno())  # to the card before the rename (power cut)
    os.replace(tmp, LIGHTS_G)


def _state(config):
    c = _cfg(config)
    # the M950 line of each configured strip (main and additional)
    everything = {str(e): _m950(e) for e in [c["led_strip"]] + [t["led_strip"] for t in c["strips_extra"]]}
    return {"ok": True, "config": c, "m950": _m950(c["led_strip"]), "m950_all": everything, "lights_g": os.path.isfile(LIGHTS_G),
            # what the page needs to know about the states (kind, defaults) and the options
            "catalog": lc.catalog(), "effects": list(lc.EFFECTS), "outputs": list(lc.OUTPUTS), "max_scenes": lc.MAX_SCENES}


def _no_strip():
    return _dumps({"ok": False, "code": "no_strip", "error": "This machine has no LED strip: nothing to send to the board"})


def _strip_of(c, params):
    """Strip requested with T<E number> (the page's tools); without T, the
    main one. Returns (E, extra_strip or None)."""
    try:
        e = int(float(params.get("T")))
    except (TypeError, ValueError):
        return c["led_strip"], None
    return e, next((t for t in c["strips_extra"] if t["led_strip"] == e), None)


def _pause(seconds):
    try:
        import status_light
        status_light.PAUSE_UNTIL = time.time() + seconds
    except Exception:
        pass


def run(params, bridge, config):
    action = str(params.get("C", "query")).strip().lower()

    # "Lights and states" plugin stopped or disabled (service_modules.py): the
    # service does not touch the lights; only the query keeps answering.
    if action not in ("query", "query", "") and not service_modules.is_active(service_modules.LIGHTS):
        return _dumps({"ok": False, "error": M("lights_lights_states_stopped_settings_plugins_lights")})

    # Turn an extra zone on/off instantly (Lights page, Now section):
    # <params> C"zona" N<index> S1|S0. status_light repaints it by itself.
    if action == "zone":
        # T"<additional strip id>" (without T: the main one)
        sl = config.get("status_light") or {}
        zones = sl.get("zones_extra") or []
        if params.get("T"):
            led_strip = next((t for t in (sl.get("strips_extra") or []) if t.get("id") == str(params.get("T"))), None)
            zones = (led_strip or {}).get("zones") or []
        try:
            i = int(params.get("N", -1))
            zones[i]["on"] = str(params.get("S", "1")) not in ("0", "off", "false")
        except (TypeError, ValueError, IndexError, KeyError):
            return _dumps({"ok": False, "error": M("lights_extra_zone_does_not_exist")})
        bridge.save_config()
        return _dumps(_state(config))

    # Status lights on a pin of the Pi (Lights > Advanced): the pins with what each one can do, and a short test.
    if action == "pi_pins":
        import pi_leds
        return _dumps({"ok": True, "pins": pi_leds.list_items_pins(), "strips": pi_leds.states()})
    if action == "pi_test":
        # N<pin>: test the strip on that pin
        import pi_leds
        pin = params.get("N")
        if pin in (None, ""):
            return _dumps({"ok": False, "error": M("lights_pin_of_strip_to_test_missing")})
        else:
            sl_ = config.get("status_light") or {}
            c_ = _cfg({"status_light": sl_})
            pin = int(pin)
            n_ = None
            for e_, s_, tot_ in [(c_["led_strip"], c_["output"], c_["led_start"] + c_["led_count"] + sum(z["n"] for z in c_["zones_extra"]))] + [
                    (t["led_strip"], t["output"], sum(z["n"] for z in t["zones"])) for t in c_["strips_extra"]]:
                if s_["kind"] == "pi" and s_["pin"] == pin:
                    n_ = max(1, tot_)
            t_ = pi_leds.STRIPS.get(pin)
            if t_ is None or n_ is None:
                return _dumps({"ok": False, "error": M("lights_strip_not_saved_its_output_pin")})
            r = t_.probe(n_, params.get("D", 4))
        r["strips"] = pi_leds.states()
        return _dumps(r)

    if action == "save":
        try:
            new = _json_param(params)
        except (ValueError, UnicodeDecodeError):
            return _dumps({"ok": False, "error": M("lights_j_must_json_configuration_hex")})
        current = _cfg(config)
        current.update({k: v for k, v in new.items() if k in DEFAULTS or k in ("states", "combine", "order_zones", "zone_state", "order_states")})
        # a page from before the redesign sends activo / virtual instead of strip
        if "strip" not in new and ("virtual" in new or "active" in new):
            current["strip"] = {"present": bool(new.get("active", True)) and not bool(new.get("virtual", False))}
        # Validate BEFORE touching the config in use (2026-10-10: an empty field
        # stayed in memory and the strip painting failed until restart)
        sl = dict(config.get("status_light") or {})
        previous = _cfg(config)
        sl.update(current)
        c = _cfg({"status_light": sl})
        if c["virtual"]:
            # No physical strip: additional strips and the E number are not
            # changed (they stay as saved; status_light does not use them
            # while there is no strip)
            c["strips_extra"] = previous["strips_extra"]
            c["led_strip"] = previous["led_strip"]
        if c["led_start"] + c["led_count"] + sum(z["n"] for z in c["zones_extra"]) > 400:
            return _dumps({"ok": False, "error": M("lights_invalid_zones_total_cannot_go_over")})
        es = [c["led_strip"]] + [t["led_strip"] for t in c["strips_extra"]]
        if len(set(es)) != len(es):
            return _dumps({"ok": False, "error": M("lights_two_strips_same_e_number_each")})
        # outputs on a pin of the Pi: only pins that can drive a strip (never a pin of DSF), one strip per pin
        import pi_leds
        pins_pi = []
        for s_ in [c["output"]] + [t["output"] for t in c["strips_extra"]]:
            if s_["kind"] != "pi":
                continue
            reason = pi_leds.pin_strip_valid(s_["pin"])
            if reason:
                return _dumps({"ok": False, "error": M("lights_gpio_pin_not_usable_for_strip", pin=s_["pin"], reason=reason)})
            pins_pi.append(s_["pin"])
        if len(set(pins_pi)) != len(pins_pi):
            return _dumps({"ok": False, "error": M("lights_two_strips_same_pi_pin")})
        for k_ in ("stop", "paused", "cancelling", "busy"):
            c["state_colors"][k_] = dict(c["states"][k_]["color"])
        sl.update(c)  # already clean values (numbers, not empty texts)
        config["status_light"] = sl
        bridge.save_config()
        try:
            _write_lights_g(c)
            bridge.send('M98 P"0:/sys/workshop/macros/lights.g"')
        except Exception as e:
            return _dumps({"ok": False, "error": M("lights_saved_but_could_not_write_lights_g", e=e)})
        activity.log_event(
            bridge, "config",
            M("lights_layout", lighting=c["led_start"], status=c["led_count"], strip=c["led_strip"]),
        )
        return _dumps(_state(config))

    # without an LED strip there is nothing to test on the board
    if action in ("test", "identify", "animation", "view_preview") and not _cfg(config)["strip"]["present"]:
        return _no_strip()

    if action == "test_state":
        # shows a state on the chosen outputs for a few seconds (status_light.PRUEBA)
        import status_light
        c = _cfg(config)
        ident = str(params.get("S", "")).strip()
        if ident not in c["states"]:
            return _dumps({"ok": False, "code": "unknown_state", "error": "Unknown state: " + ident})
        request = [x for x in re.split(r"[,\s]+", str(params.get("O", ""))) if x in lc.OUTPUTS]
        outputs = request or [o for o in lc.OUTPUTS if c["states"][ident]["outputs"].get(o)] or ["screen"]
        if not c["strip"]["present"]:
            outputs = [o for o in outputs if o != "strip"] or ["screen"]
        sec = _integer(params.get("D"), status_light.TEST_SECONDS, 2, 20)
        extra = {}
        if _has_json(params):
            try:
                d = _json_param(params)
                extra = {"color": _color(d.get("color"), c["states"][ident]["color"]) if d.get("color") else None,
                         "effect": d.get("effect")}
            except (ValueError, UnicodeDecodeError, TypeError, AttributeError):
                extra = {}
        r = status_light.probe_state(ident, sec, outputs, **extra)
        return _dumps({"ok": True, "state": ident, "seconds": sec, "outputs": list(r["outputs"])})

    if action == "scene":
        c = _cfg(config)
        if not c["strip"]["present"]:
            return _no_strip()
        sid = str(params.get("S", "")).strip()
        if _has_json(params):
            try:
                color = _color(_json_param(params), DEFAULTS["light_color"], True)
            except (ValueError, UnicodeDecodeError, TypeError):
                return _dumps({"ok": False, "code": "bad_json", "error": "J must be the colour of the scene"})
            sid = ""
        else:
            sc = next((x for x in c["work_light"]["scenes"] if x["id"] == sid), None)
            if not sc:
                return _dumps({"ok": False, "code": "unknown_scene", "error": "Unknown scene: " + sid})
            color = dict(sc["color"])
        sl = config.setdefault("status_light", {})
        sl["light_color"] = color
        wl = dict(sl.get("work_light") or {})
        wl["scene"] = sid
        sl["work_light"] = wl
        bridge.save_config()
        c2 = _cfg(config)

        def _apply():
            # in its own thread, like handlers/light.py (an API call cannot wait for another code)
            try:
                _write_lights_g(c2)
                bridge.send('M98 P"0:/sys/workshop/macros/lights.g"')
                bridge.send('M98 P"0:/macros/light/lighton.g"')
                bridge.set_status("lightOn", True)
            except Exception:
                pass

        import threading
        threading.Thread(target=_apply, daemon=True).start()
        return _dumps(_state(config))

    if action == "schedule":
        sl = config.setdefault("status_light", {})
        ng = dict(sl.get("night") or {})
        ng["enabled"] = str(params.get("S", "1")).strip().lower() not in ("0", "off", "false")
        sl["night"] = ng
        bridge.save_config()
        return _dumps(_state(config))

    if action == "import":
        # checks a profile exported by the page; nothing is saved here
        try:
            raw = _json_param(params)
        except (ValueError, UnicodeDecodeError, OSError):
            return _dumps({"ok": False, "code": "bad_json", "error": "The file is not a valid lighting profile"})
        prof = raw.get("config") if isinstance(raw, dict) and isinstance(raw.get("config"), dict) else raw
        if not isinstance(prof, dict) or not any(k in prof for k in ("states", "mode_colors", "light_color", "animation", "effects")):
            return _dumps({"ok": False, "code": "bad_profile", "error": "The file does not look like a lighting profile"})
        with_hw = str(params.get("H", "0")).strip() in ("1", "true")
        sl = dict(config.get("status_light") or {})
        for k, v in prof.items():
            if with_hw or k not in HARDWARE_KEYS:
                sl[k] = v
        return _dumps({"ok": True, "config": _cfg({"status_light": sl}), "hardware": with_hw})

    if action in ("test", "identify"):
        c = _cfg(config)
        try:
            sec = max(2, min(30, int(float(params.get("D", 6)))))
        except (TypeError, ValueError):
            sec = 6
        en, strip_x = _strip_of(c, params)
        if strip_x:
            total = _m950(en)["total"] or sum(z["n"] for z in strip_x["zones"]) or 1
        else:
            total = _m950(c["led_strip"])["total"] or (c["led_start"] + c["led_count"])
        e = f"E{en}"
        _pause(sec)
        time.sleep(0.5)  # so the status_light loop sees the pause before painting
        # Identify with what the page has ON SCREEN (even if not saved):
        # J = [[r, g, b, count], ...] in strip order, one color per zone (the same
        # ones as the page's boxes).
        if action == "identify" and _has_json(params):
            try:
                request = _json_param(params)
                segments = [(_byte(t[0]), _byte(t[1]), _byte(t[2]), _integer(t[3], 0, 0, 400)) for t in request][:40]
            except (ValueError, UnicodeDecodeError, TypeError, IndexError):
                return _dumps({"ok": False, "error": M("lights_invalid_j")})
            segments.append((0, 0, 0, max(0, total - sum(t_[3] for t_ in segments))))
            segments = [t_ for t_ in segments if t_[3] > 0]
            for i_, (r_, u_, b_, n_) in enumerate(segments):
                p_ = 255 if (r_ or u_ or b_) else 0
                bridge.send(f"M150 {e} R{r_} U{u_} B{b_} W0 P{p_} S{n_}" + (" F1" if i_ < len(segments) - 1 else ""))
            return _dumps({"ok": True, "seconds": sec})
        if strip_x:
            # additional strip: count = first N; identify = alternating violet and green
            # zones (you can see where each one ends)
            if action == "test":
                try:
                    n = max(1, min(400, int(float(params.get("N", total)))))
                except (TypeError, ValueError):
                    n = total
                segments = [(0, 80, 255, n), (0, 0, 0, max(0, total - n))]
            else:
                segments = [((180, 0, 255) if k % 2 == 0 else (0, 220, 90)) + (z["n"],) for k, z in enumerate(strip_x["zones"])]
                segments.append((0, 0, 0, max(0, total - sum(z["n"] for z in strip_x["zones"]))))
            segments = [t_ for t_ in segments if t_[3] > 0]
            for i_, (r_, u_, b_, n_) in enumerate(segments):
                p_ = 255 if (r_ or u_ or b_) else 0
                bridge.send(f"M150 {e} R{r_} U{u_} B{b_} W0 P{p_} S{n_}" + (" F1" if i_ < len(segments) - 1 else ""))
            return _dumps({"ok": True, "seconds": sec})
        if action == "test":
            try:
                n = max(1, min(400, int(float(params.get("N", total)))))
            except (TypeError, ValueError):
                n = total
            rest = total - n
            ni_, ne_ = c["led_start"], c["led_count"]
            in_state = min(n, ne_) if c["order"] == "state_first" else max(0, min(ne_, n - ni_))
            try:
                bridge.set_status("statusLightSecs", [s_ for s_ in (["#0050ff", 1, in_state], ["#000000", 0, ne_ - in_state]) if s_[2] > 0])
            except Exception:
                pass
            import status_light
            status_light.publish_strip(bridge, [(0, 80, 255, 0, 255, n), (0, 0, 0, 0, 0, max(0, rest))])
            if rest > 0:
                bridge.send(f"M150 {e} R0 U80 B255 W0 P255 S{n} F1")
                bridge.send(f"M150 {e} R0 U0 B0 W0 P0 S{rest}")
            else:
                bridge.send(f"M150 {e} R0 U80 B255 W0 P255 S{n}")
            return _dumps({"ok": True, "encendidos": n, "seconds": sec})
        # each zone in its color, in the real order of the strip: lighting amber,
        # status light blue, extra zones violet
        colors = {"lighting": (255, 160, 0, c["led_start"]), "state": (0, 200, 255, c["led_count"])}
        for z in c["zones_extra"]:
            colors[z["id"]] = (180, 0, 255, z["n"])
        segments = [colors[i] for i in c["order_zones"] if i in colors]
        rest = max(0, total - sum(t_[3] for t_ in segments))
        segments = [t_ for t_ in segments if t_[3] > 0] + ([(0, 0, 0, rest)] if rest else [])
        for i_, (r_, u_, b_, n_) in enumerate(segments):
            p_ = 255 if (r_ or u_ or b_) else 0
            bridge.send(f"M150 {e} R{r_} U{u_} B{b_} W0 P{p_} S{n_}" + (" F1" if i_ < len(segments) - 1 else ""))
        try:
            bridge.set_status("statusLightSecs", [["#00c8ff", 1, c["led_count"]]] if c["led_count"] > 0 else [])  # the interface sees the same as the strip
        except Exception:
            pass
        import status_light
        status_light.publish_strip(bridge, [(r_, u_, b_, 0, 255 if (r_ or u_ or b_) else 0, n_) for r_, u_, b_, n_ in segments])
        return _dumps({"ok": True, "seconds": sec})

    if action == "animation":
        # J (optional) = {"tipo","color","paso"} to TEST without saving: those
        # values are put in the globals, the animation runs in preview mode (V1: it
        # does not reload lights.g) and afterwards lights.g gives back the saved ones.
        trial = None
        if _has_json(params):
            try:
                trial = _json_param(params)
            except (ValueError, UnicodeDecodeError):
                trial = None
        _pause(8)

        def execute():
            try:
                if trial:
                    _write_lights_g(_cfg(config))  # makes sure the globals exist
                    bridge.send('M98 P"0:/sys/workshop/macros/lights.g"')
                    col = _color(trial.get("color"), DEFAULTS["animation"]["color"])
                    type_name = trial.get("kind") if trial.get("kind") in KINDS_ANIMATION else "bar"
                    try:
                        step = max(1, min(60, int(trial.get("step", 6))))
                    except (TypeError, ValueError):
                        step = 6
                    bridge.send("set global.ledAnimActive = true")
                    bridge.send(f'set global.ledAnimKind = "{type_name}"')
                    bridge.send(f"set global.ledAnimColor = {{{col['r']}, {col['u']}, {col['b']}, {col['w']}}}")
                    bridge.send(f"set global.ledAnimStep = {step}")
                    bridge.send('M98 P"0:/sys/ledstartup.g" V1')
                    bridge.send('M98 P"0:/sys/workshop/macros/lights.g"')
                else:
                    bridge.send('M98 P"0:/sys/ledstartup.g"')
            except Exception:
                pass
            finally:
                # the M98 returns when the animation has finished: repaint the normal state
                # right away (do not wait for the pause to expire)
                import status_light as _sl
                _sl.PAUSE_UNTIL = 0.0

        import threading
        threading.Thread(target=execute, daemon=True).start()
        return _dumps({"ok": True})

    if action == "view_preview":
        # Paint sample frames without saving anything (Lights page: try the
        # end-of-job notice or how several states combine).
        # J = {"cuadros": [[[r,g,b,w,count], ...], ...], "intervalo": s, "segundos": s}
        try:
            d = _json_param(params)
        except (ValueError, UnicodeDecodeError):
            return _dumps({"ok": False, "error": M("lights_invalid_j")})
        c = _cfg(config)
        frames = d.get("frames") or []
        sim = d.get("simulate") if isinstance(d.get("simulate"), dict) else None
        if not frames and not sim:
            return _dumps({"ok": False, "error": M("lights_no_frames")})
        interval = max(0.15, min(5.0, float(d.get("interval", 1.0))))
        seconds = max(1.0, min(20.0, float(d.get("seconds", 6.0))))
        _pause(seconds + 1)

        def animate():
            import status_light
            illum = illum_current()
            try:
                end = time.time() + seconds
                i = 0
                time.sleep(0.4)
                if sim:
                    # REAL simulation: the same calculation as the strip (status_light.
                    # compute) with the page's config (even if not saved) and sample states:
                    # turns, blinking, split and progress bar come out exactly as they will look.
                    slc = dict(sim.get("config") or {})
                    slc["led_count"] = status_light.zone_state(c)[4]
                    cfg_sim = {"status_light": slc}
                    act = set(sim.get("activeList") or [])
                    status = "idle"
                    for ident, st in (("cancelling", "cancelling"), ("paused", "paused"), ("busy", "busy")):
                        if ident in act:
                            status = st
                            break
                    if sim.get("working") and status == "idle":
                        status = "processing"
                    extras = {"homed": "without_homing" not in act, "air": "air" in act,
                              "laser_pwm": 1 if "laser" in act else 0,
                              "in_live": {"active": True} if "in_live" in act else None,
                              "rs485_faults": 1 if "rs485" in act else 0,
                              "rs485_notices": 1 if "rs485_notice" in act else 0,
                              "crash": "crash" in act, "jog_free": "jog_free" in act}
                    prog = max(0.0, min(1.0, float(sim.get("progress", 0.6))))
                    kind = str(sim.get("mode") or "Laser")
                    last = None
                    while time.time() < end:
                        secs, _, _ = status_light.compute(cfg_sim, kind, False, illum, status, int(prog * 1000), 1000, extras)
                        if secs != last:
                            status_light.paint_state(bridge, illum, secs, c)
                            last = secs
                        time.sleep(0.2)
                    return
                while time.time() < end:
                    secs = [(_byte(s[0]), _byte(s[1]), _byte(s[2]), _byte(s[3]), 255, max(0, int(s[4])))
                            for s in frames[i % len(frames)]]
                    status_light.paint_state(bridge, illum, secs, c)
                    i += 1
                    time.sleep(interval)
            except Exception:
                pass

        def illum_current():
            # current color of the work light (so as not to turn it off when painting)
            try:
                v = bridge.send("echo global.lightZoneColor")
                nums = [int(x) for x in re.findall(r"-?\d+", v or "")][:5]
                return nums if len(nums) == 5 else [0, 0, 0, 0, 0]
            except Exception:
                return [0, 0, 0, 0, 0]

        import threading
        threading.Thread(target=animate, daemon=True).start()
        return _dumps({"ok": True, "seconds": seconds})

    if action == "apply_m950":
        c = _cfg(config)
        try:
            n = int(float(params.get("N")))
        except (TypeError, ValueError):
            return _dumps({"ok": False, "error": M("lights_led_count_missing")})
        if not 1 <= n <= 400:
            return _dumps({"ok": False, "error": M("lights_count_out_of_range")})
        en, _ = _strip_of(c, params)  # T<E>: additional strip; without T, the main one
        with open(CONFIG_G, encoding="utf-8", newline="") as f:
            raw_text = f.read()
        pattern = re.compile(rf"^(\s*M950\s+E{en}\b[^;\n]*?\bU)(\d+)", re.MULTILINE)
        if not pattern.search(raw_text):
            return _dumps({"ok": False, "error": M("lights_i_did_not_find_line_m950", en=en)})
        copy = CONFIG_G + time.strftime(".bak-luces-%Y%m%d-%H%M%S")
        shutil.copy2(CONFIG_G, copy)
        raw_text = pattern.sub(lambda m: m.group(1) + str(n), raw_text, count=1)
        tmp = CONFIG_G + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(raw_text)
            f.flush()
            os.fsync(f.fileno())  # to the card before the rename (power cut)
        os.replace(tmp, CONFIG_G)
        activity.log_event(bridge, "config", M("lights_config_g", strip=en, leds=n, copy=os.path.basename(copy)))
        return _dumps({"ok": True, "m950": _m950(en), "copy": os.path.basename(copy), "restart": True})

    return _dumps(_state(config))
