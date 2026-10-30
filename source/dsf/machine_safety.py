"""Safety check of Machine v2 (design 2.9): the run kind `safety.check`, READ ONLY.

It moves nothing, sends nothing to the board and takes no reservation of the movement (Procedure(reserves=False, prechecks=False)): it works
from the object model the service already has, so it can run during a job and it REPORTS what machine.run refuses for the other kinds (no
probe, axes not homed, a heater fault). Only facts that the object model (or the service's own state) can verify; whatever cannot be known
says so: severity "unavailable".

Result (the page translates ids, severities and action keys with its own catalog):
    {"generated_at": epoch, "verdict": "ok" | "warn" | "bad",
     "counts": {"ok": n, "info": n, "warn": n, "bad": n, "unavailable": n},
     "items": [{"id", "severity", "action": key or null, "values": {numbers / codes}}]}
Severities: ok (fine), info (nothing wrong, worth knowing), warn (look at it), bad (do not calibrate or cut before fixing it),
unavailable (cannot be known from the object model). `verdict` is the worst of bad > warn > ok; info / unavailable do not count.

Action keys (what the page offers; the service does not run them): home_axes, open_levelling, check_probe, check_probe_offsets,
check_limits, check_endstops, see_heaters, see_sensors, reset_board, fix_startup_error, check_supply, close_interlocks,
declare_interlocks, check_config_guard, kinematics_unsupported.

THRESHOLDS that are a guess (not from the documentation): the supply voltage window below (the absolute range of the Duet 3 boards is not
in the verified reference, GCODE-REFERENCE section 6) and "an endstop triggered more than 1 mm from its end".
"""
import job_states
import time

import capabilities
import machine_geometry as geo
import machine_procedures as procs

VIN_MIN, VIN_MAX = 11.0, 29.0       # volts; outside this window something is wrong with the supply or the reading (a guess, to tune)
ENDSTOP_AWAY_MM = 1.0
SEVERITIES = ("ok", "info", "warn", "bad", "unavailable")
HALTED = ("halted",)
NOT_RUNNING = ("off", "disconnected", "starting", "updating")


def item(ident, severity, action=None, **values):
    return {"id": ident, "severity": severity, "action": action, "values": values}


def _axes(om):
    return [a for a in ((om or {}).get("move") or {}).get("axes") or [] if isinstance(a, dict) and a.get("visible", True)]


# ---- the checks (each returns one item) ----

def check_kinematics(om, caps):
    name = str((((om or {}).get("move") or {}).get("kinematics") or {}).get("name") or "cartesian")
    if name.lower() in capabilities.SUPPORTED_KINEMATICS:
        return item("kinematics", "ok", name=name)
    return item("kinematics", "bad", "kinematics_unsupported", name=name)


def check_homed(om, caps):
    axes = _axes(om)
    if not axes:
        return item("homed", "unavailable", reason="no_axes")
    pending = [a.get("letter") for a in axes if not a.get("homed")]
    return item("homed", "warn", "home_axes", axes=pending) if pending else item("homed", "ok")


def check_z_motors(om, caps):
    lev = (((caps or {}).get("capabilities") or {}).get("levelling") or {})
    mode, entries, z = lev.get("mode"), lev.get("m671_entries"), lev.get("z_motors")
    if mode == "missingM671":
        return item("z_motors", "warn", "open_levelling", z_motors=z, m671_entries=entries, mode=mode)
    if mode == "leadscrews" and entries != z:
        return item("z_motors", "warn", "open_levelling", z_motors=z, m671_entries=entries, mode=mode)
    if mode in ("unknown", None):
        return item("z_motors", "unavailable", reason="configuration_not_read")
    return item("z_motors", "ok", z_motors=z, m671_entries=entries, mode=mode)


