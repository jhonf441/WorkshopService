"""The temperature commands a G-code file carries, found by a pure scanner (no I/O except reading the file given, never writes, never sends).

Used by the recipe preview (layer_recipes_preview.py) to show, layer by layer, what the FILE itself asks for next to what a recipe sets.

    scan_lines(iterable of bytes or str lines, max_commands=2000) -> {"commands": [...], "truncated": bool}
    scan_file(path, max_commands=2000)                           -> the same, reading the file once, line by line (it can weigh megabytes)

A command is {"line": 1-based, "text": the line cut at 200 characters, "kind": "extruder" | "bed" | "chamber", "tool": int | None, "bed": int | None,
"temps": [numbers] | None, "code": "M104" ...}. `tool` is the T of the command or the tool selected by the last T<n> line (None when none is known);
`bed` None means NO P in an M140 / M190 (the bed-zones interception splits it across the zones). `temps` is None when the value is an expression
or anything else that can not be evaluated (the line is kept anyway). Recognised: M104, M109, G10 (P S), M568 (P S, a list S200:210 per heater),
M140, M190, M141, M191. Standby-only values (G10 R, M568 R) are not active temperatures and are skipped; comments (; and parentheses) are ignored.
"""
import re

MAX_COMMANDS = 2000
LINE_CHARS = 200

# cheap test on the raw bytes: only lines that can be one of our commands or a tool selection are decoded
_QUICK = re.compile(rb"^\s*(?:N\d+\s*)?(?:[Mm]\s*(?:104|109|140|190|141|191|568)(?!\d)|[Gg]\s*10(?!\d)|[Tt]\s*-?\d)")
_WORD = re.compile(r"^\s*(?:N\d+\s*)?([GMT])\s*(-?\d+)")
_PARAM = re.compile(r"([A-Z])\s*(\{[^}]*\}|\"[^\"]*\"|[-+]?(?:\d+\.?\d*|\.\d+)(?::[-+]?(?:\d+\.?\d*|\.\d+))*|[^\s]*)")
_PAREN = re.compile(r"\([^)]*\)")


def _strip(text):
    text = _PAREN.sub(" ", text)
    cut = text.find(";")
    return (text if cut < 0 else text[:cut]).strip().upper()


def _numbers(value):
    """[numbers] for "200" / "200:210", None for anything else (an expression, empty)."""
    if value is None or value == "":
        return None
    out = []
    for part in value.split(":"):
        try:
            out.append(float(part))
        except ValueError:
            return None
    return out


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _params(rest):
    out = {}
    for m in _PARAM.finditer(rest):
        out.setdefault(m.group(1), m.group(2))
    return out


def _command(word, number, params, tool):
    """The command dict (without line / text) or None when the line is not a temperature command that sets something."""
    if word == "M" and number in (104, 109):
        key = "S" if "S" in params else ("R" if number == 109 and "R" in params else None)
        if key is None:
            return None
        t = _int(params["T"]) if "T" in params else tool
        return {"kind": "extruder", "tool": t if t is not None and t >= 0 else None, "bed": None, "temps": _numbers(params[key]), "code": "M%d" % number}
    if word == "G" and number == 10:
        if "P" not in params or "S" not in params:
            return None  # a tool offset (L) or a standby-only change
        return {"kind": "extruder", "tool": _int(params["P"]), "bed": None, "temps": _numbers(params["S"]), "code": "G10"}
    if word == "M" and number == 568:
        if "S" not in params:
            return None
        return {"kind": "extruder", "tool": _int(params["P"]) if params.get("P", "") != "" else tool, "bed": None,
                "temps": _numbers(params["S"]), "code": "M568"}
    if word == "M" and number in (140, 190):
        key = "S" if "S" in params else ("R" if number == 190 and "R" in params else None)
        if key is None:
            return None
        explicit = "H" in params and params.get("P", "") == ""
        bed = _int(params["P"]) if params.get("P", "") != "" else None
        return {"kind": "bed", "tool": None, "bed": bed, "temps": None if explicit else _numbers(params[key]), "code": "M%d" % number}
    if word == "M" and number in (141, 191):
        key = "S" if "S" in params else ("R" if number == 191 and "R" in params else None)
        if key is None:
            return None
        return {"kind": "chamber", "tool": None, "bed": None, "temps": _numbers(params[key]), "code": "M%d" % number}
    return None


def scan_lines(lines, max_commands=MAX_COMMANDS):
    commands, tool, truncated = [], None, False
    for n, raw in enumerate(lines, 1):
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "replace")
        if not _QUICK.match(raw):
            continue
        original = raw.decode("utf-8", "replace").rstrip("\r\n")
        text = _strip(original)
        m = _WORD.match(text)
        if not m:
            continue
        word, number = m.group(1), int(m.group(2))
        if word == "T":
            tool = number if number >= 0 else None
            continue
        found = _command(word, number, _params(text[m.end():]), tool)
        if found is None:
            continue
        if len(commands) >= max_commands:
            truncated = True
            break
        found.update(line=n, text=original[:LINE_CHARS])
        commands.append(found)
    return {"commands": commands, "truncated": truncated}


def scan_file(path, max_commands=MAX_COMMANDS):
    with open(path, "rb") as fh:
        return scan_lines(fh, max_commands)
