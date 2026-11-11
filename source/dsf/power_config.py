"""Settings of the power off: power.after_job, power.timer, power.timer_cancel and power.method (api_ops registers them through power_ops).

They were handlers/shutdown.py. sys/daemon.g reads global.powerOffOnFinish (in RRF) to decide when to run the power off, and
after_job() is the ONLY way to change it: the plugin button and the macro macros/power/shutdown-after-job.g both go through the
operation, so the RRF global and what the pages show never get out of sync. The count of the timer is kept by shutdown_timer.py
(it survives restarts); the way the power is cut is described by shutdown_method.py.
"""
import time

import activity
import shutdown_method
from messages import M


def after_job(bridge, config, armed):
    """Arms (True), disarms (False) or toggles (None) the power off at the end of the job. Returns the text for the caller."""
    current = bool(config.get("shutdown", {}).get("on_finish", False))
    new = (not current) if armed is None else bool(armed)
    config.setdefault("shutdown", {})["on_finish"] = new
    bridge.save_config()
    bridge.set_status("powerOffOnFinish", new)
    bridge.send(f'set global.powerOffOnFinish = {"true" if new else "false"}')
    activity.log_event(bridge, "config", M("shutdown_on_finish", state=M("armed") if new else M("disarmed")))
    return M("shutdown_power_off_on_finish_armed") if new else M("shutdown_power_off_on_finish_disarmed")


def timer(bridge, config, minutes):
    """Schedules the power off in `minutes` (1 to 720)."""
    if not 1 <= minutes <= 720:
        return M("shutdown_timer_minutes_range")
    ap = config.setdefault("shutdown", {})
    # integer: dsf-python writes json floats with 6 digits (the time ended up rounded to ~15 min in config.json and on the screen)
    ap["timer_until"] = int(time.time() + minutes * 60)
    ap["timer_min"] = minutes
    bridge.save_config()
    activity.log_event(bridge, "config", M("shutdown_timer_set", minutes=minutes))
    return M("shutdown_timer_set", minutes=minutes)


def timer_cancel(bridge, config):
    ap = config.setdefault("shutdown", {})
    was = ap.pop("timer_until", None)
    ap.pop("timer_min", None)
    bridge.save_config()
    bridge.set_status("shutdownTimer", None)
    if was:
        activity.log_event(bridge, "config", M("shutdown_timer_cancelled"))
    return M("shutdown_timer_cancelled")


def method(bridge, config, method=None, power_off_system=None, relay_output=None, relay_value=None):
    """How the power off cuts the power (auto / meter / relay / pson). Only the arguments given change."""
    ap = config.setdefault("shutdown", {})
    if method:
        if method not in shutdown_method.METHODS:
            return M("shutdown_method_use_c_auto_c_meter")
        ap["method"] = method
    if power_off_system is not None:
        ap["power_off_pi"] = bool(power_off_system)
    # relay: the M950 P output and the value of M42 that CUTS the power
    if relay_output is not None or relay_value is not None:
        rl = dict(ap.get("relay") or {})
        if relay_output is not None:
            if not 0 <= relay_output <= 63:
                return M("shutdown_relay_output_goes_from_0_63")
            rl["output"] = relay_output
        if relay_value is not None:
            rl["power_off_with"] = 1 if relay_value == 1 else 0
        ap["relay"] = rl
    bridge.save_config()
    i = shutdown_method.emit(bridge, config, force=True)
    activity.log_event(bridge, "config", M("shutdown_method_set", method=i["method"], effective=i["effective"], pi=M("yes") if i["power_off_pi"] else M("no")))
    return M("shutdown_power_off_method", desc=i["desc"]) if not i["notice"] else M("shutdown_power_off_method_notice", desc=i["desc"], notice=i["notice"])
