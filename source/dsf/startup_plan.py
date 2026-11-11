"""
startup_plan -- the product layer of the start-up wizard ("Puesta en marcha"): what the workshop wants to change on THIS SD, shown to
every person before anything is touched, and applied only item by item for what the person ticked.

  plan(sd)                 computes everything and WRITES NOTHING: the link blocks of the native files (native_merge), the move of the mode
                           files with the reference rewrites (modes_move) and the templates a new install is missing (examples). Every item
                           that changes a file carries its unified diff (secrets masked with install_log.redact) and the sha of the file the
                           person is looking at (expected_sha).
                           A fourth group, `cleanup`: the STAGED copies under sys/workshop/examples/ that no entry of the manifest lists (an old release leaves
                           them; they are never live). Offered as "file removed", with the old file copied to legacy first. Nothing outside that folder.
  apply(sd, selected, ...) applies ONLY the items the person ticked, one by one, each with its expected_sha. Refused as a whole when the
                           board is not idle or when an item of safety (pause, cancel, homing, laser guard, start-up) lacks its own
                           confirmation and the "machine off" statement. Every old file is copied to sys/workshop/legacy/<date>/ first, the
                           write is atomic and checked by reading it back, and the run goes to install_runs / install_actions.

Never automatic and never in bulk without the per item acceptance: nothing here is called by a start-up path, only by the two API operations.
The mode files form ONE group (a half-done move leaves daemon.g pointing at a file that is not there): all its items are ticked together
or none (`group_incomplete`).
"""
import hashlib
import os
import time

import examples
import fs_atomic
import install_log
import mode_paths
import modes_move
import native_merge
import paths
import sd_manifest
import sd_restore

ABSENT = "absent"
# hooks whose target macro runs the mode system: their block (config.g boot, daemon.g tail) points at the NEW paths, so it is only offered when the
# mode files are already there
MODE_HOOKS = frozenset(("boot", "daemon-tail"))
MAX_ITEMS = 60
STAGED = "sys/workshop/examples/"        # the only folder the cleanup group may ever touch
LEGACY = sd_restore.LEGACY
# What a file is for, to tell the person why it asks for more care: code -> the i18n key is startup_wizard.safety_<code>
_SAFETY = {"sys/config.g": "startup", "sys/daemon.g": "daemon", "sys/homeall.g": "homing", "sys/homez.g": "homing"}
_SAFETY_NAMES = {"pause.g": "pause", "resume.g": "pause", "cancel.g": "cancel", "stop.g": "cancel", "homex.g": "homing", "homey.g": "homing",
                 "start.g": "startup"}


class Refused(Exception):
    def __init__(self, code, reasons):
        super().__init__(code)
        self.code, self.reasons = code, reasons


def _sha(data):
    return ABSENT if data is None else hashlib.sha256(data).hexdigest()


def safety_of(path, exists=True):
    """Code of the reason why `path` needs the separate confirmation, or None. Anything that changes an existing file under sys/ counts
    (that folder holds what the board runs on its own), and the laser guard folder always."""
    if path in _SAFETY:
        return _SAFETY[path]
    low = path.lower()
    if "/guard/" in low:
        return "guard"
    base = low.rsplit("/", 1)[-1]
    if base in _SAFETY_NAMES and low.startswith("sys/"):
        return _SAFETY_NAMES[base]
    if exists and low.startswith("sys/") and not low.startswith("sys/workshop/examples/"):
        return "system"
    return None


def _item(id, group, kind, path, action, reason="", old=None, new=None, new_path=None, selectable=True, blocked=None, warnings=None,
          needs_accept=False, diff="", expected=None, exists=None):
    exists = old is not None if exists is None else exists
    safety = safety_of(path, exists) if kind != "create" or path in _SAFETY else None
    if new_path and not safety:
        safety = safety_of(new_path, False)
    return {"id": id, "group": group, "kind": kind, "path": path, "new_path": new_path, "action": action, "reason": reason,
            "selectable": bool(selectable and not blocked), "blocked": blocked, "safety": safety, "needs_accept": bool(needs_accept),
            "expected_sha": _sha(old) if expected is None else expected, "diff": install_log.redact(diff) if diff else "",
            "warnings": list(warnings or []), "size_after": None if new is None else len(new)}


