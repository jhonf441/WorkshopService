#!/usr/bin/env python3
"""
WorkshopService - DSF plugin backend.

Intercepts M3/M4/M5 (laser on/off) to control the air-assist pump on
OUT2. Pages, macros and programs call the service through its API:
POST /machine/<Id>/api with named
operations (workshop_api.py, api_ops.py; macros through global variables,
api_macros.py). The files in handlers/ are the internal implementation.

It also paints the status LEDs (see status_light.py) on its own, without
waiting for the sys/daemon.g polling in the firmware -- see that file for
the details.

It must never exit because of transient connection errors -- DCS restarts it
by itself if it dies (sbcAutoRestart=true in plugin.json), but it still
retries the connection internally so as not to depend on that.

"""
import paths
import importlib.util
import json
import os
import signal
import sys
import threading
import time

from dsf.connections import CommandConnection, InterceptConnection
from dsf.connections import InterceptionMode
from dsf.commands.code_channel import CodeChannel
from dsf.object_model.messages import MessageType

import activity
import db
import live_job  # live job opened with job.start (closing and cut of the duration)
import heartbeats
import laser_guard  # a laser power left set (M3 / M4 without M5) is turned off
import ipc_stats  # IPC calls to DCS per minute (servicesInternal.ipc, black box ipc=)
import publisher  # set_plugin_data only on change and rate limited
import messages
from messages import M, J, B

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# The Id is the name of the plugin folder (/opt/dsf/plugins/<Id>/dsf): it works
# (WorkshopService) without touching anything.
PLUGIN_ID = os.path.basename(os.path.dirname(BASE_DIR))
if PLUGIN_ID in ("", "dsf", "src") or not PLUGIN_ID[0].isalpha():
    PLUGIN_ID = "WorkshopService"
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
HANDLERS_DIR = os.path.join(BASE_DIR, "handlers")

# Only standard codes: M3/M4/M5 for the automatic air assist and the activity of
# the live job.
FILTERS = ["M3", "M4", "M5"]


def param_value(p):
    """CodeParameter does not expose a generic .value: its type has to be requested."""
    if p.is_string:
        return p.string_value
    try:
        return p.as_float()
    except Exception:
        return p.string_value


LOG_FILE = os.path.join(BASE_DIR, "workshop-service.log")


def log(msg):
    """Really actionable errors/warnings -- this is redirected to DWC as a
    pop-up notification (sbcOutputRedirected=true), so it has to be used with
    care: connections that retry in a loop or routine events go to log_file()
    instead, so as not to flood the user with piling-up pop-ups (see log_file)."""
    if isinstance(msg, messages.Msg):  # also a message made at import time: in the machine's language (DWC's)
        msg = msg.text(messages.current_language())
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", flush=True)


def log_file(msg):
    """Routine diagnostics (connections, retries, startup/shutdown housekeeping)
    -- only to the local file, never to DWC. Check with
    `ssh ... tail -f workshop-service.log` when debugging is needed."""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# True if service.json exists but could not be read: it is not saved over (see load_config)
_config_blocked = [False]


def load_config():
    # Settings in 0:/sys/workshop/config/service.json and separate keys in
    # /opt/dsf/conf (config_store.py); on a new installation, config.example.json.
    import config_store

    cfg = config_store.load_data()
    if cfg is not None:
        return cfg
    example = os.path.join(BASE_DIR, "config.example.json")
    # service.json exists but could not be read (nor its .bak): it is NOT overwritten with the
    # factory ones
    # (updating the plugin does not delete it; it can be recovered by hand or from a backup)
    write_out = not os.path.exists(config_store.SETTINGS_FILE)
    if not write_out:
        _config_blocked[0] = True
        log(M("main_settings_unreadable_factory_values_not_saved", file=config_store.SETTINGS_FILE))
    try:
        with open(example) as f:
            cfg = json.load(f)
        if write_out:
            save_config(cfg)
            log(M("main_configuration_created_from_example"))
        return cfg
    except Exception as e:
        log(M("main_could_not_read_configuration_nor_example", e=e))
        return {
            "air_assist": {"gpout_index": 7, "off_delay_s": 2, "auto_enabled": False},
        }


