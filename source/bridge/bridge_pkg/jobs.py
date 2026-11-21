"""Activity of the orders and the live job (opening, ending, failed orders)."""


from bridge_pkg.lines import AIR_OFF_LINE, FAIL_REFUSE_S, FAIL_WATCH, FOCUS_STOP_TEXT, MOTION_CODES, reply_failed
from bridge_pkg.service_link import JOB_END_OPS
from bridge_pkg.textutil import first_token, mask


class LiveJobMixin:
    """Order activity and live job of the bridge (mixed into Bridge)."""

    # -- activity --
    def note_order(self, client, line):
        """A non-query line was accepted for the Duet: record the activity."""
        wall = self.clock.wall()
        tok = first_token(line)
        with self.lock:
            client.last_order = mask(line)[:60]
            client.last_order_at = wall
            client.pending += 1
            self.pending_orders += 1
            self.last_order_wall = wall
            if tok in MOTION_CODES:
                client.last_motion_at = wall
                self.last_motion_wall = wall

    def order_finished(self, client, slot, text, dropped=False):
        wall = self.clock.wall()
        with self.lock:
            client.pending = max(0, client.pending - 1)
            self.pending_orders = max(0, self.pending_orders - 1)
            if not dropped:
                client.last_order_at = wall
                self.last_order_wall = wall
        if not dropped:
            text = self._check_failed_order(client, slot, text)
            client.finish(slot, text, "duet")

    def _check_failed_order(self, client, slot, text):
        """A macro call or a probing order failed: the rest of the job must not run (see FAIL_WATCH). Two ways to know, neither depends on the reply starting with
        "Error": the reply says so (reply_failed), or the machine says the focus was not set (global.workshopFocusOk false after an attempt of THIS job: the
        service answers it in motion.state, asked before the program is answered). Returns the text the program gets (the stop message is added when the focus failed)."""
        if first_token(slot.line) not in FAIL_WATCH or client.failed_until > self.clock.mono():
            return text           # not a watched order, or the job already failed (the air off that passes a refused job is not a second failure)
        err = reply_failed(text)
        focus = self._focus_failed_since(client)
        if not err and not focus:
            return text
        why = "the focus was not set" if focus else err
        if focus:
            client.failed_until = self.clock.mono() + FAIL_REFUSE_S
            self.lock_focus(why)
            with self.lock:
                self.totals["focus_failed"] = self.totals.get("focus_failed", 0) + 1
        else:
            client.failed_until = self.clock.mono() + FAIL_REFUSE_S
        client.failed_why = why[:120]
        self.event("error", "focus_failed" if focus else "job_order_failed",
                   f"'{client.name}': {mask(slot.line)[:60]} failed ({why[:120]}); the rest of the job is refused and the laser and the air are turned off", client=client.name, error=why[:200])
        self._actuators_off()
        if self.live_job["active"] and self.live_job.get("client") == client.name:
            self._end_live_job("focus_failed" if focus else "order_failed")
        return (str(text or "").rstrip() + ("\n" + FOCUS_STOP_TEXT if focus else "")).lstrip()

    def focus_watch(self, focus):
        """Every look at the focus flag of the machine (the gate, every 2 s, and after each order that may have failed). The block lasts UNTIL THERE IS A GOOD FOCUS:
        a failure the macro DECLARED (its counter went up while the flag is not true, or the flag is false with a counter above zero when the bridge first looks) locks
        the work, the laser, the air and the power of any job; the flag true again lifts it. A machine that never declared anything is never locked."""
        if not isinstance(focus, dict):
            return
        fail = focus.get("fail") or 0
        ok = focus.get("ok")
        if ok is True:
            self.focus_fail_seen = fail
            self._focus_unlocked("focus_unlocked_good", "The focus was set well again: the laser, the air and the movement of the work are allowed")
            return
        first = self.focus_fail_seen is None
        news = fail > (self.focus_fail_seen or 0)
        self.focus_fail_seen = fail
        if ok is False and (news or (first and fail > 0)):
            self.lock_focus("a focus macro failed")

    def lock_focus(self, why):
        with self.lock:
            if self.focus_lock is not None:
                return
            self.focus_lock = {"since": self.clock.wall(), "why": str(why)[:120]}
        self.event("error", "focus_locked", "The focus was not set: the movement of the work, the laser, the air and the power are refused until a focus is set well "
                   "(Measure Z or Focus here) or the lock is lifted by hand in Services > G-code bridge", why=str(why)[:120])

    def unlock_focus_by_hand(self):
        """The person lifts the lock without a focus (the page asks a double touch first): it is logged as a security event and does not come back for the same failure."""
        if self.focus_lock is None:
            return "focus_not_locked", "The focus is not locked."
        f = self.gate.focus or {}
        self.focus_fail_seen = f.get("fail") or 0
        for c in list(self.clients.values()):
            c.failed_until = 0.0
            c.focus_run0 = f.get("run") or 0
        with self.lock:
            self.totals["focus_unlocked_by_hand"] = self.totals.get("focus_unlocked_by_hand", 0) + 1
        self._focus_unlocked("focus_unlocked_by_hand", "The focus lock was lifted by hand WITHOUT a good focus (the laser and the air are allowed again)", security=True)
        return "focus_unlocked", "Unlocked without focus."

    def _focus_unlocked(self, code, text, security=False):
        with self.lock:
            if self.focus_lock is None:
                return
            self.focus_lock = None
            for c in self.clients.values():
                if str(c.failed_why).startswith("the focus"):
                    c.failed_until = 0.0     # the failure that refused the rest of that job is solved
        self.event("security" if security else "info", code, text)

    def _focus_failed_since(self, client):
        """True when the machine says the focus is NOT set and a focus attempt happened since this job (or this connection) started: a flag that was left false by an
        earlier job, with no attempt in this one, is not this job's failure."""
        f = self.gate.focus_now()
        if not f or f.get("ok") is not False:
            return False
        return (f.get("run") or 0) > (client.focus_run0 or 0)

    def _actuators_off(self):
        """M5 and the air off, on a connection of its own (the client's queue may be full of lines of the job). A machine without the air macro answers an error: harmless."""
        link = self.new_link()
        for line in ("M5", AIR_OFF_LINE):
            try:
                link.execute(line)
            except Exception as e:  # noqa: BLE001 - the machine may be down; the refusal of the rest of the job stands
                self.event("error", "actuators_off_failed", f"could not send {line} after a failed order: {e}", line=line)
        link.close()

    def _start_live_job(self, client, name):
        client.taint_until = 0.0  # a new job: what an earlier one left refused no longer counts
        client.failed_until = 0.0
        client.focus_run0 = ((self.gate.focus or {}).get("run") or 0)  # the focus attempts of earlier jobs do not count against this one
        self.live_job = {"active": True, "name": name or None, "since": self.clock.wall(), "client": client.name,
                         "last_event_at": self.clock.wall(), "ended_at": None, "end_reason": None}
        self.event("info", "live_job_started", f"Live job started by '{client.name}'" + (f" ({name})" if name else ""), client=client.name, name=name or "")
        if self.live is not None:
            self.live.on_job_start(client, name)
        self.service_notify("job.start", {"name": name} if name else {})

    def _end_live_job(self, reason):
        job = self.live_job
        if not job["active"]:
            return
        job["active"] = False
        job["ended_at"] = self.clock.wall()
        job["last_event_at"] = job["ended_at"]
        job["end_reason"] = reason
        self.event("info", "live_job_ended", f"Live job ended ({reason})", reason=reason)
        if self.live is not None:
            self.live.on_job_end(reason)
        self.service_notify(JOB_END_OPS.get(reason, "job.end"), {})
