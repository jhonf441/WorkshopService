"""
Single owner of the movement (2026-10-13, docs/api/DESIGN.md section 5;
design in TallerPlugins/docs-internal/AUDITORIA-MOTION.md section 4).

One place answers "may <origin> move / change the geometry NOW?" and says why
not. Before, every piece decided by itself (jog backend, jog page, Workbench,
Vision, configurator...) with its own copy of the rules and its own delay.

Inputs, all in memory (nothing is asked to DSF here):
  - the machine status of the single subscription (state_machine) or the
    status cache of the jog loop;
  - the live job (job_live: open, name, last activity);
  - the activity of the G-code bridge (jog_move: bridge-state.json and the
    M3/M4/M5 of other programs on SBC);
  - the jog (a gesture in progress counts as an implicit reservation);
  - the reservations taken with motion.reserve.

States (code): stopped, file_job, file_paused, live_active, live_idle,
bridge_active, free; plus "reserved" when another origin holds a reservation.
Action classes: stop, move, job, sequence, geometry, power, channel.
Decision: "allow", "confirm" (only with the person's OK) or "deny".

Published (only when it changes) in plugins.WorkshopService.data.motion so
the pages can disable their buttons with the reason without polling.
"""
import job_states
import secrets
import threading
import time
from messages import M

RECENT_S = 20          # default of "release_s": activity of a live job / of the bridge newer than this = "active"
RECENT_MIN_S = 3
RECENT_MAX_S = 120
MODES = ("protegido", "duet")
CONFIRM_S = 60         # an accepted confirmation lasts this long after its last use
RESERVE_DEFAULT_S = 30
RESERVE_MAX_S = 900
JOG_LEASE_S = 3        # the implicit reservation of a jog gesture: renewed by every update of the held control
NOTICE_S = 60          # how long the "taken over" notice for the previous owner stays published
TAKE_OVER_ROLES = ("technician", "admin")
JOB_STATES = ("file_job", "file_paused", "live_active", "bridge_active")

STOPPED = {"halted", "off", "disconnected", "starting", "updating", "flashing"}
FILE_STATES = job_states.MOVING_FILE

CLASSES = ("stop", "move", "job", "sequence", "geometry", "power", "channel")

# decision table: class -> state -> decision ("reserved" is handled apart)
TABLE = {
    "stop": {},  # always allow
    "move": {"file_job": "deny", "file_paused": "allow", "live_active": "deny", "live_idle": "confirm",
             "bridge_active": "deny", "stopped": "deny"},
    "job": {"file_job": "deny", "file_paused": "deny", "live_active": "deny", "live_idle": "deny",
            "bridge_active": "deny", "stopped": "deny"},
    "sequence": {"file_job": "deny", "file_paused": "deny", "live_active": "deny", "live_idle": "deny",
                 "bridge_active": "deny", "stopped": "deny"},
    "geometry": {"file_job": "deny", "file_paused": "deny", "live_active": "deny", "live_idle": "deny",
                 "bridge_active": "confirm", "stopped": "deny"},
    "power": {"free": "confirm", "file_job": "confirm", "file_paused": "confirm", "live_active": "confirm",
              "live_idle": "confirm", "bridge_active": "confirm", "stopped": "allow"},
    "channel": {"file_job": "deny", "file_paused": "deny", "live_active": "deny", "live_idle": "deny",
                "bridge_active": "deny", "stopped": "allow"},
}

_lock = threading.Lock()
_reservations = {}   # token -> {origin, action, text, until, device, user, since, lease}
_confirmed = {}      # (origin, class, device, user) -> {"until": monotonic, "job": key}
_pub = {"last": None}
_notice = {"v": None}  # the last take over: shown to the previous owner for NOTICE_S


def _actor(a):
    """Normalized caller {device, user, role}: who is asking (browser id, name of the person, role). Empty = an internal
    call or the open mode (compatibility): it matches any owner of the same origin, like before the identities existed."""
    a = a or {}
    return {"device": str(a.get("device") or "")[:40], "user": str(a.get("user") or "")[:40], "role": str(a.get("role") or "")}


def _same_owner(r, origin, a):
    """True when the reservation r belongs to this caller: same origin and, when both sides know them, same device and person."""
    if r["origin"] != str(origin or "?")[:40]:
        return False
    if r.get("device") and a["device"] and r["device"] != a["device"]:
        return False
    return not (r.get("user") and a["user"] and r["user"] != a["user"])


