"""Height calibration of the tool (Machine v2, 2026-10-22): `machine.height.*`.

It was a card of the Workbench (Zones > Active zone > Z height > Calibrate, `34-zcal.js`); the owner asked why a calibration of the machine
lived in the bed map and not in Machine. The data and the macros did not change:

    0:/sys/workshop/config/zcal.json      settings store name `zcal` (revisioned): per mode {general: {method, setting}, k0, szp} and the paper
    0:/sys/workshop/macros/zcal.g         GENERATED from the json on every save: G31 K0 / M558.2 K1 of the calibrated mode and
                                          global.workshopZAdj (fine adjustment, read by zsurface.g after each G30). The mode files call it
    0:/sys/workshop/macros/zcal-*.g       goto / mark / probe / szp: the movements of the assistants, still macros of the SD

Operations:
    machine.height.get    (operator, read)  what is saved, the hooks of the mode files, the probes of the object model, what the assistant may do now
    machine.height.save   (technician)      changes of the saved calibration with the revision it is based on; rewrites zcal.g and applies it now
    machine.height.hook   (technician)      adds the `M98 zcal.g` line to the mode files that lack it (a copy of each file first)
    machine.height.step   (technician, motion)  one step of the assistants: goto, jog (Z only), mark (paper), measure (BLTouch), szp (FFF)

Every G-code line is a template of machine_gcode.py. A step reserves the movement like machine.mark_cross, so it is refused while a job runs
or somebody else holds the machine.
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
import settings_store
from messages import M
from workshop_api import ApiError, Arg, MOTION, READ, WRITE, Op

NAME = "zcal"
MODES = ("Laser", "CNC", "FFF")
MODE_FILES = {"Laser": "sys/modelaser.g", "CNC": "sys/modecnc.g", "FFF": "sys/modefff.g"}
ZCAL_G = "sys/workshop/macros/zcal.g"
HOOK_RE = re.compile(r"(?:taller|workshop/macros)/zcal\.g")
HOOK_LINE = '\n; Height calibration per mode (Machine > Height)\nM98 P"0:/sys/workshop/macros/zcal.g"\n'
MACROS = {"goto": "sys/workshop/macros/zcal-goto.g", "mark": "sys/workshop/macros/zcal-mark.g", "probe": "sys/workshop/macros/zcal-probe.g",
          "szp": "sys/workshop/macros/zcal-szp.g"}
METHODS = ("bltouch", "paper", "szp")
ADJUST_MAX = 3.0
PAPER_MAX = 3.0
JOG_STEPS = (-5, -1, -0.1, -0.05, 0.05, 0.1, 1, 5)
MARK_HEIGHT = (1.0, 60.0)
MEASURED = (0.0, 20.0)          # a trigger height outside this is a reading that failed
RESERVE_S = 30
_busy = threading.Lock()


def _mo():
    import machine_ops
    return machine_ops


def _bad(field):
    return ApiError("invalid_args", M("machine_height_bad_value", field=field), field=field, reason="bad_value")


# ---- the saved calibration ----

def _number(v, lo, hi, field, places=3):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        raise _bad(field)
    return round(float(v), places)


def normalize(raw):
    """The calibration as the page and zcal.g use it (never raises: what cannot be understood goes back to the defaults)."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        paper = _number(raw.get("paper", 0.1), 0, PAPER_MAX, "paper")
    except ApiError:
        paper = 0.1
    modes = {}
    for m in MODES:
        src = (raw.get("modes") or {}).get(m)
        if not isinstance(src, dict):
            continue
        gen = src.get("general") if isinstance(src.get("general"), dict) else {}
        method = gen.get("method") if gen.get("method") in METHODS else "bltouch"
        try:
            setting = _number(gen.get("setting", 0), -ADJUST_MAX, ADJUST_MAX, "setting")
        except ApiError:
            setting = 0.0
        # one calibration per mode: what the old card kept per zone (own / method / setting) is dropped, as it did when it saved
        modes[m] = {"general": {"method": method, "setting": setting}, "k0": _k0(src.get("k0")), "szp": _szp(src.get("szp")),
                    "method": {}, "setting": {}, "own": {}}
    return {"version": 1, "paper": paper, "modes": modes}


