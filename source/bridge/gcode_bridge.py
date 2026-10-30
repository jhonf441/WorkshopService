#!/usr/bin/env python3
"""
G-code bridge for the workshop (formerly "puente.py" / "duet-bridge").

Listens for TCP connections (Telnet style, configurable port, 23 by default)
and sends every received line to the Duet as G-code through DSF. The reply is
followed by "ok", which is what external cutting programs, terminals, scripts
and ESP32 boards expect. Several connections at once; with "exclusive" on, only
one of them (the owner) may send orders. Queries (M114, M105...) always pass.
Own commands: BRIDGE HELP. Telnet: a real Telnet client works (options are refused politely, NUL and IAC bytes never reach the G-code).
Live jobs (2026-10-13): the start / end G-code of the sending program carries
BRIDGE JOB START <name> / BRIDGE JOB END (or CANCEL); the bridge answers them
itself (they never reach the board) and tells WorkshopService through its API
(job.start / job.end, POST /machine/WorkshopService/api with the local key of
/opt/dsf/conf/workshop-api-token).

Line handling (3.0):
  - Every line becomes a "slot" in a per-client queue. Replies are written in
    the order the lines arrived, except that a query or a local answer may
    overtake an order that has been waiting for more than `overtake_ms`
    (so a console keeps answering while a long move blocks the machine).
  - Orders go to a per-client worker with its own DSF connection (timeout
    `order_timeout_s`); they never share a queue with queries.
  - Queries go to a small shared pool of DSF connections (timeout
    `query_timeout_s`). Identical queries from all clients are coalesced into one
    Duet request and answered from a short cache (`query_cache_ms`); when the
    machine is slow a recent cached answer is served instead of waiting.
  - Activity of the clients (last order time, pending orders, live job) is
    published in bridge-state.json ("activity") for the movement safety logic
    of the service.

Security. Telnet encrypts nothing and some programs cannot send a user or
password, so protection comes in layers:
  - Allowed IPs only: by default just the local network (10.x, 172.16-31.x,
    192.168.x, 127.x).
  - Optional password for ORDERS: without "BRIDGE KEY <password>" a connection
    can only query. "Trusted" IPs do not need it.
  - Wrong passwords block the IP for a while; maximum connections and line
    length; kick / block / hand over control from the Services page.

Files (0:/sys/workshop/..., /opt/dsf/sd/sys/workshop/... on the Pi):
  config/bridge.json        settings, reloaded when the file changes
  data/bridge-state.json    state/health, written every ~2 s (Services page, jog)
  data/bridge-action.json   actions from the page ({seq, action, ...})
  data/bridge-viewer.json   heartbeat of the page's Debug view (its mtime counts)

Debug mode keeps the last lines in memory (ring buffer) and publishes them in
the state file while it is on. It is NOT written to the journal and it turns
itself off after `debug_timeout_min` minutes unless the page keeps viewing it.
"""
import codecs
import collections
import hashlib
import ipaddress
import json
import logging
import os
import queue
import re
import secrets
import socket
import sys
import threading
import time

try:  # safe stop / resume of live jobs (2026-10-22): two files next to this one; without them the bridge works as before
    import live_stop
except ImportError:  # pragma: no cover - an old install that did not copy the new files
    live_stop = None

VERSION = "3.8.0"
SCHEMA = 2
HOST = "0.0.0.0"
SD_DIR = os.environ.get("BRIDGE_SD_DIR", "/opt/dsf/sd")

LOG = logging.getLogger("gcode-bridge")

QUERIES_DEFAULT = ["M114", "M115", "M105", "M119", "M122", "M408", "M503", "M27", "M20", "M36"]
# How long (ms) a Duet answer to each query stays valid for every client.
CACHE_MS_DEFAULT = {
    "M114": 500, "M408": 500, "M105": 1000, "M119": 1000, "M27": 1000,
    "M36": 2000, "M20": 5000, "M122": 5000, "M503": 30000, "M115": 60000,
}
CONFIG_DEFAULT = {
    "port": int(os.environ.get("BRIDGE_PORT", "23")),
    "exclusive": os.environ.get("BRIDGE_EXCLUSIVE", "1") == "1",
    "queries": QUERIES_DEFAULT,
    "names": {},                  # {"<ip>": "Cutter-PC"}
    "extended_greeting": False,   # True: after "Connected!" explain the name and the help
    "debug": os.environ.get("BRIDGE_DEBUG", "0") == "1",
    "debug_timeout_min": 30,      # debug turns itself off after this long without a viewer
    "debug_renew": True,          # True: while the page shows the debug panel the countdown starts again; False: fixed from turning it on (Extend adds time)
    # --- security ---
    "allowed": [],                # IPs or networks ("192.168.77.0/24"); empty = local network only
    "trusted": [],                # IPs that send orders without a password
    "password_hash": "",          # "scrypt$<hex>" (older bridges: sha256(salt + password), still accepted); empty = no password
    "password_salt": "",
    "max_connections": 8,
    "password_attempts": 5,       # wrong passwords before the IP is blocked
    "block_seconds": 300,
    "blocked": [],                # IPs blocked from the page until unblocked
    # --- line handling (3.0) ---
    "order_timeout_s": 120,       # max wait for the Duet on an order: a slow cut keeps the board queue full and a line can wait for a long time (15 s gave false errors)
    "query_timeout_s": 3,         # max wait for the Duet on a query
    "skip_material_macro": False, # True: the M98 that calls a material macro (macros/laser, laserfocus.g, livemark.g) is answered ok and NOT run (the program's start G-code carries it)
    "block_when_unfit": True,     # refuse movement / laser orders while the machine is paused, halted by an error, cancelling...
    "queries_in_job": True,       # False: while a live job runs the queries are answered from the last known answer, the board is not asked
    "query_channel": "Telnet",    # code channel of the queries: not the one of the orders, so a query never waits behind a slow cut ("" = same channel)
    "query_cache_ms": dict(CACHE_MS_DEFAULT),
    "query_soft_ms": 500,         # after this wait a recent cached answer is served instead
    "query_stale_s": 5,           # oldest cached answer that may be served when the Duet is slow
    "overtake_ms": 500,           # a query may overtake an order waiting longer than this
    "query_workers": 2,           # DSF connections reserved for queries
}

MAX_LINE = 1024
# G0/G1 without parameters is an automatic "ping" of some programs: answered ok locally.
NOOP_WITHOUT_PARAMS = {"G0", "G1"}
# The M98 lines a program carries to prepare the material (focus, origin, live-job mark): the zone macros in macros/laser and the two helpers they call.
MATERIAL_MACRO_RE = re.compile(r'^\s*M98\s+P\s*"?(?:[^"\s]*/macros/laser/|[^"\s]*/(?:laserfocus|livemark)\.g)', re.IGNORECASE)
# Codes that mean "the machine may be moving or about to move".
MOTION_CODES = {"G0", "G1", "G2", "G3", "G5", "G28", "G29", "G30", "G32", "G38",
                "M3", "M4", "M5", "M24", "M32", "M98"}
