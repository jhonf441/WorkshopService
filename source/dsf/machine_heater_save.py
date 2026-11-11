"""Save to the configuration what the bed zones calibration found: plan kinds `config.heater_model` (the M307 of each bed heater) and
`config.heater_cap` (its M143 cap) of machine.config.plan / machine.config.apply (technician, like every other kind: exact diff of each file, snapshot of
the whole set first, sha check, history, rollback; the machine restarts to read them). Nothing here talks to the board: after a tuning the board already
holds the new model (M303 leaves it in use), the file is what a restart reads.

values of config.heater_model = {heaters: [{heater, r, k, kf, d, s, v?, b?, e?}]}   r heating rate, k cooling rate, kf fan cooling rate, d dead time,
    s max PWM 0..1, v calibration voltage (0 = leave it out), b 1 = on/off instead of PID, e the exponent (kept as it is in an existing line)
values of config.heater_cap   = {heaters: [{heater, max}]}                         max 30..150 C (the range of the assistant)
Only BED heaters (`heat.bedHeaters` of the object model) are accepted: the kind cannot touch the cap or the model of a hotend. An existing line is changed
token by token (the rest of the line and its comment stay); when there is none the line is added after the M143 / M950 of that heater. A letter that holds
an expression (`R{...}`) is never rewritten. A cap that goes UP is allowed but warned (`cap_raised`).
"""
import re

import machine_config as mc
import machine_patch as pt
import machine_tool as mt

MAX_HEATERS = 16
HEATER_DEFINITION = re.compile(r'^\s*M950\s+H\d+\s+C"(?!nil")')  # a definition that creates the heater (C"nil" deletes it)
CAP_RANGE = (30.0, 150.0)
RANGES = {"r": (0.001, 100.0), "k": (0.0, 5.0), "kf": (0.0, 5.0), "d": (0.0, 60.0), "s": (0.0, 1.0), "v": (0.0, 60.0), "e": (0.1, 3.0)}


def _whole(text):
    return int(text) if text is not None and re.match(r"^-?[0-9]+$", str(text)) else None


