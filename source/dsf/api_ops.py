"""
Operations of the WorkshopService API (2026-10-13). Each one is implemented by
a file of handlers/, the internal implementation (run(params, bridge, config) with one letter per parameter)
and this table maps the named JSON arguments to them.

Generic part (transport, validation, permissions, confirmations, errors):
workshop_api.py. Single owner of the movement: motion_owner.py. Macros of the
SD: api_macros.py. Design: docs/api/DESIGN.md.
"""
import paths
import importlib.util
import json
import os
import time

import api_keys
import api_users
import camera_access
import audit
import guard_api
import health_history
import identity
import config_package
import startup_summary
import profile_ops
import users
import workshop_api as wa
from workshop_api import ADMIN, MOTION, POWER, READ, STOP, WRITE, Arg, ApiError, Op
import messages
import settings_ops
import interlocks
import live_job_stop
import machine_ops
import trace_since
import work_state
from messages import M

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HANDLERS_DIR = os.path.join(BASE_DIR, "handlers")
# The local key of the system programs lives OUTSIDE the SD: DuetWebServer serves the SD as 0:/ to anybody who can read files through DWC.
# Mode 640 group dsf: the service, Vision and RS485 run as dsf, the G-code bridge as the login user (member of dsf).
TOKEN_FILE = paths.CONF + "/workshop-api-token"
LEGACY_TOKEN_FILE = paths.DATA_DIR + "/.api-token"   # before 2026-10-26: on the SD, readable through DWC

_ctx = {"bridge": None, "config": None, "log": print, "log_file": print, "registry": None, "keys": None, "users": None}
KEYS_FILE = api_keys.KEYS_FILE

# Confirmation texts (also in the localization of the service page,
# plugins.WorkshopService.api.confirm.<key>.*). The server sends them so a
# program without DWC can show them too.
def _confirm(title_key, text_key):
    """{"es": {"title", "text"}, "en": {...}} as plain texts: both languages travel together, so they must not be localized again."""
    return {lang: {"title": messages.render(lang, title_key), "text": messages.render(lang, text_key)} for lang in ("es", "en")}


CONFIRM_TEXTS = {
    "power.off": _confirm("api_ops_power_off_now", "api_ops_shuts_system_down_cuts_power_whole"),
    "power.full_reset": _confirm("api_ops_restart_everything", "api_ops_restarts_board_m999_system_whatever"),
    "comms.set": _confirm("api_ops_change_communication_channel", "api_ops_changing_where_codes_service_jog_go"),
    "motors.disable": _confirm("api_ops_release_motors", "api_ops_motors_lose_their_force_position_lost"),
    "workarea.release": _confirm("api_ops_release_xy_by_hand", "api_ops_xy_released_by_hand_notice"),
    "password.set": _confirm("api_ops_dwc_password", "api_ops_from_now_dwc_external_programs_ask"),
    "keys.create": _confirm("api_ops_create_access_key", "api_ops_whoever_has_key_will_able_use"),
    "keys.revoke": _confirm("api_ops_delete_key", "api_ops_service_that_uses_it_stops_working"),
    "password.clear": _confirm("api_ops_remove_dwc_password", "api_ops_anyone_network_will_able_use_dwc"),
    "lights.apply_m950": _confirm("api_ops_change_led_count_config_g", "api_ops_m950_line_config_g_edited_copy"),
    "motion": _confirm("api_ops_move_with_job_open", "api_ops_job_running_or_open_moving_now"),
    "machine.config.apply": _confirm("machine_confirm_apply_title", "machine_confirm_apply_text"),
    "machine.try": _confirm("machine_confirm_try_title", "machine_confirm_try_text"),
    "machine.mark_cross": _confirm("machine_confirm_cross_title", "machine_confirm_cross_text"),
    "workarea.step": _confirm("machine_confirm_area_step_title", "machine_confirm_area_step_text"),
}


def _param(v):
    """Named argument value -> the value a handler expects."""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return ",".join(v)
    return v


