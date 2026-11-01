"""The HTTP server of the relay (port ports.CAMERA_RELAY): the routes are documented in camera_relay.py and classified by role in
camera_access.py (test_camera_access.py fails when a route here is not classified)."""
import http.server
import json
import os
import re
import select
import shutil
import socket
import socketserver
import threading
import time
import urllib.parse
import urllib.request

import camera_access
import camera_proto
import net_guard
import ports
import timelapse_look as look
import camera_captures
import camera_config
import camera_context
import camera_key
import camera_limits
import camera_notice
import camera_sources
import camera_timelapse
from camera_config import service
from camera_context import MAIN
from camera_sources import LOCAL, sources, sources_lock
from messages import M


BOUNDARY = b"123456789000000000000987654321"  # the same as the ESP32-camera's


def peer_closed(sock):
    """True when the screen has already closed its end. A stream that has no frame to send (the camera is reconnecting) writes nothing, so it would never see the
    screen leave and the relay would count a viewer that is gone (and keep the camera, its flash and its timers awake for it)."""
    try:
        ready, _, _ = select.select([sock], [], [], 0)
        if not ready:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        """CORS only for the own DWC (the Origin whose host is the host asked, any port); nobody else may read."""
        o = net_guard.cors_origin(self.headers.get("Origin"), self.headers.get("Host"))
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")

    def _foreign_origin(self):
        """True if the request comes from a page of another site (Origin present and not the own DWC)."""
        o = self.headers.get("Origin")
        return bool(o) and net_guard.cors_origin(o, self.headers.get("Host")) is None

    def _empty(self, code):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, route, type_name, download=False):
        if not os.path.isfile(route):
            return self._empty(404)
        length = os.path.getsize(route)
        self.send_response(200)
        self.send_header("Content-Type", type_name)
        self._cors()
        self.send_header("Content-Length", str(length))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(route)}"')
        self.end_headers()
        with open(route, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 65536)

    def _path(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path, urllib.parse.parse_qs(u.query)

    def do_OPTIONS(self):
        if self._foreign_origin():
            return self._empty(403)
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Workshop-Token, X-Workshop-Device")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._empty(200)  # liveness probe of the sidebar (HEAD /emergencyfab-ping, no-cors: any answer means alive); 200 keeps the network log quiet

    def _ip(self):
        return self.client_address[0] if self.client_address else ""

    def _allowed(self, q):
        """Local always; remote asks for the key only if DWC has a password."""
        if self._ip() in LOCAL or not service.get("key", True) or not camera_key.has_password():
            return True
        return camera_key.token_valid(camera_access.day_token(self.headers, q))

    def _without_key(self):
        body = json.dumps({"ok": False, "error": M("camera_relay_dwc_key_password_needed")}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refused(self, method, path, q):
        """True (and the answer sent) when the roles of camera_access.py do not let this call through."""
        ok, status, code = camera_access.authorize(self.headers, self._ip(), method, path, q, camera_key.token_valid)
        if ok:
            return False
        self._json({"ok": False, "code": code, "error": M("camera_relay_" + code)}, status)
        return True

    def do_POST(self):
        if self._foreign_origin():
            return self._empty(403)
        path, q = self._path()
        if not self._allowed(q):
            return self._without_key()
        if self._refused("POST", path, q):
            return
        if path in ("/luts", "/luts/remove"):
            name = (q.get("name") or [""])[0]
            if path == "/luts/remove":
                return self._json(camera_timelapse.lut_remove(name))
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = 0
            if size <= 0 or size > look.LUT_MAX_BYTES:
                return self._json({"ok": False, "error": M("camera_relay_lut_not_valid")}, 400)
            return self._json(camera_timelapse.lut_save(name, self.rfile.read(size)))
        return self._empty(404)

    def do_GET(self):
        if self._foreign_origin():
            return self._empty(403)
        path, q = self._path()
        if not self._allowed(q):
            return self._without_key()
        if self._refused("GET", path, q):
            return
        m = re.match(r"^/c/([A-Za-z0-9_-]+)(/.*)?$", path)
        cid, rest = (MAIN, path) if not m else (m.group(1), m.group(2) or "/stream")
        if rest in ("/stream", "/", "/snapshot") or rest.startswith("/control") or rest.startswith("/status"):
            f = camera_sources.source(cid)
            if f is None:
                return self._empty(404)
            if rest.startswith("/control"):
                f.invalidate()  # the next photo has to be from the new setting
            if rest.startswith("/control") or rest.startswith("/status"):
                return self._proxy(f, rest + ("?" + urllib.parse.urlsplit(self.path).query if urllib.parse.urlsplit(self.path).query else ""))
            if rest == "/snapshot":
                return self._photo(f, fresh=(q.get("fresh") or ["0"])[0] not in ("0", ""))
            return self._stream(f)
        if path == "/key" and self._ip() in LOCAL:
            # for other services of the Pi (Vision :8095): same rule as the relay
            requires = bool(service.get("key", True)) and camera_key.has_password()
            t = (q.get("t") or [""])[0]
            return self._json({"requires": requires, "ok": (not requires) or camera_key.token_valid(t)})
        if path == "/state":
            with sources_lock:
                fs = [f.summary() for f in sources.values()]
            return self._json({**camera_proto.describe(), "cameras": fs, "service": camera_config.service_cfg(), "timelapse": camera_timelapse.tl_state(),
                               "encoders": camera_timelapse.encoders(), "luts": look.list_luts(camera_context.LUTS_DIR),
                               "load": {k: camera_context.load[k] for k in ("level", "temp", "cpu", "kbps", "reason")},
                               "stop_screens": camera_sources.cap_screens()})
        if path == "/captures":
            return self._json(camera_captures.list_items_captures())
        if path == "/per_delete":
            return self._json(camera_limits.by_delete())
        if path.startswith("/captures/"):
            return self._file(os.path.join(camera_context.CAPTURES_DIR, os.path.basename(path)), "image/jpeg", "download" in q)
        if path == "/timelapses":
            return self._json(camera_captures.list_items_timelapses())
        if path == "/luts":
            return self._json(look.list_luts(camera_context.LUTS_DIR))
        if path == "/timelapse/preview":
            try:
                over = json.loads((q.get("cfg") or ["{}"])[0])
                jpg = camera_timelapse.look_preview((q.get("c") or [MAIN])[0], over if isinstance(over, dict) else {})
            except (ValueError, TypeError, AttributeError):
                jpg = None
            if not jpg:
                return self._empty(404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self._cors()
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)
            return
        if path == "/timelapse/last":
            # last photo of the timelapse being recorded (live view)
            jpg = camera_timelapse.last_frame((q.get("c") or [""])[0])
            if not jpg:
                return self._empty(404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self._cors()
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)
            return
        if path.startswith("/timelapses/"):
            a = os.path.basename(path)
            kind = {".mp4": "video/mp4", ".mov": "video/quicktime", ".zip": "application/zip", ".json": "application/json"}.get(os.path.splitext(a)[1], "image/jpeg")
            return self._file(os.path.join(camera_context.TIMELAPSE_DIR, a), kind, "download" in q)
        return self._empty(404)

    def _part(self, frame):
        self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n")
        self.wfile.write(frame)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _stream(self, f):
        """Each screen in its thread: it waits for the last frame and sends it. If it is slow it skips frames; if it accepts nothing for 5 s it is dropped."""
        f.seen()
        cli = camera_sources.Client(self._ip())
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=" + BOUNDARY.decode())
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()
        self.connection.settimeout(5)
        if not f.allow(cli):
            notice = camera_notice.frame_notice(M("camera_relay_too_many_screens_watching_wait_minute", label=f.label))
            try:
                if notice:
                    self._part(notice)
            except Exception:
                pass
            return
        f.ensure()
        try:
            while True:
                cli.new.wait(15)
                cli.new.clear()
                if cli.shut is not None:
                    notice = camera_notice.frame_notice(cli.shut) if cli.shut else None
                    if notice:
                        self._part(notice)
                    break
                frame, cli.frame = cli.frame, None
                if frame is None:
                    with f.lock:
                        if cli not in f.clients:
                            break  # the camera was removed or changed address
                    if peer_closed(self.connection):
                        break  # nothing to send, so only this tells that the screen left
                    continue
                if not cli.local and camera_context.load["level"] >= 1:
                    missing = 1.0 / max(1, service.get("load_fps", 5)) - (time.time() - cli.last_sending)
                    if missing > 0:
                        time.sleep(missing)
                        frame = cli.frame or frame  # the newest that has arrived
                        cli.frame = None
                self._part(frame)
                cli.sent += 1
                cli.last_sending = time.time()
                if not cli.local:
                    cli.bytes_sec.append((cli.last_sending, len(frame)))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError):
            pass
        finally:
            f.drop(cli)

    def _proxy(self, f, rest):
        try:
            with urllib.request.urlopen(f.base + rest, timeout=5) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "text/plain"))
                self._cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception:
            self._empty(502)

    def _photo(self, f, fresh=False):
        f.seen()
        r = f.photo(fresh=fresh)
        if not r:
            return self._empty(502)
        body, type_name = r
        self.send_response(200)
        self.send_header("Content-Type", type_name)
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # The client closed the connection in the middle of an answer (camera panel closed, page
        # reloaded): it is normal. Without this socketserver prints the traceback and DSF shows it
        # as a WorkshopService error in DWC (2026-10-09).
        import sys

        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


server = [None]


def start_server():
    srv = Server((camera_context.cfg["bind"], ports.CAMERA_RELAY), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    server[0] = srv
    camera_context.log(f"camera: relay listening on {camera_context.cfg['bind']}:{ports.CAMERA_RELAY}")


def stop_server():
    srv = server[0]
    server[0] = None
    if srv:
        srv.shutdown()
        srv.server_close()
        with sources_lock:
            for f in sources.values():
                with f.lock:
                    cs = list(f.clients)
                    f.clients.clear()
                for c in cs:
                    c.cut("")
        camera_context.log("camera: relay stopped")
