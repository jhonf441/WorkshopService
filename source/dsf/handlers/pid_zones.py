"""
Internal implementation of the API operation(s) pid.cancel, pid.start, pid.status (api_ops.py maps their named
arguments to the one-letter parameters below).

Calibrate the PID of ALL the zones of a tool, on its own (2026-10-11:
"if it is a pellet extruder or one with multiple zones, I want to be able to
calibrate the PIDs ... have it do it automatically"; "when tuning PID let it
go through the safety protocol").

Why this way: the zones of a barrel are right next to each other, the heat of
one passes to the other (thermal coupling). If one zone is calibrated with
the neighbours cold, the resulting model is no good for printing (with the
neighbours hot the zone loses less heat). That is why each zone is
calibrated with the others ALREADY at their working temperature.

What RRF requires (checked in the RepRapFirmware 3.5 code,
src/Heating/LocalHeater.cpp and Heater.cpp, 2026-10-11):
  - M303 only starts if the heater is OFF ("must be off and cold
    before auto tuning it") and if the starting temperature is at least 20 C
    below the target ("Target temperature must be at least 20C above
    ambient"). Without A, it takes 5 s of readings and requires them to be stable.
  - Only one heater at a time ("cannot start a new auto tune because heater
    N is being tuned").
  - When it ends (well or badly) the heater is left OFF; if it went well, the
    new model is already in use (M307 H<h> shows it).
  - M303 without H/T reports the result of the last one: "... tuning succeeded" or
    "... tuning failed".
  - M568 P<t> S<a>:<b>... A2 puts the tool's heaters in active WITHOUT
    selecting it (tpre/tpost do not run); a temperature near absolute
    zero (-273.15) turns that heater off.

Sequence, zone by zone:
  1. M568 P<t> S<all> A2 (all at their temperature) and then
     M568 P<t> S<...,-273.15,...> to turn off ONLY the zone being done.
  2. Wait for the neighbours to arrive (tolerance) and for the turned-off zone
     to drop at least MARGIN_COLD below its target and stay still
     (the neighbours keep it warm: that is the real "ambient temperature"
     it will have when printing).
  3. M303 H<h> S<t> (with a single zone, M303 T<t> H<h> S<t>: RRF calibrates
     with the tool's fan too). Wait for it to stop being in "tuning", read the
     result (M303) and the model (M307 H<h>).
At the end (or on cancel / failure): M568 P<t> A0 and the temperatures the
tool had are restored.

Everything is cut and turned off if: a zone passes its limit (heat.heaters[h].max) or
goes far above the target, a heater fails, someone turns off the
heaters, the machine starts a job or the maximum time passes.

While it runs it opens an explicit active risk ("pid_zones", level 4 of the
protocol, see risk_rules.py): red bar and LEDs. It publishes the progress in
plugins.WorkshopService.data.pidZones.

Usage: <params> S"start" J"<hex of {tool, zonas:[{h, t}], tol?}>"
     <params> S"status"|"estado"     -> progress JSON
     <params> S"cancel"|"cancelar"   -> turns off and ends
(S"iniciar" is an alias of S"start".)

The codes are sent from a thread of its own, never from run(): sending a
code from the callback that handles the intercepted API call deadlocks
itself (see airassist.py / jog.py).

"""
import atexit
import json
import re
import sys
import threading
import time
import types

import messages
import risk_rules
from messages import M, J, B, Msg

RISK_ID = "pid_zones"
KEY_STATE = "pidZones"

TOL_DEF = 5.0             # C: vecinas "a temperatura"
MARGIN_COLD = 25.0        # C below the target to start M303 (RRF asks for 20)
STILL_WINDOW_S = 60     # the turned-off zone is considered still if in 60 s
STILL_SPAN = 1.5        # ... it did not change more than 1.5 C
WAIT_MAX_S = 30 * 60    # heat the neighbours + cool the zone
STUCK_S = 180          # still but too hot for that long: it does not drop
CALIBRATES_MAX_S = 60 * 60   # a single M303 (the barrels are slow)
BY_ZONE_MAX_S = WAIT_MAX_S + CALIBRATES_MAX_S
TOTAL_MAX_S = 6 * 3600    # general limit (and of the active risk)
OVER_TARGET = 40.0     # C above the target: something is wrong
JOB = ("processing", "simulating", "pausing", "paused", "resuming", "cancelling")
STOP = ("halted", "off", "disconnected", "updating", "starting")

