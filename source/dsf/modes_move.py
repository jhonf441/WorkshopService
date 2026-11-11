"""Phase 4 of the SD layout: move the mode system to sys/workshop (paths in `mode_paths.py`) and fix every reference, with the diff in front.

    automodeselect.g modefff.g modelaser.g modecnc.g   sys/ -> sys/workshop/modes/
    modestate.g                                       sys/ -> sys/workshop/data/

DECISION (owner, 2026-11-07): the files are moved and the references are CHANGED, there are NO forwarding stubs. Evidence for it, from
`docs/sd-fase45-guion.md` section 2: a stub at the old path of modefff.g is a file the editors of Printing and Machine would modify instead of the
real one, it makes the M98 chain longer than config_scan follows, and the owner does not keep compatibility with old versions. What replaces the stub is
the REFERENCE SCAN: every file under sys/ and macros/ is read, each old-layout reference is proposed as a diff, and a reference that cannot be rewritten
safely (a T0 file, a workshop-owned macro) is listed so it is dealt with by hand or by the plugin release, never silently left broken.

Same safety rules as native_merge.py: planning is pure (injected `read` and `listing`), nothing is written without the owner's acceptance, a busy board or a
stale file stops everything, every old byte goes to the backup folder first, and `undo` restores it. Never automatic.

CLI (dry-run by default, the only thing that cannot write):
    python modes_move.py --root <copy-of-or-real-sd>
    python modes_move.py --root <sd> --apply --machine-off --accept --backup-dir <folder>
    python modes_move.py --root <sd> --undo --backup-dir <folder> --machine-off --accept
"""
import difflib
import hashlib
import json
import os
import re
import sys

import mode_paths

NAMES = "|".join(mode_paths.NAMES)
# `0:/sys/modefff.g`, `/sys/modefff.g`, `sys/modefff.g` (not already `sys/workshop/...`: the name must follow `sys/` directly)
_REF = re.compile(r"(?<![\w/.])(?:0:)?/?sys/(%s)\.g" % NAMES)
# M98 P"modefff.g": a bare name resolves against 0:/sys
_BARE = re.compile(r'(\bM98\s+P")(%s)\.g(")' % NAMES, re.I)
JOURNAL = "modes-move-journal.json"
SCAN_DIRS = ("sys", "macros")
# only REPORTED (never edited): the places where a person or DWC keeps a path to a mode file outside the two scanned folders
REPORT_DIRS = ("gcodes", "filaments", "menu")
REPORT_FILES = ("dwc-settings.json", "sys/dwc-settings.json")
REPORT_EXT = (".g", ".gcode", ".gc", ".nc", ".txt", ".macro", ".json", ".ngc")
REPORT_MAX_FILES = 3000
SKIP_LEGACY = "sys/workshop/legacy/"      # the backups of the wizard keep the old text on purpose: never scanned
SKIP_PARTS = ("sys/workshop/",)        # workshop-owned: plugin releases update them, the scan only reports
STAGED_PARTS = ("sys/workshop/examples/",)  # staged templates: not scanned at all (an old release leaves stale copies here)
SKIP_EXT = (".bak", ".new", ".example")
MAX_BYTES = 400000
T0_NAMES = frozenset((
    "pause.g", "resume.g", "cancel.g", "stop.g", "start.g", "homex.g", "homey.g", "bed.g", "mesh.g", "deployprobe.g", "retractprobe.g",
    "resurrect.g", "resurrect-prologue.g", "tpre.g", "tpost.g", "tfree.g", "filament-change.g", "load.g", "unload.g", "filament-error.g",
    "driver-stall.g", "driver-error.g", "heater-fault.g"))


class MoveError(Exception):
    pass


class Busy(MoveError):
    pass


class Stale(MoveError):
    pass


class NeedsAccept(MoveError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rewrite_text(text):
    """(new text, number of references changed). Idempotent: a path already in the new layout does not match."""
    n = 0

    def full(m):
        nonlocal n
        n += 1
        return mode_paths.sd(mode_paths.new_path(m.group(1)))

    def bare(m):
        nonlocal n
        n += 1
        return m.group(1) + mode_paths.sd(mode_paths.new_path(m.group(2).lower())) + m.group(3)

    text = _REF.sub(full, text)
    text = _BARE.sub(bare, text)
    return text, n


def rewrite_bytes(data):
    """Same on bytes (BOM, line endings and everything else untouched). A single-byte legacy text (Windows-1252 accents, the macros of DWC
    written by old tools) is rewritten byte for byte too: only the ASCII paths change and every other byte is kept (latin-1 maps all 256
    bytes both ways). None when the file is not text at all (a NUL byte: UTF-16 and the like)."""
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom):]
    try:
        text, enc = body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        if b"\x00" in body:
            return None, 0
        text, enc = body.decode("latin-1"), "latin-1"
    new, n = rewrite_text(text)
    return bom + new.encode(enc), n


