"""What the Lights page shows on the strip to check it: lights.test / identify / animation / preview / test_state and the tests of a strip on
a pin of the Pi: lights.pi_pins / pi_test (registered by lights_ops).

The tests that paint by hand pause the automatic painting for a few seconds (lights_loop.pause_for) and send M150 to the board; without
a physical strip they answer no_strip and send nothing. Same answers as the old handler: dicts for the result, failures as
{"ok": False, "error": ...}.
"""
import functools
import re
import threading
import time

import lights_config as lc
import lights_decide
import lights_frame
import lights_loop
import lights_output
import lights_profile as lp
import pi_leds
from messages import M


def needs_strip(fn):
    """Without an LED strip there is nothing to test on the board."""
    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        if not lp.clean(kwargs["config"])["strip"]["present"]:
            return lp.no_strip()
        return fn(*args, **kwargs)
    return guarded


@lp.needs_lights
def pi_pins():
    """Status lights on a pin of the Pi (Lights > Advanced): the pins with what each one can do, and the state of each output."""
    return lp.answer({"ok": True, "pins": pi_leds.list_items_pins(), "strips": pi_leds.states()})


@lp.needs_lights
def pi_test(config, pin, seconds):
    """A short test on the strip whose output is that pin of the Pi."""
    if pin in (None, ""):
        return lp.answer({"ok": False, "error": M("lights_pin_of_strip_to_test_missing")})
    c = lp.clean({"status_light": config.get("status_light") or {}})
    pin = int(pin)
    n = None
    for _, out, total in [(c["led_strip"], c["output"], c["led_start"] + c["led_count"] + sum(z["n"] for z in c["zones_extra"]))] + [
            (t["led_strip"], t["output"], sum(z["n"] for z in t["zones"])) for t in c["strips_extra"]]:
        if out["kind"] == "pi" and out["pin"] == pin:
            n = max(1, total)
    strip = pi_leds.STRIPS.get(pin)
    if strip is None or n is None:
        return lp.answer({"ok": False, "error": M("lights_strip_not_saved_its_output_pin")})
    r = strip.probe(n, 4 if seconds is None else seconds)
    r["strips"] = pi_leds.states()
    return lp.answer(r)


@lp.needs_lights
def test_state(config, state, seconds, outputs, data):
    """Shows one state on the chosen outputs for a few seconds (lights_frame.TEST); `data` is an optional {color, effect} to try."""
    c = lp.clean(config)
    ident = str(state).strip()
    if ident not in c["states"]:
        return lp.answer({"ok": False, "code": "unknown_state", "error": "Unknown state: " + ident})
    request = [x for x in re.split(r"[,\s]+", ",".join(outputs or [])) if x in lc.OUTPUTS]
    chosen = request or [o for o in lc.OUTPUTS if c["states"][ident]["outputs"].get(o)] or ["screen"]
    if not c["strip"]["present"]:
        chosen = [o for o in chosen if o != "strip"] or ["screen"]
    sec = lp.integer(seconds, lights_frame.TEST_SECONDS, 2, 20)
    extra = {}
    if data is not None:
        try:
            extra = {"color": lp.color(data.get("color"), c["states"][ident]["color"]) if data.get("color") else None,
                     "effect": data.get("effect")}
        except (ValueError, UnicodeDecodeError, TypeError, AttributeError):
            extra = {}
    r = lights_frame.probe_state(ident, sec, chosen, **extra)
    return lp.answer({"ok": True, "state": ident, "seconds": sec, "outputs": list(r["outputs"])})


def _send_segments(bridge, e, segments):
    """One M150 per segment (r, u, b, n) of strip E<e>, the last one without F so the board transmits the frame."""
    for i_, (r_, u_, b_, n_) in enumerate(segments):
        p_ = 255 if (r_ or u_ or b_) else 0
        bridge.send(f"M150 {e} R{r_} U{u_} B{b_} W0 P{p_} S{n_}" + (" F1" if i_ < len(segments) - 1 else ""))


def _prepare(config, seconds, strip):
    """Common start of test and identify: the layout, the length of the strip, and the automatic painting paused."""
    c = lp.clean(config)
    try:
        sec = max(2, min(30, int(float(6 if seconds is None else seconds))))
    except (TypeError, ValueError):
        sec = 6
    en, strip_x = lp.strip_of(c, strip)
    if strip_x:
        total = lp.m950(en)["total"] or sum(z["n"] for z in strip_x["zones"]) or 1
    else:
        total = lp.m950(c["led_strip"])["total"] or (c["led_start"] + c["led_count"])
    lights_loop.pause_for(sec)
    time.sleep(0.5)  # so the status_light loop sees the pause before painting
    return c, sec, f"E{en}", strip_x, total


