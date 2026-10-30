"""
Automatic backups and maintenance of the database (2026-10-10:
"tell me if it has active backups; redesign it; in the Pi service make it
visible that they work; a place where space can be increased; what happens
if one day I want to move it, what happens to what is there").

- One backup per day (at startup if the last one is more than 24 h old, and
  then every 24 h): a consistent copy with SQLite's backup API (it works
  with the database in use), checked with quick_check, and since 2026-10-11
  together with the workshop folder (0:/sys/workshop/config, data and zones)
  in a single workshop-YYYYMMDD-HHMMSS.tar.gz (inside: duet.db, config/,
  data/, zones/). backups/ and the camera (0:/workshop/camera: they weigh GB)
  are not included, nor the keys (/opt/dsf/conf: they are put back by hand).
  The earlier duet-*.db.gz (database only) remain in the list and in the
  rotation. Before writing, the free space is checked; if it is not enough, it
  fails with a notice.
- Copy in another place (mirror, 2026-10-11: "the database and the backup
  should not share the same path"): the Pi's card has the database AND the
  backups; if the card dies both are lost. With mirror "auto" each backup is
  also copied to the first connected USB drive (or to the card, if the main
  folder is already a drive). From the mirror only what is deleted from the
  main folder is deleted (with a notice). status()["same_card"] warns if
  everything is on the Pi's card.
- If the drive is removed (2026-10-11, "what happens if the usb is removed"):
  * it was the main folder: the backups continue, on the Pi's card
    (FOLDER_DEF), with ONE notice to the phone; when the drive comes back, the
    ones made in the meantime are copied to the drive (checked) and deleted
    from the card only if the card is not the mirror;
  * it was the mirror: the main folder stays the same, ONE notice to the
    phone, and when it comes back all the ones it lacks are copied.
- The last `daily` (7) are kept and, of the older ones, one per week of the
  last `weekly` (4). Those that fall out of that count are NOT deleted at
  once (workshop rule: nothing is deleted on its own without a notice): they
  stay "to delete" with a date (wait_h, 48 h), a notice arrives on the phone
  (type base_deleted) and they can be kept (S"conservar" F"<file>"); if
  nobody does anything they are deleted.
- If a backup fails, a notice to the phone (type base_backup).
- Configurable folder: by default the Pi's card (0:/workshop/backups); it can
  be a USB drive (/media/...). When changing it, the existing backups are
  COPIED to the new one and checked; those in the previous folder stay where
  they are until someone asks to delete them (delete_previous).
- Maintenance: meter readings older than 90 days are kept once per hour
  (db.prune_consumption). A notice with a date (wait_h) is sent to the phone
  first, and it is only summarized if there is a backup made AFTER the notice
  (that backup keeps the detail). To never summarize: S"ajustes" R0. Once a
  week the database is compacted if it has unused space (db.compact).

config.json "base_backup": {activo, carpeta, folder_previous, diarios,
semanales, wait_h, summarize_consumption, conservados[]}; what is pending in
maintenance goes in maintenance.json (per_delete, prune_pending).
Control: the API (base) (handlers/base.py).

"""
import paths
import datetime
import glob
import json
import os
import re
import shutil
import sqlite3
import tarfile
import threading
import time

import db
import health_history
from messages import M, J, B, Msg

FOLDER_DEF = os.path.join(db.FOLDER_DATA, "backups")
DEFAULT = {"active": True, "folder": FOLDER_DEF, "folder_previous": None, "daily": 7, "weekly": 4,
           "wait_h": 48, "summarize_consumption": True, "kept": [], "mirror": "auto"}
EACH_S = 24 * 3600
ROOTS_ALLOWED = (paths.SD + "/", "/media/", "/mnt/")
PATTERNS = ("workshop-*.tar.gz", "duet-*.db.gz")  # the second: the earlier ones (database only)
INCLUDE = ("config", "data", "zones")  # folders of 0:/sys/workshop that go with the database
MARGIN = 50 * 1048576  # free space left on the disk after writing
STATE_FILE = os.path.join(os.path.dirname(db.DB_FILE), "maintenance.json")

