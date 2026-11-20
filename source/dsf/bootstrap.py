"""Starts the service: runs the start-up steps IN THE ORDER main.py always ran them (plan phase 3a).

main.py keeps the pieces that are its own (the G-code interceptor, the laser guard, the shutdown hooks) and hands them over in a
Wiring; start() runs the sequence and ends in the interceptor loop, which never returns. Every module is loaded through `load`
(importlib.import_module by default) at the moment its step runs, as the inline imports did; a test passes a loader of doubles and
runs the whole sequence without DSF.
"""
import importlib
import json
import os
import signal
import time
from dataclasses import dataclass
from typing import Any, Callable

import access_rev
import activity
import audit_alarms
import heartbeats
import messages
import process_registry
from messages import M

spawn = process_registry.spawn


@dataclass
class Wiring:
    """What main.py provides (its own functions and objects)."""
    bridge: Any                         # main.Bridge facade over the ServiceContext
    processes: Any                      # rows (id, title, detail, expected_s) for the "Workshop services" page
    handlers_dir: str
    log_path: str
    protect_data: Callable[[], None]
    watchdog_lock: Callable[[], None]
    laser_guard_loop: Callable[[], None]
    intercept_wd: Any                   # intercept_watchdog.InterceptWatchdog (has .run(beat=))
    excepthook: Callable[[Any], None]
    handle_shutdown: Callable[[int, Any], None]
    clean_stop: Callable[[str], None]
    intercept_loop: Callable[[], None]
    api: Any = None                     # set by start_api


def _manifest_version(ctx):
    """Version of the installed manifest (<plugins folder>/<Id>.json) or of the repository one."""
    base = ctx.base_dir
    for path in (os.path.join(os.path.dirname(os.path.dirname(base)), ctx.plugin_id + ".json"),
                 os.path.join(os.path.dirname(base), "plugin.json")):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("version", "")
        except Exception:
            continue
    return ""


def start_core_threads(ctx, w, load):
    ctx.publisher.start("publisher", beat=lambda: heartbeats.ok("publisher"))  # the only thread that calls set_plugin_data
    os.makedirs(w.handlers_dir, exist_ok=True)
    spawn(w.watchdog_lock, name="watchdog_lock")
    spawn(w.laser_guard_loop, name="guardian_laser")
    spawn(w.intercept_wd.run, kwargs={"beat": lambda: heartbeats.ok("intercept_watchdog")}, name="intercept_watchdog")
    ctx.log_file("WorkshopService starting...")
    process_registry.set_excepthook(w.excepthook)


def _try(ctx, what, fn):
    try:
        fn()
    except Exception as e:
        ctx.log_file(f"{what}: {e}")


def prepare_storage(ctx, w, load):
    """Database, protected files and the files that follow the settings stores."""
    ctx.db.init_db()
    w.protect_data()
    # daily database backups and maintenance (db_backup.py, API db.*)
    load("db_backup").launch(ctx.config, w.bridge, ctx.log_file)

    def laser_correction_sync():
        # the macro the zones read (macros/lasercorrection.g) follows the settings store "laser": written again at start
        if load("laser_correction").sync():
            ctx.log_file("macros/lasercorrection.g written from the settings store laser")
    _try(ctx, "could not write macros/lasercorrection.g", laser_correction_sync)

    def focus_sync():
        # focus.g (the geometry focusrule.g loads) is created when missing, never replaced behind the owner's back
        state = load("focus_geometry").sync_at_start()
        if state == "written":
            ctx.log_file("config/focus.g written from the settings store focus")
        elif state == "differs":
            ctx.log_file("config/focus.g differs from the settings store focus: left as it is (saving the store rewrites it)")
    _try(ctx, "could not check config/focus.g", focus_sync)

    # retention of sys/workshop/zones/history: once at start and then daily, never the newest of a zone
    _try(ctx, "could not start the zones/history retention",
         lambda: load("zones_history").launch(lambda: ctx.config, ctx.log_file))

    def bed_zones_sync():
        # bedzones.g (the settings bedzones-set.g loads when the service is stopped) follows the store "bed-zones"
        if load("bed_zones_mirror").sync_at_start() == "written":
            ctx.log_file("config/bedzones.g written from the settings store bed-zones")
    _try(ctx, "could not check config/bedzones.g", bed_zones_sync)

    def apply_laser_correction():
        # the board's memory takes the stored correction (wpload.g) once it answers and is free; it never waits the start of the service
        try:
            applied, why = load("laser_correction").apply_at_start()
            ctx.log_file("laser correction applied to the board's zones" if applied else f"laser correction not applied at start: {why}")
        except Exception as e:
            ctx.log_file(f"could not apply the laser correction at start: {e}")
    spawn(apply_laser_correction, name="laser-correction-apply")


def start_api(ctx, w, load):
    """The registry of the API first; the endpoint and the macro mailbox come once the threads are running. Returns the api."""
    api_ops = load("api_ops")
    load("workshop_api")
    api = api_ops.init(w.bridge, ctx.config, ctx.plugin_id, _manifest_version(ctx), log=ctx.log, log_file=ctx.log_file)
    # the alarms of the activity record (audit_alarms.py) go out as an Activity event + phone notice, type security_alarm
    audit_alarms.sink = lambda key, params: activity.log_event(w.bridge, audit_alarms.EVENT_TYPE, M(key, **params))
    try:
        api_ops.last.extend(ctx.db.commands_last(api_ops.LAST_MAX))  # survive a restart
    except Exception as e:
        ctx.log_file(f"could not load the command history: {e}")
    signal.signal(signal.SIGTERM, w.handle_shutdown)
    # op service.restart; ends with os._exit(1) like the watchdog
    load("service_restart").configure(cleanup=lambda: w.clean_stop("service restart"), log=ctx.log_file)
    return api


