"""Configuration plans of Machine v2 (phase 1): `machine.config.plan` and `machine.config.apply` for the M671 line and bed.g.

plan   PURE: reads the files, builds the new text, returns the diff and the warnings and keeps the new text under a plan id for
       PLAN_TTL_S. Nothing is written. Kinds: config.m671 (the M671 line wherever it is: config.g or a macro it calls) and config.bed (the
       G30 points, tolerance and passes of bed.g, keeping everything else of the user's file).
apply  writes a plan through the existing `config.commit` of handlers/config.py (snapshot of the whole set first, sha check of every file,
       atomic swap with a journal), notes the result in the calibration history (machine_store, with the plan id as run_id) and, when asked,
       sends the new M671 to the board so it is valid without a restart. `M500` is never used (design 5.2).

Roles: the operation is a technician's; the kinds of machine_store that can hurt the hardware (permissions.MACHINE_ADMIN_KINDS: M208, M92,
M906/M913/M917, M569, M584) need an administrator. The registry decides from the ARGUMENT `kind` (permissions.ESCALATE_IN), so apply takes
`kind` as an argument and refuses a plan of another kind; the handler checks the role of the plan's kind again (defence in depth). This phase
plans M671, bed.g (phase 1) and, from phase 2 (machine_plans.py, patchers in machine_patch.py), G31, M208, M92, G10 tool offsets and work
offsets; M208 and M92 are administrator kinds. Kinds of later phases (M906...) still answer `not_implemented` at plan time.

The patchers are ports of the pure logic of the old Machine page (46-level-logic.js: tnvReplaceM671, tnvGenerateBedG, tnvMergeBedG, with the
regression cases of tests/level.test.js). They refuse to guess: bed.g with a structure they do not understand is reported as "newItem"
(the whole file would be replaced, with the reason) and the plan says so.
"""
import difflib
import hashlib
import json
import os
import re
import secrets
import threading
import time

import config_scan
import machine_geometry as geo
import machine_gcode
import permissions
from messages import M
from workshop_api import ApiError, Arg, MOTION, READ, Op

PLAN_TTL_S = 900
MAX_PLANS = 20
MAX_DIFF_LINES = 400
SUPPORTED = ("config.m671", "config.bed", "config.g31", "config.m208", "config.m92", "config.g10", "config.workplaces")
BED = "0:/sys/bed.g"
G28Z_LINE = "G28 Z ; levelling shifts the Z zero a little: home Z again"

_lock = threading.Lock()
_plans = {}


class PlanError(ValueError):
    """A plan cannot be made; .code is a short reason code, .field the argument at fault."""

    def __init__(self, code, field=""):
        super().__init__(code)
        self.code, self.field = code, field


# ---- small text helpers (ports of the tnv* helpers) ----

def g(v):
    return machine_gcode.num_text(v)


def _cut_comment(s):
    quoted = False
    for i, ch in enumerate(str(s)):
        if ch == '"':
            quoted = not quoted
        elif ch == ";" and not quoted:
            return str(s)[:i]
    return str(s)


_PARAM = re.compile(r"([A-Za-z])\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[-+]?(?:\d+\.?\d*|\.\d+)(?:\s*:\s*[-+]?(?:\d+\.?\d*|\.\d+))*)")


def params_of(code):
    c = re.sub(r"^\s*[GMT]\d+(?:\.\d+)?", "", str(code), flags=re.I)
    return {m.group(1).upper(): re.sub(r"\s+", "", m.group(2)) for m in _PARAM.finditer(c)}


def indent_of(s):
    return re.match(r"^[ \t]*", s).group(0)


def sha_of(data):
    return hashlib.sha256(data).hexdigest()


# ---- M671 ----

def line_m671(o):
    out = "M671 X%s Y%s" % (":".join(g(v) for v in o["x"]), ":".join(g(v) for v in o["y"]))
    if o.get("s") is not None:
        out += " S" + g(o["s"])
    if o.get("p") is not None:
        out += " P" + g(o["p"])
    if o.get("f") is not None and abs(o["f"] - 1) > 1e-9:
        out += " F" + g(o["f"])
    return out


