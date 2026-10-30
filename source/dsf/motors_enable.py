"""
Enable / disable motors from the Motors page (2026-10-12, request: "in
motors I want to be able to control whether I disable one motor or several
or all"). Pure logic (no dsf or network) so it can be tested on the PC; the
handler handlers/motors.py uses it with the real object model.

What RepRapFirmware 3.6 allows (docs.duet3d.com, G-code M17/M18/M84/
M906/M569, and the RRF 3.6 code: GCodes2.cpp case 17/18/84, Move2.cpp
EnableDrivers/DisableDrivers/SetDriversIdle):

- M18 <axes> E<n:m>: disables ALL the drivers of each named axis or
  extruder (local and CAN). Each disabled axis is left WITHOUT HOMING
  (SetAxisNotHomed). Extruders have no homing.
- M18 without parameters: all axes and extruders, and all without homing.
- M17 <axes> E<n>: enables (RRF 3.3 or newer). It does not give the homing back.
  M17 without parameters: all.
- There is no command for ONE driver of an axis with several motors (e.g. only
  0.4 of Z): RRF keeps the state per axis/extruder and M18 Z turns off 0.4 and
  0.5 together. M569 P<driver> R-1 ("always disabled") turns it off once,
  but on the 6HC the driver is enabled again with the axis's next
  move (the TMCs are enabled through CHOPCONF, not through the enable
  pin), and it also stops watching its faults and changes the configuration
  until restart: it is NOT used.
- Any move of an axis (jog, homing, job) enables its motors again by itself
  (DDA.cpp EnableDrivers).
- M84 is "deprecated" in 3.6 (it is the same as M18). M84 S / M906 T set the
  idle time: after that time the motors are NOT disabled, they drop to the
  idle current M906 I (30 % by default). Only with M906 I0 does the idle
  disable them and remove the homing of all axes.

"""
import job_states
import re
from messages import M, J, B

# state.status with a job in progress / states in which nothing is touched
WITH_JOB = job_states.ACTIVE
BUSY = ("busy", "changingTool", "starting", "updating", "halted", "flashing", "disconnected")

ALL = ("", "all", "all", "*")


def block(status, job_in_live=None):
    """None if possible, or the reason (text for the page)."""
    st = ((status or {}).get("state") or {}).get("status") or ""
    if job_in_live:
        is_active = job_in_live.get("active") if isinstance(job_in_live, dict) else bool(job_in_live)
        if is_active:
            return M("motors_enable_live_job_running_finish_or_close")
    if st in WITH_JOB:
        file = (((status or {}).get("job") or {}).get("file") or {}).get("fileName") or ""
        label = file.rsplit("/", 1)[-1]
        return M("motors_enable_job_running_named_position_lost", label=label) if label else M("motors_enable_job_running_position_lost")
    if st in BUSY:
        return M("motors_enable_machine_busy_wait_finish", st=st)
    return None


def _letter_gcode(letter):
    """RRF 3.6 accepts lowercase axis letters: in G-code they go with a ' in front."""
    return ("'" + letter) if letter.islower() else letter


def targets(status, entries):
    """Requested list ("X,Z,E0" or "all") -> (axes, extruders, error).
    axes: letters as they are in move.axes; extruders: indices. All -> (None, None, None)."""
    raw_text = str(entries or "").strip()
    if raw_text.lower() in ALL:
        return None, None, None
    move = (status or {}).get("move") or {}
    letters = [str(a.get("letter") or "") for a in (move.get("axes") or []) if a]
    n_ext = len(move.get("extruders") or [])
    axes, exts = [], []
    for part in [p for p in re.split(r"[\s,;]+", raw_text) if p]:
        m = re.fullmatch(r"[Ee](\d+)", part)
        if m and part not in letters:
            i = int(m.group(1))
            if i >= n_ext:
                return None, None, M("motors_enable_extruder_does_not_exist", i=i)
            if i not in exts:
                exts.append(i)
            continue
        p = part.lstrip("'")
        if p in letters:
            letter = p
        else:
            equal = [x for x in letters if x.upper() == p.upper()]
            if len(equal) != 1:
                return None, None, M("motors_enable_axis_does_not_exist", axis=part)
            letter = equal[0]
        if letter not in axes:
            axes.append(letter)
    if not axes and not exts:
        return None, None, M("motors_enable_no_motor_chosen")
    return axes, exts, None


def command(action, axes, extruders):
    """action 'disable' | 'enable'; axes/extruders None = all."""
    base = "M18" if action == "disable" else "M17"
    if axes is None and extruders is None:
        return base
    parts = [_letter_gcode(e) for e in (axes or [])]
    if extruders:
        parts.append("E" + ":".join(str(i) for i in extruders))
    return base + " " + " ".join(parts)


ACTIONS = {
    "disable": "disable", "deshabilitar": "disable", "off": "disable",
    "enable": "enable", "on": "enable",
    "reread": "reread", "releer": "reread",
    "watch": "watch", "mirar": "watch",
}


def plan(status, action, entries, job_in_live=None):
    """What to send. Returns dict {ok, accion, comando, ejes, extrusores,
    todos, error}. ok False -> error explains why (block or bad request)."""
    acc = ACTIONS.get(str(action or "").strip().lower())
    r = {"ok": False, "action": acc, "command": None, "axes": [], "extruders": [], "all": False, "error": None}
    if acc not in ("disable", "enable"):
        r["error"] = M("motors_enable_unknown_action_use_disable_enable")
        return r
    reason = block(status, job_in_live)
    if reason:
        r["error"] = reason
        return r
    axes, exts, err = targets(status, entries)
    if err:
        r["error"] = err
        return r
    r["all"] = axes is None and exts is None
    r["axes"] = axes or []
    r["extruders"] = exts or []
    r["command"] = command(acc, axes, exts)
    r["ok"] = True
    return r


def description(r):
    """Text for Activity."""
    that = M("motors_all") if r["all"] else J(
        [M("motors_axis", axis=e) for e in r["axes"]] + [M("motors_extruder", n=i) for i in r["extruders"]])
    return M("motors_disabled" if r["action"] == "disable" else "motors_enabled", what=that, command=r["command"])
