"""Bed / gantry levelling procedures of Machine v2 (phase 1): `level.g32`, `level.g30`, `level.measure`.

All three run IN THE SERVICE (the old Machine > Level Z drove the sequence from the browser). They need a probe and homed axes, and they
reserve the movement (class sequence) like every procedure.

level.g32      G32 passes: the firmware runs sys/bed.g, which ends in `G30 Pn ... Sk` and moves the Z motors (M671 with as many leadscrews as
               Z motors). Each pass is read (machine_parsers.parse_g32) and the old browser rules decide (machine_geometry.decide):
               measured deviation below the tolerance -> converged; the deviation GROWS (M671 probably in the wrong order) -> error
               "diverging"; the pass limit reached -> "limit" (record state partial); the firmware only says how much to turn each screw
               -> "manual"; a correction over the M671 S limit -> error "corrections_exceed" (the firmware does not apply it).
level.g30      the same loop with the points of the run (parameters, profile or bed.g) sent one `G30 Pn X Y Z-99999 K` at a time, S = number
               of leadscrews on the last one; without M671 the pass is a plain measure (S-1) and level.measure is the right kind.
level.measure  measure only: every point is probed (`G30 P.. S-1` on the last), nothing is calibrated and no motor moves.

After the passes the run measures again with S-1 (`verify`, on by default): the "after" figure of the firmware reply is the EXPECTED deviation,
not a measurement (GCODE-REFERENCE 2 and 9.19). A run that moved the motors says `rehome_needed` (Z=0 shifts after levelling); with
`rehome_z` it sends `G28 Z` at the end (opt-in: the homing macro of the machine decides how Z is homed).

Limits (profile machine.safety / machine.levelling): max_points_per_run bounds points x passes (+ the verify pass), max_passes bounds the
passes, the descent of one touch is bounded as in machine_probe. The stop request is honoured between points; one point in progress finishes.
"""
import machine_geometry as geo
import machine_parsers as parsers
import machine_probe as probe
import machine_procedures as procs

KINDS = ("level.g32", "level.g30", "level.measure")
MAX_PASSES = 20
PASS_ERRORS = {"factors": "factors_mismatch", "points": "cannot_calculate", "failure": "calibration_failed", "error": "board_error",
               "exceeds": "corrections_exceed"}


# ---- parameters ----

def _points(params):
    pts = params.get("points")
    if pts is None:
        return None
    if not isinstance(pts, list) or not 1 <= len(pts) <= geo.MAX_LEVEL_POINTS:
        raise procs.BadParams("points", "1..%d points" % geo.MAX_LEVEL_POINTS)
    out = []
    for i, p in enumerate(pts):
        if not isinstance(p, dict) or set(p) != {"x", "y"}:
            raise procs.BadParams("points", "{x, y}")
        out.append({"x": procs._num(p, "x", 0, -5000, 5000), "y": procs._num(p, "y", 0, -5000, 5000)})
    return out


def validate(params):
    procs._only(params, ("probe", "passes", "tolerance", "points", "verify", "rehome_z"))
    out = {"probe": procs._int(params, "probe", 0, 0, 15) if params.get("probe") is not None else None,
           "passes": procs._int(params, "passes", 1, 1, MAX_PASSES) if params.get("passes") is not None else None,
           "tolerance": procs._num(params, "tolerance", 0.01, 0.001, 1.0) if params.get("tolerance") is not None else None,
           "verify": procs._bool(params, "verify", True), "rehome_z": procs._bool(params, "rehome_z", False)}
    pts = _points(params)
    if pts is not None:
        out["points"] = pts
    return out