def _k0(v):
    if not isinstance(v, dict):
        return None
    try:
        return {"p": int(_number(v.get("p", 500), 0, 1023, "k0.p", 0)), "x": _number(v.get("x", 0), -500, 500, "k0.x"),
                "y": _number(v.get("y", 0), -500, 500, "k0.y"), "z": _number(v["z"], -20, 100, "k0.z"), "date": str(v.get("date") or "")[:10]}
    except (ApiError, KeyError):
        return None


def _szp(v):
    if not isinstance(v, dict):
        return None
    try:
        return {"s": int(_number(v["s"], 1, 31, "szp.s", 0)), "r": int(_number(v["r"], -2000000000, 2000000000, "szp.r", 0)), "date": str(v.get("date") or "")[:10]}
    except (ApiError, KeyError):
        return None


def generate_g(data, stamp):
    """Text of sys/workshop/macros/zcal.g from the calibration (the same file the Workbench wrote before)."""
    lines = [
        "; zcal.g -- height calibration per mode. GENERATED by the service (Machine > Height) on " + stamp + ". Do not edit by hand:",
        "; it is rewritten on every save. The mode files (modelaser.g / modecnc.g / modefff.g) call it at the end, after their own G31.",
        "var zcMode = exists(global.selectedMode) ? global.selectedMode : state.machineMode",
        "if !exists(global.workshopZAdj)",
        "    global workshopZAdj = {0, 0, 0, 0, 0, 0, 0, 0, 0}",
    ]
    first = True
    for m in MODES:
        o = data["modes"].get(m)
        if not o:
            continue
        lines.append(("if" if first else "elif") + ' var.zcMode == "%s"' % m)
        first = False
        k0 = o["k0"]
        if k0:
            lines.append("    G31 K0 P%d X%s Y%s Z%s   ; BLTouch calibrated on %s" % (k0["p"], _t(k0["x"]), _t(k0["y"]), _t(k0["z"]), k0["date"] or "?"))
        szp = o["szp"]
        if m == "FFF" and szp:
            lines.append("    M558.2 K1 S%d R%d   ; SZP calibrated on %s" % (szp["s"], szp["r"], szp["date"] or "?"))
        a = _t(o["general"]["setting"])
        lines.append("    set global.workshopZAdj = {%s}   ; fine adjustment (G54..G59.3; general %s)" % (", ".join([a] * 9), a))
    if first:
        lines.append("set global.workshopZAdj = {0, 0, 0, 0, 0, 0, 0, 0, 0}")
    else:
        lines += ["else", "    set global.workshopZAdj = {0, 0, 0, 0, 0, 0, 0, 0, 0}"]
    return "\n".join(lines) + "\n"


def _t(v):
    return machine_gcode.num_text(v)


def apply_changes(current, changes):
    """The calibration `current` with `changes` {paper?, modes: {mode: {method?, setting?, k0?, szp?}}} on top. Raises invalid_args."""
    if not isinstance(changes, dict) or not changes:
        raise _bad("changes")
    out = normalize(current)
    if "paper" in changes:
        out["paper"] = _number(changes["paper"], 0, PAPER_MAX, "paper")
    for m, ch in (changes.get("modes") or {}).items():
        if m not in MODES or not isinstance(ch, dict):
            raise _bad("modes")
        o = out["modes"].setdefault(m, {"general": {"method": "bltouch", "setting": 0.0}, "k0": None, "szp": None, "method": {}, "setting": {}, "own": {}})
        if "method" in ch:
            if ch["method"] not in METHODS or (ch["method"] == "szp" and m != "FFF"):
                raise _bad("method")
            o["general"]["method"] = ch["method"]
        if "setting" in ch:
            o["general"]["setting"] = _number(ch["setting"], -ADJUST_MAX, ADJUST_MAX, "setting")
        if "k0" in ch:
            o["k0"] = None if ch["k0"] is None else _strict(_k0, ch["k0"], "k0")
        if "szp" in ch:
            if m != "FFF" and ch["szp"] is not None:
                raise _bad("szp")
            o["szp"] = None if ch["szp"] is None else _strict(_szp, ch["szp"], "szp")
    return out