def _since_text(ts):
    return time.strftime("%H:%M", time.localtime(ts or time.time()))


def held_reason(r):
    """Why somebody else may not move: names the person (or "another device") and since when, when the owner is known."""
    if r.get("user") or r.get("device"):
        who = r["user"] if r.get("user") else M("motion_owner_other_device")
        return M("motion_owner_held_by", who=who, since=_since_text(r.get("since")))
    return M("motion_owner_using", who=r["origin"] + (f": {r['text']}" if r.get("text") else ""))


def _bridge_data(bridge):
    return (getattr(bridge, "payload", {}) or {}) if bridge is not None else {}


def _status():
    """state.status: from the jog loop cache (also what the tests set) or the subscription."""
    try:
        import jog_move
        c = jog_move._cache_ref[0]
        if c and c.get("status"):
            return c.get("status")
    except Exception:
        pass
    try:
        import machine_state
        m = machine_state.last_state() or {}
        return ((m.get("state") or {}).get("status")) or None
    except Exception:
        return None


def _live(bridge):
    """(open, name, idle_s or None) of the live job."""
    v = _bridge_data(bridge).get("liveJob")
    is_open = bool(v.get("active")) if isinstance(v, dict) else bool(v)
    if not is_open:
        return False, None, None
    label = v.get("name") if isinstance(v, dict) else None
    does = None
    try:
        import jog_move
        does = jog_move._live_does_s(bridge)
    except Exception:
        does = None
    return True, label, does


def _bridge_age():
    try:
        import jog_move
        return jog_move.bridge_activity_does_s()
    except Exception:
        return None


def _bridge_clients():
    try:
        import jog_move
        return jog_move._clients_bridge()
    except Exception:
        return 0


def _job_file():
    try:
        import machine_state
        m = machine_state.last_state() or {}
        f = ((m.get("job") or {}).get("file") or {}).get("fileName")
        return str(f).split("/")[-1] if f else None
    except Exception:
        return None


_cfg = {"ref": None}


def configure(config):
    """The service config (shared dict, edited live): config["movimiento"] = {"bloqueo": "protegido"|"duet", "release_s": int}.
    One setting for everything that asks this module (jog, Workbench, Vision, frame, configurator...)."""
    _cfg["ref"] = config


def settings():
    """(mode, release_s): "protegido" = a live job / the bridge block the movement and release_s is the quiet time that frees it;
    "duet" = like Duet / DWC: only file jobs (and a stopped machine) block."""
    c = ((_cfg["ref"] or {}).get("movement") or {}) if isinstance(_cfg["ref"], dict) else {}
    kind = c.get("block") if c.get("block") in MODES else "protegido"
    try:
        lib = int(float(c.get("release_s", RECENT_S)))
    except (TypeError, ValueError):
        lib = RECENT_S
    return kind, max(RECENT_MIN_S, min(RECENT_MAX_S, lib))


def _idle_s():
    try:
        import live_job
        return live_job.stop_s(_cfg["ref"] or {})
    except Exception:
        return 30


def _mode_duet():
    return settings()[0] == "duet"


def _reason(m):
    """reason: a message (an API answer gives it in the language of the request; published, the pages translate it)."""
    return {"reason": m}


def base_state(bridge):
    """{state, reason, job, bridge} without reservations.
    The Spanish reasons are the ones the jog shows (and its tests check)."""
    status = _status()
    job = {"kind": None, "name": None, "idle_s": None}
    b_age = _bridge_age()
    out = {"state": "free", "reason": "", "job": job, "status": status,
           "bridge": {"last_order_s": None if b_age is None else int(b_age)}}
    if status in STOPPED:
        out.update(state="stopped", **_reason(M("motion_owner_machine_not_ready", status=status)))
        return out
    if status in FILE_STATES:
        job.update(kind="file", name=_job_file())
        out.update(state="file_job", **_reason(M("motion_owner_file_job_running", status=status)))
        return out
    # priority (same order the jog always used): stopped > file job > bridge activity > live job > paused
    is_open, label, hv = _live(bridge)
    if is_open:
        job.update(kind="live", name=label, idle_s=None if hv is None else int(hv))
    elif status == "paused":
        job.update(kind="file", name=_job_file())
    if _mode_duet():
        # "duet" mode (jog.json "bloqueo"): like Duet / DWC, a live job or the bridge never blocks; only file jobs and a stopped machine do
        if status == "paused":
            out.update(state="file_paused", **_reason(M("jog_move_file_job_paused")))
        return out
    lib = settings()[1]
    if b_age is not None and b_age < lib:
        out.update(state="bridge_active", **_reason(M("motion_owner_g_code_bridge_sent_orders_s", int=int(b_age), lib=lib)))
        return out
    if is_open:
        which = f" ({label})" if label else ""
        if hv is not None and hv < lib:
            out.update(state="live_active", **_reason(M("motion_owner_live_job_active_ago_wait", which=which, ago=int(hv), lib=lib)))
        else:
            out.update(state="live_idle", **_reason(M("motion_owner_there_live_job_open_quiet_more", which=which, lib=lib)))
        return out
    if status == "paused":
        # moving is allowed while paused (RRF restores the positions on resume); geometry is not
        out.update(state="file_paused", **_reason(M("jog_move_file_job_paused")))
    return out