class Item:
    """One thing the plan does or reports. action: move | rewrite | remove-old | manual | done | absent | conflict | report (a broken reference
    outside sys/ and macros/: only informed, never edited, never blocks)."""

    def __init__(self, action, rel, new_rel=None, old=None, new=None, reason="", refs=0):
        self.action, self.rel, self.new_rel, self.old, self.new, self.reason, self.refs = action, rel, new_rel, old, new, reason, refs
        self.sha_before = sha(old) if old is not None else None

    @property
    def writes(self):
        return self.action in ("move", "rewrite")

    def diff(self):
        if self.old is None or self.new is None or self.new == self.old:
            return ""
        a = self.old.decode("utf-8", "replace").lstrip("﻿").splitlines()
        b = self.new.decode("utf-8", "replace").lstrip("﻿").splitlines()
        return "\n".join(difflib.unified_diff(a, b, "a/" + self.rel, "b/" + (self.new_rel or self.rel), lineterm="", n=2))


def _eligible(rel):
    low = rel.lower()
    if low.endswith(SKIP_EXT) or ".bak-" in low or low.startswith(SKIP_LEGACY):
        return False
    return any(low.startswith(d + "/") for d in SCAN_DIRS) and low.endswith((".g", ".gcode", ".txt", ".macro"))


def _reported(read, listing):
    """References to the old mode paths in gcodes/, filaments/, menu/ and dwc-settings.json: they would stop working after the move and nothing
    here rewrites them (a G-code job file is the person's), so they are listed for the person to see. Missing folders are fine."""
    out, seen = [], 0
    names = []
    for d in REPORT_DIRS:
        for rel in sorted(listing(d)):
            if rel.lower().endswith(REPORT_EXT):
                names.append(rel)
    names = names[:REPORT_MAX_FILES] + [f for f in REPORT_FILES]
    for rel in names:
        seen += 1
        data = read(rel)
        if data is None or len(data) > MAX_BYTES:
            continue
        n = rewrite_bytes(data)[1]
        if n:
            out.append(Item("report", rel, old=data, reason="%d reference(s) to the old mode path; not edited here (it is yours or DWC's): change it by hand" % n, refs=n))
    return out


def plan(read, listing):
    """The whole phase 4 plan. `read(rel)` -> bytes|None, `listing(dir_rel)` -> relative paths of the files under it (recursive). Pure."""
    items, moved_old = [], set()
    for old_rel, new_rel in mode_paths.MOVES:
        data, there = read(old_rel), read(new_rel)
        if data is None and there is None:
            items.append(Item("absent", old_rel, new_rel, reason="the machine has no such file (a mode it does not use)"))
        elif data is None:
            items.append(Item("done", old_rel, new_rel, reason="already in the new place"))
        elif there is not None:
            items.append(Item("conflict", old_rel, new_rel, data, reason="both the old and the new file exist: nothing is moved, decide by hand"))
        else:
            new, n = rewrite_bytes(data)
            if new is None:
                items.append(Item("conflict", old_rel, new_rel, data, reason="not UTF-8 text: nothing is moved"))
                continue
            items.append(Item("move", old_rel, new_rel, data, new, "the file moves; %d reference(s) inside it change" % n, n))
            moved_old.add(old_rel)
    blocked = {i.rel for i in items if i.action == "conflict"}
    for d in SCAN_DIRS:
        for rel in sorted(listing(d)):
            if rel in moved_old or rel in blocked or not _eligible(rel):
                continue
            base = rel.rsplit("/", 1)[-1].lower()
            if rel.lower().startswith(STAGED_PARTS):
                continue  # a staged copy of a template (DSF puts the sdFiles here and an old release leaves its old copies behind): never live, never a blocker
            if any(rel.lower().startswith(p) for p in SKIP_PARTS):
                data = read(rel)
                if data is not None and len(data) <= MAX_BYTES and rewrite_bytes(data)[1]:
                    items.append(Item("manual", rel, old=data, reason="workshop-owned: the plugin release must be updated (not edited here)", refs=rewrite_bytes(data)[1]))
                continue
            data = read(rel)
            if data is None or len(data) > MAX_BYTES:
                continue
            new, n = rewrite_bytes(data)
            if not n:
                continue
            if base in T0_NAMES or re.match(r"^(tpre|tpost|tfree|trigger|deployprobe|retractprobe)[0-9]*\.g$", base) or base.startswith("resurrect"):
                items.append(Item("manual", rel, old=data, new=new, reason="tier 0 file: never edited by the workshop; the owner edits it by hand (the diff is what to change)", refs=n))
            else:
                items.append(Item("rewrite", rel, old=data, new=new, reason="%d reference(s) to the old path" % n, refs=n))
    items.extend(_reported(read, listing))
    for i in [i for i in items if i.action == "move"]:
        items.append(Item("remove-old", i.rel, i.new_rel, i.old, reason="old file removed after the new one is verified"))
    return items


