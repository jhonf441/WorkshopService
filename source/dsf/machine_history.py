"""History of the calibrations of Machine v2 (phase 2, design 2.11 and 5.3): list, get, compare and restore.

machine.history.list     (technician) the records of the calibration store, newest first, filtered by kind, user, state and dates.
machine.history.get      (technician) one record with what restoring it would do (restorable, role needed, how the files are now).
machine.history.compare  (technician) two records of the SAME kind: table of the values that differ (results and inputs) and, for height
                         maps (mesh.probe), the difference grid and its statistics.
machine.history.restore  (technician; ADMIN for the hardware-risk kinds, by the record's kind: permissions.ESCALATE_IN + the check below)
                         builds a PLAN that puts the `before` (undo) or `after` (re-apply) values of a configuration record back. It
                         NEVER writes: the plan goes to machine.config.apply (config.commit: fresh snapshot, sha check of every file, journal),
                         so a restore can itself be undone. Only the lines the record touched are edited, so what was changed in
                         other lines since stays.

The file check (design 5.3): a record knows the sha of every file it wrote. If a file is neither as the record left it (sha_after) nor as it
found it (sha_before) the file changed since: the restore is REFUSED with `reason: "file_changed"` and the three-way table (what the record
had before / after / what the file has now, per value). The person looks at it (or at machine.history.compare) and asks again with
`accept_current: true`: the plan is then made over the CURRENT file, replacing only the values of the record.

Restorable kinds: config.m671, config.g31, config.m208, config.m92 (admin kinds), config.g10, config.workplaces, and offsets.snapshot (its
work offsets become a config.workplaces plan). Not restorable: config.bed (the whole bed.g is the value; use the config history snapshot),
calibration runs (there is nothing to put back) and records whose line did not exist before (`before` is null).
"""
import identity
import machine_config as mc
import machine_diff
import machine_heightmap as hm
import machine_offsets
import machine_store
import permissions
from messages import M
from workshop_api import ApiError, Arg, READ, WRITE, Op

RESTORABLE = ("config.m671", "config.g31", "config.m208", "config.m92", "config.g10", "config.workplaces",
              # phase 3: the values of `before` / `after` are the shape the planner takes
              "config.m556", "config.m425", "config.m593", "config.m906", "config.m913", "config.m917", "config.m203", "config.m201",
              "config.m205", "config.m566", "config.m569")
MAX_LIMIT = 200


def brief(rec):
    res = rec.get("results") or {}
    return {"id": rec["id"], "kind": rec["kind"], "ts": rec["ts"], "user": rec.get("user", ""), "role": rec.get("role", ""), "device": rec.get("device", ""),
            "state": rec["state"], "run_id": rec.get("run_id"), "notes": rec.get("notes", ""), "outcome": res.get("outcome"), "light": res.get("light"),
            "applied": bool(rec.get("applied")), "restorable": restore_info(rec)["restorable"]}


def role_for(kind):
    """The role a restore (and the apply of its plan) of a record of this kind needs."""
    target = "config.workplaces" if kind == "offsets.snapshot" else kind
    return permissions.needed_role("machine.config.apply", {"args": {"kind": target}})


def restore_info(rec):
    """{"restorable", "reason", "which": [...], "role_needed"} without touching the disk."""
    kind, res = rec["kind"], rec.get("results") or {}
    out = {"restorable": False, "reason": None, "which": [], "role_needed": role_for(kind)}
    if kind == "offsets.snapshot":
        if res.get("work"):
            out.update(restorable=True, which=["after"])
        else:
            out["reason"] = "no_value"
        return out
    if kind not in RESTORABLE:
        out["reason"] = "not_restorable"
    elif rec["state"] != "done" or not rec.get("applied"):
        out["reason"] = "not_applied"
    else:
        out["which"] = [w for w in ("before", "after") if res.get(w)]
        out["restorable"] = bool(out["which"])
        out["reason"] = None if out["which"] else "no_value"
    return out


def file_states(rec):
    """[{"path", "sha_now", "sha_before", "sha_after", "state"}] of the files the record wrote: clean (as the record left it or found it),
    changed (something else), missing."""
    out = []
    for f in (rec.get("applied") or {}).get("files") or []:
        path = "0:/" + f["path"]
        data = mc.read_bytes(path)
        now = mc.sha_of(data) if data is not None else None
        state = "missing" if data is None and f["sha_after"] is not None else "clean" if now in (f["sha_after"], f["sha_before"]) else "changed"
        out.append({"path": path, "sha_now": now, "sha_before": f["sha_before"], "sha_after": f["sha_after"], "state": state})
    return out


# ---- operations ----

def _list(args, ctx):
    limit = min(int(args.get("limit") or 50), MAX_LIMIT)
    rows, total = machine_store.query(kind=args.get("kind") or None, user=args.get("user") or None, since=args.get("since"),
                                      until=args.get("until"), state=args.get("state") or None, limit=limit, offset=int(args.get("offset") or 0))
    return {"records": [brief(r) for r in rows], "total": total, "limit": limit, "offset": int(args.get("offset") or 0)}


def _record_or_404(rec_id):
    rec = machine_store.get_record(rec_id)
    if rec is None:
        raise ApiError("not_found", M("machine_history_not_found"), reason="not_found")
    return rec


def _get(args, ctx):
    rec = _record_or_404(args["id"])
    return {"record": rec, "restore": dict(restore_info(rec), files=file_states(rec))}


