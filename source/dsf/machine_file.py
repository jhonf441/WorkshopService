"""`sys/workshop/machine.g`: the file where the workshop writes what it CREATES in the configuration (tools, bed heaters), and the one call that
`sys/config.g` makes to it.

Design and decisions of the owner: informes/rediseno-ui-service/arquitectura/CAMBIO-CONFIG-INCLUDE.md.

    machine.g      a header and one managed block per thing created, `; >>> WORKSHOP hook=machine.tool.3 v=1 sha=1a2b3c4d` ... `; <<< WORKSHOP hook=machine.tool.3`
                   (the same markers native_merge uses: the viewer already draws them). What the person writes outside the blocks is never touched.
    config.g       ONE block (hook `machine`, the three lines native_merge writes: `if fileexists(...)` + `M98 P"0:/sys/workshop/machine.g"`), put at the END of
                   the file but BEFORE the last `M501` (what `M500` saved must win over what machine.g defines) and before a `M99` / `M2` / `M0` that ends the file.
    modes          a block may exist in some modes only. Its body is then wrapped, in machine.g itself, in
                       if exists(global.selectedMode)
                           if global.selectedMode == "FFF" || global.selectedMode == "Laser"
                               <the lines>
                   `global.selectedMode` is set by the `boot` hook (modestate.g + automodeselect.g) before machine.g runs. No modes = every mode, no wrapper.
                   `modes_of` reads them back from the wrapper, so the file is the one source of truth (the object model only shows the tools of the mode running).

Pure: the functions take and return bytes or text, nothing here reads the SD except `create`, which gets the reader of the environment of the plan.
"""
import re

import mode_paths
import native_merge as nm

REL = "sys/workshop/machine.g"
ROOT = "0:/" + REL
CONFIG = "0:/sys/config.g"
KINDS = ("tool", "bed")
MODES = tuple(mode_paths.MODE_FILES)          # ("Laser", "CNC", "FFF"): the values of global.selectedMode
HOOK = nm.Hook("machine", "sys/config.g", ROOT)
HEADER = [
    "; machine.g -- what the workshop creates in the machine (tools, bed heaters). config.g calls this file once, near its end.",
    "; Every block between the >>> and <<< lines belongs to the Machine page: change it there. Your own lines go outside the blocks.",
]
_ID = re.compile(r"^machine\.(tool|bed)\.(\d{1,3})$")
_MODE = re.compile(r'==\s*"([A-Za-z]+)"')
_GUARD = "if global.selectedMode"
_CUT = ("M99", "M2", "M0", "M1")
_IND = "    "