_st = {"config": None, "bridge": None, "log": print, "failures": [], "busy": False}
_lock = threading.Lock()


def _cfg():
    c = dict(DEFAULT)
    if _st["config"] is not None:
        c.update(_st["config"].get("base_backup") or {})
    c["daily"] = max(1, min(60, int(c.get("daily") or 7)))
    c["weekly"] = max(0, min(52, int(c.get("weekly") or 0)))
    c["wait_h"] = max(1, min(24 * 14, int(c.get("wait_h") or 48)))
    c["kept"] = list(c.get("kept") or [])
    return c


def _save_cfg(c):
    if _st["config"] is None:
        return
    _st["config"]["base_backup"] = {k: c.get(k) for k in DEFAULT}
    try:
        _st["bridge"].save_config()
    except Exception as e:
        _st["log"](f"base: could not save config.json ({e!r})")


def _log(t):
    _st["log"]("base: " + t)


def _items(folder=None):
    folder = folder or _cfg()["folder"]
    out = []
    if not folder:
        return out
    files = [f for pat in PATTERNS for f in glob.glob(os.path.join(folder, pat))]
    for f in sorted(files, key=_date_name, reverse=True):
        try:
            out.append({"file": os.path.basename(f), "mb": round(os.path.getsize(f) / 1048576, 2),
                        "date": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(f))), "ts": int(os.path.getmtime(f))})
        except OSError:
            pass
    return out


def _date_name(f):
    m = re.search(r"\d{8}-\d{6}", os.path.basename(f))
    return m.group(0) if m else ""


def _in_memory_connected(folder):
    """/media/... or /mnt/...: True only if the drive is mounted (otherwise it would
    write to the Pi's card thinking it is the drive)."""
    if not folder.startswith(("/media/", "/mnt/")):
        return True
    d = os.path.normpath(folder)
    while d not in ("/", "", "/media", "/mnt"):
        if os.path.ismount(d):
            return True
        d = os.path.dirname(d)
    return False


def _in_card(folder):
    return not folder or not folder.startswith(("/media/", "/mnt/"))


def _main(c):
    """(folder written to today, True if it is the replacement because the drive is not there)."""
    if _in_memory_connected(c["folder"]):
        return c["folder"], False
    return FOLDER_DEF, True


def _all(c):
    """List of the main folder and, if its drive is not there, the replacement one."""
    dst, replacement = _main(c)
    return _items(dst) if replacement else _items(c["folder"])


def _absences(c):
    """One notice each time a drive goes missing (not one per cycle) and
    brought up to date when it comes back."""
    m = _mant_read()
    change = False
    _, replacement = _main(c)
    if replacement and not m.get("without_main"):
        m["without_main"] = int(time.time())
        change = True
        _notify("base_backup", M("db_main_disconnected", folder=c["folder"], default=FOLDER_DEF))
    elif not replacement and m.get("without_main"):
        m.pop("without_main")
        change = True
        _bring_up_to_date(c)
    esp = _mirror(c)
    kind = c.get("mirror") or "no"
    if esp:
        if m.get("mirror_seen") != esp or m.get("without_mirror"):
            m["mirror_seen"] = esp
            m.pop("without_mirror", None)
            change = True
    elif kind != "no" and m.get("mirror_seen") and not m.get("without_mirror"):
        # there was a copy in another place and no longer: notified once
        m["without_mirror"] = int(time.time())
        change = True
        _notify("base_backup", M("db_mirror_disconnected", seen=m["mirror_seen"]))
    if change:
        _mant_save(m)


