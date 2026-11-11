"""Safe merge of the link blocks into the Duet-native files (SD layout, phase 5). Design: TallerPlugins `docs-internal/SD-LAYOUT.md`
section D (tiers and hook block) and F (phases 4 and 5). Operator script: `docs/sd-fase45-guion.md`.

What it does, and nothing else
    A workshop plugin never edits the logic of a native file. It asks for ONE marked block that only CALLS a macro the workshop owns:

        ; >>> WORKSHOP hook=daemon-tail v=1 sha=1a2b3c4d  (managed block: change the file outside these lines)
        if fileexists("0:/sys/workshop/hooks/daemon-tail.g")
            M98 P"0:/sys/workshop/hooks/daemon-tail.g"
        ; <<< WORKSHOP hook=daemon-tail

    `sha=` is the first 8 hex of the sha256 of the BODY lines (the lines between the two markers, LF-normalised). The design text says "the
    three block lines"; a hash cannot cover the line that holds it, so the markers are checked by their own regex and the body by the hash.

Tiers (a closed list, enforced when a Hook is built)
    T0  never touched (pause, resume, cancel, stop, homex, homey, bed, mesh, deployprobe, retractprobe, resurrect*, tpre/tpost/tfree, ...)
    T1  daemon.g, homeall.g, homez.g   one block, the file is created only for daemon.g
    T2  config.g                        one block; a missing config.g is NEVER created

Safety rules implemented here
    * `plan_install` / `plan_remove` / `dry_run` are PURE: they read through an injected `read(rel)` and return text and diffs. They never write.
    * `apply_plan` is the only function that writes. It refuses when the board is busy, when the file moved since the plan (sha), when the plan
      needs an acceptance that was not given, and it checks the result by re-reading it. The write is atomic (fs_atomic).
    * The bytes of the file are kept: BOM, CRLF or LF (new lines use the file's own style), lines over 255 characters are reported, never cut.
    * Idempotent: a second install of a good block changes nothing; a second removal changes nothing.

Dependency declared (NOT implemented here): the manifest is written by branch `sd-fase1`. This module needs from it ONLY a list of hook
declarations, see `Hook.from_dict` and `hooks_from_manifest` (key `hooks`). Until that exists, `DEFAULT_HOOKS` is the interim table.

CLI (dry-run is the default and the only thing that cannot write):
    python native_merge.py --root <copy-of-or-real-sd> [--remove] [--only sys/daemon.g] [--adopted id,id]
"""
import difflib
import hashlib
import os
import re
import sys

BOM = b"\xef\xbb\xbf"
LONG_LINE = 255          # DSF cuts lines over this length (note in cancel.g)

# ---- the closed list of tiers ----

TIER1_FILES = ("sys/daemon.g", "sys/homeall.g", "sys/homez.g")
TIER2_FILES = ("sys/config.g",)
CREATE_IF_ABSENT = ("sys/daemon.g",)     # the only one that may be created
TIER0_NAMES = frozenset((
    "pause.g", "resume.g", "cancel.g", "stop.g", "start.g", "homex.g", "homey.g", "bed.g", "mesh.g", "deployprobe.g", "retractprobe.g",
    "resurrect.g", "resurrect-prologue.g", "tpre.g", "tpost.g", "tfree.g", "filament-change.g", "load.g", "unload.g", "filament-error.g",
    "driver-stall.g", "driver-error.g", "heater-fault.g"))

_START = re.compile(r"^[ \t]*;[ \t]*>>>[ \t]*WORKSHOP[ \t]+hook=(\S+)[ \t]+v=(\d+)[ \t]+sha=([0-9a-fA-F]{8})")
_END = re.compile(r"^[ \t]*;[ \t]*<<<[ \t]*WORKSHOP[ \t]+hook=(\S+)")