def replace_m671(text, new, comment=""):
    """Changes the first M671 line (keeping its indentation and comment) or adds one after the last M584 / M667 / M669.
    {"text", "action": replaced | added | same, "line", "notices": [codes]}"""
    t = str(text or "")
    eol = "\r\n" if "\r\n" in t else "\n"
    ls = re.split(r"\r?\n", t)
    notices = []
    found = [n for n, ln in enumerate(ls) if re.match(r"^\s*M671\b", _cut_comment(ln), re.I)]
    if len(found) > 1:
        notices.append("several_m671")
    if found:
        n0 = found[0]
        old = ls[n0]
        com = old[len(_cut_comment(old)):]
        line = indent_of(old) + new + (" " + com.lstrip() if com else " ; " + comment if comment else "")
        if line == old:
            return {"text": t, "action": "same", "line": n0 + 1, "notices": notices}
        ls[n0] = line
        return {"text": eol.join(ls), "action": "replaced", "line": n0 + 1, "notices": notices}
    after = -1
    for n, ln in enumerate(ls):
        if re.match(r"^\s*M(584|667|669)\b", _cut_comment(ln), re.I):
            after = n
    line = new + (" ; " + comment if comment else "")
    if after < 0:
        notices.append("no_m584")
        end = len(ls) - 1 if ls and ls[-1] == "" else len(ls)
        ls.insert(end, line)
        return {"text": eol.join(ls), "action": "added", "line": end + 1, "notices": notices}
    ls.insert(after + 1, line)
    return {"text": eol.join(ls), "action": "added", "line": after + 2, "notices": notices}


# ---- bed.g ----

def gcode_pass(points, k=0, s=None):
    """The lines of one pass: G30 P0..P(n-1) X Y Z-99999 [K] and S<s> on the last one."""
    out = []
    for i, p in enumerate(points):
        line = "G30 P%d X%s Y%s Z-99999%s" % (i, g(p["x"]), g(p["y"]), " K%d" % k if k else "")
        if i == len(points) - 1:
            line += " S%d" % (len(points) if s is None else s)
        out.append(line)
    return out


def generate_bed_g(o):
    ix = o.get("idx") or {}
    xi, yi, zi = ix.get("X", 0), ix.get("Y", 1), ix.get("Z", 2)
    passes = max(1, min(10, int(round(o.get("passes") or 1))))
    tol = o.get("tol") or 0.01
    out = ["; bed.g -- gantry levelling (G32), generated by Machine" + (" on " + o["date"] if o.get("date") else ""),
           "; X Y = where the probe TOUCHES (RRF subtracts the G31 offset). One point near each M671 leadscrew.",
           "; Repeats until the measured deviation is below %s mm or %d pass(es)." % (g(tol), passes),
           "if !move.axes[%d].homed || !move.axes[%d].homed || !move.axes[%d].homed" % (xi, yi, zi), "  G28", "while true"]
    out += ["  " + ln for ln in gcode_pass(o["points"], o.get("k", 0), o.get("s"))]
    out += ["  if abs(move.calibration.initial.deviation) < %s || iterations >= %d" % (g(tol), passes - 1), "    break"]
    if o.get("rehome_z"):
        out.append(G28Z_LINE)
    return "\n".join(out) + "\n"


class _Merge:
    """The state of one merge (the `fb` object of tnvMergeBedG)."""


def _new_bed(o, reason):
    return {"mode": "newItem", "text": generate_bed_g(o), "reason": reason, "notices": []}


