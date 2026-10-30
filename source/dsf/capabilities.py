"""Capabilities of the machine, discovered from the live board (F2, 2026-10-21).

The service runs on a Duet 3 + Raspberry Pi (DSF, SBC) and nothing else; what
changes between machines is everything around that: axes, tools, modes, probe,
camera, LED strip, meter, power relay. This module answers "what does this
machine have?" without assuming any file of the original workshop.

discover(model, env) is PURE: it takes the object model (a dict, or None when
the board is not reachable) plus what was read around it (env) and returns

    {"schema": 1, "live": bool,
     "board": {...},                         # board, firmware, SBC, DSF
     "capabilities": {name: {"present": bool, "source": "discovered"|"declared"|"default", ...}}}

source tells where the answer comes from: discovered = the board or the files on
the SD, declared = the settings or the machine profile say so, default = nothing
was found (present is False). Every capability has the same two keys so a
client can do `caps[name]["present"]` without checking.

env (all optional):
    mode_files   file names found as sys/mode*.g
    auto_mode    True if sys/automodeselect.g exists
    config_g     True if sys/config.g exists
    workshop_dir True if sys/workshop exists
    ledstrips    object model ledStrips (outside the common subscription) or None
    settings     service settings (service.json) as a dict
    cameras      list of configured cameras ([{id, name, url}])
    profile      declared machine profile (profile overrides are applied; its `interlocks` give lid_interlock...)
    config_scan  result of config_scan.scan() (M671 entries, G31 lines, bed.g); without it the levelling mode is "unknown"
    m115         text answer of M115 (only used when the model has no board)

get() (the I/O side) is in capabilities_io.py.
"""
import re

import boards_table

SCHEMA = 1
DISCOVERED, DECLARED, DEFAULT = "discovered", "declared", "default"
MODE_NAMES = {"fff": "FFF", "laser": "Laser", "cnc": "CNC"}
MODE_FILES_IGNORED = ("state",)   # sys/modestate.g is a helper of the workshop, not a mode


def cap(present, source, **detail):
    """One capability: present + source + free detail."""
    out = {"present": bool(present), "source": source}
    out.update(detail)
    return out


def _absent(**detail):
    return cap(False, DEFAULT, **detail)


def parse_m115(text):
    """M115 text -> {"FIRMWARE_NAME": ..., "FIRMWARE_VERSION": ..., ...} (keys in upper case)."""
    out = {}
    s = str(text or "")
    keys = list(re.finditer(r"\b([A-Z][A-Z0-9_]{2,}):\s*", s))
    for i, m in enumerate(keys):
        end = keys[i + 1].start() if i + 1 < len(keys) else len(s)
        out[m.group(1)] = s[m.end():end].strip()
    return out


# ---- board ----

def _board_info(model, env):
    boards = [b for b in (model or {}).get("boards") or [] if isinstance(b, dict)]
    main = boards[0] if boards else {}
    sbc = (model or {}).get("sbc")
    info = {
        "name": main.get("name"), "short_name": main.get("shortName"),
        "firmware_name": main.get("firmwareName"), "firmware_version": main.get("firmwareVersion"),
        "firmware_date": main.get("firmwareDate"),
        "sbc": bool(sbc), "dsf_version": ((sbc or {}).get("dsf") or {}).get("version") if isinstance(sbc, dict) else None,
        "source": DISCOVERED if main else DEFAULT,
    }
    if not main and env.get("m115"):
        m = parse_m115(env["m115"])
        info.update(firmware_name=m.get("FIRMWARE_NAME"), firmware_version=m.get("FIRMWARE_VERSION"),
                    firmware_date=m.get("FIRMWARE_DATE"), name=m.get("ELECTRONICS"), source=DISCOVERED)
    return info


