"""
Machine state for the whole service: a SINGLE subscription to DSF
(2026-10-12, item 13 of the plan: "nobody asks for the full /machine/status").

Before, each reader (job_poller, motor_poller, jog, health, risk, consumption,
timer, shutdown, communication...) asked for GET /machine/status over HTTP
(90 KB and ~300 ms of DuetWebServer each; measured 2026-10-11: 168 requests
per minute with a job and DWS at 100% of one core) and event_watcher and
job_trace each opened their own subscription. Now this module is the ONLY
owner of the object model:

  - One dsf-python SubscribeConnection in Patch mode, over DSF's socket
    (no DuetWebServer or HTTP), with the FILTERS filters. After the first
    send DSF only sends what changed, and if this side is slow to read, DSF
    merges the changes into a single patch (it waits for the Acknowledge).
  - One thread (heartbeat "suscripcion") reads, applies the patches to the
    in-memory model and notifies whoever registered with on_change().
  - get_status() returns a copy of the model WITHOUT asking for anything
    (the same copy for everybody until another patch arrives: it is
    read-only). read_in("state.status") reads a single value.
  - If it drops (DSF restarts, the socket closes or nothing arrives within
    WITHOUT_DATA_S) it reconnects with a growing wait (WAIT_MIN_S..WAIT_MAX_S).
    While there is no connection, get_status() waits up to `timeout` and then
    raises StateUnavailable (the readers already handled "could not read").
  - Every REFRESH_S it asks for the whole model again (a quiet reconnection):
    if some patch was applied wrongly, it corrects itself.

Filters (why each one; "x.**" = x and everything inside):
  state.**      status (all), machineMode and gpOut (air, jog, trace),
                logFile (event_watcher), upTime/startupError (config_guard).
                upTime changes every second: it serves as the connection's heartbeat.
  move.**       axes (position, homing, limits, zone offsets, speed,
                current), extruders, currentMove, workplaceNumber,
                limitAxes/noMovesBeforeHoming (jog, motors, trace, zones,
                risk, motors_enable, camera).
  job.file.** job.filePosition job.duration job.layer job.lastFileCancelled
  job.lastFileAborted job.lastFileName
                job in progress (job_poller, live_job, trace, camera,
                config_guard). NOT job.layers: it grows with every layer.
  global.**     workshop variables (selectedMode, consumptionKWh,
                laserOffsetOn, jogFree, workshopLanguage...).
  boards.**     VIN, drivers, CAN boards (motors, health, config_guard,
                status_light).
  heat.** sensors.** fans.** spindles.** tools.**
                heaters, endstops, fans, spindle,
                tools (consumption, risk, status_light, pid_zones,
                shutdown_all, config_guard, trace).
  sbc.**        Pi CPU/memory and sessions (health_poller).
  messages      RRF messages (event_watcher). They are not kept in the
                model: they arrive only in the patch (to the listeners).
Left out on purpose: inputs (changes with every G-code line; communication
reads it with a one-shot read), plugins (our own data: each
set_status would come back as a patch), job.layers, volumes, directories,
network, httpEndpoints, root-level userSessions, limits.

Why "x.**" and not "x": in DSF (Model/Filter.cs, PathMatches) a filter
only matches change paths that are no longer than the filter.
"move.axes" received the whole array on connect but NEVER the change of
move.axes[0].machinePosition (a longer path). With "move.**" it does.

How DSF applies the patches (IPC/Processors/ModelSubscription.cs, v3.6):
  - Object: only the keys that changed.
  - List of objects: the WHOLE list with the current length; unchanged
    elements go as {} (or [] if the element is itself a model list) and
    changed ones with their fields. A shorter list = elements were removed.
    A list of values (numbers) goes complete.
  - null = the value is null (a heater that is deleted, global.* emptied).
  - messages: only the NEW messages (not the list).
apply_patch() does that (with [] inside a list taken as "unchanged" if what
was there was a list with data).

Own reading of the socket (DsfConnection): dsf-python only does the
handshake. Its receive_json counts braces without looking at quotes (a "{"
inside a text cuts the JSON) and if DSF closes the socket it spins idle
until the 3 s timeout. Here the JSON boundaries are found respecting the
texts, and an empty recv is "connection closed".

Counter to measure on the Pi: stats() (patches/s, KB/s, whether it is alive,
reconnections, how many patches each key brought) is published in
plugins.WorkshopService.data.servicesInternal.suscripcion (heartbeats.py), and
each patch is a "suscripcion" heartbeat on the Services page (the average
interval = 1 / patches per second).

Also: zone_name() (name of each work zone, first line of
sys/workshop/zones/p<N>.g, format "; G55 <name> -- ..." written by
saveworkplace.g and the Work zones page).

"""
import paths
import json
import os
import re
import socket
import threading
import time
from collections import deque

