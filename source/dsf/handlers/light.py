"""
Internal implementation of the API operation(s) light.set (api_ops.py maps their named
arguments to the one-letter parameters below).

Turns on/off the lighting zone of the NeoPixel strip (the first 20
LEDs). It reuses the existing macros lighton.g/lightoff.g -- the real
color/brightness lives there, this handler only fires them and saves the
state so that the DWC panel shows it.

Usage: <params> S"on"   (or S"off")
Also meant to be called from a BtnCmd button.

"""
import threading
from messages import M

ON_VALUES = {"on", "1", "true", "255"}
OFF_VALUES = {"off", "0", "false"}


def _apply(macro, light_on, bridge):
    try:  # separate thread: without this a timeout left a loose traceback
        bridge.send(f'M98 P"0:/macros/light/{macro}"')
        bridge.set_status("lightOn", light_on)
    except Exception:
        pass  # Bridge.send already left it in the log


def run(params, bridge, config):
    state = str(params.get("S", "")).strip().lower()

    # The real send is done in another thread: this runs inside the callback
    # that handles the intercepted API call, and sending another code to RRF before
    # resolving THIS code can end up waiting for the same channel to be released
    # -- a deadlock. See the same fix in air_assist_on().
    if state in ON_VALUES:
        threading.Thread(target=_apply, args=("lighton.g", True, bridge), daemon=True).start()
        return M("light_turning_lighting")

    if state in OFF_VALUES:
        threading.Thread(target=_apply, args=("lightoff.g", False, bridge), daemon=True).start()
        return M("light_turning_lighting_off")

    return "Error: light.set needs on"