def _boards(model):
    items = []
    for i, b in enumerate((model or {}).get("boards") or []):
        if not isinstance(b, dict):
            continue
        known = boards_table.lookup(b.get("shortName"))
        drivers = b.get("maxMotors")
        if drivers is None and known:
            drivers = known["drivers"]
        items.append({
            "index": i, "can": b.get("canAddress", 0 if i == 0 else None),
            "short_name": b.get("shortName"), "name": (known or {}).get("name") or b.get("name"),
            "kind": (known or {}).get("kind"), "known": bool(known),
            "firmware_version": b.get("firmwareVersion"), "state": b.get("state"),
            "drivers": drivers, "chip": (known or {}).get("chip"),
            "smart_drivers": (known or {}).get("smart"), "closed_loop": (known or {}).get("closed_loop"),
        })
    if not items:
        return _absent(items=[], total_drivers=0)
    total = sum(x["drivers"] or 0 for x in items)
    return cap(True, DISCOVERED, items=items, total_drivers=total)


# ---- motion ----

def _axes(model):
    items = []
    for i, a in enumerate(((model or {}).get("move") or {}).get("axes") or []):
        if not isinstance(a, dict) or not a.get("letter"):
            continue
        items.append({"index": i, "letter": a["letter"], "min": a.get("min"), "max": a.get("max"),
                      "visible": a.get("visible", True), "homed": a.get("homed"),
                      "drivers": list(a.get("drivers") or [])})
    if not items:
        return _absent(items=[], letters=[], index_of={})
    return cap(True, DISCOVERED, items=items, letters=[x["letter"] for x in items],
               index_of={x["letter"]: x["index"] for x in items})


def _tools(model):
    items = []
    for t in (model or {}).get("tools") or []:
        if not isinstance(t, dict) or t.get("number") is None:
            continue
        items.append({"number": t["number"], "name": t.get("name") or "", "heaters": list(t.get("heaters") or []),
                      "extruders": list(t.get("extruders") or []), "fans": list(t.get("fans") or []),
                      "spindle": t.get("spindle", -1)})
    return cap(bool(items), DISCOVERED, items=items) if items else _absent(items=[])


def _heaters(model):
    heat = (model or {}).get("heat") or {}
    heaters = [i for i, h in enumerate(heat.get("heaters") or []) if h]
    bed = [h for h in heat.get("bedHeaters") or [] if isinstance(h, int) and h >= 0]
    chamber = [h for h in heat.get("chamberHeaters") or [] if isinstance(h, int) and h >= 0]
    if not heaters:
        return _absent(indexes=[], bed=[], chamber=[])
    return cap(True, DISCOVERED, indexes=heaters, bed=bed, chamber=chamber)


def _fans(model):
    items = [{"index": i, "name": f.get("name") or ""} for i, f in enumerate((model or {}).get("fans") or [])
             if isinstance(f, dict)]
    return cap(True, DISCOVERED, items=items) if items else _absent(items=[])


def _probe(model):
    items = []
    for i, p in enumerate(((model or {}).get("sensors") or {}).get("probes") or []):
        if isinstance(p, dict) and p.get("type") not in (None, 0):
            items.append({"index": i, "type": p.get("type"), "trigger_height": p.get("triggerHeight"),
                          "offsets": list(p.get("offsets") or []), "speeds": list(p.get("speeds") or []),
                          "travel_speed": p.get("travelSpeed"), "dive_heights": list(p.get("diveHeights") or []),
                          "tolerance": p.get("tolerance"), "max_probe_count": p.get("maxProbeCount"),
                          "recovery_time": p.get("recoveryTime"), "threshold": p.get("threshold"),
                          "deployed_by_user": p.get("deployedByUser"), "value": list(p.get("value") or []),
                          "scanning": p.get("type") in SCANNING_PROBE_TYPES})
    return cap(True, DISCOVERED, items=items) if items else _absent(items=[])


def _extruder(model):
    ex = [e for e in ((model or {}).get("move") or {}).get("extruders") or [] if e]
    return cap(True, DISCOVERED, count=len(ex)) if ex else _absent(count=0)


def _spindle(model):
    items = [{"index": i, "min": s.get("min"), "max": s.get("max"), "state": s.get("state")}
             for i, s in enumerate((model or {}).get("spindles") or [])
             if isinstance(s, dict) and s.get("state") not in (None, "unconfigured")]
    return cap(True, DISCOVERED, items=items) if items else _absent(items=[])


