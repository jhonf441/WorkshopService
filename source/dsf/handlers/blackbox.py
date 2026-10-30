"""
Internal implementation of the API operation(s) blackbox.status, blackbox.lines, blackbox.note, blackbox.hide, blackbox.show (api_ops.py maps their named
arguments to the one-letter parameters below).

Service black box (dsf/black_box.py): a line of load, CPU, RAM,
temperature and state every 5 s in 0:/sys/workshop/data/blackbox/, and the
report of the Pi's last unclean shutdown.

Usage: <params>                    -> state (JSON)
     <params> S"lines" N<20>     -> last N lines (max 200)
     <params> S"note" T"<text>" -> notes an event (macros)
     <params> S"hide"            -> hides the card of the last unclean shutdown
     <params> S"show"            -> shows it again

"""
import json

import black_box
from messages import M


def run(params, bridge, config):
    action = str(params.get("S", "status")).strip().lower()
    c = black_box._box["c"]
    if c is None:
        return M("blackbox_error_black_box_not_active_config")
    if action in ("hide", "hide"):
        black_box.hide(bridge)
        return M("blackbox_unclean_shutdown_report_hidden")
    if action in ("show", "show"):
        if black_box.show(bridge) is None:
            return M("blackbox_there_no_report_unclean_shutdown")
        return M("blackbox_unclean_shutdown_report_visible_again")
    if action in ("note", "note"):
        raw_text = str(params.get("T") or "").strip()
        if not raw_text:
            return M("blackbox_error_text_missing")
        black_box.event("note", raw_text)
        return M("blackbox_noted_in_black_box")
    if action in ("lines", "lines"):
        try:
            n = max(1, min(200, int(float(params.get("N") or 20))))
        except (TypeError, ValueError):
            n = 20
        return "\n".join(c.last_lines(n))
    rep = c.report()
    return json.dumps({
        "folder": "0:/" + black_box.PATH_SD,
        "interval_s": c.cfg["interval_s"],
        "fsync_s": c.cfg["fsync_s"],
        "file_kb": int(c.max_bytes / 1024),
        "active": black_box.FILES[c.is_active],
        "last_report": {k: rep.get(k) for k in ("detected", "last_datum", "seen")} if rep else None,
    }, ensure_ascii=False)