# ---- planning ----

def modes_pending(raw):
    """True while a mode file is still at the old path or a reference to it is left (the plan of modes_move has something to do or to say)."""
    return any(i.action in ("move", "rewrite", "manual", "conflict") for i in raw)


def _hook_items(read, hooks, pending_modes=False):
    items, info = [], []
    for h in hooks:
        data = read(h.file)
        p = native_merge.plan_install(data, h, target=read(h.target_rel))
        if p.changed:
            kind = "create" if data is None else "edit"
            blocked, reason = p.blocked, p.reason
            if not blocked and pending_modes and h.id in MODE_HOOKS:
                blocked = "modes_not_migrated"
                reason = "modes_not_migrated: the mode files are not yet in %s; apply the mode group first, then plan again (%s)" % (mode_paths.MODES_DIR, p.reason)
            items.append(_item("hook:" + h.id, "hooks", kind, h.file, p.action, reason, data, p.new, warnings=p.warnings,
                               needs_accept=p.needs_accept, diff=p.diff(), blocked=blocked))
        elif p.action == "skip":
            info.append({"id": "hook:" + h.id, "group": "hooks", "path": h.file, "reason": p.reason, "state": p.state})
    return items, info


def _mode_items(read, listing, raw=None):
    raw = modes_move.plan(read, listing) if raw is None else raw
    ready = modes_move.ready(raw)
    items, info = [], []
    for i in raw:
        if i.action in ("manual", "conflict", "report"):
            info.append({"id": "mode:" + i.rel, "group": "modes", "path": i.rel, "reason": i.reason, "state": i.action, "diff": install_log.redact(i.diff())})
        elif i.action in ("move", "rewrite"):
            block = None if ready else "modes_not_ready"
            items.append(_item("mode:" + i.rel, "modes", i.action, i.rel, i.action, i.reason, i.old, i.new, new_path=i.new_rel if i.action == "move" else None,
                               blocked=block, needs_accept=True,
                               diff=i.diff() or "rename %s -> %s (the content does not change)" % (i.rel, i.new_rel)))
    return items, info


def _template_items(sd, manifest, read=None):
    items = []
    read = read or modes_move.folder_read(sd)
    moved_to = {n: o for o, n in mode_paths.MOVES}
    plugins = sorted({e.get("plugin") for e in sd_manifest.entries("template", path=manifest) if e.get("plugin")})
    for plugin in plugins:
        reg = examples._read_record(sd)
        for rel, src in examples.available(plugin, sd):
            if os.path.lexists(os.path.join(sd, *rel.split("/"))) or rel in reg:
                continue
            if rel in moved_to and read(moved_to[rel]) is not None:
                continue      # the file still lives at its old path: creating the new one would leave two (the mode group moves it)
            try:
                with open(src, "rb") as f:
                    data = f.read(examples_max())
            except OSError:
                continue
            new_lines = data.decode("utf-8", "replace").splitlines()
            diff = "\n".join(["--- /dev/null", "+++ b/" + rel] + ["+" + l for l in new_lines])
            items.append(_item("template:%s:%s" % (plugin, rel), "templates", "create", rel, "create", "file_absent", None, data, diff=diff, expected=ABSENT))
            items[-1]["plugin"] = plugin
    return items


def stale_staged(sd, manifest=None):
    """Paths (relative to the SD) of the regular files under sys/workshop/examples/ that no manifest entry lists as its stage. Reads only."""
    known = {e["stage"] for e in sd_manifest.load(manifest)["files"] if e.get("stage")}
    out = []
    base = os.path.join(sd, *STAGED.rstrip("/").split("/"))
    for root, dirs, files in os.walk(base):
        dirs.sort()
        for n in sorted(files):
            route = os.path.join(root, n)
            rel = os.path.relpath(route, sd).replace(os.sep, "/")
            if rel not in known and rel.startswith(STAGED) and os.path.isfile(route) and not os.path.islink(route):
                out.append(rel)
    return out


