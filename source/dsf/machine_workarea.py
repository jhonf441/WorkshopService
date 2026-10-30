"""Work area of the machine (Machine v2, 2026-10-28): `machine.workarea.*`.

The usable area of each mode (where the pointer or the tool may work) was a card of the Workbench (Zones > Cut area, `24-cut-area*.js`); like the
height calibration it is a calibration of the MACHINE, so it lives in Machine now. The data and the macros did not change:

    0:/sys/workshop/zones/cutarea.g   per mode `global.cutArea<Mode> = {Xmin, Xmax, Ymin, Ymax}` (bed coordinates = where the POINTER lands) or
                                      null. Loaded by workplaces.g at start-up; saveworkplace.g, cutguard.g, the Workbench map and the laser editor READ it
    0:/sys/workshop/macros/handfree.g | handcorner.g | gotobed.g | framecutarea.g
                                      the movements of the corner assistants: still macros of the SD (shipped by the Workbench package, like the
                                      zcal-*.g of the height calibration)

Operations:
    machine.workarea.get    (operator, read)  the areas of the three modes, the travel of X and Y, the mode in use and which macros are on the SD
    machine.workarea.save   (technician)      one mode: a rectangle (checked like the old card did) or `remove`; the other modes are kept as they are;
                                              the file is written with a copy of the previous one and reloaded now when no job runs
    machine.workarea.release (technician, motion, level 4 confirmation)  X and Y motors off so the pointer can be taken to a corner by hand
    machine.workarea.step   (technician, motion, level 3 confirmation)  one step of the assistants: capture the corner at the end stops, take the pointer to a bed
                                              point, walk the saved area with the pointer

Every G-code line is a template of machine_gcode.py (area_*). A step reserves the movement like machine.height.step: refused while a job runs or somebody
else holds the machine. The pointer walks with the laser off (the macros send S0); framing WITH the laser is not here.
"""
import fs_atomic
import job_states
import os
import re
import threading
import time

import audit
import identity
import machine_geometry as geo
import machine_gcode
import machine_parsers as parsers
import motion_owner
import sd_paths
from messages import M
from workshop_api import ApiError, Arg, MOTION, READ, WRITE, Op

MODES = ("Laser", "CNC", "FFF")
EDIT_MODES = MODES                    # all three: workplaces.g / saveworkplace.g / framecutarea.g only READ the area, FFF included (nobody else writes it)
CUTAREA_G = "sys/workshop/zones/cutarea.g"
MIN_MM = 10.0                         # an area smaller than this is almost surely a capture error
TRAVEL_TOL = 0.001
MACROS = {"release": "sys/workshop/macros/handfree.g", "capture": "sys/workshop/macros/handcorner.g", "goto": "sys/workshop/macros/gotobed.g",
          "frame": "sys/workshop/macros/framecutarea.g"}
RESERVE_S = 120                       # the corner measurement walks to the end stops twice
JOB_STATES = job_states.ACTIVE_OR_TOOL_CHANGE
KEYS = ("xmin", "xmax", "ymin", "ymax")
_busy = threading.Lock()


def _mo():
    import machine_ops
    return machine_ops


def _bad(field, reason="bad_value"):
    return ApiError("invalid_args", M("machine_workarea_bad_value", field=field), field=field, reason=reason)


# ---- the file ----