import heartbeats
from messages import M

WP_DIR = paths.ZONES_DIR
WP_CODES = ["G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3"]

FILTERS = [
    "state.**",
    "move.**",
    "job.file.**",
    "job.filePosition",
    "job.duration",
    "job.layer",
    "job.lastFileName",
    "job.lastFileCancelled",
    "job.lastFileAborted",
    "global.**",
    "boards.**",
    "heat.**",
    "sensors.**",
    "fans.**",
    "spindles.**",
    "tools.**",
    "sbc.**",
    "messages",
]

# No message within this time: dead connection. With the board running
# state.upTime changes every 1 s; with the board off nothing arrives and it
# reconnects once a minute (cheap). A closed socket is seen right away.
WITHOUT_DATA_S = 60
RECV_S = 1.0  # how often the thread comes back even if nothing arrives
INITIAL_S = 15  # deadline for the initial model (DSF sends it right away)
WAIT_MIN_S = 1
WAIT_MAX_S = 30
REFRESH_S = 600  # whole model again (quiet reconnection)
WINDOW_S = 10  # window of the patches-per-second counter
MAX_MESSAGE = 16 * 1024 * 1024
ACK = b'{"command":"Acknowledge"}'

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop-service.log")
NAME_HEARTBEAT = "subscription"
# Texts of the Services page (heartbeats.register / heartbeats.detail)
TITLE = M("machine_state_machine_state_dsf")
DESCRIPTION = (M("machine_state_single_subscription_dsf_state_every_process"))
DETAIL_CONNECTED = M("machine_state_connected_to_dsf")
DETAIL_WITHOUT_CONNECTION = M("machine_state_no_connection_dsf_retrying")


class StateUnavailable(Exception):
    """There is no connection to DSF (or the first model has not arrived yet)."""


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [state_machine] {msg}\n")
    except Exception:
        pass


# ---------------- parches ----------------

