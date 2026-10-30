"""`machine.motion.get` of Machine v2 (phase 3, design 2.8): the table of motion parameters per axis and extruder.

Everything comes from the object model (move.axes[], move.extruders[], move.idle, move.compensation.skew) and, for what the model does not publish
(the driver mode and direction), from the `M569 P.. S.. D..` lines of config.g and the macros it calls. A value the board did not report is `null`
and its name is in the row's `unavailable` list: nothing is invented and nothing is assumed from a typical machine. Read only; editing is
`machine.config.plan` (kinds config.m906 ... config.m569) and the volatile trial is `machine.try`.

Row (axes and extruders):
    kind "axis"|"extruder", index, letter ("E", "E1"...), drivers ["0.0"], steps_per_mm, microstepping, interpolated, current_ma (M906),
    current_percent (M913), standstill_percent (M917), speed (mm/min, M203), acceleration (mm/s2, M201), jerk (mm/min, M566),
    printing_jerk (mm/s, M205), backlash (mm, M425; axes only), driver_mode "spreadcycle"|"stealthchop"|"other"|null,
    driver_mode_source "config"|"default"|null, direction 0|1|null, unavailable [names]
"""
import config_scan
import machine_patch_motion as pm
import machine_profile
from workshop_api import READ, Op

OM_FIELDS = (("steps_per_mm", "stepsPerMm"), ("current_ma", "current"), ("current_percent", "percentCurrent"),
             ("standstill_percent", "percentStstCurrent"), ("speed", "speed"), ("acceleration", "acceleration"), ("jerk", "jerk"),
             ("printing_jerk", "printingJerk"))
CHECKED = tuple(k for k, _ in OM_FIELDS) + ("microstepping", "interpolated", "driver_mode")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def config_drivers(read):
    """({driver: {"direction", "mode"}} from the configuration, config_read). The later file / line wins, like in the firmware."""
    scan = config_scan.scan(read)
    out = {}
    for path in scan["files"]:
        for drv, row in pm.read_m569(read(path) or "").items():
            cur = out.setdefault(drv, {"direction": None, "mode": None})
            cur.update({k: v for k, v in row.items() if v is not None})
    return out, scan["read"]


def _driver_mode(drivers, config, config_read):
    """(mode, source, direction) of the first driver of the axis."""
    drv = pm.norm_driver(drivers[0]) if drivers else None
    row = config.get(drv) if drv else None
    if not config_read or row is None:
        return None, None, None            # no line (or no file): the model does not say and a macro may set it, so it is not guessed
    if row["mode"] is None:
        return "spreadcycle", "default", row["direction"]       # no D on the line: the default of the firmware since 3.4 (reference section 3)
    return row["mode"], "config", row["direction"]


def build_row(kind, index, letter, d, drivers, config, config_read):
    ms = d.get("microstepping") if isinstance(d.get("microstepping"), dict) else {}
    row = {"kind": kind, "index": index, "letter": letter, "drivers": drivers}
    for key, om_key in OM_FIELDS:
        row[key] = _num(d.get(om_key))
    row["microstepping"] = _num(ms.get("value"))
    row["interpolated"] = ms.get("interpolated") if isinstance(ms.get("interpolated"), bool) else None
    row["backlash"] = _num(d.get("backlash")) if kind == "axis" else None
    row["driver_mode"], row["driver_mode_source"], row["direction"] = _driver_mode(drivers, config, config_read)
    row["unavailable"] = [k for k in CHECKED if row[k] is None] + (["backlash"] if kind == "axis" and row["backlash"] is None else [])
    return row


def _strings(v):
    return [str(x) for x in v] if isinstance(v, list) else []


def motion_view(om, read, machine_block):
    mv = (om or {}).get("move") or {}
    config, config_read = config_drivers(read)
    axes = [build_row("axis", i, a.get("letter"), a, _strings(a.get("drivers")), config, config_read)
            for i, a in enumerate(mv.get("axes") or []) if isinstance(a, dict) and a.get("letter")]
    exts = []
    for i, e in enumerate(mv.get("extruders") or []):
        if isinstance(e, dict):
            drv = [str(e["driver"])] if e.get("driver") is not None else _strings(e.get("drivers"))
            exts.append(build_row("extruder", i, "E" if i == 0 else "E%d" % i, e, drv, config, config_read))
    idle = mv.get("idle") if isinstance(mv.get("idle"), dict) else {}
    f = _num(idle.get("factor"))
    sk = (mv.get("compensation") or {}).get("skew") if isinstance(mv.get("compensation"), dict) else None
    sk = sk if isinstance(sk, dict) else {}
    return {"axes": axes, "extruders": exts,
            "idle": {"percent": None if f is None else round(f * 100, 2), "timeout_s": _num(idle.get("timeout"))},
            "backlash_factor": _num(mv.get("backlashFactor")),
            "skew": {"tan_xy": _num(sk.get("tanXY")), "tan_yz": _num(sk.get("tanYZ")), "tan_xz": _num(sk.get("tanXZ"))},
            "limits": {"max_current_ma": machine_profile.current_cap(machine_block), "ceiling_ma": machine_profile.CURRENT_CEILING_MA},
            "config_read": config_read}


def _op(args, ctx):
    import machine_ops as mo
    return motion_view(mo.model(), mo.read_sd, mo.profile_block())


def ops():
    return [Op("machine.motion.get", _op, READ, {},
               "The motion parameters per axis and extruder from the object model and the M569 lines of the configuration: current (M906), "
               "idle factor and timeout, standstill and percent current (M913 / M917), microstepping and interpolation, speed, acceleration, jerk, "
               "backlash, driver mode and direction. What the board did not report is null and listed in `unavailable`.", log=False)]
