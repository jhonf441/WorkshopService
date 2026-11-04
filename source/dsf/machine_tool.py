"""Tool creation wizard of Machine (DWC 3.6): `machine.tool.get`, `machine.tool.pins`, `machine.tool.preview` (read only) and the plan kind `config.tool`
(machine.config.plan / machine.config.apply, technician).

The wizard writes the lines that define a new tool in the configuration: M308 (sensors), M950 (heaters, fans, spindle), M143 (maximum temperature),
M563 (the tool) and G10 (offsets). It never sends anything to the board: the plan is reviewed, confirmed and applied like the rest of the configuration
plans, and the machine restarts to read it. A pin is accepted only if the board has it, it has the capability the use needs and no line of the
configuration already uses it. The lines come from `build_lines`, the same code for the preview and the plan, so what is previewed is what is written.
Pure parts: build_lines, used_pins, free_pins (tests: test_machine_tool.py).
"""
import re

import config_scan
import machine_config as mc
import machine_patch as pt
import machine_plans as plans
from workshop_api import READ, Arg, Op

TYPES = ("spindle", "laser", "pellet_extruder", "fff_extruder", "contact_probe", "generic")
MAX_TOOLS = 50
MAX_ITEMS = 4
NAME_RE = re.compile(r'^[^";\r\n{}]{1,32}$')
PIN_TOKEN_RE = re.compile(r"(?<![\w.])!?\^?((?:\d{1,2}\.)?(?:out\d+|io\d+\.(?:out|in)|temp\d+|spi\.cs\d+|\d{1,2}\.[a-z0-9.]+))(?![\w])")

# the Duet 3 6HC main board: outputs (PWM, 24 V), the io pins and the temperature / SPI inputs
BOARD_PINS = ([("out%d" % n, ("pwm", "digital")) for n in range(10)]
              + [("io%d.out" % n, ("pwm", "digital", "servo")) for n in range(9)]
              + [("io%d.in" % n, ("digital", "adc")) for n in range(9)]
              + [("temp%d" % n, ("adc",)) for n in range(4)]
              + [("spi.cs%d" % n, ("spi", "digital")) for n in range(3)])
CAPS = dict(BOARD_PINS)
SENSOR_PRESETS = {
    "thermistor": ('Y"thermistor" T100000 B3950', "adc"),
    "pt1000": ('Y"pt1000"', "adc"),
    "thermocouple": ('Y"thermocouple-max31855"', "spi"),
}


class ToolError(ValueError):
    """code = a short code of the contract (pin_used, tool_exists...), field = the field of the spec it is about."""

    def __init__(self, code, field=""):
        super().__init__(code)
        self.code, self.field = code, field


def _pin_of(raw):
    return str(raw or "").strip().lstrip("!^")


def used_pins(texts):
    """The pins named by the live lines of the configuration files (a comment never counts)."""
    used = {}
    for path, text in texts:
        _, ls = pt.split_lines(text)
        for _, code in pt.live_lines(ls):
            word = pt.command_word(code)[0]
            for m in PIN_TOKEN_RE.finditer(code):
                used.setdefault(m.group(1), word or path)
    return used


def free_pins(used, kind=None):
    """[{pin, capabilities}] the board has that no line uses; kind = a capability to ask for (pwm, adc, spi...)."""
    return [{"pin": p, "capabilities": list(c)} for p, c in BOARD_PINS if p not in used and (not kind or kind in c)]