def run_handler(name, params):
    """Runs handlers/<name>.py with a fresh module."""
    path = os.path.join(HANDLERS_DIR, f"{name}.py")
    if not os.path.isfile(path):
        raise ApiError("internal", f"handler {name} is missing in this installation")
    spec = importlib.util.spec_from_file_location(f"handler_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run(params, _ctx["bridge"], _ctx["config"])


def _actor_params(ctx):
    """Who calls, as handler parameters: D device, U name of the person, R role (see handlers/jog.py)."""
    a = identity.actor(ctx)
    return {"D": a["device"], "U": a["user"], "R": a["role"]}


def H(handler, fixed=None, letters=None, value_map=None, xf=None, actor=False):
    """Operation function that calls a handler. letters: {arg: letter};
    value_map: {arg: {api value: handler value}} (English -> internal);
    xf: {arg: fn(value)} for values the handler wants encoded; actor: also pass who calls (D, U, R)."""
    fixed = dict(fixed or {})
    letters = dict(letters or {})
    value_map = dict(value_map or {})
    xf = dict(xf or {})

    def fn(args, ctx):
        params = dict(fixed)
        for name, v in args.items():
            letter = letters.get(name)
            if letter is None:
                continue
            if name in value_map and v in value_map[name]:
                v = value_map[name][v]
            if name in xf:
                v = xf[name](v)
            params[letter] = _param(v)
        if actor:
            params.update(_actor_params(ctx))
        return run_handler(handler, params)

    fn.handler = handler
    return fn


def _hex(v):
    """The meter handler keeps the local key hex encoded (it has quotes and brackets)."""
    return str(v or "").encode("utf-8").hex()


def _armed(args, ctx):
    v = args.get("armed")
    if isinstance(v, str):
        s = v.strip().lower()
        state = "toggle" if s == "toggle" else ("arm" if s in ("1", "true", "on", "yes", "arm") else "disarm")
    else:
        state = "arm" if v else "disarm"
    return run_handler("shutdown", {"S": state})


def _jog_move(action, letters):
    """jog.xy / jog.z / jog.axis: the handler answers "confirm: ..." or
    "Jog bloqueado: ..." when the owner of the movement does not allow it."""
    def fn(args, ctx):
        params = {"S": action}
        params.update(_actor_params(ctx))
        for k, v in args.items():
            if k in letters:
                params[letters[k]] = _param(v)
        if ctx.get("confirm"):
            params["C"] = 1  # the person accepted to move with the live job open and idle
        s = str(run_handler("jog", params) or "")
        if s.startswith("confirm:"):
            reason = s.split(":", 1)[1].strip()
            raise ApiError("confirm_required", reason, confirm=_ctx["registry"].confirm_info(
                Op("jog", None, confirm={"level": 3, "key": "motion"}), reason=reason))
        if s.startswith("Jog bloqueado:"):
            raise ApiError("motion_denied", s.split(":", 1)[1].strip(), motion={"decision": "deny"})
        return s

    return fn


def _view(args, ctx):
    topic = args["topic"]
    if topic == "trace":
        import job_trace
        job_trace.beat()
        return {"ok": True, "topic": topic, "sleep_s": job_trace.SLEEP_S}
    import viewers
    viewers.heartbeat(topic)
    return {"ok": True, "topic": topic, "sleep_s": viewers.TTL_S}


def _state_get(args, ctx):
    payload = dict(getattr(_ctx["bridge"], "payload", {}) or {})
    keys = args.get("keys")
    if keys:
        return {k: payload.get(k) for k in keys}
    return payload


def _notify_send(args, ctx):
    import notifier
    cfg = notifier.get_cfg(_ctx["config"])
    if not cfg.get("topic"):
        raise ApiError("failed", "notifications have no destination (Activity page)")
    notifier.send(cfg, args.get("title") or "Workshop", args.get("message") or "")
    return "sent"


def _pid_trace(args, ctx):
    import pid_trace
    return pid_trace.get()


def _pid_start(args, ctx):
    data = {"tool": args["tool"], "zones": args.get("zones") or []}
    return run_handler("pid_zones", {"S": "start", "J": data})


# ---- motion owner ----

def _motion_ask(args, ctx):
    import motion_owner
    d = motion_owner.evaluate(_ctx["bridge"], args.get("action") or "move", args.get("origin") or ctx.get("origin") or "",
                              confirm=bool(ctx.get("confirm")), token=args.get("token"), actor=identity.actor(ctx))
    d.pop("state", None)
    d["state"] = motion_owner.snapshot(_ctx["bridge"])
    return d


def _motion_reserve(args, ctx):
    import motion_owner
    d = motion_owner.reserve(_ctx["bridge"], args.get("origin") or ctx.get("origin") or "?", args.get("action") or "sequence",
                             args.get("text") or "", args.get("seconds") or motion_owner.RESERVE_DEFAULT_S, bool(ctx.get("confirm")),
                             actor=identity.actor(ctx))
    d.pop("state", None)
    return d


def _motion_take_over(args, ctx):
    import motion_owner
    d = motion_owner.take_over(_ctx["bridge"], args.get("origin") or ctx.get("origin") or "?", args.get("action") or "sequence",
                               args.get("text") or "", args.get("seconds") or motion_owner.RESERVE_DEFAULT_S, actor=identity.actor(ctx))
    d.pop("state", None)
    if d.get("decision") == "deny":
        raise ApiError("motion_denied", d["reason"], motion={"decision": "deny", "code": d.get("code")})
    return d


def _motion_renew(args, ctx):
    import motion_owner
    r = motion_owner.renew(_ctx["bridge"], args["token"], args.get("seconds"), actor=identity.actor(ctx))
    if r.get("code") == "not_owner":
        raise ApiError("motion_denied", r["reason"], motion={"decision": "deny", "code": "not_owner"})
    return r


def _motion_release(args, ctx):
    import motion_owner
    r = motion_owner.release(_ctx["bridge"], args["token"], actor=identity.actor(ctx))
    if r.get("code") == "not_owner":
        raise ApiError("motion_denied", r["reason"], motion={"decision": "deny", "code": "not_owner"})
    return r


def _motion_state(args, ctx):
    import motion_owner
    return motion_owner.snapshot(_ctx["bridge"])


def _frame_start(args, ctx):
    import frame_ops
    r = frame_ops.launch(_ctx["bridge"], args.get("points"), args.get("mode"), args.get("power_pct") or 0, args.get("repeat", 1))
    if not r.get("ok"):
        raise ApiError("refused", r.get("error") or "the frame was not started")
    return r


def _frame_stop(args, ctx):
    import frame_ops
    return frame_ops.stop()


def _frame_status(args, ctx):
    import frame_ops
    return frame_ops.status()


def motion_check(op, args, ctx):
    """Registry hook: operations with a motion class ask the owner first."""
    import motion_owner
    d = motion_owner.evaluate(_ctx["bridge"], op.motion, ctx.get("origin") or op.name, confirm=bool(ctx.get("confirm")),
                              actor=identity.actor(ctx))
    if d["decision"] == "deny":
        raise ApiError("motion_denied", d["reason"], motion={"decision": "deny", "code": d["code"], "reason": d["reason"]})
    if d["decision"] == "confirm":
        raise ApiError("confirm_required", d["reason"], confirm=_ctx["registry"].confirm_info(
            op, reason=d["reason"], level=3), motion={"decision": "confirm", "code": d["code"]})


# ---- table ----

def _ops():
    S, I, N, B, O, L = "str", "int", "num", "bool", "obj", "list"
    a = Arg
    # shared argument descriptions
    d_from = "Start of the range, inclusive: YYYY-MM-DD (from 00:00:00) or a full date and time YYYY-MM-DDTHH:MM:SS."
    d_to = "End of the range, inclusive, same format; a date alone means the end of that day. Empty: the same as from."
    d_limit = "Rows per page (default 50, at most 200)."
    d_offset = "Rows to skip, for paging (default 0)."
    d_act_type = "Only events of this exact type (for example job_start, job_end, power, config, modo, sistema). Empty: every type."
    d_act_exclude = "Event types to leave out, for example [\"servicio\"] hides the restarts of the service."
    d_act_user = "Only the events done by this person (user name, as in rows[].user)."
    d_act_mine = "true: only the events of the person of this session (the server knows who it is); without users (open mode) it filters nothing."
    d_act_query = "Text searched in the description, the type and the detail of each event (the first 80 characters are used)."
    d_meter_sel = "Key of the meter (empty: the main one, the one that feeds the system); \"total\" adds up the meters on their own line."
    d_meter_key = "Key of the meter (empty: the main one, the one that feeds the system)."
    d_tuya_id = "Tuya device id of the meter."
    d_tuya_ip = "IP address of the meter on the local network, for example 192.168.1.50."
    d_tuya_ver = "Tuya protocol version of the meter: 3.1, 3.2, 3.3, 3.4 or 3.5 (default 3.3)."
    d_jog_speed = ("Speed in percent of the jog range, from the minimum to the maximum jog feed of the jog settings (default 50); "
                   "never above the axis speed limits of the board (M203).")
    d_jog_release = ("true: this device lets go of ITS control; ignored when another device holds the jog. "
                     "Without it (or false) the stop stops everything, whoever holds it (safety).")
    d_lights_secs = "How long the LEDs stay like that, 2 to 30 seconds (default 6); the automatic lighting is paused meanwhile."
    d_lights_strip_e = "E number of the strip (the E<n> of its M950 line); empty: the main strip."
    d_cfg_who = "Who does it (person or screen); noted in the roll back state and in Activity."
    d_bigpart = "Request of the page as an object (see the operation); errors come back as {ok: false, error}."
    return [
        Op("state.get", _state_get, READ, {"keys": a(L, desc="Names of the data keys to return (for example motion, liveJob); empty returns every key.")},
           "Returns the data the service publishes in the object model (plugins.WorkshopService.data) from its memory; nothing is asked to the board.",
           log=False),
        *health_history.ops(),  # health.history
        *guard_api.ops(),  # protection guard (guard.status, guard.set)
        # activity
        Op("activity.list", H("activity_query", {}, {"from": "D", "to": "A", "type": "T", "exclude": "X", "limit": "L", "offset": "O", "query": "Q", "user": "W", "mine": "E"}), READ,
           {"from": a(S, True, desc=d_from), "to": a(S, desc=d_to), "type": a(S, desc=d_act_type), "exclude": a(L, desc=d_act_exclude),
            "limit": a(I, min=1, max=200, desc=d_limit), "offset": a(I, min=0, desc=d_offset), "query": a(S, desc=d_act_query),
            "user": a(S, desc=d_act_user), "mine": a(B, desc=d_act_mine)},
           "Lists the events of the Activity history (jobs, power, configuration, warnings...) of a date range, paged and filtered; "
           "also returns the total and the event types that exist."),
        Op("activity.delete", H("activity_query", {"C": "remove"}, {"id": "I"}), WRITE,
           {"id": a(I, True, desc="Id of the event, as returned by activity.list (rows[].id).")},
           "Deletes one event of the Activity history for good."),
        Op("activity.clear", H("activity_query", {"C": "clean"}, {"from": "D", "to": "A", "type": "T", "exclude": "X", "query": "Q"}), WRITE,
           {"from": a(S, True, desc=d_from), "to": a(S, desc=d_to), "type": a(S, desc=d_act_type), "exclude": a(L, desc=d_act_exclude),
            "query": a(S, desc=d_act_query)},
           "Deletes every Activity event that matches the filter (date range, type, excluded types, text) and returns how many; cannot be undone."),
        Op("activity.log", H("log", {}, {"type": "T", "text": "N", "zone": "Z", "points": "P"}), WRITE,
           {"type": a(S, True, choices=("calibration", "config", "warning", "fire", "safety_check", "job_start"),
                      desc="Kind of event: calibration (a calibration was saved), config (a setting changed), warning, fire (flame or smoke seen: urgent), "
                           "safety_check (the operator confirmed the manual safety checklist before a cut; the user is the caller) or "
                           "job_start (the operator started a job from a page)."),
            "text": a(S, desc="Text of the event as shown in Activity and in the notification (cut at 300 characters). Required except for "
                              "safety_check; for job_start it is the name of the job."),
            "zone": a(S, desc="safety_check and job_start: name or number of the work zone."),
            "points": a(L, desc="safety_check: ids of the checklist points the operator confirmed (at most 20, each up to 40 characters).")},
           "Writes an event in the Activity history and, if that event type is enabled in the notifications, sends it to the phone. "
           "For things that leave no trace on the machine (calibrations, settings, warnings, fire).", macro=True),
        # air assist
        Op("air.set", lambda x, c: run_handler("airassist", {"S": "on" if x["on"] else "off"}), WRITE,
           {"on": a(B, True, desc="true switches the pump on, false switches it off.")},
           "Switches the air assist pump on or off now by running the macro laser/airon.g or laser/airoff.g (they only act in Laser mode) "
           "and updates the state shown on the pages.", macro=True),
        Op("air.auto", lambda x, c: run_handler("airassist", {"S": "auto_on" if x["on"] else "auto_off"}), WRITE,
           {"on": a(B, True, desc="true enables the automatic mode, false leaves the pump under manual control only.")},
           "Turns the automatic air assist on or off: when on, the pump follows the laser codes M3/M4 (on) and M5 (off after the delay of air.delay). "
           "Saved; the current pump state is not changed.", macro=True),
        Op("air.delay", H("airassist", {"S": "delay"}, {"seconds": "D"}), WRITE,
           {"seconds": a(N, True, min=0, max=60, desc="Delay in seconds after M5, 0 to 60.")},
           "Sets how many seconds the automatic air assist waits after M5 before switching the pump off. Saved."),
        # power
        Op("power.after_job", _armed, WRITE, {"armed": a("any", True, desc="true arms, false disarms, \"toggle\" switches the current state.")},
           "Arms or disarms the power off at the end of the current job (or of the next one that starts); sys/daemon.g then runs the power off of power.off. "
           "Saved, mirrored in global.powerOffOnFinish and logged in Activity.", macro=True),
        Op("power.timer", H("shutdown", {"S": "temporizar"}, {"minutes": "N"}), WRITE,
           {"minutes": a(I, True, min=1, max=720, desc="Minutes from now until the power off, 1 to 720.")},
           "Schedules the power off of the whole machine in N minutes (the same power off as power.off; with a job running at that time it arms "
           "power.after_job instead). Saved, survives a restart of the service; logged in Activity."),
        Op("power.timer_cancel", H("shutdown", {"S": "cancel_timer"}), WRITE, {},
           "Cancels the scheduled power off timer, if any (logged in Activity when there was one)."),
        Op("power.method", H("shutdown", {"S": "method"}, {"method": "C", "power_off_system": "A", "relay_output": "R", "relay_value": "V"},
                             {"method": {"meter": "meter", "relay": "relay"}}), WRITE,
           {"method": a(S, choices=("auto", "meter", "relay", "pson"),
                        desc="auto (the meter if one is configured, else the relay if set, else PS_ON if the board has it, else only the system), "
                             "meter (the Tuya meter cuts the whole machine), relay (an output of the board cuts all the power), "
                             "pson (M81 switches off the power supply controlled by PS_ON)."),
            "power_off_system": a(B, desc="With PS_ON, also shut the Raspberry Pi (the system) down; the meter and relay methods always shut it down."),
            "relay_output": a(I, min=0, max=63, desc="Board output that drives the relay (the P number of its M950 line), 0 to 63."),
            "relay_value": a(I, min=0, max=1, desc="Value written with M42 to that output to CUT the power: 0 or 1.")},
           "Chooses how power.off, the timer and the power off after the job cut the power. Only the arguments given change; saved, logged in Activity; "
           "the answer says what will happen."),
        Op("power.off", H("shutdown_all"), POWER, {},
           "Cuts the power of the whole machine with the chosen method (power.method): extra meters first, then sync, cut and system shutdown. "
           "Whatever is running stops. Needs a confirmation.", confirm={"level": 3, "key": "power.off"}, macro=True),
        Op("power.full_reset", H("reset_all"), POWER, {},
           "Restarts everything by software without cutting the power: asks the system to reboot and resets the board with M999. "
           "Whatever is running stops and homing is lost. Needs a confirmation.", confirm={"level": 3, "key": "power.full_reset"}, macro=True),
        # database
        Op("db.status", H("base", {"S": "state"}), READ, {}, "Returns the state of the service database, its backups and its maintenance."),
        Op("db.backup", H("base", {"S": "backup"}), WRITE, {},
           "Makes a backup now: the database and the workshop folders (0:/sys/workshop config, data, zones) in one .tar.gz in the backup folder "
           "(and in the extra copy if set)."),
        Op("db.places", H("base", {"S": "places"}), READ, {},
           "Lists where backups can be kept: the system card and every mounted USB stick, with their free space."),
        Op("db.folder", H("base", {"S": "folder"}, {"path": "D"}), WRITE,
           {"path": a(S, True, desc="Absolute folder on the system card (inside the DSF SD folder) or on a USB stick (/media/..., /mnt/...), "
                                    "for example one of db.places.")},
           "Changes the backup folder: the existing backups are copied (not moved) and checked; the old folder stays until db.delete_previous."),
        Op("db.delete_previous", H("base", {"S": "delete_previous"}), WRITE, {},
           "Deletes the backups of the previous backup folder that already have a copy in the current one; the others are left alone."),
        Op("db.keep", H("base", {"S": "keep"}, {"file": "F", "keep": "V"}), WRITE,
           {"file": a(S, True, desc="File name of the backup in the backup folder (as listed by db.status)."),
            "keep": a(B, default=True, desc="true (default) protects it from the automatic deletion; false lets the rotation delete it again.")},
           "Marks a backup so the rotation never deletes it automatically, or releases that mark."),
        Op("db.settings", H("base", {"S": "settings"}, {"auto": "A", "daily": "N", "weekly": "W", "summarize": "R", "extra_copy": "E"}), WRITE,
           {"auto": a(B, desc="Automatic daily backups on or off."),
            "daily": a(N, min=0, desc="How many daily backups are kept (the service keeps it between 1 and 60)."),
            "weekly": a(N, min=0, desc="How many weekly backups are kept among the older ones (0 to 52)."),
            "summarize": a(B, desc="Summarize meter readings older than 90 days to one per hour (after a warning and a backup); false never summarizes."),
            "extra_copy": a(S, desc="Extra copy of each backup: \"auto\" (the first USB stick, or the card when the main folder is a stick), "
                                    "\"no\", or a folder on the card or on a stick.")},
           "Changes the backup settings; only the arguments given change. Returns the resulting settings."),
        # sound
        Op("sound.beep", H("beep", {}, {"pattern": "S"}), WRITE,
           {"pattern": a(S, choices=("ok", "done", "error", "attention"), default="ok",
                         desc="ok (one beep, default), done (three rising beeps), error (two low beeps) or attention (three short beeps).")},
           "Plays a beep pattern with M300 (DWC sounds it on the screens where it is open); it answers at once and plays in the background.", macro=True),
        # black box
        Op("blackbox.status", H("blackbox", {"S": "status"}), READ, {},
           "State of the black box (a line of load, CPU, RAM, temperature and state every few seconds in 0:/sys/workshop/data/blackbox/) "
           "and the report of the last unclean shutdown."),
        Op("blackbox.lines", H("blackbox", {"S": "lines"}, {"n": "N"}), READ,
           {"n": a(I, min=1, max=200, default=20, desc="Number of lines, 1 to 200 (default 20).")},
           "Returns the last lines written by the black box, as text."),
        Op("modules.list", H("service_modules", {"C": "list"}), READ, {},
           "Lists the internal processes of the service with the way each one runs (auto / on / off), whether it runs now and why (a plugin that needs it is enabled, or forced).", log=False),
        Op("modules.set", H("service_modules", {"C": "set"}, {"process": "P", "mode": "M"}), WRITE,
           {"process": a(S, True, desc="Id of the internal process (as listed by modules.list)."),
            "mode": a(S, True, choices=("auto", "on", "off"), desc="auto: runs only while a plugin that needs it is enabled; on: always; off: never (applies at the next start of the service).")},
           "Chooses how an internal process of the service runs. Saved in the configuration."),
        Op("examples.list", H("examples", {"C": "list"}, {"plugin": "P"}), READ,
           {"plugin": a(S, True, desc="Id of the plugin that offers the examples (for example WorkshopJog).")},
           "Lists the example files a plugin offers (commented macros to edit) with their state: configured, example (all commented, still to configure) or missing.", log=False),
        Op("examples.create", H("examples", {"C": "create"}, {"plugin": "P", "file": "F"}), WRITE,
           {"plugin": a(S, True, desc="Id of the plugin that offers the examples."),
            "file": a(S, desc="Destination (relative to 0:/) of one example to create again even if it was created before; without it only the examples never created are made.")},
           "Creates the example files of a plugin that are missing and were never created. It never overwrites a file."),
        Op("jobs.preview", H("jobs_view", {}, {"file": "F", "max_vertices": "N", "mode": "M"}), READ,
           {"file": a(S, True, desc="G-code file under 0:/gcodes (for example Taller/frame.gcode)."),
            "max_vertices": a(I, min=2000, max=100000, default=30000, desc="Most vertices of the path that come back (the numbers are exact anyway)."),
            "mode": a(S, choices=("Laser", "CNC", "FFF"), desc="Mode used to read the file (default: the mode of the machine).")},
           "Reads a G-code file WITHOUT running it: the planned path in machine coordinates of the active work zone, estimated time, distances, feed range, pieces, layers, bounding box and the outline (convex hull) of what it works on.", log=False),
        Op("blackbox.note", H("blackbox", {"S": "note"}, {"text": "T"}), WRITE, {"text": a(S, True, desc="Text of the note.")},
           "Writes a note event in the black box (for example from a macro, to mark a moment).", macro=True),
        Op("blackbox.hide", H("blackbox", {"S": "hide"}), WRITE, {}, "Hides the card with the report of the last unclean shutdown of the system."),
        Op("blackbox.show", H("blackbox", {"S": "show"}), WRITE, {}, "Shows again the card with the report of the last unclean shutdown of the system (the report is never deleted)."),
        # camera
        Op("camera.status", H("camera_relay", {"S": "state"}), READ, {},
           "State of the camera relay (the process that serves the camera stream to the screens), with the number of viewers."),
        Op("camera.start", H("camera_relay", {"S": "start"}), WRITE, {},
           "Starts the camera relay again; fails without a configured camera. Not saved: after a restart the saved setting applies."),
        Op("camera.stop", H("camera_relay", {"S": "stop"}), WRITE, {},
           "Stops the camera relay: the stream is cut for every screen watching it. Not saved: after a restart the saved setting applies."),
        Op("camera.url", H("camera_relay", {"S": "url"}, {"url": "U"}), WRITE,
           {"url": a(S, True, desc="Stream address starting with http:// or https://, for example http://192.168.1.50:81/stream.")},
           "Changes the address of the main camera stream, saves it and restarts the relay with it (the screens reconnect by themselves)."),
        Op("camera.service", H("camera_relay", {"S": "service"}, {"changes": "J"}), WRITE,
           {"changes": a(O, desc="Settings to change, with the names of a read (for example {\"notice_camera\": \"main\"} or "
                                 "{\"timelapse\": {\"each_s\": 10}}). Empty: only read.")},
           "Reads or changes the camera service settings (photo in notifications and its camera, warning when a camera stops answering, "
           "limits of captures and timelapses, timelapse options). Without changes it only reads; with changes it saves them.", exclusive=False),
        Op("camera.capture", H("camera_relay", {"S": "capture"}, {"camera": "C"}), WRITE,
           {"camera": a(S, desc="Id of the camera; empty: the main camera (main).")},
           "Takes a photo from a camera and saves it with the date in the captures folder (0:/workshop/camera/captures)."),
        Op("camera.timelapse", H("camera_relay", {"S": "timelapse"}, {"action": "C", "name": "N"}, {"action": {"start": "begin", "stop": "stop", "status": ""}}),
           WRITE, {"action": a(S, choices=("start", "stop", "status"), default="status", desc="start, stop, or status (default: only returns the state)."),
                   "name": a(S, desc="Name of the timelapse when starting (default \"Timelapse HH:MM\").")},
           "Starts or stops a manual timelapse recording, or returns its state. Starting fails if one is already recording or less than 2 GB are free."),
        Op("camera.token", H("camera_relay", {"S": "token"}), READ, {},
           "Returns the key of the day (valid today and tomorrow) to watch the relay from another screen when DWC has a password."),
        # Vision service (OpenCV, port 8095): the pages ask here instead of calling the port from the browser
        Op("vision.get", H("vision_call", {"M": "get"}, {"path": "P"}), READ,
           {"path": a(S, True, desc="Vision path to read: /state, /orientation, /head or /lens.")},
           "Reads a JSON answer of the Vision service (state, camera orientation, head position, lens calibration). Fails with a clear message if Vision is off.",
           log=False),
        Op("vision.post", H("vision_call", {"M": "post"}, {"path": "P", "body": "J"}), WRITE,
           {"path": a(S, True, desc="Vision path to call: /photo, /detect, /record/search, /measure (only where Vision announces the measure capability, see docs/MACHINE-PHASE4-CONTRACT.md) or /config."),
            "body": a(O, desc="JSON body of the request (the arguments of that Vision path). Empty: no arguments.")},
           "Calls the Vision service: takes a photo, detects shapes, searches the record or changes its settings. A detection may take several seconds.",
           exclusive=False, slow=True),
        # history of received commands
        Op("history.list", H("commands_query", {}, {"from": "D", "to": "A", "name": "N", "errors": "E", "query": "Q", "limit": "L", "offset": "O",
                                                       "rw": "R", "via": "V", "channel": "G", "kind": "T", "plugin": "Y", "result": "Z"}), READ,
           {"from": a(S, True, desc=d_from), "to": a(S, desc=d_to),
            "name": a(S, desc="Only the calls of this operation, for example lights.get."),
            "errors": a(B, desc="true: only the calls that failed."),
            "query": a(S, desc="Text searched in the call and in its answer."),
            "limit": a(I, min=1, max=200, desc=d_limit), "offset": a(I, min=0, desc=d_offset),
            "rw": a(I, min=0, max=2, desc="0 every call, 1 only the ones that change something, 2 only reads."),
            "via": a(S, desc="Only the calls that arrived this way, as written in the history (for example \"API (DWC session)\", \"macro\", \"service\")."),
            "channel": a(S, desc="Only the calls of this origin channel (HTTP, SBC, Aux...); \"-\" for rows saved without origin data."),
            "kind": a(S, desc="Only the calls of this origin kind (page, console, job_file, macro, bridge, service, external...); \"-\" for rows without origin data."),
            "plugin": a(S, desc="Only the calls of this plugin or page tag; \"-\" for rows without origin data."),
            "result": a(S, desc="Only the calls with this result: ok, error or blocked; \"-\" for rows without origin data.")},
           "Lists the API calls received by the service (origin, result, duration) of a date range, paged and filtered; "
           "also returns counters of the range and of the last hour.", log=False),
        Op("history.delete", H("commands_query", {"C": "remove"}, {"from": "D", "to": "A"}), WRITE,
           {"from": a(S, True, desc=d_from), "to": a(S, desc=d_to)},
           "Deletes the received calls of a date range from the history; cannot be undone."),
        # communication channels
        Op("comms.get", H("communication"), READ, {},
           "Returns the channel the service uses to send its G-codes to the board and the one of the jog moves, with warnings and suggestions."),
        Op("comms.set", H("communication", {"A": 1, "K": "entiendo"}, {"plugin_channel": "C", "jog_channel": "J"}), ADMIN,
           {"plugin_channel": a(S, choices=("auto", "Aux2", "Aux", "SBC"), desc="Channel of the codes of the service: auto, Aux2, Aux or SBC."),
            "jog_channel": a(S, choices=("auto", "Aux2", "Aux", "SBC"), desc="Channel of the G1 moves of the jog: auto (Aux2 if free, else SBC), Aux2, Aux or SBC.")},
           "Advanced: changes the channel of the service codes and/or of the jog. Refused with a job, recent bridge activity, a jog gesture or the free jog on, "
           "and for channels that cannot be chosen now. Saved, applies at once, logged in Activity; level 4 confirmation.",
           confirm={"level": 4, "key": "comms.set"}),
        # configuration history, safe save and roll back (WorkshopConfig, Motors > stall as end stop, Workbench > level Z)
        Op("config.snapshot", H("config", {"C": "snapshot"}, {"data": "J", "file": "F", "reason": "N", "who": "Q", "rrf": "V", "mode": "M"}), WRITE,
           {"data": a(O, desc="Request: {archivos: [SD paths such as sys/config.g], motivo, quien, rrf, modo}; a plain list of paths works too. Use this or file."),
            "file": a(S, desc="0:/ path of a JSON file on the SD with the same request (for long lists). Use this or data."),
            "reason": a(S, desc="Reason shown in the history (overrides motivo; default \"Copia manual\")."),
            "who": a(S, desc="Who made the copy (person or screen); overrides quien."),
            "rrf": a(S, desc="RepRapFirmware version noted in the manifest; overrides rrf."),
            "mode": a(S, desc="Machine mode noted in the manifest (for example Laser, CNC, FFF); overrides modo.")},
           "Copies a set of configuration files of the SD to the configuration history (0:/sys/workshop/config-history/<id>/ with a manifest); "
           "missing files are listed as absent. Returns the id of the copy."),
        Op("config.list", H("config", {"C": "list"}), READ, {}, "Lists the copies of the configuration history, newest first (id, date, reason, who, files)."),
        Op("config.get", H("config", {"C": "get"}, {"id": "I"}), READ,
           {"id": a(S, True, desc="Id of the copy (YYYYMMDD-HHMMSS, as returned by config.list).")},
           "Returns the manifest of one copy of the configuration history (its files and why it was made)."),
        Op("config.commit", H("config", {"C": "commit"}, {"tx": "T", "owner": "K"}), WRITE,
           {"tx": a(S, True, desc="Id of the staged transaction (0:/sys/workshop/data/config-staging/<tx>/ with its manifest.json)."),
            "owner": a(S, desc="Id of the screen that holds the save lock; refused if another screen holds it.")},
           "Saves every file staged by a screen in one go: checks the lock and the hashes, copies the current files to the history first, "
           "then replaces them all atomically (put back if it fails half way). Logged in Activity."),
        Op("config.lock", H("config", {"C": "lock"}, {"owner": "K", "who": "Q", "seconds": "S"}), WRITE,
           {"owner": a(S, True, desc="Id of the screen that takes the lock."),
            "who": a(S, desc="Name shown to the other screens while the lock is held."),
            "seconds": a(I, min=1, max=3600, desc="How long the lock lasts (default 120); the service keeps it between 10 and 600 seconds.")},
           "Takes or renews the save lock of the configuration for one screen, so two screens never save at once; refused while another screen holds it."),
        Op("config.unlock", H("config", {"C": "unlock"}, {"owner": "K"}), WRITE, {"owner": a(S, True, desc="Id of the screen that holds the lock.")},
           "Releases the save lock; only its owner can, except an expired lock, which anyone can release."),
        Op("config.arm", H("config", {"C": "arm"}, {"id": "I", "tx": "T", "seconds": "S", "checks": "J", "file": "F", "who": "Q"}), WRITE,
           {"id": a(S, desc="Id of the copy to go back to. Use this or tx."),
            "tx": a(S, desc="Transaction of the commit; the copy made before it is used. Use this or id."),
            "seconds": a(I, min=10, max=3600, desc="Time to confirm after the restart, in seconds (default 300; the service keeps it between 30 and 3600)."),
            "checks": a(O, desc="Expected after the restart, for example {placas: [1, 40], ejes: 4, calentadores: 2, sondas: 1} (boards, axes, heaters, probes)."),
            "file": a(S, desc="0:/ path of a JSON file on the SD with the checks (instead of checks)."),
            "who": a(S, desc=d_cfg_who)},
           "Arms the automatic roll back before restarting the board with a new configuration: on a startup error, halt, no reconnection, a failed check "
           "or no confirmation in time, the copy is restored and the board restarted (with a notice). Refused with a job running."),
        Op("config.confirm", H("config", {"C": "confirm"}, {"who": "Q"}), WRITE, {"who": a(S, desc=d_cfg_who)},
           "Confirms that the new configuration works and disarms the roll back."),
        Op("config.rollback", H("config", {"C": "rollback"}, {"who": "Q"}), WRITE, {"who": a(S, desc=d_cfg_who)},
           "Emergency exit: restores the armed copy now and restarts the board, without looking at the save lock."),
        Op("config.restore", H("config", {"C": "restore"}, {"id": "I", "seconds": "S", "reboot": "R", "owner": "K", "who": "Q"}), WRITE,
           {"id": a(S, True, desc="Id of the copy to restore (from config.list)."),
            "seconds": a(I, min=0, max=3600, desc="Above 0: arms the roll back to the copy of the current files with this time to confirm; 0 disarms an armed roll back."),
            "reboot": a(B, desc="true restarts the board (M999) to load the restored files."),
            "owner": a(S, desc="Id of the screen; refused if another screen holds the save lock."),
            "who": a(S, desc=d_cfg_who)},
           "Restores any copy of the history (the current files are copied first; files the copy did not have are deleted). Refused with a job running; "
           "can arm the roll back and restart the board."),
        Op("config.guard", H("config", {"C": "guard"}), READ, {},
           "Returns the state of the roll back (armed or not, deadline, last result), the same as the plugin data configGuard."),
        # energy
        Op("energy.history", H("consumption_query", {}, {"from": "D", "to": "A", "limit": "L", "offset": "O", "meter": "M"}), READ,
           {"from": a(S, True, desc=d_from), "to": a(S, desc=d_to), "limit": a(I, min=1, max=200, desc=d_limit), "offset": a(I, min=0, desc=d_offset),
            "meter": a(S, desc=d_meter_sel)},
           "Returns the energy meter readings of a date range, paged, with a summary (kWh, peak and average power) and the power series of the range."),
        Op("energy.period", H("consumption_period", {}, {"period": "T", "date": "R", "meter": "M"}), READ,
           {"period": a(S, choices=("day", "month", "year"), default="day", desc="day (its 24 hours, default), month (its days) or year (its months)."),
            "date": a(S, desc="Reference date YYYY-MM-DD (default today): its day, month or year is used."),
            "meter": a(S, desc=d_meter_sel)},
           "Returns the kWh of a meter per hour of a day, per day of a month or per month of a year, ready to draw bars."),
        Op("energy.rate_get", H("consumption_tariff"), READ, {}, "Returns the currency and the price of one kWh used to show the approximate cost of the energy."),
        Op("energy.rate_set", H("consumption_tariff", {"C": "save"}, {"currency": "S", "value": "V"}), WRITE,
           {"currency": a(S, True, desc="Currency code shown next to the costs, for example USD, EUR, MXN (only a label; empty: the currency of the machine profile, or none)."),
            "value": a(N, True, min=0, desc="Price of one kWh in that currency.")},
           "Saves the currency and the price of one kWh (a label and a number, no conversion). Logged in Activity."),
        # energy meters
        Op("meter.get", H("consumption_meter", {}, {"meter": "M"}), READ,
           {"meter": a(S, desc="Key of a meter. Accepted, but the answer always lists every meter.")},
           "Returns the configured energy meters (Tuya) with their settings and the order in which the power off cuts them; local keys are masked."),
        Op("meter.search", H("consumption_meter", {"C": "search"}), READ, {},
           "Scans the local network for Tuya devices (about 8 seconds) and lists their IP, id and version, and which meter already uses each one.", slow=True),
        Op("meter.test", H("consumption_meter", {"C": "test"}, {"meter": "M", "id": "I", "ip": "H", "key": "K", "version": "V"}, xf={"key": _hex}), READ,
           {"meter": a(S, desc="Key of the meter being edited (empty: the main one); its saved local key is used when key is empty and the id is the same."),
            "id": a(S, desc=d_tuya_id), "ip": a(S, desc=d_tuya_ip),
            "key": a(S, desc="Local key of the device as text (empty: keep the saved one)."), "version": a(S, desc=d_tuya_ver)},
           "Tries to read a Tuya meter with the given data (power, voltage, current, energy) without saving anything.", slow=True),
        Op("meter.save", H("consumption_meter", {"C": "save"}, {"meter": "M", "id": "I", "ip": "H", "key": "K", "version": "V", "name": "N"},
                           xf={"key": _hex}), WRITE,
           {"meter": a(S, desc="Key of the meter to add or change (empty: the main one)."),
            "id": a(S, desc=d_tuya_id), "ip": a(S, desc=d_tuya_ip),
            "key": a(S, desc="Local key of the device as text (empty: keep the saved one when the id is the same)."), "version": a(S, desc=d_tuya_ver),
            "name": a(S, desc="Name shown for the meter (a new meter without a name uses its key).")},
           "Tries the meter and, only if it answers, saves it (adds a meter or changes one, keeping its kWh history continuous). Logged in Activity.",
           slow=True),
        Op("meter.forget", H("consumption_meter", {"C": "forget"}, {"meter": "M"}), WRITE, {"meter": a(S, desc="Key of the meter to remove (empty: the main one).")},
           "Removes a meter from the configuration (another one becomes the main one if needed); the saved readings are kept. Logged in Activity."),
        Op("meter.settings", H("consumption_meter", {"C": "settings"}, {"meter": "M", "changes": "J"}), WRITE,
           {"meter": a(S, desc=d_meter_key),
            "changes": a(O, True, desc="Any of: nombre, inside_of (key of the meter it is part of, or null), feeds_pi (feeds the system: cut last), "
                                       "corta (cut by the power off), orden (cut order, lower first), vigila (null or {calentador, threshold_w, cortar}: "
                                       "alarm when it draws power with that heater off).")},
           "Changes the settings of one meter: name, parent meter, whether it feeds the system, whether the power off cuts it, cut order and watched heater. "
           "Logged in Activity."),
        # jog
        Op("jog.xy", _jog_move("xy", {"x": "X", "y": "Y", "speed": "F"}), MOTION,
           {"x": a(N, True, min=-1, max=1, desc="X part of the knob deflection, -1 to 1 (the length of the x, y vector sets the speed; small values are a dead zone)."),
            "y": a(N, True, min=-1, max=1, desc="Y part of the knob deflection, -1 to 1."),
            "speed": a(N, min=0, max=100, default=50, desc=d_jog_speed)},
           "Moves X/Y while the jog knob is held: the service ramps the moves and stops if no update arrives within about 0.9 s, so repeat every ~300 ms. "
           "Denied with a job, bridge activity or a reservation; a live job idle asks a confirmation.", exclusive=False, log=False),
        Op("jog.z", _jog_move("z", {"z": "Z", "speed": "F"}), MOTION,
           {"z": a(N, True, min=-1, max=1, desc="Deflection of the Z control, -1 to 1; the sign gives the direction."),
            "speed": a(N, min=0, max=100, default=50, desc=d_jog_speed + " Z uses the zRatio fraction of that feed.")},
           "Moves Z while the jog control is held (repeat while held, like jog.xy). Same movement rules as jog.xy.", exclusive=False, log=False),
        Op("jog.axis", _jog_move("axis", {"axis": "L", "value": "V", "speed": "F"}), MOTION,
           {"axis": a(S, True, desc="Letter of an extra axis (U, V, W, A...); X, Y, Z and other values are ignored."),
            "value": a(N, True, min=-1, max=1, desc="Deflection, -1 to 1; the sign gives the direction."),
            "speed": a(N, min=0, max=100, default=50, desc=d_jog_speed)},
           "Moves an extra axis (U, V, W, A...) while its jog control is held (repeat while held). Same movement rules as jog.xy.",
           exclusive=False, log=False),
        Op("jog.stop_xy", H("jog", {"S": "stop_xy"}, {"release": "Q"}, actor=True), STOP, {"release": a(B, desc=d_jog_release)},
           "The X/Y knob was released: stops the X/Y jog at once. Never blocked.", exclusive=False),
        Op("jog.stop_z", H("jog", {"S": "stop_z"}, {"release": "Q"}, actor=True), STOP, {"release": a(B, desc=d_jog_release)},
           "The Z control was released: stops the Z jog at once. Never blocked.", exclusive=False),
        Op("jog.stop_axis", H("jog", {"S": "stop_axis"}, {"release": "Q"}, actor=True), STOP, {"release": a(B, desc=d_jog_release)},
           "The extra axis control was released: stops that jog at once. Never blocked.", exclusive=False),
        Op("jog.free", H("jog", {"S": "free"}, {"on": "A"}), MOTION, {"on": a(B, True, desc="true enters the mode, false leaves it.")},
           "Enters or leaves the jog mode without limits (moves without homing or beyond the M208 limits, guarded by stall detection); "
           "the jog loop applies the request.", exclusive=False),
        # lights
        Op("light.set", lambda x, c: run_handler("light", {"S": "on" if x["on"] else "off"}), WRITE,
           {"on": a(B, True, desc="true switches the working light on, false switches it off.")},
           "Switches the working light (lighting zone of the LED strip) on or off by running light/lighton.g or light/lightoff.g; "
           "updates the state shown on the pages.", macro=True),
        Op("statuslight.set", lambda x, c: run_handler("statuslight", {"S": "on" if x["on"] else "off"}), WRITE,
           {"on": a(B, True, desc="true: automatic control by mode and state; false: switched off by hand.")},
           "Status LEDs of the strip: back to automatic control (on) or switched off by hand (off), with the macros light/statusledon.g / statusledoff.g.",
           macro=True),
        Op("lights.get", H("lights", {"C": "query"}), READ, {},
           "Returns the configuration of the LED strip, lights and states (zones, colours, effects, scenes, night dimming) and its current state."),
        Op("lights.save", H("lights", {"C": "save"}, {"config": "J"}), WRITE,
           {"config": a(O, True, desc="The lights configuration object of the page (the keys of lights.get; unknown keys are ignored).")},
           "Saves the lights configuration (validated first), writes 0:/sys/workshop/macros/lights.g and runs it so the board uses it. Logged in Activity."),
        Op("lights.pi_pins", H("lights", {"C": "pi_pins"}), READ, {},
           "Lists the GPIO 2 to 27 of the Pi with what each one is doing (free, in use and by what) and what the lights can do with it (a strip over SPI on a MOSI pin), plus the state of that output.", log=False),
        Op("lights.pi_test", H("lights", {"C": "pi_test"}, {"seconds": "D", "pin": "N"}), WRITE,
           {"seconds": a(I, min=1, max=15, desc="How long the test lasts (default 4)."),
            "pin": a(I, True, min=2, max=27, desc="GPIO of the strip to test (it must be saved with its output on that pin).")},
           "Shows a short test on a strip whose output is a pin of the Pi (a moving colour). The normal frame comes back by itself."),
        Op("lights.test", H("lights", {"C": "test"}, {"count": "N", "seconds": "D", "strip": "T"}), WRITE,
           {"count": a(I, min=1, max=400, desc="How many LEDs to light from the start, 1 to 400 (default: the whole strip)."),
            "seconds": a(I, min=2, max=30, desc=d_lights_secs), "strip": a(I, desc=d_lights_strip_e)},
           "Lights the first N LEDs of a strip in blue for a few seconds, to count them. Needs a physical strip."),
        Op("lights.identify", H("lights", {"C": "identify"}, {"seconds": "D", "strip": "T", "segments": "J"}), WRITE,
           {"seconds": a(I, min=2, max=30, desc=d_lights_secs), "strip": a(I, desc=d_lights_strip_e),
            "segments": a(O, desc="Optional [[r, g, b, count], ...] in strip order (what the page shows, even unsaved); the rest of the strip goes off.")},
           "Paints every zone of a strip in its own colour for a few seconds (or the segments given), to see where each zone is. Needs a physical strip."),
        Op("lights.animation", H("lights", {"C": "animation"}, {"data": "J"}), WRITE,
           {"data": a(O, desc="Optional values to try without saving: {tipo: barra|parpadeo|centro|arcoiris, color: {r, u, b, w}, paso: 1-60}.")},
           "Runs the start-up animation of the strip now (sys/ledstartup.g), with the saved values or with the ones given. Needs a physical strip."),
        Op("lights.preview", H("lights", {"C": "view_preview"}, {"data": "J"}), WRITE,
           {"data": a(O, True, desc="{cuadros: [[[r,u,b,w,count], ...], ...], intervalo: 0.15-5 s, segundos: 1-20} for frames, or "
                                    "{simular: {config, activos, progreso, modo, trabajando}, segundos} to simulate states.")},
           "Shows example frames on the status zone for a few seconds, or simulates states with unsaved settings; nothing is saved. Needs a physical strip."),
        Op("lights.apply_m950", H("lights", {"C": "apply_m950"}, {"total": "N", "strip": "T"}), WRITE,
           {"total": a(I, True, min=1, max=400, desc="New number of LEDs of the strip, 1 to 400."), "strip": a(I, desc=d_lights_strip_e)},
           "Changes the LED count (U<total>) of the M950 line of a strip in sys/config.g, keeping a copy of config.g; the board must be restarted "
           "for it to apply. Logged in Activity; needs a confirmation.", confirm={"level": 3, "key": "lights.apply_m950"}),
        Op("lights.zone", H("lights", {"C": "zone"}, {"index": "N", "on": "S", "strip": "T"}), WRITE,
           {"index": a(I, True, min=0, desc="Position of the extra zone in its strip's list of extra zones, from 0."),
            "on": a(B, True, desc="true switches the zone on, false switches it off."),
            "strip": a(S, desc="Id of an additional strip; empty: the main strip.")},
           "Switches one extra zone of the strip on or off now (saved; the strip is repainted)."),
        Op("lights.test_state", H("lights", {"C": "test_state"}, {"state": "S", "seconds": "D", "outputs": "O", "data": "J"}), WRITE,
           {"state": a(S, True, desc="Id of the state in the lights configuration (for example parada, pausado)."),
            "seconds": a(I, min=2, max=20, desc="How long it is shown, 2 to 20 seconds (default 6)."),
            "outputs": a(L, desc="Outputs: strip, screen and/or board (default: the ones enabled for that state; strip is dropped without a strip)."),
            "data": a(O, desc="Optional {color, effect} to try instead of the saved ones.")},
           "Shows one light state for a few seconds on the chosen outputs, optionally with another colour or effect."),
        Op("lights.scene", H("lights", {"C": "scene"}, {"scene": "S", "color": "J"}), WRITE,
           {"scene": a(S, desc="Id of a saved scene of the working light (ignored when color is given)."),
            "color": a(O, desc="Free colour {r, u, b, w, p} instead of a scene.")},
           "Sets the colour of the working light from a scene or a free colour, saves it and switches the working light on. Needs a physical strip."),
        Op("lights.schedule", H("lights", {"C": "schedule"}, {"on": "S"}), WRITE, {"on": a(B, True, desc="true enables the night dimming, false disables it.")},
           "Turns the night dimming of the lights on or off (saved)."),
        Op("lights.import", H("lights", {"C": "import"}, {"data": "J", "hardware": "H"}), READ,
           {"data": a(O, True, desc="The profile exported by the page (or {config: <profile>})."),
            "hardware": a(B, desc="true also takes the hardware layout of the profile (strips, zones); false keeps the one of this machine.")},
           "Checks a lighting profile exported by the page and returns it merged with the current configuration; nothing is saved (use lights.save)."),
        # motors
        Op("motors.enable", H("motors", {"S": "enable"}, {"axes": "A"}), WRITE,
           {"axes": a(L, True, desc="Axes and extruders, for example [\"X\",\"E0\"], or \"all\".")},
           "Enables motors with M17 (axes and extruders). Refused with a job running (file or live) or the machine busy. Logged in Activity."),
        Op("motors.disable", H("motors", {"S": "disable"}, {"axes": "A"}), WRITE,
           {"axes": a(L, True, desc="Axes and extruders, for example [\"X\",\"E0\"], or \"all\".")},
           "Disables motors with M18: no holding torque and the homing is lost (a vertical axis can fall). Refused with a job or the machine busy; "
           "asks the movement owner; level 4 confirmation.", confirm={"level": 4, "key": "motors.disable"}, motion="geometry"),
        Op("motors.reread", H("motors", {"S": "reread"}), READ, {},
           "Asks the motors poller to read again which drivers are enabled (the result is published in the plugin data)."),
        # notifications
        Op("notifications.get", H("notifications", {"C": "query"}), READ, {},
           "Returns the phone notification settings (ntfy destination, event types and options, quiet hours, mute) and the catalogue of event types."),
        Op("notifications.active", H("notifications", {"C": "active"}, {"on": "V"}), WRITE,
           {"on": a(B, True, desc="true sends notifications, false sends none (events are still logged).")},
           "Turns every phone notification on or off. Saved and logged in Activity."),
        Op("notifications.destination", H("notifications", {"C": "destination"}, {"server": "S", "topic": "T"}), WRITE,
           {"server": a(S, desc="ntfy server starting with http:// or https:// (empty: https://ntfy.sh)."),
            "topic": a(S, desc="ntfy topic: letters, numbers, - and _, up to 64 characters.")},
           "Changes the ntfy server and topic the notifications go to. Saved and logged in Activity."),
        Op("notifications.new_topic", H("notifications", {"C": "new_topic"}), WRITE, {},
           "Replaces the ntfy topic with a new random one; the phone has to subscribe again. Saved and logged in Activity."),
        Op("notifications.type", H("notifications", {"C": "kind"}, {"type": "T", "on": "V"}), WRITE,
           {"type": a(S, True, desc="Event type id, for example job_end, error, power, fuego (catalogue in notifications.get)."),
            "on": a(B, True, desc="true sends this type to the phone, false does not.")},
           "Turns the phone notifications of one event type on or off. Saved."),
        Op("notifications.option", H("notifications", {"C": "option"}, {"type": "T", "attachment": "A", "priority": "R", "quiet_hours": "H", "camera": "K"},
                                     {"attachment": {"none": "nothing", "photo": "photo", "video": "video"}}), WRITE,
           {"type": a(S, True, desc="Event type id (catalogue in notifications.get)."),
            "attachment": a(S, choices=("none", "photo", "video"), desc="What is attached to the notification: none, a photo or a short video."),
            "priority": a(S, choices=("min", "low", "default", "high", "urgent", "auto"), desc="ntfy priority; auto goes back to the default of the type."),
            "quiet_hours": a(B, desc="Whether the quiet hours apply to this type."),
            "camera": a(S, desc="Camera of the photo or video: a camera id, or \"auto\" / \"\" for the default of the service.")},
           "Changes the options of one event type (attachment, priority, quiet hours, camera); only the arguments given change. Saved."),
        Op("notifications.quiet_hours", H("notifications", {"C": "schedule"}, {"on": "V", "from": "F", "to": "U", "mode": "Q"},
                                          {"mode": {"mute": "callar", "soft": "soft"}}), WRITE,
           {"on": a(B, desc="Quiet hours on or off."), "from": a(S, desc="Start time HH:MM, for example 22:00."),
            "to": a(S, desc="End time HH:MM, for example 07:00."),
            "mode": a(S, choices=("mute", "soft"), desc="mute: nothing is sent; soft: sent without sound.")},
           "Sets the daily quiet hours of the notifications; only the arguments given change. Saved and logged in Activity."),
        Op("notifications.video", H("notifications", {"C": "video"}, {"seconds": "D"}), WRITE,
           {"seconds": a(I, True, min=2, max=10, desc="Video length, 2 to 10 seconds.")},
           "Sets the length of the short video attached to the notifications that use video. Saved."),
        Op("notifications.mute", H("notifications", {"C": "silenciar"}, {"minutes": "D"}), WRITE,
           {"minutes": a(N, True, min=0, max=1440, desc="Minutes to mute, up to 1440; 0 unmutes now.")},
           "Mutes the phone notifications for N minutes (events are still logged), or unmutes them with 0. Logged in Activity."),
        Op("notifications.test", H("notifications", {"C": "test"}, {"type": "T"}), WRITE,
           {"type": a(S, desc="Event type id (catalogue in notifications.get): tests that type with its own attachment, priority and camera, skipping its switch, the quiet hours and the mute. Without it, a plain test.")},
           "Sends a test notification to the configured destination and returns whether it was accepted, with the settings. With a type it sends what a real event of that type would send, marked as a test."),
        Op("activity.summary", H("activity_query", {"C": "summary"}, {"from": "D", "to": "A", "exclude": "X", "user": "W", "mine": "E"}), READ,
           {"from": a(S, True, desc=d_from), "to": a(S, desc=d_to), "exclude": a(L, desc=d_act_exclude),
            "user": a(S, desc=d_act_user), "mine": a(B, desc=d_act_mine)},
           "Summary of the Activity history of a date range: events per type, jobs started / finished / cancelled, total job time and kWh, "
           "the finished jobs (newest first, up to 30), the last failures and emergency stops (up to 8) and the first and last event."),
        Op("notifications.send", _notify_send, WRITE,
           {"title": a(S, desc="Title of the notification (default Workshop)."), "message": a(S, True, desc="Text of the notification.")},
           "Sends a phone notification now to the configured ntfy topic (for macros and jobs); it does not look at the type switches, quiet hours or mute.",
           macro=True),
        # DWC password
        Op("password.status", H("password", {"S": "status"}), READ, {}, "Says whether DWC has a password (an active M551 in sys/config.g); it is never shown."),
        Op("password.set", H("password", {"S": "set"}, {"password": "V"}), ADMIN,
           {"password": a(S, True, desc="New password: 4 to 60 characters, without double quotes, semicolons or line breaks, not \"reprap\". Never kept in the history.")},
           "Sets or changes the DWC password: writes M551 in sys/config.g (with a backup copy) and applies it at once. Logged in Activity; needs a confirmation.",
           confirm={"level": 3, "key": "password.set"}),
        Op("password.clear", H("password", {"S": "clear"}), ADMIN, {},
           "Removes the DWC password: comments out M551 in sys/config.g (with a backup copy) and sets the default \"reprap\". Needs a confirmation.",
           confirm={"level": 3, "key": "password.clear"}),
        # keys of the external services (api_keys.py): only a DWC session manages them
        Op("keys.list", _keys_list, ADMIN, {},
           "Lists the access keys of external services (name, permissions, expiry, use; never the keys themselves), the presets and the classes.",
           log=False),
        Op("keys.create", _keys_create, ADMIN,
           {"name": a(S, True, desc="Name of the service that will use the key (unique)."),
            "preset": a(S, choices=list(api_keys.PRESETS), desc="Starting permissions (see keys.list); kinds and ops given replace the ones of the preset."),
            "kinds": a(L, desc="Operation classes allowed: read, write, motion, stop, power (admin can never be given)."),
            "ops": a(L, desc="Operation name patterns also allowed, for example light.*"),
            "deny": a(L, desc="Operation name patterns always refused, even if a class allows them."),
            "days": a(N, min=0, desc="Valid for this many days, up to 3650 (empty or 0: does not expire).")},
           "Creates an access key for an external service; the key is returned only once and goes in the X-Workshop-Key header. Needs a confirmation.",
           confirm={"level": 3, "key": "keys.create"}),
        Op("keys.update", _keys_update, ADMIN,
           {"id": a(S, True, desc="Id of the key (from keys.list)."), "name": a(S, desc="New name (unique)."),
            "kinds": a(L, desc="New list of allowed operation classes (replaces the old one)."),
            "ops": a(L, desc="New list of allowed operation patterns (replaces the old one)."),
            "deny": a(L, desc="New list of refused operation patterns (replaces the old one)."),
            "enabled": a(B, desc="false suspends the key without deleting it; true enables it again."),
            "days": a(N, min=0, desc="New validity in days from now, up to 3650; 0: never expires; not given: unchanged.")},
           "Changes the name, permissions, expiry or enabled state of a key; only the arguments given change."),
        Op("keys.revoke", _keys_revoke, ADMIN, {"id": a(S, True, desc="Id of the key (from keys.list).")},
           "Deletes a key for good: the service that used it stops working at once. Needs a confirmation.",
           confirm={"level": 3, "key": "keys.revoke"}),
        # PID of every zone
        Op("pid.status", H("pid_zones", {"S": "state"}), READ, {}, "Returns the progress of the PID tuning of the zones of a tool, zone by zone."),
        Op("pid.trace", _pid_trace, READ, {},
           "The record of the last PID tuning (M303), taken by the service while the heater is tuned: {trace: {heater, target, started_at, ended_at, points: [[seconds, temperature, power 0..1 or null], ...]} or null, running}."),
        Op("pid.start", _pid_start, WRITE,
           {"tool": a(I, True, min=0, desc="Tool number (the n of T<n>)."),
            "zones": a(O, True, desc="Every heater of the tool with its target: [{h: heater number, t: temperature in C}, ...].")},
           "Tunes the PID of every heater zone of a tool, one at a time with the others at working temperature (M568, M303): HEATS the tool and opens "
           "an active risk. Refused with a job or a heater faulted; switched off on any problem."),
        Op("pid.cancel", H("pid_zones", {"S": "cancel"}), STOP, {},
           "Cancels the zone tuning: the heaters of the tool are switched off and their previous temperatures put back. Never blocked.", exclusive=False),
        # big part wizard (writes files, never moves)
        Op("bigpart.read", H("big_piece", {"S": "read"}, {"data": "J"}), WRITE,
           {"data": a(O, True, desc="{archivo: path of the job file}. " + d_bigpart)},
           "Big part wizard: reads a job file and returns its summary; writes the drawing to 0:/sys/workshop/data/big-part.json. Never moves."),
        Op("bigpart.counts", H("big_piece", {"S": "counts"}, {"data": "J"}), READ,
           {"data": a(O, True, desc="{archivo, T: {giro, tx, ty} design to bed, area: {xmin, xmax, ymin, ymax}, hechas: [T of each part already cut]}.")},
           "Big part wizard: counts how the job splits into parts for the given placement and cutting area."),
        Op("bigpart.marks", H("big_piece", {"S": "marks"}, {"data": "J"}), WRITE,
           {"data": a(O, True, desc="{archivo, T, area, hechas, corr: [x, y] laser offset, pct: laser power 1-30 % (default 8), vel: feed 100-6000 (default 800)}.")},
           "Big part wizard: chooses where the registration crosses go and writes the job 0:/sys/workshop/gcodes/big-part-marks.gcode. Never moves."),
        Op("bigpart.part", H("big_piece", {"S": "part"}, {"data": "J"}), WRITE,
           {"data": a(O, True, desc="{archivo, T, area, hechas, corr: [x, y] laser offset, n: number of the part (default 1)}.")},
           "Big part wizard: writes the job of one part to 0:/sys/workshop/gcodes/big-part-piece.gcode. Never moves (the page starts the job)."),
        Op("bigpart.fit", H("big_piece", {"S": "adjust"}, {"data": "J"}), READ,
           {"data": a(O, True, desc="{diseno: [[x, y], ...] marks in the design, cama: [[x, y], ...] the same marks measured on the bed}.")},
           "Big part wizard: computes the rotation and offset of the material from the marks measured on the bed."),
        # G-code bridge
        Op("bridge.test", H("bridge_probe", {}, {"line": "C"}), READ,
           {"line": a(S, True, desc="BRIDGE HELP / STATUS / LIST / NAME or a query G-code of the bridge list (M114, M115, M119...).")},
           "Sends one query line to the G-code bridge through a short local connection and returns its answer; anything that moves is refused."),
        Op("bridge.service", H("bridge_service", {"S": "state"}), READ, {},
           "State of the G-code bridge unit of this Pi: installed, running, starts with the Pi, and if this service may start / stop it."),
        Op("bridge.service.set", H("bridge_service", {}, {"on": "S"}, value_map={"on": {True: "turnon", False: "poweroff"}}), WRITE,
           {"on": a(B, True, desc="true: start the bridge and make it start with the Pi (it survives a power cut); false: stop it and do not start it again.")},
           "Starts or stops the bridge of this Pi (systemctl through one sudoers rule limited to that unit). Stopping is refused while a live job is open."),
        # active risk (level 4)
        Op("risk.list", H("risk", {"S": "list"}), READ, {}, "Lists the active risks (level 4: the machine is without a protection), explicit and detected."),
        Op("risk.start", H("risk", {"S": "start"}, {"id": "I", "text": "T", "text_en": "E", "seconds": "D"}), WRITE,
           {"id": a(S, True, desc="Identifier of the risk, used to close it."),
            "text": a(S, desc="Text of the warning in Spanish, or the only text the caller has (default: the id)."),
            "text_en": a(S, desc="Text of the warning in English; the pages show the one of the DWC language (default: text)."),
            "seconds": a(I, min=1, max=86400, default=600, desc="Expires by itself after this many seconds (default 600; the service keeps it between 5 s and 6 h).")},
           "Opens or renews an active risk: the bar and the pages show a fixed warning and the strip paints the risk state until risk.end or the timeout.",
           macro=True),
        Op("risk.end", H("risk", {"S": "end"}, {"id": "I"}), WRITE, {"id": a(S, True, desc="Identifier given to risk.start.")},
           "Closes an explicit active risk.", macro=True),
        # live job
        Op("job.get", H("job", {"S": "query"}), READ, {}, "Returns the open live job (name, start, mode, last activity) and the idle timeout."),
        Op("job.start", interlocks.guarded(H("job", {"S": "start"}, {"name": "N"})), WRITE, {"name": a(S, desc="Name of the job (default: \"Live job\" in the language of DWC; the pages show that default name in their own language).")},
           "A live job starts (sent by an external program, not a file RRF sees): its start, mode, zone and energy are recorded; an open one is closed first. "
           "In Laser mode with a declared interlock (lid, extraction, key) that is not ok it fails with interlock_open.",
           macro=True),
        Op("job.end", H("job", {"S": "end"}), WRITE, {}, "The live job ended: it is closed and its duration and kWh are logged in Activity.", macro=True),
        Op("job.cancel", H("job", {"S": "cancel"}), WRITE, {}, "The live job was cancelled: it is closed as cancelled and logged in Activity.", macro=True),
        Op("job.close", H("job", {"S": "close"}), WRITE, {}, "Closes the open live job by hand; its duration ends at its last activity."),
        Op("job.timeout", H("job", {"S": "deadline"}, {"minutes": "D"}), WRITE,
           {"minutes": a(I, True, min=0, max=1440, desc="Minutes without activity, up to 1440; 0 = never.")},
           "Sets after how many minutes without activity an open live job closes by itself. Saved."),
        Op("movement.lock", H("job", {"S": "movement"}, {"mode": "M", "release_s": "L", "idle_s": "P"},
                              value_map={"mode": {"protected": "protegido", "duet": "duet"}}), WRITE,
           {"mode": a(S, choices=("protected", "duet"),
                      desc="protected = a live job or the G-code bridge block the movement (jog, Workbench, Vision...); duet = like Duet / DWC: only a file job blocks."),
            "release_s": a(I, min=3, max=120, desc="Seconds of quiet (no orders from the bridge, live job without activity) that free the movement in protected mode; default 20."),
            "idle_s": a(I, min=0, max=3600, desc="Seconds with the machine idle and no activity after which an open live job is closed by itself; 0 = not by this.")},
           "Sets how the movement is locked for everything (jog, Workbench, Vision, frame...). Saved. Without arguments it only reports."),
        # pages being looked at
        Op("view.heartbeat", _view, READ,
           {"topic": a(S, True, choices=("health", "power", "motors", "trace", "lights_board"),
                       desc="health (System health and Services pages), power (Consumption page), motors (Motors page), trace (job trace view) or lights_board (Lights page, Advanced tab).")},
           "Tells the service a page is visible (send every ~10 s): the pollers of that topic work at full speed; without heartbeats they sleep after ~30 s.",
           log=False),
        # single owner of the movement
        Op("motion.state", _motion_state, READ, {}, "Returns the state of the movement owner (what the machine is doing, reservations), the same as data.motion.",
           log=False),
        Op("motion.ask", _motion_ask, READ,
           {"origin": a(S, desc="Who asks (page or program name); default: the origin of the call."),
            "action": a(S, choices=("stop", "move", "job", "sequence", "geometry", "power", "channel"), default="move", desc="Class of the action (default move)."),
            "text": a(S, desc="Description of the action. Accepted but not used by the decision."),
            "token": a(S, desc="Token of the caller's own reservation, so it does not count against it.")},
           "Asks whether an origin may do a class of action now: allow, confirm or deny with the reason. Nothing is reserved; a confirmed call "
           "turns confirm into allow for 60 s."),
        Op("motion.reserve", _motion_reserve, MOTION,
           {"origin": a(S, True, desc="Who reserves (shown to the others as the reason)."),
            "action": a(S, choices=("move", "job", "sequence", "geometry"), default="sequence", desc="Class of what will be done (default sequence)."),
            "text": a(S, desc="Short description shown to the others while it lasts."),
            "seconds": a(I, min=1, max=900, default=30, desc="Duration, 1 to 900 seconds (default 30); renew it before it expires.")},
           "Reserves the machine for a sequence: other origins are denied until it ends. Answers a token (motion.renew, motion.release) or the refusal.",
           exclusive=False),
        Op("motion.take_over", _motion_take_over, MOTION,
           {"origin": a(S, True, desc="Who takes the control (shown to the others)."),
            "action": a(S, choices=("move", "job", "sequence", "geometry"), default="sequence", desc="Class of what will be done (default sequence)."),
            "text": a(S, desc="Short description shown to the others while it lasts."),
            "seconds": a(I, min=1, max=900, default=30, desc="Duration, 1 to 900 seconds (default 30); renew it before it expires.")},
           "Takes the control of the movement from the device or person that has it (technician or administrator). The previous owner is stopped and "
           "warned (data.motion.notice) and the call goes to the audit. During a file job, a live job or bridge activity only an administrator may. "
           "Answers a token like motion.reserve.", exclusive=False),
        Op("motion.renew", _motion_renew, MOTION,
           {"token": a(S, True, desc="Token returned by motion.reserve."),
            "seconds": a(I, min=1, max=900, default=30, desc="New duration from now, 1 to 900 seconds (default 30).")},
           "Extends a reservation that has not expired yet.", exclusive=False, log=False),
        Op("frame.start", interlocks.guarded(_frame_start, lambda x: x.get("mode") == "laser"), MOTION,
           {"points": a(L, True, desc="Corners of the frame as [[x, y], ...] in MACHINE coordinates of the head (G53), closed (the last point is the first); 2 to 400 points."),
            "mode": a(S, True, choices=("pointer", "laser"), desc="puntero: the machine moves with the laser off; laser: the laser is on at power_pct."),
            "power_pct": a(N, min=0, max=10, default=0, desc="Laser power in % (1 to 10), only with mode laser."),
            "repeat": a(I, min=0, max=10000, default=1, desc="Times it goes around: 1 = once (default), N = N times, 0 = until frame.stop.")},
           "Traces a frame with the machine WITHOUT making a job: the service sends short pieces and keeps little queued, so frame.stop works within about a second. "
           "Refused with a job, a live job or the jog moving; with the laser it needs Laser mode, X and Y homed and at most 10 %, "
           "and every declared interlock (lid, extraction, key) closed: error interlock_open otherwise."),
        Op("frame.stop", _frame_stop, STOP, {}, "Stops the frame in progress (never refused). The laser goes off; what was already queued on the board finishes (about a second).", exclusive=False),
        Op("frame.status", _frame_status, READ, {}, "State of the frame: active, mode, lap, how many laps, how it ended and the error if any.", log=False),
        Op("motion.release", _motion_release, MOTION, {"token": a(S, True, desc="Token returned by motion.reserve.")},
           "Ends a reservation so the others can move again.", exclusive=False),
    ] + profile_ops.ops() + config_package.ops() + startup_summary.ops() + work_state.ops() + interlocks.ops() + live_job_stop.ops() + machine_ops.ops() + trace_since.ops()


# ---- history of received calls ("Comandos recibidos") ----

LAST_MAX = 25
last = []
_SECRET_ARGS = {"password", "key", "pin", "old_pin", "new_pin", "token", "topic", "local_key"}


def _keys_store():
    st = _ctx.get("keys")
    if st is None:
        raise ApiError("internal", "the keys are not available in this installation")
    return st


def _keys_list(args, ctx):
    return {"keys": _keys_store().list(), "presets": api_keys.PRESETS, "kinds": list(api_keys.KINDS), "max": api_keys.MAX_KEYS}


def _key_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except api_keys.KeyError_ as e:
        raise ApiError("invalid_args", str(e))


def _keys_create(args, ctx):
    plain, rec = _key_call(_keys_store().create, args.get("name"), args.get("kinds"), args.get("ops"), args.get("deny"),
                           args.get("days"), args.get("preset"))
    _ctx["log_file"](f"api keys: created '{rec['name']}' ({rec['id']})")
    return {"key": plain, "record": rec, "note": "Copy the key now: it cannot be shown again. Send it in the header X-Workshop-Key."}


def _keys_update(args, ctx):
    return {"record": _key_call(_keys_store().update, args.get("id"), args.get("name"), args.get("kinds"), args.get("ops"),
                                args.get("deny"), args.get("enabled"), args.get("days"))}


def _keys_revoke(args, ctx):
    rec = _key_call(_keys_store().revoke, args.get("id"))
    _ctx["log_file"](f"api keys: revoked '{rec['name']}' ({rec['id']})")
    return {"revoked": rec}


def _masked(op, args):
    out = {}
    for k, v in (args or {}).items():
        if k in _SECRET_ARGS:
            out[k] = "***"
        elif isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False)
            out[k] = v if len(s) <= 120 else f"...({len(s)} bytes)"
        else:
            out[k] = v
    return out