# Orders that move the machine or turn the laser on: refused while the machine cannot take them (paused, halted by an error,
# cancelling...). Stops (M5, M0, M25, M112, M999) and queries always pass.
GATED_CODES = {"G0", "G1", "G2", "G3", "G5", "G28", "G29", "G30", "G32", "G38", "M3", "M4"}
UNFIT_STATES = {"paused": "paused", "pausing": "pausing", "resuming": "resuming", "cancelling": "cancelling a job",
                "halted": "halted by an error (M999 is needed)", "off": "off", "updating": "updating the firmware"}
# A stop of the program ends the live job at once (nobody else would tell the service it is over): M0 (stop) and M112
# (emergency stop). The machine halting or switching off does the same (see MachineGate.refresh).
STOP_ENDS_JOB = {"M0", "M112"}
# Only the homing itself passes while some axis is not homed (a job sent before the homing would otherwise run, from the middle, as soon as it ends).
NEEDS_HOMING_OK = {"G28"}
# After the bridge refuses an order of a job, the rest of that job is refused too for this long (it is renewed by every refused order): the program keeps
# streaming and the lines that come after the refused ones (the material macro was one of them) must not run on their own. A new BRIDGE JOB START clears it.
TAINT_S = 30.0
# A macro or a probing order that FAILS ("Error: ..." in its reply: the Z probe did not trigger, the BLTouch pin (M280) gave an alarm, a macro called abort, ...)
# stops the rest of the job: the program keeps streaming (its start macro was one of the failed lines) and what follows would run without the focus,
# the origin or the probe that macro was supposed to set. The orders that fail are the ones in FAIL_WATCH; from then on every order is refused
# except the stops (STOPS_PASS) for FAIL_REFUSE_S seconds, or until BRIDGE JOB START / BRIDGE RESUME.
FAIL_WATCH = {"M98", "G30", "M280", "M401", "M402"}
STOPS_PASS = {"M5", "M0", "M25", "M112", "M999"}
FAIL_REFUSE_S = 120.0
STATE_PERIOD_S = 2.0
STATE_PERIOD_DEBUG_S = 1.0
VIEWER_GRACE_S = 120      # debug lines stay in the state this long after the last viewer heartbeat
DEBUG_RING_LINES = 300
DEBUG_TEXT_MAX = 200


class Clock:
    """Wall and monotonic time in one place so the tests can drive them."""

    def wall(self):
        return time.time()

    def mono(self):
        return time.monotonic()