def _scan_bed(fb):
    whiles = []
    fb.pts, fb.s_idx, others = [], -1, 0
    for n, ln in enumerate(fb.ls):
        c = _cut_comment(ln).strip()
        if not c:
            continue
        if re.match(r"^while\b", c, re.I):
            whiles.append(n)
        if re.match(r"^G30\b", c, re.I):
            p = params_of(c)
            if "P" not in p:
                continue
            if fb.s_idx >= 0:
                if _int(p["P"]) == 0:
                    others += 1
                continue
            fb.pts.append(n)
            if "S" in p:
                fb.s_idx = n
    return whiles, others


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def merge_bed_g(text, o):
    """Puts the points / loop / Z homing of `o` into an existing bed.g WITHOUT touching the rest. Only the G30 set (points and S), the
    tolerance and the passes of the if / while already there (or adds them) and the G28 Z at the end change. If the structure is not
    understood: {"mode": "newItem", "text": complete new bed.g, "reason": code}.
    o = {points, k, s, passes, tol, rehome_z, idx, date}  ->  {"mode": "merge" | "newItem", "text", "reason", "notices": [codes]}"""
    t = str(text if text is not None else "")
    if not t.strip():
        return _new_bed(o, "")
    fb = _Merge()
    fb.eol = "\r\n" if "\r\n" in t else "\n"
    fb.ls = t.replace("\r", "").split("\n")
    fb.pas = max(1, min(10, int(round(o.get("passes") or 1))))
    fb.tol = o.get("tol") or 0.01
    fb.step = "\t" if any(ln.startswith("\t") for ln in fb.ls) else "  "
    whiles, others = _scan_bed(fb)
    if not fb.pts:
        return _new_bed(o, "no_g30")
    if fb.s_idx < 0:
        return _new_bed(o, "no_s")
    if others:
        return _new_bed(o, "several_sets")
    if len(whiles) > 1:
        return _new_bed(o, "several_whiles")
    fb.wi = whiles[0] if whiles else -1
    fb.end = -1
    if fb.wi >= 0:
        wind = len(indent_of(fb.ls[fb.wi]))
        fb.end = fb.wi
        for j in range(fb.wi + 1, len(fb.ls)):
            if not _cut_comment(fb.ls[j]).strip():
                continue
            if len(indent_of(fb.ls[j])) > wind:
                fb.end = j
            else:
                break
        if fb.pts[0] <= fb.wi or fb.s_idx > fb.end:
            return _new_bed(o, "points_outside_while")
    fb.L = [{"s": ln, "del": False, "after": [], "before": [], "sang": ""} for ln in fb.ls]
    fb.notices, fb.has_dev, fb.has_it = [], False, False
    _merge_loop(fb, o)
    _merge_final(fb, o)
    return {"mode": "merge", "text": fb.eol.join(fb.out), "reason": "", "notices": fb.notices}


def _merge_tolerance(fb):
    if fb.wi < 0:
        return
    for k in range(fb.wi, fb.end + 1):
        cod = _cut_comment(fb.ls[k])
        if not re.match(r"^\s*(if|elif|while)\b", cod, re.I):
            continue
        rest, nc = fb.ls[k][len(cod):], cod
        if re.search(r"deviation\)?\s*<=?\s*\d*\.?\d+", nc):
            fb.has_dev = True
            nc = re.sub(r"(deviation\)?\s*<=?\s*)\d*\.?\d+", lambda m: m.group(1) + g(fb.tol), nc, count=1)
        if re.search(r"iterations\s*(>=|>)\s*\d+", nc) and not re.match(r"^\s*while\b", nc, re.I):
            fb.has_it = True
            nc = re.sub(r"(iterations\s*)(?:>=|>)\s*\d+", lambda m: m.group(1) + ">= %d" % (fb.pas - 1), nc, count=1)
        elif re.match(r"^\s*while\b", nc, re.I) and re.search(r"iterations\s*(<=|<)\s*\d+", nc):
            fb.has_it = True
            nc = re.sub(r"(iterations\s*)(?:<=|<)\s*\d+", lambda m: m.group(1) + "< %d" % fb.pas, nc, count=1)
        fb.L[k]["s"] = nc + rest


