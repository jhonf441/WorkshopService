"""
Shared helper to record events in the activity history
(table "actividad" of db.py), in the black box and to the phone in a single step --
so no caller forgets one of them.

Typical use from a handler or from main.py:
    import activity
    activity.log_event(bridge, "power", "Full shutdown + power cut")

"""
import time

import db
import notifier

def _context():
    """What the machine and the system were doing when the event happened. Read
    from the shared DSF subscription and /proc: no request to the board, no IPC."""
    ctx = {}
    try:
        import machine_state
        m = machine_state.last_state() or {}
        st = (m.get("state") or {}).get("status")
        if st:
            ctx["machine"] = st
        kind = ((m.get("global") or {}).get("selectedMode"))
        if kind:
            ctx["mode"] = kind
        mv = m.get("move") or {}
        if isinstance(mv.get("workplaceNumber"), int):
            ctx["zone"] = machine_state.zone_name(mv["workplaceNumber"])
        fn = ((m.get("job") or {}).get("file") or {}).get("fileName")
        if fn:
            ctx["job"] = fn
        pos = [round(a.get("machinePosition"), 1) for a in (mv.get("axes") or [])[:3] if isinstance(a, dict) and isinstance(a.get("machinePosition"), (int, float))]
        if len(pos) == 3:
            ctx["position"] = pos
    except Exception:
        pass
    try:
        import os
        ctx["load"] = round(os.getloadavg()[0], 2)
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            ctx["temp_c"] = round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass
    return ctx


def _origin():
    """Module.function that logged the event (first caller outside this file)."""
    try:
        import sys
        f = sys._getframe(2)
        while f and f.f_globals.get("__name__") == __name__:
            f = f.f_back
        return f"{f.f_globals.get('__name__', '?')}.{f.f_code.co_name}" if f else None
    except Exception:
        return None


def _who():
    """(user, role) of the person whose API call is being served, (None, None) for events of the service itself."""
    try:
        import identity
        u = identity.current()
        return (u["name"], u["role"]) if u else (None, None)
    except Exception:
        return None, None


def log_event(bridge, type_name, description, kind=None, duration_s=None, consumption_kwh=None, detail=None):
    """detalle: dict with the data of the event (camera id, file, values...). The
    context (machine state, zone, job, load, temperature) and the origin are added
    automatically; the page shows it all when a row is expanded."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    info = {}
    if isinstance(detail, dict) and detail:
        info["data"] = detail
    ctx = _context()
    if ctx:
        info["context"] = ctx
    o = _origin()
    if o:
        info["origin"] = o
    who = _who()
    db.insert_activity(ts, type_name, description, kind=kind, duration_s=duration_s, consumption_kwh=consumption_kwh, detail=info or None,
                       user=who[0], role=who[1])

    # To the black box (black_box.py) as a loose event.
    try:
        import black_box
        black_box.event(type_name, description)
    except Exception:
        pass

    # Also, a notification to the phone if the type is enabled (notifier.py,
    # configurable from the Activity page). It must never prevent the record.
    try:
        notifier.notify_event(type_name, description)
    except Exception:
        pass
