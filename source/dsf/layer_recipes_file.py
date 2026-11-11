"""Temperature-by-layer RECIPES, the preview side that knows what the G-code FILE itself asks for. PURE (no I/O): it takes the commands found by gcode_temps.scan
and the tracks of a recipe, and answers

    snapshots(commands, tracks, layer_line, zones, truncated, stagger=None)  -> [{"extruder": [..] | None, "bed": [..] | None}] one per layer: what the file holds when the
                                                                  layer starts (the commands BEFORE its start line); a list has one entry per heater / zone of the
                                                                  track, None inside it = not known; None = nothing known at all
    conflicts(commands, tracks, zones, start, end)             -> [{"line", "text", "track", "same_layer": True}] commands in [start, end) that set heaters the
                                                                  recipe controls
    controlled(commands, tracks, zones, from_line)             -> how many commands from that line on touch the heaters of the recipe

`zones` is the usable bed-zones configuration (None when the bed zones are off or unreadable: then an M140 / M190 without P only reaches bed 0, as the
firmware does). A bed command WITHOUT P is split across the active zones by the interception (bed_zones.translate): the zone gets S + its offset, capped at
the bed-zones maximum (the real interception refuses it above the maximum; the preview shows the cap). With P it is that zone only, as written.
A temperature at or under -273 or 0 means off and is shown as 0.
"""
import bed_zones
import pellet_layers

MIN = pellet_layers.MIN_TEMP


def _norm(value):
    return 0.0 if value is None or value <= bed_zones.OFF_BELOW or value == 0 else float(value)


def _zone_value(setpoint, zone, config):
    target, error = bed_zones.zone_target(setpoint, zone, config)
    if error:
        return float(config["max_temp"]) if error[0] == "bed_zones_over_max" else None
    return 0.0 if target == bed_zones.OFF else target


def affected_zones(cmd, zone_numbers, zones):
    """The zones of the track (bed numbers) this bed command reaches."""
    if cmd["bed"] is not None:
        return [cmd["bed"]] if cmd["bed"] in zone_numbers else []
    if zones is None:
        return [z for z in zone_numbers if z == 0]
    if cmd["temps"] is None:
        return list(zone_numbers)  # an unreadable setpoint or an order by heater (H): every zone may be affected
    active = {z["bed"] for z in bed_zones.active_zones(zones)}
    return [z for z in zone_numbers if z in active]


def touches(cmd, name, track, zones):
    if name == "extruder":
        return cmd["kind"] == "extruder" and cmd["tool"] == track["tool"]
    return cmd["kind"] == "bed" and bool(affected_zones(cmd, track["zones"], zones))


def _apply(state, cmd, name, track, zones, stagger=None):
    if name == "extruder":
        heaters = len(track["heaters"])
        temps = cmd["temps"]
        if temps is None:
            state[:] = [None] * heaters
        elif len(temps) == 1:
            value = _norm(temps[0])
            # a single value is the nozzle temperature: with a stagger the other zones take their own step below it (never when it switches off)
            state[:] = [value + (s if stagger and value else 0.0) for s in (stagger or [0.0] * heaters)]
        else:
            for i in range(heaters):
                if i < len(temps):
                    state[i] = _norm(temps[i])
        return
    numbers = track["zones"]
    for bed in affected_zones(cmd, numbers, zones):
        i = numbers.index(bed)
        if cmd["temps"] is None:
            state[i] = None
        elif cmd["bed"] is not None or zones is None:
            state[i] = _norm(cmd["temps"][0])
        else:
            zone = next((z for z in zones["zones"] if z.get("bed") == bed), None)
            state[i] = _zone_value(cmd["temps"][0], zone, zones) if zone else None


def _view(state):
    return list(state) if any(v is not None for v in state) else None


def snapshots(commands, tracks, layer_line, zones, truncated=False, stagger=None):
    state = {}
    for name, track in tracks.items():
        state[name] = [None] * len(track["heaters"] if name == "extruder" else track["zones"])
    last_known = commands[-1]["line"] if commands else 0
    out, pos = [], 0
    for start in layer_line:
        if start is None or (truncated and start > last_known):
            out.append({n: None for n in ("extruder", "bed")})
            continue
        while pos < len(commands) and commands[pos]["line"] < start:
            for name, track in tracks.items():
                if touches(commands[pos], name, track, zones):
                    _apply(state[name], commands[pos], name, track, zones, stagger if name == "extruder" else None)
            pos += 1
        out.append({n: (_view(state[n]) if n in state else None) for n in ("extruder", "bed")})
    return out


def base_vectors(commands, tracks, layer_line, zones, truncated=False, stagger=None):
    """The BASE a relative recipe adds its deltas to, one {"extruder": [..] | None, "bed": [..] | None} per layer: the snapshot of the file at the layer's
    start, where an extruder single value (M104 / M109 / G10 / M568 with one number) is the nozzle temperature and the other heaters of the tool sit
    `stagger` (per heater, see layer_recipes_plan.stagger_for) below it, and a list (M568 S200:210:215) is taken as it is. A value under MIN
    (a heater the file switches off) is not a base: it is None, as is anything the file does not fix."""
    out = []
    for snap in snapshots(commands, tracks, layer_line, zones, truncated, stagger):
        out.append({n: ([v if v is not None and v >= MIN else None for v in snap[n]] if snap.get(n) else None) for n in ("extruder", "bed")})
    return out


def conflicts(commands, tracks, zones, start, end):
    found = []
    for cmd in commands:
        if cmd["line"] < start:
            continue
        if end is not None and cmd["line"] >= end:
            break
        for name, track in tracks.items():
            if touches(cmd, name, track, zones):
                found.append({"line": cmd["line"], "text": cmd["text"], "track": name, "same_layer": True})
    return found


def controlled(commands, tracks, zones, from_line):
    return sum(1 for cmd in commands if cmd["line"] >= from_line and any(touches(cmd, n, t, zones) for n, t in tracks.items()))