def _merge_loop(fb, o):
    _merge_tolerance(fb)
    fb.base = indent_of(fb.ls[fb.pts[0]])
    wrap = fb.wi < 0 and fb.pas > 1
    new = gcode_pass(o["points"], o.get("k", 0), o.get("s"))
    for i, line in enumerate(new):
        if i < len(fb.pts):
            old = fb.ls[fb.pts[i]]
            com = old[len(_cut_comment(old)):]
            fb.L[fb.pts[i]]["s"] = indent_of(old) + line + (" " + com.lstrip() if com else "")
        else:
            fb.L[fb.s_idx]["after"].append(indent_of(fb.ls[fb.s_idx]) + line)
    for q in range(len(new), len(fb.pts)):
        fb.L[fb.pts[q]]["del"] = True
    queue = []
    ib = fb.base + fb.step if wrap else indent_of(fb.ls[fb.s_idx])
    if wrap:
        fb.L[fb.pts[0]]["before"].append(fb.base + "while true")
        for m in range(fb.pts[0], fb.s_idx + 1):
            fb.L[m]["sang"] = fb.step
        fb.L[fb.s_idx]["after"] = [fb.step + x for x in fb.L[fb.s_idx]["after"]]
    if wrap or fb.wi >= 0:
        missing = []
        if not fb.has_dev or wrap:
            missing.append("dev")
        if not fb.has_it or wrap:
            missing.append("it")
        if len(missing) == 2:
            queue += [ib + "if abs(move.calibration.initial.deviation) < %s || iterations >= %d" % (g(fb.tol), fb.pas - 1), ib + fb.step + "break"]
        elif missing and missing[0] == "dev":
            queue += [ib + "if abs(move.calibration.initial.deviation) < %s" % g(fb.tol), ib + fb.step + "break"]
        elif missing and missing[0] == "it":
            queue += [ib + "if iterations >= %d" % (fb.pas - 1), ib + fb.step + "break"]
    fb.L[fb.s_idx]["after"].extend(queue)


def _merge_final(fb, o):
    cap = fb.end if fb.wi >= 0 else fb.s_idx
    g28z = []
    for n in range(fb.s_idx + 1, len(fb.ls)):
        cg = _cut_comment(fb.ls[n]).strip()
        if re.match(r"^G28\b", cg, re.I) and re.search(r"\bZ", cg[3:], re.I) and not re.search(r"\b[XY]", cg[3:], re.I):
            g28z.append(n)
    if o.get("rehome_z") and not g28z:
        fb.L[cap]["after"].append((indent_of(fb.ls[fb.wi]) if fb.wi >= 0 else fb.base) + G28Z_LINE)
    elif not o.get("rehome_z") and g28z:
        for n in g28z:
            fb.L[n]["del"] = True
        fb.notices.append("g28z_removed")
    fb.out = []
    for e in fb.L:
        fb.out += e["before"]
        if not e["del"]:
            fb.out.append(e["sang"] + e["s"] if e["sang"] and e["s"].strip() else e["s"])
        fb.out += e["after"]
    if not (fb.wi >= 0 or fb.pas > 1):
        fb.notices.append("no_loop")


# ---- files of the SD (bytes: the sha of a file is the one of its bytes, like config.commit checks) ----

def read_bytes(path):
    import sd_paths
    try:
        with open(sd_paths.sd(path), "rb") as f:
            return f.read()
    except OSError:
        return None


def rel_of(path):
    return str(path)[2:].lstrip("/") if len(str(path)) > 1 and str(path)[1] == ":" else str(path).lstrip("/")


def _decode(data):
    if data is None:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise PlanError("not_utf8")


def _file_entry(path, before, after_text):
    old_text = _decode(before) or ""
    new = after_text.encode("utf-8")
    diff = list(difflib.unified_diff(old_text.replace("\r", "").split("\n"), after_text.replace("\r", "").split("\n"), "a/" + rel_of(path),
                                     "b/" + rel_of(path), lineterm="", n=2))
    return {"path": path, "rel": rel_of(path), "exists": before is not None, "sha_before": sha_of(before) if before is not None else None,
            "sha_after": sha_of(new), "new": new, "changed": new != (before or b"") or before is None, "diff": diff[:MAX_DIFF_LINES],
            "diff_cut": len(diff) > MAX_DIFF_LINES}


