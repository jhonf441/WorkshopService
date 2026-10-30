"""
Internal implementation of the API operation(s) db.status, db.backup, db.places, db.folder, db.delete_previous, db.keep, db.settings (api_ops.py maps their named
arguments to the one-letter parameters below).

Service database: backups and state (see dsf/db_backup.py).

Usage: <params>                              state (JSON): database, backups, maintenance
     <params> S"respaldar"                 a backup now
     <params> S"lugares"                   where they can be stored (Pi card, USB drives)
     <params> S"carpeta" D"<path>"         changes the folder: copies the existing backups
     <params> S"delete_previous"         deletes those of the previous folder (already copied)
     <params> S"conservar" F"<file>" [V0]   a backup is never deleted on its own (V0 releases it)
     <params> S"ajustes" [A1|A0] [N<daily>] [W<weekly>] [R1|R0 summarize old consumption]
                                                [E"auto"|"no"|"<path>" copy in another place: USB drive]

"""
import json

import db_backup
import db
import messages


def _dumps(obj, **kw):
    """JSON of the answer with every message (a backup failure noted earlier) in the language of the request."""
    return json.dumps(messages.localize(obj, messages.current_language()), **kw)


def run(params, bridge, config):
    action = str(params.get("S", "state")).strip().lower() or "state"
    if action == "state":
        return _dumps(db.state_base(), ensure_ascii=False)
    if action == "backup":
        return _dumps(db_backup.back_up("by hand"), ensure_ascii=False)
    if action == "places":
        return _dumps(db_backup.places(), ensure_ascii=False)
    if action == "folder":
        return _dumps(db_backup.change_folder(params.get("D", "")), ensure_ascii=False)
    if action == "delete_previous":
        return _dumps(db_backup.delete_previous(), ensure_ascii=False)
    if action == "keep":
        v = params.get("V")
        return _dumps(db_backup.keep(params.get("F", ""), str(v) not in ("0", "0.0") if v not in (None, "") else True),
                          ensure_ascii=False)
    if action == "settings":
        r = params.get("R")
        a = params.get("A")
        n = params.get("N")
        w = params.get("W")
        e = params.get("E")
        return _dumps(db_backup.adjust(None if a in (None, "") else str(a) not in ("0", "0.0"),
                                                None if n in (None, "") else float(n), None if w in (None, "") else float(w),
                                                None if r in (None, "") else str(r) not in ("0", "0.0"),
                                                None if e in (None, "") else str(e)),
                          ensure_ascii=False)
    return "Error: unknown database action"
