"""
Paints the WHOLE LED strip from the Pi: the status zone (mode, states, progress bar), the lighting and the extra zones, in the order of the Lights page. It is the ONLY one that paints (2026-10-10): sys/daemon.g no longer sends M150 and the light macros (lighton/lightoff/statusledoff) only change their variable; this loop sees the change and repaints.

Since 2026-10-12 this module does NOT poll DSF: it reads the shared subscription model of machine_state.py (in memory, global.** included) and decides again only when that model changes (machine_state.on_change) or, while an animation needs frames, on a short timer that needs no IPC. It sends M150 only when the frame really changed and publishes plugin data only when a payload changed. Counters of what it still asks (ipc_stats) go to servicesInternal.luces. Before: one evaluate_expression every 0.4 s (2.5 calls/s) plus the RS485 reads (about 1 call/s).

If this process dies, the strip keeps the last frame (nobody else paints, at the user's request: a single owner of the strip). On reconnecting, it repaints everything at once.

Since phase 6a (2026-11) this file is only the FACADE: the code lives in layers, from the inside out:
  lights_decide  the decisions (pure): compute, zone_state, layout, read_input...
  lights_board   the board's own LEDs and the virtual status strip (pure): state_board, led_board, strip_state
  lights_frame   everything the three outputs show now (pure): arm_frame, the "test this state" request
  lights_output  what leaves the process: M150, the Pi's SPI strips, published data, counters, log
  lights_loop    Painter (one tick = one decision), the RS485 reader and run_loop
Every name other modules and tests used before is re-exported here, with its old name too (the old private names are aliases).
Assigning a name here assigns it in the module that owns it: only the tests do that (they replace `compute` / `paint_state` and set `PAUSE_UNTIL`; the lights operations pause the loop through lights_loop.pause_for / pause_until).
"""
import sys
import threading
import time  # noqa: F401  (tests replace time.sleep through this name)
import types

import lights_decide
import lights_board
import lights_frame
import lights_output
import lights_loop
import lights_counters
import service_modules

from dsf.connections import CommandConnection

from lights_decide import (  # noqa: F401
    LED_COUNT_DEFAULT,
    STATE_COLORS_DEFAULT,
    RS485_IDS,
    rs_discover,
    color_for,
    compute_state,
    STATES_DEF,
    TEXT_OF,
    state_cfg,
    sanitize,
    zone_state,
    config_state,
    strips_extra_segments,
    layout,
    hex_color,
    secs_ui,
    is_live,
    EFFECTS_IN_JOB,
    ALWAYS_WITH_EFFECT,
    MIN_BETWEEN_PAINTED_JOB_S,
    MAX_BETWEEN_PAINTED_SLOW_S,
    DUET_WITHOUT_EFFECT,
    effects_frozen,
    pi_paints,
    compute,
    MODES_COMBINE,
    modes_ui,
    pi_hot,
    motors_released,
    unclean_shutdown,
    read_input,
    rs_values,
)

from lights_board import (  # noqa: F401
    STATUS_MIDDLE_SYNC_S,
    STATUS_MIDDLE_WITHOUT_SYNC_S,
    MIDDLE_MIN_STRIP_S,
    VIN_MIN_V,
    V12_MIN_V,
    COLOR_NETWORK,
    COLOR_GREEN,
    COLOR_BLUE,
    COLOR_AMBER,
    LEDS_BOARD_DEF,
    LEDS_BOARD_IDS,
    BOARDS_VIEWS,
    num,
    state_board,
    thresholds_board,
    led_board,
    is_on,
    leds_board_segments,
    apply_leds_board,
    next_change_board,
    GROUPS_STRIP_STATE,
    HEX_SHUTDOWN,
    sec_entry,
    hex_of_color,
    strip_state,
)

from lights_frame import (  # noqa: F401
    TEST,
    TEST_SECONDS,
    probe_state,
    test_active,
    state_test,
    arm_frame,
    detail_ui,
)

from lights_counters import (  # noqa: F401
    COUNTER,
    COUNTER_TS,
    COUNTER_LOCK,
    count,
    ipc_stats,
    counters_a_zero,
)

from lights_output import (  # noqa: F401
    log_file,
    PI_BY_E,
    configure_outputs,
    send_batch,
    paint_block,
    CONFIG_G,
    DECLARED,
    e_declared,
    paint_segments,
    POWER,
    paint_segment_list,
    paint_state,
    PUB_STRIP,
    publish_strip,
    send_led_strip,
    publish_strip_state,
    effect_end_job,
    WithoutM150,
    power_off_state,
    CountedBridge,
)