class Paths:
    """Every file the bridge reads or writes, under one SD directory."""

    def __init__(self, sd_dir=None):
        root = sd_dir or SD_DIR
        sysdir = os.path.join(root, "sys")
        self.config = os.path.join(sysdir, "workshop", "config", "bridge.json")
        self.state = os.path.join(sysdir, "workshop", "data", "bridge-state.json")
        self.action = os.path.join(sysdir, "workshop", "data", "bridge-action.json")
        self.viewer = os.path.join(sysdir, "workshop", "data", "bridge-viewer.json")
        # the local key of the service lives outside the SD (DWC serves the SD); the old SD file is read only until the service has moved it
        self.api_token = os.path.join(os.path.dirname(os.path.abspath(root)), "conf", "workshop-api-token")
        self.api_token_legacy = os.path.join(sysdir, "workshop", "data", ".api-token")
        self.interrupted = os.path.join(sysdir, "workshop", "data", "live-interrupted.json")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def write_json_atomic(path, data, mode=0o664, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def str_list(v):
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def mask(line):
    """The line as it may be shown or logged (passwords hidden, shortened)."""
    parts = line.split(None, 2)
    # the old Spanish spelling is not a command any more, but a password typed with it must still never be shown or logged
    if len(parts) >= 2 and parts[0].upper() in ("BRIDGE", "PUENTE") and parts[1].upper() in ("KEY", "CLAVE"):
        return f"{parts[0]} {parts[1]} ***"
    return line[:80]


def first_token(line):
    parts = line.split()
    return parts[0].upper() if parts else ""


def query_key(line):
    """Cache key: whitespace collapsed, only the code upper-cased (parameters
    such as file paths are case sensitive)."""
    parts = line.split()
    if not parts:
        return ""
    return " ".join([parts[0].upper()] + parts[1:])


def format_response(text):
    text = (text or "").strip()
    body = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n") if text else ""
    return body + "ok\r\n"


M118_JOB_RE = re.compile(r'^M118\s+(?:.*?\s)?S\s*"\s*(BRIDGE\s+JOB(?:\s[^"]*)?)"', re.IGNORECASE)


def m118_job_line(line):
    """`M118 P0 S"BRIDGE JOB START name"` -> `BRIDGE JOB START name`, else None.
    A real G-code that carries the job mark: the Duet understands it inside an uploaded
    file (it only prints the message) while the bridge answers it itself when it streams."""
    m = M118_JOB_RE.match(line.strip())
    return m.group(1).strip() if m else None


def parse_job_command(arg):
    """Argument of BRIDGE JOB ... -> (action, detail) or None.
    action is "start" (detail = job name or None) or "end" (detail = end/cancel/close).
    START [name] | END | CANCEL | CLOSE."""
    parts = str(arg or "").strip().split(None, 1)
    if not parts:
        return None
    verb = parts[0].upper()
    rest = parts[1].strip().strip('"').strip() if len(parts) > 1 else ""
    if verb == "START":
        return "start", (rest[:80] or None)
    if verb == "END":
        return "end", "end"
    if verb == "CANCEL":
        return "end", "cancel"
    if verb == "CLOSE":
        return "end", "close"
    return None


# live job end reason -> operation of the WorkshopService API
JOB_END_OPS = {"end": "job.end", "cancel": "job.cancel", "close": "job.close", "disconnect": "job.close", "order_failed": "job.cancel", "stopped": "job.close"}


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
        for path in (self.paths.api_token, self.paths.api_token_legacy):
            try:
                with open(path, encoding="utf-8") as f:
                    t = f.read().strip()
                if t:
                    return t
            except OSError:
                continue
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


class MachineGate:
    """Knows if the machine is in a state that cannot take a live job, asking the service (motion.state) every 2 s while
    somebody is connected. Unknown state (service stopped, no answer yet) lets everything pass: the gate never blocks by
    guessing."""

    def __init__(self, bridge, notifier, threads=True):
        self.bridge = bridge
        self.notifier = notifier
        self.status = None
        self.needs_homing = False
        self.at = 0.0
        if threads:
            threading.Thread(target=self._loop, name="machine-gate", daemon=True).start()

    def _loop(self):
        while True:
            time.sleep(2.0)
            try:
                if self.bridge.clients and self.bridge.settings.get("block_when_unfit"):
                    self.refresh()
            except Exception:
                self.status = None

    def refresh(self):
        j = self.notifier.post("motion.state", {}, timeout=3)
        res = (j or {}).get("result") or {}
        self.status = res.get("status") if (j or {}).get("ok") else None
        self.needs_homing = bool(res.get("needs_homing")) if (j or {}).get("ok") else False
        self.at = time.monotonic()
        # halted (emergency stop, error) or off: the live job cannot go on; free what it holds
        if self.status in ("halted", "off") and self.bridge.live_job.get("active"):
            self.bridge._end_live_job("cancel")

    def reason(self, tok=None):
        """Why orders are refused now (text) or None. tok: the code of the order (the homing passes while the axes are not homed)."""
        if not self.bridge.settings.get("block_when_unfit"):
            return None
        if self.status is None or time.monotonic() - self.at > 10:
            return None
        why = UNFIT_STATES.get(self.status)
        if why:
            return why
        if self.needs_homing and tok not in NEEDS_HOMING_OK:
            return "not homed yet (home all the axes first)"
        return None


def clean_config(raw):
    """Merge a (possibly partial) settings dict over the defaults and
    validate every value; invalid values fall back to the default."""
    base = dict(CONFIG_DEFAULT)
    base.update({k: v for k, v in raw.items() if k in CONFIG_DEFAULT})
    try:
        base["port"] = max(1, min(65535, int(base["port"])))
    except (TypeError, ValueError):
        base["port"] = CONFIG_DEFAULT["port"]
    base["exclusive"] = bool(base["exclusive"])
    base["extended_greeting"] = bool(base["extended_greeting"])
    base["debug"] = bool(base["debug"])
    base["debug_renew"] = bool(base.get("debug_renew", True))
    base["queries_in_job"] = bool(base.get("queries_in_job", True))
    base["block_when_unfit"] = bool(base.get("block_when_unfit", True))
    base["skip_material_macro"] = bool(base.get("skip_material_macro", False))
    base["queries"] = [str(c).upper() for c in (base.get("queries") or QUERIES_DEFAULT)]
    base["names"] = {str(k): str(v) for k, v in (base.get("names") or {}).items()}
    for k in ("allowed", "trusted", "blocked"):
        base[k] = str_list(base.get(k))
    base["password_hash"] = str(base.get("password_hash") or "")
    base["password_salt"] = str(base.get("password_salt") or "")
    for k in ("max_connections", "password_attempts", "block_seconds", "query_workers", "debug_timeout_min"):
        try:
            base[k] = max(1, int(base[k]))
        except (TypeError, ValueError):
            base[k] = CONFIG_DEFAULT[k]
    base["query_workers"] = min(base["query_workers"], 8)
    for k, lo, hi in (("order_timeout_s", 1.0, 300.0), ("query_timeout_s", 0.5, 30.0), ("query_stale_s", 0.0, 120.0)):
        try:
            base[k] = max(lo, min(hi, float(base[k])))
        except (TypeError, ValueError):
            base[k] = CONFIG_DEFAULT[k]
    base["query_channel"] = "".join(ch for ch in str(base.get("query_channel") or "") if ch.isalnum())[:16]
    for k in ("query_soft_ms", "overtake_ms"):
        try:
            base[k] = max(0, int(base[k]))
        except (TypeError, ValueError):
            base[k] = CONFIG_DEFAULT[k]
    cache = dict(CACHE_MS_DEFAULT)
    given = base.get("query_cache_ms")
    if isinstance(given, dict):
        for code, ms in given.items():
            try:
                cache[str(code).upper()] = max(0, int(ms))
            except (TypeError, ValueError):
                pass
    base["query_cache_ms"] = cache
    return base


def ensure_action_file(paths, log=print):
    """The page saves its actions to this file: it must exist from the start. Returns what was done."""
    done = []
    if not os.path.exists(paths.action):
        try:
            write_json_atomic(paths.action, {"seq": None})
            done.append(f"created {paths.action}")
        except OSError as e:
            log(f"Could not create {paths.action}: {e}")
    return done


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings:
    def __init__(self, paths, log=print):
        self.paths = paths
        self.log = log
        self.lock = threading.Lock()
        self.values = clean_config({})
        self.mtime = None

    def get(self, key):
        with self.lock:
            return self.values.get(key)

    def snapshot(self):
        with self.lock:
            return dict(self.values)

    def load(self):
        """Reload when the file changed. Returns True if new values were applied."""
        path = self.paths.config
        try:
            m = os.path.getmtime(path)
        except OSError:
            return False
        if m == self.mtime:
            return False
        try:
            raw = read_json(path)
        except (OSError, ValueError) as e:
            self.log(f"Invalid settings in {path} ({e}): keeping the previous values")
            self.mtime = m
            return False
        with self.lock:
            self.values = clean_config(raw)
        self.mtime = m
        return True

    def modify(self, fn):
        """Read the settings file, apply fn(dict) and save it (atomic). Used by
        the page actions (rename, trust, password) and debug auto-off."""
        try:
            d = read_json(self.paths.config)
        except (OSError, ValueError):
            d = {}
        fn(d)
        write_json_atomic(self.paths.config, d, indent=2)
        self.mtime = None
        self.load()


# ---------------------------------------------------------------------------
# Debug ring buffer (memory only)
# ---------------------------------------------------------------------------

class DebugRing:
    def __init__(self, clock, maxlen=DEBUG_RING_LINES):
        self.clock = clock
        self.lock = threading.Lock()
        self.lines = collections.deque(maxlen=maxlen)
        self.next_id = 1
        self.active = False

    def add(self, client, kind, text):
        if not self.active:
            return
        text = str(text)
        if len(text) > DEBUG_TEXT_MAX:
            text = text[:DEBUG_TEXT_MAX] + "..."
        wall = self.clock.wall()
        stamp = time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int((wall % 1) * 1000):03d}"
        with self.lock:
            self.lines.append({"id": self.next_id, "t": stamp, "c": client, "k": kind, "x": text})
            self.next_id += 1

    def clear(self):
        with self.lock:
            self.lines.clear()

    def snapshot(self):
        with self.lock:
            return list(self.lines)

    @property
    def last_id(self):
        with self.lock:
            return self.next_id - 1


class Timing:
    """Exponential average and 5 minute maximum of the Duet answer time."""

    def __init__(self, clock):
        self.clock = clock
        self.avg_ms = None
        self.max_ms = 0.0
        self.window = clock.mono()

    def add(self, ms):
        now = self.clock.mono()
        self.avg_ms = ms if self.avg_ms is None else 0.9 * self.avg_ms + 0.1 * ms
        if now - self.window > 300:
            self.window = now
            self.max_ms = ms
        elif ms > self.max_ms:
            self.max_ms = ms


# ---------------------------------------------------------------------------
# Duet connections
# ---------------------------------------------------------------------------

def real_link_factory(timeout):
    """A DSF command connection (the dsf-python library, installed on the Pi)."""
    from dsf.connections import CommandConnection
    return CommandConnection(timeout=timeout)


class DuetLink:
    """A lazily opened DSF connection that reconnects after a failure.

    timeout and connect_wait may be numbers or callables (so a settings change
    applies to the next connection). With connect_wait > 0 an order keeps
    retrying the connection for that many seconds before giving up; with 0 a
    query fails at once and the connection is retried after RETRY_AFTER_S."""

    RETRY_AFTER_S = 2.0

    def __init__(self, factory, timeout, clock, connect_wait=0, sleep=time.sleep, channel=None):
        self.factory = factory
        self.channel = channel          # name (or callable) of a DSF code channel; None = the default one
        self.timeout = timeout
        self.connect_wait = connect_wait
        self.clock = clock
        self.sleep = sleep
        self.conn = None
        self.failed_at = None

    @staticmethod
    def _val(v):
        return v() if callable(v) else v

    def _connect(self):
        wait = self._val(self.connect_wait)
        deadline = self.clock.mono() + wait
        while True:
            failed = self.failed_at
            if wait <= 0 and failed is not None and self.clock.mono() - failed < self.RETRY_AFTER_S:
                raise ConnectionError("machine connection is down (retrying shortly)")
            try:
                conn = self.factory(self._val(self.timeout))
                conn.connect()
                self.conn = conn
                self.failed_at = None
                return
            except Exception as e:
                self.failed_at = self.clock.mono()
                if self.clock.mono() >= deadline:
                    raise ConnectionError(f"cannot connect to DSF: {e}")
                self.sleep(min(1.0, max(0.0, deadline - self.clock.mono())))

    def _code_channel(self):
        """The CodeChannel of dsf-python for `channel`, or None (default channel) if it is unset, unknown or the
        library is not there (tests)."""
        name = self._val(self.channel) if self.channel is not None else None
        if not name:
            return None
        try:
            from dsf.commands.code_channel import CodeChannel
            return getattr(CodeChannel, name, None)
        except Exception:
            return None

    def execute(self, line):
        if self.conn is None:
            self._connect()
        try:
            ch = self._code_channel()
            if ch is not None:
                return self.conn.perform_simple_code(line, channel=ch)
            return self.conn.perform_simple_code(line)
        except Exception:
            self.close()
            raise

    def close(self):
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Query service: coalescing, cache, stale answers
# ---------------------------------------------------------------------------