def _number(v, lo, hi, field, integer=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or (integer and int(v) != v):
        raise ToolError("values", field)
    return int(v) if integer else v


def _pin(raw, need, used, taken, field):
    """The pin of a use (a leading ! inverts it): the board has it, it can do what the use needs and nothing else uses it."""
    pin = _pin_of(raw)
    if pin not in CAPS:
        raise ToolError("pin_unknown", field)
    if need not in CAPS[pin]:
        raise ToolError("pin_capability", field)
    if pin in used or pin in taken:
        raise ToolError("pin_used", field)
    taken.add(pin)
    return str(raw).strip()


def _items(spec, key):
    v = spec.get(key)
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > MAX_ITEMS or not all(isinstance(x, dict) for x in v):
        raise ToolError("values", key)
    return v


def build_lines(spec, state):
    """The configuration lines of a tool -> {lines, summary}. state = {used: {pin: by}, tools: [numbers], heaters, sensors, fans, spindles (next free
    indexes), drivers_used: [..], laser_mode: bool}. Raises ToolError."""
    if not isinstance(spec, dict):
        raise ToolError("values", "spec")
    typ = spec.get("type")
    if typ not in TYPES:
        raise ToolError("values", "type")
    number = _number(spec.get("number"), 0, MAX_TOOLS - 1, "number", True)
    if number in state["tools"]:
        raise ToolError("tool_exists", "number")
    name = str(spec.get("name") or "")
    if not NAME_RE.match(name):
        raise ToolError("name", "name")
    used, taken = state["used"], set()
    lines, tool_h, tool_f, drive, spindle = [], [], [], None, None
    h_next, s_next, f_next = state["heaters"], state["sensors"], state["fans"]
    sensors_new = {}

    def sensor_line(item, field):
        nonlocal s_next
        preset = item.get("preset")
        if preset not in SENSOR_PRESETS:
            raise ToolError("values", field + ".preset")
        pin = _pin(item.get("pin"), SENSOR_PRESETS[preset][1], used, taken, field + ".pin")
        idx = s_next
        s_next += 1
        lines.append('M308 S%d P"%s" %s A"%s"' % (idx, pin, SENSOR_PRESETS[preset][0], name[:24] or "T%d" % number))
        return idx

    for i, item in enumerate(_items(spec, "sensors")):
        sensors_new[i] = sensor_line(item, "sensors[%d]" % i)
    for i, item in enumerate(_items(spec, "heaters")):
        field = "heaters[%d]" % i
        pin = _pin(item.get("pin"), "pwm", used, taken, field + ".pin")
        if isinstance(item.get("sensor"), dict):
            sidx = sensor_line(item["sensor"], field + ".sensor")
        elif isinstance(item.get("sensor"), int) and not isinstance(item.get("sensor"), bool) and 0 <= item["sensor"] < 100:
            sidx = item["sensor"]
        else:
            raise ToolError("values", field + ".sensor")
        tmax = _number(item.get("max_temp"), 50, 500, field + ".max_temp")
        idx = h_next
        h_next += 1
        lines.append('M950 H%d C"%s" T%d' % (idx, pin, sidx))
        lines.append("M143 H%d S%s" % (idx, pt.num_text(tmax)))
        tool_h.append(idx)
    for i, item in enumerate(_items(spec, "fans")):
        field = "fans[%d]" % i
        pin = _pin(item.get("pin"), "pwm", used, taken, field + ".pin")
        freq = _number(item.get("freq", 250), 1, 25000, field + ".freq")
        idx = f_next
        f_next += 1
        lines.append('M950 F%d C"%s" Q%s' % (idx, pin, pt.num_text(freq)))
        tool_f.append(idx)
    out = spec.get("output")
    if out is not None:
        if typ not in ("spindle", "laser", "generic"):
            raise ToolError("values", "output")
        if not isinstance(out, dict):
            raise ToolError("values", "output")
        pin = _pin(out.get("pin"), "pwm", used, taken, "output.pin")
        freq = _number(out.get("freq", 5000), 1, 25000, "output.freq")
        if typ == "spindle":
            rpm = _number(spec.get("rpm_max", 24000), 1, 200000, "rpm_max")
            spindle = state["spindles"]
            lines.append('M950 R%d C"%s" L0:%s Q%s' % (spindle, pin, pt.num_text(rpm), pt.num_text(freq)))
        else:
            if typ == "laser":
                if not state.get("laser_mode"):
                    raise ToolError("laser_mode", "type")
                _number(spec.get("power_max", 100), 1, 100, "power_max")
            idx = f_next
            f_next += 1
            lines.append('M950 F%d C"%s" Q%s' % (idx, pin, pt.num_text(freq)))
            tool_f.append(idx)
    elif typ in ("spindle", "laser"):
        raise ToolError("values", "output")
    drv = spec.get("drive")
    if drv is not None:
        if typ not in ("pellet_extruder", "fff_extruder", "generic") or not isinstance(drv, dict):
            raise ToolError("values", "drive")
        driver = str(drv.get("driver") or "")
        if not re.match(r"^(\d{1,2}\.)?\d{1,2}$", driver) or driver.count(".") != 1:
            raise ToolError("driver_unknown", "drive.driver")
        if driver in state["drivers_used"]:
            raise ToolError("driver_used", "drive.driver")
        if state.get("drivers_free") is not None and driver not in state["drivers_free"]:
            raise ToolError("driver_unknown", "drive.driver")
        drive = driver
    parts = ['M563 P%d S"%s"' % (number, name)]
    if drive is not None:
        parts.append("D%s" % drive)
    if tool_h:
        parts.append("H%s" % ":".join(str(h) for h in tool_h))
    if tool_f:
        parts.append("F%s" % ":".join(str(f) for f in tool_f))
    if spindle is not None:
        parts.append("R%d" % spindle)
    lines.append(" ".join(parts))
    off = spec.get("offsets")
    if off is not None:
        if not isinstance(off, dict) or set(off) - {"x", "y", "z"} or not off:
            raise ToolError("values", "offsets")
        axes = " ".join("%s%s" % (k.upper(), pt.num_text(_number(v, -1000, 1000, "offsets." + k))) for k, v in sorted(off.items()))
        lines.append("G10 P%d %s" % (number, axes))
    return {"lines": ["; Tool %d: %s (tool wizard)" % (number, name)] + lines,
            "summary": {"number": number, "name": name, "type": typ, "heaters": tool_h, "fans": tool_f, "drive": drive, "spindle": spindle}}


# ---- the state of the machine ----

def _model_state(om, used, tools_cfg):
    """What the build needs from the object model and the configuration: the next free numbers and the drivers in use."""
    om = om or {}
    tools = [t.get("number") for t in (om.get("tools") or []) if isinstance(t, dict) and isinstance(t.get("number"), int)]
    heat = om.get("heat") or {}
    heaters = len([h for h in (heat.get("heaters") or []) if h is not None])
    sensors = len([s for s in ((om.get("sensors") or {}).get("analog") or []) if s is not None])
    fans = len([f for f in (om.get("fans") or []) if f is not None])
    spindles = len([s for s in (om.get("spindles") or []) if s is not None])
    drivers = set()
    for ax in ((om.get("move") or {}).get("axes") or []):
        for d in (ax or {}).get("drives") or []:
            drivers.add("0." + str(d))
    for ex in ((om.get("move") or {}).get("extruders") or []):
        d = (ex or {}).get("driver")
        if d:
            drivers.add(str(d))
    mode = str((om.get("state") or {}).get("machineMode") or "")
    return {"used": used, "tools": sorted(set(tools + tools_cfg)), "heaters": heaters, "sensors": sensors, "fans": fans, "spindles": spindles,
            "drivers_used": drivers, "drivers_free": None, "laser_mode": mode == "Laser"}


def _config_texts(read):
    scan = config_scan.scan(read)
    return [(p, read(p) or "") for p in scan["files"]]


def _tools_in_config(texts):
    out = []
    for _, text in texts:
        _, ls = pt.split_lines(text)
        for _, code in pt.live_lines(ls):
            if pt.command_word(code)[0] == "M563":
                n = pt._p_of(code)
                if isinstance(n, int):
                    out.append(n)
    return out


def _state(read, om):
    texts = _config_texts(read)
    return _model_state(om, used_pins(texts), _tools_in_config(texts)), texts


# ---- the plan ----

def _insert_block(text, lines):
    eol, ls = pt.split_lines(text)
    at = -1
    for n, code in pt.live_lines(ls):
        if pt.command_word(code)[0] in ("M563", "M950", "M308", "M143"):
            at = n
    notices = []
    if at < 0:
        notices.append("no_anchor")
        at = len(ls) - 2 if ls and ls[-1] == "" else len(ls) - 1
    for k, line in enumerate(lines):
        ls.insert(at + 1 + k, line)
    return pt._result(ls, eol, "inserted", at + 2, notices)


def plan_tool(values, env):
    """Creates the lines of a tool in the configuration file that already defines tools (else config.g). The machine restarts to read them."""
    state, _ = _state(env["read"], env.get("om"))
    try:
        built = build_lines(values.get("spec", values), state)
    except ToolError as e:
        raise mc.PlanError("tool_name" if e.code == "name" else e.code, e.field)
    path, before, res, scan, hits = plans._edit(env, lambda t: "M563" in t, lambda t: _insert_block(t, built["lines"]))
    body = plans._body(path, before, res, scan, hits, None, None, built["summary"])
    body["warnings"].append("tool_restart")
    return body


# ---- the operations ----

def _get(args, ctx):
    import machine_ops as mo
    om = mo.model()
    state, _ = _state(mo.read_sd, om)
    tools = []
    for t in (om or {}).get("tools") or []:
        if isinstance(t, dict) and isinstance(t.get("number"), int):
            tools.append({"number": t["number"], "name": t.get("name"), "heaters": t.get("heaters") or [], "drives": t.get("extruders") or t.get("drives") or [],
                          "fans": t.get("fans") or [], "offsets": t.get("offsets") or []})
    taken = set(state["tools"])
    nxt = next((n for n in range(MAX_TOOLS) if n not in taken), None)
    return {"tools": tools, "next_number": nxt, "family_hint": str(((om or {}).get("state") or {}).get("machineMode") or "")}


def _pins(args, ctx):
    import machine_ops as mo
    state, _ = _state(mo.read_sd, mo.model())
    kind = args.get("kind")
    used = [{"pin": p, "by": by} for p, by in sorted(state["used"].items())]
    return {"free": free_pins(state["used"], kind if kind in ("pwm", "digital", "adc", "spi", "servo") else None), "used": used}


def _preview(args, ctx):
    import machine_ops as mo
    state, _ = _state(mo.read_sd, mo.model())
    try:
        built = build_lines(args.get("spec"), state)
    except ToolError as e:
        return {"lines": [], "files": [], "warnings": [], "errors": [{"code": e.code, "field": e.field}]}
    return {"lines": built["lines"], "files": [mc.rel_of(config_scan.ROOT)], "warnings": ["tool_restart"], "errors": []}


def ops():
    return [Op("machine.tool.get", _get, READ, {}, "The tools the machine has now (number, name, heaters, drives, fans, offsets), the next free tool number and the mode "
               "of the machine (Laser / CNC / FFF).", log=False),
            Op("machine.tool.pins", _pins, READ, {"kind": Arg("str", desc="Optional capability to ask for: pwm, digital, adc, spi or servo.")},
               "The pins of the board no line of the configuration uses, with what each one can do, and the ones that are in use with the command that uses them.", log=False),
            Op("machine.tool.preview", _preview, READ, {"spec": Arg("obj", desc="The tool as in the design: type, number, name, heaters, fans, sensors, output, drive, offsets.")},
               "The exact configuration lines the plan config.tool would write for this tool, or what is wrong with it. Writes nothing.", log=False)]


PLANNERS = {"config.tool": plan_tool}
