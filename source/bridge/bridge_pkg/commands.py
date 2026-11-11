"""The BRIDGE commands a client types (BRIDGE KEY, USE, JOB START ...)."""


import time

from bridge_pkg.lines import TAINT_S, parse_job_command
from bridge_pkg.textutil import mask


SUBCOMMANDS = {
    "HELP": "HELP", "?": "HELP", "": "HELP",
    "STATUS": "STATUS",
    "LIST": "LIST",
    "NAME": "NAME",
    "USE": "USE",
    "RELEASE": "RELEASE",
    "KEY": "KEY",
    "JOB": "JOB",
    "RESUME": "RESUME",
}

HELP_TEXT = (
    "Workshop G-code bridge (port {port}). Commands:\n"
    "  BRIDGE STATUS           - who has control now\n"
    "  BRIDGE LIST             - open connections\n"
    "  BRIDGE NAME <name>      - name this connection (without a name: shows it)\n"
    "  BRIDGE USE [name]       - take control (or give it to that connection)\n"
    "  BRIDGE RELEASE          - release control\n"
    "  BRIDGE KEY <password>   - identify yourself to send orders (if the bridge asks for a password)\n"
    "  BRIDGE JOB START [name] - a live job starts (put it in the start G-code of the program)\n"
    "  BRIDGE JOB END          - the live job ended (end G-code); BRIDGE JOB CANCEL if it was cut\n"
    "  M118 P0 S\"BRIDGE JOB START name\" - the same mark as a real G-code (also valid inside an uploaded file)\n"
    "  BRIDGE HELP             - this help\n"
    "Everything else is sent to the machine as G-code. Queries (M114, M105...)\n"
    "always work; orders only for whoever has control."
)