def resolve_points(params, prof, om, k, bed_text=None):
    """(points, source): the run's own, else the profile's levelling.probe_points, else the numeric G30 lines of bed.g, else one near each
    leadscrew; ([], None) when there is none."""
    if params.get("points"):
        return params["points"], "params"
    lv = (prof or {}).get("levelling") or {}
    if lv.get("probe_points"):
        return [{"x": float(p[0]), "y": float(p[1])} for p in lv["probe_points"]], "profile"
    bed = geo.bed_points(bed_text) if bed_text else None
    if bed and bed["readable"]:
        return [dict(p) for p in bed["points"]], "bed_g"
    sug = geo.suggest_points(om, k)
    return (sug, "suggested") if sug else ([], None)


def limits_of(params, prof):
    lv = (prof or {}).get("levelling") or {}
    max_passes = lv.get("max_passes", 5)
    passes = min(params.get("passes") or max_passes, max_passes)
    return passes, params.get("tolerance") or lv.get("tolerance_mm", 0.02)


def leadscrew_count(caps):
    return ((caps or {}).get("capabilities", {}).get("levelling") or {}).get("m671_entries") or 0


# ---- start checks (reasons the run is refused before it starts) ----

def check_kind(kind, params, env):
    om, prof, caps = env["om"], env["profile"], env["caps"]
    lev = ((caps or {}).get("capabilities") or {}).get("levelling") or {}
    k = probe.probe_index(params, prof, om)
    if k is None or geo.probe_of(om, k) is None:
        return "no_probe_index"
    passes, _ = limits_of(params, prof)
    limit = (prof.get("safety") or {}).get("max_points_per_run", 100)
    bed_text = env["read"]("0:/sys/bed.g") if kind != "level.measure" or not params.get("points") else None
    if kind == "level.g32":
        return _check_g32(lev, passes, limit, bed_text, params, prof, om, k)
    if kind == "level.g30" and lev.get("mode") != "leadscrews":
        return "no_m671" if lev.get("mode") == "missingM671" else "no_levelling"
    points, _ = resolve_points(params, prof, om, k, bed_text)
    errors = geo.validate_points(points, om, k, leadscrews=leadscrew_count(caps) if kind == "level.g30" else 0,
                                 max_points=limit)
    if errors:
        return errors[0]["code"]
    touches = len(points) * (passes if kind == "level.g30" else 1) + (len(points) if kind == "level.g30" and params.get("verify", True) else 0)
    if touches > limit:
        return "too_many_points"
    return _descent_reason(om, k, prof)


def _check_g32(lev, passes, limit, bed_text, params, prof, om, k):
    if lev.get("mode") != "leadscrews":
        return "no_m671" if lev.get("mode") == "missingM671" else "no_levelling"
    if bed_text is None:
        return "no_bed_g"
    bed = geo.bed_points(bed_text)
    if bed["count"] == 0:
        return "bed_g_points"
    if bed["count"] * passes > limit:
        return "too_many_points"
    return _descent_reason(om, k, prof)


def _descent_reason(om, k, prof):
    bound = geo.descent_bound(om, k)
    limit = (prof.get("safety") or {}).get("max_probe_descent_mm")
    return "descent_limit" if bound is not None and limit is not None and bound > limit else None


# ---- the touches ----

def measure_pass(ctx, points, k, om, prof):
    """Probes the points measure-only and returns {"heights": [{x, y, z, source}], "spread", "reported"}. A point that cannot be read ends the
    run (bad_reply); the firmware's own error ends it as probe_error."""
    rows, last_reply = [], ""
    state = probe.z_state(ctx, om)
    probe.descent_guard(om, k, prof, state)
    for i, p in enumerate(points):
        ctx.check()
        last = i == len(points) - 1
        reply = ctx.send("probe_point_last", p=i, x=p["x"], y=p["y"], k=k, s=-1) if last else ctx.send("probe_point", p=i, x=p["x"], y=p["y"], k=k)
        last_reply = reply
        reading = probe.read_height(ctx, reply, k)
        if reading.height is None:
            raise procs.ProcedureFailed("bad_reply", "P%d: %s" % (i, str(reply)[:100]))
        probe.descent_guard(om, k, prof, state, reading.height)
        rows.append({"x": p["x"], "y": p["y"], "z": round(reading.height, 3), "source": reading.source})
        ctx.progress(i + 1, len(points), "measuring")
    reported = parsers.parse_bed_heights(last_reply)
    return {"heights": rows, "spread": geo.spread([r["z"] for r in rows]),
            "reported": {"mean": reported["mean"], "deviation": reported["deviation"]} if reported["matched"] else None}


