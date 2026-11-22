"""Pure table of G-code classes and the exemption rule of the central G-code control (design DISENO-GCODE-CONTROL.md, phase G0).

Nothing here runs in the service: no interceptor, no main.py, no I/O, standard library only (layer L0). It answers two questions about
text that somebody put in front of the machine:

  1. classify_line(text) / classify(letter, number, minor, params): the CLASS of the code (section 4 of the design). A line with several
     codes takes the HIGHEST class (RANK). A code that is not in the table is `unknown` and is NEVER refused: the table says what we know,
     not what is allowed.
  2. exempt(text, channel) / channel_exempt(name): what is never filtered as if the operator typed it (section 3). The exemption of
     macros, files, daemon and trigger lines is by CHANNEL (a channel the filter does not subscribe to), never by looking at the text.

The lists of this module are the ONLY source (machine_gcode is L4 and permissions is L5, a kernel module cannot import them);
test_gcode_classes.py checks that they agree with machine_gcode.FORBIDDEN / TEMPLATES and with permissions.ESCALATE_IN, so a copy
cannot drift silently.

Project rule behind `never` (never write driver registers): M569.2 with a value (V, or W as the design writes it) and every
other dotted M569 sub-code are `never`; M569.2 without a value is the read of the Motors poller, so it is `read`.
"""
import re

# classes of the design, section 4 (names exact). `move_g0g3` is the part of `move` the owner has not decided yet (G0-G3 inside the
# filter or not); `empty` is a line with no code; `power` is NOT in the table of the design (it exists in permission_caps): see the
# discrepancies list in the report of phase G0.
STOP = "stop"
READ = "read"
MOVE = "move"
MOVE_G0G3 = "move_g0g3"
MOTORS = "motors"
WORKPLACE = "workplace"
HEAT = "heat"
JOB = "job"
MACRO_OTHER = "macro-ajena"
TUNING = "tuning"
HARDWARE = "hardware"
NEVER = "never"
PINS = "pins"
NETWORK = "network"
PERSIST = "persist"
MODE = "mode"
POWER = "power"
UNKNOWN = "unknown"
EMPTY = "empty"

# lowest to highest: a line takes the highest class of its codes. unknown sits under never and above the admin classes (the design
# says unknown is administrator level), but it is never refused.
RANK_ORDER = (EMPTY, STOP, READ, MOVE, MOVE_G0G3, MOTORS, WORKPLACE, HEAT, POWER, JOB, MACRO_OTHER, TUNING, MODE,
              HARDWARE, PINS, NETWORK, PERSIST, UNKNOWN, NEVER)
RANK = {c: i for i, c in enumerate(RANK_ORDER)}
CLASSES = frozenset(RANK_ORDER)

# classes of phase G1 (observe only) `filters`: the high ones, WITHOUT G0-G3 and WITHOUT reads (design section 8, phase G1).
PHASE1_FILTER_CLASSES = frozenset({HARDWARE, NEVER, PINS, NETWORK, PERSIST, TUNING, MODE, JOB, MACRO_OTHER})

# codes that stop the machine or recover from a stop: they are never filtered (design section 3). M999 is the DWC "Reset" after M112.
STOP_CODES = frozenset({"M0", "M1", "M25", "M112", "M999"})
# the codes of machine_gcode.FORBIDDEN by name: the test checks that each one lands where the design says (never, pins, stop)
FORBIDDEN_LANDING = {"M569.2": NEVER, "M569.1": NEVER, "M918": NEVER, "M950": PINS, "M112": STOP}

# the hardware-risk-4 codes of permissions.ESCALATE_IN (MACHINE_ADMIN_KINDS / MACHINE_ADMIN_TRY): the test compares both lists
HARDWARE_CODES = frozenset({"M92", "M208", "M906", "M913", "M915", "M917", "M911", "M584", "M569"})

_BASE = {
    STOP: ("M0", "M1", "M25", "M112", "M999"),
    READ: ("M20", "M27", "M36", "M38", "M39", "M105", "M114", "M115", "M117", "M118", "M119", "M122", "M291", "M292", "M408", "M409",
           "M503"),
    MOVE: ("G4", "G17", "G18", "G19", "G20", "G21", "G28", "G29", "G30", "G32", "G38", "G53", "G90", "G91", "M120", "M121", "M290",
           "M376", "M400"),
    MOVE_G0G3: ("G0", "G1", "G2", "G3"),
    MOTORS: ("M17", "M18", "M84", "M201", "M203", "M205", "M564", "M566", "M579"),
    WORKPLACE: ("G54", "G55", "G56", "G57", "G58", "G59", "G68", "G69", "G92"),
    HEAT: ("M3", "M4", "M5", "M7", "M8", "M9", "M42", "M104", "M106", "M109", "M140", "M141", "M143", "M190", "M280", "M401", "M402",
           "M562", "M568"),
    POWER: ("M80", "M81"),
    JOB: ("M2", "M23", "M24", "M26", "M32", "M226", "M577", "M916"),
    TUNING: ("M301", "M302", "M303", "M307", "M308", "M350", "M351", "M425", "M556", "M557", "M558", "M572", "M593", "M671", "M955",
             "M956"),
    HARDWARE: ("M92", "M208", "M906", "M911", "M913", "M915", "M917", "M584"),
    PINS: ("M574", "M575", "M586", "M591", "M950", "M951"),
    NETWORK: ("M540", "M550", "M551", "M552", "M553", "M554", "M555", "M587", "M588", "M589"),
    PERSIST: ("M21", "M22", "M28", "M29", "M30", "M111", "M470", "M471", "M500", "M501", "M502", "M505", "M929", "M997", "M998"),
    MODE: ("M451", "M452", "M453"),
    NEVER: ("M918",),
}
TABLE = {_c: _cls for _cls, _codes in _BASE.items() for _c in _codes}
# the code of two classes in the design: M584 is hardware (risk 4, in ESCALATE_IN) AND pins; the higher-risk row of ESCALATE_IN wins.
# M92 / M208 ... appear once, as hardware. T (tool select) runs the tool change macros and moves: move.

