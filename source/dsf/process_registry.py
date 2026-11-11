"""The ONE table of the service's internal processes, and where its threads are born (plan phase 3b: ARQUITECTO 2.3).

Before, the same processes were described in four places: main.PROCESSES (title, detail, expected pace), service_modules (which
plugins need each one, which are safety, which have their own rule), process_catalog (group, locked, pausable, live mode) and
protection_guard.WATCHES (what each one protects). They are now VIEWS of SPECS below, kept under their old names with the same values
(golden/processes.json pins what the "Workshop services" page publishes, byte for byte).

Pure data plus `launch_phase`, which resolves the "module:function" strings only when asked (so this module imports nothing and the
start-up order is read from the table, not from the order of some imports).
"""
import threading
from dataclasses import dataclass
from typing import Optional, Tuple


# Ids of the DWC plugins the processes may depend on (service_modules re-exports them)
LIGHTS = "WorkshopLights"  # "Lights and states" on screen
CAMERA = "WorkshopCamera"  # camera relay, timelapse and watchdog
POWER = "WorkshopPower"  # consumption meter reader
MOTORS = "WorkshopMotors"  # driver polling
VISION = "WorkshopVision"  # uses the camera relay
RS485 = "WorkshopRS485"  # servo alarm pause (own backend process)
WORKBENCH = "WorkshopWorkbench"  # its camera layer uses the relay
ACTIVITY = "WorkshopActivity"  # history, board events and phone notices
HEALTH = "WorkshopPiHealth"  # Pi watchdog
JOG = "WorkshopJog"  # jog engine
BAR = "WorkshopControlBar"  # shutdown with timer
CONFIGURATOR = "WorkshopConfig"  # configuration rollback
MACHINE = "WorkshopMachine"  # maintenance counters
PRINTING = "WorkshopPrinting"  # record of the PID tuning (pid_trace.py)

GROUPS = ("safety", "machine", "data", "support")
# start-up phases of the supervised processes, in the order main.py launched them
POLLERS, LATE, FINAL = "pollers", "late", "final"
PHASES = (POLLERS, LATE, FINAL)


@dataclass(frozen=True)
class ProcessSpec:
    id: str                                  # the heartbeat label
    group: str                               # "safety" | "machine" | "data" | "support" (how the page sorts it)
    title: Optional[str] = None              # key of the title message (i18n catalogs); None = registered elsewhere
    detail: Optional[str] = None             # key of the one line under the title
    expected_s: Optional[int] = None         # seconds between heartbeats; the page says "late" after 3x
    title_is_text: bool = False              # the title is plain text, not a key ("Jog")
    needs_plugins: Tuple[str, ...] = ()      # rests unless one of these DWC plugins is enabled (empty = does not rest with a plugin)
    never_gated: bool = False                # a SAFETY process of service_modules: runs in "auto" whatever the plugins
    own: bool = False                        # its rule in "auto" is a setting of the service itself (service_modules.set_rule)
    always_on: bool = False                  # no switch on the page although it is not a safety process
    mode_live: bool = False                  # its loop re-reads the mode on every pass
    pausable: bool = False                   # the page may pause / resume / restart it
    protects: Optional[str] = None           # what is lost when it dies (protection_guard.WATCHES); None = not watched
    watch_rank: int = 0                      # position among the watched processes
    view_rank: int = 0                       # position in the service_modules lists (PROCESSES / SAFETY)
    start: str = ""                          # "module:function" for heartbeats.launch; "" = started by hand in bootstrap / main
    args: Tuple[str, ...] = ()               # names of what the function receives: "bridge", "config", "log_file"
    phase: str = ""                          # POLLERS | LATE | FINAL
    rank: int = 0                            # launch order inside its phase

    @property
    def locked(self):
        return self.group == "safety" or self.always_on

    @property
    def rests_with_plugin(self):
        return bool(self.needs_plugins)


_BC = ("bridge", "config")
_BL = ("bridge", "log_file")
_BCL = ("bridge", "config", "log_file")