def save_config(cfg):
    # tmp + fsync + rename and the previous version in .bak (power cut), in both files
    import config_store

    if _config_blocked[0]:
        log(M("main_configuration_not_saved_service_json_unreadable"))
        return
    config_store.save(cfg)


def protect_data():
    """config.json and the database (+ -wal/-shm/-journal) readable only by dsf. The
    database has lived on the DSF SD since 2026-10-10 (db.DB_FILE)."""
    import config_store

    # the fallback secrets.json next to the code is only the store when /opt/dsf/conf cannot be written; otherwise a leftover of it (made by
    # hand as another user) is not ours to chmod and is not used: it must not log an error at every start
    files = [config_store.SECRETS_FILE]
    if config_store._secrets_path() == config_store.SECRETS_BACKUP:
        files.append(config_store.SECRETS_BACKUP)
    files += [db.DB_FILE, db.DB_FILE + "-wal", db.DB_FILE + "-shm", db.DB_FILE + "-journal"]
    for f in files:
        try:
            if os.path.exists(f):
                os.chmod(f, 0o600)
        except OSError as e:
            log(M("main_could_not_protect_file", file=os.path.basename(f), e=e))


# RRF channel for the plugin's OWN codes (LEDs, driver reads, set global,
# light/air macros...). 2026-10-08: with the default channel (SBC) they shared
# a queue with the G-code bridge -- while the Start GCode ran a long macro
# (M98 mdf3mm.g: probing and focus, several seconds) everything of the plugin
# waited behind it and gave "Timeout while waiting for JSON response". Nothing
# uses Aux2 on this machine (the PanelDue, if ever connected, goes through
# Aux). Tested: it answers the same (echo, read-only M569) in ~60 ms.
# 2026-10-10: it is no longer fixed; it is chosen on the page (Communication
# with the Duet) and communication.py resolves it ("auto" = Aux2 if free, as
# before).
import communication


