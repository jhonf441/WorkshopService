"""
Internal implementation of the API operation(s) motors.enable, motors.disable, motors.reread (api_ops.py maps their named
arguments to the one-letter parameters below).

Enables or disables motors (axes and extruders) with M17 / M18, never with
a job in progress (file or live job) nor with the
machine busy. Disabling an axis removes its homing. See
dsf/motors_enable.py (what RepRapFirmware allows and what it does not).

Usage: <params> S"disable"|"enable" A"X,Z,E0"|"all"
     <params> S"reread"     re-reads now whether each driver is enabled
     <params> S"watch"      heartbeat: the Motors page is visible (every ~10 s).
                                   Without one for 30 s motor_poller stops reading the drivers.
Answers JSON: {ok, accion, comando, ejes, extrusores, todos, error, respuesta}.
Alias: P"motors" S"deshabilitar"|"habilitar"|"releer".

"""
import json

import motors_enable
from messages import M


def _reread():
    try:
        import motor_poller

        motor_poller.request_reread()
    except Exception:
        pass


def _note(r, status):
    """The poller keeps which motors are released (risk bar, lights, the page): it is told at once, before the next
    reading (and it is the only source for drivers of CAN boards, whose state cannot be read)."""
    try:
        import motor_poller

        keys = motor_poller.status_keys(status) if r["all"] else list(r["axes"]) + ["E%d" % i for i in r["extruders"]]
        motor_poller.note_request(r["action"], keys)
    except Exception:
        pass


def run(params, bridge, config):
    action = motors_enable.ACTIONS.get(str(params.get("S", "")).strip().lower())
    if action == "watch":
        import viewers

        viewers.heartbeat("motors")
        return json.dumps({"ok": True, "action": "watch", "sleep_s": viewers.TTL_S})
    if action == "reread":
        _reread()
        return json.dumps({"ok": True, "action": "reread"})

    import machine_state

    try:
        status = machine_state.get_status(timeout=5)
    except Exception as e:
        return json.dumps({"ok": False, "error": M("motors_could_not_read_machine_state", e=e)}, ensure_ascii=False)
    in_live = (getattr(bridge, "payload", {}) or {}).get("liveJob")
    r = motors_enable.plan(status, params.get("S"), params.get("A", ""), in_live)
    if not r["ok"]:
        return json.dumps(r, ensure_ascii=False)

    try:
        resp = bridge.send(r["command"])
    except Exception as e:
        r.update(ok=False, error=M("motors_board_did_not_answer", command=r['command'], e=e))
        return json.dumps(r, ensure_ascii=False)
    r["response"] = str(resp or "").strip()
    if "rror" in r["response"]:
        r.update(ok=False, error=M("motors_board_rejected", command=r['command'], response=r['response']))
        return json.dumps(r, ensure_ascii=False)

    _note(r, status)
    _reread()
    try:
        import activity

        activity.log_event(bridge, "notice", motors_enable.description(r))
    except Exception:
        pass
    return json.dumps(r, ensure_ascii=False)