SPECS = (
    ProcessSpec("interceptor", "safety", "main_g_code_interceptor", "main_handles_m3_m4_m5_automatic_air", 15, own=True),
    ProcessSpec("status_light", "machine", "main_status_lights", "main_paints_status_zone_led_strip_according", 10,
                needs_plugins=(LIGHTS,), protects="lights", watch_rank=1, view_rank=1,
                start="status_light:run_loop", args=_BC, phase=POLLERS, rank=1),
    ProcessSpec("consumption", "data", "main_consumption_meter", "main_reads_tuya_meter_saves_history", 60,
                needs_plugins=(POWER,), pausable=True, view_rank=2,
                start="consumption_poller:run_loop", args=_BC, phase=POLLERS, rank=2),
    ProcessSpec("jobs", "data", "main_jobs_and_zones", "main_detects_job_start_end_mode_zone_changes", 30,
                never_gated=True, always_on=True, view_rank=2,
                start="job_poller:run_loop", args=_BC, phase=POLLERS, rank=3),
    ProcessSpec("motors", "data", "main_motors", "main_reads_drivers_currents_speeds_motors_page", 60,
                needs_plugins=(MOTORS,), pausable=True, view_rank=3,
                start="motor_poller:run_loop", args=_BC, phase=POLLERS, rank=4),
    ProcessSpec("jog", "machine", "Jog", "main_moves_machine_while_jog_button_held", 10, title_is_text=True,
                needs_plugins=(JOG, WORKBENCH, VISION), view_rank=6,
                start="jog_move:run_loop", args=_BC, phase=POLLERS, rank=10),
    ProcessSpec("bed_zones", "machine", "main_bed_zones", "main_splits_m140_m190_into_one_heater_per_bed_zone", 15,
                needs_plugins=(PRINTING,), mode_live=True, view_rank=10,
                start="bed_zones_intercept:run_loop", args=_BL, phase=POLLERS, rank=7),
    ProcessSpec("pellet_layers", "machine", "main_pellet_layers", "main_pellet_layers_detail", 15,
                needs_plugins=(PRINTING,), view_rank=11,
                start="pellet_layers_run:run_loop", args=_BC, phase=POLLERS, rank=8),
    ProcessSpec("gcodelib", "data", "main_gcodelib", "main_gcodelib_detail", 30,
                needs_plugins=(PRINTING,), view_rank=12,
                start="gcodelib_indexer:instance().run_loop", args=_BC, phase=POLLERS, rank=9),
    ProcessSpec("pid_trace", "data", "main_pid_tuning_record", "main_records_temperature_power_while_heater_tuned_pid", 30,
                needs_plugins=(PRINTING,), pausable=True, view_rank=9,
                start="pid_trace:run_loop", args=_BC, phase=POLLERS, rank=6),
    ProcessSpec("maintenance", "data", "main_maintenance_counters", "main_counts_hours_distance_axes_maintenance_plan", 30,
                needs_plugins=(MACHINE,), pausable=True, view_rank=8,
                start="machine_maint_poller:run_loop", args=_BC, phase=POLLERS, rank=5),
    ProcessSpec("events", "safety", "main_rrf_events", "main_emergencies_pauses_firmware_errors_for_activity", 30,
                never_gated=True, protects="events", watch_rank=3, view_rank=1,
                start="event_watcher:run_loop", args=_BC, phase=LATE, rank=1),
    ProcessSpec("trace", "data", "main_job_path", "main_records_job_path_only_while_someone_watches", 60,
                needs_plugins=(WORKBENCH,), pausable=True, view_rank=5,
                start="job_trace:run_loop", args=_BC, phase=LATE, rank=2),
    ProcessSpec("health", "safety", "main_system_health", "main_temperature_wifi_services_alerts_health_page", 60,
                never_gated=True, protects="health", watch_rank=6, view_rank=6,
                start="health_poller:run_loop", args=_BC, phase=LATE, rank=3),
    ProcessSpec("camera", "support", "main_camera_relay", "main_shares_camera_video_all_screens_camera", 30,
                needs_plugins=(CAMERA, VISION, WORKBENCH), protects="camera", watch_rank=2, view_rank=4,
                start="camera_relay:run_loop", args=_BCL, phase=LATE, rank=4),
    ProcessSpec("timer", "machine", "main_scheduled_power_off", "main_counts_timer_power_off_control_bar", 10,
                needs_plugins=(BAR,), view_rank=7,
                start="shutdown_timer:run_loop", args=_BC, phase=LATE, rank=5),
    ProcessSpec("risk", "safety", "main_active_risk", "main_warns_screens_leds_while_something_leaves", 10,
                never_gated=True, protects="risk", watch_rank=5, view_rank=3,
                start="risk_rules:run_loop", args=_BC, phase=LATE, rank=6),
    # 2026-10-11 (WorkshopConfig, T3.4): configuration rollback
    ProcessSpec("config_guard", "safety", "main_configuration_rollback", "main_after_saving_new_configuration_watches_board", 15,
                never_gated=True, view_rank=4,
                start="config_guard:run_loop", args=_BC, phase=LATE, rank=7),
    # 2026-10-13: single owner of the movement (motion_owner.py)
    ProcessSpec("motion", "safety", "main_movement_owner", "main_decides_whether_possible_move_change_geometry", 10,
                never_gated=True, protects="motion", watch_rank=4, view_rank=5,
                start="motion_owner:run_loop", args=_BC, phase=FINAL, rank=1),
    # F1-C: alarm when a safety process dies or a protection is left unwatched (protection_guard.py)
    ProcessSpec("guard", "safety", "main_protection_guard", "main_watches_that_safety_processes_beat_alarms_when", 5,
                never_gated=True, view_rank=7,
                start="protection_guard:run_loop", args=_BC, phase=FINAL, rank=2),
    # processes redesign (phase 1): threads that had no heartbeat (they tick from their own loop; late = 3x expected)
    ProcessSpec("guardian_laser", "safety", "main_laser_power_guard", "main_laser_power_guard_description", 1,
                protects="laser_off", watch_rank=7),
    ProcessSpec("intercept_watchdog", "safety", "main_interception_watchdog", "main_interception_watchdog_description", 1,
                protects="interception", watch_rank=8),
    ProcessSpec("watchdog_lock", "safety", "main_bridge_lock_watchdog", "main_bridge_lock_watchdog_description", 5),
    ProcessSpec("publisher", "support", "main_state_publisher", "main_state_publisher_description", 30, always_on=True),
    ProcessSpec("communication", "support", "main_code_channels", "main_code_channels_description", 10),
    # in the catalog and in the modes of the page, but registered with their own heartbeat texts elsewhere
    ProcessSpec("box_black", "data"),
    ProcessSpec("base_backup", "data"),
    ProcessSpec("commands_extra", "data", always_on=True),
    ProcessSpec("subscription", "support", always_on=True),
    ProcessSpec("api", "support", always_on=True),
    ProcessSpec("api_macros", "support", always_on=True),
)

