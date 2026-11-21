"""What the Lights page changes: lights.get / save / zone / schedule / scene / import / apply_m950 (registered by lights_ops).

Every function answers like the old handler did: a dict that goes into the result of the operation, with the failures as
{"ok": False, "error": ...} (and a "code" when the page tells them apart), never as an API error. They take the bridge and the
configuration dict of the service as arguments; the cleaning, the files of the board and the state are in lights_profile.
"""
import os
import re
import shutil
import threading
import time

import activity
import lights_profile as lp
import pi_leds
from messages import M


def get_state(config):
    """The configuration, the M950 lines and the catalogue the page needs (answers even with the lights plugin stopped)."""
    return lp.answer(lp.state(config))


def _validated(c, previous):
    """The error answer of a cleaned configuration that cannot be saved, or None."""
    if c["virtual"]:
        # No physical strip: additional strips and the E number are not changed (they stay as saved; status_light does not use them
        # while there is no strip)
        c["strips_extra"] = previous["strips_extra"]
        c["led_strip"] = previous["led_strip"]
    if c["led_start"] + c["led_count"] + sum(z["n"] for z in c["zones_extra"]) > 400:
        return lp.answer({"ok": False, "error": M("lights_invalid_zones_total_cannot_go_over")})
    es = [c["led_strip"]] + [t["led_strip"] for t in c["strips_extra"]]
    if len(set(es)) != len(es):
        return lp.answer({"ok": False, "error": M("lights_two_strips_same_e_number_each")})
    # outputs on a pin of the Pi: only pins that can drive a strip (never a pin of DSF), one strip per pin
    pins_pi = []
    for out in [c["output"]] + [t["output"] for t in c["strips_extra"]]:
        if out["kind"] != "pi":
            continue
        reason = pi_leds.pin_strip_valid(out["pin"])
        if reason:
            return lp.answer({"ok": False, "error": M("lights_gpio_pin_not_usable_for_strip", pin=out["pin"], reason=reason)})
        pins_pi.append(out["pin"])
    if len(set(pins_pi)) != len(pins_pi):
        return lp.answer({"ok": False, "error": M("lights_two_strips_same_pi_pin")})
    return None


@lp.needs_lights
def save(bridge, config, data):
    """Saves the configuration of the page (`data`): validated first, written to config.json and to lights.g, which is run so the board
    uses it."""
    current = lp.clean(config)
    current.update({k: v for k, v in data.items() if k in lp.DEFAULTS or k in ("states", "combine", "order_zones", "zone_state", "order_states")})
    # a page from before the redesign sends activo / virtual instead of strip
    if "strip" not in data and ("virtual" in data or "active" in data):
        current["strip"] = {"present": bool(data.get("active", True)) and not bool(data.get("virtual", False))}
    # Validate BEFORE touching the config in use (2026-10-10: an empty field stayed in memory and the strip painting failed until restart)
    sl = dict(config.get("status_light") or {})
    previous = lp.clean(config)
    sl.update(current)
    c = lp.clean({"status_light": sl})
    refused = _validated(c, previous)
    if refused is not None:
        return refused
    for k_ in ("stop", "paused", "cancelling", "busy"):
        c["state_colors"][k_] = dict(c["states"][k_]["color"])
    sl.update(c)  # already clean values (numbers, not empty texts)
    config["status_light"] = sl
    bridge.save_config()
    try:
        lp.write_lights_g(c)
        bridge.send('M98 P"0:/sys/workshop/macros/system/lights.g"')
    except Exception as e:
        return lp.answer({"ok": False, "error": M("lights_saved_but_could_not_write_lights_g", e=e)})
    activity.log_event(bridge, "config", M("lights_layout", lighting=c["led_start"], status=c["led_count"], strip=c["led_strip"]))
    return lp.answer(lp.state(config))


@lp.needs_lights
def zone(bridge, config, index, on, strip):
    """Turns an extra zone on or off instantly (Lights page, Now section); the paint loop repaints it by itself. `strip` is the id of an
    additional strip (empty: the main one)."""
    sl = config.get("status_light") or {}
    zones = sl.get("zones_extra") or []
    if strip:
        led_strip = next((t for t in (sl.get("strips_extra") or []) if t.get("id") == str(strip)), None)
        zones = (led_strip or {}).get("zones") or []
    try:
        zones[index]["on"] = bool(on)
    except (TypeError, ValueError, IndexError, KeyError):
        return lp.answer({"ok": False, "error": M("lights_extra_zone_does_not_exist")})
    bridge.save_config()
    return lp.answer(lp.state(config))


