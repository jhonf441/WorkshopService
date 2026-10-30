"""
API operations of the protection guard (protection_guard.py): guard.status (read) and guard.set (admin).
api_ops.py adds them to its table with one line.
"""
import protection_guard as pg
from workshop_api import ADMIN, READ, Arg, Op


def _ctx():
    import api_ops
    return api_ops._ctx


def _status(args, ctx):
    config = _ctx()["config"]
    return {"settings": pg.settings(config), "status": pg.status(), "degraded": pg.degraded()}


def _set(args, ctx):
    c = _ctx()
    config = c["config"]
    current = dict(config.get("guard") if isinstance(config.get("guard"), dict) else {})
    for k, v in args.items():
        if v is not None:
            current[k] = v
    config["guard"] = {k: v for k, v in pg.settings({"guard": current}).items()}
    if c["bridge"] is not None:
        c["bridge"].save_config()
    return {"settings": pg.settings(config)}


def ops():
    S, I, B, N = "str", "int", "bool", "num"
    lo = pg.LIMITS
    return [
        Op("guard.status", _status, READ, {},
           "Returns the state of the protection guard: which safety processes are expected, which are watched, which are down (degraded), "
           "and its settings. The same watch list is published in the data key guardStatus.", log=False),
        Op("guard.set", _set, ADMIN,
           {"enabled": Arg(B, desc="Turn the guard on or off (default on)."),
            "action": Arg(S, choices=pg.ACTIONS, desc="notify = only warn loudly when a fire or servo protection is down during a laser or CNC job (default); "
                                                      "pause = also pause a file job."),
            "external_tolerance_s": Arg(N, min=lo["external_tolerance_s"][0], max=lo["external_tolerance_s"][1],
                                        desc="Seconds without a sign of life before Vision or RS485 count as down (default 30)."),
            "tolerance_factor": Arg(N, min=lo["tolerance_factor"][0], max=lo["tolerance_factor"][1],
                                    desc="An internal process is late after this many times its expected pace (default 3)."),
            "grace_s": Arg(N, min=lo["grace_s"][0], max=lo["grace_s"][1],
                           desc="Extra seconds for the first heartbeat after a start or restart (default 60)."),
            "renotify_s": Arg(N, min=lo["renotify_s"][0], max=lo["renotify_s"][1],
                              desc="Debounce: the phone is not warned again about the same protection before these seconds (default 600).")},
           "Changes the settings of the protection guard. Saved."),
    ]