BY_ID = {s.id: s for s in SPECS}


# ---- the old tables, as views ----

def heartbeat_rows(message):
    """main.PROCESSES: (id, title, detail, expected_s) of each process shown on the page, in the page's order. `message` is
    messages.M (this module does not import messages: messages -> machine_state -> heartbeats would close a cycle)."""
    return [(s.id, s.title if s.title_is_text else message(s.title), message(s.detail), s.expected_s)
            for s in SPECS if s.title is not None]


def plugin_needs():
    """service_modules.PROCESSES: {process: plugins that need it}."""
    return {s.id: s.needs_plugins for s in sorted((s for s in SPECS if s.needs_plugins), key=lambda s: s.view_rank)}


def never_gated():
    """service_modules.SAFETY."""
    return tuple(s.id for s in sorted((s for s in SPECS if s.never_gated), key=lambda s: s.view_rank))


def own_rule():
    """service_modules.OWN."""
    return tuple(s.id for s in SPECS if s.own)


def catalog():
    """process_catalog.CATALOG: {id: {"group", "locked"}}."""
    return {s.id: {"group": s.group, "locked": s.locked} for s in SPECS}


def mode_live():
    """process_catalog.MODE_LIVE."""
    return tuple(s.id for s in SPECS if s.mode_live)


def pausable():
    """process_catalog.PAUSABLE."""
    return tuple(s.id for s in SPECS if s.pausable)


def watched():
    """The processes protection_guard expects a heartbeat from, in its order."""
    return tuple(sorted((s for s in SPECS if s.protects), key=lambda s: s.watch_rank))


def launch_order(phase):
    """Specs the supervisor launches in `phase`, in launch order."""
    return tuple(sorted((s for s in SPECS if s.start and s.phase == phase), key=lambda s: s.rank))


# ---- starting ----

def resolve(start, load):
    """"module:attr.attr()" -> the function. A segment ending in () is called (gcodelib_indexer:instance().run_loop)."""
    module, path = start.split(":", 1)
    target = load(module)
    for part in path.split("."):
        if part.endswith("()"):
            target = getattr(target, part[:-2])()
        else:
            target = getattr(target, part)
    return target


def launch_phase(phase, launcher, load, values, before=None):
    """Launches every process of `phase` through launcher(label, target, *args) (heartbeats.launch). `values` maps the argument
    names of the specs to what they stand for; before[label]() runs just before that process is launched."""
    for spec in launch_order(phase):
        if before and spec.id in before:
            before[spec.id]()
        launcher(spec.id, resolve(spec.start, load), *[values[a] for a in spec.args])


# ---- threads ----

def spawn(target, name=None, args=(), kwargs=None, daemon=True):
    """Starts a daemon thread (the only place bootstrap starts one) and returns it."""
    t = threading.Thread(target=target, name=name, args=args, kwargs=kwargs or {}, daemon=daemon)
    t.start()
    return t


def set_excepthook(hook):
    """What an uncaught error in any thread calls (main._excepthook_thread)."""
    threading.excepthook = hook
