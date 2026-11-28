"""Bed zones calibration, the PURE part: what a preheat or a tuning of the zones will do, with every number checked (no I/O, no clock).

The runner is machine_bedcal.py (two procedures of machine.run: `bedcal.preheat` and `bedcal.tune`); the operations are
bed_calibration_ops.py (`bedcal.plan` shows exactly this plan, `bedcal.preheat` / `bedcal.tune` start it). Both call the functions of this file,
so what the person is shown is what the service sends: every line is rendered from a template of the closed list (machine_gcode.py) and the
temperatures are bounded here, in three independent ways:
  - the range of the assistant, TUNE_TEMP_RANGE (30..150 C), the same as the page (`bed-calibration.js`);
  - the maximum of the bed zones settings (`max_temp`) and their maximum offset (`max_offset`);
  - the cap of the heater itself in the object model (`heat.heaters[h].max`, the M143 of the firmware): a preheat target may not pass it and a tuning
    target (which swings above the setpoint while the relay oscillates) must stay CAP_MARGIN_TUNE below it.
A zone must be configured, have a heater of its own (two zones on one heater cannot be told apart) and that heater must not be in fault or already
tuning. Every refusal is a short code (REFUSALS, texts `bedcal_refuse_<code>`); nothing here raises anything else for a bad request.
"""
import math

import json

import machine_gcode

SETTINGS_PATH = "0:/sys/workshop/config/bed-zones.json"  # the settings area "bed-zones" (settings_store.py): read as text, so this file imports nothing of the service
TUNE_TEMP_RANGE = (30.0, 150.0)  # the same range as bed-calibration.js
STAGGER_RANGE = (0, 600)         # seconds between two starts
HOLD_RANGE = (0, 60)             # minutes the zones stay hot after a preheat, then they are turned off
DEFAULT_HOLD_MIN = 15
MAX_ZONES = 16
CAP_MARGIN_TUNE = 10.0           # C: a tuning target must be this far under the cap of the heater (the relay tuning swings above the setpoint)
TOL_DEFAULT = 5.0                # C: a neighbour counts as "at temperature" within this
MARGIN_COLD = 22.0               # C under the target the tuned zone must start from (RRF asks for 20; 2 C of margin, not 5)
OVER_TARGET = 40.0               # C over its target: something is wrong, everything is turned off

REFUSALS = ("bad_param", "no_zone_config", "unknown_zone", "inactive_zone", "no_heater", "heater_shared", "heater_fault", "heater_tuning", "over_zone_max",
            "over_heater_cap", "offset_range", "not_idle", "no_model", "tune_busy")


