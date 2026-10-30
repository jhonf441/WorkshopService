"""
Internal implementation of the API operation(s) power.after_job, power.method, power.timer, power.timer_cancel (api_ops.py maps their named
arguments to the one-letter parameters below).

Arms/disarms the automatic shutdown at the end of the current job (or the
next one that starts). sys/daemon.g reads global.powerOffOnFinish (in RRF)
to decide when to fire macros/power/shutdown-all.g; this handler is the
ONLY way to change it -- both the plugin UI button and the BtnCmd/DWC
macro (macros/power/shutdown-after-job.g) go through here, so that both
sides (the RRF global and what the UI shows) never get out of sync.

Usage: <params> S"armar"
     <params> S"desarmar"
     <params> S"toggle"   (default)

"""
import time

import activity
from messages import M, J, B


def run(params, bridge, config):
    state = str(params.get("S", "toggle")).strip().lower()

    # Shutdown with timer (controls bar, 2026-10-10):
    # <params> S"temporizar" N<minutes 1..720>
    # (N, not M: a loose M is taken by the Duet as another command, e.g. "M720")
    # <params> S"cancel_timer"
    # The count is kept by dsf/shutdown_timer.py (it survives restarts).
    # How it turns off (2026-10-10, see shutdown_method.py):
    # <params> S"metodo" C"auto"|"medidor"|"rele"|"pson" [A1|A0 = also shut down the Pi] [R<output> V<0|1> of the
    # relay]
    if state == "method":
        import shutdown_method

        ap = config.setdefault("shutdown", {})
        c = str(params.get("C", "")).strip().lower()
        if c:
            if c not in shutdown_method.METHODS:
                return M("shutdown_method_use_c_auto_c_meter")
            ap["method"] = c
        if params.get("A") is not None:
            ap["power_off_pi"] = str(params.get("A")).strip() not in ("0", "false", "no")
        # relay: R<M950 P output> and V<0|1> = value of M42 that CUTS the power
        if params.get("R") is not None or params.get("V") is not None:
            rl = dict(ap.get("relay") or {})
            if params.get("R") is not None:
                try:
                    n = int(float(params.get("R")))
                except (TypeError, ValueError):
                    return M("shutdown_relay_r_has_output_number_m950")
                if not 0 <= n <= 63:
                    return M("shutdown_relay_output_goes_from_0_63")
                rl["output"] = n
            if params.get("V") is not None:
                rl["power_off_with"] = 1 if str(params.get("V")).strip() in ("1", "1.0") else 0
            ap["relay"] = rl
        bridge.save_config()
        i = shutdown_method.emit(bridge, config, force=True)
        activity.log_event(bridge, "config", M("shutdown_method_set", method=i["method"], effective=i["effective"], pi=M("yes") if i["power_off_pi"] else M("no")))
        return M("shutdown_power_off_method", desc=i["desc"]) if not i["notice"] else M("shutdown_power_off_method_notice", desc=i["desc"], notice=i["notice"])

    if state == "temporizar":
        # without valid minutes NOTHING is scheduled (before it fell back to 1 minute)
        try:
            minutes = int(float(params.get("N")))
        except (TypeError, ValueError):
            return M("shutdown_timer_minutes_missing")
        if not 1 <= minutes <= 720:
            return M("shutdown_timer_minutes_range")
        ap = config.setdefault("shutdown", {})
        # integer: dsf-python writes json floats with 6 digits (the time
        # ended up rounded to ~15 min in config.json and on the screen)
        ap["timer_until"] = int(time.time() + minutes * 60)
        ap["timer_min"] = minutes
        bridge.save_config()
        activity.log_event(bridge, "config", M("shutdown_timer_set", minutes=minutes))
        return M("shutdown_timer_set", minutes=minutes)
    if state == "cancel_timer":
        ap = config.setdefault("shutdown", {})
        was = ap.pop("timer_until", None)
        ap.pop("timer_min", None)
        bridge.save_config()
        bridge.set_status("shutdownTimer", None)
        if was:
            activity.log_event(bridge, "config", M("shutdown_timer_cancelled"))
        return M("shutdown_timer_cancelled")

    current = bool(config.get("shutdown", {}).get("on_finish", False))

    if state == "arm":
        new = True
    elif state == "disarm":
        new = False
    else:
        new = not current

    config.setdefault("shutdown", {})["on_finish"] = new
    bridge.save_config()
    bridge.set_status("powerOffOnFinish", new)
    bridge.send(f'set global.powerOffOnFinish = {"true" if new else "false"}')
    activity.log_event(bridge, "config", M("shutdown_on_finish", state=M("armed") if new else M("disarmed")))

    return M("shutdown_power_off_on_finish_armed") if new else M("shutdown_power_off_on_finish_disarmed")