def _power_control(model):
    state = (model or {}).get("state") or {}
    if state.get("atxPowerPort") or state.get("atxPower") is not None:
        return cap(True, DISCOVERED, port=state.get("atxPowerPort"), on=state.get("atxPower"))
    return _absent(port=None, on=None)


# ---- modes ----

def mode_from_file(name):
    """modelaser.g -> Laser, modefff.g -> FFF, modeplotter.g -> plotter."""
    m = re.match(r"^mode(.+)\.g$", str(name), re.I)
    if not m:
        return None
    key = m.group(1)
    if key.lower() in MODE_FILES_IGNORED:
        return None
    return MODE_NAMES.get(key.lower(), key)


def _modes(model, env):
    from_files = []
    for f in env.get("mode_files") or []:
        n = mode_from_file(f)
        if n and n not in from_files:
            from_files.append(n)
    current = ((model or {}).get("state") or {}).get("machineMode") or None
    selected = ((model or {}).get("global") or {}).get("selectedMode") or None
    available = list(from_files)
    if current and current not in available:
        available.append(current)
    if not available:
        return _absent(available=[], current=None, selectable=False, files=[])
    return cap(True, DISCOVERED, available=available, current=selected or current, machine_mode=current,
               selectable=bool(env.get("auto_mode") or len(from_files) > 1), files=sorted(env.get("mode_files") or []))


def _laser(model, modes):
    state = (model or {}).get("state") or {}
    signals = []
    # laserPwm exists with a value in any mode on some firmware builds: it only counts in Laser mode
    if state.get("machineMode") == "Laser":
        signals.append("state.machineMode")
        if state.get("laserPwm") is not None:
            signals.append("state.laserPwm")
    if "Laser" in (modes.get("available") or []):
        signals.append("mode file")
    return cap(True, DISCOVERED, signals=signals) if signals else _absent(signals=[])


# ---- accessories: strip, cameras, meter, scenes ----

def _strip_kind(t):
    t = str(t or "")
    return "dotstar" if t.lower().startswith("dotstar") else "neopixel" if t else None


def _led_strip(model, env):
    strips = [s for s in (env.get("ledstrips") if env.get("ledstrips") is not None else (model or {}).get("ledStrips")) or []
              if isinstance(s, dict)]
    if strips:
        return cap(True, DISCOVERED, items=[{"index": i, "type": s.get("type"), "kind": _strip_kind(s.get("type")),
                                             "pin": s.get("pin")} for i, s in enumerate(strips)])
    glb = (model or {}).get("global") or {}
    if glb.get("ledHasStrip") or glb.get("ledHayTira"):  # ledHayTira: the name before the English rename
        return cap(True, DISCOVERED, items=[], signal="global.ledHasStrip")
    sl = (env.get("settings") or {}).get("status_light") or {}
    if isinstance(sl.get("strip"), dict) and sl["strip"].get("present"):
        return cap(True, DECLARED, items=[], signal="settings")
    return _absent(items=[])


def _cameras(env):
    cams = [c for c in env.get("cameras") or [] if isinstance(c, dict)]
    relay = (env.get("settings") or {}).get("camara_relay") or (env.get("settings") or {}).get("camera_relay") or {}
    if relay.get("url") and not any(c.get("id") == "main" for c in cams):
        cams = [{"id": "main", "name": "main", "url": relay["url"]}] + cams
    if not cams:
        return _absent(items=[])
    return cap(True, DECLARED, items=[{"id": c.get("id"), "name": c.get("name") or c.get("id")} for c in cams])


def _meter(env):
    s = env.get("settings") or {}
    lst = s.get("meters") if isinstance(s.get("meters"), list) else []
    ready = [m for m in lst if isinstance(m, dict) and m.get("id") and m.get("ip")]
    if not ready:
        return _absent(kind=None, items=[])
    return cap(True, DECLARED, kind="tuya", items=[{"slot": m.get("slot") or "general", "name": m.get("name") or ""} for m in ready])


