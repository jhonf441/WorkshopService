"""
Job opened with the API (trabajo) S"inicio" (a live program, or a file that
carries that line): start, close and cut of the duration.
2026-10-12, item 6 of the 2026-10-11 diagnosis.

Before: a job without an "end" stayed "in progress" forever (also after
restarting) and when closed late it added extra hours, kWh and money to the
activity. Now:

  - Last real activity: the head moved, an M3/M4/M5 arrived (intercepted in
    main.py), the file advanced or an API call P"trabajo" arrived. It is
    saved with the job (on the card at most every SAVE_ACT_S, so as not to
    wear it out).
  - FILE job (the start arrived with a file running): it closes by itself
    when that file ends (state.status leaves the job states or job.file
    changes), even if the file does not carry the "end".
  - LIVE job: with no activity for "deadline_inactive_min" (config
    "job_in_live"; 0 = never) it closes by itself.
  - When the service starts: one left open is closed at its last activity,
    unless the machine is still in that same job.
  - The Duet restarts with an open job (live or file): it is closed there, at
    its last real activity, with the reason "the machine restarted"
    (2026-10-12, user's decision: following it makes no sense).
    It is detected with state.upTime: at the start the Duet's boot mark
    (now - upTime) is saved in current_job.json; if the mark later goes up
    (low upTime), the board booted again. It works with the service running
    (watch) and when the service starts.
  - Another one starts with one open: the previous one is closed at ITS last
    activity and the answer reports it (they are not mixed).
  - Any close that is not the program's "end"/"cancel" cuts the duration
    (and the kWh and the money) at the last activity, not at the moment of
    closing.
  - By hand: the API (trabajo) S"cerrar" (Services and Zones pages).

The state stays in job_current.json (dsf/), the same one read by
job_trace.py and the others.

"""
import fs_atomic
import job_states
import json
import os
import threading
import time

import activity
import db
import machine_state
import messages
from messages import M, J

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_current.json")

JOB_ACTIVE = job_states.ACTIVE
DEADLINE_DEFAULT_MIN = 30
# live job with the machine at rest and without activity for this long: the program stopped it (nobody sends the
# "end"
# when it is cut by hand). It closes by itself and releases what the job had locked.
STOP_IDLE_S = 30
# a second "start" so soon after the first is the SAME job announced twice (the material macro and the
# program's BRIDGE JOB START): they are merged into one instead of closing the first and opening another
REPEATED_S = 10
SAVE_ACT_S = 60
MIN_MOVE_MM = 0.05
# a cut less than this from "now" uses the current meter reading
NOW_TOL_S = 60
# the Duet's boot mark (now - upTime) carries the delay of the
# reading; a real restart shifts it by tens of seconds at least
STARTUP_TOL_S = 30

# how a live job ended: the message "live_job_end_<as>" of the catalog
ENDINGS = ("end", "cancel", "interrumpido", "inactive", "restart", "restart_duet", "file", "file_cancelled", "manual", "stopped")

_lock = threading.RLock()
# st: in-memory copy of job_current.json (loaded: already read)
# ult: last activity seen (no lock: written by the interceptor)
# ready: on_start already ran (before that, watch closes nothing: the old
# job is decided by the startup)
_mem = {"st": None, "loaded": False, "last": 0, "saved_act": 0, "pos": None, "fpos": None, "closed_file": None, "ready": False}


def _now():
    return time.time()


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(int(epoch)))


def _hhmm(epoch):
    return time.strftime("%H:%M", time.localtime(int(epoch)))


# ---- state on disk ----

def read_in():
    with _lock:
        if not _mem["loaded"]:
            try:
                with open(STATE_FILE) as f:
                    _mem["st"] = json.load(f)
            except Exception:
                _mem["st"] = None
            _mem["loaded"] = True
        return _mem["st"]


def _save(st):
    fs_atomic.write_json(STATE_FILE, st)
    _mem["st"], _mem["loaded"] = st, True


def _delete():
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass
    _mem["st"], _mem["loaded"] = None, True


def reload():
    """For the tests (and if another process touches the file)."""
    with _lock:
        _mem.update({"st": None, "loaded": False, "last": 0, "saved_act": 0, "pos": None, "fpos": None})


def deadline_min(config):
    try:
        v = int((config.get("job_in_live") or {}).get("deadline_inactive_min", DEADLINE_DEFAULT_MIN))
    except (TypeError, ValueError, AttributeError):
        v = DEADLINE_DEFAULT_MIN
    return max(0, min(v, 24 * 60))


def stop_s(config):
    """Seconds of rest without activity after which a live job is considered stopped (0 = do not close because of this)."""
    try:
        v = int((config.get("job_in_live") or {}).get("stop_idle_s", STOP_IDLE_S))
    except (TypeError, ValueError, AttributeError):
        v = STOP_IDLE_S
    return max(0, min(v, 3600))


