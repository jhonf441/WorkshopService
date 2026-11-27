# Public state of the lights (lightsView)

Owner's request of 2026-11-23 (note 8): the state of the lights that the side bars and the Lights summary paint must be readable
by anybody at the machine, without a session. Reading only: nothing that acts, nothing secret.

## The rule

- No API operation is opened. `permissions.PUBLIC_OPS` stays as it was (login, whoami, can, ping) and every read of the API still
  needs a session when people exist (deny what is not listed).
- The service PUBLISHES a sanitized, read-only view as plugin data `lightsView` (the object model DWC serves to every screen, the
  same channel as `statusIndicator`, `lightOn`, `ledStrip` and `lightsInfo`, which never asked for a session).
- ONE pure function builds it: `dsf/lights_view.py` `view(lights_profile.clean(config))`. It copies only the allowlisted fields.
  `dsf/test_lights_view.py` fails on any field outside the allowlist and on any sensitive one.
- It is published by the lights loop (`lights_loop.Painter._publish_view`) only when the saved settings change (never during a
  simulation of unsaved settings), and emptied (`null`) when the Lights module rests.

An earlier version on this branch opened `lights.get` / `plugins.stopped.get` without a session (a "public reading" list); it was
reverted the same day in favour of this view (architect's review: widening public API access is a decision for the maintainer).

## Shape (version 1)

```
lightsView = {
  "v": 1,
  "strip": bool,                       // a physical LED strip is configured
  "output": "duet" | "pi",             // who paints the main strip (never the pin)
  "work_light": {
    "scene": str,                      // id of the current scene ("" = none)
    "auto_off": bool, "auto_on_job": bool,
    "scenes": [{"id": str, "name": str, "color": {"r","u","b","w","p": 0-255}}]
  },
  "zones":  [{"id": str, "name": str, "on": bool, "color": {r,u,b,w,p}}],         // extra zones of the main strip
  "strips": [{"id": str, "name": str, "output": "duet" | "pi",
              "zones": [{"id": str, "name": str, "on": bool, "color": {r,u,b,w,p}}]}],
  "night":  {"enabled": bool, "from": "HH:MM", "to": "HH:MM", "level": int},
  "leds_board": bool,                  // the LEDs of the board panel are used
  "power_limit_ma": int                // 0 = no limit
}
```

Names of scenes, zones and strips that are still a default are message keys or the default name in DWC's language, exactly as in
`lights.get` (the page already translates them). The live state is in the other keys: `statusIndicator` (current state and the
active ones), `lightOn`, `ledStrip`, `lightsInfo` (power drawn, night dimming active, board LEDs, auto-off minutes).

## What never goes in

Pi pins and their order / brightness, M950 lines, E numbers, LED start / count, paths of the SD, state colours and effects, the
animation, thresholds, anything about people or keys. To add a field: decide it here, add it to the allowlist of `lights_view.py`
(`TOP_KEYS` ... `NIGHT_KEYS`) and to `SHAPE` in the test, in the same commit.

## For the pages (front)

Signed out, the Lights summary and the side bars read `plugins.WorkshopService.data.lightsView` instead of `lights.get` (which
still answers 401 without a session). The status LED mirror of the control bar was already plugin data (`statusIndicator`): its
lock (tied to `lights.save`) was a client mistake and was removed on the TallerPlugins branch back-23nov.
