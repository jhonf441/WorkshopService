"""The actions of the Services page (bridge-action.json)."""


import os
import secrets
import threading
import time

from bridge_pkg.fsutil import read_json, write_json_atomic


class ActionsMixin:
    """Page actions (mixed into Bridge)."""

    # -- page actions --
    def process_action(self):
        path = self.paths.action
        try:
            m = os.path.getmtime(path)
        except OSError:
            return
        if m == self.action_seen["mtime"]:
            return
        self.action_seen["mtime"] = m
        try:
            a = read_json(path)
        except (OSError, ValueError):
            return
        seq = a.get("seq")
        if seq is None or seq == self.action_seen["seq"]:
            return
        self.action_seen["seq"] = seq
        kind = str(a.get("action") or a.get("action") or "")
        ok, code, text = True, "done", "Done."
        try:
            code, text = self._run_action(kind, a, seq)
        except Exception as e:
            ok, code, text = False, "error", str(e)
        self.action_seen["result"] = {"seq": seq, "ok": ok, "code": code, "text": text, "time": time.strftime("%H:%M:%S")}

    @staticmethod
    def _field(a, *names):
        for n in names:
            if n in a and a[n] is not None:
                return a[n]
        return None

    def _run_live_action(self, kind, a, seq):
        """Safe stop and resume of the live job (live_stop.py). The stop waits for the board, so it runs in its own thread and the answer comes
        in the state file (live_stop.last_result); the others are instant."""
        if self.live is None:
            raise ValueError("this bridge has no safe stop (live_stop.py is missing: run install.sh again)")
        if kind == "stop_safe":
            mode, extra = a.get("mode"), {k: a[k] for k in ("boot_mark", "zone") if k in a}

            def work():
                try:
                    self.live.stop_safe(seq, mode, extra)
                except ValueError as e:
                    self.event("error", "stop_safe_failed", f"The safe stop failed: {e}", error=str(e))

            if self.threads_enabled:
                threading.Thread(target=work, name="safe-stop", daemon=True).start()
                return "stopping", "Stopping safely."
            work()
            return "stopped", "Stopped."
        if kind == "resume_arm":
            self.live.arm(str(a.get("id") or ""), a.get("overlap_lines") or 0, a.get("by"))
            return "armed", "Resume armed."
        if kind == "resume_disarm":
            self.live.disarm()
            return "disarmed", "Resume disarmed."
        self.live.discard(str(a.get("id") or ""))
        return "discarded", "Discarded."

    def _run_action(self, kind, a, seq):
        if kind in ("set_password", "clear_password"):
            return self._action_password(kind, a, seq)
        if kind == "trust":
            return self._action_trust(a)
        if kind == "block":
            return self._action_block(a)
        if kind == "unblock":
            return self._action_unblock(a)
        if kind == "restart":
            return self._action_restart()
        if kind in ("stop_safe", "resume_arm", "resume_disarm", "interrupted_discard"):
            return self._run_live_action(kind, a, seq)
        if kind == "focus_unlock":
            return self.unlock_focus_by_hand()
        if kind == "debug":
            return self._action_debug(a)
        if kind == "debug_extend":
            return self._action_debug_extend()
        if kind in ("rename", "give_control", "release", "kick"):
            return self._action_client(kind, a)
        raise ValueError(f"unknown action: {kind}")

    def _action_password(self, kind, a, seq):
        s = self.settings
        password = str(self._field(a, "password", "key") or "")
        # the password must not stay written on the SD
        try:
            write_json_atomic(self.paths.action, {"seq": seq, "action": kind, "done": True})
            self.action_seen["mtime"] = os.path.getmtime(self.paths.action)
        except OSError:
            pass
        if kind == "set_password":
            if len(password) < 4:
                raise ValueError("the password must have at least 4 characters")
            salt = secrets.token_hex(8)
            h = self.hash_password(password, salt)
            s.modify(lambda d: d.update(password_hash=h, password_salt=salt))
            with self.lock:
                for c in self.clients.values():
                    c.authenticated = False
            self.event("security", "password_set", "Bridge password set: untrusted connections can only query until they identify themselves")
            return "password_set", "Password set."
        s.modify(lambda d: d.update(password_hash="", password_salt=""))
        self.event("security", "password_cleared", "Bridge password removed")
        return "password_cleared", "Password removed."

    def _action_trust(self, a):
        s = self.settings
        ip = str(a.get("ip") or "")
        given = self._field(a, "yes", "si")
        yes = True if given is None else bool(given)

        def f(d):
            lst = [x for x in (d.get("trusted") or []) if x != ip]
            if yes:
                lst.append(ip)
            d["trusted"] = lst
        s.modify(f)
        self.event("security", "trusted" if yes else "untrusted", f"{ip} {'marked as trusted (sends orders without a password)' if yes else 'is no longer trusted'}", ip=ip)
        return "done", "Done."

    def _action_block(self, a):
        s = self.settings
        # Real block: cuts ALL connections of that IP and rejects new ones until
        # "unblock" (kick only cuts; the program reconnects at once). Kept in the
        # settings: survives restarts.
        ip = str(a.get("ip") or "")
        if not ip:
            raise ValueError("the IP is missing")

        def f(d):
            lst = [x for x in (d.get("blocked") or []) if x != ip]
            lst.append(ip)
            d["blocked"] = lst
            d["trusted"] = [x for x in (d.get("trusted") or []) if x != ip]
        s.modify(f)
        cut = 0
        with self.lock:
            for c in list(self.clients.values()):
                if c.ip != ip:
                    continue
                if self.owner is c:
                    self.owner = None
                    self.owner_since = None
                c.send_raw("Error: this IP was blocked from the workshop page.\r\n")
                c.shutdown()
                cut += 1
            self.totals["kicked"] += cut
        name = s.get("names").get(ip)
        self.event("security", "ip_blocked", f"{(repr(name) + ' (' + ip + ')') if name else ip} blocked from the page ({cut} connection(s) cut); it cannot connect again until unblocked",
                   ip=ip, name=name or "", cut=cut)
        return "ip_blocked", "Blocked."

    def _action_unblock(self, a):
        s = self.settings
        ip = str(a.get("ip") or "")
        self.temp_blocks.pop(ip, None)
        self.password_failures.pop(ip, None)
        if ip in s.get("blocked"):
            s.modify(lambda d: d.update(blocked=[x for x in (d.get("blocked") or []) if x != ip]))
        self.event("security", "ip_unblocked", f"{ip} unblocked from the page", ip=ip)
        return "ip_unblocked", "Unblocked."

    def _action_restart(self):
        # never while the bridge is in use: a live job running through it, or orders in the last 30 s
        if self.live_job.get("active"):
            raise ValueError("in use: a live job is running through the bridge")
        if self.last_order_wall and self.clock.wall() - self.last_order_wall < 30:
            raise ValueError("in use: orders arrived in the last 30 seconds")
        # the unit has Restart=always: leaving is enough, no sudo. Late, so this answer is written first.
        self.event("info", "restarting", "The page asked to restart the bridge (connections are cut and come back)")
        threading.Timer(1.5, lambda: os._exit(0)).start()
        return "restarting", "Restarting: the connections come back in a few seconds."

    def _action_debug(self, a):
        on = bool(a.get("on", True))
        self.set_debug(on)
        return "debug_on" if on else "debug_off", "Debug on." if on else "Debug off."

    def _action_debug_extend(self):
        if not self.debug_ring.active:
            raise ValueError("debug is off")
        minutes = self.settings.get("debug_timeout_min")
        self.debug_until = self.clock.mono() + minutes * 60
        self.event("info", "debug_extended", f"Debug extended: it turns off in {minutes} min", minutes=minutes)
        return "debug_extended", "Debug extended."

    def _action_client(self, kind, a):
        s = self.settings
        remember = False
        with self.lock:
            client = self.clients.get(str(self._field(a, "client", "cliente") or ""))
            if client is None and kind != "release":
                raise ValueError("that connection is gone")
            if kind == "rename":
                new = str(self._field(a, "name", "name") or "").strip()[:40]
                if not new:
                    raise ValueError("the name is missing")
                client.alias = new
                self.event("info", "renamed_from_page", f"{client.ip} is now called '{new}' (from the page)", ip=client.ip, name=new)
                given = self._field(a, "remember", "remember")
                remember = True if given is None else bool(given)
            elif kind == "give_control":
                before = self.owner
                self.owner = client
                self.owner_since = self.clock.wall()
                self.event("control", "control_given_from_page", f"The page gave control to '{client.name}' (before '{self.label(before)}')", target=client.name, owner=self.label(before))
            elif kind == "release":
                before = self.owner
                self.owner = None
                self.owner_since = None
                self.event("control", "control_released_from_page", f"The page released control (held by '{self.label(before)}')", owner=self.label(before))
            else:
                self.totals["kicked"] += 1
                self.event("security", "kicked", f"The page kicked '{self.label_ip(client)}'", client=client.name, ip=client.ip)
                client.send_raw("Error: the workshop page closed this connection.\r\n")
                client.shutdown()
        if kind == "rename" and remember:
            ip, new = client.ip, client.alias
            s.modify(lambda d: d.setdefault("names", {}).update({ip: new}))
        return "done", "Done."

    def prime_files(self):
        """At start remember the action already in the file (it must not run again)
        and the last viewer heartbeat (it is not a new viewer)."""
        try:
            self.action_seen["seq"] = read_json(self.paths.action).get("seq")
            self.action_seen["mtime"] = os.path.getmtime(self.paths.action)
        except (OSError, ValueError, AttributeError):
            pass
        try:
            self.viewer_mtime = os.path.getmtime(self.paths.viewer)
        except OSError:
            pass
