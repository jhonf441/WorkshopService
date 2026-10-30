"""Optional laser interlocks (lid, extraction, key) read from Duet general purpose inputs (F3-S, 2026-10-21).

The owner may declare in the machine profile (machine_profile.py, `interlocks`) which input of the Duet reports each one:
`gpin` is the index N of `sensors.gpIn[N]` in the object model (an input made with M950 J<N>), `active_when` is the level
of the input at which the interlock is satisfied (lid closed, extraction running, key turned on) and `label` an optional name.

Without declared interlocks nothing here does anything: the manual checklist of the pages stays the only check.

  - state(): for every DECLARED interlock "ok" | "open" | "unknown" (unknown = the input is not in the object model, has
    no value, or the board is not reachable: it is treated as not ok, the safe side);
  - capability_of(name): the capability name the pages ask (lid_interlock...);
  - guarded(fn, laser_when): wraps the function of an API operation that turns the laser on: in Laser mode with a declared
    interlock that is not ok it raises the error `interlock_open`;
  - the process guard (protection_guard.InterlockWatch) uses state() to warn when one opens during a laser job.

THIS IS NOT THE PROTECTION OF THE MACHINE. The firmware must stop the laser by itself (M581 trigger, see docs/INTERLOCKS.md);
this only refuses the starts that come through the API and warns the people.

The object model comes from the single subscription (machine_state: "sensors.**" is in its filters): no polling, no request.
"""
import functools

from messages import M
from workshop_api import READ, ApiError, Op

NAMES = ("lid", "extraction", "key")
CAPABILITY = {n: n + "_interlock" for n in NAMES}
OK, OPEN, UNKNOWN = "ok", "open", "unknown"


def declared(profile):
    """{name: {gpin, active_when, label}} of the interlocks that have an input."""
    out = {}
    for name, item in ((profile or {}).get("interlocks") or {}).items():
        if name in NAMES and isinstance(item, dict) and isinstance(item.get("gpin"), int) and not isinstance(item.get("gpin"), bool):
            out[name] = {"gpin": item["gpin"], "active_when": "low" if item.get("active_when") == "low" else "high",
                         "label": str(item.get("label") or "")}
    return out


def input_value(model, gpin):
    """0 / 1 of sensors.gpIn[gpin], or None when it is not there or has no value."""
    try:
        item = ((model or {}).get("sensors") or {}).get("gpIn")[gpin]
    except (TypeError, IndexError, KeyError):
        return None
    v = item.get("value") if isinstance(item, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return 1 if v >= 0.5 else 0


def exists(model, gpin):
    """The input exists in the object model (it may have no value yet)."""
    try:
        return isinstance(((model or {}).get("sensors") or {}).get("gpIn")[gpin], dict)
    except (TypeError, IndexError, KeyError):
        return False


def judge(item, model):
    """ok | open | unknown for one declared interlock."""
    v = input_value(model, item["gpin"])
    if v is None:
        return UNKNOWN
    return OK if (v == 1) == (item["active_when"] == "high") else OPEN


def state(profile, model):
    """[{name, capability, gpin, active_when, label, state}] of every declared interlock (fixed order)."""
    decl = declared(profile)
    return [dict(decl[n], name=n, capability=CAPABILITY[n], state=judge(decl[n], model)) for n in NAMES if n in decl]


def blocking(profile, model):
    """The first declared interlock that is not ok, or None."""
    for row in state(profile, model):
        if row["state"] != OK:
            return row
    return None


def title(row):
    """Name shown to people: the label of the profile, or the generic name of the interlock."""
    return row.get("label") or M("interlock_name_" + row["name"])


def live():
    """(profile, model) now: the saved profile and the last object model of the subscription."""
    import machine_profile
    import machine_state
    return machine_profile.load(), machine_state.last_state()


def status():
    """What safety.status answers."""
    profile, model = live()
    rows = state(profile, model)
    return {"declared": bool(rows), "ok": all(r["state"] == OK for r in rows),
            "interlocks": [{"name": r["name"], "capability": r["capability"], "label": str(title(r)), "gpin": r["gpin"],
                            "active_when": r["active_when"], "state": r["state"]} for r in rows]}


def refusal():
    """ApiError when the laser must not start (Laser mode and a declared interlock not ok), else None."""
    try:
        import api_ops
        mode = api_ops.current_mode()
        if mode != "laser":
            return None
        profile, model = live()
        row = blocking(profile, model)
    except Exception:
        return None  # reading problems must not close the machine for the pages; the firmware is the real protection
    if row is None:
        return None
    return ApiError("interlock_open", M("interlock_open", name=title(row), state=M("interlock_state_" + row["state"])),
                    interlock=row["name"], state=row["state"])


def guarded(fn, laser_when=None):
    """The operation function fn, but refused with `interlock_open` when it would turn the laser on while an interlock is not ok.
    laser_when(args) -> bool says whether this call uses the laser (default: always)."""
    @functools.wraps(fn)
    def wrapper(args, ctx):
        if laser_when is None or laser_when(args):
            err = refusal()
            if err is not None:
                raise err
        return fn(args, ctx)
    return wrapper


def ops():
    return [Op("safety.status", lambda args, ctx: status(), READ, {},
               "Live state of the laser interlocks the machine profile declares (lid, extraction, key), read from the Duet inputs: "
               "{declared, ok, interlocks: [{name, capability, label, gpin, active_when, state}]}, state being ok, open or unknown "
               "(unknown counts as not ok). Without declared interlocks: declared false, ok true, empty list. "
               "In Laser mode a declared interlock that is not ok makes job.start and frame.start with the laser fail with interlock_open.",
               log=False)]