def _read_text(rel):
    try:
        with open(sd_paths.sd(rel), "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return None


def _write_text(rel, text):
    fs_atomic.write_text(sd_paths.sd(rel), text)


_SET_RE = re.compile(r"^\s*set\s+global\.cutArea(\w+)\s*=\s*(null|\{[^}]*\})\s*$", re.I)


def parse(text):
    """{mode: {"xmin", "xmax", "ymin", "ymax"} | None} for every mode the file sets (never raises: what cannot be read is None)."""
    out = {}
    for line in (text or "").splitlines():
        m = _SET_RE.match(line.split(";", 1)[0])
        if not m:
            continue
        mode, value = m.group(1), m.group(2)
        if value.lower() == "null":
            out[mode] = None
            continue
        try:
            nums = [float(v) for v in value.strip("{} ").split(",")]
        except ValueError:
            out[mode] = None
            continue
        out[mode] = dict(zip(KEYS, nums)) if len(nums) == 4 else None
    return out


def _fmt(rect):
    return "{" + ", ".join("%.2f" % rect[k] for k in KEYS) + "}" if rect else "null"


def render(areas, mode, rect, stamp):
    """Text of cutarea.g: every mode of `areas` as it was, `mode` with the new rectangle (None = removed). Same lines the Workbench wrote."""
    vals = {m: areas.get(m) for m in MODES}
    vals[mode] = rect
    txt = ("; cutarea.g -- usable CUT AREA per mode, in BED coordinates (= position\n"
           "; of the POINTER, the same that the zones sys/workshop/zones/p<N>.g store).\n"
           "; Format {Xmin, Xmax, Ymin, Ymax}; null = not measured. Written by WorkshopService\n"
           "; (Machine > Work area) and loaded by sys/workshop/macros/workplaces.g.\n"
           "; sys/workshop/macros/saveworkplace.g uses it to never save an origin outside.\n"
           "; Last change: mode %s%s, %s\n" % (mode, "" if rect else " (removed)", stamp))
    for m in MODES:
        txt += "if !exists(global.cutArea%s)\n    global cutArea%s = null\nset global.cutArea%s = %s\n" % (m, m, m, _fmt(vals[m]))
    return txt


def areas_now(om):
    """The areas: the file is the truth (the model keeps what the last M98 loaded); the model fills a mode the file does not set."""
    out = {m: None for m in MODES}
    g = ((om or {}).get("global") or {})
    for m in MODES:
        v = g.get("cutArea" + m)
        if isinstance(v, list) and len(v) == 4 and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in v):
            out[m] = dict(zip(KEYS, [float(n) for n in v]))
    for m, rect in parse(_read_text(CUTAREA_G)).items():
        if m in out:
            out[m] = rect
    return out


# ---- the rectangle ----

def problems(rect, lim):
    """Codes of what is wrong with a rectangle (pure; empty = it can be saved). lim = travel of X and Y {"xmin"...} or None."""
    if not isinstance(rect, dict) or not all(isinstance(rect.get(k), (int, float)) and not isinstance(rect.get(k), bool) and rect.get(k) == rect.get(k)
                                             for k in KEYS):
        return ["not_numbers"]
    out = []
    if rect["xmax"] - rect["xmin"] < MIN_MM or rect["ymax"] - rect["ymin"] < MIN_MM:
        out.append("too_small")
    if lim and (rect["xmin"] < lim["xmin"] - TRAVEL_TOL or rect["xmax"] > lim["xmax"] + TRAVEL_TOL
                or rect["ymin"] < lim["ymin"] - TRAVEL_TOL or rect["ymax"] > lim["ymax"] + TRAVEL_TOL):
        out.append("outside_travel")
    return out


def _clean_rect(raw):
    if not isinstance(raw, dict):
        raise _bad("rect")
    out = {}
    for k in KEYS:
        v = raw.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not -5000 <= v <= 5000:
            raise _bad("rect." + k)
        out[k] = round(float(v), 2)
    return out


def _mode_of(om):
    g = ((om or {}).get("global") or {}).get("selectedMode")
    mode = g if g in MODES else ((om or {}).get("state") or {}).get("machineMode")
    return mode if mode in MODES else None


def macros_present():
    return {k: _read_text(v) is not None for k, v in MACROS.items()}


# ---- reads ----

def _state(args, ctx):
    om = _mo().model()
    lim = geo.limits(om)
    ax = geo.axes_by_letter(om)
    return {
        "mode": _mode_of(om), "areas": areas_now(om), "edit_modes": list(EDIT_MODES), "min_mm": MIN_MM,
        "reach": None if not lim else {k: lim[k] for k in KEYS}, "macros": macros_present(), "file": _read_text(CUTAREA_G) is not None,
        "homed": {k: bool((ax.get(k) or {}).get("homed")) for k in "XY"},
    }


