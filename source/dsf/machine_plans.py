"""Planners of the phase 2 configuration kinds for machine.config.plan (Machine v2): G31, M208, M92, G10 (tool offsets), work offsets.

Each planner is pure like the ones of machine_config.py: it reads the files, builds the new text with the patchers of machine_patch.py and returns
the plan body (files with their diff, warnings, action) WITHOUT writing. `machine_config.make_plan` stores it under a plan id and
`machine.config.apply` writes it through `config.commit`. Besides the body every planner returns

    before / after   the values of the kind as they were / will be, in the SAME shape the planner takes as `values` (so
                     machine.history.restore can feed them back to the planner), or None when the line does not exist yet
    restart_needed   True: the file is read again at the next start (config.g), `apply_now` makes the change valid at once
    now              {"lines": [(template, numbers), ...]} volatile G-code sent by apply_now (closed list of machine_gcode)

Kinds and values:
    config.g31         {k?: 0-15, p?: 0-1023, x?, y?, z?}                                   technician
    config.m208        {axes: {"X": {min, max}, ...}}                                       ADMIN (permissions.MACHINE_ADMIN_KINDS)
    config.m92         {axes: {"X": steps per mm, ...}}                                     ADMIN
    config.g10         {tool: 0-49, offsets: {"X": v, "Y": v, "Z": v}}                      technician (G10 L1)
    config.workplaces  {systems: {"1": {"X": v, ...}, ...}, target?: "macro" | "config"}    technician (G10 L2)
The persistence helper of the work offsets (`target` "macro", default) writes `0:/sys/workshop-offsets.g` and makes sure config.g calls it;
`M500` is not used and its behaviour is not assumed.
"""
import config_scan
import machine_config as mc
import machine_patch as pt

WORK_MACRO = "0:/sys/workshop-offsets.g"
WORK_CALL = 'M98 P"workshop-offsets.g"'
MACRO_HEADER = "; workshop-offsets.g -- work offsets G54..G59.3 (G10 L2), written by Machine. Called from config.g with M98.\n"
MAX_TOOL = 49


def _bad(field):
    return mc.PlanError("bad_value", field)


