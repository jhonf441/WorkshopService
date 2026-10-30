"""
History and safe saving of the machine configuration (WorkshopConfig plugin, 2026-10-11): copies the set of configuration files, saves several files at once without ever leaving one half-written, and provides a lock so that two screens do not save at the same time.

Usage: <params> C"snapshot"|"list"|"get"|"commit"|"lock"|"unlock"|"arm"|"confirm"|"rollback"|"restore"|"guard" [J"<hex>"|F"<json>"] [N"<reason>"] [I"<id>"] [T"<tx>"] [K"<screen>"] [S<sec>] [R1]

Actions (design: TallerPlugins/docs-internal/CONFIGURATOR.md 0, 3.8, 3.9, 3.12):

It works for any machine with RRF (2026-10-11, rule 0.0 of the design): the
set of files is NOT a fixed list of the workshop; the page builds it
following the M98s of config.g and sends it. Here it is only validated that
each path is inside the SD (0:/sys, 0:/macros, ...; not escaping with '..')
and outside the history itself / staging.

  C"snapshot" J"<hex of {"archivos": [...], "motivo", "quien", "rrf", "modo"}>"
              (or F"0:/<path of that JSON on the SD>" if it is too long for J)
              [N"<reason>"] [Q"<who>"] [V"<RRF version>"] [M"<mode>"]
      Copies those files to 0:/sys/workshop/config-history/<YYYYMMDD-HHMMSS>/
      (creating it if it does not exist) with manifest.json. Those that do not
      exist stay in "ausentes". Returns {"ok", "id", "archivos"}.
  C"list"
      {"ok", "snapshots": [{"id", "fecha", "motivo", "quien", "archivos"}]}, newest first.
  C"get" I"<id>"
      {"ok", "manifest": {...}} of the snapshot.
  C"commit" T"<tx>" [K"<screen>"]
      Reads 0:/sys/workshop/data/config-staging/<tx>/manifest.json:
        {"archivos": [{"ruta": "sys/config.g", "archivo": "<uploaded, optional>",
                       "sha": "<sha256 of what was uploaded>",
                       "sha_previous": "<sha256 of what was read>" | null (new file)}],
         "conjunto": ["sys/config.g", ...] (optional: the rest of the set
                     for the prior copy; those in "archivos" are added automatically),
         "motivo", "quien", "rrf", "modo"}
      Rejects if another screen holds the lock, if what was uploaded does not
      match its sha or if some file on the card is no longer the one that was
      read. If everything fits: snapshot, writes each file to a temporary +
      fsync, and only once all are written swaps them in with os.replace (if
      it fails halfway it puts the previous ones back). A journal
      (config-commit.json) allows finishing the rollback if the power is cut
      in the middle. It deletes the staging and notes it in Activity. Returns
      {"ok", "snapshot", "archivos", "sha"}.
  C"lock" K"<screen>" [Q"<who>"] [S<sec>]
      Takes or renews the lock (120 s by default, maximum 600).
  C"unlock" K"<screen>"
      Releases it (only the owner; an expired one can be released by anyone).

Rollback (2026-10-11, T3.4; state and logic in dsf/config_guard.py, the
thread that watches after the restart). All return {"ok", ..., "guard"}:
  C"arm" I"<id of the previous backup>" | T"<tx of the commit>" [S<sec, 300>]
         [J"<hex>"|F"<json>" checks {"placas": [1, 40], "ejes": 4,
          "calentadores": 2, "sondas": 1}] [Q"<who>"]
      Before the M999 that loads a new configuration. If after the restart
      the board starts with an error (state.startupError), stays halted,
      does not connect again, fails a check, or nobody confirms within S
      seconds: it restores that backup, restarts the board and notifies
      (Activity and phone). With a job in progress it never restarts:
      it disarms and notifies. If it was already armed without confirming,
      it keeps the oldest backup (the last one that worked) and renews the
      deadline.
  C"confirm" [Q"<who>"]           "everything works": disarms.
  C"rollback"                       goes back right now to the armed backup and restarts
                                    (ignoring the lock: emergency exit).
  C"restore" I"<id>" [S<sec>] [R1] [K"<screen>"]
      Restores any backup (first copying the current state). With S it arms
      the rollback to that copy; with R1 it restarts the board to load it.
  C"guard"                          state (same as plugin data configGuard).

Times as epoch integers (dsf-python leaves floats with 6 digits). Everything
lives in 0:/sys/workshop/ (the service's AppArmor; PluginManager deletes the
plugin folder on reinstall). It does not use system file locks.

"""
import paths
import hashlib
import json
import os
import re
import shutil
import time
from messages import M, J, B