# ---- save ----

def _job_running(om):
    return str(((om or {}).get("state") or {}).get("status") or "") in JOB_STATES


def _reload(om):
    """M98 of cutarea.g so the new area works now. Not while a job runs (the cut guards read it)."""
    if _job_running(om):
        return False, "job_running"
    mo = _mo()
    conn = None
    try:
        conn = mo.open_connection()
        conn.perform_simple_code(machine_gcode.render("area_reload"), channel=mo.channel(), async_exec=False)
        return True, ""
    except Exception as e:  # noqa: BLE001 - the file is saved: it loads at the next mode change
        return False, "no_connection:" + str(e)[:80]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _save(args, ctx):
    mode = args.get("mode")
    if mode not in EDIT_MODES:
        raise _bad("mode")
    om = _mo().model()
    if args.get("rect") is None:
        if args.get("remove") is not True:
            raise _bad("rect", "rect_or_remove")
        rect = None
    else:
        rect = _clean_rect(args["rect"])
        bad = problems(rect, geo.limits(om))
        if bad:
            raise ApiError("invalid_args", M("machine_workarea_bad_rect_" + bad[0]), field="rect", reason=bad[0], problems=bad)
    areas = areas_now(om)
    old = _read_text(CUTAREA_G)
    if old is not None:
        _write_text(CUTAREA_G + ".bak", old)
    _write_text(CUTAREA_G, render(areas, mode, rect, time.strftime("%Y-%m-%d %H:%M")))
    applied, why = _reload(om)
    audit.event("machine.workarea.saved", {"mode": mode, "rect": rect}, identity.actor(ctx))
    areas[mode] = rect
    return {"mode": mode, "areas": areas, "applied": applied, "apply_reason": why}


# ---- the steps of the assistants ----

def refusal(om, action, macros, areas):
    """Code of the first reason the step must not run, or None. Pure."""
    if not om:
        return "no_model"
    if not macros.get(action):
        return "macro_missing"
    ax = geo.axes_by_letter(om)
    homed = lambda *letters: all((ax.get(k) or {}).get("homed") for k in letters)    # noqa: E731
    if action in ("goto", "frame") and not homed("X", "Y"):
        return "not_homed"
    if action == "frame":
        mode = _mode_of(om)
        if mode is None:
            return "no_mode"
        if not areas.get(mode):
            return "no_area"
    return None


def _step_args(action, args, om):
    if action != "goto":
        return {}
    lim = geo.limits(om)
    out = {}
    for k in ("x", "y"):
        v = args.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not -5000 <= v <= 5000:
            raise _bad(k)
        out[k] = round(float(v), 2)
    if lim and not (lim["xmin"] - TRAVEL_TOL <= out["x"] <= lim["xmax"] + TRAVEL_TOL and lim["ymin"] - TRAVEL_TOL <= out["y"] <= lim["ymax"] + TRAVEL_TOL):
        raise _bad("x", "outside_travel")
    return out


def _send(conn, chan, template, **numbers):
    return str(conn.perform_simple_code(machine_gcode.render(template, **numbers), channel=chan, async_exec=False) or "")


def _cleanup(conn, chan):
    if conn is None:
        return
    try:
        _send(conn, chan, "wait_moves")
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def _run_step(conn, chan, action, v):
    if action == "release":
        _send(conn, chan, "area_release")
        return {}
    if action == "capture":
        errors = parsers.find_errors(_send(conn, chan, "area_capture"))
        if errors:
            raise ApiError("failed", M("machine_workarea_capture_failed"), reason="capture_failed", detail=errors[0]["text"][:200])
        x = parsers.parse_number_result(_send(conn, chan, "area_corner_x"))
        y = parsers.parse_number_result(_send(conn, chan, "area_corner_y"))
        if x is None or y is None:
            raise ApiError("failed", M("machine_workarea_no_reading"), reason="no_reading")
        return {"x": round(x, 2), "y": round(y, 2)}
    if action == "goto":
        _send(conn, chan, "area_goto", x=v["x"], y=v["y"])
        return {}
    _send(conn, chan, "area_frame")
    return {}


