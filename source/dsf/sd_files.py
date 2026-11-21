"""
sd_files -- READ ONLY list of the files every workshop plugin brings, with their state on the SD (the "files per plugin" viewer).

It groups the rows of sd_integrity.check() by the plugin that ships each file and gives every row one normal `status`, so the page does
not have to know the per-kind states of the integrity report:

  ok        the file is what the manifest expects (owned: factory sha; template/native/external: present; generated: mark matches)
  edited    a workshop-owned file that differs from the factory copy
  missing   a file that should be there and is not (a template the person deleted carries created_before: the wizard will not recreate it)
  not_yet   a generated file the service has not written yet (normal, not counted as missing)
  attention anything else that needs a look (wrong or old mark, comments only, unreadable)

Nothing here writes: it calls sd_integrity.check, which only lists and opens files for reading.
"""
import sd_integrity

STATUSES = ("ok", "edited", "missing", "not_yet", "attention")
_PRESENT = ("ok", "edited", "attention")  # the file exists on the SD
_MISSING = {"deleted", "missing"}


def status_of(row):
    """The normal status of one row of sd_integrity.check()."""
    s = row["state"]
    if s == "ok":
        return "ok"
    if s == "edited":
        return "edited"
    if s in _MISSING:
        return "missing"
    if s == "absent":
        return "not_yet"
    return "attention"


def _entry(row):
    out = {"path": row["path"], "kind": row["kind"], "status": status_of(row), "state": row["state"],
           "used_by": row.get("used_by", []), "safety": bool(row.get("safety"))}
    if row.get("sha_found"):
        out["sha"] = row["sha_found"]  # the content on the SD now: "leave it as it is" is remembered against this
    if row.get("created_before"):
        out["created_before"] = True
    if row.get("breaks_if_missing"):
        out["breaks_if_missing"] = row["breaks_if_missing"]
    return out


def mark_reviewed(out, accepted):
    """Sets `reviewed` on every file of a listing whose current sha is the one the person accepted ({path: sha}); a file that changed again is not."""
    for p in out["plugins"]:
        for f in p["files"]:
            f["reviewed"] = bool(f.get("sha")) and accepted.get(f["path"]) == f["sha"]
    return out


def counts(files):
    """expected = every file the plugin brings; present = on the SD (ok, edited or odd); the rest as named."""
    c = {"expected": len(files), "present": 0, "ok": 0, "edited": 0, "missing": 0, "not_yet": 0, "attention": 0}
    for f in files:
        c[f["status"]] += 1
        if f["status"] in _PRESENT:
            c["present"] += 1
    return c


def listing(sd=None, manifest=None, plugin=None):
    """Plugins in alphabetical order, each with its files and counts; `extras` are files of the workshop folders that no entry lists."""
    report = sd_integrity.check(sd, manifest)
    versions = report.get("plugins") or {}
    groups, extras = {}, []
    for row in report["files"]:
        if row["kind"] == "unknown":
            extras.append(row["path"])
        elif row.get("plugin"):
            groups.setdefault(row["plugin"], []).append(_entry(row))
    out = []
    for name in sorted(groups):
        if plugin and name != plugin:
            continue
        files = sorted(groups[name], key=lambda f: f["path"])
        out.append({"plugin": name, "version": versions.get(name), "counts": counts(files), "files": files})
    total = counts([f for p in out for f in p["files"]])
    return {"read_only": True, "manifest_schema": report["manifest_schema"], "plugins": out, "extras": [] if plugin else extras, "total": total}
