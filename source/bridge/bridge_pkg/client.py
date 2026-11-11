"""One client connection: slots in arrival order, the reading loop and the decision about each line."""


import codecs
import collections
import socket
import threading

from bridge_pkg.lines import (GATED_CODES, MATERIAL_MACRO_RE, MAX_LINE, NEEDS_HOMING_OK, NOOP_WITHOUT_PARAMS, STOP_ENDS_JOB, STOPS_PASS, TAINT_S,
                              is_query_line, m118_job_line)
from bridge_pkg.orders import OrderWorker
from bridge_pkg.telnet import TelnetFilter
from bridge_pkg.textutil import first_token, format_response, mask


class Slot:
    """One received line waiting for its reply."""
    __slots__ = ("kind", "line", "t0", "done", "out", "source")

    def __init__(self, kind, line, t0):
        self.kind = kind          # "local", "query" or "order"
        self.line = line
        self.t0 = t0
        self.done = False
        self.out = ""
        self.source = None


class Client:
    def __init__(self, bridge, sock, addr, number):
        self.bridge = bridge
        self.sock = sock
        self.addr = addr
        self.ip = addr[0]
        self.id = f"{addr[0]}:{addr[1]}"
        clock = bridge.clock
        self.name = bridge.settings.get("names").get(addr[0]) or bridge.auto_name(addr[0])
        self.since = clock.wall()
        self.last_rx = clock.wall()
        self.lines = self.orders = self.queries = self.rejects = 0
        self.cache_hits = self.coalesced = self.stale_served = self.overtaken = 0
        self.bytes_rx = self.bytes_tx = 0
        self.authenticated = False
        self.last = None
        self.last_at = None
        self.last_order = None
        self.last_order_at = None        # wall time of the last non-query line (received or finished)
        self.last_motion_at = None
        self.pending = 0                 # orders accepted and not finished
        self.closed = False
        self.taint_until = 0.0           # mono time until which the orders of this job are refused (see TAINT_S)
        self.failed_until = 0.0          # mono time until which every order but the stops is refused (a macro or probing order failed, see FAIL_WATCH)
        self.failed_why = ""
        self.stopped_until = 0.0         # mono time until which the rest of a job stopped safely is refused (see live_stop.py)
        self.stopped_note = None
        self.cut_after_flush = False
        self.slots = collections.deque()
        self.slot_lock = threading.RLock()
        self.order_worker = OrderWorker(bridge, self)

    # -- output --
    def new_slot(self, kind, line):
        slot = Slot(kind, line, self.bridge.clock.mono())
        with self.slot_lock:
            self.slots.append(slot)
        return slot

    def finish(self, slot, text, source=None):
        """Complete a slot with the machine's (or the bridge's) answer."""
        with self.slot_lock:
            slot.out = format_response(text)
            slot.source = source
            slot.done = True
        self.flush()

    def flush(self):
        """Write finished slots in arrival order; a finished query or local
        answer may overtake orders that have waited more than `overtake_ms`."""
        b = self.bridge
        overtake_s = b.settings.get("overtake_ms") / 1000.0
        with self.slot_lock:
            if not self.slots:
                return
            now = b.clock.mono()
            pending_ahead = False
            may_overtake = True
            keep = collections.deque()
            emit = []
            for slot in self.slots:
                if not slot.done:
                    pending_ahead = True
                    if not (slot.kind == "order" and now - slot.t0 >= overtake_s):
                        may_overtake = False
                    keep.append(slot)
                elif not pending_ahead:
                    emit.append((slot, False))
                elif slot.kind != "order" and may_overtake:
                    emit.append((slot, True))
                else:
                    keep.append(slot)
            self.slots = keep
            for slot, overtook in emit:
                if overtook:
                    self.overtaken += 1
                    with b.stat_lock:
                        b.totals["overtaken"] += 1
                shown = slot.out.strip().replace("\r", "").replace("\n", " | ")[:100]
                b.dbg(self.name, "tx", f"{shown} (+{int((now - slot.t0) * 1000)} ms{', overtook an order' if overtook else ''})")
                self._send(slot.out)
            if self.cut_after_flush and not self.slots:
                self.shutdown()

    def _send(self, text):
        if self.closed:
            return
        data = text if isinstance(text, bytes) else text.encode()
        try:
            self.sock.sendall(data)
        except OSError:
            self.shutdown()
            return
        with self.bridge.stat_lock:
            self.bridge.totals["bytes_tx"] += len(data)
            self.bytes_tx += len(data)

    def send_raw(self, text):
        with self.slot_lock:
            self._send(text)

    def shutdown(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

    # -- input --
    def run(self):
        b = self.bridge
        try:
            self.send_raw("Connected!\r\n")
            if b.settings.get("extended_greeting"):
                extra = " This bridge asks for a password to send orders: BRIDGE KEY <password>." if (b.needs_password() and not b.can_order(self)) else ""
                self.send_raw(f"Workshop G-code bridge. You are '{self.name}'. Type BRIDGE HELP for the commands.{extra}\r\n")
            buf = ""
            telnet = TelnetFilter()
            text_in = codecs.getincrementaldecoder("utf-8")(errors="ignore")   # a character split between two reads is not lost
            while not self.closed:
                data = self.sock.recv(4096)
                if not data:
                    break
                with b.lock:
                    b.totals["bytes_rx"] += len(data)
                    self.bytes_rx += len(data)
                    self.last_rx = b.clock.wall()
                data, answer = telnet.feed(data)
                if answer:
                    self.send_raw(answer)
                buf += text_in.decode(data)
                pieces = buf.replace("\r", "\n").split("\n")
                buf = pieces.pop()
                for piece in pieces:
                    piece = piece.strip()
                    if piece:
                        self.handle_line(piece)
                if len(buf) > MAX_LINE * 4:
                    buf = ""
                    self.reply_local("Error: line too long (max %d)." % MAX_LINE)
        except (OSError, TimeoutError):
            pass
        except Exception as e:
            b.event("error", "unexpected_error", f"Unexpected error with '{self.name}': {e}", client=self.name, error=str(e))
        finally:
            b.unregister(self)

    def reply_local(self, text):
        slot = self.new_slot("local", "")
        self.finish(slot, text)

    def handle_line(self, line):
        """Classify one received line and queue its reply slot."""
        b = self.bridge
        if len(line) > MAX_LINE:
            self.reply_local("Error: line too long (max %d)." % MAX_LINE)
            return
        shown = mask(line)
        wall = b.clock.wall()
        with b.lock:
            b.totals["lines"] += 1
            self.lines += 1
            self.last = shown
            self.last_at = wall
        b.dbg(self.name, "rx", shown)
        tok = first_token(line)
        if self._answer_locally(line, tok, shown):
            return
        is_query = is_query_line(line, b.settings.get("queries"))
        if is_query:
            self._send_query(line)
            return
        if self._refuse_order(line, tok):
            return
        self._send_order(line, tok)

    def _answer_locally(self, line, tok, shown):
        """BRIDGE commands, the job mark inside an M118, the empty G0 / G1 ping and the skipped material macros never reach the board: True when
        the line was one of them (its reply is queued)."""
        b = self.bridge
        if tok == "M118":
            inner = m118_job_line(line)
            if inner:
                text, cut = b.bridge_command(inner, self)
                self.reply_local(text)
                return True
        if tok == "BRIDGE":
            text, cut = b.bridge_command(line, self)
            if cut:
                self.cut_after_flush = True
            self.reply_local(text)
            return True
        parts = line.split()
        if len(parts) == 1 and tok in NOOP_WITHOUT_PARAMS:
            self.reply_local("")
            return True

        if tok == "M98" and b.settings.get("skip_material_macro") and MATERIAL_MACRO_RE.match(line):
            with b.lock:
                b.totals["skipped_material"] = b.totals.get("skipped_material", 0) + 1
                n = b.totals["skipped_material"]
            if n in (1, 10, 100):
                b.event("info", "material_macro_skipped", f"'{self.name}' sent a material macro ({shown}); the bridge skipped it (setting: skip the material G-code)", client=self.name)
            self.reply_local("")
            return True
        return False

    def _refuse_order(self, line, tok):
        """The checks an order (anything that is not a query) must pass, in this order: password, control, live-job hold, failed job, machine
        gate. True when one of them refused it (the reason is already queued as the reply)."""
        return (self._refuse_without_password()
                or self._refuse_without_control()
                or self._refuse_while_held(line, tok)
                or self._refuse_after_failed_order(tok)
                or self._refuse_by_machine(line, tok))

    def _refuse_without_password(self):
        b = self.bridge
        if b.can_order(self):
            return False
        with b.lock:
            b.totals["rejects"] += 1
            b.totals["rejects_password"] = b.totals.get("rejects_password", 0) + 1  # why, so it shows without the debug
            self.rejects += 1
            b.count("rejects")
            n = self.rejects
        if n in (1, 10, 100):
            b.event("security", "order_rejected_password", f"Order from '{self.name}' rejected: password missing", client=self.name)
        if b.exposed():
            self.reply_local("Error: this bridge has no password, no allowed list and no trusted address, so it only answers queries from the network. "
                             "Set a password (then type BRIDGE KEY <password>), an allowed list or a trusted address in Services > G-code bridge.")
        elif not b.needs_password():
            self.reply_local("Error: only the Pi and the trusted addresses may send orders to this bridge, and this address is not one of them. "
                             "Mark it as trusted in Services > G-code bridge, or set a password or an allowed list.")
        else:
            self.reply_local("Error: this bridge asks for a password to send orders. Type BRIDGE KEY <password> (or mark this IP as trusted in Services).")
        return True

    def _refuse_without_control(self):
        b = self.bridge
        if not b.settings.get("exclusive"):
            return False
        with b.lock:
            if b.owner is None or b.owner.id not in b.clients:
                b.owner = self
                b.owner_since = b.clock.wall()
                b.event("control", "control_taken", f"'{self.name}' took control of the bridge", client=self.name)
            rejected = b.owner is not self
            owner_label = b.label(b.owner)
            if rejected:
                b.totals["rejects"] += 1
                b.totals["rejects_control"] = b.totals.get("rejects_control", 0) + 1  # why, so it shows without the debug
                self.rejects += 1
                b.count("rejects")
                n = self.rejects
        if not rejected:
            return False
        if n in (1, 10, 100):
            b.event("control", "order_rejected_control", f"Order from '{self.name}' rejected: control is held by '{owner_label}'", client=self.name, owner=owner_label)
        self.reply_local(f"Error: the bridge is in use by '{owner_label}'. Your order was not executed; wait for it to finish or type BRIDGE USE.")
        return True

    def _refuse_while_held(self, line, tok):
        b = self.bridge
        if b.live is None or tok in STOPS_PASS:
            return False
        held = b.live.on_order(self, line)
        if held is None:
            return False
        kind, why = held
        if kind == "skip":
            self.reply_local("")      # the part of the job that was already done: ok, nothing reaches the board
        else:
            with b.lock:
                b.totals["rejects"] += 1
                b.totals["rejects_live_stop"] = b.totals.get("rejects_live_stop", 0) + 1  # why, so it shows without the debug
                self.rejects += 1
                b.count("rejects")
            self.reply_local("Error: " + why + ". Your order was not executed.")
        return True

    def _refuse_after_failed_order(self, tok):
        b = self.bridge
        if tok in STOPS_PASS or not self.failed_until > b.clock.mono():
            return False
        left = int(self.failed_until - b.clock.mono()) + 1
        with b.lock:
            b.totals["rejects"] += 1
            b.totals["rejects_failed_job"] = b.totals.get("rejects_failed_job", 0) + 1  # why, so it shows without the debug
            self.rejects += 1
            b.count("rejects")
            n = self.rejects
        if n in (1, 10, 100):
            b.event("info", "order_rejected_failed_job", f"Order from '{self.name}' rejected: an earlier order of the job failed ({self.failed_why})", client=self.name)
        self.reply_local(f"Error: an earlier order of this job failed ({self.failed_why}); the rest is refused for {left} s so it does not run without what that order had to set up. Fix it and send the job again (or BRIDGE RESUME).")
        return True

    def _refuse_by_machine(self, line, tok):
        # the material macros (focus, origin) move the machine, so they wait for the same conditions as a G1 (the focus macro used to run on a machine
        # that was not homed and only then aborted itself, after the live job had been opened)
        b = self.bridge
        if not (tok in GATED_CODES or (tok == "M98" and MATERIAL_MACRO_RE.match(line))):
            return False
        why = b.gate.reason(tok)
        now_m = b.clock.mono()
        if not why and tok not in NEEDS_HOMING_OK and self.taint_until > now_m:
            why = "refusing the rest of this job (an earlier order of it was refused)"
        if why and tok not in NEEDS_HOMING_OK:
            self.taint_until = now_m + TAINT_S
        if not why:
            return False
        with b.lock:
            b.totals["rejects"] += 1
            b.totals["rejects_machine"] = b.totals.get("rejects_machine", 0) + 1  # why, so it shows without the debug
            self.rejects += 1
            b.count("rejects")
            n = self.rejects
        if n in (1, 10, 100):
            b.event("info", "order_rejected_machine", f"Order from '{self.name}' rejected: the machine is {why}", client=self.name, state=why)
        self.reply_local(f"Error: the machine is {why}; the order was not executed. Fix it and send the job again.")
        return True

    def _send_query(self, line):
        b = self.bridge
        with b.lock:
            b.totals["queries"] += 1
            self.queries += 1
            b.count("queries")
        slot = self.new_slot("query", line)

        def done(text, source, slot=slot):
            with b.lock:
                if source == "cache":
                    self.cache_hits += 1
                    b.totals["cache_hits"] += 1
                elif source == "stale":
                    self.stale_served += 1
                    b.totals["stale_served"] += 1
            self.finish(slot, text, source)

        source = b.queries.request(line, done, self)
        if source == "coalesced":
            with b.lock:
                self.coalesced += 1
                b.totals["coalesced"] += 1

    def _send_order(self, line, tok):
        b = self.bridge
        with b.lock:
            b.totals["orders"] += 1
            self.orders += 1
            b.count("orders")
        if b.live is not None and tok not in STOPS_PASS:
            b.live.sent(self, line)
        slot = self.new_slot("order", line)
        b.note_order(self, line)
        self.order_worker.submit(line, slot)
        if tok in STOP_ENDS_JOB and b.live_job.get("active"):
            b._end_live_job("cancel")  # the program stopped the job: it is over, release what it was holding

    def info(self, now_wall):
        b = self.bridge
        return {
            "id": self.id, "name": self.name, "ip": self.ip, "port": self.addr[1],
            "connected_s": round(now_wall - self.since), "idle_s": round(now_wall - self.last_rx),
            "lines": self.lines, "orders": self.orders, "queries": self.queries, "rejects": self.rejects,
            "cache_hits": self.cache_hits, "coalesced": self.coalesced, "stale_served": self.stale_served,
            "overtaken": self.overtaken, "bytes_rx": self.bytes_rx, "bytes_tx": self.bytes_tx,
            "last": self.last, "last_age_s": round(now_wall - self.last_at) if self.last_at else None,
            "last_order": self.last_order, "last_order_at": self.last_order_at,
            "last_order_age_s": round(now_wall - self.last_order_at) if self.last_order_at else None,
            "last_motion_at": self.last_motion_at, "pending_orders": self.pending,
            "control": b.owner is self, "role": b.role(self), "trusted": b.is_trusted(self.ip),
            "name_saved": self.ip in b.settings.get("names"),
        }