def _compare(args, ctx):
    a, b = _record_or_404(args["a"]), _record_or_404(args["b"])
    if a["kind"] != b["kind"]:
        raise ApiError("invalid_args", M("machine_history_kind_mismatch", a=a["kind"], b=b["kind"]), field="b", reason="kind_mismatch")
    out = {"kind": a["kind"], "a": brief(a), "b": brief(b), "results": machine_diff.diff_rows(a.get("results"), b.get("results")),
           "inputs": machine_diff.diff_rows(a.get("inputs"), b.get("inputs")), "mesh": None}
    if a["kind"] == "mesh.probe":
        out["mesh"] = mesh_compare(a, b)
    return out


def mesh_compare(a, b):
    ids = [(r.get("results") or {}).get("mesh_id") for r in (a, b)]
    texts = [hm.csv_of(i) if i else None for i in ids]
    if not all(texts):
        return {"ok": False, "reason": "mesh_missing", "ids": ids}
    d = machine_diff.mesh_diff(hm.parse_csv(texts[0]), hm.parse_csv(texts[1]))
    return dict(d, ids=ids)


def _three_way(rec, plan):
    """Per value: what the record had before, after, and what the file has now."""
    res = rec.get("results") or {}
    fb, fa, fn = (machine_diff.flatten(res.get("before") or {}), machine_diff.flatten(res.get("after") or {}), machine_diff.flatten(plan.get("before") or {}))
    return [{"key": k, "before": fb.get(k), "after": fa.get(k), "now": fn.get(k)} for k in sorted(set(fb) | set(fa)) if not (fb.get(k) == fa.get(k) == fn.get(k))]


def _values_of(rec, which):
    if rec["kind"] == "offsets.snapshot":
        return "config.workplaces", machine_offsets.workplaces_values((rec.get("results") or {}).get("work") or {})
    return rec["kind"], (rec.get("results") or {}).get(which)


def _restore(args, ctx):
    rec = _record_or_404(args["id"])
    if args.get("kind") and args["kind"] != rec["kind"]:
        raise ApiError("invalid_args", M("machine_history_kind_mismatch", a=args["kind"], b=rec["kind"]), field="kind", reason="kind_mismatch")
    ok, need = mc._role_ok(ctx, "config.workplaces" if rec["kind"] == "offsets.snapshot" else rec["kind"])
    if not ok:
        raise ApiError("forbidden", M("machine_config_needs_role", role=need), reason="role", needed_role=need)
    info = restore_info(rec)
    which = args.get("which") or ("after" if rec["kind"] == "offsets.snapshot" else "before")
    if not info["restorable"]:
        raise ApiError("refused", M("machine_history_not_restorable", reason=info["reason"]), reason=info["reason"])
    if which not in info["which"]:
        raise ApiError("refused", M("machine_history_no_value", which=which), reason="no_value")
    states = file_states(rec) if rec["kind"] != "offsets.snapshot" else []
    dirty = any(s["state"] != "clean" for s in states)
    kind, values = _values_of(rec, which)
    who = identity.actor(ctx)
    try:
        plan = mc.make_plan(kind, values, mc._env(), who)
    except mc.PlanError as e:
        raise ApiError("failed", M("machine_history_plan_failed", reason=e.code), reason=e.code)
    three = _three_way(rec, plan) if rec["kind"] != "offsets.snapshot" else []
    if dirty and not args.get("accept_current"):
        mc.drop_plan(plan["id"])
        raise ApiError("conflict", M("machine_history_file_changed"), reason="file_changed", three_way=three, files=states)
    plan["restore_of"] = rec["id"]
    out = mc.public(plan)
    out["restore"] = {"of": rec["id"], "which": which, "dirty": dirty, "accepted_current": bool(dirty), "three_way": three, "files": states}
    return out


def ops():
    S, I, N, B = "str", "int", "int", "bool"
    a = Arg
    return [
        Op("machine.history.list", _list, READ,
           {"kind": a(S, desc="Only this kind (probe.repeat, level.g32, mesh.probe, config.g31, offsets.snapshot...)."), "user": a(S, desc="Only this person."),
            "state": a(S, choices=machine_store.STATES, desc="Only records that ended like this."),
            "since": a(I, min=0, desc="Epoch seconds, from."), "until": a(I, min=0, desc="Epoch seconds, until."),
            "limit": a(N, min=1, max=MAX_LIMIT, desc="Rows (default 50)."), "offset": a(I, min=0, desc="Rows to skip.")},
           "The calibration records, newest first, with who, when, how they ended and whether they can be restored.", log=False),
        Op("machine.history.get", _get, READ, {"id": a(S, True, desc="Record id.")},
           "One record complete, and what a restore would need: restorable, the values it can put back (before / after), the role needed and "
           "the state of the files the record wrote (clean, changed, missing).", log=False),
        Op("machine.history.compare", _compare, READ, {"a": a(S, True, desc="Record id."), "b": a(S, True, desc="Record id of the same kind.")},
           "Compares two records of the same kind: the values that differ (results and inputs, with the difference b - a) and, for height "
           "maps, the difference grid with its statistics (same grid required).", log=False),
        Op("machine.history.restore", _restore, WRITE,
           {"id": a(S, True, desc="Record id."), "which": a(S, choices=("before", "after"), desc="before = undo (default), after = re-apply. A snapshot of offsets only has after."),
            "kind": a(S, desc="The kind of the record (the registry asks for the administrator role from it). The service checks it against the record."),
            "accept_current": a(B, desc="The files changed since the record: make the plan over the current file after looking at the three-way table.")},
           "Builds a PLAN that puts back the values of a configuration record (nothing is written): show its diff and send plan_id to "
           "machine.config.apply with the plan's kind. Refused with reason file_changed (and the three-way table) when a file is neither as "
           "the record left it nor as it found it, unless accept_current."),
    ]
