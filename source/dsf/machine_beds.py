"""Bed heaters of Machine (DWC 3.6): `machine.beds.get`, `machine.beds.preview` (read only) and the plan kind `config.bed_heaters`
(machine.config.plan / machine.config.apply, technician, like config.tool).

RRF cannot group heaters in one bed: every zone of a split bed is a bed of its own, one sensor (M308), one heater (M950 H) and the link `M140 P<bed> H<heater>`
(see "Bed zones" of Printing, docs/api/README.md). This is the ONE way the configuration gets those lines: the plan is reviewed, confirmed and applied like every
other configuration plan (snapshot, sha check, history, rollback) and the machine restarts to read it. Nothing here talks to the board; the pins are checked
by the code of the tool wizard (the board has them, they can do what the use needs and no line of the configuration already uses them) and are NEVER guessed:
the person chooses them. The numbers of the heater and the sensor are the first ones that nothing uses (neither the board nor a line of any file: a mode file
that is not loaded now still counts). The lines come from `build_lines`, the same code for the preview and the plan, so what is previewed is what is written.
Pure parts: build_lines, used_numbers (tests: test_machine_beds.py).
"""
import re

import config_scan
import machine_config as mc
import machine_patch as pt
import machine_plans as plans
import machine_tool as mt
from workshop_api import READ, Arg, Op

MAX_BEDS = 8
MAX_BED = 31
MAX_HEATER = 19
MAX_SENSOR = 99
PRESETS = ("thermistor", "pt1000")
# output kind -> (mark kept in the comment of the M950 line (the extruder configuration reads it), PWM frequency, capability the pin needs)
OUTPUTS = {"ssr": ("ssr-ca", 10, "pwm"), "ssrdc": ("ssr-dc", 10, "pwm"), "relay": ("relay", 1, "digital")}
# a heater that is really defined: the mode files of the other modes DELETE the heaters with `M950 H0 C"nil"`, and those lines are not a definition
HEATER_DEFINITION = re.compile(r'^[ \t]*M950[ \t]+H\d+[ \t]+C"(?!nil")', re.M)
ANCHORS = ("M308", "M950", "M143", "M140", "M563")
_WHOLE = re.compile(r"^\d+$")


def _whole(text):
    return int(text) if text is not None and _WHOLE.match(str(text)) else None


def used_numbers(om, texts):
    """{heaters, sensors, beds}: the numbers the board has loaded plus the ones any line of the configuration files defines (a comment never counts)."""
    om = om or {}
    heat = om.get("heat") or {}
    heaters = {i for i, h in enumerate(heat.get("heaters") or []) if h is not None}
    sensors = {i for i, s in enumerate((om.get("sensors") or {}).get("analog") or []) if s is not None}
    beds = {i for i, h in enumerate(heat.get("bedHeaters") or []) if isinstance(h, int) and h >= 0}
    in_files = set()
    for _, text in texts:
        _, ls = pt.split_lines(text)
        for _, code in pt.live_lines(ls):
            word, params = pt.command_word(code)[0], pt.tmap(code)
            if word == "M950" and _whole(params.get("H")) is not None:
                heaters.add(_whole(params["H"]))
            elif word == "M308" and _whole(params.get("S")) is not None:
                sensors.add(_whole(params["S"]))
            elif word == "M140" and _whole(params.get("P")) is not None and _whole(params.get("H")) is not None:
                beds.add(_whole(params["P"]))
                in_files.add(_whole(params["P"]))
    return {"heaters": heaters, "sensors": sensors, "beds": beds, "bed_lines": in_files}


def _state(read, om):
    texts = mt._config_texts(read)
    out = used_numbers(om, texts)
    out["used"] = mt.used_pins(texts)
    return out


def _free(used, taken, top):
    n = 0
    while n <= top and (n in used or n in taken):
        n += 1
    if n > top:
        raise mt.ToolError("values", "numbers")
    return n


def build_lines(spec, state):
    """The configuration lines of the beds -> {lines, summary}. state = {used: {pin: by}, heaters, sensors, beds: sets of numbers in use}. Raises ToolError."""
    if not isinstance(spec, dict):
        raise mt.ToolError("values", "spec")
    beds = spec.get("beds")
    if not isinstance(beds, list) or not 1 <= len(beds) <= MAX_BEDS or not all(isinstance(b, dict) for b in beds):
        raise mt.ToolError("values", "beds")
    used, taken = state["used"], set()
    heaters, sensors, seen = set(), set(), set()
    lines = ["; Bed zones (Machine): one sensor and one heater per zone; M140 P<bed> H<heater> makes each zone a bed of its own"]
    summary = []
    for i, item in enumerate(beds):
        field = "beds[%d]" % i
        bed = mt._number(item.get("bed"), 0, MAX_BED, field + ".bed", True)
        if bed in state["beds"] or bed in seen:
            raise mt.ToolError("bed_exists", field + ".bed")
        seen.add(bed)
        name = str(item.get("name") or "Bed zone %d" % (bed + 1))
        if not mt.NAME_RE.match(name):
            raise mt.ToolError("name", field + ".name")
        sensor, output = item.get("sensor"), item.get("output")
        if not isinstance(sensor, dict) or sensor.get("preset") not in PRESETS:
            raise mt.ToolError("values", field + ".sensor.preset")
        if not isinstance(output, dict) or output.get("kind") not in OUTPUTS:
            raise mt.ToolError("values", field + ".output.kind")
        mark, freq, need = OUTPUTS[output["kind"]]
        sensor_pin = mt._pin(sensor.get("pin"), mt.SENSOR_PRESETS[sensor["preset"]][1], used, taken, field + ".sensor.pin")
        output_pin = mt._pin(output.get("pin"), need, used, taken, field + ".output.pin")
        tmax = mt._number(item.get("max_temp"), 50, 280, field + ".max_temp")
        heater = _free(state["heaters"], heaters, MAX_HEATER)
        sensor_number = _free(state["sensors"], sensors, MAX_SENSOR)
        heaters.add(heater)
        sensors.add(sensor_number)
        lines.append('M308 S%d P"%s" %s A"%s"' % (sensor_number, sensor_pin, mt.SENSOR_PRESETS[sensor["preset"]][0], name[:24]))
        lines.append('M950 H%d C"%s" Q%d T%d   ; workshop:%s' % (heater, output_pin, freq, sensor_number, mark))
        lines.append("M143 H%d S%s" % (heater, pt.num_text(tmax)))
        lines.append("M140 P%d H%d" % (bed, heater))
        summary.append({"bed": bed, "heater": heater, "sensor": sensor_number})
    return {"lines": lines, "summary": {"beds": summary}}


