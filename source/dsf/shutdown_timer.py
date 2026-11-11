"""
Shutdown with timer (controls bar, 2026-10-10).

The shutdown time lives in config.json["apagado"]["timer_until"]
(epoch, set/removed by power_config.py: power.timer / power.timer_cancel), so it survives a plugin restart and does not depend on a
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
import time

import activity
import clock
import heartbeats
import power_config
import power_off
from messages import M, J, B

WORKING = job_states.ACTIVE


class Countdown:
    """Seconds left until the scheduled shutdown, immune to jumps of the wall clock.

    config["shutdown"]["timer_until"] is a WALL epoch because it must survive a restart of the service and be shown as HH:MM
    (power_config.timer computes it as now + minutes at the moment the user schedules). Deciding with `until - wall()` would
    cut the power for real when NTP steps the clock forward (a Pi has no battery clock) and would never fire after a step
    backward. So the first time this loop sees a given `until` it converts it ONCE into a monotonic deadline; from then on only
    the monotonic clock counts. If a user ever schedules an absolute hour ("at 18:00") the conversion at that moment is still
    the right one (remaining = target - wall()); a later clock step moves the hour shown, not the countdown that is already
    armed. Known limit: a timer that is first seen after a restart is converted with the wall clock of that moment (an
    unsynchronised clock then can still skew it); a persisted "seconds remaining + boot id" is the follow-up."""

    def __init__(self):
        self._until = None
        self._deadline = None

    def missing(self, until):
        """Whole seconds left (negative when overdue); None when nothing is scheduled."""
        if not until:
            self._until = self._deadline = None
            return None
        if until != self._until:  # a new schedule (or the first sight after a restart): arm it
            self._until = until
            # wall clock, read once: converts the stored wall epoch into a monotonic deadline
            self._deadline = clock.mono() + (until - clock.wall())
        return int(self._deadline - clock.mono())

    def shown_epoch(self):
        """Wall epoch to display as HH:MM: now + what is left, so it stays coherent after a clock step."""
        return round(clock.wall() + (self._deadline - clock.mono()))  # wall clock, only shown; rounded: no flicker of the minute


def _state_machine():
    try:
        import machine_state  # single subscription to DSF (no HTTP)

        return machine_state.read_in("state.status", "", timeout=5) or ""
    except Exception:
        return ""


def _remove(config, bridge):
    config.setdefault("shutdown", {}).pop("timer_until", None)
    config["shutdown"].pop("timer_min", None)
    bridge.save_config()
    bridge.set_status("shutdownTimer", None)


def run_loop(bridge, config):
    notified_for = None
    published = "start"
    method_ts = None  # monotonic reading of the last emit; None = emit on the first pass
    countdown = Countdown()
    while True:
        # how it turns off (meter / PS_ON): for the bar and the macro's
        # confirmation; every 30 s in case the meter is configured or config.g changes
        if method_ts is None or clock.mono() - method_ts > 30:
            method_ts = clock.mono()
            try:
                import shutdown_method

                shutdown_method.emit(bridge, config)
            except Exception as e:
                heartbeats.error("timer", e)
        ap = config.get("shutdown") or {}
        until = ap.get("timer_until")
        if not until:
            countdown.missing(None)
            if published is not None:
                bridge.set_status("shutdownTimer", None)
                published = None
            heartbeats.detail("timer", M("shutdown_timer_no_scheduled_power_off"))
            heartbeats.ok("timer")
            time.sleep(2)
            continue

        missing = countdown.missing(until)
        # wall clock: only to show the hour
        datum = {"until": time.strftime("%H:%M", time.localtime(countdown.shown_epoch())), "missing_s": max(0, missing),
                "minutes": ap.get("timer_min")}
        bridge.set_status("shutdownTimer", datum)
        published = datum
        heartbeats.detail("timer", M("shutdown_timer_power_off_scheduled_at", until=datum['until'], min=max(0, missing) // 60))

        if 0 < missing <= 60 and notified_for != until:
            notified_for = until
            try:
                # bilingual like the workshop macros (global.workshopLanguage, sys/workshop/macros/system/language.g)
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
                    power_config.after_job(bridge, config, True)
                except Exception as e:
                    heartbeats.error("timer", e)
                activity.log_event(bridge, "power", M("timer_job_running"))
            else:
                _remove(config, bridge)
                activity.log_event(bridge, "power", M("timer_shutting_down"))
                try:
                    power_off.power_off(bridge, config)  # was _handler("apagartodo"): that file was renamed on 2026-10-18 and the timer never fired since
                except Exception as e:
                    heartbeats.error("timer", e)
        heartbeats.ok("timer")
        time.sleep(2)