def _count(count, total):
    try:
        return max(1, min(400, int(float(total if count is None else count))))
    except (TypeError, ValueError):
        return total


@lp.needs_lights
@needs_strip
def test_leds(bridge, config, count, seconds, strip):
    """Lights the first `count` LEDs of a strip in blue for a few seconds, to count them."""
    c, sec, e, strip_x, total = _prepare(config, seconds, strip)
    n = _count(count, total)
    if strip_x:
        _send_segments(bridge, e, [t_ for t_ in [(0, 80, 255, n), (0, 0, 0, max(0, total - n))] if t_[3] > 0])
        return lp.answer({"ok": True, "seconds": sec})
    rest = total - n
    ni_, ne_ = c["led_start"], c["led_count"]
    in_state = min(n, ne_) if c["order"] == "state_first" else max(0, min(ne_, n - ni_))
    try:
        bridge.set_status("statusLightSecs", [s_ for s_ in (["#0050ff", 1, in_state], ["#000000", 0, ne_ - in_state]) if s_[2] > 0])
    except Exception:
        pass
    lights_output.publish_strip(bridge, [(0, 80, 255, 0, 255, n), (0, 0, 0, 0, 0, max(0, rest))])
    if rest > 0:
        bridge.send(f"M150 {e} R0 U80 B255 W0 P255 S{n} F1")
        bridge.send(f"M150 {e} R0 U0 B0 W0 P0 S{rest}")
    else:
        bridge.send(f"M150 {e} R0 U80 B255 W0 P255 S{n}")
    return lp.answer({"ok": True, "encendidos": n, "seconds": sec})


def _identify_segments(segments, total):
    """The segments the page shows ([[r, g, b, count], ...] in strip order), the rest of the strip off."""
    request = segments
    out = [(lp.byte(t[0]), lp.byte(t[1]), lp.byte(t[2]), lp.integer(t[3], 0, 0, 400)) for t in request][:40]
    out.append((0, 0, 0, max(0, total - sum(t_[3] for t_ in out))))
    return [t_ for t_ in out if t_[3] > 0]


@lp.needs_lights
@needs_strip
def identify_leds(bridge, config, seconds, strip, segments):
    """Paints every zone of a strip in its own colour for a few seconds (or the `segments` of the page), to see where each zone is."""
    c, sec, e, strip_x, total = _prepare(config, seconds, strip)
    # Identify with what the page has ON SCREEN (even if not saved): one color per zone (the same ones as the page's boxes).
    if segments is not None:
        try:
            painted = _identify_segments(segments, total)
        except (ValueError, UnicodeDecodeError, TypeError, IndexError):
            return lp.answer({"ok": False, "error": M("lights_invalid_j")})
        _send_segments(bridge, e, painted)
        return lp.answer({"ok": True, "seconds": sec})
    if strip_x:
        # additional strip: alternating violet and green zones (you can see where each one ends)
        painted = [((180, 0, 255) if k % 2 == 0 else (0, 220, 90)) + (z["n"],) for k, z in enumerate(strip_x["zones"])]
        painted.append((0, 0, 0, max(0, total - sum(z["n"] for z in strip_x["zones"]))))
        _send_segments(bridge, e, [t_ for t_ in painted if t_[3] > 0])
        return lp.answer({"ok": True, "seconds": sec})
    # each zone in its color, in the real order of the strip: lighting amber, status light blue, extra zones violet
    colors = {"lighting": (255, 160, 0, c["led_start"]), "state": (0, 200, 255, c["led_count"])}
    for z in c["zones_extra"]:
        colors[z["id"]] = (180, 0, 255, z["n"])
    painted = [colors[i] for i in c["order_zones"] if i in colors]
    rest = max(0, total - sum(t_[3] for t_ in painted))
    painted = [t_ for t_ in painted if t_[3] > 0] + ([(0, 0, 0, rest)] if rest else [])
    _send_segments(bridge, e, painted)
    try:
        bridge.set_status("statusLightSecs", [["#00c8ff", 1, c["led_count"]]] if c["led_count"] > 0 else [])  # the interface sees the same as the strip
    except Exception:
        pass
    lights_output.publish_strip(bridge, [(r_, u_, b_, 0, 255 if (r_ or u_ or b_) else 0, n_) for r_, u_, b_, n_ in painted])
    return lp.answer({"ok": True, "seconds": sec})


