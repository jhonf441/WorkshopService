#!/usr/bin/env python3
"""The API of the service on this PC, for developing and testing the service page without the machine (environment E2).

    python tools/dev/api_server.py [--port 8765] [--scenario open|users|anonymous|damaged] [--rows N] [--data DIR]

It serves the REAL registry of dsf/ (tools/dev/dev_backend.py) on 127.0.0.1 only:

    POST/GET /machine/WorkshopService/api      the same entry, body and answers as on the machine

and a control surface for the tests under /__dev/ (JSON in, JSON out):

    GET  /__dev/state                          scenario, people and PINs of the seed, clock, what the isolation refused
    POST /__dev/seed      {scenario, rows, broken_chain}     back to an empty service, then the scenario (tools/dev/dev_seed.py)
                                               (faults removed, clock back to the real time, every session closed)
    POST /__dev/reset                          the last seed again
    POST /__dev/fault     {op, kind, ...}      make an operation fail (see FAULT_KINDS); op "*" = every operation
    GET/DELETE /__dev/fault                    the faults that are set / remove them all
    POST /__dev/clock     {advance_s}          move the clock forward (sessions expire, ages grow)
    GET  /__dev/published                      the plugin data the service publishes (plugins.WorkshopService.data)
    POST /__dev/published {key: value, ...}    change published keys; {"_process": {"id": "error text" | null}} breaks / heals a process;
                                               {"_notice": "name"} puts ONE notice on a healthy machine (names in /__dev/state `notices`;
                                               "none" = the healthy machine again); {"_global": {"name": value}} sets a global of the board
    POST /__dev/machine   {state, restart}     state: idle | job | live | off ; restart: returns | never | gone (what service.restart does)
    POST /__dev/replies   {"M115": "text"}     what the board answers to a code that starts like that
    GET/DELETE /__dev/requests[?since=N]       every request received (operation, arguments, headers, status) / forget them; secrets
                                               are not kept: a PIN, password or key argument is "***", a token is its first 6 characters
    GET  /__dev/codes                          the G-codes the service would have sent to the board
    GET  /__dev/model                          the object model a DWC would receive (tools/dev/dwc_sim.js reads it)

Nothing here talks to the machine: the process may only connect to this computer, launches no program and writes only under its
data folder (a throwaway one unless --data is given). Standard library only.
"""
import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dev_backend  # noqa: E402

API_PATH = "/machine/%s/api" % dev_backend.PLUGIN_ID
FAULT_KINDS = {
    "error": "answer the error `code` (with `message`, and `extra` fields) with the status the service gives that code",
    "http": "answer the bare HTTP `status` (502, 503...) with an empty body, as when the service is stopped",
    "delay": "wait `delay_s` seconds, then answer normally",
    "garbage": "answer 200 with a body that is not JSON",
    "drop": "close the connection without answering",
}
MACHINE_STATES = {"idle": "idle", "job": "processing", "live": "idle", "off": "off"}
KEPT_HEADERS = ("x-workshop-token", "x-workshop-device", "x-workshop-key", "x-session-key", "content-type", "origin", "referer")
SECRET_HEADERS = ("x-workshop-token", "x-workshop-key")
SECRET_ARGS = ("password", "key", "pin", "old_pin", "new_pin", "token", "topic", "local_key")      # the same names the service masks in its history
# the HTTP status of the codes the service raises with a status of their own (identity.py, api_users.py); the rest follow ApiError.STATUS
OWN_STATUS = {"login_required": 401, "bad_credentials": 401, "locked": 429, "damaged": 403, "pin_policy": 422, "invalid_name": 422}


def masked_args(args):
    if not isinstance(args, dict):
        return args
    return {k: ("***" if k in SECRET_ARGS and v not in (None, "") else v) for k, v in args.items()}


def masked_headers(headers):
    out = {}
    for k, v in headers.items():
        key = k.lower()
        if key in KEPT_HEADERS:
            out[key] = (str(v)[:6] + "...") if key in SECRET_HEADERS and v else v
    return out


