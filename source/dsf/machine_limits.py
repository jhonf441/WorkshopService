"""Limits and endstops of Machine v2 (phase 2, design 2.5): `machine.limits.get` and the run kind `homing.verify`.

machine.limits.get   (operator, read only) the M208 limits of every axis as the object model reports them (move.axes[]), the endstops
                     (sensors.endstops[], indexed like the axes) and where the configuration defines M208 (config.g and the macros it calls).
                     Editing the limits is `machine.config.plan` kind `config.m208` (ADMIN: permissions.MACHINE_ADMIN_KINDS) and a volatile
                     trial is `machine.try` gcode_kind `M208` (admin too).
homing.verify        HOMES the axes (G28 <axis>, one by one; motion class sequence, level 3 confirmation, reservation like the probe runs) and
                     checks, per axis: (1) the axis has an endstop, (2) it was not pressed before homing unless the axis was already at its
                     end, (3) after homing the position equals the declared home (M208 min or max, by `highEnd` of the endstop) within the
                     tolerance, (4) the endstop reads triggered after homing when it is a plain input pin. A homing file that moves away
                     from the endstop after touching it (`G1 H2 X5`) leaves a position that differs from the declared home: the delta is
                     reported, as a warning, never hidden.
Homing REPEATABILITY and the real TRAVEL check are phase 3 and are NOT here.

Result of homing.verify (and the record):
    {"outcome": "ok" | "warn", "tolerance": mm, "axes": [{"axis", "index", "endstop": {"type", "high_end", "probe"}, "home_at": "min" | "max",
     "declared": mm, "before": {"triggered", "position", "homed"}, "after": {"triggered", "position", "homed"}, "delta": mm | null,
     "checks": {"endstop_present", "not_pressed_before", "position_matches", "triggered_after"}, "ok": bool}]}
`checks.*` is true / false, null when it could not be judged (the reply had no such field).
"""
import config_scan
import machine_geometry as geo
import machine_parsers as parsers
import machine_procedures as procs
from workshop_api import READ, Op

TOLERANCE_MM = 0.05
AT_END_MM = 1.0


# ---- machine.limits.get ----

def endstop_rows(om):
    """[{"index", "axis", "type", "high_end", "triggered", "probe"}] of the endstops the model reports (a null entry = no endstop)."""
    ends = ((om or {}).get("sensors") or {}).get("endstops") or []
    letters = [a.get("letter") if isinstance(a, dict) else None for a in ((om or {}).get("move") or {}).get("axes") or []]
    return [{"index": i, "axis": letters[i] if i < len(letters) else None, "type": e.get("type"), "high_end": bool(e.get("highEnd")),
             "triggered": e.get("triggered"), "probe": e.get("probe")} for i, e in enumerate(ends) if isinstance(e, dict)]


def axes_rows(om):
    out = []
    for i, a in enumerate(((om or {}).get("move") or {}).get("axes") or []):
        if isinstance(a, dict):
            out.append({"index": i, "letter": a.get("letter"), "min": geo.num(a.get("min")), "max": geo.num(a.get("max")),
                        "min_probed": bool(a.get("minProbed")), "max_probed": bool(a.get("maxProbed")), "homed": bool(a.get("homed")),
                        "visible": a.get("visible", True) is not False, "position": geo.num(a.get("machinePosition"))})
    return out


def limit_warnings(axes, ends):
    have = {e["index"] for e in ends}
    out = []
    for a in axes:
        if not a["visible"]:
            continue
        if a["min"] is None or a["max"] is None or a["min"] >= a["max"]:
            out.append({"code": "bad_limits", "axis": a["letter"]})
        if a["letter"] in ("X", "Y", "Z") and a["index"] not in have:
            out.append({"code": "no_endstop", "axis": a["letter"]})
    return out


def limits_view(om, read):
    axes, ends = axes_rows(om), endstop_rows(om)
    scan = config_scan.scan(read)
    return {"axes": axes, "endstops": ends, "definitions": [{"file": d["file"], "line": d["line"], "text": d["text"]} for d in scan["m208"]],
            "warnings": limit_warnings(axes, ends), "config_read": scan["read"]}


def _limits_op(args, ctx):
    import machine_ops as mo
    return limits_view(mo.model(), mo.read_sd)


# ---- homing.verify ----

def validate(params):
    procs._only(params, ("axes", "tolerance"))
    axes = params.get("axes")
    if axes is not None:
        if not isinstance(axes, list) or not 1 <= len(axes) <= 9 or not all(isinstance(a, str) and len(a) == 1 and a in "XYZUVWABC" for a in axes) \
                or len(set(axes)) != len(axes):
            raise procs.BadParams("axes", "letters")
    return {"axes": axes, "tolerance": procs._num(params, "tolerance", TOLERANCE_MM, 0.001, 2.0)}


