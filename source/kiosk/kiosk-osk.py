#!/usr/bin/env python3
"""kiosk-osk.py -- shows / hides the kiosk's on-screen keyboard (squeekboard) when the page asks.

Why (2026-10-22): Chromium on the kiosk (Wayland, labwc) does not always tell squeekboard that a text field got the focus, so
fields of the pages (the PIN dialog, ...) opened no keyboard. The page (only when it runs on this same machine, host "localhost")
asks here with a GET and this script flips the keyboard through squeekboard's D-Bus interface (sm.puri.OSK0 SetVisible).

    GET http://127.0.0.1:8099/osk/show
    GET http://127.0.0.1:8099/osk/hide

When the browser is not running it also hides the keyboard (closing DWC left it open). It listens only on 127.0.0.1, so nothing outside this machine can reach it. It is launched from ~/.config/labwc/autostart.
"""
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8099
WATCH_S = 2  # how often it looks whether the browser is still there


def set_visible(visible):
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    subprocess.run(
        ["busctl", "--user", "call", "sm.puri.OSK0", "/sm/puri/OSK0", "sm.puri.OSK0", "SetVisible", "b", "true" if visible else "false"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False,
    )


def browser_running():
    return subprocess.run(["pgrep", "-x", "chromium"], stdout=subprocess.DEVNULL, check=False).returncode == 0


def watch_browser():
    """The keyboard must not stay on screen when DWC is closed (nothing is left to hide it): hide it once each time the browser is gone."""
    hidden = False
    while True:
        if browser_running():
            hidden = False
        elif not hidden:
            set_visible(False)
            hidden = True
        time.sleep(WATCH_S)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/osk/show", "/osk/hide"):
            set_visible(self.path == "/osk/show")
            code = 204
        else:
            code = 404
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=watch_browser, daemon=True).start()
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
