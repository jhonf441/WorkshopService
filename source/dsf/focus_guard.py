"""The laser focus was not set: what the service does about it, whoever started the job (the bridge, a file of DWC, a button).

The macros that set the focus (laserfocus.g, focushere.g, zmeasure.g of the Workbench) keep `global.workshopFocusOk` (true only when the focus was set and verified)
and, right before they abort because something failed (the probe did not trigger, the machine is not homed...), add one to `global.workshopFocusFail`. RRF stops the
macro but not the rest of the program, and a file job that aborts a macro is cancelled without running cancel.g: the laser and the air stay as they were.
This module only decides (pure, tested): `step(model)` says "failed" once for every new failure and "clear" when the focus is set again. main.py does the rest:
the laser and the air off (M5 and the air macro), the job of a file cancelled, a risk with its warning, a phone notice and the event. The G-code bridge has its own
check after every macro of a live job (bridge/bridge_pkg/jobs.py); this one covers the other ways to start the same macros.
"""
import threading

import machine_state
import motion_owner
import risk_rules
from messages import M

RISK_ID = "focus_not_set"
RISK_S = 900                       # the warning stays this long (or until the focus is set again)
AIR_OFF_LINE = 'M98 P"0:/macros/laser/airoff.g"'   # the machine of this workshop; another machine answers an error, harmless
FILE_JOB_STATUS = ("processing", "simulating", "pausing", "paused", "resuming")


class FocusGuard:
    def __init__(self):
        self.lock = threading.Lock()
        self.seen_fail = None      # the failure counter at the first look: a failure from before the service started is not news
        self.active = False

    def step(self, model):
        """None (nothing new), "failed" (a new failure since the last look) or "clear" (the focus is set again after a failure)."""
        fs = motion_owner.focus_state(model)
        if fs is None:
            return None
        fail = fs.get("fail") or 0
        with self.lock:
            if self.seen_fail is None:
                self.seen_fail = fail
                self.active = False
                return None
            if fail > self.seen_fail:
                self.seen_fail = fail
                self.active = True
                return "failed"
            if fs.get("ok") is True and self.active:
                self.active = False
                return "clear"
        return None


def act(guard, bridge, log_file):
    """One look (main.py calls it every second): on a new failure the machine is made safe whoever started the job, the warning goes up as a risk (home, bar, lights)
    and (main.py) the event and the phone notice are logged; when the focus is set again the warning goes down."""
    ev = guard.step(machine_state.last_state() or {})
    if ev == "failed":
        log_file("focus not set (a focus macro failed): laser and air off, a file job is cancelled")
        for line in lines_to_send(machine_state.read_in("state.status")):
            try:
                bridge.send(line)
            except Exception as e:  # noqa: BLE001 - the others still go
                log_file(f"focus guard: could not send {line}: {e}")
        text = M("focus_guard_risk")      # the risk goes out as two plain texts (as the macros do): every page shows its own language without a template of this key
        risk_rules.launch(RISK_ID, text.text("es"), RISK_S, text_en=text.text("en"))
    elif ev == "clear":
        risk_rules.finish(RISK_ID)
    return ev


def lines_to_send(status):
    """The G-code that makes the machine safe after a failure: M5, the air off and, when a file job is running, M0 (RRF cancels a job whose macro aborts but runs no cancel.g)."""
    out = ["M5", AIR_OFF_LINE]
    if status in FILE_JOB_STATUS:
        out.append("M0")
    return out