# states of a file for one hook
ABSENT_FILE = "absent-file"
NO_BLOCK = "no-block"
BLOCK_OK = "block-ok"                    # markers fine, body hash fine, body equal to the wanted one
BLOCK_OUTDATED = "block-outdated"        # markers and hash fine, but it is not the text this release wants (hook version changed)
BLOCK_EDITED = "block-edited"            # body hash does not match the header: somebody changed the inside
MARKERS_BROKEN = "markers-broken"        # one marker only, two blocks of the same hook, wrong order, nested
LEGACY_LINE = "legacy-line"              # the old unmarked line(s) are there
TARGET_REFERENCED = "target-referenced"  # no markers but an active line already calls the hook macro: the person manages it
USER_ADOPTED = "user-adopted"            # the registry says the person took the line over
LEGACY_NESTED = "legacy-nested"          # the old line is inside an if/while: replacing it would change the logic around it
LEGACY_SCATTERED = "legacy-scattered"    # the old lines are not together (code between them) or the group has an indented body after it
UNREADABLE = "unreadable"


class MergeError(Exception):
    pass


class Stale(MergeError):
    """The file changed between the plan and the apply."""


class Busy(MergeError):
    pass


class NeedsAccept(MergeError):
    pass


# ---- the declaration of a hook ----

class Hook:
    """One hook. `target` is the macro of the workshop the block calls (absolute `0:/` path). `legacy` lists what the owner's file has today and
    the block replaces IN PLACE: a string is one top-level line (regex on the active text), a list is a group of consecutive lines (the first at
    column 0, the others may be indented, for example `if` plus its body)."""

    def __init__(self, id, file, target, tier=None, version=1, legacy=(), create_if_absent=None, requires=()):
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", str(id)):
            raise MergeError("bad hook id: %r" % (id,))
        file = str(file).replace("\\", "/").lstrip("/")
        base = file.rsplit("/", 1)[-1].lower()
        if base in TIER0_NAMES or re.match(r"^(tpre|tpost|tfree|trigger|deployprobe|retractprobe)[0-9]*\.g$", base) or base.startswith("resurrect"):
            raise MergeError("tier 0 file, never touched: %s" % file)
        if file in TIER1_FILES:
            real = 1
        elif file in TIER2_FILES:
            real = 2
        else:
            raise MergeError("file not allowed for a hook: %s (T1: %s; T2: %s)" % (file, ", ".join(TIER1_FILES), ", ".join(TIER2_FILES)))
        if tier is not None and int(tier) != real:
            raise MergeError("tier %s does not match the file %s (it is T%d)" % (tier, file, real))
        if not re.match(r'^0:/[^"\r\n]{1,150}$', str(target)):
            raise MergeError("target must be an absolute 0:/ path: %r" % (target,))
        self.id, self.file, self.tier, self.target = str(id), file, real, str(target)
        self.version = int(version)
        self.legacy = [list(g) if isinstance(g, (list, tuple)) else [g] for g in legacy]
        self.create = (file in CREATE_IF_ABSENT) if create_if_absent is None else bool(create_if_absent) and file in CREATE_IF_ABSENT
        self._legacy_re = [[re.compile(p, re.I) for p in g] for g in self.legacy]
        # what the target macro must CALL (active lines) for the block to be a faithful replacement of the legacy lines: regexes
        self.requires = [str(r) for r in (requires or ())]
        self._requires_re = [re.compile(r, re.I) for r in self.requires]

    @property
    def target_rel(self):
        return self.target[3:]

    def target_problem(self, data):
        """None when the macro the block calls exists and contains every call the block takes over from the legacy lines; else a short reason.
        Without this the block would call nothing and the replaced line (a safety call such as the jog failsafe) would be lost."""
        if data is None:
            return "the macro %s is not on the SD" % self.target
        try:
            lines = data.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            return "the macro %s is not UTF-8 text" % self.target
        active = [strip_comment(l) for l in lines]
        missing = [r.pattern for r in self._requires_re if not any(r.search(a) for a in active)]
        if missing:
            return "the macro %s does not contain the call %s" % (self.target, ", ".join(missing))
        return None

    @classmethod
    def from_dict(cls, d):
        """Declaration as the manifest of sd-fase1 will carry it: {id, file, target, tier?, version?, legacy?: [str | [str...]]}."""
        return cls(d["id"], d["file"], d["target"], d.get("tier"), d.get("version", 1), d.get("legacy") or (), requires=d.get("requires") or ())

    def body_lines(self):
        return ['if fileexists("%s")' % self.target, '    M98 P"%s"' % self.target]

    def body_sha(self, lines=None):
        return body_sha(self.body_lines() if lines is None else lines)

    def block_lines(self):
        body = self.body_lines()
        head = "; >>> WORKSHOP hook=%s v=%d sha=%s  (managed block: change the file outside these lines)" % (self.id, self.version, self.body_sha(body))
        return [head] + body + ["; <<< WORKSHOP hook=%s" % self.id]


