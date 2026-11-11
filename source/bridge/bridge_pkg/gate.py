"""The machine gate: knows if the machine can take a job, asking the service."""


import threading
import time

from bridge_pkg.lines import NEEDS_HOMING_OK


UNFIT_STATES = {"paused": "paused", "pausing": "pausing", "resuming": "resuming", "cancelling": "cancelling a job",
                "halted": "halted by an error (M999 is needed)", "off": "off", "updating": "updating the firmware"}


class MachineGate:
    """Knows if the machine is in a state that cannot take a live job, asking the service (motion.state) every 2 s while
    somebody is connected. Unknown state (service stopped, no answer yet) lets everything pass: the gate never blocks by
    guessing."""

    def __init__(self, bridge, notifier, threads=True):
        self.bridge = bridge
        self.notifier = notifier
        self.status = None
        self.needs_homing = False
        self.at = 0.0
        if threads:
            threading.Thread(target=self._loop, name="machine-gate", daemon=True).start()

    def _loop(self):
        while True:
            time.sleep(2.0)
            try:
                if self.bridge.clients and self.bridge.settings.get("block_when_unfit"):
                    self.refresh()
            except Exception:
                self.status = None

    def refresh(self):
        j = self.notifier.post("motion.state", {}, timeout=3)
        res = (j or {}).get("result") or {}
        self.status = res.get("status") if (j or {}).get("ok") else None
        self.needs_homing = bool(res.get("needs_homing")) if (j or {}).get("ok") else False
        self.at = time.monotonic()
        # halted (emergency stop, error) or off: the live job cannot go on; free what it holds
        if self.status in ("halted", "off") and self.bridge.live_job.get("active"):
            self.bridge._end_live_job("cancel")

    def reason(self, tok=None):
        """Why orders are refused now (text) or None. tok: the code of the order (the homing passes while the axes are not homed)."""
        if not self.bridge.settings.get("block_when_unfit"):
            return None
        if self.status is None or time.monotonic() - self.at > 10:
            return None
        why = UNFIT_STATES.get(self.status)
        if why:
            return why
        if self.needs_homing and tok not in NEEDS_HOMING_OK:
            return "not homed yet (home all the axes first)"
        return None