def last_activity(st):
    if not st:
        return None
    ini = int(st.get("start_epoch") or 0)
    return max(ini, int(st.get("last_activity") or 0), int(_mem["last"] or 0) if _mem["last"] >= ini else 0)


def default_name():
    """Name of a live job started without one, in the language of the caller (DWC's outside a request)."""
    return str(M("live_job_default_name"))


def is_default_name(name):
    """True for an empty name or the default one in either language: the pages show it in their own language, a
    name the program or the person gave is kept as it is."""
    n = str(name or "").strip().lower()
    return not n or n in (messages.render("es", "live_job_default_name").lower(), messages.render("en", "live_job_default_name").lower())


def shown_name(name):
    """The name to write where no page translates it (a photo, a console line): the default one in DWC's language."""
    return default_name() if is_default_name(name) else str(name)


# Plugin data "liveJob" (2026-10-08): a live job leaves RRF in
# "busy", never in "processing", so the jog/Zones were not blocked during the
# cut. WorkshopJog reads {activo, nombre, desde}.
# 2026-10-12: also archivo (if the start came from a file),
# lastActivity and deadlineMin (for the page). set_status only queues the value (the publisher thread does the IPC), so it is called here
# and never from a new thread: two quick emits (a job ends, another starts) must reach the page in order.
def emit(bridge, st, config=None):
    latest = last_activity(st)
    val = {
        "active": bool(st),
        "name": st.get("name") if st else None,
        "since": st.get("start_ts") if st else None,
        "file": st.get("file") if st else None,
        "lastActivity": _iso(latest) if latest else None,
        "deadlineMin": deadline_min(config) if config is not None else None,
    }
    bridge.set_status("liveJob", val)


def mark_activity(ts=None):
    """An order arrives or something moved. No lock or disk: called by the
    M3/M4/M5 interceptor; watch() saves it every SAVE_ACT_S."""
    ts = int(ts or _now())
    if ts > _mem["last"]:
        _mem["last"] = ts


def _snapshot(status=None):
    try:
        s = status if status is not None else machine_state.get_status()
    except Exception:
        return {"mode": None, "kwh": None, "zone": None}
    g = s.get("global") or {}
    wn = (s.get("move") or {}).get("workplaceNumber")
    return {
        "mode": g.get("selectedMode"),
        "kwh": g.get("consumptionKWh"),
        "zone": machine_state.zone_name(wn) if isinstance(wn, int) else None,
    }


def _startup_duet(status):
    """Duet boot mark (epoch) according to state.upTime; None if there is none."""
    try:
        up = (status.get("state") or {}).get("upTime")
        if isinstance(up, bool) or not isinstance(up, (int, float)) or up < 0:
            return None
        return int(_now() - up)
    except Exception:
        return None


def restart_duet(st, status):
    """True if the Duet booted again after the job `st` started."""
    if not st or not status:
        return False
    saved = st.get("startup_duet")
    current_time = _startup_duet(status)
    if not saved or current_time is None:
        return False
    return current_time > int(saved) + STARTUP_TOL_S


def _file_in_progress(status):
    if not status:
        return None
    if ((status.get("state") or {}).get("status")) not in JOB_ACTIVE:
        return None
    return ((status.get("job") or {}).get("file") or {}).get("fileName") or None


# ---- inicio ----

# 2026-10-15: a live job is not accepted while the machine is in a state that cannot take it (paused, halted by an error,
# cancelling, off, updating). "busy" is normal (the stream itself keeps the machine busy) and "processing" is a file that
# carries the job.start line.
NO_ACCEPTS = {s: M("machine_state_" + s) for s in ("paused", "pausing", "resuming", "cancelling", "halted", "off", "updating", "starting")}


def reason_rejection(status):
    """Why a live job cannot start now (text), or None if it can (or the state is not known)."""
    try:
        s = (status.get("state") or {}).get("status")
    except AttributeError:
        return None
    return NO_ACCEPTS.get(s)


