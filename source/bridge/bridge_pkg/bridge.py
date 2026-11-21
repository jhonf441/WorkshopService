"""The Bridge: the object that owns the settings, the clients and the pieces the other modules implement."""


import collections
import logging
import threading
import time

from bridge_pkg.actions import ActionsMixin
from bridge_pkg.client import Client
from bridge_pkg.clock import Clock, Timing
from bridge_pkg.commands import CommandsMixin
from bridge_pkg.debug import DebugMixin, DebugRing
from bridge_pkg.duet import DuetLink, real_link_factory
from bridge_pkg.fsutil import Paths
from bridge_pkg.gate import MachineGate
from bridge_pkg.jobs import LiveJobMixin
from bridge_pkg.log import LOG
from bridge_pkg.queries import QueryService
from bridge_pkg.security import SecurityMixin
from bridge_pkg.server import ServerMixin
from bridge_pkg.service_link import ServiceNotifier
from bridge_pkg.settings import Settings
from bridge_pkg.state import StateMixin


try:  # safe stop / resume of live jobs (2026-10-22): two files next to the bridge; without them the bridge works as before
    import live_stop
except ImportError:  # pragma: no cover - an old install that did not copy the new files
    live_stop = None


class Bridge(SecurityMixin, LiveJobMixin, CommandsMixin, DebugMixin, ActionsMixin, StateMixin, ServerMixin):
    def __init__(self, paths=None, link_factory=None, clock=None, threads=True):
        self.paths = paths or Paths()
        self.clock = clock or Clock()
        self.link_factory = link_factory or real_link_factory
        self.threads_enabled = threads
        self.settings = Settings(self.paths, log=self._warn)
        self.lock = threading.RLock()
        # Leaf lock for counters touched while a client's slot lock is held
        # (lock order: bridge.lock -> client.slot_lock -> stat_lock).
        self.stat_lock = threading.Lock()
        self.debug_ring = DebugRing(self.clock)
        self.debug_until = None            # monotonic deadline while debug is on
        self.viewer_mtime = None
        self.viewer_seen_at = None         # wall time of the last viewer heartbeat
        self.started_wall = self.clock.wall()
        self.owner = None
        self.owner_since = None
        self.clients = {}                  # id -> Client
        self.client_number = 0
        self.auto_names = {}               # ip -> "clientN": the automatic name stays with the IP while the bridge runs
        self.events = collections.deque(maxlen=60)
        self.rejected = collections.deque(maxlen=20)
        self.temp_blocks = {}              # ip -> until (wall)
        self.password_failures = {}        # ip -> consecutive failures
        self.last_reject_log = {}
        self.totals = collections.Counter({
            "connections": 0, "lines": 0, "orders": 0, "queries": 0, "rejects": 0, "bridge_commands": 0,
            "duet_errors": 0, "bytes_rx": 0, "bytes_tx": 0, "rejected_connections": 0, "wrong_passwords": 0,
            "kicked": 0, "cache_hits": 0, "coalesced": 0, "duet_queries": 0, "stale_served": 0,
            "query_errors": 0, "overtaken": 0,
        })
        self.history = collections.OrderedDict()   # minute -> [orders, queries, rejects, connections]
        self.timing = {"all": Timing(self.clock), "order": Timing(self.clock), "query": Timing(self.clock)}
        self.listening = {"port": None, "error": None}
        self.seq = 0
        self.action_seen = {"seq": None, "mtime": None, "result": None}
        self.pending_orders = 0
        self.last_order_wall = None
        self.last_motion_wall = None
        self.focus_lock = None             # {"since", "why"} while a declared focus failure is not solved (see focus_watch); only a good focus or the person lifts it
        self.focus_fail_seen = None        # the failure counter of the machine at the last look
        self.live_job = {"active": False, "name": None, "since": None, "client": None,
                         "last_event_at": None, "ended_at": None, "end_reason": None}
        self.queries = QueryService(self)
        self.live = live_stop.LiveStop(self) if live_stop is not None else None
        # live job notifications to WorkshopService (tests replace it with a list)
        self.service_notify = ServiceNotifier(self.paths, threads=threads, log=self._warn)
        self.gate = MachineGate(self, self.service_notify, threads=threads)
        self._last_state_write = 0.0
        self._last_state_check = 0.0
        self._state_sig = None
        self.state_writes = 0
        self._last_config_check = 0.0
        self._state_warned = False
        self._legacy_warned = None
        self.stop_event = threading.Event()

    # -- logging / events --
    @staticmethod
    def _warn(msg):
        LOG.warning(msg)

    def dbg(self, client, kind, text):
        self.debug_ring.add(client, kind, text)

    def event(self, kind, code, text, **args):
        with self.lock:
            self.events.appendleft({"time": time.strftime("%H:%M:%S"), "type": kind, "code": code, "args": args, "text": text})
        LOG.log(logging.WARNING if kind in ("security", "error") else logging.INFO, text)
        self.dbg("-", "event", text)

    def count(self, key):
        """Per-minute counter for the activity chart (last hour)."""
        idx = {"orders": 0, "queries": 1, "rejects": 2, "connections": 3}[key]
        minute = int(self.clock.wall() // 60)
        h = self.history.get(minute)
        if h is None:
            h = self.history[minute] = [0, 0, 0, 0]
            while len(self.history) > 60:
                self.history.popitem(last=False)
        h[idx] += 1

    # -- names --
    def label(self, client):
        return client.name if client is not None else "nobody"

    def label_ip(self, client):
        return f"{client.name} ({client.ip})" if client is not None else "nobody"

    def new_link(self):
        """A private DSF connection (the safe stop uses its own, never a client's queue)."""
        return DuetLink(self.link_factory, lambda: self.settings.get("order_timeout_s"), self.clock,
                        connect_wait=lambda: self.settings.get("order_timeout_s"))

    def find(self, wanted):
        w = (wanted or "").strip().lower()
        for c in self.clients.values():
            if c.name.lower() == w or c.id == w:
                return c
        return None
    # -- client registry --
    def new_client(self, sock, addr):
        with self.lock:
            self.client_number += 1
            return Client(self, sock, addr, self.client_number)

    def auto_name(self, ip):
        """Automatic name of a client: one per IP (the same PC is always "client1"), not a number that grows
        with every connection. A second live connection from the same IP gets "-2", "-3"."""
        base = self.auto_names.get(ip)
        if base is None:
            used = set(self.auto_names.values())
            n = 1
            while f"client{n}" in used:
                n += 1
            base = self.auto_names[ip] = f"client{n}"
        live = {c.name for c in self.clients.values()}
        name, k = base, 2
        while name in live:
            name, k = f"{base}-{k}", k + 1
        return name

    def register(self, client):
        with self.lock:
            self.clients[client.id] = client
            self.totals["connections"] += 1
            self.count("connections")
            self.event("connection", "connected", f"'{self.label_ip(client)}' connected", client=client.name, ip=client.ip)

    def unregister(self, client):
        with self.lock:
            was_owner = self.owner is client
            if was_owner:
                self.owner = None
                self.owner_since = None
            self.clients.pop(client.id, None)
            self.event("connection", "disconnected", f"'{self.label_ip(client)}' disconnected" + (" (had control: the bridge is free)" if was_owner else ""),
                       client=client.name, ip=client.ip, had_control=was_owner)
            job = self.live_job
            if job["active"] and job["client"] == client.name and not self.clients:
                self._end_live_job("disconnect")
        client.order_worker.stop()
        with client.slot_lock:
            client.slots.clear()
        client.closed = True
        try:
            client.sock.close()
        except Exception:
            pass