# dotted forms we know; any other dotted form of a code is unknown (M7.41 and friends are workshop codes, not RRF)
MINORS = {("G59", 1): WORKPLACE, ("G59", 2): WORKPLACE, ("G59", 3): WORKPLACE,
          ("G92", 1): WORKPLACE, ("G92", 2): WORKPLACE, ("G92", 3): WORKPLACE,
          ("G38", 2): MOVE, ("G38", 3): MOVE, ("G38", 4): MOVE, ("G38", 5): MOVE}

# the codes that only REPORT when they carry no parameter (M92 alone prints the steps, M550 alone prints the name...). With any parameter
# (also a `{expression}`, which is never evaluated) they stay in their writing class.
BARE_READS = frozenset({"M92", "M208", "M906", "M911", "M913", "M915", "M917", "M584", "M307", "M308", "M558", "M572", "M593", "M556",
                        "M425", "M671", "M350", "M351", "M302", "M557", "M574", "M591", "M575", "M586", "M550", "M552", "M553",
                        "M554", "M555", "M587", "M589", "M540", "M564", "M201", "M203", "M205", "M566", "M579", "M143", "M141"})

WORKSHOP_MACRO_PREFIX = "0:/sys/workshop/"

# --- channels (design section 3): what the filter never sees because it never subscribes to them
FILTERED_CHANNELS = frozenset({"http"})
# the channels of the design that are exempt by construction: file jobs, daemon, trigger, autopause, queues, the service itself
# (Aux2 / SBC) and the bridge (SBC). Aux (PanelDue), Telnet and USB are not subscribed either (design decision 6: later, observe only).
EXEMPT_CHANNELS = frozenset({"file", "file2", "queue", "queue2", "daemon", "trigger", "autopause", "sbc", "aux2", "spi", "aux", "telnet",
                             "usb", "codestream", "display", "generic", "unknown"})


class Code:
    """One parsed code: letter (upper case), whole number, minor (int or None) and params {LETTER: raw text}."""
    __slots__ = ("letter", "number", "minor", "params")

    def __init__(self, letter, number, minor, params):
        self.letter, self.number, self.minor, self.params = letter, number, minor, params

    def key(self):
        return "%s%d" % (self.letter, self.number) + ("" if self.minor is None else ".%d" % self.minor)

    def __repr__(self):
        return "Code(%s, %r)" % (self.key(), self.params)


def _strip_comments(text):
    """Remove `; ...` and `( ... )` comments outside quotes and outside `{ ... }` expressions."""
    out, quote, depth, paren = [], False, 0, False
    for ch in text:
        if quote:
            out.append(ch)
            quote = ch != '"'
            continue
        if paren:
            paren = ch != ")"
            continue
        if ch == '"':
            quote = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and ch == ";":
            break
        elif depth == 0 and ch == "(":
            paren = True
            continue
        out.append(ch)
    return "".join(out)


_NUM = re.compile(r"[-+]?[0-9.]+(?::[-+]?[0-9.]+)*")
_CODE_NUM = re.compile(r"(-?[0-9]+)(?:\.([0-9]+))?")


def _read_value(s, i):
    """The value of a parameter word that starts at s[i]: quoted string, `{...}` expression, number (or a:b list) or bare text."""
    n = len(s)
    if i < n and s[i] == '"':
        j = i + 1
        while j < n:
            if s[j] == '"':
                if j + 1 < n and s[j + 1] == '"':
                    j += 2
                    continue
                return s[i:j + 1], j + 1
            j += 1
        return s[i:], n
    if i < n and s[i] == "{":
        depth, j = 0, i
        while j < n:
            depth += (s[j] == "{") - (s[j] == "}")
            j += 1
            if depth == 0:
                break
        return s[i:j], j
    m = _NUM.match(s, i)
    if m:
        return m.group(0), m.end()
    j = i
    while j < n and not s[j].isspace():
        j += 1
    return s[i:j], j


