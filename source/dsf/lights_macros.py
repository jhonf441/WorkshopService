"""The working light and the status LEDs by hand: light.set and statuslight.set (registered by lights_ops).

They run the macros of the board (light/lighton.g, lightoff.g, statusledon.g, statusledoff.g), which already hold the real colour, the
global.statusLedDisabled flag and the cache refresh that sys/daemon.g needs; this module only fires them and keeps the state the pages
show. The send is done in another thread: it runs inside the call that is still waiting for its answer, and sending another code to RRF
before that one resolves can end up waiting for the same channel to be released (a deadlock; see air_assist_on). A failure there only
left a loose traceback in the log (seen 2026-10-08 with a timeout), so it is swallowed: Bridge.send already logged it.
"""
import threading

from messages import M


def _apply(macro, status_key, value, bridge):
    try:
        bridge.send(f'M98 P"0:/macros/light/{macro}"')
        bridge.set_status(status_key, value)
    except Exception:
        pass  # Bridge.send already left it in the log


def _fire(macro, status_key, value, bridge):
    threading.Thread(target=_apply, args=(macro, status_key, value, bridge), daemon=True).start()


def work_light(on, bridge):
    """Switches the lighting zone on or off (macro lighton.g / lightoff.g); answers the message the pages show."""
    if on:
        _fire("lighton.g", "lightOn", True, bridge)
        return M("light_turning_lighting")
    _fire("lightoff.g", "lightOn", False, bridge)
    return M("light_turning_lighting_off")


def status_leds(on, bridge):
    """True gives the status LEDs back to the automatic control, False switches them off by hand (statusledon.g / statusledoff.g)."""
    if on:
        _fire("statusledon.g", "statusLightAuto", True, bridge)
        return M("statuslight_status_leds_automatic_control_back")
    _fire("statusledoff.g", "statusLightAuto", False, bridge)
    return M("statuslight_status_leds_off_by_hand")