def _copy(o):
    """Copy of dicts/lists (faster than copy.deepcopy; the rest is immutable)."""
    if isinstance(o, dict):
        return {k: _copy(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_copy(v) for v in o]
    return o


def apply_patch(base, patch):
    """Applies a DSF patch (Patch mode) onto `base` (see above). What is
    inserted is copied: the patch does not stay shared with the model."""
    for k, v in patch.items():
        b = base.get(k)
        if isinstance(v, dict) and isinstance(b, dict):
            apply_patch(b, v)
        elif isinstance(v, list) and isinstance(b, list):
            _apply_items(b, v)
        else:
            base[k] = _copy(v)
    return base


def _apply_items(b, v):
    for i, x in enumerate(v):
        if i < len(b):
            y = b[i]
            if isinstance(x, dict) and isinstance(y, dict):
                apply_patch(y, x)
            elif isinstance(x, list) and isinstance(y, list):
                if x or not y:  # [] over a list with data = unchanged
                    _apply_items(y, x)
            else:
                b[i] = _copy(x)
        else:
            b.append(_copy(x))
    del b[len(v):]


def _path(model, route):
    """model, "move.axes[0].machinePosition" -> value (KeyError if it is not there)."""
    o = model
    for part in route.split("."):
        m = re.fullmatch(r"([^\[]*)((?:\[\d+\])*)", part)
        label, idx = m.group(1), m.group(2)
        if label:
            if not isinstance(o, dict) or label not in o:
                raise KeyError(route)
            o = o[label]
        for i in re.findall(r"\[(\d+)\]", idx):
            i = int(i)
            if not isinstance(o, list) or i >= len(o):
                raise KeyError(route)
            o = o[i]
    return o


# ---------------- socket ----------------

_OUTSIDE = re.compile(rb'[{}"]')
_INSIDE = re.compile(rb'["\\]')
_NO_WHITE = re.compile(rb"\S")


class _Cutter:
    """Splits the consecutive JSON objects DSF sends (no separator),
    respecting the quoted texts. Incremental: it does not reread what was already seen."""

    def __init__(self):
        self.buf = bytearray()
        self.pos = 0
        self.prof = 0
        self.in_text = False
        self.begin = 0

    def add(self, payload):
        self.buf += payload
        if len(self.buf) > MAX_MESSAGE:
            raise ValueError(M("machine_state_dsf_message_more_than_bytes", MAX_MESSAGE=MAX_MESSAGE))

    def following(self):
        """bytes of a complete object, or None if incomplete."""
        buf = self.buf
        i = self.pos
        while True:
            if self.prof == 0:
                m = _NO_WHITE.search(buf, i)
                if not m:
                    del buf[:]
                    self.pos = 0
                    return None
                if buf[m.start()] != 0x7B:  # "{"
                    raise ValueError("DSF sent something that is not a JSON object")
                self.begin = m.start()
                self.prof = 1
                i = m.end()
                continue
            if self.in_text:
                m = _INSIDE.search(buf, i)
                if not m:
                    self.pos = len(buf)
                    return None
                if m.group() == b"\\":
                    if m.end() >= len(buf):
                        self.pos = m.start()  # the escape continues in the next recv
                        return None
                    i = m.end() + 1
                    continue
                self.in_text = False
                i = m.end()
                continue
            m = _OUTSIDE.search(buf, i)
            if not m:
                self.pos = len(buf)
                return None
            c = m.group()
            i = m.end()
            if c == b'"':
                self.in_text = True
            elif c == b"{":
                self.prof += 1
            else:
                self.prof -= 1
                if self.prof == 0:
                    obj = bytes(buf[self.begin:i])
                    del buf[:i]
                    self.pos = 0
                    return obj


class DsfConnection:
    """DSF Patch subscription: handshake with dsf-python, own reading."""

    def __init__(self, filters):
        self.filters = list(filters)
        self.sock = None
        self.cutter = _Cutter()

    def open_it(self):
        from dsf.connections import SubscribeConnection, SubscriptionMode
        import dsf_compat

        # dsf-python 3.7: verbose + obsolete so that the model is the same as on DSF 3.6 (see dsf_compat)
        c = SubscribeConnection(SubscriptionMode.PATCH, filter_list=self.filters, **dsf_compat.subscribe_kwargs(SubscribeConnection))
        try:
            c.connect()
        except Exception:
            c.close()
            raise
        self._c = c
        self.sock = c.socket
        if c.input:  # what dsf-python already read beyond the handshake
            self.cutter.add(c.input.encode("utf-8"))
            c.input = ""
        return self

    def receive(self, timeout):
        """(dict, bytes) of the next message, or None if nothing arrived within
        `timeout`. ConnectionError if DSF closed the socket."""
        limit = time.monotonic() + timeout
        while True:
            obj = self.cutter.following()
            if obj is not None:
                self.sock.sendall(ACK)  # DSF does not send the next one until the Acknowledge
                return json.loads(obj.decode("utf-8")), len(obj)
            subtracts = limit - time.monotonic()
            if subtracts <= 0:
                return None
            self.sock.settimeout(subtracts)
            try:
                payload = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not payload:
                raise ConnectionError("DSF closed the subscription")
            self.cutter.add(payload)

    def shut(self):
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:
            pass
        self.sock = None


def _connect_dsf(filters):
    return DsfConnection(filters).open_it()


# ---------------- the subscription ----------------

class Subscription:
    """Owner of the model. run_once() is one step of the thread (the tests call
    it by hand with a fake connection) and returns how long to wait."""

    def __init__(self, filters=FILTERS, connect_to=_connect_dsf, clock=time.monotonic):
        self.filters = list(filters)
        self.connect_to = connect_to
        self.clock = clock
        self.conn = None
        self.model = {}
        self.version = 0
        self._snap = None
        self._snap_version = -1
        self.lock = threading.Lock()
        self.change = threading.Condition(self.lock)
        self.connected = False
        self.since = None  # when it connected (for REFRESH_S)
        self.last = None  # ultimo mensaje
        self.waiting = WAIT_MIN_S
        self.connections = 0
        self.reconnects = 0
        self.patches_total = 0
        self.bytes_total = 0
        self.by_key = {}
        self.window = deque()
        self.last_error = None
        self.listeners = []
        self._thread = None
        self._thread_lock = threading.Lock()

    # -- hilo --
    def launch(self):
        """Starts the thread only once (supervised by heartbeats)."""
        with self._thread_lock:
            if self._thread is not None:
                return
            self._thread = True
        heartbeats.register(NAME_HEARTBEAT, TITLE, DESCRIPTION, 10)
        heartbeats.launch(NAME_HEARTBEAT, self.execute)

    def execute(self):
        log_file(f"starting (one Patch subscription, {len(self.filters)} filters)")
        while True:
            waiting = self.run_once()
            if waiting:
                time.sleep(waiting)

    def run_once(self):
        try:
            if self.conn is None:
                self._connect()
                return 0
            if self.since is not None and self.clock() - self.since >= REFRESH_S:
                self._close()
                self._connect()  # whole model again, without waiting
                return 0
            r = self.conn.receive(RECV_S)
            if r is None:
                if self.clock() - self.last >= WITHOUT_DATA_S:
                    raise TimeoutError(f"DSF sent nothing in {WITHOUT_DATA_S} s")
                return 0
            self._apply(*r)
            return 0
        except Exception as e:
            return self._failure(e)

    def _connect(self):
        self.conn = self.connect_to(self.filters)
        r = self.conn.receive(INITIAL_S)
        if r is None:
            raise TimeoutError("DSF did not send the initial model")
        model, n = r
        model.pop("messages", None)  # old messages: they are not repeated
        with self.lock:
            self.model = model
            self.version += 1
            self.connected = True
            self.since = self.last = self.clock()
            self.change.notify_all()
        self.connections += 1
        self.waiting = WAIT_MIN_S
        self._count(model, n)
        if self.connections == 1 or self.last_error:
            log_file(f"connected (connection {self.connections}, initial model {n} bytes)")
        self.last_error = None
        heartbeats.detail(NAME_HEARTBEAT, DETAIL_CONNECTED)
        heartbeats.ok(NAME_HEARTBEAT)
        if self.listeners:
            self._notify(_copy(model), True)  # the model keeps changing: copy

    def _apply(self, patch, n):
        messages = patch.pop("messages", None)
        with self.lock:
            if patch:
                apply_patch(self.model, patch)
                self.version += 1
            self.last = self.clock()
            self.change.notify_all()
        if messages:
            patch["messages"] = messages
        self._count(patch, n)
        heartbeats.ok(NAME_HEARTBEAT)
        self._notify(patch, False)

    def _count(self, patch, n):
        current_time = self.clock()
        self.patches_total += 1
        self.bytes_total += n
        self.window.append((current_time, n))
        while self.window and current_time - self.window[0][0] > WINDOW_S:
            self.window.popleft()
        for k in patch:
            self.by_key[k] = self.by_key.get(k, 0) + 1

    def _failure(self, e):
        raw_text = f"{type(e).__name__}: {e}"
        if raw_text != self.last_error:
            log_file(f"no connection ({raw_text}); retrying in {self.waiting} s")
        self.last_error = raw_text
        self._close()
        self.reconnects += 1
        heartbeats.error(NAME_HEARTBEAT, e)
        heartbeats.detail(NAME_HEARTBEAT, DETAIL_WITHOUT_CONNECTION)
        waiting = self.waiting
        self.waiting = min(self.waiting * 2, WAIT_MAX_S)
        return waiting

    def _close(self):
        if self.conn is not None:
            try:
                self.conn.shut()
            except Exception:
                pass
        self.conn = None
        self.since = None
        with self.lock:
            self.connected = False

    def _notify(self, patch, full):
        for fn in list(self.listeners):
            try:
                fn(patch, full)
            except Exception as e:
                log_file(f"listener {getattr(fn, '__name__', fn)}: {type(e).__name__}: {e}")

    # -- lectura --
    def _wait_for(self, timeout):
        """With the lock taken: waits to be connected."""
        if not self.connected and timeout and timeout > 0:
            self.change.wait_for(lambda: self.connected, timeout)
        if not self.connected:
            raise StateUnavailable("no connection with DSF")

    def status(self, timeout=3):
        """Copy of the model (shared until the next patch: do not modify)."""
        with self.lock:
            self._wait_for(timeout)
            if self._snap_version != self.version:
                self._snap = _copy(self.model)
                self._snap_version = self.version
            return self._snap

    def read_in(self, route, default=None, timeout=3):
        with self.lock:
            self._wait_for(timeout)
            try:
                return _copy(_path(self.model, route))
            except KeyError:
                return default

    def wait_for_change(self, version, timeout):
        """Waits for a patch later than `version`; returns the current version."""
        with self.lock:
            self.change.wait_for(lambda: self.version != version, timeout)
            return self.version

    def stats(self):
        current_time = self.clock()
        with self.lock:
            v = list(self.window)
        v = [x for x in v if current_time - x[0] <= WINDOW_S]
        return {
            "live": bool(self.connected and self.last is not None and current_time - self.last < WITHOUT_DATA_S),
            "patches_s": round(len(v) / WINDOW_S, 2),
            "kb_s": round(sum(n for _, n in v) / 1024 / WINDOW_S, 2),
            "patches_total": self.patches_total,
            "kb_total": round(self.bytes_total / 1024),
            "age_last_s": round(current_time - self.last, 1) if self.last is not None else None,
            "connections": self.connections,
            "reconnections": self.reconnects,
            "error": self.last_error,
            "per_key": dict(self.by_key),
            "filters": len(self.filters),
        }


_their = Subscription()


def launch():
    """Starts the subscription (main.py, at the beginning). get_status() starts
    it by itself if nobody did."""
    _their.launch()


def get_status(timeout=3, max_age_s=None):
    """Object model (the FILTERS fields) without asking DSF for anything. max_age_s
    is kept for compatibility: the model is always up to date while the
    subscription is alive. StateUnavailable if there is no connection after `timeout`."""
    _their.launch()
    return _their.status(timeout)


def read_in(route, default=None, timeout=3):
    """Un dato suelto: leer("state.status"), leer("move.axes[0].homed")."""
    _their.launch()
    return _their.read_in(route, default, timeout)


def on_change(fn):
    """fn(patch, full) in the subscription thread after each patch (full=True:
    whole model on (re)connect). It must be fast (enqueue and return) and must
    not modify the patch."""
    if fn not in _their.listeners:
        _their.listeners.append(fn)
    _their.launch()


def unsubscribe(fn):
    try:
        _their.listeners.remove(fn)
    except ValueError:
        pass


def stats():
    return _their.stats()


def read_one_shot(filters, timeout=5):
    """One-shot read of fields OUTSIDE the common subscription (e.g.
    "inputs", which changes with every G-code line): a short subscription
    with those filters, the first send, and it closes. Over DSF's socket, no
    HTTP.

    2026-10-13: DuetControlServer only notices that a subscriber is gone when it tries to send
    it the next patch. A filter that rarely changes (inputs, the RS485 data) left every closed
    subscription open for hours (6 sockets per minute, 6000 after 17 h, the process at 180 % CPU).
    state.upTime changes every second, so the dead subscription is released within a second."""
    if "state.upTime" not in filters and "state.**" not in filters:
        filters = list(filters) + ["state.upTime"]
    c = _connect_dsf(filters)
    try:
        r = c.receive(timeout)
        if r is None:
            raise StateUnavailable("DSF did not answer")
        r[0].pop("messages", None)
        return r[0]
    finally:
        c.shut()


_PLUGINS_CACHE = {"at": 0.0, "value": None}
_PLUGINS_LOCK = threading.Lock()


def read_plugins(max_age=8.0, timeout=5):
    """The `plugins` branch of the object model (the data every plugin publishes), read on demand.

    DSF only delivers it for the filter "plugins.**": a filter that names one plugin
    ("plugins.<Id>.data.**") brings nothing (checked on the Pi, 2026-10-21). The answer is
    about 140 KB (WorkshopService's own data is most of it), so it is cached for `max_age` seconds and
    shared by every caller (status light, protection guard)."""
    with _PLUGINS_LOCK:
        now = time.monotonic()
        if _PLUGINS_CACHE["value"] is not None and now - _PLUGINS_CACHE["at"] < max_age:
            return _PLUGINS_CACHE["value"]
        got = read_one_shot(["plugins.**"], timeout=timeout).get("plugins") or {}
        _PLUGINS_CACHE.update(at=now, value=got)
        return got


def zone_name(idx):
    """'G55 MDF 3mm cut' (or just 'G55' if it has no file/name)."""
    code = WP_CODES[idx] if 0 <= idx < len(WP_CODES) else f"P{idx + 1}"
    try:
        with open(f"{WP_DIR}/p{idx + 1}.g", encoding="utf-8-sig") as f:
            first = f.readline()
        m = re.match(r"^;\s*G5[4-9](?:\.\d)?\s+(?!--)(.+?)(?:\s+--.*)?\s*$", first)
        if m:
            return f"{code} {m.group(1)}"
    except Exception:
        pass
    return code


def last_reading():
    """For the black box: {"ms": None (there are no requests any more), "age_s": how
    long ago the last patch arrived, "error": last error of the subscription}."""
    e = _their.stats()
    return {"ms": None, "age_s": e.get("age_last_s"), "error": None if e.get("live") else e.get("error") or "without_connection"}


def last_state():
    """The last model received (or None), without waiting or asking for anything."""
    try:
        return _their.status(0)
    except Exception:
        return None
