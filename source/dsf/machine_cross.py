"""`machine.mark_cross` of Machine v2 (phase 2, design 2.7): the laser <-> pointer assistant ON THE SERVER.

It replaces the macros lasermark.g + the browser's G-code. Three actions:

    mark     marks a 4 mm cross with the LASER at low power where the head is now (G91, X +2 -4 +2 and Y +2 -4 +2 with the power only on the
             long strokes, then G90) and remembers the head position. Returns {"head": {x, y}, ...}.
    capture  the person has brought the POINTER to the centre of the cross with the jog: reads the head now and computes
             correction = head when marking - head now (the beam hits the bed at machine position - correction). With `save: true` the
             correction is written to the settings store `laser` (key `correction` {x, y, date}: the same field the Workbench and the Jog read)
             and stored in the calibration history (kind `laser.pointer`).
    clear    forgets the mark.

What it honours (laser_guard.py and the macro laserguard.g that it replaces): Laser mode, X and Y homed, power 1 to 10 % (more is refused),
the declared interlocks (lid, extraction, key) closed, no job and nobody else holding the movement (a reservation of class sequence for the
time of the mark), one mark at a time. The laser guard is armed before the first stroke and gets its M5 at the end, so a power left set by a
failure is turned off by the guard loop of main.py even if this code dies; the `finally` sends M5 and G90 whatever happens.

ASSUMPTION (unverified): S is sent as power% * 2.55, the scale of `M452 R255` of the workshop machine (S0..S255). A machine configured with
another PWM range needs its own scale.
"""
import threading
import time

import audit
import identity
import laser_guard
import machine_geometry as geo
import machine_parsers as parsers
import machine_store
import motion_owner
import settings_store
from messages import M
from workshop_api import ApiError, Arg, MOTION, Op

MAX_POWER_PCT = 10.0
DEFAULT_POWER_PCT = 3.0
S_PER_PCT = 2.55
HALF_MM = 2.0                 # the cross is 2 x 2 mm on each side of the centre: 4 mm strokes
FEED = 300                    # mm/min, the speed of lasermark.g
RESERVE_S = 30
_busy = threading.Lock()
_mark = {"v": None}


def _full_profile():
    import machine_profile
    return machine_profile.load()


def refusal(om, caps, profile, power):
    """Code of the first reason the cross must not be marked, or None. Pure."""
    if not isinstance(power, (int, float)) or isinstance(power, bool) or not 1 <= power <= MAX_POWER_PCT:
        return "bad_power"
    if not om:
        return "no_model"
    if ((om.get("state") or {}).get("machineMode")) != "Laser":
        return "not_laser_mode"
    if not (((caps or {}).get("capabilities") or {}).get("laser") or {}).get("present"):
        return "no_laser"
    ax = geo.axes_by_letter(om)
    if not (ax.get("X") or {}).get("homed") or not (ax.get("Y") or {}).get("homed"):
        return "not_homed"
    import interlocks
    if interlocks.blocking(profile, om) is not None:
        return "interlock_open"
    return None


def strokes(power):
    """The lines of the cross: [(axis, distance, S)] relative moves; the power only on the long strokes."""
    s = round(power * S_PER_PCT, 1)
    return [("X", HALF_MM, 0), ("X", -2 * HALF_MM, s), ("X", HALF_MM, 0), ("Y", HALF_MM, 0), ("Y", -2 * HALF_MM, s), ("Y", HALF_MM, 0)]


def _head(conn, chan, om):
    """{x, y} machine position read from the board now."""
    out = {}
    for letter in "XY":
        res = parsers.parse_json_result(str(conn.perform_simple_code(_axis_line(geo.axis_index(om, letter)), channel=chan, async_exec=False) or ""))
        pos = geo.num(res.get("machinePosition")) if isinstance(res, dict) else None
        if pos is None:
            raise ApiError("failed", M("machine_cross_no_position"), reason="no_position")
        out[letter.lower()] = pos
    return out


def _axis_line(index):
    import machine_gcode
    return machine_gcode.render("axis_state", index=index)


def _send(conn, chan, template, **numbers):
    import machine_gcode
    return str(conn.perform_simple_code(machine_gcode.render(template, **numbers), channel=chan, async_exec=False) or "")