# ---- plans ----

def _number_list(values, key, lo, hi):
    v = values.get(key)
    if not isinstance(v, list) or not 2 <= len(v) <= 4 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi for x in v):
        raise PlanError("bad_value", key)
    return [float(x) for x in v]


def _opt(values, key, lo, hi):
    v = values.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise PlanError("bad_value", key)
    return float(v)


def plan_m671(values, env):
    o = {"x": _number_list(values, "x", -5000, 5000), "y": _number_list(values, "y", -5000, 5000), "s": _opt(values, "s", 0.01, 100),
         "p": _opt(values, "p", 0.01, 100), "f": _opt(values, "f", 0.01, 10)}
    if len(o["x"]) != len(o["y"]):
        raise PlanError("bad_value", "y")
    scan = config_scan.scan(env["read"])
    if not scan["read"]:
        raise PlanError("no_config")
    path = (scan["m671"][-1]["file"] if scan["m671"] else None) or _file_with_m584_z(scan, env["read"]) or config_scan.ROOT
    before = read_bytes(path)
    if before is None:
        raise PlanError("no_config")
    res = replace_m671(_decode(before), line_m671(o), "leadscrews")
    warnings = list(res["notices"])
    z = ((env.get("caps") or {}).get("capabilities") or {}).get("z_motors") or {}
    if z.get("count") and z["count"] != len(o["x"]):
        warnings.append("entries_differ_from_z_motors")
    if res["action"] == "same":
        warnings.append("nothing_changes")
    apply_line = dict(o, s=o["s"] if o["s"] is not None else 1.0, p=o["p"] if o["p"] is not None else 0.5, f=o["f"] if o["f"] is not None else 1.0)
    import machine_plans
    return {"files": [_file_entry(path, before, res["text"])], "warnings": warnings, "action": res["action"], "line": res["line"],
            "now": {"template": "m671_set", "numbers": apply_line}, "set": list(scan["files"]), "restart_needed": True,
            "before": machine_plans.m671_values(_decode(before)), "after": machine_plans.m671_values(res["text"])}


def _file_with_m584_z(scan, read):
    for path in scan["files"]:
        text = read(path) or ""
        for ln in text.splitlines():
            c = _cut_comment(ln)
            if re.match(r"^\s*M584\b", c, re.I) and re.search(r"\bZ\s*[\d\"]", re.sub(r"^\s*M584", "", c, flags=re.I), re.I):
                return path
    return None


def plan_bed(values, env):
    om = env["om"] or {}
    pts = values.get("points")
    if not isinstance(pts, list) or not 1 <= len(pts) <= geo.MAX_LEVEL_POINTS or not all(
            isinstance(p, dict) and set(p) == {"x", "y"} and all(isinstance(p[c], (int, float)) and not isinstance(p[c], bool) for c in "xy") for p in pts):
        raise PlanError("bad_value", "points")
    points = [{"x": float(p["x"]), "y": float(p["y"])} for p in pts]
    k = values.get("k", 0)
    if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= 15:
        raise PlanError("bad_value", "k")
    passes = values.get("passes", 1)
    if isinstance(passes, bool) or not isinstance(passes, int) or not 1 <= passes <= 10:
        raise PlanError("bad_value", "passes")
    tol = _opt(values, "tol", 0.001, 1.0) or 0.01
    caps_lev = (((env.get("caps") or {}).get("capabilities") or {}).get("levelling") or {})
    leadscrews = caps_lev.get("m671_entries") or 0
    s = values.get("s")
    s = leadscrews if s is None and leadscrews else (len(points) if s is None else s)
    if isinstance(s, bool) or not isinstance(s, int) or not -1 <= s <= 4:
        raise PlanError("bad_value", "s")
    errors = geo.validate_points(points, om, k, leadscrews=leadscrews)
    if errors:
        raise PlanError(errors[0]["code"], "points")
    ax = geo.axes_by_letter(om)
    letters = [a.get("letter") for a in ((om.get("move") or {}).get("axes") or []) if isinstance(a, dict)]
    idx = {c: letters.index(c) for c in "XYZ" if c in letters}
    o = {"points": points, "k": k, "s": s, "passes": passes, "tol": tol, "rehome_z": bool(values.get("rehome_z", False)), "idx": idx,
         "date": time.strftime("%Y-%m-%d %H:%M")}
    before = read_bytes(BED)
    res = merge_bed_g(_decode(before) if before is not None else "", o)
    warnings = list(res["notices"])
    if res["mode"] == "newItem" and before is not None:
        warnings += ["replaces_whole_file", "structure:" + res["reason"]]
    if not leadscrews:
        warnings.append("without_m671")
    entry = _file_entry(BED, before, res["text"])
    if not entry["changed"]:
        warnings.append("nothing_changes")
    return {"files": [entry], "warnings": warnings, "action": res["mode"], "line": None, "now": None, "set": ["0:/sys/config.g", BED]}


