"""
sd_view -- READ ONLY reader of ONE file of the SD for the dialog "Archivos por plugin" (operation startup.file.view).

It answers what a person wants to know about a file without being a developer: is it there, what does it say, did somebody edit it and where.
Nothing here writes: it opens files for reading only (the state comes from sd_integrity.check, the same one that startup.files uses).

Which files: only a path the manifest lists (its `path`, or the `stage` copy of a template) or an extra that the listing shows. Anything else, any
`..` or absolute path and every file that may hold a secret (users, keys, tokens, passwords, bridge settings) is refused with ApiError.
The lines of the network and the password of the board (M551, M552-M554, M587-M589) are masked with install_log.redact, as in every diff.

The answer carries keys, not sentences: `summary` is a list of {key, params} that the page turns into the language of the person.
The factory copy to compare with is the one of dsf/factory for a workshop-owned file and the staged copy for a template, and only when its sha is
the manifest's. Without one the answer says so (`factory.available` false and a `reason`), it never fails.
"""
import difflib
import os
import re

import install_log
import paths
import sd_files
import sd_integrity
import sd_manifest
import sd_restore
import startup_plan

MAX_CONTENT = 200 * 1024
MAX_COMPARE_LINES = 20000
_SECRET_NAME = re.compile(r"(^|[/._-])(users?|keys?|api[-_]?keys?|tokens?|secrets?|passwords?|passwd|credentials?|bridge|pin|pins|auth)([/._-]|$)|\.(pem|key|crt|p12|db|sqlite)$", re.I)


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _bad_syntax(path):
    return (not path or path.startswith("/") or "\\" in path or "\x00" in path or ":" in path.split("/")[0]
            or any(p in ("", ".", "..") for p in path.split("/")))


def _entry_of(path, data):
    """(manifest entry | None, is_stage). The stage copy of a template is also a listed file."""
    for e in data["files"]:
        if e["path"] == path:
            return e, False
    for e in data["files"]:
        if e.get("stage") == path:
            return e, True
    return None, False


def _check_path(path, sd, manifest):
    """The entry (or None for an extra) of a path that may be shown; raises Refused otherwise."""
    path = str(path or "")
    if _bad_syntax(path):
        raise Refused("bad_path", "the path is not a path of the SD")
    data = sd_manifest.load(manifest)
    entry, stage = _entry_of(path, data)
    if entry is None:
        known = {e["path"] for e in data["files"]} | {e["stage"] for e in data["files"] if e.get("stage")}
        if path not in sd_integrity._extras(sd, known):
            raise Refused("not_listed", "the file is not one of the files the plugins bring or one the list shows")
    if _SECRET_NAME.search(path):
        raise Refused("secret", "this file may hold a password or a key: it is never shown")
    return entry, stage


def _is_binary(raw):
    head = raw[:8192]
    if b"\x00" in head:
        return True
    try:
        raw.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return sum(1 for b in head if b < 9 or 13 < b < 32) > len(head) // 20


def _factory_bytes(entry, is_stage, sd, factory):
    """(bytes | None, reason | None): the copy that the manifest vouches for, or why there is none."""
    if entry is None:
        return None, "not_shipped"
    if entry["kind"] == "workshop-owned":
        route = os.path.join(factory, *entry["path"].split("/"))
    elif entry["kind"] == "template" and not is_stage:
        route = os.path.join(sd, *entry["stage"].split("/"))
    else:
        return None, "not_shipped"
    data, problem = sd_restore._read(route)
    if data is None:
        return None, "factory_missing"
    if sd_restore._sha(data) != entry["sha256"]:
        return None, "factory_mismatch"
    return data, None


