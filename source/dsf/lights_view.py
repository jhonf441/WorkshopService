"""
lights_view -- the public, read-only view of the lights (owner's request 2026-11-23, note 8; docs/PUBLIC-STATE.md).

The Lights summary and the side bars must show the state of the lights to anybody at the machine, without a session. Instead of
opening an API operation, the service publishes this view as plugin data `lightsView` (the object model, which DWC serves to every
screen). It is built by ONE pure function from the cleaned configuration (lights_profile.clean) and copies only the allowed fields:
no Pi pins, no M950 lines, no E numbers, no LED counts or addresses, no paths, no names of people. test_lights_view.py fails on any
field that is not in the allowlist below, so a new field needs a decision here first.

Shape (version 1):
  {
    "v": 1,
    "strip": bool,                      # a physical LED strip is configured
    "output": "duet" | "pi",            # who paints the main strip (never the pin)
    "work_light": {"scene": str, "auto_off": bool, "auto_on_job": bool,
                   "scenes": [{"id": str, "name": str, "color": {r,u,b,w,p}}]},
    "zones": [{"id": str, "name": str, "on": bool, "color": {r,u,b,w,p}}],          # extra zones of the main strip
    "strips": [{"id": str, "name": str, "output": "duet"|"pi",
                "zones": [{"id": str, "name": str, "on": bool, "color": {r,u,b,w,p}}]}],
    "night": {"enabled": bool, "from": "HH:MM", "to": "HH:MM", "level": int},
    "leds_board": bool,                 # the LEDs of the board panel are used
    "power_limit_ma": int,              # 0 = no limit
  }
The live state (current light state, work light on, painted strip, power drawn, night dimming active) is already public in the
plugin data statusIndicator, lightOn, ledStrip and lightsInfo.
"""

VERSION = 1
COLOR_KEYS = ("r", "u", "b", "w", "p")
# the allowlist, key by key: test_lights_view.py compares every view against it
TOP_KEYS = ("v", "strip", "output", "work_light", "zones", "strips", "night", "leds_board", "power_limit_ma")
WORK_KEYS = ("scene", "auto_off", "auto_on_job", "scenes")
SCENE_KEYS = ("id", "name", "color")
ZONE_KEYS = ("id", "name", "on", "color")
STRIP_KEYS = ("id", "name", "output", "zones")
NIGHT_KEYS = ("enabled", "from", "to", "level")


def _d(v):
    return v if isinstance(v, dict) else {}


def _l(v):
    return v if isinstance(v, list) else []


def _color(c):
    c = _d(c)
    out = {}
    for k in COLOR_KEYS:
        try:
            out[k] = max(0, min(255, int(c.get(k, 0))))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def _kind(output):
    return "pi" if _d(output).get("kind") == "pi" else "duet"


def _zone(z):
    z = _d(z)
    return {"id": str(z.get("id") or ""), "name": str(z.get("name") or ""), "on": bool(z.get("on", True)), "color": _color(z.get("color"))}


def view(cleaned):
    """The public view of a cleaned lights configuration (lights_profile.clean). Pure; never raises on a partial dict."""
    c = _d(cleaned)
    wl = _d(c.get("work_light"))
    ng = _d(c.get("night"))
    try:
        limit = max(0, int(_d(c.get("power")).get("limit_ma") or 0))
    except (TypeError, ValueError):
        limit = 0
    return {
        "v": VERSION,
        "strip": bool(_d(c.get("strip")).get("present")),
        "output": _kind(c.get("output")),
        "work_light": {
            "scene": str(wl.get("scene") or ""),
            "auto_off": bool(_d(wl.get("auto_off")).get("enabled")),
            "auto_on_job": bool(wl.get("auto_on_job")),
            "scenes": [{"id": str(_d(s).get("id") or ""), "name": str(_d(s).get("name") or ""), "color": _color(_d(s).get("color"))}
                       for s in _l(wl.get("scenes"))],
        },
        "zones": [_zone(z) for z in _l(c.get("zones_extra"))],
        "strips": [{"id": str(_d(t).get("id") or ""), "name": str(_d(t).get("name") or ""), "output": _kind(_d(t).get("output")),
                    "zones": [_zone(z) for z in _l(_d(t).get("zones"))]} for t in _l(c.get("strips_extra"))],
        "night": {"enabled": bool(ng.get("enabled")), "from": str(ng.get("from") or ""), "to": str(ng.get("to") or ""),
                  "level": int(ng.get("level") or 0) if str(ng.get("level") or "0").isdigit() else 0},
        "leds_board": bool(_d(c.get("leds_board")).get("active")),
        "power_limit_ma": limit,
    }