def _run_animation(bridge, config, trial):
    try:
        if trial:
            lp.write_lights_g(lp.clean(config))  # makes sure the globals exist
            bridge.send('M98 P"0:/sys/workshop/macros/system/lights.g"')
            col = lp.color(trial.get("color"), lp.DEFAULTS["animation"]["color"])
            type_name = trial.get("kind") if trial.get("kind") in lp.KINDS_ANIMATION else "bar"
            try:
                step = max(1, min(60, int(trial.get("step", 6))))
            except (TypeError, ValueError):
                step = 6
            bridge.send("set global.ledAnimActive = true")
            bridge.send(f'set global.ledAnimKind = "{type_name}"')
            bridge.send(f"set global.ledAnimColor = {{{col['r']}, {col['u']}, {col['b']}, {col['w']}}}")
            bridge.send(f"set global.ledAnimStep = {step}")
            bridge.send('M98 P"0:/sys/ledstartup.g" V1')
            bridge.send('M98 P"0:/sys/workshop/macros/system/lights.g"')
        else:
            bridge.send('M98 P"0:/sys/ledstartup.g"')
    except Exception:
        pass
    finally:
        # the M98 returns when the animation has finished: repaint the normal state right away (do not wait for the pause to expire)
        lights_loop.pause_until(0.0)


@lp.needs_lights
@needs_strip
def animation(bridge, config, data):
    """Runs the start-up animation now (sys/ledstartup.g). `data` (optional, {kind, color, step}) is TRIED without saving: those values
    are put in the globals, the animation runs in preview mode (V1: it does not reload lights.g) and afterwards lights.g gives back the
    saved ones."""
    lights_loop.pause_for(8)
    threading.Thread(target=_run_animation, args=(bridge, config, data), daemon=True).start()
    return lp.answer({"ok": True})


def _illum_current(bridge):
    """Current color of the work light (so as not to turn it off when painting)."""
    try:
        v = bridge.send("echo global.lightZoneColor")
        nums = [int(x) for x in re.findall(r"-?\d+", v or "")][:5]
        return nums if len(nums) == 5 else [0, 0, 0, 0, 0]
    except Exception:
        return [0, 0, 0, 0, 0]


def _simulate(bridge, c, sim, illum, end):
    """REAL simulation: the same calculation as the strip (lights_decide.compute) with the page's config (even if not saved) and sample
    states: turns, blinking, split and progress bar come out exactly as they will look."""
    slc = dict(sim.get("config") or {})
    slc["led_count"] = lights_decide.zone_state(c)[4]
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
        secs, _, _ = lights_decide.compute(cfg_sim, kind, False, illum, status, int(prog * 1000), 1000, extras)
        if secs != last:
            lights_output.paint_state(bridge, illum, secs, c)
            last = secs
        time.sleep(0.2)


def _animate(bridge, c, frames, sim, seconds, interval):
    illum = _illum_current(bridge)
    try:
        end = time.time() + seconds
        i = 0
        time.sleep(0.4)
        if sim:
            _simulate(bridge, c, sim, illum, end)
            return
        while time.time() < end:
            secs = [(lp.byte(s[0]), lp.byte(s[1]), lp.byte(s[2]), lp.byte(s[3]), 255, max(0, int(s[4])))
                    for s in frames[i % len(frames)]]
            lights_output.paint_state(bridge, illum, secs, c)
            i += 1
            time.sleep(interval)
    except Exception:
        pass


@lp.needs_lights
@needs_strip
def preview(bridge, config, data):
    """Paints sample frames on the status zone without saving anything (Lights page: try the end-of-job notice or how several states
    combine). data = {"frames": [[[r,g,b,w,count], ...], ...], "interval": s, "seconds": s} or {"simulate": {...}, "seconds": s}."""
    d = data
    c = lp.clean(config)
    frames = d.get("frames") or []
    sim = d.get("simulate") if isinstance(d.get("simulate"), dict) else None
    if not frames and not sim:
        return lp.answer({"ok": False, "error": M("lights_no_frames")})
    interval = max(0.15, min(5.0, float(d.get("interval", 1.0))))
    seconds = max(1.0, min(20.0, float(d.get("seconds", 6.0))))
    lights_loop.pause_for(seconds + 1)
    threading.Thread(target=_animate, args=(bridge, c, frames, sim, seconds, interval), daemon=True).start()
    return lp.answer({"ok": True, "seconds": seconds})