def check_probe(om, caps):
    idx = geo.first_probe_index(om)
    if idx is None:
        return item("probe", "info", reason="no_probe")
    probe = geo.probe_of(om, idx)
    value = probe.get("value")
    readable = isinstance(value, list) and value and isinstance(value[0], (int, float)) and not isinstance(value[0], bool)
    if not readable:
        return item("probe", "warn", "check_probe", probe=idx, type=probe.get("type"), reason="no_reading")
    return item("probe", "ok", probe=idx, type=probe.get("type"), value=value[0], trigger_height=geo.num(probe.get("triggerHeight")))


def check_probe_offsets(om, caps):
    idx, lim = geo.first_probe_index(om), geo.limits(om)
    if idx is None:
        return item("probe_offsets", "info", reason="no_probe")
    if lim is None:
        return item("probe_offsets", "unavailable", reason="no_limits")
    ox, oy = geo.offsets_of(geo.probe_of(om, idx))
    bed_x, bed_y = lim["xmax"] - lim["xmin"], lim["ymax"] - lim["ymin"]
    if abs(ox) >= bed_x or abs(oy) >= bed_y:
        return item("probe_offsets", "warn", "check_probe_offsets", x=ox, y=oy, bed_x=bed_x, bed_y=bed_y)
    return item("probe_offsets", "ok", x=ox, y=oy)


def check_reach(om, caps):
    idx, lim = geo.first_probe_index(om), geo.limits(om)
    if idx is None:
        return item("reach", "info", reason="no_probe")
    if lim is None:
        return item("reach", "unavailable", reason="no_limits")
    r = geo.reach(lim, geo.offsets_of(geo.probe_of(om, idx)))
    if r is None:
        return item("reach", "bad", "check_limits", reason="probe_cannot_reach_the_bed")
    return item("reach", "ok", **{k: geo.rnd(v, 2) for k, v in r.items()})


def check_endstops(om, caps):
    ends = ((om or {}).get("sensors") or {}).get("endstops")
    axes = _axes(om)
    if not isinstance(ends, list) or not axes:
        return item("endstops", "unavailable", reason="no_endstop_data")
    missing, away = [], []
    for i, a in enumerate(((om.get("move") or {}).get("axes")) or []):
        if not isinstance(a, dict) or not a.get("visible", True) or a.get("letter") not in ("X", "Y", "Z"):
            continue
        e = ends[i] if i < len(ends) else None
        if not isinstance(e, dict):
            missing.append(a.get("letter"))
            continue
        pos, lo, hi = geo.num(a.get("machinePosition")), geo.num(a.get("min")), geo.num(a.get("max"))
        edge = hi if e.get("highEnd") else lo
        if e.get("triggered") and a.get("homed") and None not in (pos, edge) and abs(pos - edge) > ENDSTOP_AWAY_MM:
            away.append(a.get("letter"))
    if away:
        return item("endstops", "warn", "check_endstops", triggered_away_from_home=away, without_endstop=missing)
    if missing:
        return item("endstops", "warn", "check_endstops", without_endstop=missing)
    return item("endstops", "ok")


def check_heaters(om, caps):
    heaters = ((om or {}).get("heat") or {}).get("heaters") or []
    states = {i: h.get("state") for i, h in enumerate(heaters) if isinstance(h, dict)}
    fault = sorted(i for i, s in states.items() if s == "fault")
    offline = sorted(i for i, s in states.items() if s == "offline")
    if fault:
        return item("heaters", "bad", "see_heaters", fault=fault, offline=offline)
    if offline:
        return item("heaters", "warn", "see_heaters", offline=offline)
    return item("heaters", "ok", count=len(states)) if states else item("heaters", "info", reason="no_heaters")


def check_sensors(om, caps):
    bad = []
    for i, s in enumerate(((om or {}).get("sensors") or {}).get("analog") or []):
        if isinstance(s, dict) and s.get("state") not in (None, "ok"):
            bad.append({"index": i, "name": s.get("name"), "state": s.get("state")})
    return item("sensors", "warn", "see_sensors", sensors=bad[:8]) if bad else item("sensors", "ok")