def _step(args, ctx):
    mo = _mo()
    action = args.get("action")
    if action not in MACROS:
        raise _bad("action")
    om = mo.model()
    v = _step_args(action, args, om)
    why = refusal(om, action, macros_present(), areas_now(om))
    if why:
        raise ApiError("refused", M("machine_workarea_refuse_" + why), reason=why)
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])
    if not _busy.acquire(blocking=False):
        raise ApiError("refused", M("machine_workarea_busy"), reason="busy_step")
    who = identity.actor(ctx)
    bridge = mo._bridge()
    d = motion_owner.reserve(bridge, mo.ORIGIN, "sequence", "workarea_" + action, RESERVE_S, actor=who)
    if d.get("decision") != "allow":
        _busy.release()
        raise ApiError("motion_denied", d.get("reason") or "", motion={"decision": "deny", "code": d.get("code")})
    conn = chan = None
    try:
        conn, chan = mo.open_connection(), mo.channel()
        _send(conn, chan, "wait_moves")
        out = _run_step(conn, chan, action, v)
        _send(conn, chan, "wait_moves")
        audit.event("machine.workarea.step", {"action": action}, who)
        return dict(out, action=action)
    finally:
        _cleanup(conn, chan)
        try:
            motion_owner.release(bridge, d["token"], actor=who)
        finally:
            _busy.release()


def _release(args, ctx):
    return _step({"action": "release"}, ctx)


def ops():
    a = Arg
    N = "num"
    return [
        Op("machine.workarea.get", _state, READ, {}, "The work area of each mode (Laser, CNC, FFF; null = not measured) read from cutarea.g, the travel of X and Y, "
           "the mode in use, which of the corner macros are on the SD and whether X and Y are homed.", log=False),
        Op("machine.workarea.save", _save, WRITE, {
            "mode": a("str", True, choices=EDIT_MODES, desc="Laser, CNC or FFF."),
            "rect": a("obj", False, desc="{xmin, xmax, ymin, ymax} in bed coordinates (where the pointer lands): at least 10 mm each way, inside the travel of X and Y."),
            "remove": a("bool", False, desc="true with no rect: the mode goes back to not measured.")},
           "Saves the area of one mode (the others stay as they are), keeps a copy of the previous cutarea.g and loads it now when no job runs."),
        Op("machine.workarea.step", _step, MOTION, {
            "action": a("str", True, choices=("capture", "goto", "frame"), desc="capture: measure the corner at the end stops and answer {x, y}; goto: the "
                                                                                  "pointer over X Y (laser off); frame: walk the saved area of the mode in use "
                                                                                  "with the pointer."),
            "x": a(N, min=-5000, max=5000, desc="goto: bed X."), "y": a(N, min=-5000, max=5000, desc="goto: bed Y.")},
           "One step of the corner assistants: reserves the movement (refused during a job) and runs the macro handcorner.g / gotobed.g / framecutarea.g "
           "(the pointer, never the laser: S0). Level 3 confirmation: the machine moves by itself.", confirm={"level": 3, "key": "workarea.step"},
           motion="sequence", exclusive=False),
        Op("machine.workarea.release", _release, MOTION, {},
           "Releases the X and Y motors (macro handfree.g; Z stays firm) so the pointer can be taken to a corner by hand. The position is lost until the "
           "next homing. Level 4 confirmation.", confirm={"level": 4, "key": "workarea.release"}, motion="sequence", exclusive=False),
    ]


def reset():
    """For the tests."""
    if _busy.locked():
        _busy.release()