class Bridge:
    """Wraps the auxiliary CommandConnection (outgoing G-code + shared state)
    with a lock, because the air-assist timer uses it from another thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.conn = None
        self.payload = {}
        self.publicador = publisher.Publisher(publisher.instrument(self._send_datum), log=log_file)

    def _ensure_connected(self):
        while self.conn is None:
            try:
                conn = CommandConnection()
                conn.connect()
                self.conn = conn
                log_file("auxiliary CommandConnection connected")
            except Exception as e:
                log_file(f"Could not connect CommandConnection ({e}), retrying in 5s")
                time.sleep(5)

    def send(self, gcode):
        # who asked (module of the caller) for the IPC counter (ipc_stats.py)
        try:
            who = sys._getframe(1).f_globals.get("__name__", "?")
        except Exception:
            who = "?"
        with self.lock:
            self._ensure_connected()
            try:
                return ipc_stats.call("code", who, self.conn.perform_simple_code, gcode, channel=communication.channel_plugin())
            except Exception as e:
                log(M("main_error_sending_code_reconnecting", code=_mask(gcode), e=e))
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                raise

    def set_status(self, key, value, **options):
        """Publish plugin data. The value is visible to the readers inside the
        service at once (self.datos); the IPC call is made by the publisher
        thread only when it changed and at most at the rate of its key
        (publisher.py). opciones: min_interval, volatile, keepalive_s."""
        self.payload[key] = value
        # every message goes out as {"key", "params"}: each page shows it in the language of its own DWC
        self.publicador.set(key, messages.data(value), **options)

    def _send_datum(self, key, value):
        with self.lock:
            self._ensure_connected()
            try:
                self.conn.set_plugin_data(PLUGIN_ID, key, value)
            except Exception as e:
                log_file(f"Error updating state '{key}' ({e})")
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                raise

    def save_config(self):
        save_config(config)


bridge = Bridge()

config = load_config()
import service_modules
service_modules.set_settings(config.setdefault("modules", {}))  # which internal processes run (service_modules.py)
# the G-code interceptor only has a job while the automatic air is on (or the user forced it on)
service_modules.set_rule("interceptor", lambda: config["air_assist"].get("auto_enabled", True))

_air_assist_timer = None


def _air_assist_on_now():
    gpout = config["air_assist"]["gpout_index"]
    bridge.send(f'M42 P{gpout} S1')
    bridge.set_status("airAssist", True)


def air_assist_on():
    global _air_assist_timer
    if _air_assist_timer is not None:
        _air_assist_timer.cancel()
        _air_assist_timer = None
    # The M42 is not sent directly here: this runs inside the callback that
    # handles the intercepted M3/M4, and sending another code to RRF at that very
    # instant (over the same channel) can end up waiting for the M3/M4 itself to
    # finish resolving -- a self-deadlock. It is fired in a separate thread so
    # that ignore_code() can release the channel first.
    threading.Thread(target=_air_assist_on_now, daemon=True).start()


def air_assist_off_now():
    gpout = config["air_assist"]["gpout_index"]
    bridge.send(f'M42 P{gpout} S0')
    bridge.set_status("airAssist", False)


def air_assist_off_delayed():
    global _air_assist_timer
    if _air_assist_timer is not None:
        _air_assist_timer.cancel()
    delay = config["air_assist"].get("off_delay_s", 2)
    _air_assist_timer = threading.Timer(delay, air_assist_off_now)
    _air_assist_timer.daemon = True
    _air_assist_timer.start()


def _mask(raw_text):
    """Hides secrets of a G-code before logging it (DWC password of M551)."""
    import re
    return re.sub(r'\bM551(\s+)P"[^"]*"', r'M551\1P"***"', raw_text, flags=re.I)


# Interception connection and code in progress, to release them on shutdown
# (see _release_interception).
_interception = {"conn": None, "code": None}


def _release_interception():
    """2026-10-09: if the plugin stops with an unresolved intercepted code (or one
    that DCS already sent and we have not read yet), DCS 3.6 leaves it waiting
    FOREVER and the whole channel jams behind it (we saw HTTP with 'Executing
    the API (lights) (10 more codes pending)' in M122 "DSF"; DWC buttons stuck
    in "sending" until duetcontrolserver was restarted). Before exiting:
    answer the one in progress, return (ignore) the ones already in the socket,
    and close the connection."""
    conn = _interception["conn"]
    if conn is None:
        return
    try:
        if _interception["code"] is not None:
            conn.resolve_code(MessageType.Error, M("main_workshopservice_restarting_try_again_few_seconds"))
            _interception["code"] = None
    except Exception as e:
        log_file(f"shutdown: could not answer the code in progress: {e}")
    try:
        conn.socket.settimeout(0.3)
        for _ in range(20):
            conn.receive_code()
            conn.ignore_code()
            log_file("shutdown: pending code handed back to RRF unprocessed")
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass
    _interception["conn"] = None


def _release_if_missing(conn):
    """The interceptor was turned off (automatic air off, or forced off): hand the connection back."""
    if conn is not None:
        _release_interception()
        log_file("InterceptConnection released: nobody needs the interception")
    bridge.set_status("connected", True)  # the service itself keeps running; only the interception rests


import intercept_watchdog
# a code that stays in progress longer than intercept_watchdog.LIMIT_S frees the channel and restarts the service (DSF revives it)
_intercept_wd = intercept_watchdog.InterceptWatchdog(_release_interception, lambda: os._exit(1), log=log_file)


def intercept_loop():
    conn = None
    resting = False
    while True:
        if not service_modules.process("interceptor"):
            if not resting:
                _release_if_missing(conn)
                conn = None
                resting = True
                heartbeats._info["interceptor"]["idle"] = True
                heartbeats._info["interceptor"]["detail"] = "At rest: the automatic air is off"
            heartbeats.ok("interceptor")
            time.sleep(3)
            continue
        if resting:
            resting = False
            heartbeats._info["interceptor"]["idle"] = False
            heartbeats._info["interceptor"]["detail"] = ""
        if conn is None:
            try:
                conn = InterceptConnection(InterceptionMode.PRE, filters=FILTERS, timeout=3)
                conn.connect()
                _interception["conn"] = conn
                log_file("InterceptConnection connected (Pre, filters: " + ", ".join(FILTERS) + ")")
                bridge.set_status("connected", True)
                bridge.set_status("airAssistAuto", config["air_assist"].get("auto_enabled", True))
                bridge.set_status("airAssistDelay", config["air_assist"].get("off_delay_s", 2))
            except Exception as e:
                log_file(f"Could not connect InterceptConnection ({e}), retrying in 5s")
                time.sleep(5)
                continue

        try:
            code = conn.receive_code()
            _interception["code"] = code
            heartbeats.ok("interceptor")
        except TimeoutError:
            heartbeats.ok("interceptor")
            continue
        except Exception as e:
            log_file(f"InterceptConnection lost ({e}), reconnecting...")
            heartbeats.error("interceptor", e)
            bridge.set_status("connected", False)
            try:
                conn.close()
            except Exception:
                pass
            conn = None
            continue

        key = f"{code.type.value if hasattr(code.type, 'value') else code.type}{code.majorNumber}"
        bridge.set_status("lastCode", key)
        bridge.set_status("lastCodeTime", time.strftime("%Y-%m-%dT%H:%M:%S"))

        _intercept_wd.begin(key)
        try:
            if key in ("M3", "M4", "M5"):
                laser_guard.note(key, time.monotonic())
                live_job.mark_activity()  # real order of the job (cut of the duration)
                try:
                    import jog_move
                    jog_move.mark_bridge_si(code)  # the jog does not move with the bridge active
                except Exception:
                    pass
            if key in ("M3", "M4"):
                if config["air_assist"].get("auto_enabled", True):
                    air_assist_on()
                conn.ignore_code()
            elif key == "M5":
                if config["air_assist"].get("auto_enabled", True):
                    air_assist_off_delayed()
                conn.ignore_code()
            else:
                conn.ignore_code()
        except Exception as e:
            log(M("main_error_processing", key=key, e=e))
            try:
                conn.resolve_code(MessageType.Error, str(M("main_internal_error", e=e)))  # the firmware console takes one plain text, in DWC's language (messages.machine_language)
            except Exception:
                pass
        _interception["code"] = None
        _intercept_wd.end()


def _laser_guard_loop():
    """Every second: if a laser power was left set and nothing is working, sends the M5 (laser_guard.py explains when)."""
    import machine_state
    import jog_move
    while True:
        time.sleep(1.0)
        try:
            if machine_state.read_in("state.machineMode") != "Laser":
                continue
            now = time.monotonic()
            quiet = jog_move.bridge_activity_does_s()
            pwm = machine_state.read_in("state.laserPwm")
            if (quiet is not None and quiet < laser_guard.BRIDGE_QUIET_S) or (isinstance(pwm, (int, float)) and pwm > 0):
                laser_guard.arm(now)  # the bridge is working, or the laser has power: the final M5 may never arrive
            if not laser_guard.armed():
                continue
            status = machine_state.read_in("state.status")
            live = live_job.read_in() is not None
            if laser_guard.decide(time.monotonic(), status, live, quiet):
                log_file("laser power was left set with nothing working: sending M5")
                try:
                    bridge.send("M5")
                except Exception:
                    laser_guard.rearm()  # try again at the next check
                    raise
            heartbeats.ok("guardian_laser")
        except Exception as e:
            log_file(f"laser guard: {type(e).__name__}: {e}")
            time.sleep(4)


def _handle_shutdown(signum, frame):
    # DCS sends SIGTERM when stopping the plugin on purpose (stop_plugin or when
    # shutting down DSF) -- different from a crash, where sbcAutoRestart revives
    # it in seconds. Without this, the status LEDs would stay frozen: neither the
    # Pi (which no longer runs) nor daemon.g (which still thinks the Pi has
    # control) would paint them.
    log_file(f"signal {signum} received, handing the status control back to daemon.g...")
    try:
        import black_box
        black_box.shut(f"signal {signum}")  # service restart = clean shutdown
    except Exception:
        pass
    # first release the interception: a hung code jams the RRF channel
    _release_interception()
    try:
        # Reuses the bridge connection already established -- opening a NEW
        # connection right here fails, because DCS is already closing the plugin's
        # environment at this moment.
        bridge.send('M98 P"0:/sys/workshop/macros/disable_pi_status.g"')
    except Exception as e:
        log_file(f"could not tell daemon.g before exiting: {e}")
    sys.exit(0)


def _excepthook_thread(args):
    """Uncaught error in a thread: the full traceback goes to the local log and
    to DWC (and to Activity) ONE line arrives, not ~20 (2026-10-09)."""
    import traceback
    if args.exc_type is SystemExit:
        return
    label = args.thread.name if args.thread else "?"
    log_file(f"uncaught error in thread {label}:\n" + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    log(M("main_error_in_thread", label=label, type=args.exc_type.__name__, value=args.exc_value))


def _watchdog_lock():
    """Diagnostics (2026-10-09): if the bridge lock stays taken for more than
    20 s, everything that publishes state hangs (the interceptor needs it to
    publish state) and the RRF queue stays "busy". It writes the stack of each
    thread to the log file (never to stdout: if stdout is what got stuck, a
    print here would hang too)."""
    import sys
    import traceback
    consecutive, dump = 0, False
    while True:
        time.sleep(5)
        if bridge.lock.locked():
            consecutive += 1
        else:
            consecutive, dump = 0, False
        request = paths.SYS + "/workshop-stacks.request"
        a_request = os.path.exists(request)
        if a_request:
            try:
                os.remove(request)
            except Exception:
                pass
        if a_request or (consecutive >= 4 and not dump):
            dump = dump or not a_request
            names = {t.ident: t.name for t in threading.enumerate()}
            parts = ["BRIDGE LOCK HELD >20 s, thread stacks:"]
            for ident, frame in sys._current_frames().items():
                parts.append(f"--- thread {names.get(ident, ident)}")
                parts.append("".join(traceback.format_stack(frame)[-6:]))
            log_file("\n".join(parts))


if __name__ == "__main__":

    bridge.publicador.start("publisher")  # the only thread that calls set_plugin_data
    os.makedirs(HANDLERS_DIR, exist_ok=True)
    threading.Thread(target=_watchdog_lock, name="watchdog_lock", daemon=True).start()
    threading.Thread(target=_laser_guard_loop, name="guardian_laser", daemon=True).start()
    threading.Thread(target=_intercept_wd.run, name="intercept_watchdog", daemon=True).start()
    log_file("WorkshopService starting...")
    threading.excepthook = _excepthook_thread

    db.init_db()
    protect_data()
    # daily database backups and maintenance (db_backup.py, API db.*)
    import db_backup
    db_backup.launch(config, bridge, log_file)
    # API of the service (workshop_api.py / api_ops.py): the registry first, the
    # endpoint and the macro mailbox once the threads below are running
    import api_ops
    import workshop_api

    _manifest_version = ""
    # installed manifest (/opt/dsf/plugins/<Id>.json) or the repository one
    for _mf in (os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), PLUGIN_ID + ".json"),
                os.path.join(os.path.dirname(BASE_DIR), "plugin.json")):
        try:
            with open(_mf, encoding="utf-8") as _f:
                _manifest_version = json.load(_f).get("version", "")
            break
        except Exception:
            continue
    api = api_ops.init(bridge, config, PLUGIN_ID, _manifest_version, log=log, log_file=log_file)
    try:
        api_ops.last.extend(db.commands_last(api_ops.LAST_MAX))  # survive a restart
    except Exception as e:
        log_file(f"could not load the command history: {e}")

    signal.signal(signal.SIGTERM, _handle_shutdown)

    # Internal processes: they start supervised (heartbeats.launch restarts them if
    # they die) and show on the "Workshop services" page.
    PROCESSES = [
        ("interceptor", M("main_g_code_interceptor"), M("main_handles_m3_m4_m5_automatic_air"), 15),
        ("status_light", M("main_status_lights"), M("main_paints_status_zone_led_strip_according"), 10),
        ("consumption", M("main_consumption_meter"), M("main_reads_tuya_meter_saves_history"), 60),
        ("jobs", M("main_jobs_and_zones"), M("main_detects_job_start_end_mode_zone_changes"), 30),
        ("motors", M("main_motors"), M("main_reads_drivers_currents_speeds_motors_page"), 60),
        ("jog", "Jog", M("main_moves_machine_while_jog_button_held"), 10),
        ("pid_trace", M("main_pid_tuning_record"), M("main_records_temperature_power_while_heater_tuned_pid"), 30),
        ("maintenance", M("main_maintenance_counters"), M("main_counts_hours_distance_axes_maintenance_plan"), 30),
        ("events", M("main_rrf_events"), M("main_emergencies_pauses_firmware_errors_for_activity"), 30),
        ("trace", M("main_job_path"), M("main_records_job_path_only_while_someone_watches"), 60),
        ("health", M("main_system_health"), M("main_temperature_wifi_services_alerts_health_page"), 60),
        ("camera", M("main_camera_relay"), M("main_shares_camera_video_all_screens_camera"), 30),
        ("timer", M("main_scheduled_power_off"), M("main_counts_timer_power_off_control_bar"), 10),
        ("risk", M("main_active_risk"), M("main_warns_screens_leds_while_something_leaves"), 10),
        # 2026-10-11 (WorkshopConfig, T3.4): configuration rollback
        ("config_guard", M("main_configuration_rollback"), M("main_after_saving_new_configuration_watches_board"), 15),
        # 2026-10-13: single owner of the movement (motion_owner.py)
        ("motion", M("main_movement_owner"), M("main_decides_whether_possible_move_change_geometry"), 10),
        # F1-C: alarm when a safety process dies or a protection is left unwatched (protection_guard.py)
        ("guard", M("main_protection_guard"), M("main_watches_that_safety_processes_beat_alarms_when"), 5),
    ]
    for _n, _t, _d, _e in PROCESSES:
        heartbeats.register(_n, _t, _d, _e)
    heartbeats.ok("interceptor")
    heartbeats._info["interceptor"]["live"] = True

    # Machine state: ONE subscription to DSF that all threads read
    # (machine_state.get_status / read_in / on_change). First of all.
    import machine_state
    # The single subscription starts only when some process that reads it can run (service_modules.py): with no plugin that
    # needs the machine state enabled it stays closed, and opens by itself when one is enabled.
    def _subscription_low_demand():
        while not service_modules.process("subscription"):
            time.sleep(3)
        machine_state.launch()
        messages.follow_machine_language()  # texts made without a request use DWC's language (global.workshopLanguage)

    threading.Thread(target=_subscription_low_demand, name="subscription-demand", daemon=True).start()

    # channel of the own codes and of the jog BEFORE starting the threads that send G-code
    try:
        communication.update(config)
    except Exception as e:
        log_file(f"communication: could not check the channels ({e}); SBC is used")

    def _communication_loop():
        # it is checked again every 10 s (config.g can change: a new PanelDue;
        # and SBC goes from free to shared when the bridge connects)
        while True:
            try:
                communication.emit(bridge, config)
            except Exception as e:
                log_file(f"communication: {e}")
            time.sleep(10)

    threading.Thread(target=_communication_loop, name="communication", daemon=True).start()

    # commands from other plugins (WorkshopRS485) to the "Received commands" history
    import extra_commands
    extra_commands.launch(log_file)

    import status_light
    heartbeats.launch("status_light", status_light.run_loop, bridge, config)

    import consumption_poller
    heartbeats.launch("consumption", consumption_poller.run_loop, bridge, config)

    import job_poller
    heartbeats.launch("jobs", job_poller.run_loop, bridge, config)

    import motor_poller
    heartbeats.launch("motors", motor_poller.run_loop, bridge, config)

    import machine_maint_poller
    heartbeats.launch("maintenance", machine_maint_poller.run_loop, bridge, config)

    import pid_trace
    heartbeats.launch("pid_trace", pid_trace.run_loop, bridge, config)

    import jog_move
    jog_move.set_log_file(LOG_FILE)
    heartbeats.launch("jog", jog_move.run_loop, bridge, config)

    # Phone notifications of events (config on the Activity page).
    import notifier
    notifier.init(bridge, config)

    # Black box (black_box.py): one line every 5 s on the SD; if the Pi was shut
    # down without a close, report + notice. After notifier.init (it sends the notice).
    import black_box
    black_box.launch(bridge, config, log_file, {"bridge": bridge.lock, "api": api.lock})

    # live job: if a job was left open from before the restart, it is closed at
    # its last activity (it does not keep adding hours or kWh), unless the
    # machine is still in that job (live_job.py, 2026-10-12).
    import machine_state
    try:
        try:
            _st0 = machine_state.get_status(timeout=3)
        except Exception:
            _st0 = None
        _r = live_job.on_start(bridge, config, _st0)
        if _r != "none":
            log_file(f"job open from before the restart: {_r}")
    except Exception as e:
        live_job._mem["ready"] = True  # so that the monitoring works the same
        log_file(f"job_live at startup: {e}")

    # Emergencies, pauses and live RRF errors/warnings.
    import event_watcher
    heartbeats.launch("events", event_watcher.run_loop, bridge, config)

    # Trajectory of the job in progress -> sys/workshop/data/trace.json (Zones > Job)
    import job_trace
    heartbeats.launch("trace", job_trace.run_loop, bridge, config)

    # Health of the Pi and of the services ("Pi health" page, WorkshopPiHealth)
    import health_poller
    heartbeats.launch("health", health_poller.run_loop, bridge, config)

    # Camera relay (formerly a separate systemd service managed with sudo).
    import camera_relay
    heartbeats.launch("camera", camera_relay.run_loop, bridge, config, log_file)

    import shutdown_timer
    heartbeats.launch("timer", shutdown_timer.run_loop, bridge, config)

    import risk_rules
    heartbeats.launch("risk", risk_rules.run_loop, bridge, config)

    # 2026-10-11 (WorkshopConfig, T3.4): watches the startup after an armed save (config_guard.py)
    import config_guard
    heartbeats.launch("config_guard", config_guard.run_loop, bridge, config)

    threading.Thread(target=heartbeats.publish_loop, args=(bridge,), daemon=True).start()

    # single owner of the movement: publishes data.motion when it changes
    import motion_owner
    heartbeats.launch("motion", motion_owner.run_loop, bridge, config)

    # protection guard: expected vs seen heartbeats of the safety processes (status_light, Vision, RS485...)
    import protection_guard
    heartbeats.launch("guard", protection_guard.run_loop, bridge, config)

    # Machine v2: a volatile M208 trial left pending by a restart is put back first (machine_try.py)
    import machine_try
    threading.Thread(target=machine_try.recover_pending, name="machine-try-recover", daemon=True).start()

    # API: POST/GET /machine/<Id>/api (pages, programs) and the global variable
    # mailbox of the macros (service-call.g)
    workshop_api.serve(api, PLUGIN_ID, "api", api_ops.http_info)
    import api_macros
    api_macros.start(api, bridge, log_file)

    bridge.set_status("serviceStarted", time.strftime("%Y-%m-%d %H:%M:%S"))

    # "system" = the Raspberry Pi really booted; a service restart
    # (deploys, DCS relaunching it) goes as "service" so as not to clutter the
    # activity (before, every restart was a "system" event: 87 in 2 days).
    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
    except Exception:
        uptime_s = None
    if uptime_s is not None and uptime_s < 300:
        activity.log_event(bridge, "system", M("system_powered_on", seconds=int(uptime_s)))
    else:
        activity.log_event(bridge, "service", M("service_restarted"))

    intercept_loop()
