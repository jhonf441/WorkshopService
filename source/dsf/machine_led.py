"""LED strips of the board (the `M950 E<n>` line), created from the page like a tool or a bed heater: `machine.led.get`, `machine.led.preview` (read only)
and the plan kind `config.led_strip` (machine.config.plan / machine.config.apply, technician). Design: informes/rediseno-ui-service/arquitectura/CAMBIO-CONFIG-INCLUDE.md.

What it writes (ONE line, the same one the Lights page tells the person to add by hand):

    M950 E1 C"io1.out" T2 U10

T is the type of strip RepRapFirmware knows: 0 DotStar (it needs a clock pin as well: not offered), 1 NeoPixel RGB (WS2812), 2 NeoPixel RGBW (SK6812, the strip of this
workshop and the one Lights paints with M150 R U B W P). The default is RGBW. The line goes into `sys/workshop/machine.g` as the block `machine.led.<n>` (for every mode:
the strip is hardware), and `config.g` gets its one call to machine.g the first time (machine_file.py). The machine reads it at the next start (restart_needed).

The pin is NEVER guessed: the person chooses it among `LED_PINS` (the dedicated `led` connector and the logic-level `io<n>.out` pins; the `out<n>` pins carry 24 V and
would burn a 5 V strip, so they are not offered), and it must not be the pin of another line of any file of the configuration (a `M950 E` line of another strip included).
The number E must be free in the files and in the object model, and below the board's limit. Pure parts: build_lines, strips_in (tests: test_machine_led.py).
"""
import re

import machine_patch as pt

TYPES = {"rgbw": 2, "rgb": 1}      # M950 T: NeoPixel RGBW (SK6812), NeoPixel RGB (WS2812)
DEFAULT_TYPE = "rgbw"
MAX_LEDS = 400                     # the same ceiling Lights uses for U (lights.apply_m950)
MAX_STRIPS = 3                     # RepRapFirmware's own ceiling when the board does not report its limit (object model limits.ledStrips)
LED_PINS = ("led",) + tuple("io%d.out" % n for n in range(9))
DEDICATED = "led"
_E, _C, _T, _U = (re.compile(p) for p in (r"\bE(\d+)", r'\bC"([^"]*)"', r"\bT(\d+)", r"\bU(\d+)"))


def _rel(path):
    return str(path)[2:].lstrip("/") if len(str(path)) > 1 and str(path)[1] == ":" else str(path).lstrip("/")


def strips_in(texts):
    """The live `M950 E<n>` lines of the configuration files: [{e, pin, type, leds, file, line, text}] (a comment never counts)."""
    out = []
    for path, text in texts:
        _, ls = pt.split_lines(text)
        for n, code in pt.live_lines(ls):
            if pt.command_word(code)[0] != "M950":
                continue
            e = _E.search(code)
            if not e:
                continue
            pin, typ, leds = _C.search(code), _T.search(code), _U.search(code)
            out.append({"e": int(e.group(1)), "pin": pin.group(1).lstrip("!^") if pin else None, "type": int(typ.group(1)) if typ else None,
                        "leds": int(leds.group(1)) if leds else None, "file": _rel(path), "line": n + 1, "text": code.strip()[:120]})
    return out


def _where(item):
    return {"file": item["file"], "line": item["line"], "text": item["text"]} if item else None


def pin_user(texts, pin, other=None):
    """{file, line, text} of the first live line that names `pin` (a `M950 E` line first, then any other line that uses the pin: `other(texts, pin)`), or None."""
    for s in strips_in(texts):
        if s["pin"] == pin:
            return _where(s)
    return other(texts, pin) if other else None


class LedError(ValueError):
    """code (led_exists, pin_used, pin_unknown, pin_capability, led_too_many, values), field of the spec, `where` of the line that is in the way."""

    def __init__(self, code, field="", where=None):
        super().__init__(code)
        self.code, self.field, self.where = code, field, where


def _whole(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise LedError("values", field)
    return v


def build_lines(spec, state):
    """The configuration lines of a strip -> {lines, summary}. state = {texts, in_model: {E numbers}, max_strips, known_pins (the pins of the board), other_user(texts, pin)}. Raises LedError."""
    if not isinstance(spec, dict):
        raise LedError("values", "spec")
    texts = state["texts"]
    top = max(1, int(state.get("max_strips") or MAX_STRIPS))
    e = _whole(spec.get("strip"), 0, top - 1, "strip")
    found = [s for s in strips_in(texts) if s["e"] == e]
    if found:
        raise LedError("led_exists", "strip", _where(found[0]))
    if e in state.get("in_model", ()):
        raise LedError("led_exists", "strip")
    typ = spec.get("type", DEFAULT_TYPE)
    if typ not in TYPES:
        raise LedError("values", "type")
    leds = _whole(spec.get("leds"), 1, MAX_LEDS, "leds")
    pin = str(spec.get("pin") or "").strip().lstrip("!^")
    if pin not in LED_PINS:
        raise LedError("pin_capability" if pin in state.get("known_pins", ()) else "pin_unknown", "pin")
    user = pin_user(texts, pin, state.get("other_user"))
    if user:
        raise LedError("pin_used", "pin", user)
    line = 'M950 E%d C"%s" T%d U%d' % (e, pin, TYPES[typ], leds)
    return {"lines": ["; LED strip E%d (Lights): %d LEDs, %s" % (e, leds, "NeoPixel RGBW" if typ == "rgbw" else "NeoPixel RGB"), line],
            "summary": {"strip": e, "pin": pin, "type": typ, "t": TYPES[typ], "leds": leds, "line": line}}