PLANNERS = {"config.m671": plan_m671, "config.bed": plan_bed}


def planners():
    """Every planner: the ones of this module and the phase 2 ones of machine_plans.py (imported late: it imports this module)."""
    import machine_plans
    import machine_plans_motion
    return dict(PLANNERS, **machine_plans.PLANNERS, **machine_plans_motion.PLANNERS)


def make_plan(kind, values, env, who=None, now=None):
    """Builds and stores a plan. PlanError for a kind that is not planned yet or values that are not valid."""
    table = planners()
    if kind not in table:
        raise PlanError("not_implemented" if kind in _all_kinds() else "unknown_kind", "kind")
    if not isinstance(values, dict):
        raise PlanError("bad_value", "values")
    body = table[kind](values, env)
    now = int(now if now is not None else time.time())
    plan = dict(body, id="p-%d-%s" % (now, secrets.token_hex(3)), kind=kind, ts=now, who=who or {}, values=values,
                role_needed=permissions.needed_role("machine.config.apply", {"args": {"kind": kind}}))
    with _lock:
        for pid in [p for p, v in _plans.items() if now - v["ts"] > PLAN_TTL_S]:
            _plans.pop(pid, None)
        while len(_plans) >= MAX_PLANS:
            _plans.pop(min(_plans, key=lambda p: _plans[p]["ts"]))
        _plans[plan["id"]] = plan
    return plan


def _all_kinds():
    import machine_store
    return machine_store.CONFIG_KINDS


def get_plan(plan_id, now=None):
    now = int(now if now is not None else time.time())
    with _lock:
        p = _plans.get(str(plan_id))
    return p if p and now - p["ts"] <= PLAN_TTL_S else None


def drop_plan(plan_id):
    with _lock:
        _plans.pop(str(plan_id), None)


def reset():
    """For the tests."""
    with _lock:
        _plans.clear()


def public(plan):
    """The plan as the page sees it: no new bytes, the diff lines."""
    files = [{k: f[k] for k in ("path", "exists", "sha_before", "sha_after", "changed", "diff", "diff_cut")} for f in plan["files"]]
    out = {"plan_id": plan["id"], "kind": plan["kind"], "files": files, "warnings": plan["warnings"], "action": plan["action"], "line": plan["line"],
           "role_needed": plan["role_needed"], "expires": plan["ts"] + PLAN_TTL_S, "can_apply_now": bool(plan["now"]),
           "before": plan.get("before"), "after": plan.get("after")}
    if plan.get("restore_of"):
        out["restore"] = plan["restore_of"]
    return out


# ---- apply ----