def launch(bridge, config, label):
    with _lock:
        try:
            status = machine_state.get_status(max_age_s=1.0)
        except Exception:
            status = None
        notice = ""
        reason = reason_rejection(status) if status else None
        if reason:
            activity.log_event(bridge, "system", M("live_job_rejected", label=label, reason=reason), kind=None)
            return M("live_job_error_live_job_not_accepted_machine", reason=reason)
        is_open = read_in()
        if is_open and int(_now()) - int(is_open.get("start_epoch") or 0) <= REPEATED_S and not is_open.get("file"):
            if not is_default_name(label) and is_open.get("name") != label:
                is_open = dict(is_open, name=label)  # the second announcement usually has the better name
                _save(is_open)
                emit(bridge, is_open, config)
            return M("live_job_job_already_started", name=is_open.get('name'))
        if is_open:
            # do not mix: the previous one ends at ITS last activity
            r = _close_st(bridge, config, is_open, "interrumpido", last_activity(is_open), publish_end=False)
            notice = M("live_job_notice_previous_still_open_closed", name=is_open.get('name'), time=_hhmm(r[2]))
        snap = _snapshot(status)
        current_time = int(_now())
        st = {
            "name": label,
            # integer: in the plugin's process json writes floats with few
            # digits ("1.7915e+09"), which ruined the duration (2026-10-08)
            "start_epoch": current_time,
            "start_ts": _iso(current_time),
            "mode": snap["mode"],
            "kwh": snap["kwh"],
            "zone": snap["zone"],
            "file": _file_in_progress(status),
            "last_activity": current_time,
            "startup_duet": _startup_duet(status) if status else None,
        }
        _mem["last"] = current_time
        _mem["saved_act"] = current_time
        _mem["pos"] = None
        _mem["fpos"] = None
        _save(st)
        emit(bridge, st, config)
        zone = M("in_zone", zone=snap["zone"]) if snap["zone"] else ""
        activity.log_event(bridge, "job_start", M("job_started", label=label, zone=zone), kind=snap["mode"])
        return J([M("job_started", label=label, zone=zone), notice], sep="")


# ---- cierre ----

def shut(bridge, config, as_, publish_end=True):
    """end/cancel: cut now. The others: at the last
    activity. Returns (dur_s, kwh, end_epoch) or None if there was none."""
    with _lock:
        st = read_in()
        if not st:
            return None
        end = int(_now()) if as_ in ("end", "cancel") else last_activity(st)
        return _close_st(bridge, config, st, as_, end, publish_end)


def _close_st(bridge, config, st, as_, end_epoch, publish_end=True):
    ini = int(st["start_epoch"])
    end = max(ini, int(end_epoch))
    dur = end - ini
    ini_iso, end_iso = _iso(ini), _iso(end)
    cut_off = _now() - end > NOW_TOL_S
    kwh = None
    if not cut_off:
        current_time = _snapshot()
        if current_time["kwh"] is not None and st.get("kwh") is not None:
            kwh = round(max(0.0, current_time["kwh"] - st["kwh"]), 4)
    else:
        # closed late: the meter's accumulated value of now would add what came after the
        # job; what was measured between the start and the cut is taken
        try:
            res = db.consumption_span_summary(ini_iso, end_iso)
            if res:
                kwh = round(max(0.0, res["consumption_kwh"]), 4)
        except Exception:
            pass
    # The meter's accumulated value has steps of 0.01 kWh: a short cut gives
    # 0.000 (seen 2026-10-08, a 25 s job). If the accumulated value moved
    # little, it is estimated with the average power of the samples of the period
    # (every 30 s; a window of 35 s before the start to have at least one).
    pot = None
    try:
        res = db.consumption_span_summary(_iso(ini - 35), end_iso)
        if res and res["samples"]:
            pot = res["average_w"]
    except Exception:
        pass
    if pot is not None and (kwh is None or kwh < 0.05):
        kwh = round(pot * dur / 3600000.0, 4)
    # 2026-10-10: other meters (bed on another line, etc.): those on their own line
    # are added to the total; those inside another one are shown as part of it
    dz = None
    try:
        import meters
        dz = meters.breakdown(ini_iso, end_iso)
    except Exception:
        dz = None
    if dz and dz.get("extra_kwh"):
        kwh = round((kwh or 0.0) + dz["extra_kwh"], 4)
    parts = [M("minutes", min=dur / 60)]
    if kwh is not None:
        parts.append(M("kwh_avg", kwh=kwh, w=pot) if pot is not None else M("kwh", kwh=kwh))
        tariff = config.get("consumption_tariff") or {}
        if tariff.get("value_kwh"):
            parts.append(f"~{kwh * tariff['value_kwh']:.0f} {tariff.get('currency', '')}".strip())  # an amount of money
    if dz and dz.get("text"):
        parts.append(dz["text"])
    if cut_off:
        parts.append(M("cut_at_last_activity", time=_hhmm(end)))
    zone = f", {st['zone']}" if st.get("zone") else ""
    activity.log_event(
        bridge,
        "job_end",
        M("live_job_end_" + as_, name=st["name"], zone=zone, parts=J(parts)),
        kind=st.get("mode"),
        duration_s=dur,
        consumption_kwh=kwh,
    )
    if st.get("file"):
        _mem["closed_file"] = (st["file"], ini)
    if as_ in ("end", "cancel", "manual"):
        # the program (or the person) said it is over: the jog does not wait for the bridge activity window
        try:
            import jog_move
            jog_move.bridge_end_job()
        except Exception:
            pass
    _delete()
    _mem["pos"] = None
    _mem["fpos"] = None
    if publish_end:
        emit(bridge, None, config)
    return dur, kwh, end