# The handlers runner (main.py) reloads this file on every API call,
# so the state lives in a fixed module of sys.modules.
_S = sys.modules.get("_workshop_pid_zones")
if _S is None:
    _S = types.ModuleType("_workshop_pid_zones")
    _S.lock = threading.Lock()
    _S.cancel = threading.Event()
    _S.thread = None
    _S.tool = None
    _S.status = {"active": False, "phase": "inactive"}
    sys.modules["_workshop_pid_zones"] = _S


class _Cut(Exception):
    """Cut the whole sequence (everything is turned off)."""

    def __init__(self, msg, phase="error"):
        super().__init__(msg)
        self.phase = phase


class _SkipZone(Exception):
    """This zone could not be done; continue with the next one."""


def _msg(e):
    """The text of an exception, keeping the message (and so its other language) when it carries one."""
    return e.args[0] if e.args and isinstance(e.args[0], Msg) else str(e)


def _now():
    return int(time.time())  # integers: dsf-python leaves floats with 6 digits


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _status():
    import machine_state
    return machine_state.get_status(timeout=3, max_age_s=0.5)


def _is_error(r):
    return bool(re.search(r"error|abort", str(r or ""), re.I))


def _fmt(t):
    return ("%.2f" % t).rstrip("0").rstrip(".") if t > -273 else "-273.15"


# ---- estado publicado ----

def _publish(bridge, force=False):
    with _S.lock:
        e = messages.data(_S.status)  # a copy; its messages as {"key", "params"}
    e["actualizado"] = _now()
    latest = getattr(_S, "_published_at", 0)
    if force or time.time() - latest >= 5:
        _S._published_at = time.time()
        try:
            bridge.set_status(KEY_STATE, e)
        except Exception:
            pass


def _put(bridge, force=True, **changes):
    with _S.lock:
        _S.status.update(changes)
    _publish(bridge, force)


def _zone(i, **changes):
    with _S.lock:
        _S.status["zones"][i].update(changes)


def _update_temps(s):
    hs = ((s or {}).get("heat") or {}).get("heaters") or []
    with _S.lock:
        for z in _S.status.get("zones", []):
            h = hs[z["h"]] if z["h"] < len(hs) else None
            if h:
                c = _num(h.get("current"))
                z["actual"] = round(c, 1) if c is not None else None
                z["state"] = h.get("state")


# ---- vigilancia ----

def _watch(s, tool, zones, calibrating=None, begin=0):
    """Checks on every pass. calibrating = h of the zone in M303 (it may be
    'tuning' or 'off'); the others must stay active."""
    if _S.cancel.is_set():
        raise _Cut(M("pid_zones_cancelled_by_user"), "cancelled")
    if time.time() - begin > _S.status.get("max_s", TOTAL_MAX_S):
        raise _Cut(M("pid_zones_maximum_calibration_time_passed_everything_was"))
    if s is None:
        return
    st = ((s.get("state") or {}).get("status") or "").lower()
    if st in JOB:
        raise _Cut(M("pid_zones_machine_started_job_calibration_was_cut"))
    if st in STOP:
        raise _Cut(M("pid_zones_board_stopped_restarted_state_calibration_was", st=st))
    hs = (s.get("heat") or {}).get("heaters") or []
    for z in zones:
        h = hs[z["h"]] if z["h"] < len(hs) else None
        if not h:
            raise _Cut(M("pid_zones_heater_no_longer_exists_calibration_was", h=int(z["h"])))
        status = h.get("state")
        cur = _num(h.get("current")) or 0.0
        cap = _num(h.get("max"))
        if status == "fault":
            raise _Cut(M("pid_zones_heater_went_into_fault_everything_was", h=int(z["h"])))
        if cap is not None and cur >= cap:
            raise _Cut(M("pid_zones_zone_heater_reached_its_limit_c", h=int(z["h"]), int=int(cap)))
        if cur > z["t"] + OVER_TARGET:
            raise _Cut(M("pid_zones_zone_heater_went_c_far_above", h=int(z["h"]), int=int(cur)))
        if z["h"] != calibrating and status == "off" and z.get("_debe_estar_activa"):
            raise _Cut(M("pid_zones_someone_turned_heaters_off_calibration_was"), "cancelled")