SD = paths.SD

LOCK_SEC = 120
LOCK_MAX_SEC = 600

_RE_TX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RE_ID = re.compile(r"^\d{8}-\d{6}(-\d{1,3})?$")
MAX_FILES = 500


def _now():
    return int(time.time())  # integers: dsf-python leaves floats with 6 digits


# Test points (test_config.py changes them to simulate failures halfway)
def _replace(origin, destination):
    os.replace(origin, destination)


def _p(*parts):
    return os.path.join(SD, *parts)


def _history_dir():
    return _p("sys", "workshop", "config-history")


def _data_dir():
    return _p("sys", "workshop", "data")


def _lock_path():
    return os.path.join(_data_dir(), "config-lock.json")


def _daily_path():
    return os.path.join(_data_dir(), "config-commit.json")


def _staging_dir(tx):
    return os.path.join(_data_dir(), "config-staging", tx)


def _resp(**kw):
    return json.dumps(kw)


def _error(raw_text, **kw):
    return json.dumps(dict({"ok": False, "error": raw_text}, **kw))


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path_abs):
    if not os.path.isfile(path_abs):
        return None
    with open(path_abs, "rb") as f:
        return _sha(f.read())


def _fsync_dir(d):
    # on Linux the rename stays on the card only with an fsync of the folder;
    # on Windows (tests) a folder cannot be opened: it is ignored
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write(path_abs, payload):
    """Writes bytes and sends them to the card (without rename)."""
    with open(path_abs, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())


def _write_atomic(path_abs, payload):
    os.makedirs(os.path.dirname(path_abs), exist_ok=True)
    tmp = path_abs + ".wc-tmp"
    _write(tmp, payload)
    os.replace(tmp, path_abs)  # lock and journal: they do not go through the test point
    _fsync_dir(os.path.dirname(path_abs))


