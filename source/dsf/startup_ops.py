"""
startup_ops -- the read only operations of the start-up report (SD-LAYOUT.md E.2 and F.5, phase 1).

  startup.files        the files every plugin brings, grouped by plugin, with their state (sd_files.listing)
  startup.file.view    one file to read: content, summary keys, comparison with the factory copy, was it applied (sd_view)
  startup.integrity    compares the SD with the manifest (sd_integrity.check). Never writes, never restores.
  startup.runs.list    summaries of the runs of the start-up, newest first
  startup.runs.get     one run with its actions; the text of a diff only for an administrator (it may name network lines)

All of them need the technician role (the paths and outcomes reveal the layout of the SD). Restoring one workshop file (phase 6, sd_restore.py) is
the administrator's startup.integrity.restore, with its own read only preview; applying hooks and migrating are later phases.
"""
import install_log
import identity
import sd_files
import sd_integrity
import sd_restore
import sd_pending
import sd_view
import settings_store
import startup_plan
import service_restart
from workshop_api import ADMIN, ApiError, Arg, Op, READ, WRITE


def _written(fn, *args, **kw):
    """Run something that writes the SD; whatever happens, the plan kept by sd_pending is forgotten (it is computed again at the next look)."""
    try:
        return fn(*args, **kw)
    finally:
        sd_pending.forget()


def accepted_reviews():
    value = settings_store.get("file-review")["value"]
    return value if isinstance(value, dict) else {}

def file_review(args, c):
    path = args["path"]
    found = [f for p in sd_files.listing()["plugins"] for f in p["files"] if f["path"] == path]
    if not found:
        raise ApiError("invalid_args", "not a file the plugins bring", field="path")
    f = found[0]
    if args.get("reviewed", True) is False:
        settings_store.merge("file-review", {path: ""})
        return {"path": path, "reviewed": False}
    if f["status"] != "edited" or not f.get("sha"):
        raise ApiError("invalid_args", "only a file edited by hand can be left as it is", field="path")
    if args.get("expected_sha") and args["expected_sha"] != f["sha"]:
        raise ApiError("conflict", "the file changed since the person looked at it", field="expected_sha")
    settings_store.merge("file-review", {path: f["sha"]})
    return {"path": path, "reviewed": True, "sha": f["sha"]}

def review_op():
    a, S, B = Arg, "str", "bool"
    return Op("startup.file.review", file_review, WRITE,
       {"path": a(S, True, desc="Path of the file relative to 0:/, as the list of files shows it."),
        "reviewed": a(B, default=True, desc="true: leave the file as it is (the person edited it on purpose); false: ask for attention again."),
        "expected_sha": a(S, desc="The sha the person was looking at (the `sha` of startup.files): a file that changed since is refused.")},
       "Remembers that a hand-edited file was looked at and is meant to stay as it is. It is kept against the sha of the content: the file asks for attention "
       "again only when it changes again. Nothing on the SD is written; it only stores the decision in the service settings.", log=False)


