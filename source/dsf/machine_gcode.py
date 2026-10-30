"""The closed list of G-code that the Machine operations may send (Machine v2, design section 5.4).

The page never sends free text: a procedure of the service asks for a TEMPLATE by name with its numbers, `render()` builds the
line, and `check()` -- the only gate in front of the connection -- refuses anything that is not exactly one of the templates.
On top of that FORBIDDEN is a second, independent wall: even if somebody adds a template by mistake, a line that writes
a driver register, maps an expansion board, defines pins or stops the machine as an emergency is refused (and a test feeds every
template and a battery of bad lines through it).

Why those codes are forbidden (the policy of the owner, CLAUDE.md "NEVER write driver registers"):
  - `M569.2` (any: `W..` writes a raw TMC register and can damage the chip; even the read `R..` is the Motors poller's job, not
    Machine's) and `M569.1` (closed loop writes);
  - `M918`: expansion board mapping; `M950`: pins (admin, lights module); `M112`: emergency stop belongs to DWC / Jog.

Each phase adds the templates its procedures need, together with its tests; phase 0 only had the reads and the probe retract that the
skeleton needs, phase 1 adds the probing, levelling, mesh and M671 lines. A template with a number is validated twice: by the range of
its name in PARAMS (whole numbers, or decimals of at most 3 places) and by the pattern of the template itself.
"""
import re


class ForbiddenCode(ValueError):
    """The line is not one of the allowed templates (or is one of the forbidden codes). .code is the line; .reason a short code."""

    def __init__(self, code, reason):
        super().__init__("%s: %s" % (reason, code))
        self.code = code
        self.reason = reason


# second wall: never, from any Machine operation. Case-insensitive, any spacing, any position of the word in the line.
FORBIDDEN = (
    ("driver_register", re.compile(r"\bM569\.2\b", re.I)),
    ("closed_loop_write", re.compile(r"\bM569\.1\b", re.I)),
    ("driver_subcode", re.compile(r"\bM569\.[0-9]+", re.I)),         # M569.0 .3 .4 ... any dotted sub-code of the driver command (phase 3)
    ("board_mapping", re.compile(r"\bM918\b", re.I)),
    ("pins", re.compile(r"\bM950\b", re.I)),
    ("emergency_stop", re.compile(r"\bM112\b", re.I)),
)

_INDEX = r"([0-9]{1,2})"
_NUM = r"-?[0-9]{1,5}(?:\.[0-9]{1,3})?"
_LIST = r"%s(?::%s){1,3}" % (_NUM, _NUM)
_SKEW = r"-?[0-9]{1,2}(?:\.[0-9]{1,6})?"          # a skew factor: up to 6 places (it is a tangent)
SHAPERS = ("none", "zvd", "zvdd", "zvddd", "mzv", "ei2", "ei3")