def _light_scenes(strip, env):
    sl = (env.get("settings") or {}).get("status_light") or {}
    scenes = sl.get("scenes")
    if not strip["present"]:
        return _absent(ids=[])
    if isinstance(scenes, list) and scenes:
        return cap(True, DECLARED, ids=[str(x.get("id")) for x in scenes if isinstance(x, dict)])
    return cap(True, DEFAULT, ids=["job", "photo", "inspeccion", "dim"])


def _workshop(model, env):
    """Workshop-specific pieces (only reported when they are really there)."""
    signals = []
    if env.get("workshop_dir"):
        signals.append("sys/workshop")
    if "selectedMode" in ((model or {}).get("global") or {}):
        signals.append("global.selectedMode")
    if env.get("auto_mode"):
        signals.append("sys/automodeselect.g")
    return cap(True, DISCOVERED, signals=signals) if signals else _absent(signals=[])


# ---- optional laser interlocks (declared in the profile, read from a Duet input) ----

def _interlocks(model, env):
    """{lid_interlock, extraction_interlock, key_interlock}: present when declared AND the input exists in the object model."""
    import interlocks
    decl = interlocks.declared(env.get("profile"))
    out = {}
    for name in interlocks.NAMES:
        item = decl.get(name)
        if item is None:
            out[interlocks.CAPABILITY[name]] = _absent(gpin=None)
        elif interlocks.exists(model, item["gpin"]):
            out[interlocks.CAPABILITY[name]] = cap(True, DECLARED, gpin=item["gpin"], active_when=item["active_when"], label=item["label"])
        else:
            out[interlocks.CAPABILITY[name]] = _absent(gpin=item["gpin"], reason="input_missing")
    return out


# ---- Machine v2: geometry, calibration state and what the board reports about it (phase 0) ----

# kinematics that Machine supports (it assumes straight axes); the name comes from move.kinematics.name of the object model
SUPPORTED_KINEMATICS = ("cartesian", "corexy", "corexyu", "corexyuv", "corexz")
# probe types that scan (a continuous reading instead of a trigger): the type number is NOT verified against a real capture
SCANNING_PROBE_TYPES = (11,)
_DRIVER = re.compile(r"^(\d+)\.(\d+)$")


def parse_driver(raw):
    """"1.2" (RRF 3.4+) or 2 (older) -> {"raw", "board", "port"}; anything else keeps only raw."""
    m = _DRIVER.match(raw) if isinstance(raw, str) else None
    if m:
        return {"raw": raw, "board": int(m.group(1)), "port": int(m.group(2))}
    if isinstance(raw, int) and not isinstance(raw, bool):
        return {"raw": raw, "board": 0, "port": raw}
    return {"raw": raw, "board": None, "port": None}


def _kinematics(model):
    """Name, support and tilt correction. A non cartesian geometry is reported as unsupported (Machine hides its modules)."""
    k = ((model or {}).get("move") or {}).get("kinematics")
    name = k.get("name") if isinstance(k, dict) else None
    if not name:
        return _absent(name=None, supported=False, unsupported=False, reason=None, tilt_correction=None)
    ok = str(name).lower() in SUPPORTED_KINEMATICS
    return cap(True, DISCOVERED, name=name, supported=ok, unsupported=not ok,
               reason=None if ok else "non_cartesian_kinematics",
               tilt_correction=k.get("tiltCorrection") if isinstance(k.get("tiltCorrection"), dict) else None)


def _axis_drivers(model):
    """Per axis: its drivers (board and port), steps per mm, current, microstepping, speed, acceleration, jerk."""
    items = []
    for i, a in enumerate(((model or {}).get("move") or {}).get("axes") or []):
        if not isinstance(a, dict) or not a.get("letter"):
            continue
        ms = a.get("microstepping") if isinstance(a.get("microstepping"), dict) else {}
        items.append({"index": i, "letter": a["letter"], "drivers": [parse_driver(d) for d in a.get("drivers") or []],
                      "steps_per_mm": a.get("stepsPerMm"), "current": a.get("current"), "microstepping": ms.get("value"),
                      "interpolated": ms.get("interpolated"), "speed": a.get("speed"), "acceleration": a.get("acceleration"),
                      "jerk": a.get("jerk")})
    if not items:
        return _absent(items=[], multi_motor=[])
    return cap(True, DISCOVERED, items=items, multi_motor=[x["letter"] for x in items if len(x["drivers"]) > 1])


