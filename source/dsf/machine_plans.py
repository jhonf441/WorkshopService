"""Planners of the phase 2 configuration kinds for machine.config.plan (Machine v2): G31, M208, M92, G10 (tool offsets).

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
The work offsets G54..G59.3 (G10 L2) have NO planner: they are the work zones of the Workbench (WorkshopWorkbench writes
`0:/sys/workshop/zones/p<N>.g`, one per system, with the laser <-> pointer correction inside; `workplaces.g` loads them at start-up).
Machine only reads them (machine.offsets.get) and keeps snapshots to compare. `M500` is not used and its behaviour is not assumed.
"""
import config_scan
import machine_config as mc
import machine_patch as pt

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


PLANNERS = {"config.g31": plan_g31, "config.m208": plan_m208, "config.m92": plan_m92, "config.g10": plan_g10}
