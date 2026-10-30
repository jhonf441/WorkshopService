"""
Automatic configuration rollback (WorkshopConfig plugin,
T3.4 -- 2026-10-11; design TallerPlugins/docs-internal/CONFIGURATOR.md 3.8,
3.9 and 3.12).

Flow: the page saves (the API (config) C"commit", which leaves a backup of
the previous state), arms the rollback (C"arm" with the id of that backup and
a deadline) and restarts the board (M999). This thread watches /machine/status:

  - restart seen = state.upTime goes down (or the board goes through "starting" /
    "disconnected");
  - once the startup is finished (status no longer "starting"), it is a FAILURE if:
      * state.startupError is not null. RRF 3.5+ fills it with the first error
        of config.g or of what it calls (RepRap::SaveConfigError ->
        state.startupError {file, line, message}, src/Platform/RepRap.cpp)
        and in SBC mode DSF 3.5+ fills it (ObjectModel.HandleMacroErrorAsync
        while config.g runs; MacroFile sets it back to null when config.g
        starts). Same path in 3.5 and 3.6. In RRF 3.4 or earlier it does not
        exist: the other checks and the deadline remain.
      * status "halted" (the board stopped);
      * it is still "disconnected" WAIT_CONNECTION_S after the restart;
      * an optional check of the arm fails (CAN boards, number of axes,
        heaters, probes) once WAIT_CHECKS_S have passed since startup (CAN
        boards take a few seconds to show up);
  - the deadline expires without C"confirm" -> it is also a failure.

On a failure it restores the backup with the SAME atomic saving as the commit
(handlers/config.py restore: prior copy, temporaries + fsync, journal,
os.replace), restarts the board (M999) to load it and notifies in Activity and
the phone. It never restores or restarts with a job in progress: if one starts
while it is armed, it disarms and notifies. If the board is "busy" (a
macro, a homing) it waits up to WAIT_BUSY_S before restarting.

Without object model data it does nothing (it cannot know whether there is a job).

The state lives in 0:/sys/workshop/data/config-guard.json (it survives a
service restart; times are epoch integers) and is published in
plugins.WorkshopService.data.configGuard for the page (with the seconds
remaining: the browser's clock may not match the Pi's).

Generic: nothing from the workshop is required (liveJob is only
looked at if the service published it).

"""
import job_states
import importlib.util
import os
import re
import threading
import time

import messages
from messages import M, J, B

DEADLINE_S = 300
DEADLINE_MIN_S = 30
DEADLINE_MAX_S = 3600
PERIOD_S = 2            # armed: every 2 s (design 3.12)
PERIOD_INACTIVE_S = 5   # disarmed: only looks whether someone armed
WAIT_CHECKS_S = 20
WAIT_CONNECTION_S = 120
WAIT_BUSY_S = 300

JOB = job_states.ACTIVE
STARTING = ("starting", "disconnected", "updating")
BUSY = ("busy", "changingTool")

FILE = "config-guard.json"

_lock = threading.RLock()
_wake = threading.Event()


# ---- points that the tests change ----

def read_state():
    """Object model completo (/machine/status) o excepcion."""
    import machine_state
    return machine_state.get_status(timeout=3)


def api_thread():
    """handlers/config.py loaded the way main.py loads it (the thread does not go through run)."""
    global _mod_config
    if _mod_config is None:
        route = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handlers", "config.py")
        spec = importlib.util.spec_from_file_location("handler_config_guard", route)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mod_config = mod
    return _mod_config._api()


_mod_config = None


# ---- state in a file ----

def _path(api):
    return os.path.join(api.data_dir(), FILE)


def _load(api):
    import json
    try:
        with open(_path(api), encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict):
            return messages.restored(st)  # its texts are messages again (published as keys)
    except (OSError, ValueError):
        pass
    return {"state": "inactive"}


def _save(api, st):
    import json
    api.write_atomic(_path(api), json.dumps(messages.stored(st), default=str).encode("utf-8"))


def state_public(api, st=None):
    st = st if st is not None else _load(api)
    armed = st.get("state") == "armed"
    current_time = api.current_time()
    return {
        "guard": {
            "state": "armed" if armed else "inactive",
            "snapshot": st.get("snapshot") if armed else None,
            "tx": st.get("tx") if armed else None,
            "deadline_s": int(st.get("deadline_s") or 0) if armed else 0,
            "expires": int(st.get("expires") or 0) if armed else 0,
            "remaining_s": max(0, int(st.get("expires") or 0) - current_time) if armed else 0,
            "restart_seen": bool(st.get("restart_seen")) if armed else False,
            "startup_ok": bool(st.get("startup_ok")) if armed else False,
            "failure": st.get("failure") if armed else None,
            "waiting": st.get("waiting") if armed else None,
            "last": st.get("last"),
        }
    }