# ---- the plan ----


def _defines_heaters(text):
    return HEATER_DEFINITION.search(text) is not None


def _insert_block(text, lines):
    """Adds the block after the last TOP-LEVEL line that defines a sensor, a heater, a limit, a bed or a tool (a line inside an `if` block is indented and is
    never the anchor: the block would end that block and could separate it from its `else`); without one, at the end of the file."""
    eol, ls = pt.split_lines(text)
    at = -1
    for n, code in pt.live_lines(ls):
        if code[:1] not in (" ", "\t") and pt.command_word(code)[0] in ANCHORS:
            at = n
    notices = []
    if at < 0:
        notices.append("no_anchor")
        at = len(ls) - 2 if ls and ls[-1] == "" else len(ls) - 1
    for k, line in enumerate(lines):
        ls.insert(at + 1 + k, line)
    return pt._result(ls, eol, "inserted", at + 2, notices)

def _target(read):
    """The file the block goes into: the LAST file of the configuration that already defines heaters, else config.g (what plans._edit picks)."""
    scan = config_scan.scan(read)
    hits = [p for p in scan["files"] if _defines_heaters(read(p) or "")]
    return hits[-1] if hits else config_scan.ROOT


def plan_bed_heaters(values, env):
    """Adds the lines of the beds to the configuration file that defines heaters (else config.g). The machine restarts to read them."""
    state = _state(env["read"], env.get("om"))
    try:
        built = build_lines(values.get("spec", values), state)
    except mt.ToolError as e:
        raise mc.PlanError("tool_name" if e.code == "name" else e.code, e.field)
    path, before, res, scan, hits = plans._edit(env, _defines_heaters, lambda t: _insert_block(t, built["lines"]))
    body = plans._body(path, before, res, scan, hits, None, None, built["summary"])
    body["warnings"].append("beds_restart")
    return body


# ---- the operations ----

def _get(args, ctx):
    import machine_ops as mo
    om = mo.model()
    state = _state(mo.read_sd, om)
    heat = (om or {}).get("heat") or {}
    defined = [{"bed": i, "heater": h} for i, h in enumerate(heat.get("bedHeaters") or []) if isinstance(h, int) and h >= 0]
    taken_beds = state["beds"]
    return {"defined": defined,
            "in_files": sorted(state["bed_lines"] - {d["bed"] for d in defined}),
            "next": {"heater": next((n for n in range(MAX_HEATER + 1) if n not in state["heaters"]), None),
                     "sensor": next((n for n in range(MAX_SENSOR + 1) if n not in state["sensors"]), None),
                     "beds": [n for n in range(MAX_BED + 1) if n not in taken_beds][:MAX_BEDS]},
            "max_beds": MAX_BEDS}


def _preview(args, ctx):
    import machine_ops as mo
    state = _state(mo.read_sd, mo.model())
    try:
        built = build_lines(args.get("spec"), state)
    except mt.ToolError as e:
        return {"lines": [], "files": [], "warnings": [], "errors": [{"code": e.code, "field": e.field}], "beds": []}
    return {"lines": built["lines"], "files": [mc.rel_of(_target(mo.read_sd))], "warnings": ["beds_restart"], "errors": [], "beds": built["summary"]["beds"]}


def ops():
    return [Op("machine.beds.get", _get, READ, {}, "The beds the machine has now ([{bed, heater}]), the beds that only a configuration file defines (a mode file that is not "
               "loaded now), the first heater and sensor numbers nothing uses and the first free bed numbers.", log=False),
            Op("machine.beds.preview", _preview, READ, {"spec": Arg("obj", desc="{beds: [{bed, name?, sensor: {preset: thermistor|pt1000, pin}, output: {kind: ssr|ssrdc|relay, pin}, max_temp}]}")},
               "The exact configuration lines the plan config.bed_heaters would write for these beds and the file they go into, or what is wrong with them. Writes nothing.", log=False)]


PLANNERS = {"config.bed_heaters": plan_bed_heaters}
