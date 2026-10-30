"""Pure patchers of the motion-parameter lines Machine v2 edits in phase 3 (design 2.6 / 2.8): M556, M425, M593, M906 / M913 / M917,
M203 / M201 / M205 / M566 and the BASIC parameters of M569 (direction S, driver mode D).

Same contract as machine_patch.py (text in, text out, never the disk): the line keeps its spacing, comment and line endings, only the tokens named in
the change are touched, the LAST definition is the effective one (`several_definitions`), an expression token is never replaced, a missing line is
added after an anchor.

M569 is the only careful one. This module changes ONLY the tokens `S` and `D` of a line that already exists for that driver: it never adds a line,
never touches `R`, `T`, `F`, `B`, `Y`, `C`, `H`, `V`, `U` or any chopper register, never edits a line of closed loop (`D4` / `D5`) and never sees
`M569.1`, `M569.2`, `M569.0` (they are different command words and are left alone). A missing line is PatchError("missing_line").
"""
import re

import machine_patch as pt

LETTERS = pt.AXIS_LETTERS + "E"
# where a new line goes (after the last line of one of these words); no anchor = the end of the file with the notice no_anchor
ANCHORS = {"M556": ("M566", "M201", "M203", "M92"), "M425": ("M556", "M566", "M201", "M203", "M92"), "M593": ("M425", "M556", "M566", "M201", "M203"),
           "M906": ("M350", "M584"), "M913": ("M906", "M350"), "M917": ("M913", "M906"), "M203": ("M201", "M92", "M584"),
           "M201": ("M203", "M92", "M584"), "M205": ("M566", "M201", "M203"), "M566": ("M201", "M203", "M92")}
COMMENTS = {"M556": "skew", "M425": "backlash", "M593": "input shaping", "M906": "motor current", "M913": "motor current percent",
            "M917": "standstill current percent", "M203": "maximum speeds", "M201": "accelerations", "M205": "job jerk", "M566": "jerk"}
DRIVER_MODES = {"spreadcycle": 2, "stealthchop": 3}
MODE_NAMES = {2: "spreadcycle", 3: "stealthchop"}
_DRIVER = re.compile(r"^(?:([0-9]{1,3})\.)?([0-9]{1,2})$")
_BASIC_PARAMS = ("S", "D")                      # the ONLY tokens of M569 this module writes


def _first_float(text):
    return pt._float(str(text).split(":")[0]) if text is not None and not str(text).startswith("{") else None


def read_letters(text, word, letters=LETTERS + "ITSPF", skip_with=None):
    """{LETTER: float} of the effective (last) definition of each letter of `word`. The first value of `X80:80`. Lines holding the token
    `skip_with` (M203 with S: other units) are left out."""
    _, ls = pt.split_lines(text)
    out = {}
    for _, code in pt.live_lines(ls):
        if pt.command_word(code)[0] != word:
            continue
        t = pt.tmap(code)
        if skip_with and skip_with in t:
            continue
        for c, v in t.items():
            f = _first_float(v)
            if c in letters and f is not None:
                out[c] = f
    return out


def patch_word(text, word, tokens):
    """tokens = {LETTER: text}. M203 with an S token (mm/s units) is not rewritten (unsupported_form for the axis)."""
    return pt.patch_axes(text, word, tokens, forbid="S" if word == "M203" else None, anchor_words=ANCHORS.get(word, ()), comment=COMMENTS.get(word, ""))


# ---- M593 ----

def patch_m593(text, shaper, frequency=None, damping=None):
    """`M593 P"zvd" F43.5 S0.1`. `none` writes only P; the other tokens of the line are left as they are."""
    tokens = {"P": '"%s"' % shaper}
    if frequency is not None:
        tokens["F"] = pt.num_text(frequency)
    if damping is not None:
        tokens["S"] = pt.num_text(damping)
    return pt.patch_axes(text, "M593", tokens, anchor_words=ANCHORS["M593"], comment=COMMENTS["M593"])


def read_m593(text):
    """{"type", "frequency", "damping"} of the effective M593 line (a key is missing when the line lacks it), or None."""
    _, ls = pt.split_lines(text)
    found = [pt.tmap(code) for _, code in pt.live_lines(ls) if pt.command_word(code)[0] == "M593"]
    if not found:
        return None
    t = found[-1]
    out = {}
    if t.get("P", "").startswith('"'):
        out["type"] = t["P"].strip('"').lower()
    for key, c in (("frequency", "F"), ("damping", "S")):
        v = _first_float(t.get(c))
        if v is not None:
            out[key] = v
    return out or None


# ---- M569 (basic parameters only) ----

def norm_driver(p):
    """'0.1' -> '0.1', '2' -> '0.2' (a driver without a board number is on board 0), None when it is not a driver id."""
    m = _DRIVER.match(str(p))
    return "%s.%s" % (m.group(1) or "0", m.group(2)) if m else None


def _m569_lines(ls, driver):
    return [n for n, code in pt.live_lines(ls) if pt.command_word(code)[0] == "M569" and norm_driver(pt.tmap(code).get("P")) == driver]


def patch_m569(text, driver, changes):
    """changes = {"S": "1", "D": "3"} (only those two letters). The line of that driver must exist; otherwise PatchError("missing_line")."""
    if set(changes) - set(_BASIC_PARAMS):
        raise pt.PatchError("bad_param", sorted(set(changes) - set(_BASIC_PARAMS))[0])
    eol, ls = pt.split_lines(text)
    cands = _m569_lines(ls, driver)
    if not cands:
        raise pt.PatchError("missing_line", "P")
    n = cands[-1]
    code = pt.split_comment(ls[n])[0]
    d = _first_float(pt.tmap(code).get("D"))
    if "D" in changes and d is not None and int(d) not in MODE_NAMES:
        raise pt.PatchError("unsupported_form", "D")        # closed loop or the old off-time modes: not ours to rewrite
    notices = ["several_definitions"] if len(cands) > 1 else []
    new = pt.set_tokens(ls[n], changes)
    if new == ls[n]:
        return {"text": text, "action": "same", "line": n + 1, "notices": notices}
    ls[n] = new
    return {"text": eol.join(ls), "action": "replaced", "line": n + 1, "notices": notices}


def read_m569(text):
    """{driver: {"direction": 0|1|None, "mode": "spreadcycle"|"stealthchop"|"other"|None}} of the effective line of each driver."""
    _, ls = pt.split_lines(text)
    out = {}
    for _, code in pt.live_lines(ls):
        if pt.command_word(code)[0] != "M569":
            continue
        t = pt.tmap(code)
        drv = norm_driver(t.get("P"))
        if drv is None:
            continue
        s, d = _first_float(t.get("S")), _first_float(t.get("D"))
        row = out.setdefault(drv, {"direction": None, "mode": None})
        if s is not None:
            row["direction"] = int(s)
        if d is not None:
            row["mode"] = MODE_NAMES.get(int(d), "other")
    return out