def _z_motors(drivers, env):
    """How many motors move Z and which drivers: letter lookup (or the index of the profile), never axes[2]."""
    declared = (((env.get("profile") or {}).get("axis_index")) or {}).get("Z")
    items = drivers.get("items") or []
    z = next((x for x in items if x["index"] == declared), None) if declared is not None else None
    z = z or next((x for x in items if x["letter"] == "Z"), None)
    if not z:
        return _absent(count=0, drivers=[], axis_index=None, independent=False)
    return cap(True, DISCOVERED, count=len(z["drivers"]), drivers=z["drivers"], axis_index=z["index"],
               independent=len(z["drivers"]) > 1)


def _endstops(model, axes):
    letters = {x["index"]: x["letter"] for x in axes.get("items") or []}
    items = [{"index": i, "axis": letters.get(i), "type": e.get("type"), "high_end": e.get("highEnd"),
              "triggered": e.get("triggered"), "probe": e.get("probe")}
             for i, e in enumerate(((model or {}).get("sensors") or {}).get("endstops") or []) if isinstance(e, dict)]
    return cap(True, DISCOVERED, items=items, count=len(items)) if items else _absent(items=[], count=0)


def _accelerometers(model):
    items = [{"index": i, "orientation": a.get("orientation"), "points": a.get("points"), "runs": a.get("runs"),
              "sampling_rate": a.get("samplingRate"), "resolution": a.get("resolution")}
             for i, a in enumerate(((model or {}).get("sensors") or {}).get("accelerometers") or []) if isinstance(a, dict)]
    return cap(True, DISCOVERED, items=items, count=len(items)) if items else _absent(items=[], count=0)


def _shaping(model):
    """Input shaping: present when the firmware reports move.shaping (3.4+); `configured` says if a shaper is active."""
    s = ((model or {}).get("move") or {}).get("shaping")
    if not isinstance(s, dict):
        return _absent(configured=False, type=None, frequency=None, damping=None, min_acceleration=None)
    kind = s.get("type")
    return cap(True, DISCOVERED, configured=bool(kind) and str(kind).lower() != "none", type=kind, frequency=s.get("frequency"),
               damping=s.get("damping"), min_acceleration=s.get("minAcceleration"))


def _compensation(model):
    """Active height-map compensation (move.compensation). Absent when none is loaded."""
    c = ((model or {}).get("move") or {}).get("compensation")
    kind = c.get("type") if isinstance(c, dict) else None
    if not kind or str(kind).lower() == "none":
        return _absent(type="none", file=None, probe_grid=None, fade_height=None, mesh_deviation=None)
    return cap(True, DISCOVERED, type=kind, file=c.get("file"), probe_grid=c.get("probeGrid"), fade_height=c.get("fadeHeight"),
               mesh_deviation=c.get("meshDeviation") if isinstance(c.get("meshDeviation"), dict) else None)


def _workplaces(model, axes):
    """Work coordinate systems (G54..): the current one and the offsets of each axis."""
    mv = (model or {}).get("move") or {}
    letters = {x["index"]: x["letter"] for x in axes.get("items") or []}
    offsets = {letters[i]: list(a.get("workplaceOffsets"))
               for i, a in enumerate(mv.get("axes") or []) if i in letters and isinstance(a, dict) and isinstance(a.get("workplaceOffsets"), list)}
    if not offsets:
        return _absent(current=None, count=0, offsets={})
    current = mv.get("workplaceNumber")           # obsolete in the model; the current key is move.motionSystems[].workplaceNumber (0-based)
    if not isinstance(current, int) or isinstance(current, bool):
        ms = (mv.get("motionSystems") or [None])[0]
        current = ms.get("workplaceNumber") if isinstance(ms, dict) and isinstance(ms.get("workplaceNumber"), int) else None
    return cap(True, DISCOVERED, current=current, count=max(len(v) for v in offsets.values()), offsets=offsets)


