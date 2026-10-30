"""
Internal implementation of the API operation(s) air.auto, air.delay, air.set (api_ops.py maps their named
arguments to the one-letter parameters below).

Controls the air pump (cutting assistance, OUT2 / logical GPIO 7):

- S"on" / S"off": turns the pump on/off NOW, by hand, and updates the
  state shown by the plugin UI. Before this, both the
  "Turn pump on/off" buttons of the plugin page and "Air ON/OFF" of
  BtnCmd sent M42 P7 S1/S0 directly -- the plugin page LOOKED
  in sync because it drew the change optimistically at the moment of
  the click, but it went stale on any other trigger
  (BtnCmd, console, another macro), and BtnCmd did not even have that
  optimistic drawing. Confirmed by the user 2026-10-06. Passing everything
  through here (UI, BtnCmd, and any future macro) leaves a single real state.
- S"auto_on" / S"auto_off": turns on/off the automatic mode that follows
  M3/M4/M5 by itself (without touching the pump's current on/off state).

- S"retardo" D<seconds>: how long the automatic mode waits after M5 before
  turning the pump off (0-60 s).

Usage: <params> S"on"|"off"|"auto_on"|"auto_off"|"retardo" D<s>

"""
import threading
from messages import M


def _apply(macro, air_on, bridge):
    # The real send goes in a separate thread -- this runs inside the callback
    # that handles the intercepted API call, and sending another code to RRF BEFORE
    # resolving this same code ends up waiting for the same channel to be released:
    # a deadlock. The same fix already used by light.py and
    # air_assist_on() in main.py -- I had missed it here. Confirmed in
    # production 2026-10-06: without this, <params> S"on"/"off"
    # always raises TimeoutError, even though a loose M42 P.. S.. (without going
    # through an API call) works instantly.
    #
    # It calls the macro (laser/airon.g or airoff.g) instead of sending M42 P7
    # directly: those macros already carry the check for
    # "global.selectedMode = Laser" (the GPIO7 pin only exists in Laser
    # mode), so sending a raw M42 from here skipped that guard.
    # It also keeps a single source of truth with the live jobs (which call
    # these same macros) and with the automatic mode via M3/M4/M5.
    bridge.send(f'M98 P"0:/macros/laser/{macro}"')
    bridge.set_status("airAssist", air_on)


def run(params, bridge, config):
    state = str(params.get("S", "")).strip().lower()

    if state == "on":
        threading.Thread(target=_apply, args=("airon.g", True, bridge), daemon=True).start()
        return M("airassist_turning_air_pump_on_by_hand")

    if state == "off":
        threading.Thread(target=_apply, args=("airoff.g", False, bridge), daemon=True).start()
        return M("airassist_turning_air_pump_off_by_hand")

    if state == "auto_on":
        config["air_assist"]["auto_enabled"] = True
        bridge.save_config()
        bridge.set_status("airAssistAuto", True)
        return M("airassist_automatic_air_assist_m3_m4_m5")

    if state == "auto_off":
        config["air_assist"]["auto_enabled"] = False
        bridge.save_config()
        bridge.set_status("airAssistAuto", False)
        return M("airassist_automatic_air_assist_m3_m4_m5_2")

    if state == "delay":
        try:
            d = max(0.0, min(float(params.get("D", 2)), 60.0))
        except (TypeError, ValueError):
            return "Error: air.delay needs seconds"
        config["air_assist"]["off_delay_s"] = d
        bridge.save_config()
        bridge.set_status("airAssistDelay", d)
        return M("airassist_air_assist_turns_off_s_after", d=d)

    return "Error: unknown air assist action"
