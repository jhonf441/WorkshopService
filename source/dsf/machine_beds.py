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
import machine_file
import machine_patch as pt
import machine_sensors as ms
import machine_tool as mt
from workshop_api import READ, Arg, Op

# Ceilings used ONLY when the board does not report its own limits (object model `limits`, RRF 3.4+): bed numbers fit in 5 bits, 20 heaters.
# What the board really supports is limits.bedHeaters / limits.heaters (see board_limits): there is no fixed number of beds.
MAX_BED = 31
MAX_BEDS = MAX_BED + 1
MAX_HEATER = 19
MAX_SENSOR = 99
PRESETS = tuple(ms.PRESETS)  # the sensor types of a zone: machine_sensors.py (M308 of RepRapFirmware 3.x)
# output kind -> (mark kept in the comment of the M950 line (the extruder configuration reads it), PWM frequency, capability the pin needs).
# "dc" = the heater hangs straight from a MOSFET of the board (no relay): the M950 line carries no mark and no Q (the firmware default, what the
# 3D printing page reads as "DC board"); it is only accepted on a pin that really is a bed or heater MOSFET (DIRECT_PINS), never on a fan output,
# a low-current output, a logic io pin or an expansion board: a heater wired to the wrong output is a fire risk, so any doubt is a refusal.
OUTPUTS = {"dc": (None, None, "pwm"), "ssr": ("ssr-ca", 10, "pwm"), "ssrdc": ("ssr-dc", 10, "pwm"), "relay": ("relay", 1, "digital")}
# the Duet 3 MB6HC main board: out0 = the bed heater MOSFET (18 A), out1..out3 = the heater MOSFETs (6 A); the same table as the client
# (WorkshopMachine lib/bed-output.js). out4..out9 drive fans and small loads, ioN.out is logic level, N.outM is another board: none is direct.
DIRECT_PINS = ("out0", "out1", "out2", "out3")
DIRECT = "dc"
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


def board_limits(om):
    """{beds, heaters}: how many beds and heaters THIS board supports (limits.bedHeaters, limits.heaters of the object model); the ceilings above when it does not say."""
    limits = (om or {}).get("limits") or {}

    def pick(key, fallback):
        n = limits.get(key)
        return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else fallback
    return {"beds": pick("bedHeaters", MAX_BEDS), "heaters": pick("heaters", MAX_HEATER + 1)}


def _state(read, om):
    texts = mt._config_texts(read)
    out = used_numbers(om, texts)
    lim = board_limits(om)
    out["max_beds"], out["max_heaters"] = lim["beds"], lim["heaters"]
    out["used"] = mt.used_pins(texts)
    return out


def is_direct_pin(raw):
    """True only for a bed or heater MOSFET of the main board written plainly (no inversion, no pull-up, no board prefix): the pin a heater may hang
    from without a relay. Anything else (a fan output, a logic pin, an expansion board, an inverted pin) is not direct."""
    text = str(raw or "").strip()
    return text in DIRECT_PINS


def heater_line(heater, pin, sensor, mark, freq):
    """The M950 line of a bed heater: with a relay it carries the PWM frequency and the mark of the relay kind; direct to a MOSFET it carries neither."""
    if mark is None:
        return 'M950 H%d C"%s" T%d' % (heater, pin, sensor)
    return 'M950 H%d C"%s" Q%d T%d   ; workshop:%s' % (heater, pin, freq, sensor, mark)


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
    max_beds = state.get("max_beds", MAX_BEDS)
    max_heaters = state.get("max_heaters", MAX_HEATER + 1)
    if not isinstance(beds, list) or not 1 <= len(beds) <= max_beds or not all(isinstance(b, dict) for b in beds):
        raise mt.ToolError("values", "beds")
    used, taken = state["used"], set()
    heaters, sensors, seen = set(), set(), set()
    lines = ["; Bed zones (Machine): one sensor and one heater per zone; M140 P<bed> H<heater> makes each zone a bed of its own"]
    summary = []
    for i, item in enumerate(beds):
        field = "beds[%d]" % i
        bed = mt._number(item.get("bed"), 0, min(MAX_BED, max_beds - 1), field + ".bed", True)
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
        sensor_pin = mt._pin(sensor.get("pin"), ms.need(sensor["preset"]), used, taken, field + ".sensor.pin")
        try:
            sensor_text = ms.sensor_text(sensor["preset"], sensor, sensor_pin)
        except ms.SensorError as e:
            raise mt.ToolError(e.code, "%s.sensor.%s" % (field, e.field))
        if output["kind"] == DIRECT and not is_direct_pin(output.get("pin")):
            raise mt.ToolError("pin_not_mosfet", field + ".output.pin")
        output_pin = mt._pin(output.get("pin"), need, used, taken, field + ".output.pin")
        tmax = mt._number(item.get("max_temp"), 50, 280, field + ".max_temp")
        heater = _free(state["heaters"], heaters, max_heaters - 1)
        sensor_number = _free(state["sensors"], sensors, MAX_SENSOR)
        heaters.add(heater)
        sensors.add(sensor_number)
        lines.append('M308 S%d P"%s" %s A"%s"' % (sensor_number, sensor_pin, sensor_text, name[:24]))
        lines.append(heater_line(heater, output_pin, sensor_number, mark, freq))
        lines.append("M143 H%d S%s" % (heater, pt.num_text(tmax)))
        lines.append("M140 P%d H%d" % (bed, heater))
        summary.append({"bed": bed, "heater": heater, "sensor": sensor_number})
    return {"lines": lines, "summary": {"beds": summary}}


