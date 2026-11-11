"""Service database administration behind the operations db.status, db.backup, db.places, db.folder, db.delete_previous, db.keep and
db.settings (service_ops.py registers them; phase 5 of the redesign, it replaces handlers/base.py).

A thin layer over db.py (state) and db_backup.py (backups, folders, rotation, settings): named, already validated arguments in, the
answer of db_backup out. A refused change is an answer with `ok: False` and an `error` text, as it always was, not an ApiError. The
settings are saved by db_backup itself (config["base_backup"] and bridge.save_config()).
"""
import db
import db_backup


def state():
    """Database file, sizes, rows per table, backups and a quick check; None when the file does not exist yet."""
    return db.state_base()


def back_up_now():
    return db_backup.back_up("by hand")


def places():
    """Where backups can be kept: the system card and every mounted USB drive."""
    return db_backup.places()


def change_folder(*, path):
    """Changes the backup folder: copies (does not move) the existing backups; the old folder stays until delete_previous()."""
    return db_backup.change_folder(path)


def delete_previous():
    """Deletes the backups of the previous folder that already have a copy in the current one."""
    return db_backup.delete_previous()


def keep(*, file, keep=True):
    """A kept backup is never deleted on its own; keep=False releases it."""
    return db_backup.keep(file, bool(keep))


def settings(*, auto=None, daily=None, weekly=None, summarize=None, extra_copy=None):
    """Changes the backup settings; an argument that is None (or an empty extra_copy) is left as it is."""
    return db_backup.adjust(None if auto is None else bool(auto),
                            None if daily is None else float(daily),
                            None if weekly is None else float(weekly),
                            None if summarize is None else bool(summarize),
                            None if extra_copy in (None, "") else str(extra_copy))
