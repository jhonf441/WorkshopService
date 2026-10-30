"""
Watches the G-code bridge unit and says in the Activity history when it starts and when it stops, and WHY.

Until now only a restart asked from the Services page was recorded (and in the memory of the bridge, so it was lost with the
restart). A start at boot, after a power cut, or by systemd after an unexpected exit left no trace. Here the service compares,
on each cycle of health_poller, the moment the unit entered "active" (systemd's ActiveEnterTimestampMonotonic: microseconds
since the boot, no rounding) with the last one it saw:

    changed          -> "started" (reason: Pi boot / asked from the page / automatic)
    active -> not    -> "stopped" (reason: asked from the page / not by the page)

The first reading only sets the baseline (no event: the service itself may be the one that just started).
"""
import time
from messages import M

BOOT_MARGIN_S = 180      # the bridge entered "active" at most this long after the Pi booted: it started with the Pi
PAGE_WINDOW_S = 120   # an order given from the page counts as the reason for a change that happens within this time


def reason_start(active_since_us, pi_uptime_s, request_page, restart_request):
    """Why the unit started: 'boot', 'page' or 'auto'.
    activo_desde_us: ActiveEnterTimestampMonotonic (microseconds since boot) or None; pi_uptime_s: seconds since the Pi booted;
    pedido_pagina: the seconds since the page asked to turn the bridge on (None = never / long ago);
    reinicio_pedido: the bridge reported that the page asked to restart it a moment ago."""
    if request_page is not None and request_page <= PAGE_WINDOW_S:
        return "page"
    if restart_request:
        return "page"
    if active_since_us is not None and active_since_us / 1e6 <= BOOT_MARGIN_S:
        return "boot"
    return "auto"


TEXTS_ES = {
    "boot": M("bridge_watchdog_g_code_bridge_started_at_pi_boot"),
    "page": M("bridge_watchdog_g_code_bridge_started_from_page"),
    "auto": M("bridge_watchdog_g_code_bridge_restarted_by_itself"),
    "stop_page": M("bridge_watchdog_g_code_bridge_stopped_from_page"),
    "stop_other": M("bridge_watchdog_g_code_bridge_stopped_not_from"),
}


def watch(mem, is_active, active_since_us, pi_uptime_s, request_page=None, restart_request=False, flag_shutdown=False):
    """One cycle. mem: dict kept between cycles. Returns the text of the event to record, or None."""
    previous = mem.get("seen")
    mem["seen"] = True
    raw_text = None
    if not previous:
        pass  # baseline
    elif is_active and (not mem.get("active") or active_since_us != mem.get("since_us")):
        raw_text = TEXTS_ES[reason_start(active_since_us, pi_uptime_s, request_page, restart_request)]
    elif not is_active and mem.get("active"):
        by_page = flag_shutdown or (request_page is not None and request_page <= PAGE_WINDOW_S)
        raw_text = TEXTS_ES["stop_page" if by_page else "stop_other"]
    mem["active"] = bool(is_active)
    mem["since_us"] = active_since_us
    return raw_text