def stage(plan, owner, reason, who, rrf=""):
    """Writes the staging folder config.commit reads: the new files and manifest.json. Returns the transaction id."""
    import sd_paths
    tx = "mc-" + plan["id"][2:]
    base = sd_paths.sd("sys/workshop/data/config-staging/" + tx)
    entries, group = [], []
    for f in plan["files"]:
        dest = os.path.join(base, *f["rel"].split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(f["new"])
        entries.append({"path": f["rel"], "file": f["rel"], "sha": f["sha_after"], "sha_previous": f["sha_before"]})
    for p in plan.get("set") or []:
        if rel_of(p) not in group:
            group.append(rel_of(p))
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"files": entries, "set": group, "reason": reason, "who": who, "rrf": rrf, "mode": ""}, fh)
    return tx


def unstage(tx):
    """Removes the staging folder of a transaction that did not commit (config.commit removes it itself when it succeeds)."""
    import shutil
    import sd_paths
    shutil.rmtree(sd_paths.sd("sys/workshop/data/config-staging/" + tx), ignore_errors=True)


def commit(tx, owner, who):
    """Locks, commits and unlocks through the handler of config.commit. Returns its answer (dict)."""
    import api_ops
    api_ops.run_handler("config", {"C": "lock", "K": owner, "Q": who, "S": 60})
    try:
        return json.loads(api_ops.run_handler("config", {"C": "commit", "T": tx, "K": owner}))
    finally:
        try:
            api_ops.run_handler("config", {"C": "unlock", "K": owner})
        except Exception:  # noqa: BLE001
            pass


# ---- operations ----

def _env():
    import machine_ops as mo
    return {"read": mo.read_sd, "om": mo.model(), "caps": mo._caps(), "profile": mo.profile_block()}


def _plan_op(args, ctx):
    import identity
    who = identity.actor(ctx)
    try:
        plan = make_plan(args["kind"], args.get("values") or {}, _env(), who)
    except PlanError as e:
        if e.code in ("not_implemented", "unknown_kind"):
            raise ApiError("not_implemented" if e.code == "not_implemented" else "invalid_args", M("machine_config_kind_" + e.code, kind=args["kind"]), field="kind")
        raise ApiError("invalid_args", M("machine_config_plan_" + _msg_code(e.code), field=e.field), field="values." + e.field, reason=e.code)
    return public(plan)


def _msg_code(code):
    return code if code in ("no_config", "not_utf8", "bad_value", "no_points", "too_many_points", "too_few_points", "out_of_reach",
                            "duplicate_point", "no_limits", "patch_expression", "patch_unsupported_form", "patch_bad_axis",
                            "patch_missing_line", "current_over_limit", "bad_type", "no_frequency") else "other"


def _role_ok(ctx, kind):
    import identity
    need = permissions.needed_role("machine.config.apply", {"args": {"kind": kind}})
    have = identity.actor(ctx)["role"]
    return not have or permissions.RANK.get(have, -1) >= permissions.RANK[need], need


def _apply_op(args, ctx):
    import audit
    import identity
    import machine_ops as mo
    import machine_store
    plan = get_plan(args["plan_id"])
    if plan is None:
        raise ApiError("not_found", M("machine_config_plan_expired"), reason="plan_expired")
    if plan["kind"] != args["kind"]:
        raise ApiError("invalid_args", M("machine_config_plan_kind_mismatch", kind=plan["kind"]), field="kind", reason="kind_mismatch")
    ok, need = _role_ok(ctx, plan["kind"])
    if not ok:
        raise ApiError("forbidden", M("machine_config_needs_role", role=need), reason="role", needed_role=need)
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])
    if not any(f["changed"] for f in plan["files"]):
        raise ApiError("refused", M("machine_config_nothing_to_apply"), reason="nothing_to_apply")
    who = identity.actor(ctx)
    user, role = audit.actor(ctx)
    name = who["user"] or user
    tx = stage(plan, "machine-" + plan["id"], "Machine: %s (%s)" % (plan["kind"], name), name)
    try:
        done = commit(tx, "machine-" + plan["id"], name)
    except Exception as e:  # noqa: BLE001
        unstage(tx)
        raise ApiError("failed", M("machine_config_commit_failed", error=str(e)))
    if not done.get("ok"):
        unstage(tx)
        raise ApiError("conflict" if done.get("conflict") else "failed", done.get("error") or M("machine_config_commit_failed", error=""),
                       conflict=done.get("conflict"))
    drop_plan(plan["id"])
    applied = {"files": [{"path": f["rel"], "sha_before": f["sha_before"], "sha_after": f["sha_after"], "snapshot_id": done.get("snapshot")} for f in plan["files"]]}
    record_id = _record(plan, applied, who, machine_store, mo)
    out = {"applied": True, "snapshot": done.get("snapshot"), "files": done.get("files"), "record_id": record_id,
           "restart_needed": bool(plan.get("restart_needed", plan["kind"] == "config.m671"))}
    if args.get("apply_now") and plan.get("now"):
        out["now"] = _send_now(plan, mo)
    return out