def _expire(now=None):
    now = time.monotonic() if now is None else now
    for t in [t for t, r in _reservations.items() if r["until"] <= now]:
        _reservations.pop(t, None)
    for k in [k for k, c in _confirmed.items() if c["until"] <= now]:
        _confirmed.pop(k, None)


def _other_owner(origin, token=None, actor=None):
    """The reservation (or jog gesture) of someone else, or None."""
    _expire()
    a = _actor(actor)
    for t, r in _reservations.items():
        if t != token and not _same_owner(r, origin, a):
            return dict(r, token=None)
    if origin != "jog":
        try:
            import jog_move
            if jog_move.gesture_active():
                return {"origin": "jog", "action": "move", "text": "", "until": time.monotonic() + 1}
        except Exception:
            pass
    return None


def _job_key(st):
    j = st.get("job") or {}
    return (j.get("kind"), j.get("name"))


def evaluate(bridge, action="move", origin="", confirm=False, token=None, actor=None, take_over=False):
    """{"decision", "code", "reason", "state"} for that class of action.
    confirm=True: the person accepted the confirmation (remembered CONFIRM_S
    for that origin, class, device, person and job). take_over=True does not stop at the reservation of another owner
    (take_over() decides before whether that is allowed)."""
    if action not in CLASSES:
        action = "move"
    st = base_state(bridge)
    code = st["state"]
    a = _actor(actor)
    with _lock:
        owner = None if (action == "stop" or take_over) else _other_owner(origin, token, a)
        if owner is not None:
            return dict({"decision": "deny", "code": "reserved", "state": st}, **_reason(held_reason(owner)))
        dec = "allow" if action == "stop" else TABLE[action].get(code, "allow")
        # supply off ("off"): changing the geometry (machine mode, origins) moves nothing, so it is allowed, like the pages do
        # ("settings" in machine-free.js); a board that is halted, starting or updating still denies it
        if action == "geometry" and code == "stopped" and st.get("status") == "off":
            dec = "allow"
        if dec == "confirm":
            k = (origin, action, a["device"], a["user"])
            now = time.monotonic()
            c = _confirmed.get(k)
            if confirm:
                _confirmed[k] = {"until": now + CONFIRM_S, "job": _job_key(st)}
                dec = "allow"
            elif c and c["until"] > now and c["job"] == _job_key(st):
                c["until"] = now + CONFIRM_S  # still using it: renew
                dec = "allow"
    return {"decision": dec, "code": code, "reason": st["reason"] if dec != "allow" else "", "state": st}


def jog_block(bridge, actor=None):
    """(level, reason) for the jog backend, WITHOUT the remembered confirmations
    (the jog keeps its own, see jog_move.confirmar): level "" = may move,
    "bloquear" = no, "confirmar" = only if the person accepts."""
    with _lock:
        owner = _other_owner("jog", actor=actor)
    if owner is not None:
        return "block", held_reason(owner)
    st = base_state(bridge)
    dec = TABLE["move"].get(st["state"], "allow")
    if dec == "deny":
        return "block", st["reason"]
    if dec == "confirm":
        return "confirm", st["reason"]
    return "", ""