def g30_pass(ctx, points, k, leadscrews):
    """One calibrating pass: the points one by one, S = number of leadscrews on the last. Returns the reply of the last."""
    last_reply = ""
    for i, p in enumerate(points):
        ctx.check()
        if i < len(points) - 1:
            reply = ctx.send("probe_point", p=i, x=p["x"], y=p["y"], k=k)
        else:
            reply = ctx.send("probe_point_last", p=i, x=p["x"], y=p["y"], k=k, s=min(leadscrews, 4))
        errors = parsers.find_errors(reply)
        hard = [e for e in errors if e["code"] not in ("corrections_exceed", "factors_mismatch", "cannot_calculate", "calibration_failed")]
        if hard:
            raise procs.ProcedureFailed("probe_error", "P%d: %s" % (i, hard[0]["text"]))
        last_reply = reply
        ctx.progress(i + 1, len(points), "probing")
    return last_reply


# ---- the pass loop ----

def compact(result, n):
    """A pass as it is stored: numbers rounded, nothing bulky."""
    out = {"n": n, "kind": result["kind"]}
    for key in ("before", "after"):
        if result.get(key):
            out[key] = {a: geo.rnd(b, 4) for a, b in result[key].items()}
    if result.get("adjustments") is not None:
        out["adjustments"] = [geo.rnd(v, 3) for v in result["adjustments"]]
    for key in ("screws", "limit", "points", "source"):
        if result.get(key) is not None:
            out[key] = result[key]
    return out


def best_result(parsed):
    settings = [r for r in parsed["results"] if r["kind"] == "setting"]
    return settings[-1] if settings else parsed["last"]


def om_result(ctx, before):
    """Fallback when the reply says nothing readable: the calibration of the object model, if it changed since before the pass."""
    now = parsers.parse_calibration(ctx.send("calibration_om"))
    if not now["matched"] or not now["initial"] or now["initial"] == (before or {}).get("initial"):
        return None, now
    return {"kind": "setting", "before": now["initial"], "after": now["final"] or {}, "adjustments": [], "points": now["factors"] or 0,
            "source": "om"}, now


def run_passes(ctx, do_pass, max_passes, tolerance, state):
    """Passes until the rules of machine_geometry.decide say stop. `state` collects {"passes", "raw"}; returns the outcome."""
    baseline = parsers.parse_calibration(ctx.send("calibration_om"))
    full = []
    for n in range(1, max_passes + 1):
        ctx.check()
        reply = do_pass(n)
        parsed = parsers.parse_g32(reply)
        state["raw"] = parsed["raw"]
        result = best_result(parsed)
        if result is None:
            result, baseline = om_result(ctx, baseline)
        if result is None:
            raise procs.ProcedureFailed("no_result", parsed["raw"][:120])
        full.append(result)
        state["passes"].append(compact(result, n))
        decision = geo.decide(result, full, n, max_passes, tolerance)
        if decision == "next":
            continue
        if decision == "diverging":
            raise procs.ProcedureFailed("diverging")
        if decision in ("failed", "exceeds"):
            raise procs.ProcedureFailed(PASS_ERRORS.get(result["kind"], "board_error"), parsed["raw"][:120])
        return decision
    return "limit"