def _cleanup_items(sd, manifest, taken):
    """One item per stale staged copy. `taken` = paths already offered by another item (a stale copy the templates group still offers to create is left alone)."""
    items = []
    for rel in stale_staged(sd, manifest):
        if rel in taken or os.path.getsize(os.path.join(sd, *rel.split("/"))) > examples_max():
            continue
        with open(os.path.join(sd, *rel.split("/")), "rb") as f:
            data = f.read()
        lines = data.decode("utf-8", "replace").splitlines()
        diff = "\n".join(["--- a/" + rel, "+++ /dev/null"] + ["-" + l for l in lines])
        items.append(_item("cleanup:" + rel, "cleanup", "remove", rel, "remove", "stale_staged_copy", data, None, diff=diff))
        items[-1]["plugin"] = rel[len(STAGED):].split("/", 1)[0]
    return items


def examples_max():
    return 400000


def plan(sd=None, manifest=None, hooks=None, getters=None):
    """The whole plan. READS ONLY. `getters` (service_restart) adds the `blockers` list; the plan is computed either way."""
    sd = sd or paths.SD
    read, listing = modes_move.folder_read(sd), modes_move.folder_listing(sd)
    raw = modes_move.plan(read, listing)
    h_items, h_info = _hook_items(read, native_merge.DEFAULT_HOOKS if hooks is None else hooks, modes_pending(raw))
    m_items, m_info = _mode_items(read, listing, raw)
    t_items = _template_items(sd, manifest, read)
    staged_in_use = {"%s%s/%s" % (STAGED, i["plugin"], i["path"]) for i in t_items}
    c_items = _cleanup_items(sd, manifest, staged_in_use)
    items = h_items + m_items + t_items + c_items
    # said out loud: until the mode group is applied the readers of the service (capabilities, config package, height) see no modes
    return {"read_only": True, "sd_empty": read("sys/config.g") is None, "items": items, "info": h_info + m_info,
            "modes_unmigrated": [i.rel for i in raw if i.action in ("move", "conflict")],
            "counts": {g: sum(1 for i in items if i["group"] == g) for g in ("hooks", "modes", "templates", "cleanup")},
            "blockers": sd_restore.blockers(getters) if getters is not None else []}


# ---- applying ----

def _backup_folder(sd):
    rel = "%s/%s/startup" % (LEGACY, time.strftime("%Y%m%d"))
    if os.path.lexists(os.path.join(sd, *rel.split("/"))):
        rel += "-" + time.strftime("%H%M%S")
    return rel


def _check_selection(selected, by_id, machine_off):
    """Everything that can be refused BEFORE a byte is written. Returns the list of (selection, planned item)."""
    if not selected:
        raise Refused("nothing_selected", [{"code": "nothing_selected", "reason": "no item was ticked"}])
    if len(selected) > MAX_ITEMS:
        raise Refused("too_many", [{"code": "too_many", "reason": "too many items"}])
    seen, out, reasons = set(), [], []
    for s in selected:
        iid = str((s or {}).get("id") or "")
        if not iid or iid in seen:
            raise Refused("bad_selection", [{"code": "bad_selection", "reason": "an item is missing or repeated: %s" % iid}])
        seen.add(iid)
        out.append((s, by_id.get(iid)))
    for s, it in out:
        iid = str(s.get("id"))
        if it is not None and it["safety"] and not (s.get("confirm_safety") is True and machine_off):
            reasons.append({"code": "safety_confirm_required", "id": iid, "safety": it["safety"],
                            "reason": "%s is a safety file: it needs its own confirmation and the statement that the machine is off" % it["path"]})
    if reasons:
        raise Refused("safety_confirm_required", reasons)
    group = {i["id"] for i in by_id.values() if i["group"] == "modes" and i["selectable"]}
    picked = {iid for iid in seen if iid in group}
    if picked and picked != group:
        raise Refused("group_incomplete", [{"code": "group_incomplete", "reason": "the mode files move together: tick all of them or none"}])
    return out


