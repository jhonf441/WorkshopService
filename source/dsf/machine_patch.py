"""Pure patchers of the configuration lines Machine v2 edits in phase 2: G31, M208, M92, G10 L1 (tool offsets) and G10 L2 (work offsets).

Every function takes the TEXT of a file and returns the new text, never touching the disk. Same contract as machine_config.replace_m671:

    {"text": new text, "action": "replaced" | "added" | "same", "line": 1-based line number of the change, "notices": [codes]}

Rules shared by all of them (design 5.2: "no magic writers"):
  - the line keeps its indentation, its spacing, its comment and the line endings of the file (CRLF stays CRLF);
  - only the tokens named in the change are touched; every other token of the line is left as the user wrote it;
  - a firmware command is "effective" in its LAST definition (a later line wins), so that is the one edited; more than one definition
    gives the notice "several_definitions" (the page shows it, nothing else is touched);
  - a token that is an expression (`X{global.foo}`) is never replaced: PatchError("expression");
  - M208 written with S (`M208 S1 X0`) is a different form that this module does not rewrite: PatchError("unsupported_form") when it holds
    an axis that has to change;
  - a missing line is ADDED after an anchor (the line that must precede it) or at the end of the file, with the notice "no_anchor".

`read_*` give back the values a text defines (the effective ones) in the same shape the planners take, so a plan can say what was there before.
`M500` is never written and never assumed (the reference says it stores G10 L2 in config-override.g; Machine does not rely on it).
"""
import re

import machine_gcode

AXIS_LETTERS = "XYZUVWABC"
# commands whose axis letter can carry one value per motor (`X80:80`): only the first is used by the firmware, so the notice is given
MULTI_VALUE_WORDS = ("M92", "M906", "M913", "M917", "M203", "M201", "M205", "M566")
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)"
_TOKEN = re.compile(r'"[^"]*"|(?<![A-Za-z0-9_.])([A-Za-z])(\{(?:[^{}]|\{[^{}]*\})*\}|"[^"]*"|%s(?::%s)*)' % (_NUM, _NUM))
_WORD = re.compile(r"^(\s*)([A-Za-z]\d+(?:\.\d+)?)")


class PatchError(ValueError):
    """The line cannot be edited safely; .code is a short reason code, .field the token (letter) at fault."""

    def __init__(self, code, field=""):
        super().__init__(code)
        self.code, self.field = code, field


# ---- lines and tokens ----