def _strict(fn, v, field):
    out = fn(v)
    if out is None:
        raise _bad(field)
    return out


# ---- files of the SD ----

def _read_text(rel):
    try:
        with open(sd_paths.sd(rel), "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return None


def _write_text(rel, text):
    fs_atomic.write_text(sd_paths.sd(rel), text)


def _stamp():
    return time.strftime("%Y%m%d%H%M%S")


def hooks():
    """{mode: True (the mode file calls zcal.g) / False / None (that mode has no file on this machine)}."""
    out = {}
    for m in MODES:
        t = _read_text(MODE_FILES[m])
        out[m] = None if t is None else bool(HOOK_RE.search(t))
    return out


def macros_present():
    return {k: _read_text(v) is not None for k, v in MACROS.items()}


# ---- reads ----

def _probes(om):
    out = []
    for i, p in enumerate(((om or {}).get("sensors") or {}).get("probes") or []):
        if not isinstance(p, dict) or p.get("type") in (None, 0):
            continue
        ox, oy = geo.offsets_of(p)
        out.append({"index": i, "type": p.get("type") if isinstance(p.get("type"), int) else None, "trigger_height": geo.rnd(geo.num(p.get("triggerHeight"))),
                    "threshold": geo.num(p.get("threshold")), "offset_x": geo.rnd(ox), "offset_y": geo.rnd(oy)})
    return out


def _mode_of(om):
    g = ((om or {}).get("global") or {}).get("selectedMode")
    mode = g if g in MODES else ((om or {}).get("state") or {}).get("machineMode")
    return mode if mode in MODES else None


def _state(args, ctx):
    mo = _mo()
    om = mo.model()
    cur = settings_store.get(NAME)
    ax = geo.axes_by_letter(om)
    lim = geo.limits(om)
    return {
        "mode": _mode_of(om), "rev": cur["rev"], "data": normalize(cur["value"]), "hooks": hooks(), "applied": _read_text(ZCAL_G) is not None,
        "probes": _probes(om), "macros": macros_present(),
        "homed": {k: bool((ax.get(k) or {}).get("homed")) for k in "XYZ"},
        "z": geo.rnd(geo.num((ax.get("Z") or {}).get("userPosition"))),
        "reach": None if not lim else {"x_min": lim["xmin"], "x_max": lim["xmax"], "y_min": lim["ymin"], "y_max": lim["ymax"]},
        "jog_steps": list(JOG_STEPS), "paper_max": PAPER_MAX, "adjust_max": ADJUST_MAX,
    }


# ---- writes ----

def _conflict(exc):
    return ApiError("conflict", M("machine_height_conflict"), reason="conflict", value=normalize(exc.value), rev=exc.rev)


def _apply_now(om):
    """M98 of zcal.g so the new numbers work now. Not while a job runs (it would change the trigger height under it)."""
    mo = _mo()
    status = str(((om or {}).get("state") or {}).get("status") or "")
    if status in job_states.ACTIVE_OR_TOOL_CHANGE:
        return False, "job_running"
    conn = None
    try:
        conn = mo.open_connection()
        conn.perform_simple_code(machine_gcode.render("zcal_apply"), channel=mo.channel(), async_exec=False)
        return True, ""
    except Exception as e:  # noqa: BLE001 - the files are saved: the numbers apply at the next mode change
        return False, "no_connection:" + str(e)[:80]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _save(args, ctx):
    base = args.get("base_rev")
    if not isinstance(base, str):
        raise _bad("base_rev")
    cur = settings_store.get(NAME)
    new = apply_changes(cur["value"], args.get("changes"))
    try:
        res = settings_store.set(NAME, new, base)
    except settings_store.Conflict as exc:
        raise _conflict(exc)
    except settings_store.SettingsError:
        raise _bad("changes")
    _write_text(ZCAL_G, generate_g(new, time.strftime("%Y-%m-%d %H:%M")))
    applied, why = _apply_now(_mo().model())
    audit.event("machine.height.saved", {"changes": args.get("changes")}, identity.actor(ctx))
    return {"rev": res["rev"], "data": new, "applied": applied, "apply_reason": why, "hooks": hooks()}


def _hook(args, ctx):
    data = normalize(settings_store.get(NAME)["value"])
    _write_text(ZCAL_G, generate_g(data, time.strftime("%Y-%m-%d %H:%M")))
    done, already, absent, stamp = [], [], [], _stamp()
    for m in MODES:
        text = _read_text(MODE_FILES[m])
        if text is None:
            absent.append(m)
        elif HOOK_RE.search(text):
            already.append(m)
        else:
            _write_text(MODE_FILES[m] + ".bak-" + stamp, text)
            _write_text(MODE_FILES[m], text.rstrip() + "\n" + HOOK_LINE)
            done.append(m)
    audit.event("machine.height.hook", {"added": done}, identity.actor(ctx))
    return {"added": done, "already": already, "absent": absent, "hooks": hooks()}


# ---- the movements of the assistants ----

def refusal(om, action, args, macros):
    """Code of the first reason the step must not run, or None. Pure."""
    if not om:
        return "no_model"
    ax = geo.axes_by_letter(om)
    homed = lambda *letters: all((ax.get(k) or {}).get("homed") for k in letters)    # noqa: E731
    need = {"goto": "goto", "measure": "probe", "mark": "mark", "szp": "szp"}.get(action)
    if need and not macros.get(need if need != "mark" else "mark"):
        return "macro_missing"
    if action in ("goto", "measure", "szp") and not homed("X", "Y", "Z"):
        return "not_homed"
    if action == "mark" and not homed("Z"):
        return "not_homed_z"
    if action == "measure" and geo.probe_of(om, 0) is None:
        return "no_probe"
    if action == "szp":
        if _mode_of(om) != "FFF":
            return "szp_not_fff"
        if geo.probe_of(om, 1) is None:
            return "no_szp"
    return None


def _send(conn, chan, template, **numbers):
    return str(conn.perform_simple_code(machine_gcode.render(template, **numbers), channel=chan, async_exec=False) or "")


def _cleanup(conn, chan):
    if conn is None:
        return
    for template in ("abs_mode", "wait_moves"):
        try:
            _send(conn, chan, template)
        except Exception:  # noqa: BLE001 - best effort
            pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def _step_args(action, args):
    if action in ("goto", "measure", "szp"):
        out = {"x": _number(args.get("x"), -5000, 5000, "x"), "y": _number(args.get("y"), -5000, 5000, "y")}
        if action == "szp":
            a = args.get("a")
            if a not in (1, 2) or isinstance(a, bool):
                raise _bad("a")
            out["a"] = a
        return out
    if action == "jog":
        dz = args.get("dz")
        if isinstance(dz, bool) or not isinstance(dz, (int, float)) or float(dz) not in [float(s) for s in JOG_STEPS]:
            raise _bad("dz")
        return {"dz": float(dz)}
    if action == "mark":
        return {"paper": _number(args.get("paper", 0.1), 0, PAPER_MAX, "paper"), "h": _number(args.get("h", 5), MARK_HEIGHT[0], MARK_HEIGHT[1], "h")}
    raise _bad("action")


def _run_step(conn, chan, action, v):
    if action == "goto":
        _send(conn, chan, "zcal_goto", x=v["x"], y=v["y"])
        return {}
    if action == "jog":
        feed = 600 if abs(v["dz"]) >= 1 else 120
        _send(conn, chan, "rel_mode")                     # one request: nobody else's line can fall between the G91 and the G90
        _send(conn, chan, "jog_z", d=v["dz"], feed=feed)
        _send(conn, chan, "abs_mode")
        return {}
    if action == "mark":
        _send(conn, chan, "zcal_mark", paper=v["paper"], h=v["h"])
        return {}
    if action == "measure":
        _send(conn, chan, "zcal_probe", x=v["x"], y=v["y"])
        med = parsers.parse_number_result(_send(conn, chan, "zcal_med"))
        if med is None or not MEASURED[0] < med < MEASURED[1]:
            raise ApiError("failed", M("machine_height_no_reading"), reason="no_reading")
        return {"measured": round(med, 3)}
    out = _send(conn, chan, "zcal_szp", x=v["x"], y=v["y"], a=v["a"])
    return {"output": out.strip()[:2000]}


def _step(args, ctx):
    mo = _mo()
    action = args.get("action")
    v = _step_args(action, args)
    om = mo.model()
    why = refusal(om, action, args, macros_present())
    if why:
        raise ApiError("refused", M("machine_height_refuse_" + why), reason=why)
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])
    if not _busy.acquire(blocking=False):
        raise ApiError("refused", M("machine_height_busy"), reason="busy_step")
    who = identity.actor(ctx)
    bridge = mo._bridge()
    d = motion_owner.reserve(bridge, mo.ORIGIN, "sequence", "height_" + action, RESERVE_S, actor=who)
    if d.get("decision") != "allow":
        _busy.release()
        raise ApiError("motion_denied", d.get("reason") or "", motion={"decision": "deny", "code": d.get("code")})
    conn = chan = None
    try:
        conn, chan = mo.open_connection(), mo.channel()
        _send(conn, chan, "wait_moves")
        out = _run_step(conn, chan, action, v)
        _send(conn, chan, "wait_moves")
        return dict(out, action=action)
    finally:
        _cleanup(conn, chan)
        try:
            motion_owner.release(bridge, d["token"], actor=who)
        finally:
            _busy.release()