class Refused(ValueError):
    """The request cannot be run; .code is one of REFUSALS and .params the numbers for the text."""

    def __init__(self, code, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# ---- the settings of the zones (read tolerantly: the page validates them when it saves) ----

def read_settings(text):
    """{"max_temp", "max_offset", "tolerance", "zones": {bed: {"active", "offset"}}} from the TEXT of the settings file, or Refused no_zone_config."""
    try:
        value = json.loads((text or "").lstrip("﻿"))
    except ValueError:
        raise Refused("no_zone_config")
    if not isinstance(value, dict) or not isinstance(value.get("zones"), list):
        raise Refused("no_zone_config")
    max_temp, max_offset, tol = _num(value.get("max_temp")), _num(value.get("max_offset")), _num(value.get("tolerance"))
    if max_temp is None or not 0 < max_temp <= 200 or max_offset is None or not 0 <= max_offset <= 30:
        raise Refused("no_zone_config")
    zones = {}
    for z in value["zones"]:
        bed, off = (_int(z.get("bed")) if isinstance(z, dict) else None), (_num(z.get("offset", 0.0)) if isinstance(z, dict) else None)
        if bed is None or not 0 <= bed <= 31 or off is None or z.get("active", True) not in (True, False):
            raise Refused("no_zone_config")
        zones[bed] = {"active": bool(z.get("active", True)), "offset": off}
    if not zones:
        raise Refused("no_zone_config")
    return {"max_temp": max_temp, "max_offset": max_offset, "tolerance": tol if tol is not None and 0 < tol <= 15 else 2.0, "zones": zones}


# ---- the zones of a request ----

def _heaters(om):
    heat = (om or {}).get("heat") if isinstance(om, dict) else None
    heat = heat if isinstance(heat, dict) else {}
    return list(heat.get("bedHeaters") or []), list(heat.get("heaters") or [])


def idle_check(om):
    """Refused not_idle unless the machine is idle (no job, no pause, not busy with something else) and no heater is being tuned."""
    status = str((((om or {}).get("state") or {}).get("status")) or "").lower()
    if status != "idle":
        raise Refused("not_idle", status=status or "?")
    if any(isinstance(h, dict) and h.get("state") == "tuning" for h in _heaters(om)[1]):
        raise Refused("heater_tuning")


def resolve(om, settings, beds, active_only=True):
    """[{bed, heater, cap, offset}] for the requested beds in their order. Refused unknown_zone / inactive_zone / no_heater / heater_shared /
    heater_fault / heater_tuning / offset_range."""
    slots, heaters = _heaters(om)
    rows, seen = [], set()
    for bed in beds:
        z = settings["zones"].get(bed)
        if z is None:
            raise Refused("unknown_zone", bed=bed)
        if active_only and not z["active"]:
            raise Refused("inactive_zone", bed=bed)
        idx = slots[bed] if bed < len(slots) else None
        h = heaters[idx] if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(heaters) else None
        if not isinstance(h, dict):
            raise Refused("no_heater", bed=bed)
        if idx in seen:
            raise Refused("heater_shared", bed=bed)
        seen.add(idx)
        if h.get("state") == "fault":
            raise Refused("heater_fault", bed=bed)
        if h.get("state") == "tuning":
            raise Refused("heater_tuning", bed=bed)
        cap = _num(h.get("max"))
        if abs(z["offset"]) > settings["max_offset"]:
            raise Refused("offset_range", bed=bed, max=settings["max_offset"])
        rows.append({"bed": bed, "heater": idx, "cap": cap, "offset": z["offset"]})
    return rows


def only(params, allowed):
    """Refused bad_param for an argument that is not one of `allowed` (or when params is not an object)."""
    if not isinstance(params, dict):
        raise Refused("bad_param", field="params")
    extra = sorted(set(params) - set(allowed))
    if extra:
        raise Refused("bad_param", field=extra[0])


def clean_beds(raw):
    """The beds of a request: 1..MAX_ZONES distinct whole numbers 0..31, in order. Refused bad_param."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ZONES or any(_int(b) is None or not 0 <= b <= 31 for b in raw) or len(set(raw)) != len(raw):
        raise Refused("bad_param", field="beds")
    return list(raw)


def clean_temp(raw, field="temp"):
    v = _num(raw)
    if v is None or not TUNE_TEMP_RANGE[0] <= v <= TUNE_TEMP_RANGE[1]:
        raise Refused("bad_param", field=field)
    return v


def bounded(field, raw, lo, hi, as_int=True):
    v = _num(raw)
    if v is None or not lo <= v <= hi:
        raise Refused("bad_param", field=field)
    return int(round(v)) if as_int else v


# ---- the preheat ----

def plan_preheat(om, settings, params):
    """The plan of a preheat. params: {beds (the order, edges first: the page computes it), temp, stagger_s, hold_min}.
    -> {"kind", "temp", "stagger_s", "hold_s", "tolerance", "zones": [{bed, heater, cap, offset, target, start_s}], "steps": [{at_s, code}], "off": [codes]}"""
    beds = clean_beds(params.get("beds"))
    temp = clean_temp(params.get("temp"))
    stagger = bounded("stagger_s", params.get("stagger_s", 30), STAGGER_RANGE[0], STAGGER_RANGE[1])
    hold = bounded("hold_min", params.get("hold_min", DEFAULT_HOLD_MIN), HOLD_RANGE[0], HOLD_RANGE[1])
    idle_check(om)
    rows = resolve(om, settings, beds)
    zones, steps = [], []
    for k, r in enumerate(rows):
        target = temp + r["offset"]
        if target < 1:
            raise Refused("offset_range", bed=r["bed"], max=settings["max_offset"])
        if target > settings["max_temp"]:
            raise Refused("over_zone_max", bed=r["bed"], target=machine_gcode.num_text(target), max=machine_gcode.num_text(settings["max_temp"]))
        if r["cap"] is not None and target > r["cap"]:
            raise Refused("over_heater_cap", bed=r["bed"], target=machine_gcode.num_text(target), cap=machine_gcode.num_text(r["cap"]))
        z = dict(r, target=target, start_s=k * stagger)
        zones.append(z)
        steps.append({"at_s": z["start_s"], "code": machine_gcode.render("bed_set", bed=r["bed"], set_temp=target)})
    return {"kind": "preheat", "temp": temp, "stagger_s": stagger, "hold_s": hold * 60, "tolerance": max(settings["tolerance"], 1.0),
            "zones": zones, "steps": steps, "off": off_lines(zones)}


def off_lines(zones):
    """One M140 off per zone of the plan (the Stop button and the fail-safe send exactly these)."""
    return [machine_gcode.render("bed_off", bed=z["bed"]) for z in zones]


# ---- the tuning ----

def plan_tune(om, settings, params):
    """The plan of a tuning, zone by zone in the given order. params: {beds, temp, together, only?}.
    `beds` are all the zones that take part (the neighbours of each other); `only` (a subset of them, default all) are the ones that are tuned.
    The tuned zone is off and cold at its start; with `together` the other zones of `beds` are held at `temp` (no offset: the model is the coupled one), else off.
    -> {"kind", "temp", "together", "tolerance", "zones": [{bed, heater, cap, offset, target, tune}], "steps": [{zone, code}], "off": [codes]}"""
    beds = clean_beds(params.get("beds"))
    temp = clean_temp(params.get("temp"))
    together = params.get("together", True)
    if not isinstance(together, bool):
        raise Refused("bad_param", field="together")
    only = params.get("only")
    if only is None:
        only = beds
    if not isinstance(only, list) or not only or any(b not in beds for b in only) or len(set(only)) != len(only):
        raise Refused("bad_param", field="only")
    idle_check(om)
    rows = resolve(om, settings, beds, active_only=False)
    if temp > settings["max_temp"]:
        raise Refused("over_zone_max", bed=rows[0]["bed"], target=machine_gcode.num_text(temp), max=machine_gcode.num_text(settings["max_temp"]))
    for r in rows:
        if r["cap"] is not None and temp > r["cap"] - CAP_MARGIN_TUNE:
            raise Refused("over_heater_cap", bed=r["bed"], target=machine_gcode.num_text(temp), cap=machine_gcode.num_text(r["cap"] - CAP_MARGIN_TUNE))
    zones = [dict(r, target=temp, tune=r["bed"] in only) for r in rows]
    steps = []
    for z in [z for z in zones if z["tune"]]:
        for o in zones:
            if o is z:
                steps.append({"zone": z["bed"], "code": machine_gcode.render("bed_off", bed=o["bed"])})
            elif together:
                steps.append({"zone": z["bed"], "code": machine_gcode.render("bed_set", bed=o["bed"], set_temp=temp)})
            else:
                steps.append({"zone": z["bed"], "code": machine_gcode.render("bed_off", bed=o["bed"])})
        steps.append({"zone": z["bed"], "code": machine_gcode.render("heater_tune", heater=z["heater"], tune_temp=temp)})
        steps.append({"zone": z["bed"], "code": machine_gcode.render("tune_report")})
        steps.append({"zone": z["bed"], "code": machine_gcode.render("heater_model", heater=z["heater"])})
    return {"kind": "tune", "temp": temp, "together": together, "tolerance": max(settings["tolerance"], TOL_DEFAULT), "zones": zones, "steps": steps,
            "off": off_lines(zones)}


# ---- readings of the object model ----

def reading(om, heater):
    """(current, state, cap) of a heater from the object model; (None, None, None) when it is not there."""
    hs = _heaters(om)[1]
    h = hs[heater] if 0 <= heater < len(hs) else None
    if not isinstance(h, dict):
        return None, None, None
    return _num(h.get("current")), h.get("state"), _num(h.get("max"))


def model_of(om, heater):
    """The heater model of the object model as plain numbers (what a tuning leaves), or None when the board shows none."""
    hs = _heaters(om)[1]
    h = hs[heater] if 0 <= heater < len(hs) else None
    md = h.get("model") if isinstance(h, dict) else None
    if not isinstance(md, dict) or md.get("enabled") is False:
        return None
    r, k, d = _num(md.get("heatingRate")), _num(md.get("coolingRate")), _num(md.get("deadTime"))
    if r is None or k is None or d is None:
        return None
    pid = md.get("pid") if isinstance(md.get("pid"), dict) else {}
    return {"heating_rate": r, "cooling_rate": k, "fan_cooling_rate": _num(md.get("fanCoolingRate")) or 0.0, "dead_time": d,
            "max_pwm": _num(md.get("maxPwm")) if _num(md.get("maxPwm")) is not None else 1.0, "voltage": _num(md.get("standardVoltage")) or 0.0,
            "pid_used": pid.get("used") is not False}


def tune_succeeded(reply):
    """True when the answer of `M303` (no parameters, the report of the last tuning) says it succeeded."""
    t = str(reply or "").lower()
    return "succeeded" in t and "failed" not in t


def model_line(heater, md):
    """The M307 line of a heater model (the numbers of model_of), for the page to show; nothing sends it (M307 with values is not in the closed list)."""
    if not md:
        return None
    s = "M307 H%d R%.3f K%.3f:%.3f D%.2f E1.35 S%.2f" % (heater, md["heating_rate"], md["cooling_rate"], md["fan_cooling_rate"], md["dead_time"], md["max_pwm"])
    if md["voltage"] > 0:
        s += " V%.1f" % md["voltage"]
    return s + " B%d" % (0 if md["pid_used"] else 1)
