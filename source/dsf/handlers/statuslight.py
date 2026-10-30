"""
Internal implementation of the API operation(s) statuslight.set (api_ops.py maps their named
arguments to the one-letter parameters below).

Manual control of the 17 "status" LEDs (indices 20-36) of the NeoPixel
strip. It reuses the existing macros statusledon.g/statusledoff.g,
which already handle the global.statusLedDisabled flag and the cache
refresh that sys/daemon.g needs -- this handler only fires them.

Usage: <params> S"on"   (automatic control by mode/state)
     <params> S"off"  (turned off by hand)
Also meant to be called from a BtnCmd button.

"""
import threading
from messages import M

ON_VALUES = {"on", "1", "true"}
OFF_VALUES = {"off", "0", "false"}


def _apply(macro, light_on, bridge):
    # In a separate thread: an uncaught exception here only left a
    # traceback in the log (seen 2026-10-08 with a timeout).
    try:
        bridge.send(f'M98 P"0:/macros/light/{macro}"')
        bridge.set_status("statusLightAuto", light_on)
    except Exception:
        pass  # Bridge.send already left it in the log


def run(params, bridge, config):
    state = str(params.get("S", "")).strip().lower()

    # Same fix as light.py: the real send goes in another thread so as not to
    # deadlock with the API call itself that has not resolved yet.
    if state in ON_VALUES:
        threading.Thread(target=_apply, args=("statusledon.g", True, bridge), daemon=True).start()
        return M("statuslight_status_leds_automatic_control_back")

    if state in OFF_VALUES:
        threading.Thread(target=_apply, args=("statusledoff.g", False, bridge), daemon=True).start()
        return M("statuslight_status_leds_off_by_hand")

    return "Error: statuslight.set needs on"