def _words(s):
    """Split a comment-free line into (letter, value) words; a word is one letter followed by its value."""
    words, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '"':  # a bare quoted text (M117 "hello"): skip it whole, what it contains is not code
            i = _read_value(s, i)[1]
            continue
        if not ch.isalpha():
            i += 1
            continue
        if i + 1 < n and s[i + 1].isalpha() and (i == 0 or s[i - 1].isspace()):
            # a keyword (echo, set, if ...): not a G-code word, keep it whole
            j = i
            while j < n and not s[j].isspace():
                j += 1
            words.append((s[i:j].lower(), None))
            i = j
            continue
        value, i2 = _read_value(s, i + 1)
        words.append((ch.upper(), value))
        i = i2
    return words


def parse(text):
    """Parse one line into a list of Code. Keyword lines (echo, set, if) give a single Code with letter "" and number 0."""
    s = _strip_comments(str(text or "")).strip()
    words = _words(s)
    if words and words[0][0] == "N" and words[0][1] is not None:
        words = words[1:]
    if not words:
        return []
    if words[0][1] is None:
        return [Code("", 0, None, {"": s})]
    codes = []
    for pos, (letter, value) in enumerate(words):
        is_code = letter in "GM" or (letter == "T" and pos == 0)
        m = _CODE_NUM.fullmatch(value) if (is_code and value is not None) else None
        if m:
            codes.append(Code(letter, int(m.group(1)), None if m.group(2) is None else int(m.group(2)), {}))
        elif codes and value is not None:
            codes[-1].params[letter] = value
    return codes


def _present(params):
    if params is None:
        return {}
    if isinstance(params, dict):
        return {str(k).upper(): ("" if v is None else str(v)) for k, v in params.items()}
    return {str(k).upper(): "" for k in params}


def _unquote(v):
    v = str(v).strip()
    return v[1:-1].replace('""', '"') if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else v


def _classify_m569(minor, p):
    if minor is None:
        return READ if set(p) <= {"P"} else HARDWARE
    if minor == 2:
        return NEVER if ("V" in p or "W" in p) else READ
    return NEVER


def _classify_g10(p):
    if "L" in p:
        return WORKPLACE
    return HEAT if ("R" in p or "S" in p) else MOVE


def _classify_m98(p):
    path = _unquote(p.get("P", ""))
    if "{" in path or not path:
        return MACRO_OTHER
    return JOB if path.lower().startswith(WORKSHOP_MACRO_PREFIX) else MACRO_OTHER


def classify(letter, number, minor=None, params=None):
    """Class of ONE code. `params` is a dict {LETTER: text} (or an iterable of letters); only its keys and the `{` mark are used."""
    letter, p = str(letter).upper(), _present(params)
    number = int(number)
    key = "%s%d" % (letter, number)
    if letter == "T":
        return MOVE
    if letter not in "GM":
        return UNKNOWN
    if key == "M569":
        return _classify_m569(minor, p)
    if minor is not None:
        return MINORS.get((key, int(minor)), UNKNOWN)
    if key == "G10":
        return _classify_g10(p)
    if key == "M98":
        return _classify_m98(p)
    if key == "G31":
        return READ if set(p) <= {"K"} else TUNING
    cls = TABLE.get(key)
    if cls is None:
        return UNKNOWN
    if key in BARE_READS and not p:
        return READ
    return cls


def _classify_keyword(text):
    low = text.strip().lower()
    if re.match(r"set\s+global\.selectedmode\b", low):
        return MODE
    if low.startswith("echo"):
        return READ
    return UNKNOWN


def classify_codes(text):
    """[(key, class)] of every code of the line, in order. Keyword lines give one pair with the text's first word."""
    out = []
    for c in parse(text):
        if c.letter == "":
            out.append((c.params[""].split()[0].lower(), _classify_keyword(c.params[""])))
        else:
            out.append((c.key(), classify(c.letter, c.number, c.minor, c.params)))
    return out


def classify_line(text):
    """Class of a whole line: the highest of its codes (`empty` when it has none)."""
    best = EMPTY
    for _key, cls in classify_codes(text):
        if RANK[cls] > RANK[best]:
            best = cls
    return best


def channel_exempt(channel):
    """True when the filter never sees this channel (file job, daemon, trigger, queues, the service itself, the bridge...). By NAME of the
    channel, never by the text of the line. A missing name is NOT exempt: nothing is assumed about an origin we cannot name."""
    if channel is None:
        return False
    name = str(getattr(channel, "value", channel)).strip().lower()
    return bool(name) and name not in FILTERED_CHANNELS


def exempt_class(cls):
    """A class that is never filtered: a stop (or a line with no code)."""
    return cls in (STOP, EMPTY)


def exempt(text=None, channel=None):
    """The exemption rule of the design (section 3): True when the line must pass untouched, either because its channel is not one the
    filter subscribes to, or because the line (all of it) is a stop / recovery code. A line that mixes M112 with a never code is NOT
    exempt (the highest class decides)."""
    if channel_exempt(channel):
        return True
    return text is not None and exempt_class(classify_line(text))


def outside_filters(cls):
    """True for the classes that stay out of the phase-G1 `filters` (stop, read, empty, and moves, heat, workplace, motors, power...)."""
    return cls not in PHASE1_FILTER_CLASSES
