"""What a received line is: the closed grammar of the queries, the codes of each policy and the job marks (pure, no state)."""


import re


QUERIES_DEFAULT = ["M114", "M115", "M105", "M119", "M122", "M408", "M503", "M27", "M20", "M36"]
# Closed grammar of the queries. A line is a query only if it matches the pattern of its code COMPLETELY (the whole line, not its first
# word): anything else (`M114 G1 X100`, `M122 P1001`, `M105 M3 S255`) is an order and goes through password, control, machine gate and log.
_PATH = r'(?:"[^"]*"|[^\s;"]+)'
QUERY_GRAMMAR = {
    "M114": r"M114(?:\s+S\d)?",
    "M115": r"M115(?:\s+B\d+)?",
    "M105": r"M105(?:\s+[TR]\d+)?",
    "M119": r"M119",
    "M122": r'M122(?:\s+B\d+|\s+"DSF")?',
    "M408": r"M408(?:\s+S\d)?(?:\s+R\d+)?",
    "M409": r'M409(?:\s+[KF]"[^"]*"|\s+[KF][^\s;"]+)*',
    "M503": r"M503",
    "M27": r"M27(?:\s+S\d)?",
    "M20": r"M20(?:\s+S\d|\s+R\d+|\s+P" + _PATH + r")*",
    "M36": r"M36(?:\s+" + _PATH + r")?",
}
QUERY_GRAMMAR_RE = {code: re.compile(pattern + r"\Z", re.IGNORECASE) for code, pattern in QUERY_GRAMMAR.items()}


def is_query_line(line, allowed):
    """True if the whole line is a query of the closed grammar and its code is in the allowed list."""
    parts = line.split()
    if not parts or parts[0].upper() not in allowed:
        return False
    rx = QUERY_GRAMMAR_RE.get(parts[0].upper())
    return bool(rx and rx.match(line.strip()))


MAX_LINE = 1024
# G0/G1 without parameters is an automatic "ping" of some programs: answered ok locally.
NOOP_WITHOUT_PARAMS = {"G0", "G1"}
# The M98 lines a program carries to prepare the material (focus, origin, live-job mark): the zone macros in macros/laser and the two helpers they call.
MATERIAL_MACRO_RE = re.compile(r'^\s*M98\s+P\s*"?(?:[^"\s]*/macros/laser/|[^"\s]*/(?:laserfocus|livemark)\.g)', re.IGNORECASE)
# Codes that mean "the machine may be moving or about to move".
MOTION_CODES = {"G0", "G1", "G2", "G3", "G5", "G28", "G29", "G30", "G32", "G38",
                "M3", "M4", "M5", "M24", "M32", "M98"}
# Orders that move the machine or turn the laser on: refused while the machine cannot take them (paused, halted by an error,
# cancelling...). Stops (M5, M0, M25, M112, M999) and queries always pass.
GATED_CODES = {"G0", "G1", "G2", "G3", "G5", "G28", "G29", "G30", "G32", "G38", "M3", "M4"}


# A stop of the program ends the live job at once (nobody else would tell the service it is over): M0 (stop) and M112
# (emergency stop). The machine halting or switching off does the same (see MachineGate.refresh).
STOP_ENDS_JOB = {"M0", "M112"}
# Only the homing itself passes while some axis is not homed (a job sent before the homing would otherwise run, from the middle, as soon as it ends).
NEEDS_HOMING_OK = {"G28"}
# After the bridge refuses an order of a job, the rest of that job is refused too for this long (it is renewed by every refused order): the program keeps
# streaming and the lines that come after the refused ones (the material macro was one of them) must not run on their own. A new BRIDGE JOB START clears it.
TAINT_S = 30.0
# A macro or a probing order that FAILS ("Error: ..." in its reply: the Z probe did not trigger, the BLTouch pin (M280) gave an alarm, a macro called abort, ...)
# stops the rest of the job: the program keeps streaming (its start macro was one of the failed lines) and what follows would run without the focus,
# the origin or the probe that macro was supposed to set. The orders that fail are the ones in FAIL_WATCH; from then on every order is refused
# except the stops (STOPS_PASS) for FAIL_REFUSE_S seconds, or until BRIDGE JOB START / BRIDGE RESUME.
FAIL_WATCH = {"M98", "G30", "M280", "M401", "M402"}
STOPS_PASS = {"M5", "M0", "M25", "M112", "M999"}
FAIL_REFUSE_S = 120.0


M118_JOB_RE = re.compile(r'^M118\s+(?:.*?\s)?S\s*"\s*(BRIDGE\s+JOB(?:\s[^"]*)?)"', re.IGNORECASE)


def m118_job_line(line):
    """`M118 P0 S"BRIDGE JOB START name"` -> `BRIDGE JOB START name`, else None.
    A real G-code that carries the job mark: the Duet understands it inside an uploaded
    file (it only prints the message) while the bridge answers it itself when it streams."""
    m = M118_JOB_RE.match(line.strip())
    return m.group(1).strip() if m else None


def parse_job_command(arg):
    """Argument of BRIDGE JOB ... -> (action, detail) or None.
    action is "start" (detail = job name or None) or "end" (detail = end/cancel/close).
    START [name] | END | CANCEL | CLOSE."""
    parts = str(arg or "").strip().split(None, 1)
    if not parts:
        return None
    verb = parts[0].upper()
    rest = parts[1].strip().strip('"').strip() if len(parts) > 1 else ""
    if verb == "START":
        return "start", (rest[:80] or None)
    if verb == "END":
        return "end", "end"
    if verb == "CANCEL":
        return "end", "cancel"
    if verb == "CLOSE":
        return "end", "close"
    return None