def _publish(api, bridge, st=None):
    if bridge is None:
        return
    try:
        bridge.set_status("configGuard", state_public(api, st)["guard"])
    except Exception:
        pass


# ---- avisos (Actividad + celular) ----

def _notify(bridge, config, raw_text, phone=True):
    """Activity (type "config") and, if that type is not active in the
    notifications, to the phone anyway: a rollback cannot happen without
    anyone knowing (like "riesgo"). It never cuts the flow."""
    try:
        import activity
        activity.log_event(bridge, "config", raw_text)
    except Exception:
        pass
    if not phone or config is None:
        return
    try:
        import notifier
        cfg = notifier.get_cfg(config)
        if not cfg["active"] or not cfg["topic"] or cfg["kinds"].get("config") or notifier.muted(cfg):
            return  # off, no topic, muted, or log_event already sent it
        import messages
        lang = messages.language(config)
        title = M("guard_title").text(lang)
        body = raw_text.text(lang) if isinstance(raw_text, messages.Msg) else raw_text
        threading.Thread(
            target=notifier.send, args=(cfg, title, body),
            kwargs={"priority": "high", "tags": "wrench"}, daemon=True,
        ).start()
    except Exception:
        pass


# ---- maquina ----

def _job(s, bridge):
    """Name of the job in progress or None."""
    status = str(((s or {}).get("state") or {}).get("status") or "")
    if status in JOB:
        label = (((s or {}).get("job") or {}).get("file") or {}).get("fileName") or ""
        return os.path.basename(str(label).replace("\\", "/")) or M("config_guard_no_name")
    live = (getattr(bridge, "payload", None) or {}).get("liveJob") or {}
    if isinstance(live, dict) and live.get("active"):
        return str(live.get("name") or "") or M("config_guard_no_name")
    return None


def _restart(bridge):
    if bridge is None:
        return False
    try:
        bridge.send("M999")
        return True
    except Exception:
        return False


def _text_error(err):
    if isinstance(err, dict):
        file = str(err.get("file") or "?")
        return M("guard_startup_error", file=file, line=err.get("line", "?"), message=err.get("message") or "")
    return M("guard_startup_error", file="?", line="?", message=str(err))


def _checks_failed(ch, s):
    """Text with what does not fit, or None. ch comes from the arm (everything optional)."""
    if not isinstance(ch, dict) or not s:
        return None
    missing = []
    if isinstance(ch.get("boards"), list):
        present = {int(b.get("canAddress") or 0) for b in (s.get("boards") or []) if isinstance(b, dict)}
        lost = [str(p) for p in ch["boards"] if isinstance(p, (int, float)) and int(p) not in present]
        if lost:
            missing.append(M("guard_missing_boards", boards=", ".join(lost)))
    counts = (
        ("axes", "guard_count_axes", ((s.get("move") or {}).get("axes") or [])),
        ("heaters", "guard_count_heaters", ((s.get("heat") or {}).get("heaters") or [])),
        ("probes", "guard_count_probes", ((s.get("sensors") or {}).get("probes") or [])),
    )
    for key, label, entries in counts:
        if isinstance(ch.get(key), (int, float)):
            any_present = len([x for x in entries if x])
            if any_present != int(ch[key]):
                missing.append(M(label, expected=int(ch[key]), found=any_present))
    return J(missing, "; ") if missing else None


def _deadline(value, default=DEADLINE_S):
    try:
        return max(DEADLINE_MIN_S, min(DEADLINE_MAX_S, int(float(value))))
    except (TypeError, ValueError):
        return default


# ---- actions (called by handlers/config.py) ----

