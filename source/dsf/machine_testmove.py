"""The test move of the steps-per-mm assistant, sent from the page: `machine.test_move` (technician, level 3 confirmation).

The assistant tells the person to command a known distance, measure what the axis really moved and compute the new steps per mm. The move itself was
shown as G-code to copy; now the page can send it. The page never sends text: this operation checks the machine, asks the movement owner for the
bed and renders ONE template of the closed list (machine_gcode.py `rel_move`: `G1 X100 F600 S0`, always S0 so a laser never fires) between `G91`
and `G90`, and puts the machine back in absolute mode whatever happens.

Refused (nothing is sent): the machine is not idle (a job runs, paused, halted, off), the axis does not exist or is not homed (the limits would be
unknown), the move would leave the travel of the axis, the distance or the feed is out of range, or the movement owner says no.
"""
import audit
import identity
import machine_cross
import machine_geometry as geo
import machine_gcode
import motion_owner
from messages import M
from workshop_api import ApiError, Arg, MOTION, Op

MAX_MM = 200.0
MIN_MM = 0.1
MAX_FEED = 6000
DEFAULT_FEED = 600
AXES = "XYZUVWABC"      # an extruder is not an axis to move here: its steps are calibrated by extruding
RESERVE_S = 60


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def refusal(om, axis, dist, feed):
    """The code that stops the move ("" = it can go). Order: what is wrong with the request, then the state of the machine, then the travel."""
    if axis not in AXES or len(axis) != 1:
        return "bad_axis"
    d = _num(dist)
    if d is None or not MIN_MM <= abs(d) <= MAX_MM:
        return "bad_distance"
    f = _num(feed)
    if f is None or not 1 <= f <= MAX_FEED:
        return "bad_feed"
    if not om:
        return "no_model"
    status = str(((om or {}).get("state") or {}).get("status") or "")
    if status != "idle":
        return "not_idle"
    ax = geo.axes_by_letter(om).get(axis)
    if not ax:
        return "no_axis"
    if not ax.get("homed"):
        return "not_homed"
    pos, lo, hi = geo.num(ax.get("machinePosition")), geo.num(ax.get("min")), geo.num(ax.get("max"))
    if pos is None or lo is None or hi is None:
        return "no_limits"
    if not lo - 1e-6 <= pos + d <= hi + 1e-6:
        return "outside_limits"
    return ""


def _run(args, ctx):
    import machine_ops as mo
    axis = str(args.get("axis") or "").upper()
    dist = args.get("distance")
    feed = args.get("feed") if args.get("feed") is not None else DEFAULT_FEED
    if not ctx.get("confirm"):
        raise ApiError("confirm_required", M("machine_testmove_confirm", axis=axis, d=dist), confirm=mo._confirm_info(None, "machine.test_move"))
    why = refusal(mo.model(), axis, dist, feed)
    if why:
        raise ApiError("refused", M("machine_testmove_refuse_" + why, max=MAX_MM), reason=why)
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])
    who = identity.actor(ctx)
    bridge = mo._bridge()
    d = motion_owner.reserve(bridge, mo.ORIGIN, "sequence", "test_move", RESERVE_S, actor=who)
    if d.get("decision") != "allow":
        raise ApiError("motion_denied", d.get("reason") or "", motion={"decision": "deny", "code": d.get("code")})
    conn = chan = None
    try:
        conn, chan = mo.open_connection(), mo.channel()
        machine_cross._send(conn, chan, "wait_moves")
        machine_cross._send(conn, chan, "rel_mode")
        machine_cross._send(conn, chan, "rel_move", axis=axis, dist=dist, feed=int(feed))
        machine_cross._send(conn, chan, "wait_moves")
    finally:
        _back_to_absolute(conn, chan)
        motion_owner.release(bridge, d["token"], actor=who)
    audit.event("machine.test_move", {"axis": axis, "distance": dist, "feed": feed}, who)
    return {"axis": axis, "distance": dist, "feed": int(feed)}


def _back_to_absolute(conn, chan):
    """Whatever happened: absolute mode again and the moves finished; the connection closed."""
    if conn is None:
        return
    for template in ("abs_mode", "wait_moves"):
        try:
            machine_cross._send(conn, chan, template)
        except Exception:  # noqa: BLE001 - best effort: the next command of the page does not depend on it
            pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def ops():
    a = Arg
    return [Op("machine.test_move", _run, MOTION,
               {"axis": a("str", True, desc="Axis letter to move (X Y Z U V W A B C)."),
                "distance": a("num", True, min=-MAX_MM, max=MAX_MM, desc="Distance in mm, relative (0.1 to 200, negative goes back)."),
                "feed": a("num", min=1, max=MAX_FEED, desc="Feed in mm/min (default 600).")},
               "The test move of the steps-per-mm assistant: G91, G1 <axis><distance> F<feed> S0, G90 (the laser never fires). Level 3 confirmation; "
               "refused unless the machine is idle, the axis homed and the move inside its travel.")]