class Dev:
    """The state of the control surface."""

    def __init__(self, backend):
        self.backend = backend
        self.lock = threading.RLock()
        self.faults = []        # {op, kind, times (None = until removed), ...}
        self.requests = []      # {n, t, method, path, op, args, confirm, origin, headers, status, fault}
        self.count = 0
        self.seed = {"scenario": "open", "rows": 0, "broken_chain": False}
        self.summary = {}

    def apply_seed(self, scenario=None, rows=None, broken_chain=None):
        import dev_seed
        with self.lock:
            if scenario is not None:
                self.seed = {"scenario": scenario, "rows": int(rows or 0), "broken_chain": bool(broken_chain)}
            self.faults = []
            dev_backend._clock["offset"] = 0.0    # a seed starts at the real time again
            self.summary = dev_seed.apply(self.backend, self.seed["scenario"], self.seed["rows"], self.seed["broken_chain"])
            return self.summary

    def fault_for(self, op):
        with self.lock:
            for f in self.faults:
                if f["op"] in ("*", op):
                    if f.get("times") is not None:
                        f["times"] -= 1
                        if f["times"] <= 0:
                            self.faults.remove(f)
                    return f
        return None

    def record(self, entry):
        with self.lock:
            self.count += 1
            entry["n"] = self.count
            self.requests.append(entry)
            del self.requests[:-5000]

    def machine(self, body):
        b = self.backend
        state = body.get("state")
        if state is not None:
            if state not in MACHINE_STATES:
                raise ValueError("state: one of " + ", ".join(MACHINE_STATES))
            job = state == "job"
            b.subscription.patch({"state": {"status": MACHINE_STATES[state]}, "job": {"file": {"fileName": "0:/gcodes/dev-part.nc" if job else None}}})
            b.bridge.set_status("liveJob", {"active": True, "name": "Dev live job", "file": "", "since": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                            "lastActivity": time.strftime("%Y-%m-%dT%H:%M:%S")} if state == "live" else None)
        if body.get("restart") is not None:
            if body["restart"] not in ("returns", "never", "gone"):
                raise ValueError("restart: returns | never | gone")
            b.restart_mode = body["restart"]
        return {"status": b.model["state"]["status"], "restart": b.restart_mode, "pid": b.pid}

    def publish(self, body):
        import dev_fixtures
        b = self.backend
        for key, value in body.items():
            if key == "_notice":
                dev_fixtures.apply_notice(b, value)
            elif key == "_global":
                b.subscription.patch({"global": dict(value or {})})
            elif key == "_process":
                for pid, text in (value or {}).items():
                    if text is None:
                        b.unhealthy.pop(pid, None)
                    else:
                        b.unhealthy[pid] = str(text)
            else:
                b.bridge.set_status(key, value)
        b.beat()
        return b.bridge.published