def file_registered(file_name, since_epoch):
    """job_poller: the file job is already recorded by this module (opened
    with that file, or closed during that file) -> do not duplicate the end."""
    if not file_name:
        return False
    st = read_in()
    if st and st.get("file") == file_name:
        return True
    c = _mem["closed_file"]
    return bool(c and c[0] == file_name and c[1] >= int(since_epoch or 0) - 60)


# ---- monitoring (every round of job_poller, with the status it already read) ----

def _position(status):
    axes = (status.get("move") or {}).get("axes") or []
    return tuple(a.get("machinePosition") for a in axes if a)


def watch(bridge, config, status):
    """Marks activity by movement/advance of the file and closes what applies.
    Returns the reason if it closed one, otherwise None."""
    if not status or not _mem["ready"]:
        return None
    with _lock:
        st = read_in()
        if not st:
            _mem["pos"] = None
            _mem["fpos"] = None
            return None
        current_time = _now()
        state = status.get("state") or {}
        job = status.get("job") or {}
        ms = state.get("status")

        # the Duet restarted: the job ends at its last real activity
        if restart_duet(st, status):
            _close_st(bridge, config, st, "restart_duet", last_activity(st))
            return "restart_duet"
        if not st.get("startup_duet"):
            mark = _startup_duet(status)
            if mark:  # the start could not read it: the first time there is one is taken
                st = dict(st, startup_duet=mark)
                try:
                    _save(st)
                except Exception:
                    pass

        pos = _position(status)
        prev = _mem["pos"]
        if prev is not None and len(prev) == len(pos):
            for a, b in zip(prev, pos):
                if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) > MIN_MOVE_MM:
                    mark_activity(current_time)
                    break
        _mem["pos"] = pos
        if ((status.get("move") or {}).get("currentMove") or {}).get("requestedSpeed"):
            mark_activity(current_time)
        if st.get("file"):
            fpos = job.get("filePosition")
            if _mem["fpos"] is not None and fpos is not None and fpos != _mem["fpos"]:
                mark_activity(current_time)
            _mem["fpos"] = fpos

        as_ = None
        if st.get("file"):
            fn = (job.get("file") or {}).get("fileName")
            if ms not in JOB_ACTIVE or fn != st["file"]:
                cancelled = job.get("lastFileCancelled") or job.get("lastFileAborted") or ms == "cancelling"
                as_ = "file_cancelled" if cancelled else "file"
        else:
            deadline = deadline_min(config)
            if ms in ("halted", "off"):
                as_ = "stopped"  # emergency stop or failure: the job does not continue any more
            elif ms == "idle" and stop_s(config) and current_time - last_activity(st) > stop_s(config):
                as_ = "stopped"  # the program cut it: the board is still and nothing moves
            elif deadline and current_time - last_activity(st) > deadline * 60:
                as_ = "inactive"
        if as_:
            _close_st(bridge, config, st, as_, last_activity(st))
            return as_

        # save the last activity (at most every SAVE_ACT_S)
        latest = last_activity(st)
        if latest > int(st.get("last_activity") or 0) and current_time - _mem["saved_act"] >= SAVE_ACT_S:
            st = dict(st, last_activity=latest)
            try:
                _save(st)
                _mem["saved_act"] = current_time
                emit(bridge, st, config)
            except Exception:
                pass
        return None


# ---- service startup ----

def on_start(bridge, config, status):
    """One open from before the restart: it is closed at its last activity
    (and the phone notice goes out with the job_end), unless the machine
    is still in that same job. Without status (DSF does not answer) it is left:
    watch() closes it when there is data. Returns "ninguno"|"sigue"|"cerrado"."""
    with _lock:
        reload()
        _mem["ready"] = True
        st = read_in()
        if not st:
            emit(bridge, None, config)
            return "none"
        follows = status is None
        if status is not None and restart_duet(st, status):
            _close_st(bridge, config, st, "restart_duet", last_activity(st))
            return "closed"
        if status is not None:
            ms = (status.get("state") or {}).get("status")
            if st.get("file"):
                follows = _file_in_progress(status) == st["file"]
            else:
                deadline = deadline_min(config)
                recent = not deadline or _now() - last_activity(st) <= deadline * 60
                follows = ms == "busy" and recent
        if follows:
            _mem["saved_act"] = _now()
            emit(bridge, st, config)
            return "follows"
        _close_st(bridge, config, st, "restart", last_activity(st))
        return "closed"
