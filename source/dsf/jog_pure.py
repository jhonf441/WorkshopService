"""Pure pieces of the jog (split out of jog_move.py, behaviour unchanged): the free-mode settings limits, the
driver-stall.g text, the M915 reply parser and the bridge-state.json age math. No connection state here."""
import collections
import time

# One queued jog G1: the gesture it belongs to, the monotonic instant after which it is too old to be sent
# (queued + 2 x LEAD_S) and the G-code text. G90/G91 are not Segments: they never expire.
Segment = collections.namedtuple("Segment", "gesture_id deadline code")


def _name_channel(ch):
    n = getattr(ch, "name", None) or str(ch or "")
    return n.split(".")[-1]


def segment_stale(seg, live_gesture_id, now=None):
    """True if the segment must not be sent: its gesture is over (the hand let go) or its deadline passed."""
    return seg.gesture_id != live_gesture_id or (now if now is not None else time.monotonic()) > seg.deadline


FREE_MODES = ("withoutHoming", "outsideLimits")
_FREE_DEF = {"mode": "withoutHoming", "color": "#ff1744", "timeoutS": 60, "marginMm": 5.0, "speedPct": 25, "correctionXY": 50, "correctionZ": 100, "crash": True, "crashSens": 8, "crashSteps": 100}
_FREE_LIM = {"timeoutS": (10, 600), "marginMm": (0.0, 30.0), "speedPct": (5, 100), "correctionXY": (20, 100), "correctionZ": (40, 100), "crashSens": (-64, 63), "crashSteps": (20, 400)}
STALL_MACRO_MARK = "workshop-JOG-free"

STALL_MACRO_TEXT = f"""; driver-stall.g -- RepRapFirmware runs it when a driver configured with
; M915 ... R2 detects a stall (StallGuard). WorkshopService created it for the
; "without limits" mode of the WorkshopJog jog. If you change it, delete the mark
; below and the jog never touches it again (and does not use the stall detection).
; {STALL_MACRO_MARK}
; Crash calibration (Motors page, sys/workshop/macros/axis/crash-cal.g): only counts. With the
; jog without limits active it ALWAYS stops (even if a calibration cut halfway
; left global.crashCal at true).
if exists(global.crashCal) && global.crashCal && !(exists(global.jogFree) && global.jogFree)
  if exists(global.crashCalHit)
    set global.crashCalHit = global.crashCalHit + 1
elif exists(global.jogFree) && global.jogFree
  ; WorkshopService sees these two globals in its object model subscription and stops the jog
  if !exists(global.jogFreeStallN)
    global jogFreeStallN = 0
  if !exists(global.jogFreeStallDrv)
    global jogFreeStallDrv = ""
  set global.jogFreeStallDrv = param.B ^ "." ^ param.D
  set global.jogFreeStallN = global.jogFreeStallN + 1
else
  var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false
  if var.en
    echo "Stall detected on driver " ^ param.B ^ "." ^ param.D ^ ": " ^ param.S
  else
    echo "Choque detectado en el driver " ^ param.B ^ "." ^ param.D ^ ": " ^ param.S
"""


def _free_cfg_clean(o):
    c = dict(_FREE_DEF)
    if isinstance(o, dict):
        for k, (lo, hi) in _FREE_LIM.items():
            v = o.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                c[k] = min(max(v, lo), hi)
        if isinstance(o.get("crash"), bool):
            c["crash"] = o["crash"]
        if o.get("mode") in FREE_MODES:
            c["mode"] = o["mode"]
        import re as _re

        if isinstance(o.get("color"), str) and _re.fullmatch(r"#[0-9a-fA-F]{6}", o["color"]):
            c["color"] = o["color"]
    return c


def _parse_m915(raw_text):
    """'Driver 0.0: stall threshold 3, filter on, full steps/sec 200 (40.0 mm/sec),
    ... action on stall: none' -> [{id, sgt, filt, pasos, mms, accion}]"""
    import re

    out = []
    for m in re.finditer(
        r"Driver ([\d.]+): stall threshold (-?\d+), filter (on|off), full steps/sec (\d+) \(([\d.]+) mm/sec\).*?action on stall: (none|log|raise event)",
        raw_text,
    ):
        out.append(
            {
                "id": m.group(1),
                "sgt": int(m.group(2)),
                "filt": m.group(3) == "on",
                "steps": int(m.group(4)),
                "mms": float(m.group(5)),
                "action": {"none": 0, "log": 1, "raise event": 2}[m.group(6)],
            }
        )
    return out


BRIDGE_STATE_FRESH_S = 10  # a bridge-state.json older than this does not prove orders are still pending


def bridge_state_age_s(state, file_age_s=0.0, now=None):
    """Seconds since the last non-query line of any client, from a parsed
    bridge-state.json; None if there is no data.

    Schema 2 (bridge 3.0): state["activity"] has absolute times, so the age
    does not depend on when the file was written:
      pending_orders  orders sent to the machine and not finished yet (counted
                      only while the file is fresh, so a dead bridge cannot
                      block the jog forever);
      last_order_at   epoch of the last non-query line (received or finished).
    A state without either returns None."""
    now = time.time() if now is None else now
    # Bridge 3.x: the clients carry RELATIVE ages in whole seconds. The absolute epochs of the file reach us rounded to 6
    # digits (1.7921e9 = steps of 27 h), which made "last order 0 s ago" true half of the time (2026-10-15: the jog stayed
    # blocked after the live job had ended). The relative ages are the reliable data.
    cls = state.get("clients") if isinstance(state, dict) else None
    if isinstance(cls, list) and any(isinstance(c, dict) and "last_order_age_s" in c for c in cls):
        val = None
        for c in cls:
            if not isinstance(c, dict):
                continue
            if (c.get("pending_orders") or 0) > 0 and file_age_s <= BRIDGE_STATE_FRESH_S:
                return 0.0
            ag = c.get("last_order_age_s")
            if isinstance(ag, (int, float)):
                h = float(ag) + file_age_s
                val = h if val is None else min(val, h)
        return val
    act = state.get("activity") if isinstance(state, dict) else None
    if isinstance(act, dict):
        gen = act.get("generated_at")
        fresh = isinstance(gen, (int, float)) and (now - gen) <= BRIDGE_STATE_FRESH_S
        if fresh and (act.get("pending_orders") or 0) > 0:
            return 0.0
        last = act.get("last_order_at")
        return max(0.0, now - float(last)) if isinstance(last, (int, float)) else None
    return None