def ops():
    a = Arg
    N = "num"
    return [
        Op("machine.height.get", _state, READ, {}, "Height calibration of the tool, read only: what is saved per mode (method, fine adjustment, calibrated "
           "G31 K0 / SZP), the hooks of the mode files, the probes of the object model and what the assistants may do now.", log=False),
        Op("machine.height.save", _save, WRITE, {
            "base_rev": a("str", True, desc="The rev of the saved calibration this change is based on (machine.height.get)."),
            "changes": a("obj", True, desc="{paper?, modes: {Laser|CNC|FFF: {method?, setting?, k0?, szp?}}}: fine adjustment -3..3 mm, k0 {p, x, y, z, date}, "
                                           "szp {s, r, date}; null removes k0 / szp.")},
           "Saves the height calibration (revisioned: a conflict returns the current value), rewrites sys/workshop/macros/zcal.g and applies it now when no job runs."),
        Op("machine.height.hook", _hook, WRITE, {}, "Adds the line that loads the calibration (M98 zcal.g) to the mode files that lack it, keeping a copy of each file."),
        Op("machine.height.step", _step, MOTION, {
            "action": a("str", True, choices=("goto", "jog", "mark", "measure", "szp"), desc="goto: the tool over X Y; jog: Z one step; mark: Z0 with the paper; "
                                                                                              "measure: the BLTouch measures at X Y; szp: FFF scanning probe step."),
            "x": a(N, min=-5000, max=5000, desc="goto / measure / szp: X."), "y": a(N, min=-5000, max=5000, desc="goto / measure / szp: Y."),
            "dz": a(N, min=-5, max=5, desc="jog: -5, -1, -0.1, -0.05, 0.05, 0.1, 1 or 5."),
            "paper": a(N, min=0, max=PAPER_MAX, desc="mark: thickness of the paper / feeler gauge."), "h": a(N, min=1, max=60, desc="mark: height to rise to."),
            "a": a("int", min=1, max=2, desc="szp: 1 drive level, 2 height vs reading.")},
           "One step of the height assistants: reserves the movement (refused during a job) and sends the macros zcal-goto / zcal-mark / zcal-probe / zcal-szp or one "
           "relative Z step (never the laser: S0).", motion="sequence", exclusive=False),
    ]


def reset():
    """For the tests."""
    if _busy.locked():
        _busy.release()