def hooks_from_manifest(manifest):
    """The `hooks` list of a plugin manifest (interface with sd-fase1). Missing key = no hooks."""
    return [Hook.from_dict(d) for d in ((manifest or {}).get("hooks") or [])]


# Interim table until the manifest of sd-fase1 carries `hooks`. The macros named here are the ones the design says the workshop owns under
# 0:/sys/workshop/hooks/. `legacy` is what the real machine has today (shapes seen in the repo's fixture of the owner's files).
DEFAULT_HOOKS = (
    Hook("daemon-tail", "sys/daemon.g", "0:/sys/workshop/hooks/daemon-tail.g", legacy=[r'^M98\s+P"[^"]*jogFreeFailsafe\.g"'],
         requires=[r"jogFreeFailsafe\.g"]),
    Hook("homeall-tail", "sys/homeall.g", "0:/sys/workshop/hooks/homeall-tail.g", legacy=[r'^M98\s+P"[^"]*zbedref\.g"'],
         requires=[r"zbedref\.g"]),
    Hook("homez-tail", "sys/homez.g", "0:/sys/workshop/hooks/homez-tail.g", legacy=[r'^M98\s+P"[^"]*zbedref\.g"'],
         requires=[r"zbedref\.g"]),
    Hook("boot", "sys/config.g", "0:/sys/workshop/hooks/boot.g", legacy=[
        # the old layout (sys/) and the one after phase 4 (sys/workshop/modes, sys/workshop/data) are both recognised
        [r"^if\s+!exists\(global\.selectedMode\)", r'^M98\s+P"0:/sys/(?:workshop/data/)?modestate\.g"'],
        r'^M98\s+P"0:/sys/(?:workshop/modes/)?automodeselect\.g"',
        r'^M98\s+P"0:/sys/workshop/macros/work/workplaces\.g"'],
         requires=[r"modestate\.g", r"automodeselect\.g", r"workplaces\.g"]),
)


# ---- text helpers ----