def _normalize(route):
    """'0:/sys/config.g', '/macros/x.g', 'sys\\config.g' -> 'sys/config.g'.
    Cualquier archivo dentro de la SD (2026-10-11: sirve para cualquier
    maquina, no hay lista fija), sin '..', sin salir por un enlace (www es
    un enlace a ../dwc) y fuera del historial, el staging, el candado y el
    diario de este mismo handler. None si no vale."""
    r = str(route or "").strip().replace("\\", "/")
    if r.startswith("0:"):
        r = r[2:]
    if not r or "\x00" in r or ":" in r:
        return None  # otra unidad (1:/...) o algo raro
    parts = [p for p in r.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    r = "/".join(parts)
    if r.endswith((".wc-tmp", ".wc-back")):
        return None
    if r.startswith("sys/workshop/config-history/") or r == "sys/workshop/config-history":
        return None
    if r.startswith("sys/workshop/data/config-"):
        return None  # staging, candado y diario
    root = os.path.realpath(SD)
    real = os.path.realpath(_abs(r))
    if os.path.commonpath([root, real]) != root or real == root:
        return None
    return r


def _abs(rel):
    return _p(*rel.split("/"))


def _items_paths(value):
    """Received list of paths -> (normalized paths without repeats, bad one or None)."""
    if not isinstance(value, list):
        return None, M("config_not_a_list")
    output = []
    for v in value:
        r = _normalize(v)
        if not r:
            return None, str(v)
        if r not in output:
            output.append(r)
    if len(output) > MAX_FILES:
        return None, M("config_more_than_files", MAX_FILES=MAX_FILES)
    return output, None


# ---- snapshots ----

def _new_id():
    base = time.strftime("%Y%m%d-%H%M%S", time.localtime(_now()))
    hist = _history_dir()
    ident, n = base, 1
    while os.path.exists(os.path.join(hist, ident)):
        n += 1
        ident = f"{base}-{n}"
    return ident


def snapshot(paths_requested, reason, who="", rrf="", kind="", tx=None):
    """Copies the paths (already normalized) and returns the manifest. It is built
    in a temporary folder and renamed at the end: one is never left half-done.
    It creates sys/workshop/config-history if it does not exist (nothing is assumed)."""
    paths = sorted(r for r in set(paths_requested) if os.path.isfile(_abs(r)))
    absent = sorted(r for r in set(paths_requested) if not os.path.isfile(_abs(r)))
    hist = _history_dir()
    os.makedirs(hist, exist_ok=True)
    ident = _new_id()
    tmp_dir = os.path.join(hist, "." + ident + ".tmp")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    files = {}
    for r in paths:
        with open(_abs(r), "rb") as f:
            payload = f.read()
        destination = os.path.join(tmp_dir, *r.split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        _write(destination, payload)
        files[r] = {"sha": _sha(payload), "bytes": len(payload)}
    manifest = {
        "version": 1,
        "id": ident,
        "date": _now(),
        "reason": str(reason or ""),
        "who": str(who or ""),
        "rrf": str(rrf or ""),
        "mode": str(kind or ""),
        "files": files,
        # files the commit is going to create: going back to this snapshot = deleting them
        "absent": absent,
    }
    if tx:
        manifest["tx"] = tx
    os.makedirs(tmp_dir, exist_ok=True)
    _write(os.path.join(tmp_dir, "manifest.json"), json.dumps(manifest, indent=1).encode("utf-8"))
    os.replace(tmp_dir, os.path.join(hist, ident))
    _fsync_dir(hist)
    return manifest


def _read_manifest(ident):
    if not _RE_ID.match(str(ident or "")):
        return None
    try:
        with open(os.path.join(_history_dir(), ident, "manifest.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_items():
    hist = _history_dir()
    output = []
    if not os.path.isdir(hist):
        return output
    for n in os.listdir(hist):
        m = _read_manifest(n)
        if not m:
            continue
        output.append({
            "id": n,
            "date": int(m.get("date") or 0),
            "reason": m.get("reason", ""),
            "who": m.get("who", ""),
            "files": len(m.get("files") or {}),
        })
    output.sort(key=lambda s: (s["date"], s["id"]), reverse=True)
    return output


def _copy_of(ident, rel):
    with open(os.path.join(_history_dir(), ident, *rel.split("/")), "rb") as f:
        return f.read()


# ---- candado ----

def _read_lock():
    try:
        with open(_lock_path(), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if int(c.get("expires") or 0) <= _now():
        return None  # vencido = libre
    return c


def _lock_foreign(owner):
    c = _read_lock()
    if c and c.get("owner") != str(owner or ""):
        return c
    return None


def _msg_busy(c):
    who = c.get("who") or c.get("owner") or M("config_another_screen")
    sec = max(0, int(c.get("expires") or 0) - _now())
    return _error(
        M("config_another_screen_saving_configuration_try_again", who=who, sec=sec),
        busy=True, who=who, expires=int(c.get("expires") or 0),
    )


def take_lock(owner, who="", seconds=LOCK_SEC):
    owner = str(owner or "").strip()
    if not owner:
        return _error(M("config_screen_missing_for_lock"))
    foreign = _lock_foreign(owner)
    if foreign:
        return _msg_busy(foreign)
    try:
        sec = max(10, min(LOCK_MAX_SEC, int(float(seconds))))
    except (TypeError, ValueError):
        sec = LOCK_SEC
    previous = _read_lock()
    current_time = _now()
    c = {
        "owner": owner,
        "who": str(who or (previous or {}).get("who") or ""),
        "since": int((previous or {}).get("since") or current_time),
        "expires": current_time + sec,
    }
    os.makedirs(_data_dir(), exist_ok=True)
    _write_atomic(_lock_path(), json.dumps(c).encode("utf-8"))
    return _resp(ok=True, owner=owner, expires=c["expires"], seconds=sec)


def release_lock(owner):
    foreign = _lock_foreign(owner)
    if foreign:
        return _msg_busy(foreign)
    try:
        os.remove(_lock_path())
    except FileNotFoundError:
        pass
    return _resp(ok=True)


# ---- commit ----

def _register(bridge, raw_text):
    try:
        import activity
        activity.log_event(bridge, "config", raw_text)
    except Exception:
        pass  # it never prevents the saving


def recover():
    """If a journal was left (power cut in the middle of the renames), it leaves
    everything as it was in the previous snapshot. Returns the restored id or None."""
    try:
        with open(_daily_path(), encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        d = None
    if d:
        _revert(d.get("snapshot"), d.get("paths") or [], d.get("newItems") or [])
    try:
        os.remove(_daily_path())
    except OSError:
        pass
    for r in (d or {}).get("paths") or []:
        try:
            os.remove(_abs(r) + ".wc-tmp")
        except OSError:
            pass
    return (d or {}).get("snapshot")


def _revert(ident, paths, new):
    for r in paths:
        destination = _abs(r)
        if r in new:
            try:
                os.remove(destination)
            except FileNotFoundError:
                pass
            continue
        payload = _copy_of(ident, r)
        if _sha_file(destination) != _sha(payload):
            tmp = destination + ".wc-back"
            _write(tmp, payload)
            os.replace(tmp, destination)  # without the test point: the rollback is always real
            _fsync_dir(os.path.dirname(destination))


def _apply(changes, snap_id, tx):
    """Writes a set of changes without ever leaving one half-done
    (2026-10-11: taken out of commit so that restore uses the same thing).
    changes = [(rel, data)], data None = delete the file. snap_id is the
    copy of how everything was BEFORE (it must include every rel). Returns
    None if it went well or the error text (everything stays as before)."""
    paths = [c[0] for c in changes]
    new = [r for r in paths if not os.path.isfile(_abs(r))]  # volver = borrarlos

    # 1. all the temporaries written and on the card BEFORE the first rename
    tmps = []
    try:
        for rel, payload in changes:
            if payload is None:
                continue
            destination = _abs(rel)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            tmp = destination + ".wc-tmp"
            tmps.append(tmp)
            _write(tmp, payload)
    except Exception as e:
        for t in tmps:
            try:
                os.remove(t)
            except OSError:
                pass
        return M("config_could_not_save_previous_configuration_was", e=e)

    # 2. journal + renames (and deletions at the end); if something fails halfway, go back to the
    # previous ones
    os.makedirs(_data_dir(), exist_ok=True)
    _write_atomic(_daily_path(), json.dumps({"tx": tx, "snapshot": snap_id, "paths": paths, "newItems": new}).encode("utf-8"))
    try:
        for rel, payload in changes:
            if payload is None:
                continue
            destination = _abs(rel)
            _replace(destination + ".wc-tmp", destination)
            _fsync_dir(os.path.dirname(destination))
        for rel, payload in changes:
            if payload is None and os.path.isfile(_abs(rel)):
                os.remove(_abs(rel))
                _fsync_dir(os.path.dirname(_abs(rel)))
    except Exception as e:
        recover()
        return M("config_could_not_save_previous_configuration_was_2", e=e)
    try:
        os.remove(_daily_path())
    except OSError:
        pass
    return None


def commit(tx, owner="", bridge=None):
    tx = str(tx or "").strip()
    if not _RE_TX.match(tx):
        return _error(M("config_valid_t_tx_missing_letters_numbers"))
    foreign = _lock_foreign(owner)
    if foreign:
        return _msg_busy(foreign)
    # if a previous commit was left cut, first finish its rollback
    recover()
    stage = _staging_dir(tx)
    try:
        with open(os.path.join(stage, "manifest.json"), encoding="utf-8") as f:
            request = json.load(f)
    except (OSError, ValueError):
        return _error(M("config_i_did_not_find_save_request", tx=tx))

    entries = request.get("files") if isinstance(request, dict) else None
    if not isinstance(entries, list) or not entries:
        return _error(M("config_save_request_has_no_files"))
    group, bad = _items_paths(request.get("set") or [])
    if group is None:
        return _error(M("config_path_not_allowed", path=bad))

    # 1. validate everything before touching anything
    changes = []  # (rel, datos, sha_nuevo, nuevo)
    seen = set()
    conflicts = []
    for a in entries:
        rel = _normalize((a or {}).get("path"))
        if not rel:
            return _error(M("config_path_not_allowed", path=(a or {}).get('path')))
        if rel in seen:
            return _error(M("config_file_repeated_in_request", rel=rel))
        seen.add(rel)
        uploaded = str(a.get("file") or rel).replace("\\", "/").lstrip("/")
        uploaded_abs = os.path.realpath(os.path.join(stage, *uploaded.split("/")))
        if ".." in uploaded.split("/") or os.path.commonpath([os.path.realpath(stage), uploaded_abs]) != os.path.realpath(stage):
            return _error(M("config_path_not_allowed", path=uploaded))
        try:
            with open(uploaded_abs, "rb") as f:
                payload = f.read()
        except OSError:
            return _error(M("config_uploaded_file_missing", rel=rel))
        if _sha(payload) != str(a.get("sha") or "").lower():
            return _error(M("config_file_uploaded_arrived_incomplete_different_save", rel=rel))
        previous = str(a.get("sha_previous")).lower() if a.get("sha_previous") else None
        in_disk = _sha_file(_abs(rel))
        if previous != in_disk:
            conflicts.append(rel)  # null = the file was not supposed to exist
        changes.append((rel, payload, _sha(payload), in_disk is None))
    if conflicts:
        return _error(
            M("config_someone_changed_files_after_read", files=", ".join(conflicts)),
            conflict=conflicts,
        )

    # 2. copy of the set the page sent + the files that change
    paths = [c[0] for c in changes]
    snap = snapshot(
        group + paths,
        request.get("reason") or f"Before saving ({tx})",
        who=request.get("who", ""), rrf=request.get("rrf", ""), kind=request.get("mode", ""),
        tx=tx,
    )

    # 3 and 4: temporaries, journal and renames (_apply, shared with restore)
    err = _apply([(c[0], c[1]) for c in changes], snap["id"], tx)
    if err:
        return _error(err, snapshot=snap["id"])

    shutil.rmtree(stage, ignore_errors=True)
    _register(bridge, M("config_saved", paths=", ".join(paths), id=snap["id"]))
    return _resp(ok=True, snapshot=snap["id"], files=paths, sha={c[0]: c[2] for c in changes})


# ---- restaurar un respaldo (2026-10-11, T3.4) ----

def restore(ident, reason="", who="", bridge=None, owner=None, register=True):
    """Takes the files back to the backup ident with the same atomic saving
    as commit: first it copies how everything is now (so that what is taken
    out can be recovered), writes the backup's files and deletes those the
    backup did not have ("ausentes": a later save created them).
    It does not restart the board nor look at whether there is a job: that is done by
    the caller (run / config_guard). owner=None does not look at the lock
    (automatic rollback: safety comes first). Returns a dict."""
    ident = str(ident or "").strip()
    m = _read_manifest(ident)
    if not m:
        return {"ok": False, "error": M("config_backup_does_not_exist", ident=ident)}
    if owner is not None:
        foreign = _lock_foreign(owner)
        if foreign:
            return json.loads(_msg_busy(foreign))
    recover()
    files = m.get("files") or {}
    paths_m, bad = _items_paths(list(files.keys()) + list(m.get("absent") or []))
    if paths_m is None:
        return {"ok": False, "error": M("config_path_not_allowed_in_backup", ident=ident, path=bad)}
    changes = []
    for rel in paths_m:
        if rel in files:
            try:
                payload = _copy_of(ident, rel)
            except OSError:
                return {"ok": False, "error": M("config_backup_incomplete", ident=ident, rel=rel)}
            if _sha(payload) != str((files[rel] or {}).get("sha") or ""):
                return {"ok": False, "error": M("config_backup_damaged", ident=ident, rel=rel)}
            if _sha_file(_abs(rel)) != _sha(payload):
                changes.append((rel, payload))
        elif os.path.isfile(_abs(rel)):
            changes.append((rel, None))  # it did not exist in the backup
    if not changes:
        return {"ok": True, "snapshot": None, "files": [], "without_changes": True, "restored": ident}
    paths = [c[0] for c in changes]
    previous = snapshot(paths_m, f"Before restoring {ident}" + (f" ({reason})" if reason else ""), who=who)
    err = _apply(changes, previous["id"], "restore-" + ident)
    if err:
        return {"ok": False, "error": err, "snapshot": previous["id"]}
    if register:
        _register(bridge, M("config_restored", id=ident, paths=", ".join(paths), previous=previous["id"]))
    return {"ok": True, "snapshot": previous["id"], "files": paths, "restored": ident}


def _api():
    """What config_guard uses from this module (the thread and the handler
    share the same state in config-guard.json)."""
    import types
    return types.SimpleNamespace(
        SD=SD, restore=restore, read_manifest=_read_manifest, list_items=list_items,
        data_dir=_data_dir, write_atomic=_write_atomic, current_time=_now,
    )


# ---- entrada API call ----

def _json_param(params):
    """J"<hex of the JSON>" or F"0:/<path on the SD of a JSON>" (for long lists:
    a very long DSF code fails, see lights.py)."""
    f = str(params.get("F", "") or "").strip()
    if f:
        rel = _normalize(f)
        if not rel:
            raise ValueError("F outside the SD")
        with open(_abs(rel), encoding="utf-8") as fh:
            return json.load(fh)
    j = params.get("J")
    if isinstance(j, (dict, list)):
        return j  # API: the object itself
    return json.loads(bytes.fromhex(str(j or "")).decode("utf-8"))


def run(params, bridge, config):
    action = str(params.get("C", "list")).strip().lower()
    try:
        recover()
    except Exception:
        pass

    if action == "snapshot":
        try:
            request = _json_param(params)
        except Exception:
            return _error(M("config_file_list_missing"))
        if isinstance(request, list):
            request = {"files": request}
        if not isinstance(request, dict):
            return _error(M("config_file_list_missing"))
        paths, bad = _items_paths(request.get("files"))
        if paths is None:
            return _error(M("config_path_not_allowed", path=bad))
        if not paths:
            return _error(M("config_list_files_empty"))
        m = snapshot(
            paths,
            params.get("N") or request.get("reason") or "Manual copy",
            who=params.get("Q") or request.get("who", ""),
            rrf=params.get("V") or request.get("rrf", ""),
            kind=params.get("M") or request.get("mode", ""),
        )
        return _resp(ok=True, id=m["id"], files=len(m["files"]), absent=m["absent"])

    if action == "list":
        return _resp(ok=True, snapshots=list_items())

    if action == "get":
        m = _read_manifest(str(params.get("I", "")).strip())
        if not m:
            return _error(M("config_backup_does_not_exist", ident=params.get('I', '')))
        return _resp(ok=True, manifest=m)

    if action == "commit":
        return commit(params.get("T", ""), params.get("K", ""), bridge)

    if action == "lock":
        return take_lock(params.get("K", ""), params.get("Q", ""), params.get("S", LOCK_SEC))

    if action == "unlock":
        return release_lock(params.get("K", ""))

    # rollback (2026-10-11, T3.4): the logic and the state live in config_guard.py
    if action in ("arm", "confirm", "rollback", "restore", "guard"):
        import config_guard
        api = _api()
        if action == "arm":
            checks = None
            if params.get("J") or params.get("F"):
                try:
                    checks = _json_param(params)
                except Exception:
                    return _error(M("config_checks_badly_written"))
            r = config_guard.arm(
                api, bridge, config, ident=params.get("I", ""), tx=params.get("T", ""),
                deadline=params.get("S", config_guard.DEADLINE_S), checks=checks, who=params.get("Q", ""),
            )
        elif action == "confirm":
            r = config_guard.confirm(api, bridge, config, who=params.get("Q", ""))
        elif action == "rollback":
            r = config_guard.revert_by_hand(api, bridge, config, who=params.get("Q", ""))
        elif action == "restore":
            r = config_guard.restore_backup(
                api, bridge, config, params.get("I", ""), deadline=params.get("S", 0),
                restart=str(params.get("R", "0")).strip() not in ("", "0", "0.0"),
                who=params.get("Q", ""), owner=params.get("K", ""),
            )
        else:
            r = dict(config_guard.state_public(api), ok=True)
        return json.dumps(r)

    return _error(M("config_unknown_action", action=action))
