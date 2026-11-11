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
import sys
import threading
import time

from dsf.connections import CommandConnection, InterceptConnection
from dsf.connections import InterceptionMode
from dsf.commands.code_channel import CodeChannel
from dsf.object_model.messages import MessageType

import access_usage  # last use of each capability by each person
import bootstrap
import db
import live_job  # live job opened with job.start (closing and cut of the duration)
import heartbeats
import laser_guard  # a laser power left set (M3 / M4 without M5) is turned off
import process_registry
import service_context
import service_log
import service_settings
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


LOG_FILE = paths.DATA_DIR + "/logs/workshop-service.log"  # rotated by service_log
service_log.configure(LOG_FILE)


def log(msg):
    """Really actionable errors/warnings -- this is redirected to DWC as a
    pop-up notification (sbcOutputRedirected=true), so it has to be used with
    care: connections that retry in a loop or routine events go to log_file()
    instead, so as not to flood the user with piling-up pop-ups (see log_file)."""
    if isinstance(msg, messages.Msg):  # also a message made at import time: in the machine's language (DWC's)
        msg = msg.text(messages.current_language())
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", flush=True)  # console/journal only (as before): not written to the file


def log_file(msg):
    """Routine diagnostics (connections, retries, startup/shutdown housekeeping)
    -- only to the local file, never to DWC. Check with
    `ssh ... tail -f workshop-service.log` when debugging is needed."""
    service_log.log(msg)


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
    """Facade over the ServiceContext (service_context.py): the same methods and attributes the modules have always used.
    The lock, the connection and the published payload live in the context."""

    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def lock(self):
        return self.ctx.lock

    @property
    def conn(self):
        return self.ctx.conn

    @conn.setter
    def conn(self, value):
        self.ctx.conn = value

    @property
    def payload(self):
        return self.ctx.payload

    @property
    def publicador(self):
        return self.ctx.publisher

    def _ensure_connected(self):
        self.ctx.ensure_connected()

    def send(self, gcode):
        # who asked (module of the caller) for the IPC counter (ipc_stats.py)
        try:
            who = sys._getframe(1).f_globals.get("__name__", "?")
        except Exception:
            who = "?"
        return self.ctx.send(gcode, who)

    def set_status(self, key, value, **options):
        """Publish plugin data (see ServiceContext.set_status). opciones: min_interval, volatile, keepalive_s."""
        self.ctx.set_status(key, value, **options)

    def _send_datum(self, key, value):
        self.ctx.send_datum(key, value)

    def save_config(self):
        self.ctx.save_config()


config = load_config()
ctx = service_context.ServiceContext(
    plugin_id=PLUGIN_ID, base_dir=BASE_DIR, config=config, settings=service_settings.ServiceSettings(config, save_config),
    log=log, log_file=log_file, connect=CommandConnection, db=db)
bridge = Bridge(ctx)

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


def _beat(label):
    """The heartbeat of a loop that must never die because of its own bookkeeping (laser guard, watchdogs): never raises."""
    try:
        heartbeats.ok(label)
    except Exception:
        pass


def _laser_guard_loop():
    """Every second: if a laser power was left set and nothing is working, sends the M5 (laser_guard.py explains when)."""
    import machine_state
    import jog_move
    while True:
        time.sleep(1.0)
        _beat("guardian_laser")  # every pass, also outside Laser mode; never raises (the guard must not die for this)
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
    _clean_stop(f"signal {signum}")
    sys.exit(0)


def _clean_stop(why):
    """The clean part of the shutdown (shared by SIGTERM above and the service.restart op, service_restart.py): it does NOT end the process."""
    try:
        import black_box
        black_box.shut(why)  # service restart = clean shutdown
    except Exception:
        pass
    # first release the interception: a hung code jams the RRF channel
    _release_interception()
    access_usage.flush_all()  # the last uses of the capabilities reach the file (never raises)
    try:
        import bed_zones_intercept
        bed_zones_intercept.release(log_file)
    except Exception:
        pass
    try:
        # Reuses the bridge connection already established -- opening a NEW
        # connection right here fails, because DCS is already closing the plugin's
        # environment at this moment.
        bridge.send('M98 P"0:/sys/workshop/macros/system/disable_pi_status.g"')
    except Exception as e:
        log_file(f"could not tell daemon.g before exiting: {e}")


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
        _beat("watchdog_lock")
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


# Internal processes shown on the "Workshop services" page: a view of the one table in process_registry.py
PROCESSES = process_registry.heartbeat_rows(M)


if __name__ == "__main__":
    bootstrap.start(ctx, bootstrap.Wiring(
        bridge=bridge, processes=PROCESSES, handlers_dir=HANDLERS_DIR, log_path=LOG_FILE, protect_data=protect_data,
        watchdog_lock=_watchdog_lock, laser_guard_loop=_laser_guard_loop, intercept_wd=_intercept_wd,
        excepthook=_excepthook_thread, handle_shutdown=_handle_shutdown, clean_stop=_clean_stop, intercept_loop=intercept_loop))
