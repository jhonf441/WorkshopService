"""API operations of the lights: lights.get / save / test / identify / animation / preview / apply_m950 / zone / test_state / scene /
schedule / import / pi_pins / pi_test (lights_edit, lights_probe), light.set and statuslight.set (lights_macros). api_ops.init registers them through build(ctx), like
settings_ops. The class, arguments, roles (permissions.py) and flags of each operation are the ones they had when they were handlers.
"""
import lights_edit
import lights_macros
import lights_probe
from workshop_api import READ, WRITE, Arg, Op


def _macro_ops(ctx):
    """The working light and the status LEDs (lights_macros)."""
    S, I, B, O, L = "str", "int", "bool", "obj", "list"
    a = Arg

    def light_set(args, c):
        return lights_macros.work_light(args["on"], ctx["bridge"])

    def statuslight_set(args, c):
        return lights_macros.status_leds(args["on"], ctx["bridge"])

    return [
        Op("light.set", light_set, WRITE, {"on": a(B, True, desc="true switches the working light on, false switches it off.")},
           "Switches the working light (lighting zone of the LED strip) on or off by running light/lighton.g or light/lightoff.g; "
           "updates the state shown on the pages.", macro=True),
        Op("statuslight.set", statuslight_set, WRITE,
           {"on": a(B, True, desc="true: automatic control by mode and state; false: switched off by hand.")},
           "Status LEDs of the strip: back to automatic control (on) or switched off by hand (off), with the macros light/statusledon.g / statusledoff.g.",
           macro=True),
    ]


def _edit_ops(ctx):
    """What the Lights page changes (lights_edit)."""
    S, I, B, O, L = "str", "int", "bool", "obj", "list"
    a = Arg
    d_lights_secs = "How long the LEDs stay like that, 2 to 30 seconds (default 6); the automatic lighting is paused meanwhile."
    d_lights_strip_e = "E number of the strip (the E<n> of its M950 line); empty: the main strip."

    def get_state(args, c):
        return lights_edit.get_state(ctx["config"])

    def save(args, c):
        return lights_edit.save(bridge=ctx["bridge"], config=ctx["config"], data=args["config"])

    def apply_m950(args, c):
        return lights_edit.apply_m950(bridge=ctx["bridge"], config=ctx["config"], total=args["total"], strip=args.get("strip"))

    def zone(args, c):
        return lights_edit.zone(bridge=ctx["bridge"], config=ctx["config"], index=args["index"], on=args["on"], strip=args.get("strip"))

    def scene(args, c):
        return lights_edit.scene(bridge=ctx["bridge"], config=ctx["config"], scene_id=args.get("scene"), color=args.get("color"))

    def schedule(args, c):
        return lights_edit.schedule(bridge=ctx["bridge"], config=ctx["config"], on=args["on"])

    def import_profile(args, c):
        return lights_edit.import_profile(config=ctx["config"], data=args["data"], hardware=args.get("hardware", False))

    return [
        Op("lights.get", get_state, READ, {},
           "Returns the configuration of the LED strip, lights and states (zones, colours, effects, scenes, night dimming) and its current state."),
        Op("lights.save", save, WRITE,
           {"config": a(O, True, desc="The lights configuration object of the page (the keys of lights.get; unknown keys are ignored).")},
           "Saves the lights configuration (validated first), writes 0:/sys/workshop/macros/system/lights.g and runs it so the board uses it. Logged in Activity."),
        Op("lights.apply_m950", apply_m950, WRITE,
           {"total": a(I, True, min=1, max=400, desc="New number of LEDs of the strip, 1 to 400."), "strip": a(I, desc=d_lights_strip_e)},
           "Changes the LED count (U<total>) of the M950 line of a strip in sys/config.g, keeping a copy of config.g; the board must be restarted "
           "for it to apply. Logged in Activity; needs a confirmation.", confirm={"level": 3, "key": "lights.apply_m950"}),
        Op("lights.zone", zone, WRITE,
           {"index": a(I, True, min=0, desc="Position of the extra zone in its strip's list of extra zones, from 0."),
            "on": a(B, True, desc="true switches the zone on, false switches it off."),
            "strip": a(S, desc="Id of an additional strip; empty: the main strip.")},
           "Switches one extra zone of the strip on or off now (saved; the strip is repainted)."),
        Op("lights.scene", scene, WRITE,
           {"scene": a(S, desc="Id of a saved scene of the working light (ignored when color is given)."),
            "color": a(O, desc="Free colour {r, u, b, w, p} instead of a scene.")},
           "Sets the colour of the working light from a scene or a free colour, saves it and switches the working light on. Needs a physical strip."),
        Op("lights.schedule", schedule, WRITE, {"on": a(B, True, desc="true enables the night dimming, false disables it.")},
           "Turns the night dimming of the lights on or off (saved)."),
        Op("lights.import", import_profile, READ,
           {"data": a(O, True, desc="The profile exported by the page (or {config: <profile>})."),
            "hardware": a(B, desc="true also takes the hardware layout of the profile (strips, zones); false keeps the one of this machine.")},
           "Checks a lighting profile exported by the page and returns it merged with the current configuration; nothing is saved (use lights.save)."),
    ]


