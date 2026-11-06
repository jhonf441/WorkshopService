"""Edit the heater and the sensor of a bed that already exists (plan kind `config.bed_edit` of machine.config.plan / machine.config.apply, technician).

`config.bed_heaters` (machine_beds.py) only ADDS beds. This kind changes the NUMBERS of a bed that the configuration files already define:
the heater (`M950 H`, `M143 H`, `M307 H`, `M570 H` and the link `M140 P<bed> H<heater>`) and the sensor (`M308 S` and the `T` of the heater's `M950`).
values = {spec: {bed, heater?, sensor?}} (at least one of heater / sensor). The numbers are checked with the helpers of machine_beds.py (used_numbers,
board_limits, the same scan of the files): the new number must be the current one or one that nothing uses (the board or any line of any file) and inside
the limits of the board, so no other bed, tool or sensor is stepped on. A free number RENUMBERS the lines of the current one in every file of the
configuration (a mode file of another mode that deletes the heater with `M950 H<n> C"nil"` follows it, so it keeps deleting the same heater).
Lines that use an expression in that letter are never rewritten. It is the same plan as every other change (exact diff of each file, snapshot, sha check,
history, rollback) and the machine restarts to read it. Nothing here talks to the board. Pure parts: read_links, rewrite_text (test_machine_bed_edit.py).
"""
import config_scan
import machine_beds as mb
import machine_config as mc
import machine_patch as pt
import machine_tool as mt

NAMES = ("heater", "sensor")


def read_links(texts):
    """{beds: {bed: heater}, sensors: {heater: sensor or None}} from the live lines of the files (the last line of each key wins; `C"nil"` is no definition)."""
    beds, sensors = {}, {}
    for _, text in texts:
        _, ls = pt.split_lines(text)
        for _, code in pt.live_lines(ls):
            word, p = pt.command_word(code)[0], pt.tmap(code)
            bed, heater = mb._whole(p.get("P")), mb._whole(p.get("H"))
            if word == "M140" and bed is not None and heater is not None:
                beds[bed] = heater
            elif word == "M950" and heater is not None and mb.HEATER_DEFINITION.match(code):
                sensors[heater] = mb._whole(p.get("T"))
    return {"beds": beds, "sensors": sensors}


def current(texts, bed):
    """(heater, sensor) of a bed from the files; (None, None) when no line links it."""
    links = read_links(texts)
    heater = links["beds"].get(bed)
    return heater, links["sensors"].get(heater) if heater is not None else None


def _tokens(word, p, bed, old_h, new_h, old_s, new_s):
    """The tokens one line must change, or None."""
    h, out = mb._whole(p.get("H")), {}
    if new_h != old_h and h == old_h:
        if word in ("M950", "M143", "M307", "M570") or (word == "M140" and mb._whole(p.get("P")) == bed):
            out["H"] = str(new_h)
    if new_s != old_s:
        if word == "M308" and mb._whole(p.get("S")) == old_s:
            out["S"] = str(new_s)
        elif word == "M950" and h == old_h and "T" in p:
            out["T"] = str(new_s)
    return out or None


def rewrite_text(text, bed, old_h, new_h, old_s, new_s):
    """(new text, first changed line number or None). Raises machine_patch.PatchError for a letter that holds an expression."""
    eol, ls = pt.split_lines(text)
    first = None
    for n, code in pt.live_lines(ls):
        word, p = pt.command_word(code)[0], pt.tmap(code)
        new = _tokens(word, p, bed, old_h, new_h, old_s, new_s)
        if new:
            ls[n] = pt.set_tokens(ls[n], new)
            first = n + 1 if first is None else first
    return eol.join(ls), first


def _spec(values, state):
    """(bed, heater or None, sensor or None) checked against the limits of the board. Raises ToolError."""
    spec = values.get("spec", values)
    if not isinstance(spec, dict):
        raise mt.ToolError("values", "spec")
    bed = mt._number(spec.get("bed"), 0, min(mb.MAX_BED, state["max_beds"] - 1), "spec.bed", True)
    heater = None if spec.get("heater") is None else mt._number(spec["heater"], 0, state["max_heaters"] - 1, "spec.heater", True)
    sensor = None if spec.get("sensor") is None else mt._number(spec["sensor"], 0, state["max_sensors"] - 1, "spec.sensor", True)
    if heater is None and sensor is None:
        raise mt.ToolError("values", "spec")
    return bed, heater, sensor


def check(values, texts, state):
    """(bed, old heater, new heater, old sensor, new sensor) once the bed exists and the numbers are the bed's own or free. Raises ToolError."""
    bed, heater, sensor = _spec(values, state)
    old_h, old_s = current(texts, bed)
    if old_h is None:
        raise mt.ToolError("bed_missing", "spec.bed")
    new_h = old_h if heater is None else heater
    if new_h != old_h and new_h in state["heaters"]:
        raise mt.ToolError("heater_used", "spec.heater")
    new_s = old_s if sensor is None else sensor
    if sensor is not None:
        if old_s is None:
            raise mt.ToolError("no_sensor_link", "spec.sensor")
        shared = [h for h, s in read_links(texts)["sensors"].items() if s == old_s and h != old_h]
        if sensor != old_s and (sensor in state["sensors"] or shared):
            raise mt.ToolError("sensor_used", "spec.sensor")
    return bed, old_h, new_h, old_s, new_s


def plan_bed_edit(values, env):
    """The files with the heater and / or the sensor of an existing bed changed. The machine restarts to read them."""
    texts = mt._config_texts(env["read"])
    if not texts:
        raise mc.PlanError("no_config")
    state = mb._state(env["read"], env.get("om"))
    state["max_sensors"] = board_sensors(env.get("om"))
    try:
        bed, old_h, new_h, old_s, new_s = check(values, texts, state)
    except mt.ToolError as e:
        raise mc.PlanError("tool_name" if e.code == "name" else e.code, e.field)
    files, line = [], None
    for path, text in texts:
        before = mc.read_bytes(path)
        if before is None:
            raise mc.PlanError("no_config")
        try:
            out, first = rewrite_text(mc._decode(before), bed, old_h, new_h, old_s, new_s)
        except pt.PatchError as e:
            raise mc.PlanError("patch_" + e.code, e.field)
        if first is not None:
            files.append(mc._file_entry(path, before, out))
            line = first if line is None else line
    warnings = ["beds_restart"] if files else ["nothing_changes"]
    return {"files": files, "warnings": warnings, "action": "replaced" if files else "same", "line": line, "now": None,
            "set": list(config_scan.scan(env["read"])["files"]), "before": {"bed": bed, "heater": old_h, "sensor": old_s},
            "after": {"bed": bed, "heater": new_h, "sensor": new_s}, "restart_needed": True}


def board_sensors(om):
    """How many sensors the board supports (limits.sensors), the ceiling of machine_beds when it does not say."""
    n = ((om or {}).get("limits") or {}).get("sensors")
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else mb.MAX_SENSOR + 1


PLANNERS = {"config.bed_edit": plan_bed_edit}
