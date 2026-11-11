"""Orders: one worker (and one DSF connection) per client."""


import queue
import threading

from bridge_pkg.duet import DuetLink
from bridge_pkg.textutil import mask


class OrderWorker:
    def __init__(self, bridge, client):
        self.bridge = bridge
        self.client = client
        self.queue = queue.Queue()
        self.thread = None
        self.link = None
        self.stopped = False
        self.lock = threading.Lock()

    def get_link(self):
        if self.link is None:
            b = self.bridge
            self.link = DuetLink(b.link_factory, lambda: b.settings.get("order_timeout_s"), b.clock,
                                 connect_wait=lambda: b.settings.get("order_timeout_s"))
        return self.link

    def submit(self, line, slot):
        with self.lock:
            if self.thread is None and self.bridge.threads_enabled:
                self.thread = threading.Thread(target=self._run, name=f"orders-{self.client.name}", daemon=True)
                self.thread.start()
        self.queue.put((line, slot))

    def stop(self):
        self.stopped = True
        self.queue.put(None)

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                break
            self.execute(*item)
        # connection gone: orders that never ran are finished as dropped
        self.drop_pending()
        self.get_link().close()

    def drop_pending(self):
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self.bridge.order_finished(self.client, item[1], None, dropped=True)

    def run_pending(self):
        """Run what is queued, in order, in the calling thread (tests)."""
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self.execute(*item)

    def execute(self, line, slot):
        """Run one order on this client's own DSF connection."""
        b = self.bridge
        if self.stopped:
            b.order_finished(self.client, slot, None, dropped=True)
            return
        t0 = b.clock.mono()
        text, error = None, None
        try:
            text = self.get_link().execute(line)
        except Exception as e:
            error = e
        ms = (b.clock.mono() - t0) * 1000
        if error is None:
            b.timing["order"].add(ms)
            b.timing["all"].add(ms)
            b.dbg(self.client.name, "duet", f"{mask(line)[:60]} done by the Duet in {int(ms)} ms")
        else:
            with b.lock:
                b.totals["duet_errors"] += 1
            b.event("error", "duet_error", f"Machine error on '{line[:40]}' from '{self.client.name}': {error}",
                    line=line[:40], client=self.client.name, error=str(error))
            text = f"Error: {error}"
        b.order_finished(self.client, slot, text)
