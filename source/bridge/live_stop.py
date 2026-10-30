"""Safe stop and resume of the live job, the part that lives inside the bridge (2026-10-22). The pure logic is in live_resume.py.

What the bridge does here:
  - while a live job runs it keeps the journal of the lines that reached the board (live_resume.Journal);
  - stop_safe(): refuses the lines that come after, lets what the board already accepted finish, turns the laser off, reads where the head is,
    saves an INTERRUPTED record (data/live-interrupted.json, atomic + .bak) and closes the live job in the service;
  - arm(): marks ONE record to be resumed: the next BRIDGE JOB START of the program starts a ResumeSession that swallows the lines of the part
    already done (verified against the hash), plays the approach when the line is reached and lets the job go on;
  - public_state(): what the pages see (in bridge-state.json, key "live_stop").

It never cancels the job object of the board, never cuts power and is NOT the emergency stop (M112 keeps working as before).
"""
import json
import os
import re
import threading
import time

import live_resume as LR

MAX_RECORDS = 5
ARM_TTL_S = 30 * 60            # an armed resume that nobody relaunched in this time disarms itself
DRAIN_TIMEOUT_S = 120.0        # how long a stop waits for the lines the board already accepted
TRAVEL_FEED = 3000.0           # mm/min of the approach travel (laser off)
Z_FEED = 300.0
REFUSE_S = 120.0               # the rest of the stopped job stays refused this long (renewed by every refused line)

_POS = re.compile(r"X:\s*(-?[\d.]+)\s+Y:\s*(-?[\d.]+)\s+Z:\s*(-?[\d.]+)")
_MACHINE = re.compile(r"Machine\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)")


def parse_m114(text):
    """{"work": {x,y,z}, "machine": {x,y,z}} from the answer of M114 (either part may be missing)."""
    out = {}
    m = _POS.search(str(text or ""))
    if m:
        out["work"] = {"x": float(m.group(1)), "y": float(m.group(2)), "z": float(m.group(3))}
    m = _MACHINE.search(str(text or ""))
    if m:
        out["machine"] = {"x": float(m.group(1)), "y": float(m.group(2)), "z": float(m.group(3))}
    return out