def register_processes(w):
    for row in w.processes:
        heartbeats.register(*row)
    heartbeats.ok("interceptor")
    heartbeats.mark_live("interceptor")


def start_machine_state(ctx, w, load):
    """ONE subscription to DSF that all threads read (machine_state.get_status / read_in / on_change). First of all."""
    load("machine_state")
    service_modules = load("service_modules")

    def subscription_low_demand():
        # opens only when some process that reads it can run (service_modules.py)
        while not service_modules.process("subscription"):
            time.sleep(3)
        load("machine_state").launch()
        messages.follow_machine_language()  # texts made without a request use DWC's language (global.workshopLanguage)
    spawn(subscription_low_demand, name="subscription-demand")


def start_communication(ctx, w, load):
    """Channel of the own codes and of the jog BEFORE starting the threads that send G-code."""
    communication = load("communication")
    try:
        communication.update(ctx.config)
    except Exception as e:
        ctx.log_file(f"communication: could not check the channels ({e}); SBC is used")

    def communication_loop():
        # checked again every 10 s (config.g can change: a new PanelDue; and SBC goes from free to shared when the bridge connects)
        while True:
            try:
                communication.emit(w.bridge, ctx.config)
            except Exception as e:
                ctx.log_file(f"communication: {e}")
            try:
                heartbeats.ok("communication")
            except Exception:
                pass
            time.sleep(10)
    spawn(communication_loop, name="communication")


def _launch_phase(ctx, w, load, phase, before=None):
    """The supervised processes of one phase, as the table of process_registry.py lists them (module, function, arguments, order)."""
    values = {"bridge": w.bridge, "config": ctx.config, "log_file": ctx.log_file}
    process_registry.launch_phase(phase, heartbeats.launch, load, values, before)


def launch_pollers(ctx, w, load):
    # the jog's own log file is set just before it is launched
    _launch_phase(ctx, w, load, process_registry.POLLERS, before={"jog": lambda: load("jog_move").set_log_file(w.log_path)})


def start_notices_and_live_job(ctx, w, load):
    b, c = w.bridge, ctx.config
    load("notifier").init(b, c)  # phone notifications of events (config on the Activity page)
    # black box: one line every 5 s on the SD; after notifier.init (it sends the notice)
    load("black_box").launch(b, c, ctx.log_file, {"bridge": b.lock, "api": w.api.lock})
    # live job: a job left open from before the restart is closed at its last activity, unless the machine is still in it
    machine_state, live_job = load("machine_state"), load("live_job")
    try:
        try:
            st0 = machine_state.get_status(timeout=3)
        except Exception:
            st0 = None
        r = live_job.on_start(b, c, st0)
        if r != "none":
            ctx.log_file(f"job open from before the restart: {r}")
    except Exception as e:
        live_job._mem["ready"] = True  # so that the monitoring works the same
        ctx.log_file(f"job_live at startup: {e}")


def launch_late(ctx, w, load):
    _launch_phase(ctx, w, load, process_registry.LATE)
    spawn(heartbeats.publish_loop, args=(w.bridge,))
    _launch_phase(ctx, w, load, process_registry.FINAL)  # the single owner of the movement, then the protection guard


def announce(ctx, w, load):
    """serviceStarted and the first activity event."""
    b = w.bridge
    b.set_status("serviceStarted", time.strftime("%Y-%m-%d %H:%M:%S"))
    access_rev.listen(lambda n: b.set_status("accessRev", n))  # only the integer: a page that sees it change asks auth.whoami again
    # "system" = the Raspberry Pi really booted; a service restart goes as "service" so as not to clutter the activity
    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
    except Exception:
        uptime_s = None
    if uptime_s is not None and uptime_s < 300:
        activity.log_event(b, "system", M("system_powered_on", seconds=int(uptime_s)))
    else:
        activity.log_event(b, "service", M("service_restarted"))


def start(ctx, w, load=None):
    """The whole start-up, in the order main.py ran it; ends in the interceptor loop (it never returns)."""
    load = load or importlib.import_module
    start_core_threads(ctx, w, load)
    prepare_storage(ctx, w, load)
    w.api = start_api(ctx, w, load)
    register_processes(w)
    start_machine_state(ctx, w, load)
    start_communication(ctx, w, load)
    load("extra_commands").launch(ctx.log_file)  # commands from other plugins (WorkshopRS485) to the "Received commands" history
    launch_pollers(ctx, w, load)
    start_notices_and_live_job(ctx, w, load)
    launch_late(ctx, w, load)
    spawn(load("machine_try").recover_pending, name="machine-try-recover")  # Machine v2: a volatile M208 trial left pending is put back
    # API: POST/GET /machine/<Id>/api (pages, programs) and the global variable mailbox of the macros (service-call.g)
    load("workshop_api").serve(w.api, ctx.plugin_id, "api", load("api_ops").http_info)
    load("api_macros").start(w.api, w.bridge, ctx.log_file)
    announce(ctx, w, load)
    w.intercept_loop()
