"""
Catalog of the service's internal processes for the "Workshop services" page (processes redesign, phase 1).

Pure data, no I/O. Every process (the heartbeat label) has a GROUP the page uses to sort it and a LOCKED flag:
a locked process has NO switch on the page (the safety group, plus the ones the service cannot run without).
heartbeats.register merges these two fields into the process info, so snapshot() publishes them; an id that is not
here gets the defaults (group "support", not locked) and the regression test (test_process_catalog.py) fails
until it is added.
"""

GROUPS = ("safety", "machine", "data", "support")
DEFAULT_GROUP = "support"

_SAFETY = ("guardian_laser", "intercept_watchdog", "watchdog_lock", "guard", "motion", "risk", "events",
           "config_guard", "health", "interceptor")
_MACHINE = ("jog", "bed_zones", "timer", "status_light")
_DATA = ("consumption", "motors", "maintenance", "pid_trace", "trace", "jobs", "box_black", "base_backup",
         "commands_extra")
_SUPPORT = ("subscription", "publisher", "communication", "camera", "api", "api_macros")
# no switch on the page: safety, plus the processes the rest of the service stands on
_LOCKED_EXTRA = ("jobs", "subscription", "publisher", "api", "commands_extra", "api_macros")

CATALOG = {}
for _group, _ids in (("safety", _SAFETY), ("machine", _MACHINE), ("data", _DATA), ("support", _SUPPORT)):
    for _id in _ids:
        CATALOG[_id] = {"group": _group, "locked": _group == "safety" or _id in _LOCKED_EXTRA}

# Processes whose loop re-reads the MODE (service_modules.process(label), which honours on/off) on EVERY pass, so a change of
# the switch reacts without restarting the service. Verdicts (phase 2, read from the loops; conservative, when in doubt OUT):
#   bed_zones    IN   bed_zones_intercept.py:221 `while True: if not service_modules.process(LABEL)` (LABEL = "bed_zones") -> rests at once.
#   interceptor  OUT  main.py:341 does re-read process("interceptor") each pass, but it is a safety process (locked, no switch) and the
#                     rule is: a safety process is never listed as live.
#   subscription OUT  main.py:649 waits for process("subscription") ONCE before machine_state.launch(); never stops it afterwards.
#   status_light, consumption, motors, camera, maintenance, pid_trace  OUT  their loops call is_active(<plugin>) (status_light.py:1888,
#                     consumption_poller.py:168, motor_poller.py:230, camera_relay.py:177, machine_maint_poller.py:188, pid_trace.py:157):
#                     they test the PLUGIN, not the mode; "off" and "on" are only read by the supervisor at launch (heartbeats.launch).
#   jog, timer, trace, events, jobs, risk, config_guard, motion, health, guard  OUT  no loop reads service_modules (grep): only the
#                     supervisor at launch decides.
# protection_guard.py:307 reads process() each pass but only to decide what it EXPECTS alive; it does not stop anything.
MODE_LIVE = ("bed_zones",)


# Processes the page may PAUSE / RESUME / RESTART (phase 3, ops processes.pause / resume / restart): the non-locked ones of the data group whose
# loop has a plain per-pass structure and calls heartbeats.gate(label) at the top of each pass. Read from the loops (2026-11):
#   consumption  consumption_poller.run_loop   `while True`, one meter read per pass, sleeps POLL_INTERVAL_S: gate before the plugin check.
#   motors       motor_poller.run_loop         `while not stop()`, read-only M122/M569/M569.2 polling, rests with pause(): gate at the top.
#   maintenance  machine_maint_poller.run_loop `while not stop()` around _cycle(): gate in the loop; paused = the odometer rests (col.rest).
#   pid_trace    pid_trace.run_loop            same shape as maintenance; its finally saves the record, so a restart loses nothing.
#   trace        job_trace.run_loop            `while True: time.sleep(v.run_once())`; paused = the recorder sleeps (a gap, as when nobody looks).
# NOT pausable, whatever the page may want: anything locked, the safety group, the machine group (jog, bed_zones, timer, status_light),
# camera, jobs, box_black (its loop writes the black box a crash report depends on), base_backup (a once-a-day job, no per-pass loop).
PAUSABLE = ("consumption", "motors", "maintenance", "pid_trace", "trace")


def is_pausable(process_id):
    return process_id in PAUSABLE and not is_locked(process_id) and group_of(process_id) == "data"


def is_mode_live(process_id):
    return process_id in MODE_LIVE


def group_of(process_id):
    return CATALOG.get(process_id, {}).get("group", DEFAULT_GROUP)


def is_locked(process_id):
    return bool(CATALOG.get(process_id, {}).get("locked", False))


def missing_modes(modes=None):
    """Ids that service_modules lets the user set (PROCESSES, SAFETY, OWN, "subscription") with no catalog entry."""
    if modes is None:
        import service_modules
        modes = list(service_modules.PROCESSES) + list(service_modules.SAFETY) + list(service_modules.OWN) + ["subscription"]
    return sorted(m for m in modes if m not in CATALOG)