def _record(plan, applied, who, machine_store, mo):
    results = {"warnings": plan["warnings"], "action": plan["action"], "line": plan["line"], "before": plan.get("before"), "after": plan.get("after")}
    if plan.get("restore_of"):
        results["restore_of"] = plan["restore_of"]
    try:
        for inputs in (_small(plan["values"]), {"cut": True}):
            rec = machine_store.make_record(plan["kind"], who, run_id=plan["id"], machine=machine_store.fingerprint_of(mo._caps()), inputs=inputs,
                                            results=results, applied=applied, state="done")
            try:
                return machine_store.append(rec)["id"]
            except machine_store.StoreError as e:
                if e.code != "too_large":
                    raise
        return None
    except Exception as e:  # noqa: BLE001 - the files are already written; a missing record must not hide that
        print("machine: could not store the record of %s: %s" % (plan["id"], e))
        return None


def _small(values):
    text = json.dumps(values, separators=(",", ":"))
    return values if len(text) < 1200 else {"cut": True}


def _send_now(plan, mo):
    """Sends the new values so they are valid at once (no restart); the file already has them for the next start."""
    lines = plan["now"].get("lines") or [(plan["now"]["template"], plan["now"]["numbers"])]
    try:
        replies = mo.geometry_send(lines)
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "error": str(e)[:120]}
    import machine_parsers
    errors = machine_parsers.find_errors("\n".join(replies))
    return {"sent": not errors, "error": errors[0]["text"] if errors else None}


def ops():
    S, O, B = "str", "obj", "bool"
    a = Arg
    kinds = ("config.m671 (values {x: [..], y: [..], s, p, f}), config.bed (values {points: [{x, y}], k, s, passes, tol, rehome_z}), "
             "config.g31 ({k, p, x, y, z}), config.m208 (admin; {axes: {X: {min, max}}}), config.m92 (admin; {axes: {X: steps}}), "
             "config.g10 ({tool, offsets: {X, Y, Z}}), config.workplaces ({systems: {\"1\": {X, Y, Z}}, target: macro | config})")
    return [
        Op("machine.config.plan", _plan_op, READ, {"kind": a(S, True, desc="Kind of change: " + kinds + "."),
                                                  "values": a(O, desc="The values of the kind.")},
           "Builds a change of the configuration WITHOUT writing anything: finds the file (config.g or a macro it calls for M671, bed.g), returns "
           "the exact diff, the warnings, the values before and after and a plan_id valid for 15 minutes. Kinds of later phases answer not_implemented.", log=False),
        Op("machine.config.apply", _apply_op, MOTION, {"plan_id": a(S, True, desc="Plan from machine.config.plan."),
                                                       "kind": a(S, True, desc="The kind of the plan (the role needed depends on it: the kinds that can hurt the hardware need an administrator)."),
                                                       "apply_now": a(B, desc="Also send the new M671 to the board so it is valid without a restart.")},
           "Writes a plan through config.commit (snapshot of the whole set first, sha check of every file, atomic swap), records it in the "
           "calibration history and, with apply_now, sends the M671 line. Refused with a job, a procedure running, or a file that changed "
           "since the plan. Needs a confirmation.", motion="geometry", confirm={"level": 3, "key": "machine.config.apply"}),
    ]