def check_status(om, caps):
    st = ((om or {}).get("state") or {})
    status, startup = st.get("status"), st.get("startupError")
    if startup:
        return item("status", "bad", "fix_startup_error", status=status)
    if status in HALTED:
        return item("status", "bad", "reset_board", status=status)
    if status in NOT_RUNNING:
        return item("status", "warn", None, status=status)
    if status is None:
        return item("status", "unavailable", reason="no_state")
    return item("status", "ok", status=status)


def check_reset_reason(om, caps):
    # GCODE-REFERENCE 9.14: the object model has no key for the reason of the last reset; it only appears in the text of M122.
    return item("reset_reason", "unavailable", reason="no_verified_key")


def check_supply(om, caps):
    boards = (om or {}).get("boards") or []
    vin = (boards[0].get("vIn") if boards and isinstance(boards[0], dict) else None) or {}
    cur = geo.num(vin.get("current"))
    if cur is None:
        return item("supply", "unavailable", reason="no_vin")
    values = {"vin": cur, "min": geo.num(vin.get("min")), "max": geo.num(vin.get("max"))}
    return item("supply", "bad", "check_supply", **values) if not VIN_MIN <= cur <= VIN_MAX else item("supply", "ok", **values)


def check_interlocks(om, caps, rows=None):
    if rows is None:
        return item("interlocks", "unavailable", reason="no_profile")
    if not rows:
        return item("interlocks", "info", "declare_interlocks", reason="not_declared")
    bad = [{"name": r["name"], "state": r["state"]} for r in rows if r["state"] != "ok"]
    return item("interlocks", "warn", "close_interlocks", interlocks=bad) if bad else item("interlocks", "ok", count=len(rows))


def check_guard(om, caps, guard=None):
    if guard is None:
        return item("config_guard", "unavailable", reason="no_guard_state")
    if guard.get("state") == "armed":
        return item("config_guard", "warn", "check_config_guard", remaining_s=guard.get("remaining_s"), failure=guard.get("failure"))
    return item("config_guard", "ok")


def check_job(om, caps):
    status = (((om or {}).get("state") or {}).get("status"))
    return item("job", "info", None, status=status) if status in job_states.ACTIVE else item("job", "ok")


MODEL_CHECKS = (check_kinematics, check_homed, check_z_motors, check_probe, check_probe_offsets, check_reach, check_endstops, check_heaters,
                check_sensors, check_status, check_reset_reason, check_supply, check_job)


def evaluate(om, caps, interlock_rows=None, guard=None, now=None):
    """The whole check (pure). `om` may be empty: then every model check reports what it can."""
    items = [fn(om or {}, caps) for fn in MODEL_CHECKS]
    items.append(check_interlocks(om, caps, interlock_rows))
    items.append(check_guard(om, caps, guard))
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITIES}
    verdict = "bad" if counts["bad"] else "warn" if counts["warn"] else "ok"
    return {"generated_at": int(now if now is not None else time.time()), "verdict": verdict, "counts": counts, "items": items}


# ---- the run ----

def _interlock_rows(om):
    try:
        import interlocks
        import machine_profile
        return interlocks.state(machine_profile.load(), om)
    except Exception:  # noqa: BLE001 - an unreadable profile is "unavailable", not a failure of the check
        return None


def _guard_state():
    try:
        import config_guard
        return config_guard.state_public(config_guard.api_thread())["guard"]
    except Exception:  # noqa: BLE001
        return None


def validate(params):
    procs._only(params, ())
    return {}


def run_check(ctx, params):
    ctx.progress(0, 1, "checking")
    om = ctx.model()
    result = evaluate(om, ctx.caps(), _interlock_rows(om), _guard_state())
    ctx.set_result(result)
    ctx.set_record({"outcome": result["verdict"], "counts": result["counts"],
                    "attention": [i["id"] for i in result["items"] if i["severity"] in ("warn", "bad")]})
    ctx.progress(1, 1, "checking")


procs.register(procs.Procedure("safety.check", run_check, validate, motion="sequence", reserves=False, prechecks=False))
