"""The run kind `offsets.verify` of machine.run (Machine v2 phase 4, design 2.7 "Verification with the camera"; contract in
docs/MACHINE-PHASE4-CONTRACT.md).

It moves the head to a point, asks Vision where the head (crosshair) or a mark is, and reports the error in mm with its uncertainty.
Two targets:
  system  the head REFERENCE goes to the offsets of work system n (`G53 G1 X.. Y..`, machine coordinates): checks that the stored offset points
          to the place the camera sees. Expected point = the X and Y offsets of the system.
  tool    the ACTIVE tool goes to `G1 X0 Y0` of the current system (the firmware applies the tool offset): the tip lands on the work origin of
          the system when the tool offset is right. Expected point = that work origin. The run never changes tool.
Methods: crosshair (no laser), laser (the cross of machine.mark_cross: <= 10 %, Laser mode, interlocks closed, the laser guard armed and
a final M5), pen (the pen is on the head, nothing is fired).

Needs the capability `vision.measure` (machine_measure.py): without it the run is refused with `no_vision_measure` before anything moves.
ASSUMPTIONS (unverified on the board): the modifier form `G53 G1 X.. Y.. F.. S0`, and that G53 ignores the tool offset.
"""
import time

import laser_guard
import machine_cross as cross
import machine_geometry as geo
import machine_measure as meas
import machine_offsets as offsets
import machine_parsers as parsers
import machine_procedures as procs

TARGETS = ("system", "tool")
METHODS = ("crosshair", "laser", "pen")
SAMPLE_GAP_S = 0.3


def validate(params):
    procs._only(params, ("target", "system", "tool", "method", "power", "samples", "tolerance", "feed", "settle_s"))
    target, method = params.get("target", "system"), params.get("method", "crosshair")
    if target not in TARGETS:
        raise procs.BadParams("target", "system or tool")
    if method not in METHODS:
        raise procs.BadParams("method", "crosshair, laser or pen")
    system, tool = params.get("system"), params.get("tool")
    return {"target": target, "method": method, "system": procs._int(params, "system", 1, 1, 9) if system is not None else None,
            "tool": procs._int(params, "tool", 0, 0, 49) if tool is not None else None,
            "power": procs._num(params, "power", cross.DEFAULT_POWER_PCT, 1, cross.MAX_POWER_PCT),
            "samples": procs._int(params, "samples", 3, 1, 5), "tolerance": procs._num(params, "tolerance", 0.5, 0.05, 5.0),
            "feed": procs._int(params, "feed", 3000, 600, 12000), "settle_s": procs._num(params, "settle_s", 1.0, 0.0, 5.0)}


def plan(params, om, caps):
    """(target dict, expected {x, y}) or a refusal code (str). Pure."""
    work = offsets.work_table(om)
    if params["target"] == "system":
        n = params["system"] or offsets.current_system(om, caps) or 1
        target = {"kind": "system", "system": n}
    else:
        n = offsets.current_system(om, caps) or 1
        tool = (om.get("state") or {}).get("currentTool")
        if not isinstance(tool, int) or isinstance(tool, bool) or tool < 0:
            return "bad_target"
        if params["tool"] is not None and params["tool"] != tool:
            return "tool_not_current"
        target = {"kind": "tool", "tool": tool, "system": n}
    row = (work.get(str(n)) or {}).get("offsets") or {}
    if row.get("X") is None or row.get("Y") is None:
        return "bad_target"
    expected = {"x": row["X"], "y": row["Y"]}
    lim = geo.limits(om)
    if lim is None or not (lim["xmin"] <= expected["x"] <= lim["xmax"] and lim["ymin"] <= expected["y"] <= lim["ymax"]):
        return "out_of_reach"
    return target, expected


def check(params, env):
    if not meas.capability()["measure"]:
        return "no_vision_measure"
    got = plan(params, env["om"], env["caps"])
    if isinstance(got, str):
        return got
    if params["method"] == "laser":
        return cross.refusal(env["om"], env["caps"], cross._full_profile(), params["power"])
    return None


def _position(ctx, om, letter):
    res = parsers.parse_json_result(ctx.send("axis_state", index=geo.axis_index(om, letter)))
    pos = geo.num(res.get("machinePosition")) if isinstance(res, dict) else None
    if pos is None:
        raise procs.ProcedureFailed("no_position")
    return pos


def _fire(ctx, power):
    """The cross of machine.mark_cross at the place the head is now, without touching its remembered mark."""
    laser_guard.arm(time.monotonic())
    try:
        ctx.send("rel_mode")
        for axis, dist, s in cross.strokes(power):
            ctx.send("cross_move", axis=axis, d=dist, feed=cross.FEED, power=s)
        ctx.send("wait_moves")
    finally:
        for template in ("laser_off", "abs_mode", "wait_moves"):
            try:
                ctx.send(template)
            except Exception:  # noqa: BLE001 - best effort; the laser guard loop is the backstop
                pass
        laser_guard.note("M5", time.monotonic())


def _go(ctx, params, target, expected):
    ctx.send("abs_mode")
    if target["kind"] == "system":
        ctx.send("move_xy_machine", x=expected["x"], y=expected["y"], feed=params["feed"])
    else:
        ctx.send("move_xy", x=0, y=0, feed=params["feed"])
    ctx.send("wait_moves")
    ctx.wait(params["settle_s"])


def run(ctx, params):
    om = ctx.model()
    got = plan(params, om, ctx.caps())
    if isinstance(got, str):
        raise procs.ProcedureFailed(got)
    target, expected = got
    total = params["samples"] + 3
    ctx.progress(0, total, "move")
    _go(ctx, params, target, expected)
    reached = {"x": _position(ctx, om, "X"), "y": _position(ctx, om, "Y")}
    if params["method"] == "laser":
        ctx.progress(1, total, "mark")
        _fire(ctx, params["power"])
    what = "crosshair" if params["method"] == "crosshair" else "mark"
    bounds, samples = geo.limits(om), []
    for i in range(params["samples"]):
        ctx.check()
        ctx.progress(2 + i, total, "measure")
        try:
            samples.append(meas.measure(what, expected, bounds=bounds))
        except meas.MeasureError as e:
            ctx.set_result({"outcome": "failed", "target": target, "method": params["method"], "expected": expected, "reached": reached,
                            "vision_reason": e.reason, "samples": samples})
            raise procs.ProcedureFailed(e.code, e.reason)
        ctx.wait(SAMPLE_GAP_S)
    verdict = meas.judge(expected, samples, params["tolerance"])
    cal = next((s["calibration"] for s in samples if s["calibration"]), None)
    result = dict(verdict, target=target, method=params["method"], expected=expected, reached=reached,
                  samples=[{k: s[k] for k in ("x", "y", "sigma_mm", "confidence")} for s in samples], vision={"calibration": cal})
    ctx.set_result(result)
    ctx.set_record({k: result[k] for k in ("outcome", "target", "method", "expected", "measured", "error", "tolerance", "uncertainty_mm")})
    ctx.progress(total, total, "done")


procs.register(procs.Procedure("offsets.verify", run, validate, motion="sequence", needs_homed=True, needs_confirm=True, check=check))