# template id -> (format, pattern of what it may render). The format only has the named numbers of its pattern.
TEMPLATES = {
    "probe_params": ("G31 K{index}", re.compile(r"^G31 K%s$" % _INDEX)),                      # reads the probe parameters; no value = no change
    "probe_value": ('M409 K"sensors.probes[{index}].value"', re.compile(r'^M409 K"sensors\.probes\[%s\]\.value"$' % _INDEX)),
    "wait_moves": ("M400", re.compile(r"^M400$")),
    "probe_deploy": ("M401 P{index}", re.compile(r"^M401 P%s$" % _INDEX)),                      # always paired with probe_retract in a finally
    "probe_retract": ("M402 P{index}", re.compile(r"^M402 P%s$" % _INDEX)),
    # phase 1: probing. G30 K.. S-1 probes at the current XY and reports the stop height without touching the Z datum; with P the
    # firmware goes to X Y (where the PROBE touches) and probes from the dive height (Z-99999 = really probe, never a blind descent).
    "probe_stop": ("G30 K{k} S-1", re.compile(r"^G30 K%s S-1$" % _INDEX)),
    "probe_point": ("G30 P{p} X{x} Y{y} Z-99999 K{k}", re.compile(r"^G30 P%s X%s Y%s Z-99999 K%s$" % (_INDEX, _NUM, _NUM, _INDEX))),
    "probe_point_last": ("G30 P{p} X{x} Y{y} Z-99999 K{k} S{s}",
                         re.compile(r"^G30 P%s X%s Y%s Z-99999 K%s S(?:-1|[0-4])$" % (_INDEX, _NUM, _NUM, _INDEX))),
    "axis_state": ('M409 K"move.axes[{index}]" F"d2"', re.compile(r'^M409 K"move\.axes\[%s\]" F"d2"$' % _INDEX)),
    "probe_last_stop": ('M409 K"sensors.probes[{index}].lastStopHeight"', re.compile(r'^M409 K"sensors\.probes\[%s\]\.lastStopHeight"$' % _INDEX)),
    # levelling: G32 runs sys/bed.g; the calibration result is read back from the object model
    "bed_level": ("G32", re.compile(r"^G32$")),
    "home_z": ("G28 Z", re.compile(r"^G28 Z$")),
    "calibration_om": ('M409 K"move.calibration" F"d99"', re.compile(r'^M409 K"move\.calibration" F"d99"$')),
    "m671_set": ("M671 X{x} Y{y} S{s} P{p} F{f}", re.compile(r"^M671 X%s Y%s S%s P%s F%s$" % (_LIST, _LIST, _NUM, _NUM, _NUM))),
    # mesh: G32 first (it clears the map), then the grid and G29 S0 (explicit S: sys/mesh.g is NOT run). S1/S2 load and clear.
    "grid_define": ("M557 X{x0}:{x1} Y{y0}:{y1} P{nx}:{ny}", re.compile(r"^M557 X%s:%s Y%s:%s P[0-9]{1,2}:[0-9]{1,2}$" % (_NUM, _NUM, _NUM, _NUM))),
    "grid_probe": ("G29 S0 K{k}", re.compile(r"^G29 S0 K%s$" % _INDEX)),
    "mesh_load": ("G29 S1", re.compile(r"^G29 S1$")),
    "mesh_clear": ("G29 S2", re.compile(r"^G29 S2$")),
    "mesh_taper": ("M376 H{h}", re.compile(r"^M376 H%s$" % _NUM)),
    "compensation_om": ('M409 K"move.compensation" F"d99"', re.compile(r'^M409 K"move\.compensation" F"d99"$')),
    # phase 2: values that apply_now / machine.try send at once (volatile; the file is what persists). Always with the explicit L of G10:
    # a bare G10 is a firmware retract and G10 with R / S is a temperature.
    "g31_set": ("G31 K{k} P{trig} X{x} Y{y} Z{z}", re.compile(r"^G31 K%s P[0-9]{1,4} X%s Y%s Z%s$" % (_INDEX, _NUM, _NUM, _NUM))),
    "limits_set": ("M208 {axis}{lo}:{hi}", re.compile(r"^M208 [XYZUVWABC]%s:%s$" % (_NUM, _NUM))),
    "steps_set": ("M92 {axis}{v}", re.compile(r"^M92 [XYZUVWABCE]%s$" % _NUM)),
    "g10_tool_axis": ("G10 L1 P{tool} {axis}{v}", re.compile(r"^G10 L1 P[0-9]{1,2} [XYZUVWABC]%s$" % _NUM)),
    "g10_work_axis": ("G10 L2 P{n} {axis}{v}", re.compile(r"^G10 L2 P[1-9] [XYZUVWABC]%s$" % _NUM)),
    # homing verification and the reads it needs
    "home_axis": ("G28 {axis}", re.compile(r"^G28 [XYZUVWABC]$")),
    "endstops_om": ('M409 K"sensors.endstops" F"d99"', re.compile(r'^M409 K"sensors\.endstops" F"d99"$')),
    # laser cross (laser <-> pointer): relative moves with the power of the cut, then back to absolute and the laser off
    "rel_mode": ("G91", re.compile(r"^G91$")),
    "abs_mode": ("G90", re.compile(r"^G90$")),
    "cross_move": ("G1 {axis}{d} F{feed} S{power}", re.compile(r"^G1 [XY]%s F[0-9]{1,5} S[0-9]{1,3}(?:\.[0-9]{1,3})?$" % _NUM)),
    "laser_off": ("M5", re.compile(r"^M5$")),
    # phase 3: motion parameters. Volatile values of machine.try / apply_now: ONE axis or one value per line, no M569 anywhere (the
    # plan edits the FILE for that), no M955 beyond the bare report, no M956 without A0 (the only form the firmware implements).
    "current_set": ("M906 {axis}{v}", re.compile(r"^M906 [XYZUVWABCE]%s$" % _NUM)),
    "idle_percent_set": ("M906 I{idle}", re.compile(r"^M906 I[0-9]{1,3}$")),
    "idle_timeout_set": ("M906 T{secs}", re.compile(r"^M906 T[0-9]{1,4}$")),
    "current_pct_set": ("M913 {axis}{pct}", re.compile(r"^M913 [XYZUVWABCE]%s$" % _NUM)),
    "standstill_set": ("M917 {axis}{pct}", re.compile(r"^M917 [XYZUVWABCE]%s$" % _NUM)),
    "speed_set": ("M203 {axis}{v}", re.compile(r"^M203 [XYZUVWABCE]%s$" % _NUM)),
    "accel_set": ("M201 {axis}{v}", re.compile(r"^M201 [XYZUVWABCE]%s$" % _NUM)),
    "jerk_set": ("M205 {axis}{v}", re.compile(r"^M205 [XYZUVWABCE]%s$" % _NUM)),
    "jerk_machine_set": ("M566 {axis}{v}", re.compile(r"^M566 [XYZUVWABCE]%s$" % _NUM)),
    "backlash_set": ("M425 {axis}{v}", re.compile(r"^M425 [XYZUVWABC]%s$" % _NUM)),
    "backlash_factor": ("M425 S{mult}", re.compile(r"^M425 S%s$" % _NUM)),
    "skew_set": ("M556 S1 X{fx} Y{fy} Z{fz}", re.compile(r"^M556 S1 X%s Y%s Z%s$" % (_SKEW, _SKEW, _SKEW))),     # S1: the values ARE the skew factors
    "shaping_set": ('M593 P"{shaper}" F{freq} S{damp}', re.compile(r'^M593 P"(?:zvd|zvdd|zvddd|mzv|ei2|ei3)" F%s S%s$' % (_NUM, _NUM))),
    "shaping_none": ('M593 P"none"', re.compile(r'^M593 P"none"$')),
    "accel_report": ("M955 P{index}", re.compile(r"^M955 P%s$" % _INDEX)),                       # no other option: it only reports
    "accel_collect": ("M956 P{index} S{samples} A0 {axis}", re.compile(r"^M956 P%s S[0-9]{3,4} A0 [XY]$" % _INDEX)),
    # phase 4: the move of offsets.verify, absolute, X and Y only, never the laser (S0). move_xy is in the user coordinates of the active system
    # and tool (the firmware applies the offsets); move_xy_machine is in machine coordinates (G53, UNVERIFIED form on the board)
    "move_xy": ("G1 X{x} Y{y} F{feed} S0", re.compile(r"^G1 X%s Y%s F[0-9]{1,5} S0$" % (_NUM, _NUM))),
    "move_xy_machine": ("G53 G1 X{x} Y{y} F{feed} S0", re.compile(r"^G53 G1 X%s Y%s F[0-9]{1,5} S0$" % (_NUM, _NUM))),
    "tune_move": ("G1 {axis}{pos} F{feed} S0", re.compile(r"^G1 [XY]%s F[0-9]{1,5} S0$" % _NUM)),     # absolute, X or Y only, never the laser
    # height calibration (machine_height.py): the macros of the assistants and ONE relative Z step (G91 / G90 are rel_mode / abs_mode), never the laser
    "zcal_goto": ('M98 P"0:/sys/workshop/macros/zcal-goto.g" X{x} Y{y}', re.compile(r'^M98 P"0:/sys/workshop/macros/zcal-goto\.g" X%s Y%s$' % (_NUM, _NUM))),
    "zcal_mark": ('M98 P"0:/sys/workshop/macros/zcal-mark.g" P{paper} H{h}', re.compile(r'^M98 P"0:/sys/workshop/macros/zcal-mark\.g" P%s H%s$' % (_NUM, _NUM))),
    "zcal_probe": ('M98 P"0:/sys/workshop/macros/zcal-probe.g" X{x} Y{y}', re.compile(r'^M98 P"0:/sys/workshop/macros/zcal-probe\.g" X%s Y%s$' % (_NUM, _NUM))),
    "zcal_szp": ('M98 P"0:/sys/workshop/macros/zcal-szp.g" X{x} Y{y} A{a}', re.compile(r'^M98 P"0:/sys/workshop/macros/zcal-szp\.g" X%s Y%s A[12]$' % (_NUM, _NUM))),
    "zcal_apply": ('M98 P"0:/sys/workshop/macros/zcal.g"', re.compile(r'^M98 P"0:/sys/workshop/macros/zcal\.g"$')),
    "zcal_med": ('M409 K"global.workshopZcalMed"', re.compile(r'^M409 K"global\.workshopZcalMed"$')),
    "jog_z": ("G1 Z{d} F{feed} S0", re.compile(r"^G1 Z%s F[0-9]{1,5} S0$" % _NUM)),
    # work area (machine_workarea.py): the macros of the corner assistants (release X/Y, measure the corner at the end stops, take the pointer
    # to a bed point, walk the saved area with the pointer), the two numbers the measurement leaves in the object model and the reload of cutarea.g
    "area_release": ('M98 P"0:/sys/workshop/macros/handfree.g"', re.compile(r'^M98 P"0:/sys/workshop/macros/handfree\.g"$')),
    "area_capture": ('M98 P"0:/sys/workshop/macros/handcorner.g"', re.compile(r'^M98 P"0:/sys/workshop/macros/handcorner\.g"$')),
    "area_goto": ('M98 P"0:/sys/workshop/macros/gotobed.g" X{x} Y{y}', re.compile(r'^M98 P"0:/sys/workshop/macros/gotobed\.g" X%s Y%s$' % (_NUM, _NUM))),
    "area_frame": ('M98 P"0:/sys/workshop/macros/framecutarea.g"', re.compile(r'^M98 P"0:/sys/workshop/macros/framecutarea\.g"$')),
    "area_corner_x": ('M409 K"global.handCornerX"', re.compile(r'^M409 K"global\.handCornerX"$')),
    "area_corner_y": ('M409 K"global.handCornerY"', re.compile(r'^M409 K"global\.handCornerY"$')),
    "area_reload": ('M98 P"0:/sys/workshop/zones/cutarea.g"', re.compile(r'^M98 P"0:/sys/workshop/zones/cutarea\.g"$')),
}