def make_handler(dev):
    backend = dev.backend

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        wbufsize = 65536        # headers and body leave in ONE write
        server_version = "WorkshopDev"

        def log_message(self, *a):
            return None

        # An answer leaves in ONE write (wbufsize) and the socket closes after the client finished reading (lingering close). With the
        # headers and the body in two writes, on Windows a client lost about one answer in 500 half read (connection reset): 0 in 2000 now.
        def finish(self):
            try:
                super().finish()
            except (OSError, ValueError):
                pass                    # the connection was dropped on purpose (fault "drop")
            finally:
                try:
                    self.connection.shutdown(socket.SHUT_WR)
                    self.connection.settimeout(1.0)
                    while self.connection.recv(4096):
                        pass
                except OSError:
                    pass

        def _send(self, status, body, raw=None):
            data = raw if raw is not None else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8" if raw is None else "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")     # one request per connection: no half-read socket is ever closed under a client
            self.close_connection = True
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n).decode("utf-8", "replace") if n else ""

        def _json(self):
            text = self._body()
            return json.loads(text) if text.strip() else {}

        # ---- the API ----
        def _api(self, method):
            body = self._body() if method == "POST" else ""
            headers = {k: v for k, v in self.headers.items()}
            entry = {"t": time.strftime("%H:%M:%S"), "method": method, "path": self.path, "op": None, "args": None, "confirm": False, "origin": "",
                     "headers": masked_headers(headers), "status": None, "fault": None}
            try:
                d = json.loads(body) if body.strip() else {}
                if isinstance(d, dict):
                    entry.update(op=d.get("op"), args=masked_args(d.get("args")), confirm=bool(d.get("confirm")), origin=d.get("origin") or "")
            except ValueError:
                pass
            op = entry["op"] or "api.describe"
            fault = dev.fault_for(op)
            if fault:
                entry["fault"] = fault["kind"]
            try:
                if fault and fault["kind"] == "delay":
                    time.sleep(float(fault.get("delay_s") or 1))
                if fault and fault["kind"] == "drop":
                    entry["status"] = 0
                    self.close_connection = True
                    self.connection.close()
                    return
                if fault and fault["kind"] == "http":
                    entry["status"] = int(fault.get("status") or 503)
                    self.send_response(entry["status"])
                    self.send_header("Content-Length", "0")
                    self.send_header("Connection", "close")
                    self.close_connection = True
                    self.end_headers()
                    return
                if fault and fault["kind"] == "garbage":
                    entry["status"] = 200
                    return self._send(200, None, raw=b"<html><body>502 Bad Gateway</body></html>")
                if fault and fault["kind"] == "error":
                    status, out = backend.error_body(op, fault.get("code") or "failed", fault.get("message"), fault.get("extra"))
                    status = int(fault.get("status") or OWN_STATUS.get(fault.get("code"), status))
                else:
                    # a DWC session: the simulator sends its session key; without it the call is an open one, as from a program
                    session = 1 if self.headers.get("X-Session-Key") else None
                    status, out = backend.handle(headers, body, session)
                entry["status"] = status
                self._send(status, out)
            finally:
                dev.record(entry)

        # ---- the control surface ----
        def _dev(self, method):
            url = urlparse(self.path)
            what = url.path[len("/__dev/"):].strip("/")
            try:
                if what == "state" and method == "GET":
                    out = {"seed": dev.seed, "summary": dev.summary, "version": backend.version, "pid": backend.pid, "restart": backend.restart_mode,
                           "clock_offset_s": dev_backend._clock["offset"], "machine": backend.model["state"]["status"], "requests": dev.count,
                           "faults": dev.faults, "blocked": dev_backend.blocked, "data_root": backend.root, "fault_kinds": FAULT_KINDS,
                           "notices": sorted(__import__("dev_fixtures").NOTICES), "log": backend.log_lines[-40:]}
                elif what == "seed" and method == "POST":
                    b = self._json()
                    out = dev.apply_seed(b.get("scenario") or "open", b.get("rows"), b.get("broken_chain"))
                elif what == "reset" and method == "POST":
                    out = dev.apply_seed()
                elif what == "fault":
                    if method == "POST":
                        b = self._json()
                        if b.get("kind") not in FAULT_KINDS or not b.get("op"):
                            raise ValueError("fault: {op, kind} with kind one of " + ", ".join(FAULT_KINDS))
                        with dev.lock:
                            dev.faults.append(dict(b, times=int(b["times"]) if b.get("times") else None))
                    elif method == "DELETE":
                        with dev.lock:
                            dev.faults = []
                    out = {"faults": dev.faults}
                elif what == "clock" and method == "POST":
                    out = {"clock_offset_s": dev_backend.advance_clock(self._json().get("advance_s") or 0)}
                elif what == "published":
                    out = dev.publish(self._json()) if method == "POST" else backend.bridge.published
                elif what == "machine" and method == "POST":
                    out = dev.machine(self._json())
                elif what == "replies" and method == "POST":
                    backend.bridge.replies.update(self._json())
                    out = {"replies": backend.bridge.replies}
                elif what == "model" and method == "GET":
                    out = backend.full_model()
                elif what == "codes" and method == "GET":
                    out = {"codes": backend.bridge.sent}
                elif what == "requests":
                    if method == "DELETE":
                        with dev.lock:
                            dev.requests = []
                    since = int((parse_qs(url.query).get("since") or ["0"])[0])
                    out = {"count": dev.count, "requests": [r for r in dev.requests if r["n"] > since]}
                else:
                    return self._send(404, {"error": "unknown control path /__dev/" + what})
                self._send(200, out)
            except Exception as e:  # noqa: BLE001 - a control call answers its own error
                self._send(400, {"error": "%s: %s" % (type(e).__name__, e)})

        def _route(self, method):
            path = urlparse(self.path).path
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._send(403, {"error": "local only"})
            if path == API_PATH and method in ("GET", "POST"):
                return self._api(method)
            if path.startswith("/__dev/"):
                return self._dev(method)
            self._send(404, {"error": "not found: " + path})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_DELETE(self):
            self._route("DELETE")

    return Handler


def serve(port=8765, scenario="open", rows=0, data=None, ready=None):
    """Starts the backend and the HTTP server; returns (server, dev). `ready` is called with the port once it listens."""
    data = data or tempfile.mkdtemp(prefix="wsvc-dev-")
    backend = dev_backend.Backend(data)
    dev = Dev(backend)
    dev.apply_seed(scenario, rows, False)
    ThreadingHTTPServer.request_queue_size = 128     # the default (5) is short for a browser that opens several connections at once
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(dev))
    server.daemon_threads = True

    def ticker():
        while True:
            time.sleep(5)
            try:
                with dev.lock:
                    backend.beat()
            except Exception:
                pass
    threading.Thread(target=ticker, daemon=True, name="dev-beat").start()
    if ready:
        ready(server.server_address[1])
    return server, dev


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765, help="0 = any free port")
    ap.add_argument("--scenario", default="open", choices=["open", "users", "anonymous", "damaged"])
    ap.add_argument("--rows", type=int, default=0, help="rows seeded in activity, received commands and audit")
    ap.add_argument("--data", default=None, help="data folder (default: a throwaway one in the temp folder)")
    args = ap.parse_args(argv)
    server, dev = serve(args.port, args.scenario, args.rows, args.data)
    print("workshop dev api: http://127.0.0.1:%d%s  (control: /__dev/state)  scenario=%s  data=%s" % (server.server_address[1], API_PATH, args.scenario, dev.backend.root), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