def render(items):
    out = []
    for i in items:
        tag = "%s %s%s" % (i.action.upper(), i.rel, " -> " + i.new_rel if i.new_rel and i.action != "rewrite" else "")
        out.append("== " + tag)
        out.append("   " + i.reason)
        d = i.diff()
        if d:
            out.append(d)
    rep_ = [i for i in items if i.action == "report"]
    if rep_:
        out.append("Broken references outside sys/ and macros/ (informed only, not edited): " + ", ".join(i.rel for i in rep_))
    pend = [i for i in items if i.action in ("manual", "conflict")]
    out.append("\nSummary: %d move(s), %d rewrite(s), %d to do by hand, %d conflict(s)" % (
        sum(i.action == "move" for i in items), sum(i.action == "rewrite" for i in items),
        sum(i.action == "manual" for i in items), sum(i.action == "conflict" for i in items)))
    if pend:
        out.append("Not done automatically (every one needs a decision before the board restarts): " + ", ".join(i.rel for i in pend))
    return "\n".join(out) + "\n"


def ready(items):
    """True when applying leaves nothing broken: no conflict and nothing left by hand."""
    return not any(i.action in ("conflict", "manual") for i in items)


def apply(items, read, write, remove, backup_dir, busy=lambda: False, accept=False):
    """Writes the plan: new files first, then the edits, then the old files are removed; every old byte goes to `backup_dir` and a journal
    is written for `undo`. Refuses on a busy board, a missing acceptance, a file that moved since the plan, a conflict or anything left by hand."""
    todo = [i for i in items if i.writes]
    if not todo:
        return {"written": 0}
    if busy():
        raise Busy("the board is not idle: nothing written")
    if not accept:
        raise NeedsAccept("the owner must accept the diffs shown")
    if not ready(items):
        raise MoveError("there are conflicts or references left for the owner: nothing written (see the plan)")
    for i in items:
        if i.action != "report" and i.old is not None and (sha(read(i.rel) or b"") if read(i.rel) is not None else None) != i.sha_before:
            raise Stale("%s changed since the plan: plan again" % i.rel)
    for i in [x for x in items if x.action == "move"]:
        if read(i.new_rel) is not None:
            raise Stale("%s appeared since the plan" % i.new_rel)
    journal = {"moves": [], "edits": [], "removed": [], "complete": False}
    os.makedirs(backup_dir, exist_ok=True)

    def flush():
        # atomic (tmp + fsync + replace) and written after EVERY step, so an apply that stops half way (a failed read-back, a power cut)
        # leaves the journal of what it did and undo can put it back
        import fs_atomic
        fs_atomic.write_text(os.path.join(backup_dir, JOURNAL), json.dumps(journal, indent=1))

    def keep(rel, data):
        dest = os.path.join(backup_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.exists(dest):          # never overwrites an earlier backup
            with open(dest, "wb") as fh:
                fh.write(data)

    try:
        for i in todo:
            keep(i.rel, i.old)
        flush()
        for i in [x for x in todo if x.action == "move"]:
            journal["moves"].append({"old": i.rel, "new": i.new_rel, "sha_old": i.sha_before, "sha_new": sha(i.new)})
            flush()                           # the intention first: a crash between the write and the journal must not orphan the new file
            write(i.new_rel, i.new)
            if read(i.new_rel) != i.new:
                raise MoveError("read-back of %s differs" % i.new_rel)
        for i in [x for x in todo if x.action == "rewrite"]:
            journal["edits"].append({"file": i.rel, "sha_before": i.sha_before, "sha_after": sha(i.new)})
            flush()
            write(i.rel, i.new)
            if read(i.rel) != i.new:
                raise MoveError("read-back of %s differs" % i.rel)
        for i in [x for x in todo if x.action == "move"]:
            remove(i.rel)
            journal["removed"].append(i.rel)
            flush()
        journal["complete"] = True
        flush()
    except BaseException:
        try:
            flush()
        except Exception:  # noqa: BLE001 -- the original error is the one to report
            pass
        raise
    return {"written": len(todo), "journal": journal}


def undo(backup_dir, read, write, remove, busy=lambda: False, accept=False):
    """Puts back the exact old bytes from `backup_dir` (the files that were moved or edited) and removes the new copies that still are what
    was written. NOTHING is written when something is in the way (all or nothing: a half undo would leave the references pointing nowhere):
    a file the person edited after the apply (its sha is not the `sha_after` / `sha_new` of the journal), or an old file that was created
    again with other content. Those are returned in `conflicts` ({"path", "why"}) and `restored` is 0."""
    if busy():
        raise Busy("the board is not idle: nothing changed")
    if not accept:
        raise NeedsAccept("the owner must accept the undo")
    with open(os.path.join(backup_dir, JOURNAL), encoding="utf-8") as fh:
        j = json.load(fh)

    def backup(rel):
        with open(os.path.join(backup_dir, *rel.split("/")), "rb") as fh:
            return fh.read()

    conflicts, plan_ = [], []
    for m in j["moves"]:
        old_back = backup(m["old"])
        now_new, now_old = read(m["new"]), read(m["old"])
        if now_new is not None and sha(now_new) != m["sha_new"]:
            conflicts.append({"path": m["new"], "why": "changed after the move: its sha is not the one the apply wrote"})
        if now_old is not None and now_old != old_back:
            conflicts.append({"path": m["old"], "why": "created again with other content after the move"})
        plan_.append(("move", m, old_back, now_new, now_old))
    for e in j["edits"]:
        now = read(e["file"])
        if now is not None and sha(now) not in (e["sha_after"], e["sha_before"]):
            conflicts.append({"path": e["file"], "why": "edited after the apply: its sha is not the one the apply wrote"})
        elif now is None:
            conflicts.append({"path": e["file"], "why": "removed after the apply"})
        plan_.append(("edit", e, backup(e["file"]), now, None))
    if conflicts:
        return {"restored": 0, "conflicts": conflicts, "kept_changed": [c["path"] for c in conflicts if c["why"].startswith("changed")]}
    n = 0
    for kind, it, data, now, now_old in plan_:
        rel = it["old"] if kind == "move" else it["file"]
        if kind == "move":
            if now_old != data:
                write(rel, data)
                n += 1
            if now is not None:
                remove(it["new"])
        elif now != data:
            write(rel, data)
            n += 1
    return {"restored": n, "conflicts": [], "kept_changed": []}


# ---- over a folder ----

def folder_read(root):
    def read(rel):
        try:
            with open(os.path.join(root, *rel.split("/")), "rb") as fh:
                return fh.read()
        except (FileNotFoundError, NotADirectoryError):
            return None
    return read


def folder_listing(root):
    def listing(d):
        out = []
        base = os.path.join(root, *d.split("/"))
        for folder, _dirs, files in os.walk(base):
            for n in files:
                out.append(os.path.relpath(os.path.join(folder, n), root).replace(os.sep, "/"))
        return out
    return listing


def folder_write(root):
    import fs_atomic
    return lambda rel, data: fs_atomic.write_bytes(os.path.join(root, *rel.split("/")), data)


def folder_remove(root):
    return lambda rel: os.remove(os.path.join(root, *rel.split("/")))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Phase 4: dry-run (default) of the move of the mode system. Writes ONLY with --apply or --undo.")
    ap.add_argument("--root", required=True, help="folder that contains sys/ (a copy of the SD, or the SD)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--machine-off", action="store_true", help="I confirm: owner present, machine off, no job")
    ap.add_argument("--accept", action="store_true", help="I read the diffs above and accept them")
    ap.add_argument("--backup-dir")
    a = ap.parse_args(argv)
    if not os.path.isdir(os.path.join(a.root, "sys")):
        print("no sys/ folder under %s" % a.root)
        return 2
    read, listing = folder_read(a.root), folder_listing(a.root)
    if a.undo:
        if not (a.machine_off and a.accept and a.backup_dir):
            print("--undo needs --machine-off, --accept and --backup-dir: nothing changed.")
            return 2
        r = undo(a.backup_dir, read, folder_write(a.root), folder_remove(a.root), accept=True)
        print(r)
        if r["conflicts"]:
            print("STOPPED: nothing was restored; look at the files in `conflicts` and decide by hand.")
            return 3
        return 0
    items = plan(read, listing)
    sys.stdout.write(render(items))
    if not a.apply:
        print("DRY-RUN: nothing was written.")
        return 0
    if not (a.machine_off and a.accept and a.backup_dir):
        print("--apply needs --machine-off, --accept and --backup-dir: nothing written.")
        return 2
    try:
        r = apply(items, read, folder_write(a.root), folder_remove(a.root), a.backup_dir, accept=True)
    except MoveError as e:
        print("STOPPED: %s" % e)
        return 3
    print("written: %d file(s); journal in %s" % (r["written"], os.path.join(a.backup_dir, JOURNAL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