def call_text(op, args):
    """How a call is shown in the history: op {"arg": value}."""
    m = _masked(op, args)
    return op + (" " + json.dumps(m, ensure_ascii=False, separators=(",", ":")) if m else "")


_VIA_LABEL = {wa.VIA_SESSION: "API (DWC session)", wa.VIA_OPEN: "API", wa.VIA_TOKEN: "API (local program)",
              wa.VIA_MACRO: "macro", wa.VIA_INTERNAL: "service"}


def record(op, args, ctx, ok, result, message, code, dur_ms, wait_ms):
    import db
    import origin_track
    raw_text = call_text(op, args)
    reg = _ctx["registry"]
    o = reg.ops.get(op) if reg else None
    reading = bool(o and o.kind == READ)
    if message is None and result is not None:
        try:
            response = json.dumps(result, ensure_ascii=False)[:300]
        except Exception:
            response = str(result)[:300]
    else:
        response = str(message or "")[:300]
    if op.startswith("meter."):
        response = "(hidden: meter data)"
    if op == "keys.create":
        response = "(hidden: the new key)"
    if op.startswith("auth.") or op.startswith("users."):
        response = "(hidden: sessions and PINs)"
    org = origin_track.describe_api(ctx, ok, message, code, dur_ms, wait_ms)
    origin_track.remember(org)
    via = _VIA_LABEL.get(ctx.get("via"), "API")
    if ctx.get("via") == wa.VIA_KEY and isinstance(ctx.get("key"), dict):
        via = "API (key: %s)" % ctx["key"].get("name")
    last.insert(0, {"hour": time.strftime("%H:%M:%S"), "origin": org, "code": raw_text[:160], "ok": bool(ok),
                       "response": response, "ms": dur_ms, "via": via, "reading": reading})
    del last[LAST_MAX:]
    bridge = _ctx["bridge"]
    if bridge is not None:
        bridge.set_status("lastCommands", list(last))
    try:
        who, role = audit.actor(ctx)
        db.command_insert(time.strftime("%Y-%m-%dT%H:%M:%S"), op, raw_text[:400], ok, dur_ms, response[:1000], via, reading, org, who, role)
    except Exception as e:
        _ctx["log_file"](f"could not save the call in the history: {e}")
    audit.record(op, o.kind if o else "", args, ctx, ok, code, message, _ctx["log_file"])


