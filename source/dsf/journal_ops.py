"""The `journal.read` operation (layer L5): registers journal_view.read in the API. Read-only; the rules are in journal_view.py."""
import journal_view
from workshop_api import READ, Arg, Op


def _op(args, ctx):
    return journal_view.read(args.get("unit") or "duetcontrolserver", args.get("since") or "1h", args.get("level") or "all",
                args.get("search") or "", args.get("lines") or journal_view.DEFAULT_LINES)


def ops():
    return [
        Op("journal.read", _op, READ,
           {"unit": Arg("str", choices=tuple(journal_view.UNITS), desc="Which log: a Duet or workshop unit, NetworkManager, ssh or the kernel (default duetcontrolserver)."),
            "since": Arg("str", choices=tuple(journal_view.WINDOWS), desc="How far back: 15min, 1h (default), 6h, 24h or 7d."),
            "level": Arg("str", choices=tuple(journal_view.LEVELS), desc="Lowest level shown: all (default), notice, warning or error (that level and the worse ones)."),
            "search": Arg("str", desc="Text the line (or its program name) must contain, any case; it is data, never passed to a program."),
            "lines": Arg("int", min=10, max=journal_view.MAX_LINES, desc="Most lines returned (default 200); the last ones are kept.")},
           "Reads the system journal of one unit of a closed list (or the kernel), read-only. Returns {readable, lines: [{t: epoch ms, p: 0-7, who, text}], "
           "truncated}; when the service cannot read the journal, {readable: false, reason: no_permission | failed | no_journalctl}.",
           log=False, slow=True),
    ]