def finish(ctx, params, state, outcome, points, k, om, prof, tolerance):
    """Verification measure, the Z homing if asked, and the result."""
    moved = any(p["kind"] == "setting" for p in state["passes"])
    result = {"outcome": outcome, "passes": state["passes"], "tolerance": tolerance, "rehome_needed": moved}
    ctx.set_result(result)
    if params["verify"] and points and outcome in ("converged", "limit", "measured"):
        ctx.progress(0, len(points), "verifying")
        v = measure_pass(ctx, points, k, om, prof)
        v["light"] = "ok" if (v["spread"]["deviation"] or 0) < tolerance else "warn"
        result["verified"] = v
    elif params["verify"]:
        result["verified"] = None
    if params["rehome_z"] and moved:
        ctx.send("home_z")
        result["rehome_needed"] = False
    if outcome == "limit":
        ctx.partial = True
    ctx.set_result(result)
    ctx.set_record(_record_of(result))


def _record_of(result):
    out = {k: v for k, v in result.items() if k != "verified"}
    out["passes"] = result["passes"][:8]
    if result.get("verified"):
        out["verified"] = {"spread": result["verified"]["spread"], "light": result["verified"]["light"], "reported": result["verified"]["reported"]}
    return out


# ---- the three kinds ----

def prepare(ctx, params):
    om, prof = ctx.model(), ctx.profile()
    k = probe.probe_index(params, prof, om)
    if k is None or geo.probe_of(om, k) is None:
        raise procs.ProcedureFailed("no_probe_index")
    ctx.use_probe(k)
    probe.descent_guard(om, k, prof, probe.z_state(ctx, om))
    return om, prof, k


def run_g32(ctx, params):
    om, prof, k = prepare(ctx, params)
    max_passes, tol = limits_of(params, prof)
    points, _ = resolve_points(params, prof, om, k, ctx.read("0:/sys/bed.g"))
    state = {"passes": [], "raw": ""}
    def do_pass(n):
        ctx.progress(n - 1, max_passes, "g32")
        return ctx.send("bed_level")

    try:
        outcome = run_passes(ctx, do_pass, max_passes, tol, state)
    except Exception:
        ctx.set_result({"outcome": "failed", "passes": state["passes"], "raw": state["raw"], "tolerance": tol})
        raise
    finish(ctx, params, state, outcome, points, k, om, prof, tol)


def run_g30(ctx, params):
    om, prof, k = prepare(ctx, params)
    max_passes, tol = limits_of(params, prof)
    points, _ = resolve_points(params, prof, om, k, ctx.read("0:/sys/bed.g"))
    leadscrews = leadscrew_count(ctx.caps())
    state = {"passes": [], "raw": ""}
    try:
        outcome = run_passes(ctx, lambda n: g30_pass(ctx, points, k, leadscrews), max_passes, tol, state)
    except Exception:
        ctx.set_result({"outcome": "failed", "passes": state["passes"], "raw": state["raw"], "tolerance": tol})
        raise
    finish(ctx, params, state, outcome, points, k, om, prof, tol)


def run_measure(ctx, params):
    om, prof, k = prepare(ctx, params)
    _, tol = limits_of(params, prof)
    points, source = resolve_points(params, prof, om, k, ctx.read("0:/sys/bed.g"))
    ctx.progress(0, len(points), "measuring")
    v = measure_pass(ctx, points, k, om, prof)
    v.update(outcome="measured", points_from=source, tolerance=tol, light="ok" if (v["spread"]["deviation"] or 0) < tol else "warn")
    ctx.set_result(v)
    ctx.set_record({"outcome": "measured", "spread": v["spread"], "reported": v["reported"], "points": len(points), "light": v["light"]})


def _checker(kind):
    return lambda params, env: check_kind(kind, params, env)


for _kind, _fn in (("level.g32", run_g32), ("level.g30", run_g30), ("level.measure", run_measure)):
    procs.register(procs.Procedure(_kind, _fn, validate, motion="sequence", needs_probe=True, needs_homed=True, deploys=True, check=_checker(_kind)))