def reserve(bridge, origin, action="sequence", text="", seconds=RESERVE_DEFAULT_S, confirm=False, actor=None, take_over=False):
    a = _actor(actor)
    d = evaluate(bridge, action, origin, confirm, actor=a, take_over=take_over)
    if d["decision"] != "allow":
        return d
    secs = max(1, min(RESERVE_MAX_S, int(seconds or RESERVE_DEFAULT_S)))
    token = secrets.token_hex(6)
    evicted = []
    with _lock:
        if take_over:
            evicted = _evict_others(origin, a)
        _reservations[token] = {"origin": str(origin or "?")[:40], "action": action, "text": str(text or "")[:120],
                                "until": time.monotonic() + secs, "device": a["device"], "user": a["user"], "since": time.time(),
                                "lease": bool(take_over)}  # a taken over control is short and ends with the release of the jog
    publish(bridge, force=True)
    return dict(d, token=token, seconds=secs, evicted=evicted)


def _evict_others(origin, a):
    """Drops the reservations of other owners (inside the lock); returns who they were."""
    out = []
    for t in [t for t, r in _reservations.items() if not _same_owner(r, origin, a)]:
        r = _reservations.pop(t)
        out.append({"origin": r["origin"], "user": r.get("user", ""), "device": r.get("device", "")})
    return out


def take_over(bridge, origin, action="sequence", text="", seconds=RESERVE_DEFAULT_S, actor=None):
    """Takes the control from whoever has it (a technician or an administrator). Never during a file job, a live job or the
    bridge unless the caller is an administrator. The previous owner gets a notice (data.motion.notice) and its jog gesture
    is stopped. The audit row is the one of the API call (motion.take_over is not a plain read)."""
    a = _actor(actor)
    if a["role"] not in TAKE_OVER_ROLES:
        return {"decision": "deny", "code": "forbidden", "reason": M("motion_owner_take_over_role")}
    st = base_state(bridge)
    if st["state"] in JOB_STATES and a["role"] != "admin":
        return {"decision": "deny", "code": "job_running", "reason": M("motion_owner_take_over_job"), "state": st}
    with _lock:
        _expire()
        before = [dict(r) for r in _reservations.values() if not _same_owner(r, origin, a)]
    try:
        import jog_move
        gesture = jog_move.gesture_active()
        if before or gesture:
            jog_move.stop_all()
    except Exception:
        gesture = False
    if not before and not gesture:
        return dict(reserve(bridge, origin, action, text, seconds, actor=a), taken=False)
    d = reserve(bridge, origin, action, text, seconds, actor=a, take_over=True)
    if d.get("decision") == "allow":
        prev = before[0] if before else {}
        _notice["v"] = {"kind": "taken_over", "from_user": prev.get("user", ""), "from_device": prev.get("device", "")[:8],
                        "by": a["user"], "by_device": a["device"][:8], "at": int(time.time()), "until": time.monotonic() + NOTICE_S}
        publish(bridge, force=True)
    return dict(d, taken=True)


def _not_owner(r, a):
    return bool(r.get("device") and a["device"] and r["device"] != a["device"]) or bool(r.get("user") and a["user"] and r["user"] != a["user"])


def renew(bridge, token, seconds=RESERVE_DEFAULT_S, actor=None):
    a = _actor(actor)
    with _lock:
        _expire()
        r = _reservations.get(token)
        if not r:
            return {"ok": False, "code": "expired", "reason": M("motion_owner_reservation_has_already_expired")}
        if _not_owner(r, a):
            return {"ok": False, "code": "not_owner", "reason": held_reason(r)}
        r["until"] = time.monotonic() + max(1, min(RESERVE_MAX_S, int(seconds or RESERVE_DEFAULT_S)))
    return {"ok": True, "token": token}


def release(bridge, token, actor=None):
    a = _actor(actor)
    with _lock:
        r = _reservations.get(token)
        if r and _not_owner(r, a):
            return {"ok": False, "released": False, "code": "not_owner", "reason": held_reason(r)}
        r = _reservations.pop(token, None)
    if r:
        publish(bridge, force=True)
    return {"ok": True, "released": bool(r)}


# -- jog: the implicit reservation of a held control, per device --

def jog_conflict(actor):
    """Reason text when ANOTHER device has the jog (a lease of origin "jog"), else "". Reservations of other origins are not
    this: they keep the old path (jog_block)."""
    a = _actor(actor)
    with _lock:
        _expire()
        for r in _reservations.values():
            if r["origin"] == "jog" and not _same_owner(r, "jog", a):
                return held_reason(r)
    return ""


