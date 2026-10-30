"""The procedures that machine.run can start (Machine v2, phase 0): the registry and the one example.

A procedure is a function `fn(ctx, params)` run by machine_ops.py inside a reservation of the movement. It talks to the board ONLY through
`ctx.send(template, **numbers)` (machine_gcode.py: a closed list), reports with `ctx.progress(step, total, phase)`, calls `ctx.check()`
between steps (stop requested, machine halted, reservation lost -> the run ends as "aborted") and leaves its result with
`ctx.set_result({...})`. It never opens a connection, never reserves and never releases anything by itself.

Phase 0 has ONE procedure, `probe.read`: it reads the probe parameters (`G31 K..`, no values given, so nothing changes) and the probe
reading a few times (`M409`). It moves nothing and writes nothing; it exists to prove the whole pipeline end to end (reservation,
progress, stop, record, audit) on the real code path. It still takes the `sequence` reservation, like the real procedures will.
The other kinds of the design (section 4.1) are DECLARED here and answer `not_implemented` until their phase.
"""
import json
import math
import re


class UnknownKind(ValueError):
    """machine.run was asked for a kind that does not exist."""


class NotImplementedKind(ValueError):
    """The kind exists in the design but its phase has not been built."""


class BadParams(ValueError):
    """A parameter of a run is not valid; .field names it."""

    def __init__(self, field, detail=""):
        super().__init__("%s%s" % (field, ": " + detail if detail else ""))
        self.field = field


class ProcedureFailed(RuntimeError):
    """The procedure cannot go on (for example the board answered something it cannot read); .code is the reason code."""

    def __init__(self, code, detail=""):
        super().__init__("%s%s" % (code, ": " + detail if detail else ""))
        self.code = code


class Procedure:
    """What machine_ops needs to know about a procedure.

    motion        class of the movement reservation: "sequence" (calibrations) or "geometry" (changes the compensation)
    needs_probe   refused when the board reports no probe
    needs_homed   refused when a visible axis is not homed
    needs_confirm the service asks for the level 3 confirmation (confirm_required) before starting
    deploys       the run may leave the probe out: the runner retracts it (M402) at the end, whatever happens
    records       the end of the run is stored in the calibration history
    reserves      False: a read-only run that needs neither the movement nor a connection (safety.check): it is not refused by a job, takes no
                  reservation and `ctx.send` is not available
    prechecks     False: the generic refusals of machine_ops.precheck (no probe, not homed, heater fault...) do not apply: the run REPORTS them
    check         optional check(params, env) -> reason code or None, made at the start with env = {"om", "caps", "profile", "read"}: the
                  reasons that depend on the machine (no levelling possible, no points, a mesh bigger than the safety limit...)
    """

    def __init__(self, kind, fn, validate, motion="sequence", needs_probe=False, needs_homed=False, needs_confirm=False,
                 deploys=False, records=True, check=None, reserves=True, prechecks=True):
        self.kind = kind
        self.fn = fn
        self.validate = validate
        self.motion = motion
        self.needs_probe = needs_probe
        self.needs_homed = needs_homed
        self.needs_confirm = needs_confirm
        self.deploys = deploys
        self.records = records
        self.check = check
        self.reserves = reserves
        self.prechecks = prechecks


# the kinds of the design that wait for their phase (machine_store.RUN_KINDS minus what is registered); phase 1 registers probe.repeat,
# level.g32, level.g30, level.measure and mesh.probe (machine_probe.py, machine_level.py, machine_mesh.py)
PLANNED = ("probe.repeat", "probe.accuracy", "probe.trigger", "probe.offset", "level.g32", "level.g30", "level.measure", "mesh.probe",
           "homing.verify", "homing.repeat", "offsets.verify", "safety.check", "shaping.tune")
# reason code of Procedure.check -> message key (the texts are in i18n/es.json and en.json)
REFUSAL_KEYS = {
    "no_levelling": "machine_refuse_no_levelling", "no_m671": "machine_refuse_no_m671", "no_bed_g": "machine_refuse_no_bed_g",
    "no_points": "machine_refuse_no_points", "too_many_points": "machine_refuse_too_many_points",
    "too_few_points": "machine_refuse_too_few_points", "out_of_reach": "machine_refuse_out_of_reach",
    "duplicate_point": "machine_refuse_duplicate_point", "no_limits": "machine_refuse_no_limits",
    "descent_limit": "machine_refuse_descent_limit", "bad_region": "machine_refuse_bad_region",
    "no_probe_index": "machine_refuse_no_probe_index", "bed_g_points": "machine_refuse_bed_g_points",
    "no_endstops": "machine_refuse_no_endstops", "bad_axis": "machine_refuse_bad_axis",
    "no_accelerometer": "machine_refuse_no_accelerometer", "feed_too_high": "machine_refuse_feed_too_high",
    # phase 4: camera verification of offsets (machine_verify.py); the laser reasons are those of machine.mark_cross
    "no_vision_measure": "machine_refuse_no_vision_measure", "bad_target": "machine_refuse_bad_target",
    "tool_not_current": "machine_refuse_tool_not_current", "bad_power": "machine_refuse_laser_bad_power",
    "not_laser_mode": "machine_refuse_laser_not_laser_mode", "no_laser": "machine_refuse_laser_no_laser",
    "interlock_open": "machine_refuse_laser_interlock_open",
}
_registry = {}