def targets(params, om):
    """[(letter, index)] to verify: the asked ones, else every visible axis X Y Z that has an endstop."""
    ends = {e["index"] for e in endstop_rows(om)}
    rows = [a for a in axes_rows(om) if a["visible"]]
    if params.get("axes"):
        return [(a["letter"], a["index"]) for a in rows if a["letter"] in params["axes"]]
    return [(a["letter"], a["index"]) for a in rows if a["letter"] in ("X", "Y", "Z") and a["index"] in ends]


def check(params, env):
    om = env["om"]
    found = targets(params, om)
    if params.get("axes") and len(found) != len(params["axes"]):
        return "bad_axis"
    ends = {e["index"] for e in endstop_rows(om)}
    if not found or any(i not in ends for _, i in found):
        return "no_endstops"
    return None


def _state(ctx, index):
    """{"triggered", "position", "homed", "min", "max"} read from the board now (the endstop by the axis index)."""
    ends = parsers.parse_json_result(ctx.send("endstops_om"))
    e = ends[index] if isinstance(ends, list) and index < len(ends) and isinstance(ends[index], dict) else {}
    ax = parsers.parse_json_result(ctx.send("axis_state", index=index))
    ax = ax if isinstance(ax, dict) else {}
    return {"triggered": e.get("triggered") if isinstance(e.get("triggered"), bool) else None, "position": geo.num(ax.get("machinePosition")),
            "homed": ax.get("homed") if isinstance(ax.get("homed"), bool) else None, "min": geo.num(ax.get("min")), "max": geo.num(ax.get("max")),
            "end": {"type": e.get("type"), "high_end": bool(e.get("highEnd")), "probe": e.get("probe")}}


def judge(letter, index, before, after, tolerance):
    """The result row of one axis (pure)."""
    high = after["end"]["high_end"] if after["end"].get("type") else before["end"]["high_end"]
    declared = after["max"] if high else after["min"]
    if declared is None:
        declared = before["max"] if high else before["min"]
    at_end = before["position"] is not None and declared is not None and abs(before["position"] - declared) <= AT_END_MM
    delta = after["position"] - declared if after["position"] is not None and declared is not None else None
    checks = {"endstop_present": True,
              "not_pressed_before": None if before["triggered"] is None else (not before["triggered"]) or bool(before["homed"] and at_end),
              "position_matches": None if delta is None else abs(delta) <= tolerance,
              "triggered_after": after["triggered"] if after["end"].get("type") == "inputPin" else None}
    ok = all(v is not False for v in checks.values()) and checks["position_matches"] is True
    return {"axis": letter, "index": index, "endstop": {k: after["end"].get(k) for k in ("type", "high_end", "probe")},
            "home_at": "max" if high else "min", "declared": declared,
            "before": {k: before[k] for k in ("triggered", "position", "homed")}, "after": {k: after[k] for k in ("triggered", "position", "homed")},
            "delta": None if delta is None else round(delta, 4), "checks": checks, "ok": ok}


def run_verify(ctx, params):
    om = ctx.model()
    todo = targets(params, om)
    rows = []
    ctx.progress(0, len(todo), "homing")
    try:
        for n, (letter, index) in enumerate(todo):
            ctx.check()
            before = _state(ctx, index)
            errors = parsers.find_errors(ctx.send("home_axis", axis=letter))
            if errors:
                raise procs.ProcedureFailed("homing_failed", errors[0]["text"])
            ctx.send("wait_moves")
            rows.append(judge(letter, index, before, _state(ctx, index), params["tolerance"]))
            ctx.progress(n + 1, len(todo), "homing")
    except Exception:
        ctx.set_result({"outcome": "failed", "tolerance": params["tolerance"], "axes": rows})
        raise
    result = {"outcome": "ok" if all(r["ok"] for r in rows) else "warn", "tolerance": params["tolerance"], "axes": rows}
    ctx.set_result(result)
    ctx.set_record({"outcome": result["outcome"], "tolerance": params["tolerance"],
                    "axes": [{"axis": r["axis"], "delta": r["delta"], "ok": r["ok"], "home_at": r["home_at"]} for r in rows]})


procs.register(procs.Procedure("homing.verify", run_verify, validate, motion="sequence", needs_confirm=True, check=check))


def ops():
    return [Op("machine.limits.get", _limits_op, READ, {},
               "The M208 limits of every axis (min, max, probed, homed, position) from the object model, the endstops (type, high end, state) and "
               "where the configuration defines M208. Changing a limit is machine.config.plan config.m208 (administrator).", log=False)]
