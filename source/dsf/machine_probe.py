"""Probe procedures of Machine v2 (phase 1): `probe.repeat`, the repeatability test, and the helpers the levelling and mesh runs share.

probe.repeat   N touches at ONE point (`G30 K.. S-1`, measure only: it reports the stop height and never moves the Z datum), then the mean,
               sample standard deviation, min / max / range, the drift between the first and the second half, and a traffic light by the
               thresholds of the profile (`machine.thresholds`: probe_sigma_warn / probe_sigma_bad; starting values, a guess).
               With x and y the touches are made with `G30 P0 X.. Y.. Z-99999 K.. S-1`: the firmware goes to that point (where the PROBE
               touches) and probes from the dive height, so no move of this module ever goes down blindly.

Safety (profile `machine.safety`): the Z descent of one touch is bounded by the firmware floor (M208 Z min minus the dive height plus the
trigger height); a start where that bound is over `max_probe_descent_mm` is refused, and a reading below the limit ends the run. Every line
goes through machine_gcode (closed list); a stop request is honoured between touches; the probe is retracted at the end by the runner.

Replies are read tolerantly (machine_parsers): "Stopped at height" (verified in the 3.6.1 source), else the probe's `lastStopHeight` of the
object model, else the single value of a `bed probe heights:` line. The source of every reading is recorded.
"""
import machine_geometry as geo
import machine_parsers as parsers
import machine_procedures as procs

MAX_SAMPLES = 100


class Reading:
    """One measured height and where it came from ("reply", "model", "bed_heights")."""

    def __init__(self, height, source, errors=()):
        self.height, self.source, self.errors = height, source, list(errors)


def probe_index(params, profile, om):
    """The probe to use: the asked one, else the profile's, else the first real probe of the board; None when there is none."""
    if params.get("probe") is not None:
        return params["probe"]
    idx = ((profile or {}).get("probe") or {}).get("index")
    if idx is None:
        idx = geo.first_probe_index(om)
    return idx


def read_height(ctx, reply, k):
    """The height a G30 left, from its reply or, when the reply says nothing readable, from the probe in the object model.
    Raises ProcedureFailed("probe_error", first error text) when the board reported an error; returns Reading(None, ...) otherwise."""
    g30 = parsers.parse_g30(reply)
    if g30["errors"]:
        raise procs.ProcedureFailed("probe_error", "; ".join(e["text"] for e in g30["errors"])[:200])
    if g30["height"] is not None:
        return Reading(g30["height"], "reply")
    heights = parsers.parse_bed_heights(reply)
    if heights["matched"] and len(heights["heights"]) == 1 and heights["heights"][0] is not None:
        return Reading(heights["heights"][0], "bed_heights")
    value = parsers.parse_number_result(ctx.send("probe_last_stop", index=k))
    return Reading(value, "model") if value is not None else Reading(None, "none")


def z_state(ctx, om):
    """Where the head is NOW, read from the board (the model of the service can be a moment old): {"machine", "user", "min"} of the Z axis.
    A number the board does not give falls back to the model; without the machine position the run does not start blind
    (ProcedureFailed("descent_unknown")): the descent limit could not be kept."""
    idx = geo.axis_index(om, "Z")
    res = parsers.parse_json_result(ctx.send("axis_state", index=idx))
    res = res if isinstance(res, dict) else {}
    z = (geo.axes_by_letter(om).get("Z") or {})
    machine = geo.num(res.get("machinePosition"))
    machine = machine if machine is not None else geo.num(z.get("machinePosition"))
    if machine is None:
        raise procs.ProcedureFailed("descent_unknown")
    user = geo.num(res.get("userPosition"))
    zmin = geo.num(res.get("min"))
    return {"machine": machine, "user": user if user is not None else machine, "min": zmin if zmin is not None else geo.num(z.get("min"))}


def descent_guard(om, k, profile, state, height=None):
    """ProcedureFailed("descent_limit") when the probing would go (or went) further down than the profile allows.
    Before the touch (height None): the bound from where the head is. After it: the real descent from where the head started
    (`height` is a stop height in user coordinates, like the figure the firmware reports)."""
    limit = ((profile or {}).get("safety") or {}).get("max_probe_descent_mm")
    if limit is None:
        return None
    if height is None:
        bound = geo.descent_bound(om, k, z=state["machine"], zmin=state["min"])
        if bound is not None and bound > limit:
            raise procs.ProcedureFailed("descent_limit", "%.1f > %.1f" % (bound, limit))
        return bound
    if state["user"] - height > limit:
        raise procs.ProcedureFailed("descent_limit", "%.1f > %.1f" % (state["user"] - height, limit))
    return None