class CommandsMixin:
    """BRIDGE commands (mixed into Bridge)."""

    # -- BRIDGE commands --
    def _job_start_refusal(self, sub, arg, client):
        """BRIDGE JOB START on a machine that cannot take the job (off, halted, paused, not homed): the text of the refusal, or None.
        The live job is not opened, and the rest of what the program streams is refused too (like any refused order), so the focus macro
        that comes next does not run on its own. The state is asked again when what the gate has is older than a second (the gate itself
        asks every 2 s); an unknown state (service stopped, no answer) lets the job start: the gate never blocks by guessing."""
        if sub != "JOB" or not self.can_order(client) or not self.settings.get("block_when_unfit"):
            return None
        job = parse_job_command(arg)
        if job is None or job[0] != "start":
            return None
        if time.monotonic() - self.gate.at > 1.0:
            try:
                self.gate.refresh()
            except Exception:
                self.gate.status = None
        why = self.gate.reason()
        if not why:
            return None
        client.taint_until = self.clock.mono() + TAINT_S
        with self.lock:
            self.totals["rejects"] += 1
            self.totals["rejects_machine"] = self.totals.get("rejects_machine", 0) + 1
            client.rejects += 1
            self.count("rejects")
        self.event("info", "job_start_rejected_machine", f"Live job start from '{client.name}' rejected: the machine is {why}", client=client.name, state=why)
        return f"Error: the machine is {why}; the live job was not started. Fix it and send the job again."

    def bridge_command(self, line, client):
        parts = line.split(None, 2)
        sub = SUBCOMMANDS.get(parts[1].upper() if len(parts) > 1 else "", None)
        arg = parts[2].strip() if len(parts) > 2 else ""
        refused = self._job_start_refusal(sub, arg, client)  # outside the lock: it may ask the service
        if refused:
            return refused, False
        # scrypt takes about 100 ms on the Pi: it runs BEFORE the lock, so one slow attempt does not hold back the other clients
        key_ok = bool(sub == "KEY" and arg and self.needs_password() and self.password_ok(arg))
        with self.lock:
            self.totals["bridge_commands"] += 1
            if sub == "KEY":
                ip = client.ip
                if not self.needs_password():
                    return "This bridge does not ask for a password.", False
                if key_ok:
                    client.authenticated = True
                    self.password_failures.pop(ip, None)
                    self.event("security", "password_ok", f"'{client.name}' identified with the password", client=client.name)
                    return "Password correct: you can send orders now.", False
                self.totals["wrong_passwords"] += 1
                n = self.password_failures[ip] = self.password_failures.get(ip, 0) + 1
                limit = self.settings.get("password_attempts")
                if n >= limit:
                    secs = self.settings.get("block_seconds")
                    self.temp_blocks[ip] = self.clock.wall() + secs
                    self.password_failures.pop(ip, None)
                    self.event("security", "ip_blocked_by_password", f"{ip} blocked for {secs // 60} min after {n} wrong passwords", ip=ip, minutes=secs // 60, attempts=n)
                    return f"Wrong password. {ip} is blocked for {secs // 60} min.", True
                self.event("security", "password_wrong", f"Wrong password from '{self.label_ip(client)}' ({n}/{limit})", client=client.name, ip=ip, n=n, limit=limit)
                return f"Wrong password ({n}/{limit}).", False
            if sub == "NAME" and arg:
                arg = arg[:40]
                client.name = arg
                self.event("info", "renamed", f"{client.ip} is now called '{arg}'", ip=client.ip, name=arg)
                return f"Name set: {arg}", False
            if sub == "NAME":
                return f"You are '{self.label_ip(client)}'. Use BRIDGE NAME <name> to change it.", False
            if sub == "STATUS":
                extra = "" if self.can_order(client) else " Without the password you can only query (BRIDGE KEY <password>)."
                if self.owner is None:
                    return f"Bridge free: the first connection that sends an order takes control. You are '{self.label_ip(client)}'.{extra}", False
                return f"Control is held by '{self.label_ip(self.owner)}'. You are '{self.label_ip(client)}'.{extra}", False
            if sub == "RELEASE":
                before = self.owner
                self.owner = None
                self.owner_since = None
                self.event("control", "control_released", f"'{client.name}' released control (held by '{self.label(before)}')", client=client.name, owner=self.label(before))
                return f"Control released (held by '{self.label_ip(before)}').", False
            if sub == "RESUME":
                was = client.failed_until > self.clock.mono()
                client.failed_until = 0.0
                client.taint_until = 0.0
                return ("Orders accepted again." if was else "Nothing was stopped."), False
            if sub == "LIST":
                names = [self.label_ip(c) + (" [control]" if c is self.owner else "") for c in sorted(self.clients.values(), key=lambda c: c.name)]
                return ("Connected: " + ", ".join(names)) if names else "No connections.", False
            if sub == "USE":
                if not self.can_order(client):
                    return "This bridge asks for a password to take control: BRIDGE KEY <password>.", False
                target = client if not arg else self.find(arg)
                if target is None:
                    return f"No connection called '{arg}'. Connected: {', '.join(c.name for c in self.clients.values())}", False
                before = self.owner
                self.owner = target
                self.owner_since = self.clock.wall()
                self.event("control", "control_given", f"'{client.name}' gave control to '{target.name}' (before '{self.label(before)}')",
                           client=client.name, target=target.name, owner=self.label(before))
                return f"'{self.label_ip(target)}' has control now.", False
            if sub == "JOB":
                if not self.can_order(client):
                    return "Error: this bridge asks for a password to mark jobs: BRIDGE KEY <password>.", False
                job = parse_job_command(arg)
                if job is None:
                    return "Error: use BRIDGE JOB START [name], BRIDGE JOB END or BRIDGE JOB CANCEL.", False
                if job[0] == "start":
                    if self.live_job["active"]:
                        self._end_live_job("close")  # a new start closes the previous one
                    self._start_live_job(client, job[1])
                    return "Live job started" + (f": {job[1]}" if job[1] else "") + ".", False
                if not self.live_job["active"]:
                    return "No live job was open.", False
                self._end_live_job(job[1])
                return f"Live job ended ({job[1]}).", False
            if sub == "HELP":
                return HELP_TEXT.format(port=self.listening["port"]), False
        return f"Unknown command: '{mask(line)}'. Type BRIDGE HELP for the list.", False