def arm(api, bridge, config, ident="", tx="", deadline=DEADLINE_S, checks=None, who=""):
    ident = str(ident or "").strip()
    tx = str(tx or "").strip()
    if not ident and tx:
        for snap in api.list_items():  # newest first
            m = api.read_manifest(snap["id"]) or {}
            if m.get("tx") == tx:
                ident = snap["id"]
                break
        if not ident:
            return {"ok": False, "error": M("config_guard_backup_of_save_not_found", tx=tx)}
    if not ident:
        return {"ok": False, "error": M("config_guard_previous_backup_id_missing")}
    if not api.read_manifest(ident):
        return {"ok": False, "error": M("config_guard_backup_does_not_exist", ident=ident)}
    try:
        s = read_state()
    except Exception:
        s = None
    if _job(s, bridge):
        return {"ok": False, "error": M("config_guard_job_running_rollback_not_armed")}
    sec = _deadline(deadline)
    current_time = api.current_time()
    up = ((s or {}).get("state") or {}).get("upTime")
    with _lock:
        previous = _load(api)
        kept = previous.get("state") == "armed" and previous.get("snapshot") != ident
        st = {
            "version": 1,
            "state": "armed",
            # armed without confirming: the oldest backup is the last one that worked
            "snapshot": previous["snapshot"] if kept else ident,
            "tx": tx or (previous.get("tx") if kept else None),
            "who": str(who or ""),
            "deadline_s": sec,
            "armed": current_time,
            "expires": current_time + sec,
            "uptime_last": int(up) if isinstance(up, (int, float)) else None,
            "restart_seen": False,
            "checks": checks if isinstance(checks, dict) else None,
            "last": previous.get("last"),
        }
        _save(api, st)
    _wake.set()
    _publish(api, bridge, st)
    _notify(bridge, config, M("guard_armed", sec=sec, snapshot=st["snapshot"]), phone=False)
    return dict(state_public(api, st), ok=True, snapshot=st["snapshot"], kept=kept)


def confirm(api, bridge, config, who=""):
    with _lock:
        st = _load(api)
        if st.get("state") != "armed":
            return dict(state_public(api, st), ok=True, armed=False)
        new = {"state": "inactive", "last": {
            "result": "confirmed", "snapshot": st.get("snapshot"), "ts": api.current_time(), "who": str(who or ""),
        }}
        _save(api, new)
    _publish(api, bridge, new)
    _notify(bridge, config, M("guard_confirmed", snapshot=st.get("snapshot")), phone=False)
    return dict(state_public(api, new), ok=True, armed=True)


def _revert(api, bridge, config, st, reason, result, who=""):
    """Restores st["snapshot"], restarts and notifies. Leaves the state inactive
    (it never retries on its own: a damaged backup is not fixed by waiting)."""
    ident = st.get("snapshot")
    r = api.restore(ident, reason=reason, who=who or "rollback", bridge=bridge, register=False)
    current_time = api.current_time()
    if r.get("ok"):
        restarted = _restart(bridge)
        if restarted:
            raw_text = M("guard_restored_restarted", id=ident, reason=reason)
        else:
            raw_text = M("guard_restored_not_restarted", id=ident, reason=reason)
        last = {"result": result, "reason": reason, "snapshot": ident, "ts": current_time,
                  "backup_previous": r.get("snapshot"), "files": r.get("files") or [], "restarted": restarted}
    else:
        raw_text = M("guard_restore_failed", id=ident, error=r.get("error"))
        last = {"result": "error", "reason": reason, "snapshot": ident, "ts": current_time, "error": r.get("error")}
    new = {"state": "inactive", "last": last}
    _save(api, new)
    _publish(api, bridge, new)
    _notify(bridge, config, raw_text)
    return dict(state_public(api, new), ok=bool(r.get("ok")), error=None if r.get("ok") else r.get("error"),
                restored=ident, backup_previous=r.get("snapshot"), restarted=last.get("restarted", False))


def revert_by_hand(api, bridge, config, who=""):
    """C"rollback": right now, without waiting for the deadline (ignoring the lock: it is the
    emergency exit of a configuration that does not work)."""
    try:
        s = read_state()
    except Exception:
        return {"ok": False, "error": M("config_guard_could_not_read_machine_state_nothing")}
    if _job(s, bridge):
        return {"ok": False, "error": M("config_guard_job_running_nothing_restored")}
    with _lock:
        st = _load(api)
        if st.get("state") != "armed":
            return {"ok": False, "error": M("config_guard_no_rollback_armed")}
        return _revert(api, bridge, config, st, M("guard_requested_by_hand"), "rollback", who)