def _apply_modes(sd, picks, busy, run, done, failed):
    read = modes_move.folder_read(sd)
    items = modes_move.plan(read, modes_move.folder_listing(sd))
    backup = _backup_folder(sd) + "/modes-move"
    try:
        modes_move.apply(items, read, modes_move.folder_write(sd), modes_move.folder_remove(sd), os.path.join(sd, *backup.split("/")), busy, accept=True)
    except (modes_move.MoveError, OSError) as e:
        for s, it in picks:
            failed(s, it, "write_error" if isinstance(e, OSError) else type(e).__name__.lower(), str(e))
        return
    for s, it in picks:
        data = read(it["new_path"] or it["path"])
        run.add(None, it["path"], "moved" if it["action"] == "move" else "updated", "native-managed" if it["action"] == "rewrite" else "workshop-owned",
                "explicit_user_accept", sha_before=it["expected_sha"], sha_after=_sha(data), size_after=None if data is None else len(data),
                backup_path=backup + "/" + it["path"], diff=it["diff"])
        done.append({"id": s["id"], "result": it["action"], "path": it["new_path"] or it["path"], "sha_after": _sha(data), "backup_path": backup + "/" + it["path"]})


def apply(selected, getters, machine_off=False, actor=None, sd=None, manifest=None, hooks=None):
    """Applies the items the person ticked. `selected`: [{"id", "expected_sha", "confirm_safety"}]. `machine_off`: the person's statement.
    Raises Refused before writing anything; otherwise returns {"run_id", "applied", "failed", "summary"}."""
    sd = sd or paths.SD
    actor = actor or {}
    busy = lambda: bool(sd_restore.blockers(getters))  # noqa: E731
    now = sd_restore.blockers(getters)
    if now:
        raise Refused("board_busy", now)
    current = plan(sd, manifest, hooks)
    by_id = {i["id"]: i for i in current["items"]}
    picks = _check_selection(selected, by_id, bool(machine_off))
    run = install_log.Run("wizard", actor.get("user", ""), actor.get("role", ""), actor.get("device", ""), actor.get("via", "api"), False, {})
    done, failed_list = [], []
    read, write = native_merge.folder_reader(sd), native_merge.folder_writer(sd)

    def failed(s, it, code, why):
        path = it["path"] if it else str(s.get("id"))
        run.add(it.get("plugin") if it else None, path, "failed", None, code, error=why)
        failed_list.append({"id": str(s.get("id")), "code": code, "reason": why})

    modes, modes_bad = [], False
    for s, it in picks:
        if it is None:
            failed(s, None, "not_in_plan", "the item is not in the plan any more: look at the new plan")
        elif not it["selectable"]:
            failed(s, it, "not_applicable", it["blocked"] or "this item cannot be applied")
        elif str(s.get("expected_sha") or "") != it["expected_sha"]:
            failed(s, it, "changed_since_preview", "the file changed after the preview: look at the new diff and ask again")
        elif it["group"] == "modes":
            modes.append((s, it))
    # the mode files first (the references change, THEN the boot block replaces those lines). Every check above was made on the plan the
    # person saw; a hook is planned again on the file as it is now.
    ids = {s["id"] for s, i in picks if i and i["group"] == "modes"}
    if modes and len(modes) == len(ids):
        n_before = len(failed_list)
        _apply_modes(sd, modes, busy, run, done, failed)
        modes_bad = len(failed_list) > n_before
    elif ids:
        modes_bad = True
        for s, it in modes:
            failed(s, it, "group_incomplete", "a mode item failed its check: none of the group was written")
    for s, it in picks:
        if any(f["id"] == str(s.get("id")) for f in failed_list) or it["group"] == "modes":
            continue
        if modes_bad and it["group"] == "hooks":
            failed(s, it, "modes_failed", "the mode group did not apply: no hook of this run was written")
            continue
        if sd_restore.blockers(getters):
            failed(s, it, "board_busy", "the board stopped being idle: nothing more was written")
            continue
        try:
            if it["group"] == "hooks":
                _apply_hook(sd, it, hooks, read, write, busy, run, done)
            elif it["group"] == "cleanup":
                _apply_cleanup(sd, it, manifest, run, done)
            else:
                _apply_template(sd, it, run, done)
        except (native_merge.MergeError, OSError, ValueError) as e:
            failed(s, it, type(e).__name__.lower(), str(e))
    try:
        run_id = run.finish()
    except Exception:  # noqa: BLE001 -- the report of the log never undoes what was done
        run_id = None
    return {"run_id": run_id, "applied": done, "failed": failed_list, "summary": run.summary()}