# range of each named value: ("int", lo, hi), ("num", lo, hi) (decimals, at most 3 places) or ("list", lo, hi, n_min, n_max) (a:b:c).
# A name that is not here is an index: a whole number 0..99.
PARAMS = {
    "k": ("int", 0, 15), "p": ("int", 0, 31), "s": ("int", -1, 4), "nx": ("int", 2, 31), "ny": ("int", 2, 31),
    "x": ("num", -5000, 5000), "y": ("num", -5000, 5000), "z": ("num", -5000, 5000),
    "x0": ("num", -5000, 5000), "x1": ("num", -5000, 5000), "y0": ("num", -5000, 5000), "y1": ("num", -5000, 5000),
    "h": ("num", 0, 100), "paper": ("num", 0, 3), "a": ("int", 1, 2),
    "trig": ("int", 0, 1023), "axis": ("letter",), "lo": ("num", -5000, 5000), "hi": ("num", -5000, 5000), "v": ("num", -99999, 99999),
    "tool": ("int", 0, 49), "n": ("int", 1, 9), "d": ("num", -50, 50), "feed": ("int", 1, 30000), "power": ("num", 0, 255),
    # phase 3
    "idle": ("int", 0, 100), "secs": ("int", 1, 3600), "pct": ("num", 0, 100), "mult": ("num", 1, 100), "samples": ("int", 100, 3000),
    "pos": ("num", -5000, 5000), "freq": ("num", 4, 300), "damp": ("num", 0, 0.99), "shaper": ("choice", SHAPERS[1:]),
    "fx": ("num", -0.2, 0.2, 6), "fy": ("num", -0.2, 0.2, 6), "fz": ("num", -0.2, 0.2, 6),
}
# M671 has its own names for the same letters: coordinates are lists, S P F are decimals
LIST_TEMPLATES = {"m671_set": {"x": ("list", -5000, 5000, 2, 4), "y": ("list", -5000, 5000, 2, 4), "s": ("num", 0, 100),
                               "p": ("num", 0, 100), "f": ("num", 0, 10)}}


