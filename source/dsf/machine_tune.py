"""Accelerometer tuning of the input shaper: the run kind `shaping.tune` of machine.run (Machine v2, phase 3, design 2.8 and Q5).

BEHIND A CAPABILITY. The owner is not assumed to have an accelerometer. The run is refused with `reason: "no_accelerometer"` unless

  - `capabilities.accelerometers.present` is true (discovered from sensors.accelerometers; a profile that only DECLARES one is not enough), AND
  - the object model lists the accelerometer index asked for.

It then sends only: `M955 P<n>` (the bare report: nothing is configured), `G90`, a move to the start, `M956 P<n> S<samples> A0 <axis>` (A0 = activate now, the
only form the firmware implements) and X or Y moves back and forth inside the limits of the axis. The service does NOT analyse the file the firmware writes
(its format is not verified): the result says where it is. Everything is a template of the closed list (machine_gcode.py).

Params {axis: "X"|"Y" (X), accelerometer: 0-15 (0), samples: 100-3000 (1000), travel: mm 10-150 (50), start: mm (axis minimum + 20), feed: mm/min 600-30000
(6000, never above the axis speed), cycles: 1-10 (3)}. Result {outcome: "collected", axis, accelerometer, samples, folder, moves, report}.
"""
import machine_geometry as geo
import machine_procedures as procs

FOLDER = "0:/sys/accelerometer"
MARGIN_MM = 5.0


def validate(params):
    procs._only(params, ("axis", "accelerometer", "samples", "travel", "start", "feed", "cycles"))
    axis = params.get("axis", "X")
    if axis not in ("X", "Y"):
        raise procs.BadParams("axis", "X or Y")
    start = params.get("start")
    return {"axis": axis, "accelerometer": procs._int(params, "accelerometer", 0, 0, 15), "samples": procs._int(params, "samples", 1000, 100, 3000),
            "travel": procs._num(params, "travel", 50, 10, 150), "start": procs._num(params, "start", 0, -5000, 5000) if start is not None else None,
            "feed": procs._int(params, "feed", 6000, 600, 30000), "cycles": procs._int(params, "cycles", 3, 1, 10)}


def _axis(om, letter):
    return next((a for a in ((om or {}).get("move") or {}).get("axes") or [] if isinstance(a, dict) and a.get("letter") == letter), None)


def resolved(params, om):
    """(start, lo, hi, speed) for the axis; None for lo / hi when the model does not say."""
    a = _axis(om, params["axis"]) or {}
    lo, hi, speed = geo.num(a.get("min")), geo.num(a.get("max")), geo.num(a.get("speed"))
    start = params["start"] if params["start"] is not None else (lo + 20 if lo is not None else None)
    return start, lo, hi, speed


def check(params, env):
    """Reason code or None. `no_accelerometer` first: it is the capability gate."""
    caps = ((env.get("caps") or {}).get("capabilities") or {}).get("accelerometers") or {}
    listed = {i.get("index") for i in caps.get("items") or []}
    om_list = ((env.get("om") or {}).get("sensors") or {}).get("accelerometers")
    if not caps.get("present") or params["accelerometer"] not in listed or not isinstance(om_list, list) or params["accelerometer"] >= len(om_list):
        return "no_accelerometer"
    start, lo, hi, speed = resolved(params, env["om"])
    if lo is None or hi is None or start is None:
        return "no_limits"
    if start < lo + MARGIN_MM or start + params["travel"] > hi - MARGIN_MM:
        return "out_of_reach"
    if speed is not None and params["feed"] > speed:
        return "feed_too_high"
    return None


def run(ctx, params):
    start, _, _, _ = resolved(params, ctx.model())
    axis, n, end = params["axis"], params["accelerometer"], start + params["travel"]
    total = 4 + 2 * params["cycles"]
    ctx.progress(0, total, "prepare")
    report = ctx.send("accel_report", index=n)
    ctx.send("abs_mode")
    ctx.send("tune_move", axis=axis, pos=start, feed=params["feed"])
    ctx.send("wait_moves")
    ctx.check()
    ctx.progress(2, total, "collect")
    ctx.send("accel_collect", index=n, samples=params["samples"], axis=axis)       # A0 is part of the template: collection starts at once
    step, moves = 3, 0
    for _ in range(params["cycles"]):
        for pos in (end, start):
            ctx.check()
            ctx.send("tune_move", axis=axis, pos=pos, feed=params["feed"])
            moves += 1
            step += 1
            ctx.progress(step, total, "move")
    ctx.send("wait_moves")
    result = {"outcome": "collected", "axis": axis, "accelerometer": n, "samples": params["samples"], "folder": FOLDER, "moves": moves,
              "report": report.strip()[:300]}
    ctx.set_result(result)
    ctx.set_record({"outcome": "collected", "axis": axis, "accelerometer": n, "samples": params["samples"], "folder": FOLDER})


procs.register(procs.Procedure("shaping.tune", run, validate, motion="sequence", needs_homed=True, needs_confirm=True, check=check))