def register(proc):
    _registry[proc.kind] = proc
    return proc


def unregister(kind):
    _registry.pop(kind, None)


def get(kind):
    """The procedure of `kind`; UnknownKind / NotImplementedKind otherwise."""
    if kind in _registry:
        return _registry[kind]
    if kind in PLANNED:
        raise NotImplementedKind(kind)
    raise UnknownKind(str(kind))


def kinds():
    """{"implemented": [...], "planned": [...]}"""
    return {"implemented": sorted(_registry), "planned": [k for k in PLANNED if k not in _registry]}


# ---- parameters ----

def _int(params, key, default, lo, hi):
    v = params.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BadParams(key, "%d..%d" % (lo, hi))
    return v


def _num(params, key, default, lo, hi):
    v = params.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or v != v:
        raise BadParams(key, "%g..%g" % (lo, hi))
    return float(v)


def _bool(params, key, default):
    v = params.get(key, default)
    if not isinstance(v, bool):
        raise BadParams(key, "true/false")
    return v


def _only(params, allowed):
    extra = sorted(set(params) - set(allowed))
    if extra:
        raise BadParams(extra[0], "unknown")


# ---- parsing of the board's answers (the wording changes with the firmware: tolerant, and None when it cannot read) ----

def parse_probe_value(reply):
    """M409 K"sensors.probes[i].value" answers {"key":..., "result":[v, ...]}; returns the first value or None."""
    try:
        doc = json.loads(str(reply))
    except ValueError:
        return None
    res = doc.get("result") if isinstance(doc, dict) else None
    first = res[0] if isinstance(res, list) and res else res
    return float(first) if isinstance(first, (int, float)) and not isinstance(first, bool) else None


_G31_THRESHOLD = re.compile(r"(?:trigger value|threshold)\s+(-?[0-9.]+)", re.I)
_G31_HEIGHT = re.compile(r"trigger height\s+(-?[0-9.]+)", re.I)
_G31_OFFSETS = re.compile(r"offsets?\s+X\s*(-?[0-9.]+)\s*Y\s*(-?[0-9.]+)", re.I)


def parse_g31(reply):
    """{"threshold", "trigger_height", "offset_x", "offset_y"} of the reply to `G31 K..` (a key is missing when the reply lacks it)."""
    text = str(reply)
    out = {}
    for key, rx in (("threshold", _G31_THRESHOLD), ("trigger_height", _G31_HEIGHT)):
        m = rx.search(text)
        if m:
            out[key] = float(m.group(1))
    m = _G31_OFFSETS.search(text)
    if m:
        out["offset_x"], out["offset_y"] = float(m.group(1)), float(m.group(2))
    return out


def stats(values):
    """n, min, max, range, mean and sample standard deviation (0 with one value)."""
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "min": min(values), "max": max(values), "range": max(values) - min(values), "mean": mean, "stdev": sd}


# ---- probe.read (the example) ----

def validate_probe_read(params):
    _only(params, ("probe", "samples", "interval_s"))
    return {"probe": _int(params, "probe", 0, 0, 15), "samples": _int(params, "samples", 5, 1, 20),
            "interval_s": _num(params, "interval_s", 0.5, 0.0, 5.0)}


def run_probe_read(ctx, params):
    idx, n = params["probe"], params["samples"]
    ctx.progress(0, n, "parameters")
    g31 = parse_g31(ctx.send("probe_params", index=idx))
    values = []
    for i in range(n):
        ctx.check()
        v = parse_probe_value(ctx.send("probe_value", index=idx))
        if v is None:
            raise ProcedureFailed("bad_reply", "probe_value")
        values.append(v)
        ctx.progress(i + 1, n, "sampling")
        if i < n - 1:
            ctx.wait(params["interval_s"])
    ctx.set_result({"probe": idx, "parameters": g31, "samples": values, "stats": stats(values)})


register(Procedure("probe.read", run_probe_read, validate_probe_read, motion="sequence", needs_probe=True))


# phase 1: the procedures register themselves when their module is imported (after everything above exists)
import machine_probe  # noqa: E402,F401
import machine_level  # noqa: E402,F401
import machine_mesh  # noqa: E402,F401
# phase 2: the read-only safety check and the endstop / homing verification
import machine_safety  # noqa: E402,F401
import machine_limits  # noqa: E402,F401
# phase 3: the accelerometer tuning of the input shaper (refused without the capability)
import machine_tune  # noqa: E402,F401
# phase 4: verification of the offsets with the camera (behind the Vision capability vision.measure)
import machine_verify  # noqa: E402,F401
