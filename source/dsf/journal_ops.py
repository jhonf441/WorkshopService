"""The `journal.read` operation (layer L5): registers journal_view.read in the API. Read-only; the rules are in journal_view.py."""
import journal_view
import log_sources
from workshop_api import READ, Arg, Op


def ops(install_runs):
    """install_runs(limit) gives the runs of the start-up (startup_ops.install_runs, handed over by api_ops: this module does not import the database)."""
    def _op(args, ctx):
        return journal_view.read(args.get("unit") or "duetcontrolserver", args.get("since") or "1h", args.get("level") or "all",
                                 args.get("search") or "", args.get("lines") or journal_view.DEFAULT_LINES,
                                 runs_loader=lambda: install_runs(log_sources.INSTALL_RUNS), noise=args.get("noise") or "hide")

    return [
        Op("journal.read", _op, READ,
           {"unit": Arg("str", choices=tuple(journal_view.UNITS) + log_sources.SOURCES, desc="Which log: a Duet or workshop unit, NetworkManager, ssh, the kernel, or the workshop's own files: workshop-service (the service log) and install (the start-up runs). Default duetcontrolserver."),
            "since": Arg("str", choices=tuple(journal_view.WINDOWS), desc="How far back: 15min, 1h (default), 6h, 24h or 7d."),
            "level": Arg("str", choices=tuple(journal_view.LEVELS), desc="Lowest level shown: all (default), notice, warning or error (that level and the worse ones)."),
            "search": Arg("str", desc="Text the line (or its program name) must contain, any case; it is data, never passed to a program."),
            "lines": Arg("int", min=10, max=journal_view.MAX_LINES, desc="Most lines returned (default 200); the last ones are kept."),
            "noise": Arg("str", choices=journal_view.NOISE_MODES, desc="hide (default) leaves out a few known harmless lines (Wi-Fi driver frames, a .NET Wi-Fi 7 warning, AppArmor profiles loaded at boot); show keeps them, flagged noise.")},
           "Reads the system journal of one unit of a closed list (or the kernel), or one of the workshop's own logs, read-only. Returns {readable, lines: [{t: epoch ms, p: 0-7, who, text, noise?}], "
           "truncated, noise_hidden}; when the service cannot read the journal, {readable: false, reason: no_permission | failed | no_journalctl | no_file}.",
           log=False, slow=True),
    ]
