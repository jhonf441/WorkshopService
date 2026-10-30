"""
State updates of the continuous jog (WorkshopJog page: knob X/Y, Z slider,
extra axes). Called by the API operations jog.* (api_ops.py); jog_move.py
is the only one that computes the ramp and sends motion. This handler never
sends G-code itself: it only updates the shared state under a lock.

Parameters (internal, filled by api_ops.py from the named arguments):
  S"xy" X<-1..1> Y<-1..1> F<0..100>   jog.xy: vector + speed percent
  S"stop_xy"                           jog.stop_xy
  S"z" Z<-1..1> F<0..100>              jog.z
  S"stop_z"                            jog.stop_z
  S"eje" L"U" V<-1..1> F<0..100>       jog.axis: extra axis (U, V, W, A...) held
  S"stop_axis"                          jog.stop_axis
  S"libre" A1|A0                       jog.free: mode without limits (with guards)
  C1 on the moves = the person confirmed (live job open and idle).
  D<device> U<user> R<role>            who calls (browser id, name, role; filled by api_ops.py from the identity of the call)
  Q1 on the stops                      "I let go of MY control": ignored when another device holds the jog; without it the
                                       stop stops everything (safety)

When the jog does not move, the answer starts with a code (api_ops.py turns
them into API errors):
  "Jog bconfirms: <reason>"   motion_denied (file job, live job with activity,
         confirms             bridge activity, reservation of another page)
  "confirm: <reason>"       confirm_required (live job open but idle > 20 s;
                              the confirmation lasts 60 s from the last gesture,
                              only for that job). Also in data.jogBlock.
A paused file job lets the jog move (RRF restores the positions on resume).
The stall of the mode without limits arrives through global variables written
by sys/driver-stall.g (api_macros.py), not through this handler.
"""
import jog_move
import motion_owner
from messages import M


def _after_stop(bridge, actor, release):
    """A stop frees the jog lease: all of them when it stopped everything, the caller's own when it only let go of its control
    (and only if nothing else is still held)."""
    if not jog_move.held():
        motion_owner.jog_release(bridge, actor, everyone=not release)


def run(params, bridge, config):
    action = str(params.get("S", "")).strip().lower()
    actor = {"device": params.get("D") or "", "user": params.get("U") or "", "role": params.get("R") or ""}
    device = actor["device"]
    release = str(params.get("Q", "0")).strip() in ("1", "1.0", "true", "True")

    # the jog refuses to move when the single owner of the movement says so
    # (motion_owner.py), even if the page lets it: only state, never G-code here
    if action in ("xy", "z", "axis"):
        taken = motion_owner.jog_conflict(actor)
        if taken:  # another device holds the jog: it is refused WITHOUT touching what that device is doing
            return "Jog bloqueado: " + taken
        confirmed = str(params.get("C", "0")).strip() in ("1", "1.0", "true", "True")
        if confirmed:
            jog_move.confirm(bridge, actor)
        level, reason = jog_move.decide_block(bridge, actor)
        if level == "confirm":
            jog_move._publish_block(bridge, reason, level)
            return "confirm: " + reason
        if level:
            jog_move.reject(bridge, reason)
            return "Jog bloqueado: " + reason
        jog_move.renew_confirmation(bridge, actor)
        motion_owner.jog_claim(bridge, actor)

    if action == "xy":
        nx = float(params.get("X", 0) or 0)
        ny = float(params.get("Y", 0) or 0)
        speed = float(params.get("F", 50) or 50)
        jog_move.set_xy(nx, ny, speed, device)
        return M("jog_jog_xy_updated")

    if action == "stop_xy":
        jog_move.stop_xy(device, release)
        _after_stop(bridge, actor, release)
        return M("jog_jog_xy_stopped")

    if action == "z":
        z_val = float(params.get("Z", 0) or 0)
        speed = float(params.get("F", 50) or 50)
        jog_move.set_z(z_val, speed, device)
        return M("jog_jog_z_updated")

    if action == "stop_z":
        jog_move.stop_z(device, release)
        _after_stop(bridge, actor, release)
        return M("jog_jog_z_stopped")

    if action == "axis":
        jog_move.set_ext(params.get("L", ""), float(params.get("V", 0) or 0), float(params.get("F", 50) or 50), device)
        return M("jog_jog_extra_axis_updated")

    if action == "stop_axis":
        jog_move.stop_ext(device, release)
        _after_stop(bridge, actor, release)
        return M("jog_jog_extra_axis_stopped")

    if action == "free":
        on = str(params.get("A", "0")).strip() in ("1", "1.0", "true", "True")
        jog_move.free_request(on)
        return M("jog_jog_without_limits_turning_on") if on else M("jog_jog_without_limits_turning_off")

    return "Error: unknown jog action"