def _apply_hook(sd, it, hooks, read, write, busy, run, done):
    hook = next(h for h in (native_merge.DEFAULT_HOOKS if hooks is None else hooks) if "hook:" + h.id == it["id"])
    # planned again on the files as they are NOW, including the macro the block calls: apply_plan refuses a plan marked target_missing
    p = native_merge.plan_install(read(hook.file), hook, target=read(hook.target_rel))
    if p.blocked is None and hook.id in MODE_HOOKS and modes_pending(modes_move.plan(modes_move.folder_read(sd), modes_move.folder_listing(sd))):
        raise native_merge.MergeError("modes_not_migrated: the mode files are not in %s yet" % mode_paths.MODES_DIR)
    backups = []

    def backup(rel, data):
        if data is None:
            return
        dest = "%s/%s/%s" % (LEGACY, time.strftime("%Y%m%d"), rel)
        if os.path.lexists(os.path.join(sd, *dest.split("/"))):
            dest += "." + time.strftime("%H%M%S")
        fs_atomic.write_bytes(os.path.join(sd, *dest.split("/")), data)
        backups.append(dest)

    sha_after = native_merge.apply_plan(p, read, write, busy, accept=True, backup=backup)
    kind = "created" if it["action"] == "create" else ("hook_inserted" if p.action == "insert" else "hook_updated")
    run.add(None, hook.file, kind, "native-managed", "explicit_user_accept", sha_before=it["expected_sha"] if it["expected_sha"] != ABSENT else None,
            sha_after=sha_after, backup_path=backups[0] if backups else None, diff=it["diff"])
    done.append({"id": it["id"], "result": p.action, "path": hook.file, "sha_after": sha_after, "backup_path": backups[0] if backups else None})


def _apply_template(sd, it, run, done):
    r = examples.install(it["plugin"], sd, only=[it["path"]])
    if it["path"] not in r["created"]:
        raise OSError("not created: %s" % (r["skipped"].get(it["path"]) or "unknown"))
    with open(os.path.join(sd, *it["path"].split("/")), "rb") as f:
        sha_after = _sha(f.read())
    run.add(it["plugin"], it["path"], "created", "template", "explicit_user_accept", sha_after=sha_after, size_after=it["size_after"], diff=it["diff"])
    done.append({"id": it["id"], "result": "create", "path": it["path"], "sha_after": sha_after, "backup_path": None})


def _apply_cleanup(sd, it, manifest, run, done):
    """Removes ONE stale staged copy: only under sys/workshop/examples/, only a regular file the manifest does not list, only if it is still the
    file the person saw. The old bytes go to legacy first and are read back; then the file goes; empty folders left in examples/ go with it."""
    rel = it["path"]
    parts = rel.split("/")
    if not rel.startswith(STAGED) or ".." in parts or "" in parts or "\\" in rel or rel not in stale_staged(sd, manifest):
        raise ValueError("not a stale staged copy: %s" % rel)
    route = os.path.join(sd, *parts)
    with open(route, "rb") as f:
        data = f.read()
    if _sha(data) != it["expected_sha"]:
        raise ValueError("the file changed after the preview")
    dest = "%s/%s/%s" % (LEGACY, time.strftime("%Y%m%d"), rel)
    if os.path.lexists(os.path.join(sd, *dest.split("/"))):
        dest += "." + time.strftime("%H%M%S")
    fs_atomic.write_bytes(os.path.join(sd, *dest.split("/")), data)
    with open(os.path.join(sd, *dest.split("/")), "rb") as f:
        if _sha(f.read()) != _sha(data):
            raise OSError("the copy in legacy does not match: the file was not removed")
    os.remove(route)
    folder = os.path.dirname(route)
    stop = os.path.join(sd, *STAGED.rstrip("/").split("/"))
    while os.path.normcase(folder) != os.path.normcase(stop) and os.path.normcase(folder).startswith(os.path.normcase(stop)):
        try:
            os.rmdir(folder)
        except OSError:
            break
        folder = os.path.dirname(folder)
    run.add(it.get("plugin"), rel, "quarantined", "stale-staged", "explicit_user_accept", sha_before=it["expected_sha"], size_before=len(data),
            backup_path=dest, diff=it["diff"])
    done.append({"id": it["id"], "result": "remove", "path": rel, "sha_after": ABSENT, "backup_path": dest})
