"""Black box reads and notes behind the operations blackbox.status, blackbox.lines, blackbox.note, blackbox.hide and
blackbox.show (activity_ops.py registers them; phase 5 of the redesign, they replace handlers/blackbox.py).

The black box itself is black_box.py (a line of load, CPU, RAM, temperature and state every few seconds in
0:/sys/workshop/data/blackbox/, and the report of the last unclean shutdown). These functions take the running box (or the
bridge) and return what the operation answers: a dict for the state, a text for everything else. The refusal when the box is not
active belongs to the operation (it needs ApiError, which is a layer above).
"""
import black_box
from messages import M


def status(box):
    """State of the box: folder, intervals, size of a file, the file being written and the last unclean shutdown report."""
    rep = box.report()
    return {
        "folder": "0:/" + black_box.PATH_SD,
        "interval_s": box.cfg["interval_s"],
        "fsync_s": box.cfg["fsync_s"],
        "file_kb": int(box.max_bytes / 1024),
        "active": black_box.FILES[box.is_active],
        "last_report": {k: rep.get(k) for k in ("detected", "last_datum", "seen")} if rep else None,
    }


def lines(box, n=20):
    """The last n lines (1 to 200) as one text."""
    return "\n".join(box.last_lines(max(1, min(200, int(n)))))


def note(text):
    """Writes a note event (what a macro marks a moment with)."""
    black_box.event("note", str(text).strip())
    return M("blackbox_noted_in_black_box")


def hide(bridge):
    """Hides the card of the last unclean shutdown (the report file is never deleted)."""
    black_box.hide(bridge)
    return M("blackbox_unclean_shutdown_report_hidden")


def show(bridge):
    """Shows the card again."""
    if black_box.show(bridge) is None:
        return M("blackbox_there_no_report_unclean_shutdown")
    return M("blackbox_unclean_shutdown_report_visible_again")