def restore_backup(api, bridge, config, ident, deadline=0, restart=False, who="", owner=""):
    """C"restore": any backup. With a deadline it arms the rollback to the
    copy of what there was; without one, an armed rollback is disarmed
    (the manual restore wins)."""
    try:
        s = read_state()
    except Exception:
        return {"ok": False, "error": M("config_guard_could_not_read_machine_state_nothing")}
    if _job(s, bridge):
        return {"ok": False, "error": M("config_guard_job_running_nothing_restored")}
    try:
        sec = int(float(deadline or 0))
    except (TypeError, ValueError):
        sec = 0
    with _lock:
        r = api.restore(ident, who=who, bridge=bridge, owner=str(owner or ""))
        if not r.get("ok"):
            return r
        st = _load(api)
        if sec > 0 and r.get("snapshot"):
            armed = arm(api, bridge, config, ident=r["snapshot"], deadline=sec, who=who)
            if not armed.get("ok"):
                r["notice"] = armed.get("error")
        elif st.get("state") == "armed":
            st = {"state": "inactive", "last": {
                "result": "reemplazado", "snapshot": st.get("snapshot"), "ts": api.current_time(), "restored": ident,
            }}
            _save(api, st)
            _publish(api, bridge, st)
    r["restarted"] = _restart(bridge) if restart else False
    r.update(state_public(api))
    return r


# ---- the thread ----

def step(api, bridge, config):
    """One pass of the watching. Returns what happened (for the tests
    and the Services detail): None (disarmed), "without_data", "armed",
    "waiting", "disarmed_job", "restored", "error"."""
    with _lock:
        st = _load(api)
        if st.get("state") != "armed":
            return None
        try:
            s = read_state()
        except Exception:
            s = None
        if not isinstance(s, dict):
            _publish(api, bridge, st)
            return "without_data"
        current_time = api.current_time()
        state = s.get("state") or {}
        status = str(state.get("status") or "")

        job = _job(s, bridge)
        if job:
            new = {"state": "inactive", "last": {
                "result": "disarmed_job", "snapshot": st.get("snapshot"), "ts": current_time, "job": job,
            }}
            _save(api, new)
            _publish(api, bridge, new)
            _notify(bridge, config, M("guard_cancelled_job", job=job))
            return "disarmed_job"

        up = state.get("upTime")
        up = int(up) if isinstance(up, (int, float)) else None
        if not st.get("restart_seen"):
            previous = st.get("uptime_last")
            if status in STARTING or (up is not None and previous is not None and up < previous):
                st["restart_seen"] = True
                st["restart_ts"] = current_time
        if up is not None:
            st["uptime_last"] = up

        if st.get("restart_seen") and not st.get("failure"):
            failure = None
            if status == "disconnected":
                since = st.setdefault("disconnected_since", current_time)
                if current_time - since >= WAIT_CONNECTION_S:
                    failure = M("guard_board_not_back")
            elif status in STARTING:
                st.pop("disconnected_since", None)
            else:
                st.pop("disconnected_since", None)
                st.setdefault("arranco_ts", current_time)
                if state.get("startupError"):
                    failure = _text_error(state.get("startupError"))
                elif status == "halted":
                    failure = M("guard_board_halted")
                else:
                    bad = _checks_failed(st.get("checks"), s)
                    if bad:
                        if current_time - st["arranco_ts"] >= WAIT_CHECKS_S:
                            failure = bad
                    elif not st.get("startup_ok"):
                        st["startup_ok"] = current_time
            if failure:
                st["failure"] = failure

        if not st.get("failure") and current_time >= int(st.get("expires") or 0):
            st["failure"] = M("guard_nobody_confirmed", sec=int(st.get("deadline_s") or 0))

        if st.get("failure"):
            if status in BUSY and current_time - st.setdefault("busy_since", current_time) < WAIT_BUSY_S:
                st["waiting"] = "busy"
                _save(api, st)
                _publish(api, bridge, st)
                return "waiting"
            r = _revert(api, bridge, config, st, st["failure"], "restored")
            return "restored" if r.get("ok") else "error"

        st.pop("busy_since", None)
        st.pop("waiting", None)
        _save(api, st)
        _publish(api, bridge, st)
        return "armed"


# what step() returned, as the detail of the Services page
_DETAIL = {None: "config_guard_state_disarmed", "without_data": "config_guard_state_without_data", "armed": "config_guard_state_armed",
           "waiting": "config_guard_state_waiting", "disarmed_job": "config_guard_state_disarmed_job",
           "restored": "config_guard_state_restored", "error": "config_guard_state_error"}


def run_loop(bridge, config):
    import heartbeats
    try:
        _publish(api_thread(), bridge)
    except Exception as e:
        heartbeats.error("config_guard", e)
    while True:
        armed = False
        try:
            r = step(api_thread(), bridge, config)
            armed = r in ("armed", "waiting", "without_data")
            heartbeats.detail("config_guard", M(_DETAIL.get(r, "config_guard_state_disarmed")))
            heartbeats.ok("config_guard")
        except Exception as e:
            heartbeats.error("config_guard", e)
        _wake.wait(PERIOD_S if armed else PERIOD_INACTIVE_S)
        _wake.clear()
