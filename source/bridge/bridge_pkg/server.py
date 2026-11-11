"""Periodic work and the listening socket of the bridge."""


import json
import socket
import threading
import time

from bridge_pkg.fsutil import ensure_action_file
from bridge_pkg.log import LOG
from bridge_pkg.state import STATE_CHECK_S, STATE_HEARTBEAT_S


HOST = "0.0.0.0"


class ServerMixin:
    """Tick loop and listening socket (mixed into Bridge)."""

    # -- periodic work (the tick thread calls this about 10 times a second) --
    def tick(self):
        mono = self.clock.mono()
        self.queries.expire()
        for c in list(self.clients.values()):
            if c.slots:
                c.flush()
        if mono - self._last_config_check >= 1.0:
            self._last_config_check = mono
            self.settings.load()
            self.process_action()
            self.debug_tick()
        if mono - self._last_state_check >= STATE_CHECK_S:
            self._last_state_check = mono
            self.write_state_if_due(mono)

    def write_state_if_due(self, mono):
        """Writes when the content changed (at once, within one check) or, if nothing changed, as a heartbeat every STATE_HEARTBEAT_S."""
        state = self.build_state()
        changed = json.dumps(self._significant(state), sort_keys=True, default=str) != self._state_sig
        if changed or mono - self._last_state_write >= STATE_HEARTBEAT_S:
            self.write_state(state, mono)

    def tick_loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                LOG.warning("error in the periodic cycle: %s", e)
            self.stop_event.wait(0.1)

    # -- listening socket --
    @staticmethod
    def open_socket(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, port))
        s.listen(8)
        s.settimeout(1.0)
        return s

    @staticmethod
    def keepalive(conn):
        # Dead connections (suspended PC, dropped WiFi) are cut in ~30 s and free the control.
        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            conn.setsockopt(socket.IPPROTO_TCP, getattr(socket, "TCP_USER_TIMEOUT", 18), 30000)
        except Exception as e:
            LOG.warning("could not set keepalive: %s", e)

    def serve(self):
        for m in ensure_action_file(self.paths, log=LOG.warning):
            print(f"start: {m}", flush=True)
        self.settings.load()
        self.prime_files()
        self.debug_tick()
        self.queries.start()
        threading.Thread(target=self.tick_loop, name="tick", daemon=True).start()
        server = None
        while True:
            port = self.settings.get("port")
            if server is None or self.listening["port"] != port:
                if server is not None:
                    server.close()
                    self.event("info", "port_changed", f"Port change: {self.listening['port']} -> {port} (connected clients stay)", old=self.listening["port"], new=port)
                try:
                    server = self.open_socket(port)
                    self.listening["port"] = port
                    self.listening["error"] = None
                    self.event("info", "listening", f"Listening on port {port} (exclusive: {self.settings.get('exclusive')}, password: {'yes' if self.needs_password() else 'no'})",
                               port=port, exclusive=self.settings.get("exclusive"), password=self.needs_password())
                    if self.exposed():
                        self.event("security", "orders_refused_until_guard", "No password, no allowed list and no trusted address: the network can only query. "
                                   "Set a password, `allowed` (for example the PC's address) or a trusted address to send orders", port=port)
                except OSError as e:
                    server = None
                    self.listening["error"] = f"Could not open port {port}: {e}"
                    LOG.warning(self.listening["error"])
                    time.sleep(5)
                    continue
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                server = None
                continue
            if not self.admit(conn, addr):
                continue
            conn.settimeout(None)
            self.keepalive(conn)
            client = self.new_client(conn, addr)
            self.register(client)
            threading.Thread(target=client.run, name=f"client-{client.name}", daemon=True).start()
