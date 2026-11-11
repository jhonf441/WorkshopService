"""Who may connect and who may send orders: allowed list, trusted addresses, scrypt password, blocks."""


import hashlib
import ipaddress
import secrets
import time

from bridge_pkg.log import LOG


class SecurityMixin:
    """Access guard of the bridge (mixed into Bridge)."""

    # -- security --
    def ip_allowed(self, ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        nets = self.settings.get("allowed")
        if not nets:
            return a.is_private or a.is_loopback
        for n in nets:
            try:
                if a in ipaddress.ip_network(n, strict=False):
                    return True
            except ValueError:
                continue
        return a.is_loopback  # the Pi can always talk to itself

    def exposed(self):
        """True when nothing says WHO may send orders: no password, no allow-list and no trusted address. Orders are then refused from the
        network (only the Pi itself and queries pass) until one of the three is set; it used to let every private address order."""
        return not self.settings.get("allowed") and not self.needs_password() and not self.settings.get("trusted")

    def is_trusted(self, ip):
        return ip in self.settings.get("trusted")

    @staticmethod
    def hash_password(password, salt):
        """scrypt (the same parameters family as dsf/users.py), stored as "scrypt$<hex>"."""
        raw = hashlib.scrypt(password.encode(), salt=salt.encode(), n=2 ** 14, r=8, p=1, dklen=32)
        return "scrypt$" + raw.hex()

    def _valid_hash(self):
        """The stored scrypt hash, or "" when there is none. A hash in any other format (the sha256 of bridges before 2026-10-26) is not a
        valid password: the bridge acts as if no password was set and says so once in the log. No migration: set the password again."""
        h = self.settings.get("password_hash")
        if not h:
            return ""
        if isinstance(h, str) and h.startswith("scrypt$"):
            return h
        if self._legacy_warned != h:
            self._legacy_warned = h
            LOG.warning("bridge.json holds a password hash in an old format: it is ignored and the bridge acts as if no password was set. "
                        "Set the password again (Services > G-code bridge, or install.sh guard)")
        return ""

    def password_ok(self, password):
        """Slow on purpose (scrypt): never call it with self.lock held."""
        h = self._valid_hash()
        if not h:
            return False
        salt = self.settings.get("password_salt") or ""
        return secrets.compare_digest(self.hash_password(password, salt), h)

    def needs_password(self):
        return bool(self._valid_hash())

    @staticmethod
    def is_local_ip(ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return a.is_loopback or bool(getattr(a, "ipv4_mapped", None) and a.ipv4_mapped.is_loopback)

    def can_order(self, client):
        """Orders (anything that is not a query) need: the Pi itself, or a trusted address, or the password, or - with no password - an
        allow-list the owner wrote (the client already passed it in `ip_allowed`). With none of them set, nobody on the network orders."""
        if self.is_local_ip(client.ip) or self.is_trusted(client.ip):
            return True
        if self.needs_password():
            return client.authenticated
        return bool(self.settings.get("allowed"))

    def role(self, client):
        if client is self.owner:
            return "control"
        if not self.can_order(client):
            return "no_password"
        return "listener"

    def reject_connection(self, sock, addr, code, reason):
        ip = addr[0]
        with self.lock:
            self.totals["rejected_connections"] += 1
            self.rejected.appendleft({"time": time.strftime("%H:%M:%S"), "ip": ip, "code": code, "text": reason})
            # one event per IP per minute (a scan does not fill the list)
            if self.clock.mono() - self.last_reject_log.get(ip, -1e9) > 60:
                self.last_reject_log[ip] = self.clock.mono()
                self.event("security", "connection_rejected", f"Connection rejected from {ip}: {reason}", ip=ip, reason=code)
        try:
            sock.sendall(f"Error: {reason}\r\n".encode())
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass

    def admit(self, sock, addr):
        ip = addr[0]
        if ip in self.settings.get("blocked"):
            self.reject_connection(sock, addr, "ip_blocked_page", "IP blocked from the workshop page (Services > Bridge > Unblock)")
            return False
        until = self.temp_blocks.get(ip)
        if until and until > self.clock.wall():
            self.reject_connection(sock, addr, "ip_blocked_password", f"IP blocked for wrong passwords ({int(until - self.clock.wall())} s)")
            return False
        if until:
            self.temp_blocks.pop(ip, None)
        if not self.ip_allowed(ip):
            self.reject_connection(sock, addr, "ip_not_allowed", "IP not allowed on this bridge")
            return False
        with self.lock:
            n = len(self.clients)
        if n >= self.settings.get("max_connections"):
            self.reject_connection(sock, addr, "too_many_connections", f"too many connections ({n})")
            return False
        return True