def _number(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        raise mc.PlanError("bad_value", field)
    return float(v)


def _heaters(values, om, key):
    """The list of the request with each heater checked to be a bed heater, no repeats."""
    raw = values.get(key)
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_HEATERS or any(not isinstance(x, dict) for x in raw):
        raise mc.PlanError("bad_value", key)
    slots = [h for h in (((om or {}).get("heat") or {}).get("bedHeaters") or []) if isinstance(h, int) and h >= 0]
    out, seen = [], set()
    for i, x in enumerate(raw):
        h = x.get("heater")
        field = "%s[%d].heater" % (key, i)
        if isinstance(h, bool) or not isinstance(h, int) or h < 0 or h in seen:
            raise mc.PlanError("bad_value", field)
        if h not in slots:
            raise mc.PlanError("not_bed_heater", field)
        seen.add(h)
        out.append((i, h, x))
    return out


def _fix(v, places):
    return "%.*f" % (places, v)


def _model_tokens(x, i):
    f = "heaters[%d]." % i
    r, k = _number(x.get("r"), *RANGES["r"], f + "r"), _number(x.get("k"), *RANGES["k"], f + "k")
    kf = _number(x.get("kf", 0.0), *RANGES["kf"], f + "kf")
    d, s = _number(x.get("d"), *RANGES["d"], f + "d"), _number(x.get("s", 1.0), *RANGES["s"], f + "s")
    v = _number(x.get("v", 0.0), *RANGES["v"], f + "v")
    b = x.get("b", 0)
    if b not in (0, 1) or isinstance(b, bool):
        raise mc.PlanError("bad_value", f + "b")
    tokens = {"R": _fix(r, 3), "K": "%s:%s" % (_fix(k, 3), _fix(kf, 3)), "D": _fix(d, 2), "S": _fix(s, 2), "B": str(b)}
    if v > 0:
        tokens["V"] = _fix(v, 1)
    if x.get("e") is not None:
        tokens["E"] = _fix(_number(x["e"], *RANGES["e"], f + "e"), 2)
    return tokens


def _is_live(word, code, h, p_ok=None):
    p = pt.tmap(code)
    return pt.command_word(code)[0] == word and _whole(p.get("H")) == h and (p_ok is None or p_ok(p))


def _find(texts, word, h, p_ok=None):
    """(file index, line index) of the LAST live line of `word` for heater h in the files (the one the firmware keeps), or None."""
    hit = None
    for fi, (_, text) in enumerate(texts):
        _, ls = pt.split_lines(text)
        for n, code in pt.live_lines(ls):
            if _is_live(word, code, h, p_ok):
                hit = (fi, n)
    return hit


def _anchor(texts, h):
    """(file index, line index) after which a new M307 / M143 goes: the last M143 of the heater, else its M950 definition; None when neither exists."""
    cap, defn = None, None
    for fi, (_, text) in enumerate(texts):
        _, ls = pt.split_lines(text)
        for n, code in pt.live_lines(ls):
            if _is_live("M143", code, h):
                cap = (fi, n)
            elif _is_live("M950", code, h) and HEATER_DEFINITION.match(code):
                defn = (fi, n)
    return cap or defn


def _apply(texts, edits):
    """The new texts after the edits [(word, h, tokens, p_ok, new line)]; returns (list of new texts, first changed line per file, notices)."""
    new = [pt.split_lines(t) for _, t in texts]
    lines = [list(ls) for _, ls in new]
    first, notices = {}, []
    for word, h, tokens, p_ok, make in edits:
        hit = _find([(p, "\n".join(ls)) for (p, _), ls in zip(texts, lines)], word, h, p_ok)
        try:
            if hit:
                fi, n = hit
                changed = pt.set_tokens(lines[fi][n], tokens)
                if changed != lines[fi][n]:
                    lines[fi][n] = changed
                    first[fi] = min(first.get(fi, n + 1), n + 1)
                continue
            anchor = _anchor([(p, "\n".join(ls)) for (p, _), ls in zip(texts, lines)], h)
        except pt.PatchError as e:
            raise mc.PlanError("patch_" + e.code, e.field)
        if anchor is None:
            raise mc.PlanError("no_heater_line", "H%d" % h)
        fi, n = anchor
        lines[fi].insert(n + 1, make)
        first[fi] = min(first.get(fi, n + 2), n + 2)
        notices.append("line_added")
    return [(eol_ls[0].join(ls)) for eol_ls, ls in zip(new, lines)], first, notices


def _files(texts, out, first):
    files, line = [], None
    for fi, (path, _) in enumerate(texts):
        before = mc.read_bytes(path)
        if before is None:
            raise mc.PlanError("no_config")
        if out[fi].encode("utf-8") != before:
            files.append(mc.file_entry(path, before, out[fi]))
            line = first[fi] if line is None else line
    return files, line


def _result(texts, env, files, line, notices, before, after):
    warnings = list(notices) + (["restart"] if files else ["nothing_changes"])
    return {"files": files, "warnings": warnings, "action": "replaced" if files else "same", "line": line, "now": None,
            "set": [p for p, _ in texts], "before": before, "after": after, "restart_needed": True}


def plan_heater_model(values, env):
    """The files with the M307 of each heater set to the numbers given."""
    texts = mt.config_texts(env["read"])
    if not texts:
        raise mc.PlanError("no_config")
    todo = _heaters(values, env.get("om"), "heaters")
    edits, after = [], {}
    for i, h, x in todo:
        tokens = _model_tokens(x, i)
        line = "M307 H%d R%s K%s D%s E%s S%s%s B%s" % (h, tokens["R"], tokens["K"], tokens["D"], tokens.get("E", "1.35"), tokens["S"],
                                                    " V" + tokens["V"] if "V" in tokens else "", tokens["B"])
        edits.append(("M307", h, tokens, None, line))
        after[str(h)] = line
    out, first, notices = _apply(texts, edits)
    files, line = _files(texts, out, first)
    return _result(texts, env, files, line, notices, None, after)


def plan_heater_cap(values, env):
    """The files with the M143 cap of each heater set to `max` (the line without P: the cap, not a monitor)."""
    texts = mt.config_texts(env["read"])
    if not texts:
        raise mc.PlanError("no_config")
    todo = _heaters(values, env.get("om"), "heaters")
    edits, after, before, notices = [], {}, {}, []
    no_p = lambda p: p.get("P") in (None, "0")  # noqa: E731 - a monitor (P1 / P2) is not the cap
    for i, h, x in todo:
        cap = _number(x.get("max"), CAP_RANGE[0], CAP_RANGE[1], "heaters[%d].max" % i)
        old = _find(texts, "M143", h, no_p)
        if old:
            s = pt.tmap(pt.split_lines(texts[old[0]][1])[1][old[1]]).get("S")
            before[str(h)] = s
            try:
                if s is not None and float(s) < cap:
                    notices.append("cap_raised")
            except ValueError:
                pass
        edits.append(("M143", h, {"S": mc.g(cap)}, no_p, "M143 H%d S%s" % (h, mc.g(cap))))
        after[str(h)] = mc.g(cap)
    out, first, more = _apply(texts, edits)
    files, line = _files(texts, out, first)
    return _result(texts, env, files, line, notices + more, before, after)


PLANNERS = {"config.heater_model": plan_heater_model, "config.heater_cap": plan_heater_cap}