@lp.needs_lights
def schedule(bridge, config, on):
    """Night dimming on or off (saved)."""
    sl = config.setdefault("status_light", {})
    ng = dict(sl.get("night") or {})
    ng["enabled"] = bool(on)
    sl["night"] = ng
    bridge.save_config()
    return lp.answer(lp.state(config))


def _light_on_with(bridge, c):
    """Writes lights.g and switches the working light on (in its own thread: an API call cannot wait for another code)."""
    try:
        lp.write_lights_g(c)
        bridge.send('M98 P"0:/sys/workshop/macros/system/lights.g"')
        bridge.send('M98 P"0:/macros/light/lighton.g"')
        bridge.set_status("lightOn", True)
    except Exception:
        pass


@lp.needs_lights
def scene(bridge, config, scene_id, color):
    """Sets the colour of the working light from a saved scene (`scene_id`) or a free colour (`color`, which drops the scene), saves it
    and switches the light on. Needs a physical strip."""
    c = lp.clean(config)
    if not c["strip"]["present"]:
        return lp.no_strip()
    sid = str(scene_id or "").strip()
    if color is not None:
        chosen = lp.color(color, lp.DEFAULTS["light_color"], True)
        sid = ""
    else:
        sc = next((x for x in c["work_light"]["scenes"] if x["id"] == sid), None)
        if not sc:
            return lp.answer({"ok": False, "code": "unknown_scene", "error": "Unknown scene: " + sid})
        chosen = dict(sc["color"])
    sl = config.setdefault("status_light", {})
    sl["light_color"] = chosen
    wl = dict(sl.get("work_light") or {})
    wl["scene"] = sid
    sl["work_light"] = wl
    bridge.save_config()
    threading.Thread(target=_light_on_with, args=(bridge, lp.clean(config)), daemon=True).start()
    return lp.answer(lp.state(config))


@lp.needs_lights
def import_profile(config, data, hardware):
    """Checks a profile exported by the page and returns it merged with the current configuration; nothing is saved. `hardware` also
    takes the hardware layout of the profile."""
    prof = data.get("config") if isinstance(data, dict) and isinstance(data.get("config"), dict) else data
    if not isinstance(prof, dict) or not any(k in prof for k in ("states", "mode_colors", "light_color", "animation", "effects")):
        return lp.answer({"ok": False, "code": "bad_profile", "error": "The file does not look like a lighting profile"})
    sl = dict(config.get("status_light") or {})
    for k, v in prof.items():
        if hardware or k not in lp.HARDWARE_KEYS:
            sl[k] = v
    return lp.answer({"ok": True, "config": lp.clean({"status_light": sl}), "hardware": bool(hardware)})


@lp.needs_lights
def apply_m950(bridge, config, total, strip):
    """Changes the U (number of LEDs) of the M950 line of a strip in sys/config.g (or sys/workshop/machine.g when the Machine page created it), keeping a copy of that file; the board must be restarted
    for it to apply. `strip` is the E number (empty: the main strip)."""
    c = lp.clean(config)
    try:
        total = int(float(total))
    except (TypeError, ValueError):
        return lp.answer({"ok": False, "error": M("lights_led_count_missing")})
    if not 1 <= total <= 400:
        return lp.answer({"ok": False, "error": M("lights_count_out_of_range")})
    en, _ = lp.strip_of(c, strip)
    target = lp.strip_file(en) or lp.CONFIG_G   # config.g, or machine.g where the Machine page created the strip
    with open(target, encoding="utf-8", newline="") as f:
        raw_text = f.read()
    pattern = re.compile(rf"^(\s*M950\s+E{en}\b[^;\n]*?\bU)(\d+)", re.MULTILINE)
    if not pattern.search(raw_text):
        return lp.answer({"ok": False, "error": M("lights_i_did_not_find_line_m950", en=en)})
    copy = target + time.strftime(".bak-luces-%Y%m%d-%H%M%S")
    shutil.copy2(target, copy)
    raw_text = pattern.sub(lambda m: m.group(1) + str(total), raw_text, count=1)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(raw_text)
        f.flush()
        os.fsync(f.fileno())  # to the card before the rename (power cut)
    os.replace(tmp, target)
    activity.log_event(bridge, "config", M("lights_config_g", strip=en, leds=total, copy=os.path.basename(copy)))
    return lp.answer({"ok": True, "m950": lp.m950(en), "copy": os.path.basename(copy), "restart": True})