def _probed_axes(mask):
    """`offsetsProbed` is a BITMAP in the object model (bit i = axis i was probed; GCODE-REFERENCE section 4); an older fixture had a list."""
    if isinstance(mask, list):
        return list(mask)
    if isinstance(mask, int) and not isinstance(mask, bool):
        return [i for i in range(32) if mask >> i & 1]
    return []


def _tool_offsets(model):
    items = [{"number": t["number"], "offsets": list(t.get("offsets") or []), "probed": _probed_axes(t.get("offsetsProbed"))}
             for t in (model or {}).get("tools") or [] if isinstance(t, dict) and t.get("number") is not None]
    return cap(True, DISCOVERED, items=items) if items else _absent(items=[])


def _levelling(kin, z, probe, scanned):
    """What the bed levelling module can do (section 2.3 of the design): leadscrews (M671 matches the Z motors), missingM671,
    singleZ, noZ, unsupported (kinematics) or unknown (the configuration was not scanned). `m671_entries` is None when unknown."""
    import config_scan
    entries = config_scan.m671_entries(scanned) if scanned and scanned.get("read") else None
    if kin["present"] and kin.get("unsupported"):
        mode = "unsupported"
    elif not z["present"]:
        mode = "noZ"
    elif z["count"] < 2:
        mode = "singleZ"
    elif entries is None:
        mode = "unknown"
    elif entries == z["count"]:
        mode = "leadscrews"
    else:
        mode = "missingM671"
    ok = mode in ("leadscrews", "missingM671")
    return cap(ok, DISCOVERED if ok else DEFAULT, mode=mode, m671_entries=entries, z_motors=z.get("count", 0),
               probe_present=probe["present"], bed_g=bool((scanned or {}).get("bed_g")), reason=None if ok else mode)


def _machine_v2(model, env, probe):
    """The capabilities Machine v2 adds (design section 6.1). All have present/source like the rest."""
    kin = _kinematics(model)
    drivers = _axis_drivers(model)
    axes = _axes(model)
    z = _z_motors(drivers, env)
    return {
        "kinematics": kin, "axis_drivers": drivers, "z_motors": z, "endstops": _endstops(model, axes),
        "accelerometers": _accelerometers(model), "input_shaping": _shaping(model), "compensation": _compensation(model),
        "workplaces": _workplaces(model, axes), "tool_offsets": _tool_offsets(model),
        "levelling": _levelling(kin, z, probe, env.get("config_scan")),
    }

# ---- overrides and entry point ----

def apply_overrides(caps, overrides):
    """Profile overrides {capability: bool}: False = do not use it, True = declared present."""
    for name, wanted in (overrides or {}).items():
        c = caps.get(name)
        if c is None or not isinstance(wanted, bool):
            continue
        if wanted is False and c["present"]:
            c.update(present=False, disabled_by_profile=True, discovered_present=True, source=DECLARED)
        elif wanted is True and not c["present"]:
            c.update(present=True, source=DECLARED)
    return caps


def discover(model, env=None):
    """Capabilities from the object model + env. See the module docstring."""
    env = env or {}
    model = model if isinstance(model, dict) else None
    modes = _modes(model, env)
    strip = _led_strip(model, env)
    caps = {
        "boards": _boards(model), "axes": _axes(model), "tools": _tools(model), "heaters": _heaters(model),
        "fans": _fans(model), "probe": _probe(model), "extruder": _extruder(model), "spindle": _spindle(model),
        "modes": modes, "laser": _laser(model, modes), "power_control": _power_control(model),
        "led_strip": strip, "light_scenes": _light_scenes(strip, env), "camera": _cameras(env),
        "meter": _meter(env), "workshop": _workshop(model, env),
    }
    caps.update(_interlocks(model, env))
    caps.update(_machine_v2(model, env, caps["probe"]))
    apply_overrides(caps, (env.get("profile") or {}).get("capability_overrides"))
    return {"schema": SCHEMA, "live": model is not None, "board": _board_info(model, env), "capabilities": caps}


def has(result, name):
    """True if the capability is present in a discover() result."""
    return bool(((result or {}).get("capabilities") or {}).get(name, {}).get("present"))