# ---- the plan ----


def plan_bed_heaters(values, env):
    """Adds the lines of the beds to the configuration file that defines heaters (else config.g). The machine restarts to read them."""
    state = _state(env["read"], env.get("om"))
    try:
        built = build_lines(values.get("spec", values), state)
    except mt.ToolError as e:
        raise mt.plan_error(e, env["read"])
    spec = values.get("spec", values)
    first = min(b["bed"] for b in built["summary"]["beds"])
    return machine_file.plan_body(mc, config_scan.scan(env["read"]), "bed", first, built, spec.get("modes") if isinstance(spec, dict) else None, "beds_restart")


# ---- the operations ----

def _get(args, ctx):
    import machine_ops as mo
    om = mo.model()
    state = _state(mo.read_sd, om)
    heat = (om or {}).get("heat") or {}
    import machine_bed_edit
    texts = mt._config_texts(mo.read_sd)
    defined = []
    for i, h in enumerate(heat.get("bedHeaters") or []):
        if isinstance(h, int) and h >= 0:
            file_heater, sensor = machine_bed_edit.current(texts, i)
            # sensor: the T of the heater's M950 line; editable: a line of the files links this bed (config.bed_edit can rewrite it)
            defined.append({"bed": i, "heater": h, "sensor": sensor, "editable": file_heater is not None})
    taken_beds = state["beds"]
    return {"defined": defined,
            "in_files": sorted(state["bed_lines"] - {d["bed"] for d in defined}),
            "next": {"heater": next((n for n in range(state["max_heaters"]) if n not in state["heaters"]), None),
                     "sensor": next((n for n in range(MAX_SENSOR + 1) if n not in state["sensors"]), None),
                     "beds": [n for n in range(min(MAX_BED + 1, state["max_beds"])) if n not in taken_beds]},
            "max_beds": state["max_beds"]}


def _modes(args):
    """The modes of the spec as machine.g will keep them (None = every mode); a bad value is answered as an error by the preview."""
    spec = args.get("spec")
    return list(machine_file.clean_modes(spec.get("modes"))) if isinstance(spec, dict) and spec.get("modes") not in (None, "all", []) else None


def _preview(args, ctx):
    import machine_ops as mo
    state = _state(mo.read_sd, mo.model())
    bad = machine_file.modes_problem(args.get("spec"))
    if bad:
        return {"lines": [], "files": [], "warnings": [], "errors": [bad], "beds": []}
    try:
        built = build_lines(args.get("spec"), state)
    except mt.ToolError as e:
        return {"lines": [], "files": [], "warnings": [], "errors": [mt.error_of(e, mo.read_sd)], "beds": []}
    return {"lines": built["lines"], "files": machine_file.preview_files(mc), "warnings": ["beds_restart"], "errors": [], "beds": built["summary"]["beds"], "modes": _modes(args)}


def ops():
    return [Op("machine.beds.get", _get, READ, {}, "The beds the machine has now ([{bed, heater, sensor, editable}]), the beds that only a configuration file defines (a mode file that is not "
               "loaded now), the first heater and sensor numbers nothing uses and the first free bed numbers.", log=False),
            Op("machine.beds.preview", _preview, READ, {"spec": Arg("obj", desc="{beds: [{bed, name?, sensor: {preset: thermistor|pt1000|thermocouple|tc-max31856|pt100|linear-analog, pin, + the fields of the type (see docs/api)}, output: {kind: dc|ssr|ssrdc|relay, pin}, max_temp}]}")},
               "The exact configuration lines the plan config.bed_heaters would write for these beds and the file they go into, or what is wrong with them "
               "(dc = straight to a bed or heater MOSFET of the board, out0..out3 only: error pin_not_mosfet on any other pin). Writes nothing.", log=False)]


PLANNERS = {"config.bed_heaters": plan_bed_heaters}