def record_denied(op, args, ctx, body):
    """Refusal (403) of an operation that is not logged (the jog...): only the audit keeps it."""
    err = (body or {}).get("error") or {}
    audit.record(op.name, op.kind, args, ctx, False, err.get("code"), err.get("message"), _ctx["log_file"])


def current_mode():
    """Mode of the machine now in lower case ("laser", "cnc", "fff") or None."""
    try:
        import machine_state
        m = machine_state.last_state() or {}
        v = (m.get("global") or {}).get("selectedMode") or (m.get("state") or {}).get("machineMode")
        return str(v).strip().lower() if v else None
    except Exception:
        return None


# ---- start ----

def migrate_token(token_file, legacy_file, log=print):
    """Moves the local key from the old SD file to token_file: the same key (the programs that already hold it keep working), then the SD copy
    is removed. Logs once, only when it did something. Returns True when a legacy file was found."""
    if not legacy_file or not os.path.isfile(legacy_file):
        return False
    try:
        with open(legacy_file, encoding="utf-8") as f:
            old = f.read().strip()
    except OSError as e:
        log(f"api: could not read the old local key file ({e})")
        return True
    try:
        if len(old) >= 32 and not os.path.isfile(token_file):
            os.makedirs(os.path.dirname(token_file), exist_ok=True)
            tmp = token_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(old + "\n")
            try:
                os.chmod(tmp, 0o640)
            except OSError:
                pass
            os.replace(tmp, token_file)
        os.remove(legacy_file)
        log("api: the local key moved out of the SD card to " + token_file + " (the SD copy was removed)")
    except OSError as e:
        log(f"api: could not move the local key off the SD ({e}); the old file stays")
    return True