def _decode(raw):
    """Text of a file as the person would read it. UTF-8 when the file is; a legacy file (Windows-1252 accents, or a mix of both) is read
    line by line, each line as UTF-8 if it is and as Windows-1252 if not, so the accents are not shown as replacement marks."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    out = []
    for line in raw.split(b"\n"):
        try:
            out.append(line.decode("utf-8"))
        except UnicodeDecodeError:
            out.append(line.decode("cp1252", "replace"))
    return "\n".join(out)


def _text(raw):
    return install_log.redact(_decode(raw), limit=10 ** 9)


def compare(sd_lines, factory_lines):
    """Per line of the file on the SD: its flag (same | changed | added); the ranges of lines that differ; the factory lines the file lost.
    changed = the line replaces another one of the factory; added = the factory has nothing there; removed = [{after, lines}] (after = number
    of the line of the SD that precedes them, 0 = at the top)."""
    flags = ["same"] * len(sd_lines)
    removed = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, factory_lines, sd_lines, autojunk=False).get_opcodes():
        if tag == "replace":
            flags[j1:j2] = ["changed"] * (j2 - j1)
            if (i2 - i1) > (j2 - j1):
                removed.append({"after": j2, "lines": factory_lines[i1 + (j2 - j1):i2]})
        elif tag == "insert":
            flags[j1:j2] = ["added"] * (j2 - j1)
        elif tag == "delete":
            removed.append({"after": j1, "lines": factory_lines[i1:i2]})
    ranges, start = [], None
    for n, f in enumerate(flags + ["same"], 1):
        if f != "same" and start is None:
            start = n
        elif f == "same" and start is not None:
            ranges.append([start, n - 1])
            start = None
    return flags, ranges, removed


_APPLIED = ("created", "updated", "moved", "hook_inserted", "hook_updated", "restored", "hook_adopted")
_SKIPPED = ("skipped_exists", "skipped_created_before", "skipped_user_content")


def pending_paths(sd=None, manifest=None):
    """Paths the wizard proposes to change now (the plan writes nothing). None when the plan cannot be computed: then nobody is told "pending"."""
    try:
        items = startup_plan.plan(sd, manifest)["items"]
    except Exception:  # noqa: BLE001 -- a reader never fails because of the plan
        return None
    return {p for i in items for p in (i["path"], i.get("new_path")) if p}


def applied_of(path, kind, state, last, pending):
    """Was it applied? {key, params}: applied_pending (the wizard proposes a change), applied_by (the wizard or a restore did it: date, who),
    applied_plugin (the plugin installed it and it is what the manifest says), applied_skipped (left alone on purpose), applied_never.
    `last` = the last row of the install log for the path (install_log.last_action_by_path) or None; `pending` = pending_paths() or None."""
    if pending and path in pending:
        return {"key": "applied_pending"}
    if last and last.get("action") in _APPLIED:
        if last.get("trigger") in ("plugin-install", "plugin-update"):
            return {"key": "applied_plugin"}
        return {"key": "applied_by", "params": {"date": str(last.get("ts") or "")[:10], "who": last.get("actor") or ""}}
    if state == "ok" and kind in ("workshop-owned", "template"):
        return {"key": "applied_plugin"}
    if last and last.get("action") in _SKIPPED:
        return {"key": "applied_skipped"}
    return {"key": "applied_never"}


def _summary(row, entry, present, binary, truncated, lines_n, cmp, factory_reason, masked):
    s = []
    state = row["state"]
    if not present:
        if state == "absent":
            s.append({"key": "not_yet"})
        elif row.get("created_before"):
            s.append({"key": "missing_deleted"})
        elif state in ("missing", "deleted"):
            s.append({"key": "missing"})
        else:
            s.append({"key": "unreadable"})
        return s
    if state == "edited":
        if cmp is not None and (cmp["ranges"] or cmp["removed"]):
            s.append({"key": "edited_lines", "params": {"ranges": cmp["ranges"], "removed": sum(len(r["lines"]) for r in cmp["removed"])}})
        elif cmp is not None:
            s.append({"key": "edited_same_text"})   # only the line endings or the end of the file differ
        else:
            s.append({"key": "edited_no_factory"})
    elif state in ("mark-mismatch", "legacy-mark"):
        s.append({"key": "wrong_mark"})
    elif state == "comments-only":
        s.append({"key": "comments_only"})
    elif state == "unreadable":
        s.append({"key": "unreadable"})
    elif state == "unknown-extra":
        s.append({"key": "extra"})
    else:
        s.append({"key": "loaded_ok", "params": {"lines": lines_n}})
    if entry and entry["kind"] == "native-managed" and row.get("hooks") and not all(row["hooks"].values()):
        s.append({"key": "lines_missing", "params": {"n": sum(1 for v in row["hooks"].values() if not v)}})
    if binary:
        s.append({"key": "binary"})
    if truncated:
        s.append({"key": "truncated"})
    if factory_reason and state == "edited":
        s.append({"key": "no_factory", "params": {"why": factory_reason}})
    if masked:
        s.append({"key": "masked"})
    return s


def view(path, sd=None, manifest=None, factory=None, last=None, pending=None):
    """Everything the reader of the dialog needs about `path`. READ ONLY. Raises Refused for a path that may not be shown."""
    sd = sd or paths.SD
    factory = factory or sd_restore.FACTORY
    entry, is_stage = _check_path(path, sd, manifest)
    path = str(path)
    row = next((r for r in sd_integrity.check(sd, manifest)["files"] if r["path"] == path), None)
    if row is None:   # the stage copy of a template: it is the file itself, listed through its template
        owner = {"path": path, "kind": "template", "plugin": entry.get("plugin") if entry else None, "state": "ok", "used_by": entry.get("used_by", []) if entry else []}
        row = dict(owner)
    raw, problem = sd_restore._read(os.path.join(sd, *path.split("/")))
    present = raw is not None
    if last is None:
        try:
            last = install_log.last_action_by_path().get(path)
        except Exception:  # noqa: BLE001 -- the log is a help, not a condition
            last = None
    if pending is None:
        pending = pending_paths(sd, manifest)
    out = {"read_only": True, "path": path, "kind": row["kind"], "plugin": row.get("plugin"), "used_by": row.get("used_by", []), "state": row["state"],
           "status": sd_files.status_of(row), "present": present, "size": None if raw is None else len(raw), "lines": 0, "binary": False,
           "content": None, "truncated": False, "masked": False, "factory": {"available": False, "reason": None}}
    out["applied"] = applied_of(path, row["kind"], row["state"], last, pending)
    if not present:
        out["summary"] = _summary(row, entry, False, False, False, 0, None, None, False) + [out["applied"]]
        return out
    out["binary"] = _is_binary(raw)
    cmp = None
    reason = None
    if not out["binary"]:
        text = _text(raw)
        out["masked"] = text != _decode(raw)
        lines = text.splitlines()
        out["lines"] = len(lines)
        out["truncated"] = len(raw) > MAX_CONTENT
        shown = lines
        if out["truncated"]:
            shown = text.encode("utf-8")[:MAX_CONTENT].decode("utf-8", "ignore").splitlines()[:-1]
        out["content"] = "\n".join(shown)
        if entry is not None and not is_stage:
            fbytes, reason = _factory_bytes(entry, is_stage, sd, factory)
            if fbytes is not None and not out["truncated"] and not _is_binary(fbytes):
                flines = _text(fbytes).splitlines()
                if len(flines) > MAX_COMPARE_LINES or len(lines) > MAX_COMPARE_LINES:
                    reason = "too_big"
                else:
                    flags, ranges, removed = compare(lines, flines)
                    cmp = {"ranges": ranges, "removed": removed}
                    out["factory"] = {"available": True, "reason": None, "changed": ranges, "removed": removed, "lines_factory": len(flines)}
                    out["diff_lines"] = [{"n": n, "text": t, "flag": f} for n, (t, f) in enumerate(zip(lines, flags), 1)]
            elif fbytes is not None:
                reason = "too_big" if out["truncated"] else "not_text"
        else:
            reason = "not_shipped" if reason is None else reason
        if not out["factory"]["available"]:
            out["factory"]["reason"] = reason
    out["summary"] = _summary(row, entry, True, out["binary"], out["truncated"], out["lines"], cmp, out["factory"]["reason"], out["masked"]) + [out["applied"]]
    return out