from lights_loop import (  # noqa: F401
    POLL_INTERVAL_S,
    PAUSE_UNTIL,
    LASER_HOLD_S,
    run_reader_rs485,
    IDLE_WAIT_S,
    STRIP_STATE_MIN_S,
    MIN_BETWEEN_TURNS_S,
)

# the names these modules had before the split
_rs_discover = rs_discover
_color_for = color_for
_PI_BY_E = PI_BY_E
_send_batch = send_batch
_paint = paint_block
_TEXT = TEXT_OF
_state_cfg = state_cfg
_sanitize = sanitize
_declared = DECLARED
_e_declared = e_declared
_paint_segments = paint_segments
_POWER = POWER
_paint_segment_list = paint_segment_list
_pub_strip = PUB_STRIP
_send_led_strip = send_led_strip
_hex = hex_color
_in_live = is_live
_boards_views = BOARDS_VIEWS
_num = num
_on = is_on
_NETWORK = COLOR_NETWORK
_GREEN = COLOR_GREEN
_BLUE = COLOR_BLUE
_AMBER = COLOR_AMBER
_HEX_SHUTDOWN = HEX_SHUTDOWN
_sec = sec_entry
_hexc = hex_of_color
_effect_end_job = effect_end_job
_WithoutM150 = WithoutM150
_COUNTER = COUNTER
_COUNTER_TS = COUNTER_TS
_COUNTER_LOCK = COUNTER_LOCK
_Counter = CountedBridge
_state_test = state_test
_rs_values = rs_values
_run_reader_rs485 = run_reader_rs485


# ---------------------------------------------------------------------------
# What touches the rest of the service (the other features, DSF, threads): the layers above know none of it
# ---------------------------------------------------------------------------
def _jog_free_active():
    try:
        import jog_move

        return jog_move.free_active()
    except Exception:
        return False


def _jog_free_color():
    try:
        import jog_move

        return jog_move.free_color()
    except Exception:
        return None


def _jog_alert_limits():
    try:
        import jog_move

        return jog_move.alert_limits()
    except Exception:
        return False


def _guard_degraded():
    """True while a protection is down or the guard stopped ticking (protection_guard.degraded)."""
    try:
        import protection_guard
        return protection_guard.degraded()
    except Exception:
        return False


lights_loop.PROBES.update(jog_free_active=_jog_free_active, jog_free_color=_jog_free_color,
                          jog_alert_limits=_jog_alert_limits, guard_degraded=_guard_degraded)


class ReaderRs485(lights_loop.ReaderRs485):
    def _read_one_shot(self):
        import machine_state
        count("reads")
        return {"plugins": machine_state.read_plugins(max_age=4.0)}


class Painter(lights_loop.Painter):
    # -- one-off, counted: tells daemon.g that the Pi paints (strip only) --
    def _announce_real(self):
        import communication
        count("reads")
        if self.conn is None:
            self.conn = CommandConnection()
            self.conn.connect()
        # same own channel as Bridge.send (communication.py)
        self.conn.perform_simple_code('M98 P"0:/sys/workshop/macros/system/enable_pi_status.g"', channel=communication.channel_plugin())

    def _light_of_job(self, turn_on):
        """Same as lights_macros: the macros keep the colour and brightness."""
        macro = "lighton.g" if turn_on else "lightoff.g"
        real = self.bridge_real

        def _thread():
            try:
                real.send(f'M98 P"0:/macros/light/{macro}"')
                real.set_status("lightOn", bool(turn_on))
            except Exception:
                pass

        threading.Thread(target=_thread, daemon=True).start()


def run_loop(bridge_real, config):
    """Event driven: wakes up when the shared model changes (state_machine.
    on_change) and, only while an animation needs frames, on a short timer.
    Reads nothing from DSF itself."""
    import machine_state

    event = threading.Event()
    rs = ReaderRs485()
    threading.Thread(target=run_reader_rs485, args=(rs,), daemon=True, name="lights-rs485").start()
    painter = Painter(bridge_real, config, rs)

    def _change(patch, full):
        if full:
            painter.reconnected = True
        event.set()

    machine_state.on_change(_change)
    loop = lights_loop.LightsLoop(painter, event, machine_state.get_status, lambda: service_modules.is_active(service_modules.LIGHTS))
    while True:
        loop.step()


# name -> the module that owns it, for what is assigned from outside after import
_OWNERS = (lights_counters, lights_decide, lights_board, lights_frame, lights_output, lights_loop)


class _Facade(types.ModuleType):
    def __setattr__(self, name, value):
        for owner in _OWNERS:
            if name in owner.__dict__:
                setattr(owner, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Facade