class _Waiter:
    __slots__ = ("callback", "t0", "client", "answered")

    def __init__(self, callback, t0, client):
        self.callback = callback
        self.t0 = t0
        self.client = client
        self.answered = False


class _Job:
    __slots__ = ("key", "line", "waiters")

    def __init__(self, key, line):
        self.key = key
        self.line = line
        self.waiters = []


class QueryService:
    """Answers queries for every client.

    request(line, callback) -> source, where source is "cache" (answered now
    from the cache), "coalesced" (joined a request already on its way) or
    "duet" (a new Duet request). callback(text, source) is called exactly once
    with source "cache", "duet", "stale" (a recent cached answer served because
    the Duet was slow or failed) or "error".
    """

    CACHE_MAX = 64

    def __init__(self, bridge):
        self.bridge = bridge
        self.lock = threading.Lock()
        self.cache = {}          # key -> (mono time, text)
        self.inflight = {}       # key -> _Job
        self.jobs = queue.Queue()
        self.threads = []
        self.stopping = False

    # -- client side --
    def request(self, line, callback, client=None):
        b = self.bridge
        key = query_key(line)
        now = b.clock.mono()
        if not b.settings.get("queries_in_job") and b.live_job.get("active"):
            # the user does not want the board asked while the job runs: the last known answer, or a plain ok
            with self.lock:
                entry = self.cache.get(key)
            b.dbg(getattr(client, "name", "-"), "cache", f"{key} answered without asking the board (live job, queries off)")
            self._call(callback, entry[1] if entry is not None else "ok", "cache")
            return "cache"
        ttl = (b.settings.get("query_cache_ms").get(first_token(line), 0)) / 1000.0
        hit = None
        source = "duet"
        with self.lock:
            entry = self.cache.get(key)
            if entry is not None and ttl > 0 and now - entry[0] <= ttl:
                hit = entry
                source = "cache"
            else:
                waiter = _Waiter(callback, now, client)
                job = self.inflight.get(key)
                if job is not None:
                    job.waiters.append(waiter)
                    source = "coalesced"
                else:
                    job = _Job(key, line)
                    job.waiters.append(waiter)
                    self.inflight[key] = job
                    self.jobs.put(job)
        if hit is not None:
            b.dbg(getattr(client, "name", "-"), "cache", f"{key} answered from cache ({int((now - hit[0]) * 1000)} ms old)")
            self._call(callback, hit[1], "cache")
        elif source == "coalesced":
            b.dbg(getattr(client, "name", "-"), "coalesce", f"{key} joined the request already on its way")
        return source

    @staticmethod
    def _call(callback, text, source):
        try:
            callback(text, source)
        except Exception as e:
            LOG.warning("query callback failed: %s", e)

    def _stale(self, key, now):
        """A cached answer young enough to be served when the Duet is slow."""
        limit = self.bridge.settings.get("query_stale_s")
        entry = self.cache.get(key)
        if entry is not None and now - entry[0] <= limit:
            return entry
        return None

    # -- worker side --
    def start(self):
        n = self.bridge.settings.get("query_workers")
        for i in range(n):
            t = threading.Thread(target=self._worker, name=f"query-{i}", daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stopping = True
        for _ in self.threads:
            self.jobs.put(None)

    def _worker(self):
        b = self.bridge
        link = DuetLink(b.link_factory, lambda: b.settings.get("query_timeout_s"), b.clock,
                        channel=lambda: b.settings.get("query_channel"))
        while not self.stopping:
            job = self.jobs.get()
            if job is None:
                break
            self.run_job(job, link)
        link.close()

    def run_next(self, link, block=False):
        """Run one queued job synchronously (tests). Returns False if none."""
        try:
            job = self.jobs.get(block, 1.0 if block else None)
        except queue.Empty:
            return False
        if job is None:
            return False
        self.run_job(job, link)
        return True

    def run_job(self, job, link):
        b = self.bridge
        t0 = b.clock.mono()
        text, error = None, None
        try:
            text = (link.execute(job.line) or "").strip()
        except Exception as e:
            error = e
        ms = (b.clock.mono() - t0) * 1000
        now = b.clock.mono()
        with self.lock:
            self.inflight.pop(job.key, None)
            waiters = [w for w in job.waiters if not w.answered]
            for w in waiters:
                w.answered = True
            if error is None:
                self.cache[job.key] = (now, text)
                if len(self.cache) > self.CACHE_MAX:
                    oldest = min(self.cache, key=lambda k: self.cache[k][0])
                    self.cache.pop(oldest, None)
            stale = self._stale(job.key, now) if error is not None else None
        with b.lock:
            b.totals["duet_queries"] += 1
            if error is not None:
                b.totals["query_errors"] += 1
        if error is None:
            b.timing["query"].add(ms)
            b.timing["all"].add(ms)
            b.dbg("-", "duet", f"{job.key} answered by the Duet in {int(ms)} ms ({len(waiters)} waiting)")
            for w in waiters:
                self._call(w.callback, text, "duet")
        else:
            b.dbg("-", "error", f"{job.key} failed after {int(ms)} ms: {error}")
            b.event("error", "duet_error", f"Machine error on query '{job.line[:40]}': {error}", line=job.line[:40], error=str(error))
            for w in waiters:
                if stale is not None:
                    self._call(w.callback, stale[1], "stale")
                else:
                    self._call(w.callback, f"Error: {error}", "error")

    def expire(self):
        """Answer waiters that waited too long: a recent cached answer after
        `query_soft_ms`, an error (or the cached answer) after the query timeout."""
        b = self.bridge
        soft = b.settings.get("query_soft_ms") / 1000.0
        hard = b.settings.get("query_timeout_s") + 0.5
        now = b.clock.mono()
        due = []
        with self.lock:
            for key, job in self.inflight.items():
                stale = self._stale(key, now)
                for w in job.waiters:
                    if w.answered:
                        continue
                    waited = now - w.t0
                    if stale is not None and waited >= soft:
                        w.answered = True
                        due.append((w, stale[1], "stale"))
                    elif waited >= hard:
                        w.answered = True
                        due.append((w, "Error: the machine did not answer the query in time", "error"))
        for w, text, source in due:
            b.dbg(getattr(w.client, "name", "-"), "stale" if source == "stale" else "error",
                  f"query answered with {source} data after {int((now - w.t0) * 1000)} ms")
            self._call(w.callback, text, source)


# ---------------------------------------------------------------------------
# Orders: one worker (and one DSF connection) per client
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Client connection
# ---------------------------------------------------------------------------

class Slot:
    """One received line waiting for its reply."""
    __slots__ = ("kind", "line", "t0", "done", "out", "source")

    def __init__(self, kind, line, t0):
        self.kind = kind          # "local", "query" or "order"
        self.line = line
        self.t0 = t0
        self.done = False
        self.out = ""
        self.source = None


class TelnetFilter:
    """The Telnet layer of the connection (RFC 854 / 855 / 1143), kept minimal: the bridge never starts a negotiation, so a plain TCP program
    (cutting software, a script, an ESP32) sees nothing new; a real Telnet client (PuTTY, telnet, nc -t) sends its option requests and the
    bytes of them used to land inside the first line, in front of the first G-code.
      - IAC IAC is the literal byte 255; IAC <command> and IAC SB ... IAC SE are removed from the data;
      - every option is refused: DO x -> IAC WONT x, WILL x -> IAC DONT x (each answer once per option, so two refusing ends never loop);
      - NUL bytes are removed (the NVT sends CR NUL for a bare Enter) and CR LF / CR / LF all end a line."""

    IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

    def __init__(self):
        self.state = "data"      # data | iac | opt | sb | sb_iac
        self.verb = 0
        self.refused = set()

    def feed(self, data):
        """bytes from the socket -> (bytes for the application, bytes to answer on the socket)"""
        out, reply = bytearray(), bytearray()
        for b in data:
            st = self.state
            if st == "data":
                if b == self.IAC:
                    self.state = "iac"
                elif b != 0:
                    out.append(b)
            elif st == "iac":
                if b == self.IAC:
                    out.append(b)
                    self.state = "data"
                elif b in (self.WILL, self.WONT, self.DO, self.DONT):
                    self.verb = b
                    self.state = "opt"
                elif b == self.SB:
                    self.state = "sb"
                else:
                    self.state = "data"   # NOP, AYT, IP, BRK, GA...: nothing to do
            elif st == "opt":
                key = (self.verb, b)
                if self.verb in (self.WILL, self.DO) and key not in self.refused:
                    self.refused.add(key)
                    reply += bytes((self.IAC, self.DONT if self.verb == self.WILL else self.WONT, b))
                self.state = "data"
            elif st == "sb":
                if b == self.IAC:
                    self.state = "sb_iac"
            else:   # sb_iac
                self.state = "data" if b == self.SE else ("sb" if b == self.IAC else "sb")
        return bytes(out), bytes(reply)


class Client:
    def __init__(self, bridge, sock, addr, number):
        self.bridge = bridge
        self.sock = sock
        self.addr = addr
        self.ip = addr[0]
        self.id = f"{addr[0]}:{addr[1]}"
        clock = bridge.clock
        self.name = bridge.settings.get("names").get(addr[0]) or bridge.auto_name(addr[0])
        self.since = clock.wall()
        self.last_rx = clock.wall()
        self.lines = self.orders = self.queries = self.rejects = 0
        self.cache_hits = self.coalesced = self.stale_served = self.overtaken = 0
        self.bytes_rx = self.bytes_tx = 0
        self.authenticated = False
        self.last = None
        self.last_at = None
        self.last_order = None
        self.last_order_at = None        # wall time of the last non-query line (received or finished)
        self.last_motion_at = None
        self.pending = 0                 # orders accepted and not finished
        self.closed = False
        self.taint_until = 0.0           # mono time until which the orders of this job are refused (see TAINT_S)
        self.failed_until = 0.0          # mono time until which every order but the stops is refused (a macro or probing order failed, see FAIL_WATCH)
        self.failed_why = ""
        self.stopped_until = 0.0         # mono time until which the rest of a job stopped safely is refused (see live_stop.py)
        self.stopped_note = None
        self.cut_after_flush = False
        self.slots = collections.deque()
        self.slot_lock = threading.RLock()
        self.order_worker = OrderWorker(bridge, self)

    # -- output --
    def new_slot(self, kind, line):
        slot = Slot(kind, line, self.bridge.clock.mono())
        with self.slot_lock:
            self.slots.append(slot)
        return slot

    def finish(self, slot, text, source=None):
        """Complete a slot with the machine's (or the bridge's) answer."""
        with self.slot_lock:
            slot.out = format_response(text)
            slot.source = source
            slot.done = True
        self.flush()

    def flush(self):
        """Write finished slots in arrival order; a finished query or local
        answer may overtake orders that have waited more than `overtake_ms`."""
        b = self.bridge
        overtake_s = b.settings.get("overtake_ms") / 1000.0
        with self.slot_lock:
            if not self.slots:
                return
            now = b.clock.mono()
            pending_ahead = False
            may_overtake = True
            keep = collections.deque()
            emit = []
            for slot in self.slots:
                if not slot.done:
                    pending_ahead = True
                    if not (slot.kind == "order" and now - slot.t0 >= overtake_s):
                        may_overtake = False
                    keep.append(slot)
                elif not pending_ahead:
                    emit.append((slot, False))
                elif slot.kind != "order" and may_overtake:
                    emit.append((slot, True))
                else:
                    keep.append(slot)
            self.slots = keep
            for slot, overtook in emit:
                if overtook:
                    self.overtaken += 1
                    with b.stat_lock:
                        b.totals["overtaken"] += 1
                shown = slot.out.strip().replace("\r", "").replace("\n", " | ")[:100]
                b.dbg(self.name, "tx", f"{shown} (+{int((now - slot.t0) * 1000)} ms{', overtook an order' if overtook else ''})")
                self._send(slot.out)
            if self.cut_after_flush and not self.slots:
                self.shutdown()

    def _send(self, text):
        if self.closed:
            return
        data = text if isinstance(text, bytes) else text.encode()
        try:
            self.sock.sendall(data)
        except OSError:
            self.shutdown()
            return
        with self.bridge.stat_lock:
            self.bridge.totals["bytes_tx"] += len(data)
            self.bytes_tx += len(data)

    def send_raw(self, text):
        with self.slot_lock:
            self._send(text)

    def shutdown(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

    # -- input --
    def run(self):
        b = self.bridge
        try:
            self.send_raw("Connected!\r\n")
            if b.settings.get("extended_greeting"):
                extra = " This bridge asks for a password to send orders: BRIDGE KEY <password>." if (b.needs_password() and not b.is_trusted(self.ip)) else ""
                self.send_raw(f"Workshop G-code bridge. You are '{self.name}'. Type BRIDGE HELP for the commands.{extra}\r\n")
            buf = ""
            telnet = TelnetFilter()
            text_in = codecs.getincrementaldecoder("utf-8")(errors="ignore")   # a character split between two reads is not lost
            while not self.closed:
                data = self.sock.recv(4096)
                if not data:
                    break
                with b.lock:
                    b.totals["bytes_rx"] += len(data)
                    self.bytes_rx += len(data)
                    self.last_rx = b.clock.wall()
                data, answer = telnet.feed(data)
                if answer:
                    self.send_raw(answer)
                buf += text_in.decode(data)
                pieces = buf.replace("\r", "\n").split("\n")
                buf = pieces.pop()
                for piece in pieces:
                    piece = piece.strip()
                    if piece:
                        self.handle_line(piece)
                if len(buf) > MAX_LINE * 4:
                    buf = ""
                    self.reply_local("Error: line too long (max %d)." % MAX_LINE)
        except (OSError, TimeoutError):
            pass
        except Exception as e:
            b.event("error", "unexpected_error", f"Unexpected error with '{self.name}': {e}", client=self.name, error=str(e))
        finally:
            b.unregister(self)

    def reply_local(self, text):
        slot = self.new_slot("local", "")
        self.finish(slot, text)

    def handle_line(self, line):
        """Classify one received line and queue its reply slot."""
        b = self.bridge
        if len(line) > MAX_LINE:
            self.reply_local("Error: line too long (max %d)." % MAX_LINE)
            return
        shown = mask(line)
        wall = b.clock.wall()
        with b.lock:
            b.totals["lines"] += 1
            self.lines += 1
            self.last = shown
            self.last_at = wall
        b.dbg(self.name, "rx", shown)
        tok = first_token(line)

        if tok == "M118":
            inner = m118_job_line(line)
            if inner:
                text, cut = b.bridge_command(inner, self)
                self.reply_local(text)
                return
        if tok == "BRIDGE":
            text, cut = b.bridge_command(line, self)
            if cut:
                self.cut_after_flush = True
            self.reply_local(text)
            return
        parts = line.split()
        if len(parts) == 1 and tok in NOOP_WITHOUT_PARAMS:
            self.reply_local("")
            return

        if tok == "M98" and b.settings.get("skip_material_macro") and MATERIAL_MACRO_RE.match(line):
            with b.lock:
                b.totals["skipped_material"] = b.totals.get("skipped_material", 0) + 1
                n = b.totals["skipped_material"]
            if n in (1, 10, 100):
                b.event("info", "material_macro_skipped", f"'{self.name}' sent a material macro ({shown}); the bridge skipped it (setting: skip the material G-code)", client=self.name)
            self.reply_local("")
            return

        is_query = tok in b.settings.get("queries")
        if not is_query and not b.can_order(self):
            with b.lock:
                b.totals["rejects"] += 1
                self.rejects += 1
                b.count("rejects")
                n = self.rejects
            if n in (1, 10, 100):
                b.event("security", "order_rejected_password", f"Order from '{self.name}' rejected: password missing", client=self.name)
            self.reply_local("Error: this bridge asks for a password to send orders. Type BRIDGE KEY <password> (or mark this IP as trusted in Services).")
            return
        if b.settings.get("exclusive") and not is_query:
            with b.lock:
                if b.owner is None or b.owner.id not in b.clients:
                    b.owner = self
                    b.owner_since = b.clock.wall()
                    b.event("control", "control_taken", f"'{self.name}' took control of the bridge", client=self.name)
                rejected = b.owner is not self
                owner_label = b.label(b.owner)
                if rejected:
                    b.totals["rejects"] += 1
                    self.rejects += 1
                    b.count("rejects")
                    n = self.rejects
            if rejected:
                if n in (1, 10, 100):
                    b.event("control", "order_rejected_control", f"Order from '{self.name}' rejected: control is held by '{owner_label}'", client=self.name, owner=owner_label)
                self.reply_local(f"Error: the bridge is in use by '{owner_label}'. Your order was not executed; wait for it to finish or type BRIDGE USE.")
                return

        if not is_query and b.live is not None and tok not in STOPS_PASS:
            held = b.live.on_order(self, line)
            if held is not None:
                kind, why = held
                if kind == "skip":
                    self.reply_local("")      # the part of the job that was already done: ok, nothing reaches the board
                else:
                    with b.lock:
                        b.totals["rejects"] += 1
                        self.rejects += 1
                        b.count("rejects")
                    self.reply_local("Error: " + why + ". Your order was not executed.")
                return

        if not is_query and tok not in STOPS_PASS and self.failed_until > b.clock.mono():
            left = int(self.failed_until - b.clock.mono()) + 1
            with b.lock:
                b.totals["rejects"] += 1
                self.rejects += 1
                b.count("rejects")
                n = self.rejects
            if n in (1, 10, 100):
                b.event("info", "order_rejected_failed_job", f"Order from '{self.name}' rejected: an earlier order of the job failed ({self.failed_why})", client=self.name)
            self.reply_local(f"Error: an earlier order of this job failed ({self.failed_why}); the rest is refused for {left} s so it does not run without what that order had to set up. Fix it and send the job again (or BRIDGE RESUME).")
            return

        if not is_query and tok in GATED_CODES:
            why = b.gate.reason(tok)
            now_m = b.clock.mono()
            if not why and tok not in NEEDS_HOMING_OK and self.taint_until > now_m:
                why = "refusing the rest of this job (an earlier order of it was refused)"
            if why and tok not in NEEDS_HOMING_OK:
                self.taint_until = now_m + TAINT_S
            if why:
                with b.lock:
                    b.totals["rejects"] += 1
                    self.rejects += 1
                    b.count("rejects")
                    n = self.rejects
                if n in (1, 10, 100):
                    b.event("info", "order_rejected_machine", f"Order from '{self.name}' rejected: the machine is {why}", client=self.name, state=why)
                self.reply_local(f"Error: the machine is {why}; the order was not executed. Fix it and send the job again.")
                return

        if is_query:
            with b.lock:
                b.totals["queries"] += 1
                self.queries += 1
                b.count("queries")
            slot = self.new_slot("query", line)

            def done(text, source, slot=slot):
                with b.lock:
                    if source == "cache":
                        self.cache_hits += 1
                        b.totals["cache_hits"] += 1
                    elif source == "stale":
                        self.stale_served += 1
                        b.totals["stale_served"] += 1
                self.finish(slot, text, source)

            source = b.queries.request(line, done, self)
            if source == "coalesced":
                with b.lock:
                    self.coalesced += 1
                    b.totals["coalesced"] += 1
            return

        with b.lock:
            b.totals["orders"] += 1
            self.orders += 1
            b.count("orders")
        if b.live is not None and tok not in STOPS_PASS:
            b.live.sent(self, line)
        slot = self.new_slot("order", line)
        b.note_order(self, line)
        self.order_worker.submit(line, slot)
        if tok in STOP_ENDS_JOB and b.live_job.get("active"):
            b._end_live_job("cancel")  # the program stopped the job: it is over, release what it was holding

    def info(self, now_wall):
        b = self.bridge
        return {
            "id": self.id, "name": self.name, "ip": self.ip, "port": self.addr[1],
            "connected_s": round(now_wall - self.since), "idle_s": round(now_wall - self.last_rx),
            "lines": self.lines, "orders": self.orders, "queries": self.queries, "rejects": self.rejects,
            "cache_hits": self.cache_hits, "coalesced": self.coalesced, "stale_served": self.stale_served,
            "overtaken": self.overtaken, "bytes_rx": self.bytes_rx, "bytes_tx": self.bytes_tx,
            "last": self.last, "last_age_s": round(now_wall - self.last_at) if self.last_at else None,
            "last_order": self.last_order, "last_order_at": self.last_order_at,
            "last_order_age_s": round(now_wall - self.last_order_at) if self.last_order_at else None,
            "last_motion_at": self.last_motion_at, "pending_orders": self.pending,
            "control": b.owner is self, "role": b.role(self), "trusted": b.is_trusted(self.ip),
            "name_saved": self.ip in b.settings.get("names"),
        }


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------

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


class Bridge:
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
        self.live_job = {"active": False, "name": None, "since": None, "client": None,
                         "last_event_at": None, "ended_at": None, "end_reason": None}
        self.queries = QueryService(self)
        self.live = live_stop.LiveStop(self) if live_stop is not None else None
        # live job notifications to WorkshopService (tests replace it with a list)
        self.service_notify = ServiceNotifier(self.paths, threads=threads, log=self._warn)
        self.gate = MachineGate(self, self.service_notify, threads=threads)
        self._last_state_write = 0.0
        self._last_config_check = 0.0
        self._state_warned = False
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
        """True when any private address of the LAN may send orders: no allow-list and no password."""
        return not self.settings.get("allowed") and not self.needs_password()

    def is_trusted(self, ip):
        return ip in self.settings.get("trusted")

    @staticmethod
    def hash_password(password, salt):
        """scrypt (the same parameters family as dsf/users.py), stored as "scrypt$<hex>"."""
        raw = hashlib.scrypt(password.encode(), salt=salt.encode(), n=2 ** 14, r=8, p=1, dklen=32)
        return "scrypt$" + raw.hex()

    @staticmethod
    def legacy_hash(password, salt):
        """The format of bridges before 2026-10-26: sha256(salt + password) in plain hex. Still accepted; set the password again to upgrade."""
        return hashlib.sha256((salt + password).encode()).hexdigest()

    def password_ok(self, password):
        h = self.settings.get("password_hash")
        if not h:
            return False
        salt = self.settings.get("password_salt") or ""
        if h.startswith("scrypt$"):
            return secrets.compare_digest(self.hash_password(password, salt), h)
        return secrets.compare_digest(self.legacy_hash(password, salt), h)

    def needs_password(self):
        return bool(self.settings.get("password_hash"))

    def can_order(self, client):
        return (not self.needs_password()) or client.authenticated or self.is_trusted(client.ip)

    def role(self, client):
        if client is self.owner:
            return "control"
        if self.needs_password() and not (client.authenticated or self.is_trusted(client.ip)):
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

    # -- activity --
    def note_order(self, client, line):
        """A non-query line was accepted for the Duet: record the activity."""
        wall = self.clock.wall()
        tok = first_token(line)
        with self.lock:
            client.last_order = mask(line)[:60]
            client.last_order_at = wall
            client.pending += 1
            self.pending_orders += 1
            self.last_order_wall = wall
            if tok in MOTION_CODES:
                client.last_motion_at = wall
                self.last_motion_wall = wall

    def order_finished(self, client, slot, text, dropped=False):
        wall = self.clock.wall()
        with self.lock:
            client.pending = max(0, client.pending - 1)
            self.pending_orders = max(0, self.pending_orders - 1)
            if not dropped:
                client.last_order_at = wall
                self.last_order_wall = wall
        if not dropped:
            self._check_failed_order(client, slot, text)
            client.finish(slot, text, "duet")

    def _check_failed_order(self, client, slot, text):
        """A macro call or a probing order answered with an error: the rest of the job must not run (see FAIL_WATCH)."""
        if first_token(slot.line) not in FAIL_WATCH:
            return
        err = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip().lower().startswith("error")), None)
        if not err:
            return
        client.failed_until = self.clock.mono() + FAIL_REFUSE_S
        client.failed_why = err[:120]
        self.event("error", "job_order_failed", f"'{client.name}': {mask(slot.line)[:60]} failed ({err[:120]}); the rest of the job is refused", client=client.name, error=err[:200])
        if self.live_job["active"] and self.live_job.get("client") == client.name:
            self._end_live_job("order_failed")

    def _start_live_job(self, client, name):
        client.taint_until = 0.0  # a new job: what an earlier one left refused no longer counts
        client.failed_until = 0.0
        self.live_job = {"active": True, "name": name or None, "since": self.clock.wall(), "client": client.name,
                         "last_event_at": self.clock.wall(), "ended_at": None, "end_reason": None}
        self.event("info", "live_job_started", f"Live job started by '{client.name}'" + (f" ({name})" if name else ""), client=client.name, name=name or "")
        if self.live is not None:
            self.live.on_job_start(client, name)
        self.service_notify("job.start", {"name": name} if name else {})

    def _end_live_job(self, reason):
        job = self.live_job
        if not job["active"]:
            return
        job["active"] = False
        job["ended_at"] = self.clock.wall()
        job["last_event_at"] = job["ended_at"]
        job["end_reason"] = reason
        self.event("info", "live_job_ended", f"Live job ended ({reason})", reason=reason)
        if self.live is not None:
            self.live.on_job_end(reason)
        self.service_notify(JOB_END_OPS.get(reason, "job.end"), {})

    # -- BRIDGE commands --
    def bridge_command(self, line, client):
        parts = line.split(None, 2)
        sub = SUBCOMMANDS.get(parts[1].upper() if len(parts) > 1 else "", None)
        arg = parts[2].strip() if len(parts) > 2 else ""
        with self.lock:
            self.totals["bridge_commands"] += 1
            if sub == "KEY":
                ip = client.ip
                if not self.needs_password():
                    return "This bridge does not ask for a password.", False
                if arg and self.password_ok(arg):
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

    # -- debug mode --
    @property
    def debug_active(self):
        return self.debug_ring.active

    def set_debug(self, on, persist=True):
        """Turn the in-memory debug on or off. While on it renews itself from the
        page's heartbeat (when debug_renew is on) and switches itself off after debug_timeout_min."""
        minutes = self.settings.get("debug_timeout_min")
        if on:
            if not self.debug_ring.active:
                self.debug_ring.clear()
            self.debug_ring.active = True
            self.debug_until = self.clock.mono() + minutes * 60
            self.event("info", "debug_on", f"Debug on (turns off by itself after {minutes} min without being viewed)", minutes=minutes)
        else:
            was = self.debug_ring.active
            self.debug_ring.active = False
            self.debug_until = None
            if was:
                self.event("info", "debug_off", "Debug off")
        if persist and self.settings.get("debug") != bool(on):
            try:
                self.settings.modify(lambda d: d.update(debug=bool(on)))
            except OSError as e:
                LOG.warning("could not save the debug setting: %s", e)

    def debug_tick(self):
        cfg_debug = bool(self.settings.get("debug"))
        if cfg_debug and not self.debug_ring.active:
            self.set_debug(True, persist=False)
        elif not cfg_debug and self.debug_ring.active:
            self.set_debug(False, persist=False)
        if not self.debug_ring.active:
            return
        try:
            m = os.path.getmtime(self.paths.viewer)
        except OSError:
            m = None
        if m is not None and m != self.viewer_mtime:
            self.viewer_mtime = m
            self.viewer_seen_at = self.clock.wall()
            if self.settings.get("debug_renew"):
                self.debug_until = self.clock.mono() + self.settings.get("debug_timeout_min") * 60
        if self.debug_until is not None and self.clock.mono() >= self.debug_until:
            self.set_debug(False)

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
        s = self.settings
        if kind in ("set_password", "clear_password"):
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
        if kind == "trust":
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
        if kind == "block":
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
        if kind == "unblock":
            ip = str(a.get("ip") or "")
            self.temp_blocks.pop(ip, None)
            self.password_failures.pop(ip, None)
            if ip in s.get("blocked"):
                s.modify(lambda d: d.update(blocked=[x for x in (d.get("blocked") or []) if x != ip]))
            self.event("security", "ip_unblocked", f"{ip} unblocked from the page", ip=ip)
            return "ip_unblocked", "Unblocked."
        if kind == "restart":
            # never while the bridge is in use: a live job running through it, or orders in the last 30 s
            if self.live_job.get("active"):
                raise ValueError("in use: a live job is running through the bridge")
            if self.last_order_wall and self.clock.wall() - self.last_order_wall < 30:
                raise ValueError("in use: orders arrived in the last 30 seconds")
            # the unit has Restart=always: leaving is enough, no sudo. Late, so this answer is written first.
            self.event("info", "restarting", "The page asked to restart the bridge (connections are cut and come back)")
            threading.Timer(1.5, lambda: os._exit(0)).start()
            return "restarting", "Restarting: the connections come back in a few seconds."
        if kind in ("stop_safe", "resume_arm", "resume_disarm", "interrupted_discard"):
            return self._run_live_action(kind, a, seq)
        if kind == "debug":
            on = bool(a.get("on", True))
            self.set_debug(on)
            return "debug_on" if on else "debug_off", "Debug on." if on else "Debug off."
        if kind == "debug_extend":
            if not self.debug_ring.active:
                raise ValueError("debug is off")
            minutes = self.settings.get("debug_timeout_min")
            self.debug_until = self.clock.mono() + minutes * 60
            self.event("info", "debug_extended", f"Debug extended: it turns off in {minutes} min", minutes=minutes)
            return "debug_extended", "Debug extended."
        if kind in ("rename", "give_control", "release", "kick"):
            remember = False
            with self.lock:
                client = self.clients.get(str(self._field(a, "client", "cliente") or ""))
                if client is None and kind != "release":
                    raise ValueError("that connection is gone")
                if kind == "rename":
                    new = str(self._field(a, "name", "name") or "").strip()[:40]
                    if not new:
                        raise ValueError("the name is missing")
                    client.name = new
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
                ip, new = client.ip, client.name
                s.modify(lambda d: d.setdefault("names", {}).update({ip: new}))
            return "done", "Done."
        raise ValueError(f"unknown action: {kind}")

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

    # -- state for the Services page and the movement logic --
    def build_state(self):
        wall = self.clock.wall()
        mono = self.clock.mono()
        s = self.settings
        minute = int(wall // 60)
        with self.lock:
            self.seq = (self.seq + 1) % 100000
            hist = [list(self.history.get(m) or [0, 0, 0, 0]) for m in range(minute - 59, minute + 1)]
            clients = [c.info(wall) for c in sorted(self.clients.values(), key=lambda c: c.since)]
            job = dict(self.live_job)
            debug = self._debug_state(wall, mono)
            state = {
                "schema": SCHEMA,
                "version": VERSION,
                "seq": self.seq,
                "time": wall,
                "clock": time.strftime("%H:%M:%S", time.localtime(wall)),
                "uptime_s": round(wall - self.started_wall),
                "port": self.listening["port"],
                "error": self.listening["error"],
                "exclusive": s.get("exclusive"),
                "owner": self.owner.name if self.owner else None,
                "owner_id": self.owner.id if self.owner else None,
                "owner_since_s": round(wall - self.owner_since) if self.owner_since else None,
                "clients": clients,
                "totals": dict(self.totals),
                "history": hist,
                "duet_ms_avg": round(self.timing["all"].avg_ms, 1) if self.timing["all"].avg_ms is not None else None,
                "duet_ms_max": round(self.timing["all"].max_ms, 1),
                "order_ms_avg": round(self.timing["order"].avg_ms, 1) if self.timing["order"].avg_ms is not None else None,
                "query_ms_avg": round(self.timing["query"].avg_ms, 1) if self.timing["query"].avg_ms is not None else None,
                "events": list(self.events)[:40],
                "security": {
                    "password": self.needs_password(),
                    "allowed": s.get("allowed"),
                    "local_only": not s.get("allowed"),
                    "exposed": self.exposed(),
                    "trusted": s.get("trusted"),
                    "max_connections": s.get("max_connections"),
                    "password_attempts": s.get("password_attempts"),
                    "blocked": [{"ip": ip, "remaining_s": None, "fixed": True, "name": s.get("names").get(ip)} for ip in s.get("blocked")]
                    + [{"ip": ip, "remaining_s": int(until - wall)} for ip, until in self.temp_blocks.items()
                       if until > wall and ip not in s.get("blocked")],
                    "rejected": list(self.rejected)[:10],
                },
                "action": self.action_seen["result"],
                "live_stop": self.live.public_state() if self.live is not None else {"enabled": False},
                "debug": debug,
                "activity": {
                    "generated_at": wall,
                    "clients_connected": len(self.clients),
                    "pending_orders": self.pending_orders,
                    "last_order_at": self.last_order_wall,
                    "last_motion_at": self.last_motion_wall,
                    "live_job": job,
                },
            }
        return state

    def _debug_state(self, wall, mono):
        active = self.debug_ring.active
        viewing = self.viewer_seen_at is not None and wall - self.viewer_seen_at <= VIEWER_GRACE_S
        return {
            "active": active,
            "timeout_min": self.settings.get("debug_timeout_min"),
            "renew": bool(self.settings.get("debug_renew")),
            "remaining_s": max(0, int(self.debug_until - mono)) if (active and self.debug_until is not None) else None,
            "viewer_seen_s": round(wall - self.viewer_seen_at) if self.viewer_seen_at is not None else None,
            "last_id": self.debug_ring.last_id,
            "lines": self.debug_ring.snapshot() if (active or viewing) else [],
        }

    def write_state(self):
        state = self.build_state()
        path = self.paths.state
        try:
            write_json_atomic(path, state)
            self._state_warned = False
            return True
        except OSError as e:
            if not self._state_warned:
                self._state_warned = True
                LOG.warning("could not write the state file %s: %s", path, e)
        return False

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
        period = STATE_PERIOD_DEBUG_S if self.debug_ring.active else STATE_PERIOD_S
        if mono - self._last_state_write >= period:
            self._last_state_write = mono
            self.write_state()

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
                        self.event("security", "open_to_lan", "Any device of the private network may send orders: set `allowed` (for example the PC's address) or a password",
                                   port=port)
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


def make_readable():
    # Binding port 23 without root (CAP_NET_BIND_SERVICE in the unit) makes the
    # process "non dumpable": /proc/<pid> becomes root's and DSF cannot identify
    # it ("Failed to find plugin permissions"), cutting the connection.
    # PR_SET_DUMPABLE=1 puts it back to normal.
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(4, 1, 0, 0, 0)  # PR_SET_DUMPABLE
    except Exception as e:
        LOG.warning("could not mark the process as readable: %s", e)


def main():
    # The journal gets warnings and errors only; the detailed view is the
    # in-memory Debug view of the Services page.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(levelname)s %(message)s")
    make_readable()
    print(f"Workshop G-code bridge {VERSION} (journal at warning level; debug is in the Services page)", flush=True)
    Bridge().serve()


if __name__ == "__main__":
    main()
