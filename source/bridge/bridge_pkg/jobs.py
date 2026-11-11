"""Activity of the orders and the live job (opening, ending, failed orders)."""


from bridge_pkg.lines import FAIL_REFUSE_S, FAIL_WATCH, MOTION_CODES
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
            self._check_failed_order(client, slot, text)
            client.finish(slot, text, "duet")

    def _check_failed_order(self, client, slot, text):
        """A macro call or a probing order answered with an error: the rest of the job must not run (see FAIL_WATCH)."""
        if first_token(slot.line) not in FAIL_WATCH:
            return
        err = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip().lower().startswith("error")), None)
        if not err:
            return
        client.failed_until = self.clock.mono() + FAIL_REFUSE_S
        client.failed_why = err[:120]
        self.event("error", "job_order_failed", f"'{client.name}': {mask(slot.line)[:60]} failed ({err[:120]}); the rest of the job is refused", client=client.name, error=err[:200])
        if self.live_job["active"] and self.live_job.get("client") == client.name:
            self._end_live_job("order_failed")

    def _start_live_job(self, client, name):
        client.taint_until = 0.0  # a new job: what an earlier one left refused no longer counts
        client.failed_until = 0.0
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