class LiveStop:
    """One per bridge. `bridge` gives: clock, lock, live_job, clients, pending_orders, link_factory, settings, event(), paths, service_notify,
    _end_live_job(), gate."""

    def __init__(self, bridge, sleep=time.sleep):
        self.b = bridge
        self.sleep = sleep
        self.journal = None            # live_resume.Journal of the open live job
        self.session = None            # live_resume.ResumeSession while a resumed job is being verified / swallowed
        self.stopping = False
        self.last_result = None        # {"seq", "ok", "code", "text", "id"} of the last stop / resume action
        self.lock = threading.RLock()
        self._records = None

    # ------------------------------------------------------------------ records on disk
    def _path(self):
        return self.b.paths.interrupted

    def records(self):
        with self.lock:
            if self._records is None:
                self._records = self._load()
            return self._records

    def _load(self):
        for path in (self._path(), self._path() + ".bak"):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                recs = data.get("records") if isinstance(data, dict) else None
                if isinstance(recs, list):
                    return [r for r in recs if isinstance(r, dict) and r.get("id")]
            except (OSError, ValueError):
                continue
        return []

    def _save(self):
        path = self._path()
        data = {"v": 1, "records": self._records or []}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            try:
                os.replace(path, path + ".bak")
            except OSError:
                pass
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o664)
        except OSError:
            pass
        os.replace(tmp, path)

    def find(self, rid):
        return next((r for r in self.records() if r.get("id") == rid), None)

    # ------------------------------------------------------------------ the journal of the live job
    def on_job_start(self, client, name):
        """A live job starts (BRIDGE JOB START): a fresh journal; a resume armed before becomes a verifying session."""
        with self.lock:
            self.stopping = False
            self.session = None
            client.stopped_note = None
            client.stopped_until = 0.0
            self.journal = LR.Journal(name, self.b.clock.wall(), client.name)
            armed = next((r for r in self.records() if r.get("armed")), None)
            if not armed:
                return
            arm = armed["armed"]
            if self.b.clock.wall() > float(arm.get("expires") or 0):
                armed["armed"] = None
                self._save()
                self.b.event("info", "resume_expired", "A resume was armed but nobody relaunched the job in time: disarmed", id=armed["id"])
                return
            self.session = LR.ResumeSession(armed, arm.get("overlap_lines") or 0)
            self.b.event("info", "resume_started", "Resume: the lines already done are verified and skipped (%d of the job)" % self.session.stop_at,
                         id=armed["id"], lines=self.session.stop_at)

    def on_job_end(self, reason):
        with self.lock:
            sess = self.session
            if sess is not None and sess.state in ("skipping", "ready"):
                self.b.event("error", "resume_ended_early", "The relaunched job ended before reaching the line where it was stopped", reason=reason)
            self.session = None
            if reason != "stopped":
                self.journal = None

    def active_for(self, client):
        j = self.journal
        return j is not None and self.b.live_job.get("active") and self.b.live_job.get("client") == client.name

    def on_order(self, client, line):
        """Called for every order line of a client BEFORE it is sent to the board. Returns None (go on) or (verdict, text):
        "skip" (answer ok, do not run), "refuse" / "abort" (answer with an error, do not run)."""
        with self.lock:
            now = self.b.clock.mono()
            if getattr(client, "stopped_note", None) and not self.b.live_job.get("active"):
                tok = line.split(None, 1)[0].upper() if line.split() else ""
                if tok not in ("M5", "M0", "M25", "M112", "M999") and now < client.stopped_until:
                    client.stopped_until = now + REFUSE_S
                    return "refuse", client.stopped_note
                client.stopped_note = None
            if self.stopping and self.b.live_job.get("client") == client.name:
                return "refuse", "the job is being stopped safely from the workshop page; its lines are not executed any more"
            if not self.active_for(client):
                return None
            sess = self.session
            if sess is None or sess.state in ("done", "aborted"):
                return None
            verdict, info = sess.feed(line)
            if verdict == "skip":
                self.journal.add(line)       # the resumed job counts every line again, so it can be stopped and resumed once more
                return "skip", ""
            if verdict == "abort":
                return "abort", self._abort(client, info)
        # "approach": the first line past the stop. The approach runs outside the lock (it moves the machine for a few seconds)
        err = self._approach(client, sess)
        with self.lock:
            if err:
                return "abort", self._abort(client, err)
            self._consumed(sess)
        return None

    def sent(self, client, line):
        """The line passed every check and goes to the board: it is part of the job now (the journal counts it only here, so a line that the
        machine gate or a failed order refused is never counted)."""
        with self.lock:
            if self.active_for(client) and (self.session is None or self.session.state in ("done", "aborted")):
                self.journal.add(line)

    def _abort(self, client, why):
        text = "the resume was cancelled and nothing was run: " + str(why)
        client.failed_until = self.b.clock.mono() + REFUSE_S
        client.failed_why = text[:120]
        self.b.event("error", "resume_aborted", "Resume cancelled: " + str(why), reason=str(why)[:200])
        if self.session is not None:
            self.session.state = "aborted"
            self.session.reason = str(why)
        self.last_result = {"seq": None, "ok": False, "code": "resume_aborted", "text": text, "id": (self.session.record["id"] if self.session else None)}
        return text

    def _consumed(self, sess):
        rid = sess.record["id"]
        self._records = [r for r in self.records() if r.get("id") != rid]
        try:
            self._save()
        except OSError:
            pass
        self.b.event("info", "resume_done", "Resumed: the job goes on from where it stopped", id=rid)

    # ------------------------------------------------------------------ the approach
    def _approach(self, client, sess):
        """Plays the approach lines on the client's own connection. Returns an error text or None."""
        why = self.b.gate.reason("G1")
        if why:
            return "the machine is %s" % why
        modal, pos = sess.resume_state()
        link = client.order_worker.get_link()
        current_z = None
        try:
            current_z = (parse_m114(link.execute("M114")).get("work") or {}).get("z")
        except Exception:
            current_z = None
        lines = LR.approach_lines(modal, pos, current_z, TRAVEL_FEED, Z_FEED)
        self.b.event("info", "resume_approach", "Resume: going back to the point where the job stopped (%d lines, laser off)" % len(lines), lines=len(lines))
        for ln in lines:
            try:
                text = link.execute(ln)
            except Exception as e:  # noqa: BLE001
                return "the approach failed on '%s': %s" % (ln, e)
            if str(text or "").lstrip().lower().startswith("error"):
                return "the board refused '%s': %s" % (ln, str(text).strip()[:100])
        return None

    # ------------------------------------------------------------------ stop
    def stop_safe(self, seq=None, mode=None, extra=None):
        """Stops the live job safely. Returns the record. Raises ValueError with a plain reason when it cannot."""
        b = self.b
        with self.lock:
            if self.stopping:
                raise ValueError("a safe stop is already in progress")
            job = b.live_job
            if not job.get("active") or self.journal is None:
                raise ValueError("there is no live job to stop")
            client = b.find(job.get("client"))
            self.stopping = True
        try:
            self._wait_drained()
            link = b.new_link()
            try:
                try:
                    link.execute("M5")
                except Exception as e:  # noqa: BLE001
                    b.event("error", "stop_laser_off_failed", "The laser-off order failed during the safe stop: %s" % e, error=str(e))
                    raise ValueError("could not turn the laser off (%s): the stop was not completed" % e)
                position = {}
                try:
                    position = parse_m114(link.execute("M114"))
                except Exception:
                    position = {}
            finally:
                link.close()
            with self.lock:
                modal = self.journal.modal
                resumable, why_not = True, None
                if mode is not None and mode != "laser":
                    resumable, why_not = False, "only laser jobs can be resumed"
                elif self.journal.count == 0:
                    resumable, why_not = False, "no line of the job had run yet: just send it again"
                rec = self.journal.record(b.clock.wall(), extra=dict(extra or {}, mode=mode, position=position, resumable=resumable, why_not=why_not,
                                                                     laser_s=modal.power))
                for r in self.records():
                    r["armed"] = None            # a new interruption supersedes any resume that was armed
                self._records = ([rec] + self.records())[:MAX_RECORDS]
                self._save()
                if client is not None:
                    client.stopped_until = b.clock.mono() + REFUSE_S
                    client.stopped_note = "the job was stopped safely from the workshop page: its lines are refused so it does not go on from the middle (send it again or resume it)"
                self.last_result = {"seq": seq, "ok": True, "code": "stopped", "text": "Stopped at line %d." % rec["lines"], "id": rec["id"]}
            b.event("info", "live_job_stopped_safely", "Live job stopped safely at line %d (laser off, record saved)" % rec["lines"], id=rec["id"], lines=rec["lines"])
            b._end_live_job("stopped")
            return rec
        except ValueError as e:
            with self.lock:
                self.last_result = {"seq": seq, "ok": False, "code": "stop_failed", "text": str(e), "id": None}
            raise
        finally:
            with self.lock:
                self.stopping = False

    def _wait_drained(self):
        b = self.b
        end = b.clock.mono() + DRAIN_TIMEOUT_S
        while b.pending_orders > 0 and b.clock.mono() < end:
            self.sleep(0.1)
            if not b.threads_enabled:
                break          # tests drive the queue by hand

    # ------------------------------------------------------------------ resume control
    def arm(self, rid, overlap_lines=0, by=None):
        with self.lock:
            rec = self.find(rid)
            if rec is None:
                raise ValueError("that interrupted job does not exist any more")
            if not rec.get("resumable"):
                raise ValueError(rec.get("why_not") or "this job cannot be resumed")
            if self.b.live_job.get("active"):
                raise ValueError("a live job is running now")
            for r in self.records():
                r["armed"] = None
            overlap = max(0, min(int(overlap_lines or 0), max(0, len(rec.get("tail") or []) - 1), int(rec.get("lines") or 0)))
            rec["armed"] = {"at": self.b.clock.wall(), "expires": self.b.clock.wall() + ARM_TTL_S, "overlap_lines": overlap, "by": by}
            self._save()
            self.last_result = {"seq": None, "ok": True, "code": "armed", "text": "Resume armed: send the same job again from the program.", "id": rid}
        self.b.event("info", "resume_armed", "Resume armed for '%s' (line %d)" % (rec.get("name") or "job", rec.get("lines") or 0), id=rid, overlap=overlap)

    def disarm(self):
        with self.lock:
            changed = False
            for r in self.records():
                if r.get("armed"):
                    r["armed"] = None
                    changed = True
            if changed:
                self._save()
            self.session = None
        if changed:
            self.b.event("info", "resume_disarmed", "Resume disarmed")

    def discard(self, rid):
        with self.lock:
            before = len(self.records())
            self._records = [r for r in self.records() if r.get("id") != rid]
            if len(self._records) != before:
                self._save()
                self.b.event("info", "interrupted_discarded", "Interrupted job discarded", id=rid)
            else:
                raise ValueError("that interrupted job does not exist any more")

    # ------------------------------------------------------------------ what the pages see
    def public_state(self):
        with self.lock:
            sess = self.session
            return {
                "enabled": True,
                "stopping": self.stopping,
                "journal_lines": self.journal.count if self.journal is not None else None,
                "resume": sess.progress if sess is not None else None,
                "last_result": self.last_result,
                "interrupted": [LR.describe(r) for r in self.records()],
            }