def init(bridge, config, plugin_id, version="", log=print, log_file=print, token_file=TOKEN_FILE, keys_file=KEYS_FILE, users_file=users.USERS_FILE,
         legacy_token_file=LEGACY_TOKEN_FILE):
    """Builds the registry of the service. Does not open any connection."""
    _ctx.update(bridge=bridge, config=config, log=log, log_file=log_file)
    reg = identity.AuthRegistry(plugin_id, version, log_file)
    for op in _ops() + settings_ops.build(_ctx) + api_users.make_ops(lambda: _ctx.get("users")):
        reg.add(op)
    _ctx["users"] = reg.users = users.UserStore(users_file, log=log_file) if users_file else None
    camera_access.bind(lambda: _ctx.get("users"))  # the camera relay (:8090) applies the same roles
    reg.mode_of = current_mode
    reg.on_denied = record_denied
    reg.confirm_texts = CONFIRM_TEXTS
    reg.motion_check = motion_check
    reg.on_call = record
    _ctx["registry"] = reg
    if keys_file:
        _ctx["keys"] = api_keys.KeyStore(keys_file, log=log_file)
        reg.key_lookup = _ctx["keys"].lookup
    if token_file:
        migrate_token(token_file, legacy_token_file, log_file)
        reg.load_token(token_file)
    return reg


def call(op, args=None, origin="service", via=wa.VIA_INTERNAL, confirm=False):
    """Run an operation from inside the service (or a test). Returns the body dict."""
    reg = _ctx["registry"]
    if reg is None:
        raise RuntimeError("api_ops.init() was not called")
    return reg.call(op, args, {"via": via, "origin": origin, "confirm": confirm})[1]


def http_info(headers, session):
    import origin_track
    info = origin_track.http_info_headers(headers, session)
    info.update(identity.http_identity(headers, _ctx.get("users")))  # who (session token) and from which browser (device id)
    return info