# ---- probe.repeat ----

def validate_repeat(params):
    procs._only(params, ("probe", "samples", "x", "y", "deploy_each"))
    out = {"samples": procs._int(params, "samples", 10, 2, MAX_SAMPLES), "deploy_each": procs._bool(params, "deploy_each", False)}
    out["probe"] = procs._int(params, "probe", 0, 0, 15) if params.get("probe") is not None else None
    if (params.get("x") is None) != (params.get("y") is None):
        raise procs.BadParams("x", "x and y go together")
    if params.get("x") is not None:
        out["x"], out["y"] = procs._num(params, "x", 0, -5000, 5000), procs._num(params, "y", 0, -5000, 5000)
    return out


def check_repeat(params, env):
    om, mach = env["om"], env["profile"]
    k = probe_index(params, mach, om)
    if k is None or geo.probe_of(om, k) is None:
        return "no_probe_index"
    if params.get("x") is not None:
        lim = geo.limits(om)
        if lim is None:
            return "no_limits"
        if not geo.head_inside((params["x"], params["y"]), lim, geo.offsets_of(geo.probe_of(om, k))):
            return "out_of_reach"
    bound = geo.descent_bound(om, k)
    limit = (mach.get("safety") or {}).get("max_probe_descent_mm")
    if bound is not None and limit is not None and bound > limit:
        return "descent_limit"
    return None


def verdict(sigma, thresholds):
    """ok / warn / bad by the standard deviation against the profile's thresholds."""
    warn, bad = thresholds.get("probe_sigma_warn"), thresholds.get("probe_sigma_bad")
    if warn is None or bad is None:
        return "unknown"
    return "bad" if sigma > bad else "warn" if sigma > warn else "ok"


def drift(values):
    """Mean of the second half minus the mean of the first half (positive: the readings rise)."""
    half = len(values) // 2
    if half < 1:
        return 0.0
    first, second = values[:half], values[len(values) - half:]
    return sum(second) / len(second) - sum(first) / len(first)


def summary_of(values, sources, thresholds, k, point, trigger_height, complete):
    st = procs.stats(values) if values else None
    out = {"probe": k, "point": point, "complete": complete, "trigger_height": trigger_height, "sources": sources}
    if st:
        sigma = st["stdev"]
        out.update(stats={key: round(v, 4) if isinstance(v, float) else v for key, v in st.items()}, drift=round(drift(values), 4),
                   verdict={"light": verdict(sigma, thresholds), "sigma": round(sigma, 4), "warn": thresholds.get("probe_sigma_warn"),
                            "bad": thresholds.get("probe_sigma_bad")})
    return out


def run_repeat(ctx, params):
    prof = ctx.profile()
    om = ctx.model()
    k = probe_index(params, prof, om)
    probe = geo.probe_of(om, k)
    if probe is None:
        raise procs.ProcedureFailed("no_probe_index")
    ctx.use_probe(k)
    thresholds = prof.get("thresholds") or {}
    n = params["samples"]
    point = {"x": params["x"], "y": params["y"]} if params.get("x") is not None else None
    state = z_state(ctx, om)
    descent_guard(om, k, prof, state)
    values, sources = [], {}
    ctx.progress(0, n, "measuring")
    try:
        for i in range(n):
            ctx.check()
            if params["deploy_each"]:
                ctx.send("probe_deploy", index=k)
            reply = ctx.send("probe_point_last", p=0, x=point["x"], y=point["y"], k=k, s=-1) if point else ctx.send("probe_stop", k=k)
            if params["deploy_each"]:
                ctx.send("probe_retract", index=k)
            reading = read_height(ctx, reply, k)
            if reading.height is None:
                raise procs.ProcedureFailed("bad_reply", str(reply)[:120])
            descent_guard(om, k, prof, state, reading.height)
            values.append(reading.height)
            sources[reading.source] = sources.get(reading.source, 0) + 1
            ctx.progress(i + 1, n, "measuring")
    except Exception:
        ctx.set_result(summary_of(values, sources, thresholds, k, point, geo.num(probe.get("triggerHeight")), False))
        raise
    result = summary_of(values, sources, thresholds, k, point, geo.num(probe.get("triggerHeight")), True)
    result["samples"] = [round(v, 3) for v in values]
    result["outcome"] = result["verdict"]["light"]
    ctx.set_result(result)
    ctx.set_record(result)


procs.register(procs.Procedure("probe.repeat", run_repeat, validate_repeat, motion="sequence", needs_probe=True, needs_homed=True,
                               deploys=True, check=check_repeat))
