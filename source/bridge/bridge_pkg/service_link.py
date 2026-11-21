"""The calls to WorkshopService about the live job (job.start / job.end ...), in the background."""


import json
import queue
import threading
import time


# live job end reason -> operation of the WorkshopService API
JOB_END_OPS = {"end": "job.end", "cancel": "job.cancel", "close": "job.close", "disconnect": "job.close", "order_failed": "job.cancel", "focus_failed": "job.cancel", "stopped": "job.close"}


class ServiceNotifier:
    """Tells WorkshopService about the live job through its API, in the
    background (a slow or stopped service never delays a line of the job).
    Retries a few times; a failure is only logged (the service also closes an
    idle live job by itself)."""

    URL = "http://127.0.0.1/machine/WorkshopService/api"

    def __init__(self, paths, threads=True, log=None):
        self.paths = paths
        self.log = log or (lambda *_a: None)
        self.q = queue.Queue(maxsize=50)
        if threads:
            threading.Thread(target=self._loop, name="service-api", daemon=True).start()

    def __call__(self, op, args):
        try:
            self.q.put_nowait((op, dict(args or {})))
        except queue.Full:
            self.log(f"service API queue full: {op} dropped")

    def _token(self):
        try:
            with open(self.paths.api_token, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def post(self, op, args, timeout=5):
        import urllib.error
        import urllib.request
        body = json.dumps({"op": op, "args": args, "origin": "bridge"}).encode()
        h = {"Content-Type": "application/json"}
        tok = self._token()
        if tok:
            h["X-Workshop-Token"] = tok
        req = urllib.request.Request(self.URL, data=body, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                return {"ok": False, "error": {"code": "http", "message": f"HTTP {e.code}"}}

    def _loop(self):
        while True:
            op, args = self.q.get()
            for attempt in range(4):
                try:
                    j = self.post(op, args)
                    if j.get("ok") or (j.get("error") or {}).get("code") not in ("busy", "http"):
                        if not j.get("ok"):
                            self.log(f"service API {op}: {(j.get('error') or {}).get('message')}")
                        break
                except Exception as e:  # service restarting / stopped
                    if attempt == 3:
                        self.log(f"service API {op} not delivered: {e}")
                time.sleep(2 + attempt * 3)