def _probe_ops(ctx):
    """What the Lights page shows on the strip to check it (lights_probe)."""
    S, I, B, O, L = "str", "int", "bool", "obj", "list"
    a = Arg
    d_lights_secs = "How long the LEDs stay like that, 2 to 30 seconds (default 6); the automatic lighting is paused meanwhile."
    d_lights_strip_e = "E number of the strip (the E<n> of its M950 line); empty: the main strip."

    def pi_pins(args, c):
        return lights_probe.pi_pins()

    def pi_test(args, c):
        return lights_probe.pi_test(config=ctx["config"], pin=args["pin"], seconds=args.get("seconds"))

    def test_leds(args, c):
        return lights_probe.test_leds(bridge=ctx["bridge"], config=ctx["config"], count=args.get("count"), seconds=args.get("seconds"),
                                      strip=args.get("strip"))

    def identify_leds(args, c):
        return lights_probe.identify_leds(bridge=ctx["bridge"], config=ctx["config"], seconds=args.get("seconds"), strip=args.get("strip"),
                                          segments=args.get("segments"))

    def animation(args, c):
        return lights_probe.animation(bridge=ctx["bridge"], config=ctx["config"], data=args.get("data"))

    def preview(args, c):
        return lights_probe.preview(bridge=ctx["bridge"], config=ctx["config"], data=args["data"])

    def test_state(args, c):
        return lights_probe.test_state(config=ctx["config"], state=args["state"], seconds=args.get("seconds"), outputs=args.get("outputs"),
                                       data=args.get("data"))

    return [
        Op("lights.pi_pins", pi_pins, READ, {},
           "Lists the GPIO 2 to 27 of the Pi with what each one is doing (free, in use and by what) and what the lights can do with it (a strip over SPI on a MOSI pin), plus the state of that output.", log=False),
        Op("lights.pi_test", pi_test, WRITE,
           {"seconds": a(I, min=1, max=15, desc="How long the test lasts (default 4)."),
            "pin": a(I, True, min=2, max=27, desc="GPIO of the strip to test (it must be saved with its output on that pin).")},
           "Shows a short test on a strip whose output is a pin of the Pi (a moving colour). The normal frame comes back by itself."),
        Op("lights.test", test_leds, WRITE,
           {"count": a(I, min=1, max=400, desc="How many LEDs to light from the start, 1 to 400 (default: the whole strip)."),
            "seconds": a(I, min=2, max=30, desc=d_lights_secs), "strip": a(I, desc=d_lights_strip_e)},
           "Lights the first N LEDs of a strip in blue for a few seconds, to count them. Needs a physical strip."),
        Op("lights.identify", identify_leds, WRITE,
           {"seconds": a(I, min=2, max=30, desc=d_lights_secs), "strip": a(I, desc=d_lights_strip_e),
            "segments": a(O, desc="Optional [[r, g, b, count], ...] in strip order (what the page shows, even unsaved); the rest of the strip goes off.")},
           "Paints every zone of a strip in its own colour for a few seconds (or the segments given), to see where each zone is. Needs a physical strip."),
        Op("lights.animation", animation, WRITE,
           {"data": a(O, desc="Optional values to try without saving: {tipo: barra|parpadeo|centro|arcoiris, color: {r, u, b, w}, paso: 1-60}.")},
           "Runs the start-up animation of the strip now (sys/ledstartup.g), with the saved values or with the ones given. Needs a physical strip."),
        Op("lights.preview", preview, WRITE,
           {"data": a(O, True, desc="{cuadros: [[[r,u,b,w,count], ...], ...], intervalo: 0.15-5 s, segundos: 1-20} for frames, or "
                                    "{simular: {config, activos, progreso, modo, trabajando}, segundos} to simulate states.")},
           "Shows example frames on the status zone for a few seconds, or simulates states with unsaved settings; nothing is saved. Needs a physical strip."),
        Op("lights.test_state", test_state, WRITE,
           {"state": a(S, True, desc="Id of the state in the lights configuration (for example parada, pausado)."),
            "seconds": a(I, min=2, max=20, desc="How long it is shown, 2 to 20 seconds (default 6)."),
            "outputs": a(L, desc="Outputs: strip, screen and/or board (default: the ones enabled for that state; strip is dropped without a strip)."),
            "data": a(O, desc="Optional {color, effect} to try instead of the saved ones.")},
           "Shows one light state for a few seconds on the chosen outputs, optionally with another colour or effect."),
    ]


def build(ctx):
    """The operations; ctx is api_ops._ctx (bridge, config)."""
    return _macro_ops(ctx) + _edit_ops(ctx) + _probe_ops(ctx)