def build(ctx):
    a, S, I, B = Arg, "str", "int", "bool"

    def integrity(args, c):
        report = sd_integrity.check()
        if not args.get("details", True):
            report = {k: v for k, v in report.items() if k != "files"}
        elif args.get("only_problems"):
            report["files"] = [f for f in report["files"] if f["state"] in sd_integrity.ATTENTION]
        return report

    def files(args, c):
        out = sd_files.mark_reviewed(sd_files.listing(plugin=args.get("plugin") or None), accepted_reviews())
        try:
            last = install_log.last_action_by_path()
        except Exception:  # noqa: BLE001 -- the log is a help: without it the rows simply carry no "applied" answer
            return out
        pending = sd_view.pending_paths()
        for p in out["plugins"]:
            for f in p["files"]:
                f["applied"] = sd_view.applied_of(f["path"], f["kind"], f["state"], last.get(f["path"]), pending)
        return out

    def file_view(args, c):
        try:
            return sd_view.view(args["path"])
        except sd_view.Refused as e:
            raise ApiError("invalid_args", e.message, field="path", reason=e.code)

    def runs_list(args, c):
        return install_log.list_runs(args.get("limit") or 50, args.get("offset") or 0, args.get("plugin") or None)

    def runs_get(args, c):
        admin = ((c.get("user") or {}).get("role") == "admin")
        run = install_log.get_run(args["run_id"], with_diff=admin)
        if run is None:
            raise ApiError("invalid_args", "no such run", field="run_id")
        return run

    def _getters(c):
        return service_restart.default_getters((ctx or {}).get("bridge"))
    def restore_preview(args, c):
        return sd_restore.preview(args["path"], getters=_getters(c))

    def restore(args, c):
        if args.get("apply") is not True:
            raise ApiError("invalid_args", "restoring needs apply true, with the expected_sha of the preview", field="apply")
        who = identity.actor(c)
        who["via"] = "api"
        try:
            return _written(sd_restore.restore, args["path"], args.get("expected_sha"), _getters(c), actor=who)
        except sd_restore.RestoreRefused as e:
            raise ApiError("conflict", "; ".join(r["reason"] for r in e.reasons), reasons=e.reasons)

    def plan(args, c):
        return startup_plan.plan(getters=_getters(c))
    def apply_(args, c):
        if args.get("apply") is not True:
            raise ApiError("invalid_args", "applying needs apply true, with the items the person ticked", field="apply")
        who = identity.actor(c)
        who["via"] = "api"
        try:
            return _written(startup_plan.apply, args["items"], _getters(c), args.get("machine_off") is True, who)
        except startup_plan.Refused as e:
            raise ApiError("conflict", "; ".join(r["reason"] for r in e.reasons), reasons=e.reasons)

    return [
        Op("startup.plan", plan, READ,
           {}, "The start-up plan of THIS SD: the link blocks of the native files, the move of the mode files with the references that change, and the templates "
               "a new install is missing. Every item that changes a file carries its unified diff (secrets masked) and the expected_sha to send back. "
               "WRITES NOTHING.", log=False),
        Op("startup.apply", apply_, ADMIN,
           {"items": a("obj", True, desc="The items the person ticked: [{id, expected_sha, confirm_safety}]. Only these are applied, one by one."),
            "machine_off": a(B, default=False, desc="The person states the machine is off (needed for safety files)."),
            "apply": a(B, True, desc="Must be true: the explicit request.")},
           "Applies ONLY the items of startup.plan that the person ticked, each with the expected_sha of the preview (a file that changed since is skipped). "
           "Refused unless the board is idle. Safety files (pause, cancel, homing, laser guard, start-up) also need confirm_safety on the item and machine_off. "
           "The old file is first copied to sys/workshop/legacy/<date>/, writes are atomic and read back, and the run goes to the install log."),
        review_op(),
        Op("startup.file.view", file_view, READ,
           {"path": a(S, True, desc="Path of the file relative to 0:/, as the list of files shows it.")},
           "One file of the SD to read: is it there, its text (cut at 200 KB; network and password lines masked), what differs from the factory copy "
           "(line ranges and a flag per line) when there is one, and whether it was applied (the install log and the plan). Only files the plugins bring "
           "or the list shows; never users, keys or tokens. READ ONLY.", log=False),
        Op("startup.integrity.restore.preview", restore_preview, READ,
           {"path": a(S, True, desc="Path of the file relative to 0:/ (as listed by startup.integrity).")},
           "What restoring ONE workshop-owned file from the factory copy would do: refusals with their reason, the diff current -> factory and the "
           "expected_sha to send back. WRITES NOTHING.", log=False),
        Op("startup.integrity.restore", restore, ADMIN,
           {"path": a(S, True, desc="Path of the file relative to 0:/."),
            "expected_sha": a(S, True, desc="expected_sha of the preview (the sha of the current file, or 'absent'): a file that changed since is not replaced."),
            "apply": a(B, True, desc="Must be true: the explicit request.")},
           "Restores ONE workshop-owned file from the factory copy, on explicit request only. Refused for templates, native, generated and external files, "
           "for anything that runs in pause, cancel, homing, the laser guard or at start-up, and unless the board is idle with no job, laser or movement. "
           "The current file is first copied to sys/workshop/legacy/<date>/, the write is atomic and the action goes to the install log."),
        Op("startup.integrity", integrity, READ,
           {"details": a(B, default=True, desc="false: only the summary (counts per state and kind), no file list."),
            "only_problems": a(B, default=False, desc="true: in the file list keep only the files that need a person to look (edited, deleted, wrong mark, unknown extra).")},
           "Integrity report of the SD against the manifest of the workshop files (workshop-owned, templates, native files with workshop lines, "
           "generated files and files the person has to provide). READ ONLY: it never writes, restores or deletes anything.", log=False),
        Op("startup.files", files, READ,
           {"plugin": a(S, desc="Only this plugin.")},
           "The files every workshop plugin brings (workshop-owned, templates, native files with workshop lines, generated and expected-external), each with "
           "its class, its state on the SD (ok, edited, missing, not yet generated, needs a look), who uses it and whether it is a safety file, plus counts "
           "per plugin. READ ONLY: it only reads the SD.", log=False),
        Op("startup.runs.list", runs_list, READ,
           {"plugin": a(S, desc="Only the runs that touched a file of this plugin."), "limit": a(I, min=1, max=200, default=50, desc="Runs per page."),
            "offset": a(I, min=0, default=0, desc="Runs to skip.")},
           "The runs of the start-up (who, when, which plugins, counts per outcome), newest first.", log=False),
        Op("startup.runs.get", runs_get, READ, {"run_id": a(S, True, desc="Id of the run (startup.runs.list).")},
           "One run of the start-up with the action on every file: created, skipped (and why), failed, with the sha before and after. "
           "The text of a diff is included only for an administrator.", log=False),
    ]