def body_sha(lines):
    return hashlib.sha256("\n".join(l.rstrip("\r\n") for l in lines).encode("utf-8")).hexdigest()[:8]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def strip_comment(line):
    out, quoted = [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            break
        out.append(ch)
    return "".join(out).strip()


def _split(data):
    """bytes -> (lines with their endings, bom bytes, eol of the file). Raises MergeError when it is not UTF-8."""
    bom = BOM if data.startswith(BOM) else b""
    try:
        text = data[len(bom):].decode("utf-8")
    except UnicodeDecodeError:
        raise MergeError("not UTF-8 text")
    lines = text.splitlines(True)
    crlf = sum(1 for l in lines if l.endswith("\r\n"))
    lf = sum(1 for l in lines if l.endswith("\n") and not l.endswith("\r\n"))
    return lines, bom, ("\r\n" if crlf > lf else "\n")


def _join(lines, bom):
    return bom + "".join(lines).encode("utf-8")


def _blocks(lines):
    """[(id, start, end or None, version, sha)] plus broken flag. Pairs are matched by id; a start of another id inside an open block is broken."""
    found, broken, open_ = [], False, {}
    for i, l in enumerate(lines):
        m = _START.match(l)
        if m:
            if open_:
                broken = True
            if m.group(1) in open_:
                broken = True
            open_[m.group(1)] = (i, int(m.group(2)), m.group(3).lower())
            continue
        m = _END.match(l)
        if m:
            hid = m.group(1)
            if hid not in open_:
                broken = True
                found.append((hid, None, i, None, None))
                continue
            s, v, h = open_.pop(hid)
            found.append((hid, s, i, v, h))
    for hid, (s, v, h) in open_.items():
        broken = True
        found.append((hid, s, None, v, h))
    return found, broken


class Finding:
    def __init__(self, state, **kw):
        self.state = state
        self.start = kw.get("start")
        self.end = kw.get("end")
        self.legacy_spans = kw.get("legacy_spans") or []     # [(first, last)] physical line ranges
        self.detail = kw.get("detail", "")
        self.version = kw.get("version")


def _legacy_spans(lines, hook):
    spans = []
    active = [(i, strip_comment(l)) for i, l in enumerate(lines)]
    for group in hook._legacy_re:
        n = len(group)
        for i in range(len(lines) - n + 1):
            if all(group[k].search(active[i + k][1]) for k in range(n)) and not lines[i][:1].isspace():
                if not any(a <= i <= b for a, b in spans):
                    spans.append((i, i + n - 1))
    return sorted(spans)


def _scattered(lines, spans):
    """Reason why replacing the old lines by ONE block at the first one would change the logic, or "". The block goes where the first old
    line was and the others disappear, so between two spans only blank or comment lines may be; and the line after a multi-line group (an `if`
    and its call) must not be indented, or the group has more body than the pattern knows."""
    for (a1, b1), (a2, _b2) in zip(spans, spans[1:]):
        if any(strip_comment(l) for l in lines[b1 + 1:a2]):
            return "the old lines are not together (code between lines %d and %d): replace them by hand" % (b1 + 1, a2 + 1)
    for a, b in spans:
        if b > a and b + 1 < len(lines) and lines[b + 1][:1].isspace() and strip_comment(lines[b + 1]):
            return "the old group of lines %d-%d has an indented line after it (%d): it would be left without its `if`" % (a + 1, b + 1, b + 2)
    return ""


def classify(data, hook, adopted=False):
    """The state of `data` (bytes or None) for `hook`."""
    if data is None:
        return Finding(ABSENT_FILE)
    try:
        lines, _bom, _eol = _split(data)
    except MergeError as e:
        return Finding(UNREADABLE, detail=str(e))
    blocks, broken = _blocks(lines)
    mine = [b for b in blocks if b[0] == hook.id]
    if broken and (not mine or any(b[1] is None or b[2] is None for b in mine)):
        return Finding(MARKERS_BROKEN, detail="a marker has no pair or the order is wrong")
    if broken:
        return Finding(MARKERS_BROKEN, detail="markers of different hooks are nested or repeated")
    if len(mine) > 1:
        return Finding(MARKERS_BROKEN, detail="the block of hook %s appears %d times" % (hook.id, len(mine)))
    if mine:
        _hid, s, e, v, h = mine[0]
        body = [l.rstrip("\r\n") for l in lines[s + 1:e]]
        if body_sha(body) != h:
            return Finding(BLOCK_EDITED, start=s, end=e, version=v, detail="the body does not match sha=%s" % h)
        if body != hook.body_lines() or v != hook.version:
            return Finding(BLOCK_OUTDATED, start=s, end=e, version=v)
        return Finding(BLOCK_OK, start=s, end=e, version=v)
    spans = _legacy_spans(lines, hook)
    if spans:
        bad = _scattered(lines, spans)
        if bad:
            return Finding(LEGACY_SCATTERED, legacy_spans=spans, detail=bad)
        return Finding(LEGACY_LINE, legacy_spans=spans)
    for g in hook._legacy_re:
        if len(g) == 1 and any(l[:1].isspace() and g[0].search(strip_comment(l)) for l in lines):
            return Finding(LEGACY_NESTED, detail="the old line is indented (inside an if or loop); change it by hand")
    if adopted:
        return Finding(USER_ADOPTED)
    for l in lines:
        if hook.target in strip_comment(l):
            return Finding(TARGET_REFERENCED, detail="an active line already calls %s" % hook.target)
    return Finding(NO_BLOCK)


# ---- plans ----

class Plan:
    """What would happen to one file for one hook. `new` is the full new content (bytes) or None when nothing changes."""

    def __init__(self, hook, state, action, reason="", old=None, new=None, needs_accept=False, warnings=None, op="install"):
        self.blocked = None        # code when the plan must not be written (target_missing); the text and the diff stay for the person to see
        self.hook, self.state, self.action, self.reason = hook, state, action, reason
        self.old, self.new, self.needs_accept = old, new, needs_accept
        self.warnings = warnings or []
        self.op = op
        self.sha_before = sha256(old) if old is not None else None

    @property
    def changed(self):
        return self.new is not None and self.new != self.old

    def diff(self):
        if not self.changed:
            return ""
        a = (self.old or b"").decode("utf-8", "replace").lstrip("﻿").splitlines()
        b = self.new.decode("utf-8", "replace").lstrip("﻿").splitlines()
        return "\n".join(difflib.unified_diff(a, b, "a/" + self.hook.file, "b/" + self.hook.file, lineterm="", n=3))

    def as_dict(self):
        return {"hook": self.hook.id, "file": self.hook.file, "tier": self.hook.tier, "state": self.state, "action": self.action, "reason": self.reason,
                "changed": self.changed, "blocked": self.blocked, "needs_accept": self.needs_accept, "sha_before": self.sha_before,
                "sha_after": sha256(self.new) if self.changed else self.sha_before, "warnings": list(self.warnings), "diff": self.diff()}


def _warnings(lines):
    out = []
    long_ = [i + 1 for i, l in enumerate(lines) if len(l.rstrip("\r\n")) > LONG_LINE]
    if long_:
        out.append("lines over %d characters (DSF cuts them; not touched): %s" % (LONG_LINE, ", ".join(map(str, long_[:10]))))
    return out


def _fixed_eol(block, eol):
    return [l + eol for l in block]


def _insert_at(lines, hook, blocks):
    """Index where a new block goes: after the last block of a smaller id / before the first of a greater one when others exist, else the end."""
    others = sorted((b for b in blocks if b[1] is not None and b[2] is not None and b[0] != hook.id), key=lambda b: b[0])
    if others:
        smaller = [b for b in others if b[0] < hook.id]
        if smaller:
            return smaller[-1][2] + 1
        return others[0][1]
    return len(lines)


UNCHECKED = object()


def plan_install(data, hook, adopted=False, resolve=None, target=UNCHECKED):
    """`target` = the bytes of the macro the block calls (None = absent); when given, a plan that writes is marked `blocked="target_missing"`
    if that macro is not there or lacks the call the block replaces (nothing would call it: the old line would be lost). UNCHECKED = not
    verified by this caller.  See `_plan_install` for the rest."""
    p = _plan_install(data, hook, adopted, resolve)
    if target is not UNCHECKED and p.changed and p.action != "adopt":
        why = hook.target_problem(target)
        if why:
            p.blocked = "target_missing"
            p.reason = "target_missing: %s; nothing is written (%s)" % (why, p.reason)
    return p


def _plan_install(data, hook, adopted=False, resolve=None):
    """Plan to put `hook` into the file whose bytes are `data` (None = file absent). Pure. `resolve` answers a conflict:
    'replace' (block edited or outdated: put the wanted block, diff shown), 'adopt' (block edited: remove OUR markers, keep the lines)."""
    f = classify(data, hook, adopted)
    st = f.state
    P = lambda action, reason="", new=None, acc=False, w=None: Plan(hook, st, action, reason, data, new, acc, w)
    if st == UNREADABLE:
        return P("skip", f.detail)
    if st == ABSENT_FILE:
        if not hook.create:
            return P("skip", "file absent: not created (only %s is created)" % ", ".join(CREATE_IF_ABSENT))
        head = "; daemon.g -- created by the Workshop plugins: the block below only calls a macro of the workshop. Your own lines go outside it.\n"
        text = head + "".join(_fixed_eol(hook.block_lines(), "\n"))
        return P("create", "file absent: a short header and the block", text.encode("utf-8"))
    lines, bom, eol = _split(data)
    w = _warnings(lines)
    if st == BLOCK_OK:
        return P("unchanged", "the block is there and correct", None, False, w)
    if st == MARKERS_BROKEN:
        return P("skip", "markers-broken: " + f.detail + " (nothing changed; fix by hand or restore the backup)", None, False, w)
    if st in (LEGACY_NESTED, LEGACY_SCATTERED):
        return P("skip", f.detail, None, False, w)
    if st == USER_ADOPTED:
        return P("skip", "you manage this line (adopted); it is not inserted again", None, False, w)
    if st == TARGET_REFERENCED:
        return P("skip", f.detail + "; the line is yours, not wrapped", None, False, w)
    if st == BLOCK_EDITED:
        if resolve == "replace":
            new = lines[:f.start] + _fixed_eol(hook.block_lines(), eol) + lines[f.end + 1:]
            return P("replace-edited", "drift: the edited block is replaced by the wanted one", _join(new, bom), True, w)
        if resolve == "adopt":
            new = lines[:f.start] + lines[f.start + 1:f.end] + lines[f.end + 1:]
            return P("adopt", "drift: our markers are removed, the lines stay, the registry must record 'adopted'", _join(new, bom), True, w)
        return P("skip", "drift: " + f.detail + "; choose resolve='replace' (diff shown) or 'adopt'", None, False, w)
    if st == BLOCK_OUTDATED:
        new = lines[:f.start] + _fixed_eol(hook.block_lines(), eol) + lines[f.end + 1:]
        return P("update", "the block of v%s becomes v%d (only the block changes)" % (f.version, hook.version), _join(new, bom), False, w)
    if st == LEGACY_LINE:
        new = list(lines)
        first = f.legacy_spans[0][0]
        for a, b in reversed(f.legacy_spans):
            del new[a:b + 1]
        new[first:first] = _fixed_eol(hook.block_lines(), eol)
        return P("replace-legacy", "the old line(s) %s are replaced in place by the block" % ", ".join(
            "%d-%d" % (a + 1, b + 1) if a != b else str(a + 1) for a, b in f.legacy_spans), _join(new, bom), True, w)
    # NO_BLOCK: append (ordered by id among other workshop blocks)
    blocks, _ = _blocks(lines)
    at = _insert_at(lines, hook, blocks)
    new = list(lines)
    if at == len(new) and new and not new[-1].endswith("\n"):
        new[-1] = new[-1] + eol
    new[at:at] = _fixed_eol(hook.block_lines(), eol)
    return P("insert", "block appended" + (" (ordered by id)" if blocks else ""), _join(new, bom), False, w)


def plan_remove(data, hook, resolve=None):
    """Plan to take the block out (uninstall). Only OUR block is removed; with a block edited inside, only `resolve='force'`."""
    f = classify(data, hook)
    st = f.state
    P = lambda action, reason="", new=None, acc=False, w=None: Plan(hook, st, action, reason, data, new, acc, w, op="remove")
    if st in (ABSENT_FILE, NO_BLOCK, LEGACY_LINE, LEGACY_NESTED, LEGACY_SCATTERED, TARGET_REFERENCED, USER_ADOPTED):
        return P("unchanged", "no block of ours in the file")
    if st in (UNREADABLE, MARKERS_BROKEN):
        return P("skip", "%s: %s" % (st, f.detail))
    lines, bom, _eol = _split(data)
    new = lines[:f.start] + lines[f.end + 1:]
    if st == BLOCK_EDITED and resolve != "force":
        return P("skip", "drift: the block was edited inside; resolve='force' removes it (diff shown)")
    return P("remove", "block removed" + (" (it had been edited)" if st == BLOCK_EDITED else ""), _join(new, bom), st == BLOCK_EDITED)


def dry_run(read, hooks=DEFAULT_HOOKS, remove=False, adopted=(), only=None, resolve=None):
    """Plans for every hook. `read(rel)` returns the bytes of `sys/...` or None. NEVER writes. Several hooks in one file are chained: the
    second plan starts from the text the first would leave, so the diffs add up and the result is what apply would write."""
    plans, cur = [], {}
    for h in hooks:
        if only and h.file != only:
            continue
        data = cur[h.file] if h.file in cur else read(h.file)
        p = plan_remove(data, h, resolve) if remove else plan_install(data, h, h.id in adopted, resolve, read(h.target_rel))
        if p.changed:
            cur[h.file] = p.new
        plans.append(p)
    return plans


def render(plans):
    out = []
    for p in plans:
        out.append("== %s  [T%d]  hook=%s  state=%s  action=%s%s" % (p.hook.file, p.hook.tier, p.hook.id, p.state, p.action, "  (needs acceptance)" if p.needs_accept else ""))
        out.append("   " + p.reason)
        for w in p.warnings:
            out.append("   WARNING " + w)
        d = p.diff()
        if d:
            out.append(d)
    return "\n".join(out) + "\n"


# ---- the only writing function ----

def apply_plan(plan, read, write, busy=lambda: False, accept=False, backup=None):
    """Writes ONE plan. `read(rel)` -> bytes|None, `write(rel, bytes)`, `busy()` -> truthy when a job or macro runs or the board is not idle,
    `backup(rel, bytes_or_None)` is called with the exact old bytes before writing. Returns the sha256 of what was written (or None when
    nothing changed). Raises Busy, Stale, NeedsAccept, MergeError."""
    if not plan.changed:
        return None
    if plan.blocked:
        raise MergeError(plan.reason)
    if busy():
        raise Busy("the board is not idle (job, macro or paused): nothing written")
    if plan.needs_accept and not accept:
        raise NeedsAccept("%s on %s needs the owner's explicit acceptance of the diff" % (plan.action, plan.hook.file))
    now = read(plan.hook.file)
    if (sha256(now) if now is not None else None) != plan.sha_before:
        raise Stale("%s changed since the plan: plan again" % plan.hook.file)
    if backup:
        backup(plan.hook.file, now)
    write(plan.hook.file, plan.new)
    back = read(plan.hook.file)
    if back != plan.new:
        raise MergeError("read-back of %s differs from what was written" % plan.hook.file)
    if plan.op == "install" and plan.action != "adopt":
        after = classify(back, plan.hook)
        if after.state != BLOCK_OK:
            raise MergeError("after writing, %s is %s, not block-ok" % (plan.hook.file, after.state))
    elif plan.op == "remove" and classify(back, plan.hook).start is not None:
        raise MergeError("after removing, the block is still in %s" % plan.hook.file)
    return sha256(back)


# ---- file access over a folder (a copy of the SD, or the SD itself) ----

def folder_reader(root):
    def read(rel):
        try:
            with open(os.path.join(root, *rel.split("/")), "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return None
    return read


def folder_writer(root):
    import fs_atomic

    def write(rel, data):
        fs_atomic.write_bytes(os.path.join(root, *rel.split("/")), data)
    return write


def folder_backup(root, folder):
    def backup(rel, data):
        if data is None:
            return
        dest = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "xb") as fh:      # never overwrites an earlier backup
            fh.write(data)
    return backup


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Dry-run (default) of the link blocks in the native files. Writes ONLY with --apply.")
    ap.add_argument("--root", required=True, help="folder that contains sys/ (a copy of the SD, or the SD)")
    ap.add_argument("--remove", action="store_true", help="plan the removal of the blocks")
    ap.add_argument("--only", help="one file, for example sys/daemon.g")
    ap.add_argument("--adopted", default="", help="hook ids the person has taken over, comma separated")
    ap.add_argument("--resolve", choices=("replace", "adopt", "force"))
    ap.add_argument("--apply", action="store_true", help="write (needs --machine-off, --accept and --only)")
    ap.add_argument("--machine-off", action="store_true", help="I confirm: owner present, machine off, no job")
    ap.add_argument("--accept", action="store_true", help="I read the diff above and accept it")
    ap.add_argument("--backup-dir", help="folder for the exact old bytes (required with --apply)")
    a = ap.parse_args(argv)
    if not os.path.isdir(os.path.join(a.root, "sys")):
        print("no sys/ folder under %s" % a.root)
        return 2
    read = folder_reader(a.root)
    plans = dry_run(read, remove=a.remove, adopted=[x for x in a.adopted.split(",") if x], only=a.only, resolve=a.resolve)
    sys.stdout.write(render(plans))
    if not a.apply:
        print("DRY-RUN: nothing was written.")
        return 0
    if not (a.machine_off and a.accept and a.only and a.backup_dir):
        print("--apply needs --machine-off, --accept, --only <file> and --backup-dir: nothing written.")
        return 2
    wrote = 0
    for p in plans:
        wrote += 1 if apply_plan(p, read, folder_writer(a.root), accept=True, backup=folder_backup(a.root, a.backup_dir)) else 0
    print("written: %d file(s)" % wrote)
    return 0


if __name__ == "__main__":
    sys.exit(main())