def jog_claim(bridge, actor):
    """The caller holds the jog: creates or renews its lease (JOG_LEASE_S from now)."""
    a = _actor(actor)
    created = False
    with _lock:
        _expire()
        mine = [r for r in _reservations.values() if r.get("lease") and _same_owner(r, "jog", a)]
        if mine:
            mine[0]["until"] = time.monotonic() + JOG_LEASE_S
        else:
            _reservations["jog-" + secrets.token_hex(4)] = {
                "origin": "jog", "action": "move", "text": "", "until": time.monotonic() + JOG_LEASE_S,
                "device": a["device"], "user": a["user"], "since": time.time(), "lease": True}
            created = True
    if created:
        publish(bridge, force=True)


def jog_release(bridge, actor=None, everyone=False):
    """The jog is released: drops the lease of the caller (or all of them: a stop that is not the release of one device)."""
    a = _actor(actor)
    with _lock:
        gone = [t for t, r in _reservations.items() if r.get("lease") and (everyone or _same_owner(r, "jog", a))]
        for t in gone:
            _reservations.pop(t, None)
    if gone:
        publish(bridge, force=True)
    return bool(gone)


def homing_needed():
    """True when the firmware does not allow moves before homing (move.noMovesBeforeHoming) and some axis is not homed yet: the bridge refuses the
    orders that move or fire the laser in that case (a job sent before the homing would otherwise run, from the middle, as soon as the homing ends)."""
    try:
        import machine_state
        m = machine_state.last_state() or {}
        mv = m.get("move") or {}
        if mv.get("noMovesBeforeHoming") is False:
            return False
        axes = [a for a in (mv.get("axes") or []) if a and a.get("visible", True)]
        return bool(axes) and not all(a.get("homed") for a in axes)
    except Exception:
        return False


def snapshot(bridge):
    """What is published (no ages that change every second)."""
    st = base_state(bridge)
    with _lock:
        _expire()
        res = list(_reservations.values())
        owners = [{"origin": r["origin"], "action": r["action"], "text": r["text"], "name": r.get("user", ""),
                   "device": r.get("device", "")[:8], "since": int(r.get("since") or 0),
                   "until_s": int(r["until"] - time.monotonic())} for r in res]
    try:
        import jog_move
        if jog_move.gesture_active():
            owners.append({"origin": "jog", "action": "move", "text": "", "until_s": 1})
    except Exception:
        pass
    for i, o in enumerate(owners):  # ready-made reason for the pages (a message: each page shows it in its language)
        if i < len(res):
            o["reason"] = held_reason(res[i])
        else:
            o["reason"] = M("motion_owner_using", who=o["origin"] + (f": {o['text']}" if o.get("text") else ""))
    j = st["job"]
    return {"state": st["state"], "reason": st["reason"],
            "owner": owners[0] if owners else None, "notice": _notice_now(),
            "job": {"kind": j.get("kind"), "name": j.get("name")},
            "bridge": {"clients": _bridge_clients(), "active": st["state"] == "bridge_active"},
            "status": st.get("status"), "needs_homing": homing_needed(), "v": 1,
            "settings": {"mode": settings()[0], "release_s": settings()[1], "idle_s": _idle_s()}}


def _notice_now():
    n = _notice["v"]
    if not n or n["until"] <= time.monotonic():
        return None
    return {k: v for k, v in n.items() if k != "until"}


def publish(bridge, force=False):
    if bridge is None:
        return
    s = snapshot(bridge)
    o = s["owner"] or {}
    key = (s["state"], s["reason"], o.get("origin"), o.get("text"), o.get("name"), o.get("device"), o.get("since"), (s["notice"] or {}).get("at"),
           s["job"]["kind"], s["job"]["name"], s["bridge"]["clients"], s["status"])
    if not force and key == _pub["last"]:
        return
    _pub["last"] = key
    try:
        bridge.set_status("motion", s)
    except Exception:
        pass


def run_loop(bridge, config):
    """Publishes plugins.<Id>.data.motion when it changes (checked every second)."""
    import heartbeats
    configure(config)
    while True:
        try:
            publish(bridge)
            heartbeats.ok("motion")
        except Exception as e:  # noqa: BLE001
            heartbeats.error("motion", e)
        time.sleep(1.0)


def reset():
    """For the tests."""
    with _lock:
        _reservations.clear()
        _confirmed.clear()
    _notice["v"] = None
    _pub["last"] = None