def _bring_up_to_date(c):
    """The main drive came back: the backups made on the card while it was not
    there (newer than the last one on the drive) are copied to the drive."""
    any_present = _items(c["folder"])
    latest = any_present[0]["file"] if any_present else ""
    names = set(x["file"] for x in any_present)
    esp = _mirror(c)
    moved = 0
    for x in reversed(_items(FOLDER_DEF)):
        if x["file"] in names or _date_name(x["file"]) <= _date_name(latest):
            continue
        src = os.path.join(FOLDER_DEF, x["file"])
        try:
            _copy_checked(src, os.path.join(c["folder"], x["file"]))
            moved += 1
            if not esp or os.path.normpath(esp) != os.path.normpath(FOLDER_DEF):
                os.remove(src)  # it is already (checked) on the drive; the card is not the mirror
        except OSError as e:
            _log(f"could not move {x['file']} to {c['folder']} ({e})")
    if moved:
        _log(f"backup storage back: {moved} backup(s) made on the card moved to {c['folder']}")


def _mirror(c):
    """Folder of the copy in another place, or None."""
    e = c.get("mirror")
    if e in (None, "", "no"):
        return None
    if e == "auto":
        if _in_card(c["folder"]):
            usb = [x for x in places()[1:] if x.get("writable")]
            e = usb[0]["folder"] if usb else None
        else:
            e = FOLDER_DEF
    if not e or os.path.normpath(e) == os.path.normpath(c["folder"]) or not _in_memory_connected(e):
        return None
    return e


def _size_folders():
    t = 0
    for d in INCLUDE:
        for root, _, files in os.walk(os.path.join(db.FOLDER_DATA, d)):
            for a in files:
                try:
                    t += os.path.getsize(os.path.join(root, a))
                except OSError:
                    pass
    return t


def _without_temp(ti):
    n = os.path.basename(ti.name)
    if n.endswith(".tmp") or ".tmp-" in n or n.startswith(".writable"):
        return None
    return ti


def _copy_checked(src, dst):
    shutil.copy2(src, dst + ".tmp")
    if os.path.getsize(dst + ".tmp") != os.path.getsize(src):
        os.remove(dst + ".tmp")
        raise OSError(M("db_backup_copy_came_out_another_size"))
    os.replace(dst + ".tmp", dst)


def _readable(path):
    """True when the whole file can be read. A card with a damaged sector answers OSError (EBADMSG, EIO) in the middle of a read:
    tarfile would already have written the header and a short member would make the archive unreadable, so the file is
    read through once before it is added."""
    try:
        with open(path, "rb") as fh:
            while fh.read(1048576):
                pass
        return True
    except OSError as e:
        _log(f"unreadable file left out of the backup: {path} ({e!r})")
        return False


def _add_tree(tf, folder, arc, skipped):
    """Adds a folder to the archive one file at a time. A file that cannot be read is left out and named in `skipped`; the rest is
    saved (a single bad file used to stop the whole backup, every retry, for as long as the file stayed on the card)."""
    ti = tf.gettarinfo(folder, arcname=arc)
    tf.addfile(ti)
    try:
        names = sorted(os.listdir(folder))
    except OSError as e:
        _log(f"unreadable folder left out of the backup: {folder} ({e!r})")
        skipped.append(arc)
        return
    for n in names:
        path = os.path.join(folder, n)
        sub = arc + "/" + n
        if _without_temp(tarfile.TarInfo(sub)) is None:
            continue
        if os.path.isdir(path) and not os.path.islink(path):
            _add_tree(tf, path, sub, skipped)
        elif _readable(path):
            try:
                tf.add(path, arcname=sub, recursive=False)
            except OSError as e:
                # cannot happen after _readable unless the card failed in between; the member was not written (header and data go together)
                _log(f"file left out of the backup: {path} ({e!r})")
                skipped.append(sub)
        else:
            skipped.append(sub)


