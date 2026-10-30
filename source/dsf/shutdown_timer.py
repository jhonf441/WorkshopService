"""
Shutdown with timer (controls bar, 2026-10-10).

The shutdown time lives in config.json["apagado"]["timer_until"]
(epoch, set/removed by handlers/shutdown.py with S"temporizar" / S"cancelar_
temporizador"), so it survives a plugin restart and does not depend on a
screen being open. This loop:
  - publishes plugins.WorkshopService.data.shutdownTimer
    {"hasta": "HH:MM", "missing_s": n, "minutos": m} (or None)
  - 60 s before, warns in DWC (M291 S1, non-blocking)
  - when the time comes: if there is a job in progress (file or live)
    it does NOT cut: it arms "Shut down when finished"; otherwise it runs the same
    safe shutdown as "Shut down now" (handlers/shutdown_all.py, without the
    macro's confirmation: it was already confirmed when scheduling).

"""
import job_states
import importlib.util
import os
import time

import activity
import heartbeats
from messages import M, J, B

HANDLERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handlers")
WORKING = job_states.ACTIVE


def _state_machine():
    try:
        import machine_state  # single subscription to DSF (no HTTP)

        return machine_state.read_in("state.status", "", timeout=5) or ""
    except Exception:
        return ""


def _handler(label):
    route = os.path.join(HANDLERS_DIR, label + ".py")
    spec = importlib.util.spec_from_file_location("handler_" + label, route)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _remove(config, bridge):
    config.setdefault("shutdown", {}).pop("timer_until", None)
    config["shutdown"].pop("timer_min", None)
    bridge.save_config()
    bridge.set_status("shutdownTimer", None)


def run_loop(bridge, config):
    notified_for = None
    published = "start"
    method_ts = 0
    while True:
        # how it turns off (meter / PS_ON): for the bar and the macro's
        # confirmation; every 30 s in case the meter is configured or config.g changes
        if time.time() - method_ts > 30:
            method_ts = time.time()
            try:
                import shutdown_method

                shutdown_method.emit(bridge, config)
            except Exception as e:
                heartbeats.error("timer", e)
        ap = config.get("shutdown") or {}
        until = ap.get("timer_until")
        if not until:
            if published is not None:
                bridge.set_status("shutdownTimer", None)
                published = None
            heartbeats.detail("timer", M("shutdown_timer_no_scheduled_power_off"))
            heartbeats.ok("timer")
            time.sleep(2)
            continue

        missing = int(until - time.time())
        datum = {"until": time.strftime("%H:%M", time.localtime(until)), "missing_s": max(0, missing),
                "minutes": ap.get("timer_min")}
        bridge.set_status("shutdownTimer", datum)
        published = datum
        heartbeats.detail("timer", M("shutdown_timer_power_off_scheduled_at", until=datum['until'], min=max(0, missing) // 60))

        if 0 < missing <= 60 and notified_for != until:
            notified_for = until
            try:
                # bilingual like the workshop macros (global.workshopLanguage, sys/workshop/macros/language.g)
                body, title = M("shutdown_timer_machine_powers_off_in_1_minute"), M("shutdown_timer_scheduled_power_off")
                bridge.send('M291 P{(exists(global.workshopLanguage) && global.workshopLanguage == "en")'
                            ' ? "' + body.text("en") + '" : "' + body.text("es") + '"}'
                            ' R{(exists(global.workshopLanguage) && global.workshopLanguage == "en") ? "' + title.text("en") + '" : "' + title.text("es") + '"}'
                            ' S1 T30')
            except Exception:
                pass

        if missing <= 0:
            status = _state_machine()
            in_live = ((getattr(bridge, "payload", {}) or {}).get("liveJob") or {})
            if status in WORKING or (isinstance(in_live, dict) and in_live.get("active")):
                # never cut a job in half: it shuts down when it finishes
                _remove(config, bridge)
                try:
                    _handler("shutdown").run({"S": "arm"}, bridge, config)
                except Exception as e:
                    heartbeats.error("timer", e)
                activity.log_event(bridge, "power", M("timer_job_running"))
            else:
                _remove(config, bridge)
                activity.log_event(bridge, "power", M("timer_shutting_down"))
                try:
                    _handler("apagartodo").run({}, bridge, config)
                except Exception as e:
                    heartbeats.error("timer", e)
        heartbeats.ok("timer")
        time.sleep(2)
