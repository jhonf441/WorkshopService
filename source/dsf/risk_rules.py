"""
Active risk (warning standard, level 4 -- 2026-10-10: "the protocol will also
manage, depending on the danger, the color... and the lights paint it"; "yes,
apply it everywhere").

Level 4 = something that LEAVES THE MACHINE WITHOUT A PROTECTION WHILE IT LASTS.
While there is one active:
  - plugins.WorkshopService.data.riskActive = [{id, text, since, auto}]
    (the bar and the pages show a fixed warning of what is going on). text is a
    message published as {"key", "params"}: every page shows it in the language
    of its DWC (an explicit risk brings its two texts: key "_raw", params {es, en}),
  - the LED strip paints the "riesgo" state (blinking red, color in Lights).

Sources:
  - AUTOMATIC, from the object model (they do not depend on a screen warning):
      global.crashCal true        -> calibrating the crash detection
      a heater in "tuning"         -> calibrating PID (it heats and cools by itself)
      global.motorsLoose true   -> X/Y motors without force (manual measurement)
      motor_poller.released()   -> motors released with M18 (from the Motors page or anywhere else)
  - EXPLICIT, from any screen or macro:
      the API (risk) S"start" I"<id>" T"<text>" [E"<English text>"] [D<seconds, default 600>]
      the API (risk) S"end" I"<id>"
      the API (risk)                          -> list (JSON)
    An explicit one expires by itself after D seconds: if the screen that opened
    it closes or hangs, the warning does not stay stuck forever.
(The no-limits jog and a detected crash have their own states.)

"""
import threading
import time

import heartbeats
import messages
from messages import M, J, B

_lock = threading.Lock()
_explicit = {}  # id -> {texto, text_en, desde, hasta}
_current = []
PERIOD_S = 1.0


def launch(ident, raw_text, duration_s=600, text_en=None):
    """raw_text: a message of the service (M(...)), or a text from outside: the Spanish one (or the only one the caller
    has) with text_en the English one."""
    with _lock:
        prev = _explicit.get(ident)
        _explicit[ident] = {
            "text": raw_text if isinstance(raw_text, messages.Msg) else str(raw_text or text_en or ident),
            "text_en": None if isinstance(raw_text, messages.Msg) else str(text_en or raw_text or ident),
            # integers: they are published as JSON and dsf-python leaves floats with 6 digits
            "since": prev["since"] if prev else int(time.time()),
            "until": int(time.time() + max(5, min(float(duration_s or 600), 6 * 3600))),
        }


def finish(ident):
    with _lock:
        _explicit.pop(ident, None)


def active():
    return list(_current)


def _risk(ident, m):
    """(id, message) of an automatic risk."""
    return ident, m


def _automatic(s):
    out = []
    g = (s or {}).get("global") or {}
    if g.get("crashCal") is True:
        out.append(_risk("crash_cal", M("risk_rules_calibrating_crash_detection_real_crash_does")))
    ax = {a.get("letter"): a for a in (((s or {}).get("move") or {}).get("axes") or []) if a}
    homed_xy = bool(ax.get("X", {}).get("homed")) and bool(ax.get("Y", {}).get("homed"))
    # loose until captured (handcorner.g turns it off) or until homing
    loose = g.get("motorsLoose") is True and not homed_xy
    if loose:
        out.append(_risk("motors_loose", M("risk_rules_x_y_motors_without_force_machine")))
    # 2026-10-21: motors released by M18 (Motors page, console, a macro) as the motors poller knows it; it lasts until a
    # reading says they have force again, the axis is homed or they are enabled. handfree.g's own risk above covers it.
    try:
        import motor_poller
        released = motor_poller.released()
    except Exception:
        released = []
    if released and not loose:
        out.append(_risk("motors_released", M("risk_rules_motors_released", axes=", ".join(released))))
    # 2026-10-11 (level 4 complete for the no-limits jog): the red bar on all the
    # screens while it lasts; the lights keep their own color (status_light)
    try:
        import jog_move
        if jog_move.free_active():
            out.append(_risk("jog_free", M("risk_rules_jog_without_limits_machine_moves_without")))
    except Exception:
        pass
    for i, h in enumerate(((s or {}).get("heat") or {}).get("heaters") or []):
        if h and h.get("state") == "tuning":
            out.append(_risk(f"pid_{i}", M("risk_rules_calibrating_pid_heater_heats_cools_by", i=i)))
    return out


# Activity (2026-10-10): each risk leaves two events, at the start and at the
# end (with how long it lasted), to know afterwards when the machine was without
# that protection.
_noted = {}  # id -> {texto, desde}


def _note(bridge, entries, current_time):
    try:
        import activity
    except Exception:
        return
    ids = {e["id"]: e for e in entries}
    for ident, e in ids.items():
        if ident not in _noted:
            _noted[ident] = {"text": e["text"], "since": current_time}
            activity.log_event(bridge, "risk", M("risk_active", text=e["text"]))
    for ident in list(_noted):
        if ident not in ids:
            a = _noted.pop(ident)
            dur = int(current_time - a["since"])
            txt = f"{dur // 60} min {dur % 60} s" if dur >= 60 else f"{dur} s"
            activity.log_event(bridge, "risk", M("risk_ended", text=a["text"], lasted=txt))


def run_loop(bridge, config):
    import machine_state

    since_auto = {}
    published = None
    while True:
        try:
            try:
                s = machine_state.get_status(timeout=3, max_age_s=1.0)
            except Exception:
                s = None
            current_time = time.time()
            entries = []
            seen = set()
            # "text" is a message: the pages show it in their own language (an explicit risk brings its two texts: B())
            for ident, m in _automatic(s):
                seen.add(ident)
                since_auto.setdefault(ident, current_time)
                entries.append({"id": ident, "text": m, "since": int(since_auto[ident] * 1000), "auto": True})
            for k in list(since_auto):
                if k not in seen:
                    since_auto.pop(k, None)
            with _lock:
                for ident, e in list(_explicit.items()):
                    if current_time > e["until"]:
                        _explicit.pop(ident, None)
                        continue
                    text = e["text"] if isinstance(e["text"], messages.Msg) else B(e["text"], e.get("text_en"))
                    entries.append({"id": ident, "text": text,
                                    "since": int(e["since"] * 1000), "auto": False})
            _current[:] = entries
            _note(bridge, entries, current_time)
            key = [(e["id"], messages.data(e["text"])) for e in entries]
            if key != published:
                published = key
                bridge.set_status("riskActive", entries)
            heartbeats.detail("risk", ", ".join(e["id"] for e in entries) or M("risk_rules_none"))
            heartbeats.ok("risk")
        except Exception as e:
            heartbeats.error("risk", e)
        time.sleep(PERIOD_S)