def mark(args, ctx):
    import machine_ops as mo
    power = float(args.get("power") or DEFAULT_POWER_PCT)
    if not ctx.get("confirm"):                                    # the laser fires: level 3 confirmation, only for the mark (not capture / clear)
        raise ApiError("confirm_required", M("machine_cross_confirm"), confirm=mo._confirm_info(None, "machine.mark_cross"))
    om, caps = mo.model(), mo._caps()
    why = refusal(om, caps, _full_profile(), power)
    if why:
        raise ApiError("refused", M("machine_cross_refuse_" + why, max=MAX_POWER_PCT), reason=why)
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])
    if not _busy.acquire(blocking=False):
        raise ApiError("refused", M("machine_cross_busy"), reason="busy_mark")
    who = identity.actor(ctx)
    bridge = mo._bridge()
    d = motion_owner.reserve(bridge, mo.ORIGIN, "sequence", "mark_cross", RESERVE_S, actor=who)
    if d.get("decision") != "allow":
        _busy.release()
        raise ApiError("motion_denied", d.get("reason") or "", motion={"decision": "deny", "code": d.get("code")})
    conn = chan = None
    try:
        conn, chan = mo.open_connection(), mo.channel()
        _send(conn, chan, "wait_moves")
        head = _head(conn, chan, om)
        return _fire(conn, chan, head, power, who)
    finally:
        _cleanup(conn, chan)
        try:
            motion_owner.release(bridge, d["token"], actor=who)
        finally:
            _busy.release()


def _fire(conn, chan, head, power, who):
    laser_guard.arm(time.monotonic())                    # if anything below fails to turn the laser off, the guard loop will
    _send(conn, chan, "rel_mode")
    for axis, dist, s in strokes(power):
        _send(conn, chan, "cross_move", axis=axis, d=dist, feed=FEED, power=s)
    _send(conn, chan, "wait_moves")
    stamp = int(time.time())
    _mark["v"] = {"x": head["x"], "y": head["y"], "ts": stamp, "power_pct": power, "user": who["user"]}
    return {"action": "mark", "head": head, "power_pct": power, "s": round(power * S_PER_PCT, 1), "size_mm": 4, "marked_at": stamp}


def _cleanup(conn, chan):
    """Whatever happened: laser off, absolute mode, wait for the moves; the laser guard learns the M5."""
    if conn is None:
        return
    for template in ("laser_off", "abs_mode", "wait_moves"):
        try:
            _send(conn, chan, template)
        except Exception:  # noqa: BLE001 - best effort; the guard loop is the backstop
            pass
    laser_guard.note("M5", time.monotonic())
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def capture(args, ctx):
    import machine_ops as mo
    m = _mark["v"]
    if m is None:
        raise ApiError("refused", M("machine_cross_no_mark"), reason="no_mark")
    om = mo.model()
    conn = mo.open_connection()
    try:
        head = _head(conn, mo.channel(), om)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    corr = {"x": round(m["x"] - head["x"], 3), "y": round(m["y"] - head["y"], 3)}
    previous = ((settings_store.get("laser")["value"]) or {}).get("correction")
    out = {"action": "capture", "mark": {k: m[k] for k in ("x", "y", "ts")}, "head": head, "correction": corr, "previous": previous, "saved": False,
           "record_id": None}
    if args.get("save"):
        out.update(_save(corr, previous, m, head, ctx))
    return out


def _save(corr, previous, m, head, ctx):
    import machine_ops as mo
    who = identity.actor(ctx)
    value = dict(corr, date=time.strftime("%Y-%m-%d %H:%M"))
    settings_store.merge("laser", {"correction": value})
    rec_id = None
    try:
        rec = machine_store.make_record("laser.pointer", who, machine=machine_store.fingerprint_of(mo._caps()),
                                        inputs={"mark": {"x": m["x"], "y": m["y"]}, "head": head, "power_pct": m["power_pct"]},
                                        results={"correction": corr, "previous": previous}, state="done")
        rec_id = machine_store.append(rec)["id"]
    except Exception as e:  # noqa: BLE001 - the correction is saved; a missing record must not hide it
        print("machine.mark_cross: could not store the record: %s" % e)
    audit.event("machine.mark_cross.saved", {"correction": corr}, who)
    return {"saved": True, "record_id": rec_id}


def _op(args, ctx):
    action = args.get("action") or "mark"
    if action == "mark":
        return mark(args, ctx)
    if action == "capture":
        return capture(args, ctx)
    cleared = _mark["v"] is not None
    _mark["v"] = None
    return {"action": "clear", "cleared": cleared}


def reset():
    """For the tests."""
    _mark["v"] = None


def ops():
    a = Arg
    return [Op("machine.mark_cross", _op, MOTION,
               {"action": a("str", choices=("mark", "capture", "clear"), desc="mark (default): the laser cross; capture: compute the correction with the pointer "
                                                                              "over the cross; clear: forget the mark."),
                "power": a("num", min=1, max=MAX_POWER_PCT, desc="Laser power in percent for the mark (1 to 10, default 3)."),
                "save": a("bool", desc="capture: also write the correction to the settings store laser and to the history.")},
               "Laser <-> pointer assistant on the server: marks a 4 mm cross with the laser (Laser mode, X and Y homed, at most 10 %, "
               "interlocks closed, the movement reserved) or computes the correction once the pointer is over it. The laser is always turned off at the end.",
               motion="sequence", exclusive=False)]