def forbidden(code):
    """Reason code if the line contains a forbidden code, else None."""
    for reason, rx in FORBIDDEN:
        if rx.search(str(code)):
            return reason
    return None


def num_text(v, places=3):
    """A decimal as the G-code writes it: at most 3 places (6 for a skew factor), no trailing zeros, never "-0"."""
    t = ("%.*f" % (places, float(v))).rstrip("0").rstrip(".")
    return "0" if t in ("-0", "") else t


def _value_text(template_id, name, v):
    spec = LIST_TEMPLATES.get(template_id, {}).get(name) or PARAMS.get(name, ("int", 0, 99))
    bad = ForbiddenCode("%s %s=%r" % (template_id, name, v), "bad_value")
    if spec[0] == "letter":
        if not isinstance(v, str) or len(v) != 1 or v not in "XYZUVWABCE":
            raise bad
        return v
    if spec[0] == "choice":
        if not isinstance(v, str) or v not in spec[1]:
            raise bad
        return v
    kind, lo, hi = spec[0], spec[1], spec[2]
    if kind == "list":
        if not isinstance(v, (list, tuple)) or not spec[3] <= len(v) <= spec[4]:
            raise bad
        return ":".join(_value_text_num(x, lo, hi, bad) for x in v)
    if kind == "num":
        return _value_text_num(v, lo, hi, bad, spec[3] if len(spec) > 3 else 3)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise bad
    return str(v)


def _value_text_num(v, lo, hi, bad, places=3):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        raise bad
    return num_text(v, places)


def render(template_id, **params):
    """The line of a template. Unknown template or a value outside the range of its name -> ForbiddenCode."""
    if template_id not in TEMPLATES:
        raise ForbiddenCode(template_id, "unknown_template")
    fmt, rx = TEMPLATES[template_id]
    clean = {k: _value_text(template_id, k, v) for k, v in params.items()}
    try:
        line = fmt.format(**clean)
    except (KeyError, IndexError):
        raise ForbiddenCode(template_id, "bad_value")
    return check(line)


def check(code):
    """Returns the line when it is exactly one of the templates; ForbiddenCode otherwise. The single gate before the connection."""
    line = str(code).strip()
    why = forbidden(line)
    if why:
        raise ForbiddenCode(line, why)
    if "\n" in line or "\r" in line or ";" in line:
        raise ForbiddenCode(line, "not_one_line")
    if not any(rx.match(line) for _, rx in TEMPLATES.values()):
        raise ForbiddenCode(line, "not_in_the_list")
    return line