def _flip(c):
    """Copies to the mirror the backups it lacks. A failure here does not make the backup fail."""
    dst = _mirror(c)
    _st["mirror_error"] = None
    if not dst:
        return
    try:
        os.makedirs(dst, exist_ok=True)
        any_present = set(x["file"] for x in _items(dst))
        for x in reversed(_items(c["folder"])):
            if x["file"] in any_present:
                continue
            src = os.path.join(c["folder"], x["file"])
            if shutil.disk_usage(dst).free < os.path.getsize(src) + MARGIN:
                raise OSError(M("db_backup_no_space"))
            _copy_checked(src, os.path.join(dst, x["file"]))
    except OSError as e:
        _st["mirror_error"] = f"{dst}: {e.strerror or e}"
        _failure(M("db_fail_copy", dst=dst, error=e.strerror or (e.args[0] if e.args and isinstance(e.args[0], Msg) else str(e)), folder=c["folder"]))


def _free_gb(folder):
    try:
        d = folder
        while d and not os.path.isdir(d):
            d = os.path.dirname(d)
        return round(shutil.disk_usage(d or "/").free / 1024 ** 3, 1)
    except OSError:
        return None


def _failure(t):
    # a message stays one: the API answer gives it in the language of the page that asks
    _st["failures"].insert(0, {"date": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": t})
    del _st["failures"][5:]
    _log(t)
    _notify("base_backup", M("db_backup_failure", reason=t))


def _notify(type_name, raw_text):
    """Activity + phone (notifier, according to the type)."""
    try:
        import activity
        activity.log_event(_st["bridge"], type_name, raw_text)
    except Exception as e:
        _log(f"could not record the warning ({e!r})")


def back_up(reason="daily"):
    """A backup now. {ok, file, mb} or {ok: False, error}."""
    if _st["busy"]:
        return {"ok": False, "error": M("db_backup_backup_already_being_made")}
    c = _cfg()
    _st["busy"] = True
    tmp = None
    skipped = []
    destination, replacement = _main(c)
    try:
        os.makedirs(destination, exist_ok=True)
        label = time.strftime("workshop-%Y%m%d-%H%M%S")
        # the database copy is opened with SQLite (it needs locks): in the
        # plugin folder, which the AppArmor profile does let lock
        tmp = os.path.join(db.BASE_DIR, "." + label + ".db.tmp")
        with db._lock:
            src = sqlite3.connect(db.DB_FILE, timeout=30)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                src.close()
        ok = dst.execute("PRAGMA quick_check").fetchone()[0]
        dst.close()
        if ok != "ok":
            _failure(M("db_fail_check", result=ok))
            return {"ok": False, "error": M("db_backup_copy_failed_check")}
        # uncompressed is the worst case: if that does not fit, it is not started
        needs = os.path.getsize(tmp) + _size_folders() + MARGIN
        idle = shutil.disk_usage(destination).free
        if idle < needs:
            _failure(M("db_fail_space", dst=destination, free=idle // 1048576, need=needs // 1048576))
            return {"ok": False, "error": M("db_backup_no_space")}
        final = os.path.join(destination, label + ".tar.gz")
        # 0600 from the moment it is created: it carries the database data and the configuration
        fd = os.open(final + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            with tarfile.open(fileobj=fh, mode="w:gz", compresslevel=6) as tf:
                tf.add(tmp, arcname="duet.db")
                for d in INCLUDE:
                    p = os.path.join(db.FOLDER_DATA, d)
                    if os.path.isdir(p):
                        _add_tree(tf, p, d, skipped)
            fh.flush()
            os.fsync(fh.fileno())  # to the card before the rename (power cut)
        os.replace(final + ".tmp", final)
        try:
            os.chmod(final, 0o600)  # on a FAT drive there are no permissions: it does not matter
        except OSError:
            pass
        mb = round(os.path.getsize(final) / 1048576, 2)
        _log(f"backup {reason} done: {final} ({mb} MB)" + (" -- on the card: the storage is missing" if replacement else ""))
        if skipped:
            _notify("base_backup", M("db_backup_skipped", n=len(skipped), names=", ".join(skipped[:3])))
        if not replacement:
            _rotate(c)
            _flip(c)
        return {"ok": True, "file": os.path.basename(final), "mb": mb, "skipped": skipped, "mirror": _mirror(c), "mirror_error": _st.get("mirror_error")}
    except Exception as e:
        _failure(M("db_fail_backup", error=str(e)))
        for f in glob.glob(os.path.join(destination, "*.gz.tmp")):
            try:
                os.remove(f)
            except OSError:
                pass
        return {"ok": False, "error": str(e)}
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        _st["busy"] = False


def _leftover(c):
    """Backups outside the count (last `daily` + the newest of each week of the
    last `weekly`), not counting the kept ones."""
    all_items = _items(c["folder"])
    remaining = set(x["file"] for x in all_items[:c["daily"]])
    weeks = {}
    for x in all_items[c["daily"]:]:
        week = datetime.date.fromtimestamp(x["ts"]).isocalendar()[:2]
        if week not in weeks and len(weeks) < c["weekly"]:
            weeks[week] = x["file"]
    remaining.update(weeks.values())
    return [x["file"] for x in all_items if x["file"] not in remaining and x["file"] not in c["kept"]]


def _rotate(c):
    """Marks what is left over with a date and notice, unmarks what is no longer
    left over and deletes what has expired (nobody kept it)."""
    if _main(c)[1]:
        return  # the drive is not there: nothing is marked or deleted until it comes back
    m = _mant_read()
    pb = m.get("per_delete") or {}
    leftover = _leftover(c)
    current_time = int(time.time())
    until = current_time + c["wait_h"] * 3600
    new = [a for a in leftover if a not in pb]
    for a in new:
        pb[a] = {"since": current_time, "until": until}  # int epoch (dsf-python writes floats with 6 digits)
    loose = [a for a in pb if a not in leftover]
    for a in loose:
        del pb[a]  # kept, deleted by hand or the count changed
    expired = [a for a, d in pb.items() if d["until"] <= current_time]
    for a in expired:
        pb.pop(a)
        for folder in (c["folder"], _mirror(c)):  # the mirror follows the main one
            if not folder:
                continue
            try:
                os.remove(os.path.join(folder, a))
                _log(f"old backup deleted: {folder}/{a} (warned and nobody kept it)")
            except OSError:
                pass
    if new or loose or expired:
        m["per_delete"] = pb
        _mant_save(m)
    if new:
        when = time.strftime("%d/%m %H:%M", time.localtime(until))
        _notify("base_deleted", M("db_to_delete", n=len(new), when=when, daily=c["daily"], weekly=c["weekly"]))


def keep(file, value=True):
    """A kept backup is never deleted on its own (nor does it count for the rotation)."""
    file = os.path.basename(str(file or ""))
    c = _cfg()
    if not os.path.exists(os.path.join(c["folder"], file)):
        return {"ok": False, "error": M("db_backup_backup_does_not_exist")}
    cons = [a for a in c["kept"] if a != file]
    if value:
        cons.append(file)
    c["kept"] = cons
    _save_cfg(c)
    _rotate(c)
    return {"ok": True, "keep": bool(value)}


def _check_prune(c, m):
    """Hourly summary of the old consumption, with a notice before. Returns True
    if maintenance.json changed."""
    if not c.get("summarize_consumption", True):
        if m.pop("prune_pending", None):
            return True
        return False
    current_time = int(time.time())
    pending_items = m.get("prune_pending")
    if not pending_items:
        n = db.consumption_by_summarize()
        if not n:
            return False
        limit = current_time - db.CONSUMPTION_DETAIL_DAYS * 86400
        until = current_time + c["wait_h"] * 3600
        m["prune_pending"] = {"limit": limit, "rows": n, "since": current_time, "until": until}
        day = time.strftime("%d/%m/%Y", time.localtime(limit))
        when = time.strftime("%d/%m %H:%M", time.localtime(until))
        _notify("base_deleted", M("db_to_summarize", day=day, when=when, n=n))
        return True
    if pending_items["until"] > current_time:
        return False
    entries = _items(c["folder"])
    if not entries or entries[0]["ts"] < pending_items["since"]:
        return False  # first a backup with the full detail
    n = db.prune_consumption(before_of=pending_items["limit"])
    _log(f"meter readings before {time.strftime('%Y-%m-%d', time.localtime(pending_items['limit']))}: {n} rows summarized per hour (after a warning)")
    m.pop("prune_pending", None)
    m["prune"] = current_time
    return True


def places():
    """Where they can be stored: the Pi's card and each mounted USB drive."""
    out = [{"name": M("db_backup_system_card"), "folder": FOLDER_DEF, "free_gb": _free_gb(FOLDER_DEF)}]
    for base in ("/media", "/mnt"):
        for m in sorted(glob.glob(os.path.join(base, "*")) + glob.glob(os.path.join(base, "*", "*"))):
            if os.path.ismount(m):
                out.append({"name": M("db_backup_usb_drive_name", name=os.path.basename(m)), "folder": os.path.join(m, "workshop-backups"),
                            "free_gb": _free_gb(m), "writable": os.access(m, os.W_OK)})
    return out


def change_folder(new):
    """Changes where they are stored. Copies (does not move) the existing backups
    and checks each copy; the previous folder stays until delete_previous()."""
    new = os.path.normpath(str(new or "").strip()).replace("\\", "/")
    if not any((new + "/").startswith(r) for r in ROOTS_ALLOWED):
        return {"ok": False, "error": M("db_backup_folder_must_be_on_card_or_drive")}
    c = _cfg()
    old = c["folder"]
    if os.path.normpath(old) == new:
        return {"ok": True, "copied": 0}
    try:
        os.makedirs(new, exist_ok=True)
        trial = os.path.join(new, ".writable")
        with open(trial, "w") as fh:
            fh.write("ok")
        os.remove(trial)
    except OSError as e:
        return {"ok": False, "error": M("db_backup_cannot_write_to", folder=new, error=str(e.strerror or e))}
    copied = 0
    for x in _items(old):
        src, dst = os.path.join(old, x["file"]), os.path.join(new, x["file"])
        try:
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            if os.path.getsize(dst) != os.path.getsize(src):
                raise OSError(M("db_backup_different_size"))
            copied += 1
        except OSError as e:
            return {"ok": False, "error": M("db_backup_could_not_copy_folder_was_not", file=x['file'], e=e)}
    c["folder_previous"] = old if _items(old) else None
    c["folder"] = new
    _save_cfg(c)
    _log(f"backup folder: {old} -> {new} ({copied} copied; the previous ones stay in {old})")
    return {"ok": True, "copied": copied, "folder_previous": c["folder_previous"]}


def delete_previous():
    """Deletes the backups of the previous folder (only the backups), once they
    are already copied to the new one."""
    c = _cfg()
    ant = c.get("folder_previous")
    if not ant:
        return {"ok": False, "error": M("db_backup_no_previous_folder")}
    new = set(x["file"] for x in _items(c["folder"]))
    deleted = 0
    for x in _items(ant):
        if x["file"] not in new:
            continue  # not copied to the new one: it is not touched
        try:
            os.remove(os.path.join(ant, x["file"]))
            deleted += 1
        except OSError:
            pass
    if not _items(ant):
        c["folder_previous"] = None
        _save_cfg(c)
    _log(f"deleted {deleted} backups of the previous folder {ant}")
    return {"ok": True, "deleted": deleted}


def adjust(is_active=None, daily=None, weekly=None, summarize=None, mirror=None):
    c = _cfg()
    if mirror is not None:
        e = str(mirror).strip()
        if e not in ("auto", "no"):
            e = os.path.normpath(e).replace("\\", "/")
            if not any((e + "/").startswith(r) for r in ROOTS_ALLOWED):
                return {"ok": False, "error": M("db_backup_mirror_must_be_on_card_or_drive")}
        c["mirror"] = e
    if summarize is not None:
        c["summarize_consumption"] = bool(summarize)
    if is_active is not None:
        c["active"] = bool(is_active)
    if daily is not None:
        c["daily"] = max(1, min(60, int(daily)))
    if weekly is not None:
        c["weekly"] = max(0, min(52, int(weekly)))
    _save_cfg(c)
    if c["active"]:
        _rotate(c)
    if mirror is not None and c["active"]:
        threading.Thread(target=_flip, args=(c,), daemon=True).start()
    return {"ok": True, "config": {k: c[k] for k in ("active", "daily", "weekly", "summarize_consumption", "mirror")}}


def _mant_read():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _mant_save(d):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    except OSError:
        pass


def status():
    c = _cfg()
    destination, replacement = _main(c)
    entries = _all(c)
    latest = entries[0] if entries else None
    m = _mant_read()
    esp = _mirror(c)
    items_esp = _items(esp) if esp else []
    return {
        "active": c["active"],
        "includes": ["duet.db"] + [d + "/" for d in INCLUDE],
        # the main folder's drive is not there: it is being saved to the card
        "folder_disconnected": replacement,
        "saving_en": destination,
        "mirror_disconnected": bool(not esp and (c.get("mirror") or "no") != "no" and m.get("without_mirror")),
        "mirror_seen": m.get("mirror_seen"),
        "mirror_mode": c.get("mirror") or "no",
        "mirror": esp,
        "mirror_amount": len(items_esp),
        "mirror_last": items_esp[0] if items_esp else None,
        "mirror_free_gb": _free_gb(esp) if esp else None,
        "mirror_error": _st.get("mirror_error"),
        # the database lives on the Pi's card: if the backups do too, a damaged card takes everything
        "same_card": _in_card(destination) and (not esp or _in_card(esp)),
        "folder": c["folder"],
        "folder_previous": c.get("folder_previous"),
        "previous": len(_items(c["folder_previous"])) if c.get("folder_previous") else 0,
        "daily": c["daily"],
        "weekly": c["weekly"],
        "last": latest,
        "next": (latest["ts"] + EACH_S) if (latest and c["active"]) else None,
        "late": bool(c["active"] and (not latest or time.time() - latest["ts"] > EACH_S + 3 * 3600)),
        "amount": len(entries),
        "mb_total": round(sum(x["mb"] for x in entries), 2),
        "free_gb": _free_gb(destination),
        "list": entries[:20],
        "failures": list(_st["failures"]),
        "busy": _st["busy"],
        "last_prune": m.get("prune"),
        "wait_h": c["wait_h"],
        "kept": c["kept"],
        "per_delete": [dict(d, file=a) for a, d in sorted((m.get("per_delete") or {}).items(), key=lambda x: x[1]["until"])],
        "summarize_consumption": c["summarize_consumption"],
        "prune_pending": m.get("prune_pending"),
        "last_compaction": m.get("compact"),
    }


def _cycle():
    c = _cfg()
    current_time = time.time()
    if c["active"]:
        _absences(c)
        entries = _all(c)
        if not entries or current_time - entries[0]["ts"] >= EACH_S:
            back_up("daily")
        elif not _main(c)[1]:
            _flip(c)  # the copy is back: it is brought up to date without waiting for the next backup
    if c["active"]:
        _rotate(c)  # what is marked expires even if today is not a backup day
    m = _mant_read()
    try:
        if _check_prune(c, m):
            _mant_save(m)
    except Exception as e:
        _log(f"could not summarize the old consumption ({e!r})")
    try:
        health_history.maintain()
    except Exception as e:
        _log(f"could not purge the health history ({e!r})")
    if current_time - (m.get("compact") or 0) >= 7 * 24 * 3600:
        try:
            mb = db.compact()
            if mb:
                _log(f"database compacted: {mb} MB freed")
        except Exception as e:
            _log(f"could not compact ({e!r})")
        m["compact"] = int(current_time)
        _mant_save(m)


def _loop():
    time.sleep(60)  # so the rest of the service starts first
    while True:
        try:
            _cycle()
        except Exception as e:
            _log(f"cycle: {e!r}")
        time.sleep(600)


def launch(config, bridge, log=print):
    _st.update(config=config, bridge=bridge, log=log)
    threading.Thread(target=_loop, name="base_backup", daemon=True).start()