def _number(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        raise _bad(field)
    return float(v)


def _axis_map(values, key, build, letters=pt.AXIS_LETTERS):
    """{LETTER: build(raw, field)} of values[key]; at least one axis, only the letters allowed (the axes; M92 also takes E)."""
    raw = values.get(key)
    if not isinstance(raw, dict) or not raw:
        raise _bad(key)
    out = {}
    for letter, v in raw.items():
        if not isinstance(letter, str) or len(letter) != 1 or letter.upper() not in letters:
            raise _bad(key + "." + str(letter))
        out[letter.upper()] = build(v, key + "." + letter)
    return out


def _edit(env, finder, patcher):
    """(path, before bytes, result of patcher(text), scan, files holding the definition): picks the LAST file of the configuration that
    already has the definition, else config.g."""
    scan = config_scan.scan(env["read"])
    if not scan["read"]:
        raise mc.PlanError("no_config")
    hits = [p for p in scan["files"] if finder(env["read"](p) or "")]
    path = hits[-1] if hits else config_scan.ROOT
    before = mc.read_bytes(path)
    if before is None:
        raise mc.PlanError("no_config")
    try:
        res = patcher(mc._decode(before))
    except pt.PatchError as e:
        raise mc.PlanError("patch_" + e.code, e.field)
    return path, before, res, scan, hits


def _body(path, before, res, scan, hits, now_lines, before_v, after_v):
    warnings = list(res["notices"])
    if len(hits) > 1:
        warnings.append("defined_in_several_files")
    if res["action"] == "same":
        warnings.append("nothing_changes")
    return {"files": [mc._file_entry(path, before, res["text"])], "warnings": warnings, "action": res["action"], "line": res["line"],
            "now": {"lines": now_lines} if now_lines else None, "set": list(scan["files"]), "before": before_v, "after": after_v,
            "restart_needed": True}


# ---- G31 ----

def plan_g31(values, env):
    k = values.get("k", 0)
    if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= 15:
        raise _bad("k")
    new = {}
    for key, lo, hi in (("p", 0, 1023), ("x", -500, 500), ("y", -500, 500), ("z", -20, 100)):
        if values.get(key) is not None:
            new[key] = _number(values[key], lo, hi, key)
    if not new:
        raise _bad("values")
    path, before, res, scan, hits = _edit(env, lambda t: pt.read_g31(t, k) is not None, lambda t: pt.patch_g31(t, k, new, "probe %d" % k))
    after_v = pt.read_g31(res["text"], k)
    now = None
    if after_v and all(c in after_v for c in "pxyz"):
        now = [("g31_set", {"k": k, "trig": int(after_v["p"]), "x": after_v["x"], "y": after_v["y"], "z": after_v["z"]})]
    old = pt.read_g31(mc._decode(before), k)
    body = _body(path, before, res, scan, hits, now, old, after_v)
    if res["action"] == "added":
        body["warnings"].append("new_line_resets_defaults")        # a new G31 starts from the firmware defaults for what is not given
    return body


# ---- M208 / M92 (administrator) ----

def _limit(v, field):
    if not isinstance(v, dict) or set(v) != {"min", "max"}:
        raise _bad(field)
    lo, hi = _number(v["min"], -5000, 5000, field + ".min"), _number(v["max"], -5000, 5000, field + ".max")
    if lo >= hi:
        raise _bad(field)
    return (lo, hi)


def plan_m208(values, env):
    limits = _axis_map(values, "axes", _limit)
    path, before, res, scan, hits = _edit(env, lambda t: bool(set(pt.read_m208(t)) & set(limits)),
                                         lambda t: pt.patch_m208(t, limits, "limits"))
    pick = lambda text: {c: v for c, v in pt.read_m208(text).items() if c in limits}                  # noqa: E731
    old = pick(mc._decode(before))
    now = [("limits_set", {"axis": c, "lo": lo, "hi": hi}) for c, (lo, hi) in limits.items()]
    return _body(path, before, res, scan, hits, now, {"axes": old} if old else None, {"axes": pick(res["text"])})


def plan_m92(values, env):
    steps = _axis_map(values, "axes", lambda v, f: _number(v, 0.01, 99999, f), pt.AXIS_LETTERS + "E")
    path, before, res, scan, hits = _edit(env, lambda t: bool(set(pt.read_m92(t)) & set(steps)), lambda t: pt.patch_m92(t, steps, "steps per mm"))
    pick = lambda text: {c: v for c, v in pt.read_m92(text).items() if c in steps}                     # noqa: E731
    old = pick(mc._decode(before))
    now = [("steps_set", {"axis": c, "v": v}) for c, v in steps.items()]
    body = _body(path, before, res, scan, hits, now, {"axes": old} if old else None, {"axes": pick(res["text"])})
    if any(c in old and not 0.5 <= steps[c] / old[c] <= 2 for c in steps if old.get(c)):
        body["warnings"].append("big_change")
    return body


# ---- G10: tool offsets (L1) ----

def plan_g10(values, env):
    tool = values.get("tool")
    if isinstance(tool, bool) or not isinstance(tool, int) or not 0 <= tool <= MAX_TOOL:
        raise _bad("tool")
    offsets = _axis_map(values, "offsets", lambda v, f: _number(v, -1000, 1000, f))
    path, before, res, scan, hits = _edit(env, lambda t: pt.read_tool_offset(t, tool) is not None,
                                         lambda t: pt.patch_tool_offset(t, tool, offsets, "tool %d" % tool))
    pick = lambda text: {c: v for c, v in (pt.read_tool_offset(text, tool) or {}).items() if c in offsets}   # noqa: E731
    old = pick(mc._decode(before))
    now = [("g10_tool_axis", {"tool": tool, "axis": c, "v": v}) for c, v in offsets.items()]
    return _body(path, before, res, scan, hits, now, {"tool": tool, "offsets": old} if old else None, {"tool": tool, "offsets": pick(res["text"])})


# ---- G10: work offsets (L2) ----

def _systems(values):
    raw = values.get("systems")
    if not isinstance(raw, dict) or not raw:
        raise _bad("systems")
    out = {}
    for key, offs in raw.items():
        try:
            n = int(key)
        except (TypeError, ValueError):
            raise _bad("systems." + str(key))
        if not 1 <= n <= 9 or str(n) != str(key) or not isinstance(offs, dict) or not offs:
            raise _bad("systems." + str(key))
        out[n] = _axis_map({"o": offs}, "o", lambda v, f: _number(v, -99999, 99999, f))
    return out


def _work_pick(text, systems):
    cur = pt.read_work_offsets(text)
    return {str(n): {c: v for c, v in cur.get(n, {}).items() if c in systems[n]} for n in systems if n in cur}


def _patch_all(text, systems):
    notices, action, line = [], "same", None
    for n in sorted(systems):
        r = pt.patch_work_offset(text, n, systems[n], "G%s" % (53 + n if n <= 6 else "59.%d" % (n - 6)))
        text = r["text"]
        notices += [x for x in r["notices"] if x not in notices]
        if r["action"] != "same" and action != "added":
            action = r["action"]
        line = line or (r["line"] if r["action"] != "same" else None)
    return {"text": text, "action": action, "line": line or 1, "notices": notices}


def _ensure_call(root_text, scan_calls):
    """config.g text with the M98 of the macro: before an M501 line if there is one, else at the end."""
    if WORK_MACRO.lower() in scan_calls:
        return root_text, False
    eol, ls = pt.split_lines(root_text)
    at = next((n for n, code in pt.live_lines(ls) if pt.command_word(code)[0] == "M501"), None)
    if at is None:
        end = len(ls) - 1 if ls and ls[-1] == "" else len(ls)
        ls.insert(end, WORK_CALL + " ; work offsets (Machine)")
    else:
        ls.insert(at, WORK_CALL + " ; work offsets (Machine)")
    return eol.join(ls), True


def plan_workplaces(values, env):
    systems = _systems(values)
    target = values.get("target", "macro")
    if target not in ("macro", "config"):
        raise _bad("target")
    scan = config_scan.scan(env["read"])
    if not scan["read"]:
        raise mc.PlanError("no_config")
    if target == "config":
        return _plan_work_in_config(systems, env, values)
    root_before = mc.read_bytes(config_scan.ROOT)
    macro_before = mc.read_bytes(WORK_MACRO)
    macro_old = mc._decode(macro_before) if macro_before is not None else ""
    inline = [p for p in scan["files"] if p.lower() != WORK_MACRO.lower() and pt.read_work_offsets(env["read"](p) or "")]
    try:
        res = _patch_all(macro_old if macro_before is not None else MACRO_HEADER, systems)
    except pt.PatchError as e:
        raise mc.PlanError("patch_" + e.code, e.field)
    files = [mc._file_entry(WORK_MACRO, macro_before, res["text"])]
    calls = {c.lower() for p in scan["files"] for c in config_scan.scan_text(env["read"](p) or "", p)["calls"]}
    root_text, call_added = _ensure_call(mc._decode(root_before), calls)
    if call_added:
        files.append(mc._file_entry(config_scan.ROOT, root_before, root_text))
    warnings = list(res["notices"]) + (["also_in_config"] if inline else []) + (["config_calls_macro"] if call_added else [])
    if not any(f["changed"] for f in files):
        warnings.append("nothing_changes")
    now = [("g10_work_axis", {"n": n, "axis": c, "v": v}) for n in sorted(systems) for c, v in systems[n].items()]
    return {"files": files, "warnings": warnings, "action": "added" if macro_before is None else res["action"], "line": res["line"],
            "now": {"lines": now}, "set": list(scan["files"]) + [WORK_MACRO], "before": _wrap_work(_work_pick(macro_old, systems)),
            "after": _wrap_work(_work_pick(res["text"], systems)), "restart_needed": True}


def _wrap_work(systems):
    return {"systems": systems} if systems else None


def _plan_work_in_config(systems, env, values):
    path, before, res, scan, hits = _edit(env, lambda t: any(n in pt.read_work_offsets(t) for n in systems), lambda t: _patch_all(t, systems))
    now = [("g10_work_axis", {"n": n, "axis": c, "v": v}) for n in sorted(systems) for c, v in systems[n].items()]
    return _body(path, before, res, scan, hits, now, _wrap_work(_work_pick(mc._decode(before), systems)), _wrap_work(_work_pick(res["text"], systems)))


# ---- M671 (phase 1 planner): the values before / after, so it can be restored ----

def m671_values(text):
    """{x, y, s?, p?, f?} of the last M671 line of a text, or None."""
    _, ls = pt.split_lines(text)
    found = [code for _, code in pt.live_lines(ls) if pt.command_word(code)[0] == "M671"]
    if not found:
        return None
    t = pt.tmap(found[-1])
    try:
        out = {c.lower(): [float(x) for x in t[c].split(":")] for c in "XY" if c in t}
        out.update({c.lower(): float(t[c]) for c in "SPF" if c in t})
    except ValueError:
        return None
    return out if "x" in out and "y" in out else None


PLANNERS = {"config.g31": plan_g31, "config.m208": plan_m208, "config.m92": plan_m92, "config.g10": plan_g10, "config.workplaces": plan_workplaces}