# ---- secuencia ----

def _temps(zones, power_off=None):
    return ":".join("-273.15" if z["h"] == power_off else _fmt(z["t"]) for z in zones)


def _send(bridge, code):
    r = bridge.send(code)
    if _is_error(r):
        raise _Cut(M("pid_zones_board_rejected", code=code, answer=str(r).strip()[:200]))
    return str(r or "")


def _wait_for(bridge, tool, zones, i, begin, tol):
    """Neighbours at temperature and zone i turned off, cold and still."""
    z = zones[i]
    hist = []
    t0 = time.time()
    stuck_since = None
    while True:
        s = None
        try:
            s = _status()
        except Exception:
            pass
        _watch(s, tool, zones, calibrating=z["h"], begin=begin)
        _update_temps(s)
        hs = ((s or {}).get("heat") or {}).get("heaters") or []
        cur = _num((hs[z["h"]] or {}).get("current")) if s and z["h"] < len(hs) else None
        neighbors_ok = s is not None and all(
            abs((_num((hs[o["h"]] or {}).get("current")) or -999) - o["t"]) <= tol
            for o in zones if o["h"] != z["h"]
        )
        current_time = time.time()
        if cur is not None:
            hist.append((current_time, cur))
        hist = [p for p in hist if current_time - p[0] <= STILL_WINDOW_S]
        still = bool(hist) and current_time - t0 >= STILL_WINDOW_S and \
            max(p[1] for p in hist) - min(p[1] for p in hist) <= STILL_SPAN
        cold = cur is not None and cur <= z["t"] - MARGIN_COLD
        with _S.lock:
            _S.status["neighbors_lists"] = neighbors_ok
            _S.status["zone_cold"] = cold
        _publish(bridge)
        if neighbors_ok and cold and still:
            return
        # still, neighbours ready, but it does not drop enough: the neighbours
        # keep it hot and RRF cannot start the calibration
        if neighbors_ok and still and not cold:
            stuck_since = stuck_since or current_time
            if current_time - stuck_since >= STUCK_S:
                raise _SkipZone(
                    M("pid_zones_neighbours_hot_zone_stays_at_c", int=int(cur), int2=int(z["t"] - MARGIN_COLD)))
        else:
            stuck_since = None
        if current_time - t0 > WAIT_MAX_S:
            if not neighbors_ok:
                raise _Cut(M("pid_zones_zones_did_not_reach_their_temperature", WAIT_MAX_S=int(WAIT_MAX_S // 60)))
            raise _SkipZone(M("pid_zones_zone_did_not_go_down_stay"))
        time.sleep(1)


def _calibrate(bridge, tool, zones, i, begin):
    z = zones[i]
    code = ("M303 T%d H%d S%s" % (tool, z["h"], _fmt(z["t"]))) if len(zones) == 1 else \
        ("M303 H%d S%s" % (z["h"], _fmt(z["t"])))
    r = bridge.send(code)
    if _is_error(r):
        raise _SkipZone(M("pid_zones_rrf_did_not_start_calibration", answer=str(r).strip()[:200]))
    t0 = time.time()
    seen = False
    while True:
        s = None
        try:
            s = _status()
        except Exception:
            pass
        _watch(s, tool, zones, calibrating=z["h"], begin=begin)
        _update_temps(s)
        _publish(bridge)
        hs = ((s or {}).get("heat") or {}).get("heaters") or []
        st = (hs[z["h"]] or {}).get("state") if s and z["h"] < len(hs) else None
        if st == "tuning":
            seen = True
        elif s is not None and (seen or time.time() - t0 > 15):
            break
        if time.time() - t0 > CALIBRATES_MAX_S:
            raise _Cut(M("pid_zones_calibration_one_zone_went_over_minutes", CALIBRATES_MAX_S=int(CALIBRATES_MAX_S // 60)))
        time.sleep(1)
    time.sleep(1.5)
    res = str(bridge.send("M303") or "")
    if "succeeded" not in res.lower():
        raise _SkipZone(M("pid_zones_calibration_zone_failed_look_at_console"))
    model = str(bridge.send("M307 H%d" % z["h"]) or "").strip()
    _zone(i, result="ok", model=model, error=None, end=_now())


def _work(bridge, tool, zones, orig, tol):
    begin = time.time()
    try:
        activity_log(bridge, M("pid_started", tool=tool, zones=", ".join("H%d %d C" % (z["h"], int(z["t"])) for z in zones)))
        for i, z in enumerate(zones):
            _put(bridge, zone_current=i, phase="preparing")
            _zone(i, result="in_progress", start=_now())
            try:
                if len(zones) > 1:
                    _send(bridge, "M568 P%d S%s A2" % (tool, _temps(zones)))
                    _send(bridge, "M568 P%d S%s" % (tool, _temps(zones, power_off=z["h"])))
                    for o in zones:
                        o["_debe_estar_activa"] = o["h"] != z["h"]
                else:
                    _send(bridge, "M568 P%d A0" % tool)
                _put(bridge, phase="waiting")
                _wait_for(bridge, tool, zones, i, begin, tol)
                _put(bridge, phase="calibrando")
                _calibrate(bridge, tool, zones, i, begin)
            except _SkipZone as e:
                _zone(i, result="failure", error=_msg(e), end=_now())
                _publish(bridge, True)
        with _S.lock:
            good = sum(1 for z in _S.status["zones"] if z.get("result") == "ok")
        _put(bridge, phase="finished", zone_current=None,
               error=None if good == len(zones) else M("pid_zones_zones_could_not_be_calibrated", failed=len(zones) - good, total=len(zones)))
        activity_log(bridge, M("pid_finished", tool=tool, good=good, total=len(zones)))
    except _Cut as e:
        with _S.lock:
            for zz in _S.status.get("zones", []):
                if zz.get("result") in ("pending", "in_progress"):
                    zz["result"] = "cut"
        _put(bridge, phase=e.phase, error=_msg(e), zone_current=None)
        activity_log(bridge, M("pid_cut", tool=tool, reason=_msg(e)))
    except Exception as e:
        _put(bridge, phase="error", error=M("pid_zones_internal_error", e=e), zone_current=None)
    finally:
        _power_off(bridge, tool, orig)
        risk_rules.finish(RISK_ID)
        _put(bridge, active=False, end=_now())
        _S.tool = None


def _power_off(bridge, tool, orig=None):
    for code in ["M568 P%d A0" % tool] + (["M568 P%d S%s" % (tool, orig)] if orig else []):
        try:
            bridge.send(code)
        except Exception:
            pass


def activity_log(bridge, raw_text):
    try:
        import activity
        activity.log_event(bridge, "calibration", raw_text)
    except Exception:
        pass


def _at_exit():
    # if the service stops in the middle: do not leave the barrel hot alone
    if _S.thread is not None and _S.thread.is_alive() and _S.tool is not None:
        try:
            b = getattr(_S, "bridge", None)
            if b is not None:
                b.send("M568 P%d A0" % _S.tool)
        except Exception:
            pass


if not getattr(_S, "_atexit", False):
    atexit.register(_at_exit)
    _S._atexit = True


# ---- API call ----

def _read_request(params):
    try:
        j = params.get("J")
        b = j if isinstance(j, dict) else json.loads(bytes.fromhex(str(j or "")).decode("utf-8"))
    except Exception:
        raise ValueError(M("pid_zones_valid_j_hex_json_missing"))
    tool = b.get("tool")
    if not isinstance(tool, (int, float)) or int(tool) != tool:
        raise ValueError(M("pid_zones_tool_number_missing"))
    zones = []
    for z in b.get("zones") or []:
        h, t = z.get("h"), _num(z.get("t"))
        if not isinstance(h, (int, float)) or int(h) != h or t is None:
            raise ValueError(M("pid_zones_zone_badly_written"))
        zones.append({"h": int(h), "t": float(t)})
    if not zones:
        raise ValueError(M("pid_zones_no_zones"))
    if len({z["h"] for z in zones}) != len(zones):
        raise ValueError(M("pid_zones_repeated_zone"))
    tol = _num(b.get("tol")) or TOL_DEF
    return int(tool), zones, max(1.0, min(tol, 15.0))


def _begin(params, bridge):
    if _S.thread is not None and _S.thread.is_alive():
        return M("pid_zones_error_zone_calibration_already_running")
    try:
        tool, zones, tol = _read_request(params)
    except ValueError as e:
        return J(["Error", _msg(e)], sep=": ")
    try:
        s = _status()
    except Exception as e:
        return M("pid_zones_error_could_not_read_machine_state", e=e)
    st = ((s.get("state") or {}).get("status") or "").lower()
    if st != "idle":
        return M("pid_zones_error_machine_has_at_rest_now", st=st)
    t = next((x for x in (s.get("tools") or []) if x and x.get("number") == tool), None)
    if not t:
        return M("pid_zones_error_tool_does_not_exist", tool=tool)
    hs = (s.get("heat") or {}).get("heaters") or []
    th = list(t.get("heaters") or [])
    if any(h and h.get("state") == "tuning" for h in hs):
        return M("pid_zones_error_heater_already_being_calibrated")
    for z in zones:
        if z["h"] not in th:
            return M("pid_zones_error_heater_not_of_tool", h=z["h"], tool=tool)
        h = hs[z["h"]] if z["h"] < len(hs) else None
        if not h:
            return M("pid_zones_error_heater_does_not_exist", h=z["h"])
        if h.get("state") == "fault":
            return M("pid_zones_error_heater_fault", h=int(z["h"]))
        cap = _num(h.get("max"))
        if z["t"] < 50 or (cap is not None and z["t"] >= cap):
            return M("pid_zones_error_heater_temperature_range", h=z["h"], cap=int(cap) if cap is not None else "?")
    # M568 S carries ALL the tool's zones in their order: all are requested
    # (the ones not being calibrated could not be sustained with a known model)
    requested = {z["h"]: z for z in zones}
    if set(requested) != set(th):
        return M("pid_zones_error_all_zones_of_tool_needed", tool=tool, heaters=", ".join(str(h) for h in th))
    order = [requested[h] for h in th]
    active = list(t.get("active") or [])
    # active temperatures the tool had: they are restored at the end
    # (M568 S changes them). If they were all 0 it is not needed.
    orig = ":".join(_fmt(_num(a) or 0.0) for a in active) if any((_num(a) or 0) > 0 for a in active) else None

    n = len(order)
    max_s = min(TOTAL_MAX_S, n * BY_ZONE_MAX_S + 10 * 60)
    _S.cancel.clear()
    _S.tool = tool
    _S.bridge = bridge
    with _S.lock:
        _S.status = {
            "active": True, "phase": "preparing", "tool": tool, "tol": tol,
            "since": _now(), "end": None, "max_s": int(max_s), "error": None,
            "zone_current": None, "neighbors_lists": False, "zone_cold": False,
            "margin_cold": int(MARGIN_COLD),
            "zones": [{"h": z["h"], "t": z["t"], "result": "pending", "model": None,
                       "error": None, "actual": None, "state": None} for z in order],
        }
    risk_rules.launch(RISK_ID, M("pid_zones_calibrating_pid_all_zones_t_heats", tool=int(tool)), max_s + 120)

    def execute():
        _work(bridge, tool, order, orig, tol)

    _S.thread = threading.Thread(target=execute, name="pid_zones", daemon=True)
    _S.thread.start()
    _publish(bridge, True)
    return json.dumps({"ok": True, "zones": n, "max_s": int(max_s)})


def run(params, bridge, config):
    action = str(params.get("S", "status")).strip().lower()
    if action in ("start", "start"):
        return _begin(params, bridge)
    if action in ("cancel", "cancel"):
        if _S.thread is not None and _S.thread.is_alive():
            _S.cancel.set()
            return M("pid_zones_cancelling_zones_off")
        return M("pid_zones_there_no_zone_calibration_running")
    with _S.lock:
        e = messages.localize(_S.status, messages.current_language())  # a copy, in the language of the request
    e["active"] = bool(_S.thread is not None and _S.thread.is_alive())
    e["now"] = _now()
    return json.dumps(e)