def split_comment(line):
    """(code, comment): the comment starts at the first `;` outside quotes and is returned with its `;`."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ";" and not quoted:
            return line[:i], line[i:]
    return line, ""


def command_word(code):
    """('G31', end index) of the first word of a code, or (None, 0)."""
    m = _WORD.match(code)
    return (m.group(2).upper(), m.end()) if m else (None, 0)


def tokens_of(code):
    """[(LETTER, text, start, end)] of the parameters after the command word (strings that are not a parameter are skipped)."""
    _, end = command_word(code)
    out = []
    for m in _TOKEN.finditer(code, end):
        if m.group(1):
            out.append((m.group(1).upper(), m.group(2), m.start(), m.end()))
    return out


def tmap(code):
    """{LETTER: text} of the LAST token of each letter."""
    return {t[0]: t[1] for t in tokens_of(code)}


def split_lines(text):
    t = str(text or "")
    return ("\r\n" if "\r\n" in t else "\n"), re.split(r"\r?\n", t)


def live_lines(ls):
    """[(index, code without comment)] of the lines that hold a command."""
    out = []
    for n, ln in enumerate(ls):
        code = split_comment(ln)[0]
        if code.strip():
            out.append((n, code))
    return out


def num_text(v):
    return machine_gcode.num_text(v)


def set_tokens(line, new):
    """The line with the tokens of `new` {LETTER: text} replaced (the LAST one of that letter) or appended before the comment."""
    code, comment = split_comment(line)
    toks = tokens_of(code)
    core = code.rstrip()
    trail = code[len(core):]
    todo, add = dict(new), []
    for letter, text in list(todo.items()):
        found = [t for t in toks if t[0] == letter]
        if not found:
            add.append(letter + text)
            continue
        _, old, start, end = found[-1]
        if old.startswith("{"):
            raise PatchError("expression", letter)
        core = core[:start] + code[start] + text + core[end:]
        code = core + trail
        toks = tokens_of(code)
    if add:
        core = core + " " + " ".join(add)
    return core + trail + comment


def _result(ls, eol, action, line, notices):
    return {"text": eol.join(ls), "action": action, "line": line, "notices": notices}


def _insert(ls, eol, new_line, anchor):
    """Puts new_line after the last line that satisfies anchor(code), else at the end; returns (index, notices)."""
    notices, at = [], -1
    if anchor is not None:
        for n, code in live_lines(ls):
            if anchor(code):
                at = n
    if at >= 0:
        ls.insert(at + 1, new_line)
        return at + 1, notices
    if anchor is not None:
        notices.append("no_anchor")
    end = len(ls) - 1 if ls and ls[-1] == "" else len(ls)
    ls.insert(end, new_line)
    return end, notices


def _with_comment(line, comment):
    return line + (" ; " + comment if comment else "")


# ---- one definition per key (G31, G10) ----

def _edit_one(text, select, tokens, make_new, anchor, comment):
    eol, ls = split_lines(text)
    cands = [n for n, code in live_lines(ls) if select(code)]
    notices = ["several_definitions"] if len(cands) > 1 else []
    if cands:
        n = cands[-1]
        new = set_tokens(ls[n], tokens)
        if new == ls[n]:
            return _result(ls, eol, "same", n + 1, notices)
        ls[n] = new
        return _result(ls, eol, "replaced", n + 1, notices)
    idx, more = _insert(ls, eol, _with_comment(make_new(), comment), anchor)
    return _result(ls, eol, "added", idx + 1, notices + more)


def _k_of(code):
    k = tmap(code).get("K")
    try:
        return int(float(k)) if k is not None else 0
    except ValueError:
        return -1


def is_g31(code, k):
    word, _ = command_word(code)
    t = tmap(code)
    return word == "G31" and _k_of(code) == k and any(c in t for c in "PXYZ")


def patch_g31(text, k, values, comment=""):
    """values = {"p", "x", "y", "z"} (the ones to set; numbers). The line `G31 K<k> P.. X.. Y.. Z..` of probe k."""
    tokens = {c.upper(): num_text(v) for c, v in values.items() if v is not None and c in "pxyz"}

    def anchor(code):
        word, _ = command_word(code)
        return word == "M558" and _k_of(code) == k

    def make_new():
        return "G31 K%d" % k + "".join(" %s%s" % (c, tokens[c]) for c in "PXYZ" if c in tokens)
    res = _edit_one(text, lambda c: is_g31(c, k), tokens, make_new, anchor, comment)
    if res["action"] == "added" and "no_anchor" in res["notices"]:
        # a G31 must come after the M558 of its probe: without one, any M558 is the next best place
        eol, ls = split_lines(res["text"])
        del ls[res["line"] - 1]
        idx, more = _insert(ls, eol, _with_comment(make_new(), comment), lambda c: command_word(c)[0] == "M558")
        res = _result(ls, eol, "added", idx + 1, ["no_m558_for_probe"] if "no_anchor" not in more else ["no_m558"])
    return res


def read_g31(text, k):
    """{"k", "p", "x", "y", "z"} (floats; a key is missing when the line lacks it) of the effective G31 of probe k, or None."""
    _, ls = split_lines(text)
    found = [code for _, code in live_lines(ls) if is_g31(code, k)]
    if not found:
        return None
    t = tmap(found[-1])
    out = {"k": k}
    for c in "pxyz":
        v = _float(t.get(c.upper()))
        if v is not None:
            out[c] = v
    return out


def _float(s):
    try:
        return float(s) if s is not None and ":" not in s and not s.startswith("{") else None
    except ValueError:
        return None


def _l_of(code):
    v = tmap(code).get("L")
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _p_of(code):
    v = _float(tmap(code).get("P"))
    return int(v) if v is not None else None


def is_tool_offset(code, tool):
    """G10 [L1] P<tool> with axis letters: a tool offset. Never a temperature (R / S) and never the bare G10 (a firmware retract)."""
    t = tmap(code)
    if command_word(code)[0] != "G10" or _p_of(code) != tool or not any(c in t for c in AXIS_LETTERS):
        return False
    return _l_of(code) in (None, 1.0) and not ({"R", "S"} & set(t))


def is_work_offset(code, system):
    return command_word(code)[0] == "G10" and _l_of(code) == 2.0 and _p_of(code) == system


def _axis_tokens(offsets):
    out = {}
    for letter, v in offsets.items():
        if letter not in AXIS_LETTERS:
            raise PatchError("bad_axis", letter)
        out[letter] = num_text(v)
    return out


def patch_tool_offset(text, tool, offsets, comment=""):
    """G10 L1 P<tool> X.. Y.. Z.. (offsets = {"X": v, ...}). A new line goes after the M563 of that tool."""
    tokens = _axis_tokens(offsets)

    def anchor(code):
        return command_word(code)[0] == "M563" and _p_of(code) == tool
    return _edit_one(text, lambda c: is_tool_offset(c, tool), tokens,
                     lambda: "G10 L1 P%d" % tool + "".join(" %s%s" % (c, tokens[c]) for c in AXIS_LETTERS if c in tokens), anchor, comment)


def read_tool_offset(text, tool):
    _, ls = split_lines(text)
    found = [code for _, code in live_lines(ls) if is_tool_offset(code, tool)]
    return {c: _float(v) for c, v in tmap(found[-1]).items() if c in AXIS_LETTERS and _float(v) is not None} if found else None


def patch_work_offset(text, system, offsets, comment=""):
    """G10 L2 P<system> X.. Y.. Z.. (system 1..9 = G54..G59.3). A new line goes after the last G10 L2 line, else at the end."""
    tokens = _axis_tokens(offsets)

    def anchor(code):
        return command_word(code)[0] == "G10" and _l_of(code) == 2.0
    return _edit_one(text, lambda c: is_work_offset(c, system), tokens,
                     lambda: "G10 L2 P%d" % system + "".join(" %s%s" % (c, tokens[c]) for c in AXIS_LETTERS if c in tokens), anchor, comment)


def read_work_offsets(text):
    """{system: {LETTER: float}} of the effective G10 L2 lines."""
    _, ls = split_lines(text)
    out = {}
    for _, code in live_lines(ls):
        if command_word(code)[0] == "G10" and _l_of(code) == 2.0 and _p_of(code) is not None:
            vals = {c: _float(v) for c, v in tmap(code).items() if c in AXIS_LETTERS and _float(v) is not None}
            out.setdefault(_p_of(code), {}).update(vals)
    return out


# ---- one letter per axis on a shared line (M208, M92) ----

def patch_axes(text, word, axes, forbid=None, anchor_words=(), comment=""):
    """axes = {LETTER: token text} for the command `word` (M208: "0:350", M92: "80"). Each letter is edited in the last line that holds it;
    letters found nowhere are appended to the last usable line, or become a new line after the last anchor word. A line holding the
    parameter `forbid` (M208 with S) is not rewritten: an axis that has to change in it is PatchError("unsupported_form")."""
    eol, ls = split_lines(text)
    mine = [(n, code) for n, code in live_lines(ls) if command_word(code)[0] == word]
    blocked = [n for n, code in mine if forbid and forbid in tmap(code)]
    usable = [n for n, code in mine if n not in blocked]
    notices, changed, missing = [], [], {}
    for letter, tok in axes.items():
        if any(letter in tmap(split_comment(ls[n])[0]) for n in blocked):
            raise PatchError("unsupported_form", letter)
        cands = [n for n in usable if letter in tmap(split_comment(ls[n])[0])]
        if len(cands) > 1 and "several_definitions" not in notices:
            notices.append("several_definitions")
        if not cands:
            missing[letter] = tok
            continue
        n = cands[-1]
        if ":" in tmap(split_comment(ls[n])[0])[letter] and word in MULTI_VALUE_WORDS:
            notices.append("multi_driver_value")
        new = set_tokens(ls[n], {letter: tok})
        if new != ls[n]:
            ls[n] = new
            changed.append(n)
    if missing and usable:
        n = usable[-1]
        ls[n] = set_tokens(ls[n], missing)
        changed.append(n)
    elif missing:
        line = _with_comment(word + "".join(" %s%s" % (c, t) for c, t in missing.items()), comment)
        idx, more = _insert(ls, eol, line, (lambda c: command_word(c)[0] in anchor_words) if anchor_words else None)
        return _result(ls, eol, "added", idx + 1, notices + more)
    if not changed:
        return _result(ls, eol, "same", (usable or [0])[-1] + 1, notices)
    return _result(ls, eol, "replaced", min(changed) + 1, notices)


def patch_m208(text, limits, comment=""):
    """limits = {"X": (min, max)}: `M208 X<min>:<max>`."""
    return patch_axes(text, "M208", {c: "%s:%s" % (num_text(lo), num_text(hi)) for c, (lo, hi) in limits.items()}, forbid="S",
                      anchor_words=("M584", "M669", "M667"), comment=comment)


def patch_m92(text, steps, comment=""):
    """steps = {"X": steps per mm}: `M92 X<v>`. Several drivers on an axis need ONE value (reference: only the first is used)."""
    return patch_axes(text, "M92", {c: num_text(v) for c, v in steps.items()}, anchor_words=("M350", "M584"), comment=comment)


def read_axes(text, word):
    """{LETTER: token text} of the effective (last) definition of each axis of `word`; S-form M208 lines are left out."""
    _, ls = split_lines(text)
    out = {}
    for _, code in live_lines(ls):
        if command_word(code)[0] != word:
            continue
        t = tmap(code)
        if word == "M208" and "S" in t:
            continue
        for c, v in t.items():
            if c in AXIS_LETTERS + "E":
                out[c] = v
    return out


def read_m208(text):
    """{LETTER: {"min", "max"}} of the lines `M208 X<min>:<max>`."""
    out = {}
    for c, v in read_axes(text, "M208").items():
        parts = v.split(":")
        if len(parts) == 2 and _float(parts[0]) is not None and _float(parts[1]) is not None:
            out[c] = {"min": float(parts[0]), "max": float(parts[1])}
    return out


def read_m92(text):
    out = {}
    for c, v in read_axes(text, "M92").items():
        f = _float(v.split(":")[0])
        if f is not None:
            out[c] = f
    return out