class MachineFileError(ValueError):
    """code: block_exists, block_edited, hook_edited, hook_broken, file_broken, not_utf8, bad_modes."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def clean_modes(modes):
    """None (every mode) or the sorted tuple of the modes asked for. Raises MachineFileError('bad_modes') for a mode that does not exist."""
    if modes is None or modes == "all" or modes == []:
        return None
    if not isinstance(modes, (list, tuple)) or not all(isinstance(m, str) and m in MODES for m in modes):
        raise MachineFileError("bad_modes")
    got = tuple(sorted(set(modes), key=MODES.index))
    return None if len(got) == len(MODES) else got


def block_id(kind, number):
    return "machine.%s.%d" % (kind, number)


def body_lines(lines, modes):
    """The lines of a block as they go into the file: wrapped for some modes, as they are for all."""
    modes = clean_modes(modes)
    if modes is None:
        return list(lines)
    cond = " || ".join('global.selectedMode == "%s"' % m for m in modes)
    return ["if exists(global.selectedMode)", _IND + "if " + cond] + [_IND * 2 + l if l.strip() else l for l in lines]


def modes_of(body):
    """The modes a block body is restricted to (tuple), or None when it is for every mode."""
    for l in body[:3]:
        s = l.strip()
        if s.startswith(_GUARD):
            found = tuple(m for m in _MODE.findall(s) if m in MODES)
            return found or None
    return None


def block_lines(kind, number, lines, modes=None):
    """The managed block (markers, hash, body) as a list of lines without end of line."""
    bid, body = block_id(kind, number), body_lines(lines, modes)
    head = "; >>> WORKSHOP hook=%s v=1 sha=%s  (managed block: change it in the Machine page, or outside these lines)" % (bid, nm.body_sha(body))
    return [head] + body + ["; <<< WORKSHOP hook=%s" % bid]


def parse(data):
    """The blocks of machine.g: [{id, kind, number, modes, start, end, edited}] and `broken` (a marker without its pair). Never raises on odd text."""
    if data is None:
        return {"blocks": [], "broken": False, "exists": False}
    try:
        lines, _bom, _eol = nm.split_bytes(data)
    except nm.MergeError:
        raise MachineFileError("not_utf8")
    found, broken = nm.find_blocks(lines)
    out = []
    for hid, s, e, _v, sha in found:
        m = _ID.match(hid)
        if not m or s is None or e is None:
            continue
        body = [l.rstrip("\r\n") for l in lines[s + 1:e]]
        out.append({"id": hid, "kind": m.group(1), "number": int(m.group(2)), "modes": modes_of(body), "start": s, "end": e, "edited": nm.body_sha(body) != sha})
    return {"blocks": out, "broken": broken, "exists": True}


def add_block(data, kind, number, lines, modes=None):
    """New bytes of machine.g with the block of the thing at the end (the file is created with its header when `data` is None). The block of the
    same id must not exist (a creation never overwrites). Keeps BOM and the style of line endings."""
    if kind not in KINDS:
        raise MachineFileError("bad_kind")
    if data is None:
        lines_old, bom, eol = [], b"", "\n"
        new = [l + eol for l in HEADER]
    else:
        got = parse(data)
        if got["broken"]:
            raise MachineFileError("file_broken")
        if any(b["id"] == block_id(kind, number) for b in got["blocks"]):
            raise MachineFileError("block_exists", block_id(kind, number))
        lines_old, bom, eol = nm.split_bytes(data)
        new = list(lines_old)
        if new and not new[-1].endswith("\n"):
            new[-1] += eol
        if new and new[-1].strip():
            new.append(eol)                    # one blank line between what is there and the block
    new += [l + eol for l in block_lines(kind, number, lines, modes)]
    return nm.join_bytes(new, bom)


def hook_index(lines):
    """Where the call goes in config.g: before the last top-level `M501`; else before a `M99` / `M2` / `M0` that ends the file; else at the end.
    Returns (index, note) with note None, 'before_m501' or 'before_stop'."""
    live = [(i, nm.strip_comment(l)) for i, l in enumerate(lines) if l[:1] not in (" ", "\t") and nm.strip_comment(l)]
    last501 = None
    for i, code in live:
        if code.split()[0].upper() == "M501":
            last501 = i
    if last501 is not None:
        return last501, "before_m501"
    if live and live[-1][1].split()[0].upper() in _CUT:
        return live[-1][0], "before_stop"
    return len(lines), None


def plan_hook(config):
    """(new bytes of config.g or None when nothing changes, state, note). States: 'same' (block there), 'manual' (a line of the person already calls
    machine.g: it is left as it is), 'inserted'. Raises MachineFileError('hook_edited' / 'hook_broken') when the block is there but was changed or its markers
    do not pair (nothing is guessed), and ('no_config') when config.g is not there: it is never created."""
    if config is None:
        raise MachineFileError("no_config")
    f = nm.classify(config, HOOK)
    if f.state == nm.BLOCK_OK:
        return None, "same", None
    if f.state == nm.TARGET_REFERENCED:
        return None, "manual", None
    if f.state in (nm.BLOCK_EDITED, nm.BLOCK_OUTDATED):
        raise MachineFileError("hook_edited", f.detail or "")
    if f.state in (nm.MARKERS_BROKEN, nm.UNREADABLE):
        raise MachineFileError("hook_broken", f.detail or "")
    lines, bom, eol = nm.split_bytes(config)
    at, note = hook_index(lines)
    new = list(lines)
    if at == len(new) and new and not new[-1].endswith("\n"):
        new[-1] += eol
    new[at:at] = nm.with_eol(HOOK.block_lines(), eol)
    return nm.join_bytes(new, bom), "inserted", note


def create(mc, scan, kind, number, lines, modes=None):
    """`mc` is the module machine_config (passed in: this module is below it). What a plan that CREATES writes: {files: [entries for machine.g and, when the call is not there yet, config.g], warnings: [...], set: [paths],
    action, line}. `scan` = config_scan.scan(read) of the configuration (the caller scans it: this module stays out of config_scan). Raises MachineFileError."""
    if not scan["read"]:
        raise MachineFileError("no_config")
    before_m = mc.read_bytes(ROOT)
    new_m = add_block(before_m, kind, number, lines, modes)
    before_c = mc.read_bytes(CONFIG)
    new_c, state, note = plan_hook(before_c)
    files = [mc.file_entry(ROOT, before_m, new_m.decode("utf-8"))]
    warnings = []
    if before_m is None:
        warnings.append("machine_file_new")
    if new_c is not None:
        files.append(mc.file_entry(CONFIG, before_c, new_c.decode("utf-8-sig")))
        warnings.append("machine_hook_added")
        if note:
            warnings.append("machine_hook_" + note)
    elif state == "manual":
        warnings.append("machine_hook_manual")
    group = list(scan["files"]) + ([ROOT] if ROOT not in scan["files"] else [])
    mine = [b for b in parse(new_m)["blocks"] if b["id"] == block_id(kind, number)]
    return {"files": files, "warnings": warnings, "set": group, "action": "inserted", "line": mine[0]["start"] + 1}


def plan_error(mc, e, kind):
    """The PlanError of a MachineFileError (machine_config's codes: the page and the catalog know them)."""
    code = {"bad_modes": ("bad_value", "modes"), "bad_kind": ("bad_value", "kind"), "block_exists": (kind + "_exists", "number" if kind == "tool" else "beds"),
            "no_config": ("no_config", ""), "not_utf8": ("not_utf8", ""), "file_broken": ("machine_file_broken", ""),
            "hook_edited": ("machine_hook_edited", ""), "hook_broken": ("machine_hook_broken", "")}.get(e.code, ("other", ""))
    return mc.PlanError(code[0], code[1])


def plan_body(mc, scan, kind, number, built, modes, warning):
    """The body of a plan that creates `built` (build_lines of the tool or the beds): machine.g (and config.g the first time) instead of the file that
    held the last definition. `warning` = the restart notice of the kind."""
    try:
        got = create(mc, scan, kind, number, built["lines"], modes)
    except MachineFileError as e:
        raise plan_error(mc, e, kind)
    return {"files": got["files"], "warnings": got["warnings"] + [warning], "action": got["action"], "line": got["line"], "now": None, "set": got["set"],
            "before": None, "after": built["summary"], "restart_needed": True}


def preview_files(mc):
    """The files a creation would write, as `sys/...` paths: machine.g, and config.g while it does not call machine.g yet (or cannot be read: the plan says so)."""
    try:
        new_c = plan_hook(mc.read_bytes(CONFIG))[0]
    except MachineFileError:
        new_c = None
    return [REL] + (["sys/config.g"] if new_c is not None else [])


def modes_problem(spec):
    """None, or the error {code, field} of the `modes` of a spec (the previews answer it instead of raising)."""
    try:
        clean_modes(spec.get("modes") if isinstance(spec, dict) else None)
    except MachineFileError:
        return {"code": "values", "field": "modes"}
    return None
