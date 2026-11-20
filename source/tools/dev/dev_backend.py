"""The REAL backend of the service (dsf/) running on a development PC, with no board, no DSF and no network.

Used by tools/dev/api_server.py (environment E2 of the page redesign). What is real: the registry of operations (api_ops.init),
the roles and sessions, the validation of arguments, the confirmations, the conflicts, the audit, the database and the texts.
What is a stand-in: the bridge to the board (DevBridge: nothing is sent, every code is recorded and answered from a script), the
object model of the machine (DevModel: a small invented one) and the processes of the service, which do not run (their
heartbeats are beaten by hand so that the published process list has the real shape).

Safety of the environment, applied BEFORE any module of dsf/ is imported (isolate()):
  * every data file lives under a throwaway folder (WORKSHOP_DSF_ROOT);
  * a socket may only connect to this computer: any other address is refused and recorded (the real machine cannot be reached);
  * no program is launched (subprocess is refused and recorded), and nothing can end the process (os._exit is recorded).
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DSF = os.path.join(ROOT, "dsf")
PLUGIN_ID = "WorkshopService"
LOOPBACK = ("127.0.0.1", "::1", "localhost")

blocked = []        # what the isolation refused: {"t", "what", "detail"}
_real_time = time.time
_real_mono = time.monotonic
_clock = {"offset": 0.0}


def _refuse(what, detail):
    blocked.append({"t": time.strftime("%H:%M:%S"), "what": what, "detail": str(detail)[:200]})


def isolate(data_root):
    """Points the service at `data_root` and closes the ways out of this computer. Call it once, before importing dsf/."""
    root = data_root.replace("\\", "/").rstrip("/")
    for d in ("sd/sys/workshop/config", "sd/sys/workshop/data", "sd/sys/workshop/macros", "sd/gcodes", "sd/macros", "conf", "plugins"):
        os.makedirs(root + "/" + d, exist_ok=True)
    os.environ["WORKSHOP_DSF_ROOT"] = root
    for name in ("WORKSHOP_DB", "WORKSHOP_USERS", "WORKSHOP_ROLES", "WORKSHOP_ACCESS", "WORKSHOP_ACCESS_USAGE", "WORKSHOP_CONFIG", "WORKSHOP_SECRETS", "WORKSHOP_PLUGINS_DIR"):
        os.environ.pop(name, None)  # every file follows the root: nothing of this PC's environment leaks in
    sys.dont_write_bytecode = True

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def host_of(address):
        return address[0] if isinstance(address, tuple) and address else str(address)

    def connect(self, address):
        if host_of(address) not in LOOPBACK:
            _refuse("network", address)
            raise ConnectionRefusedError("dev environment: connections leave this computer nowhere (%s)" % (address,))
        return real_connect(self, address)

    def connect_ex(self, address):
        if host_of(address) not in LOOPBACK:
            _refuse("network", address)
            return 10061
        return real_connect_ex(self, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex

    class NoPopen:
        def __init__(self, args, *a, **kw):
            _refuse("program", args)
            raise FileNotFoundError("dev environment: no program is launched (%s)" % (args,))

    subprocess.Popen = NoPopen
    os.system = lambda command: (_refuse("program", command), 1)[1]
    os._exit = lambda code=0: _refuse("exit", code)

    # the clock can be moved forward (sessions that expire, ages): both readings shift together
    time.time = lambda: _real_time() + _clock["offset"]
    time.monotonic = lambda: _real_mono() + _clock["offset"]
    return root


def advance_clock(seconds):
    _clock["offset"] += float(seconds)
    return _clock["offset"]


def _stub_modules():
    """dsf-python is not on a PC; the Tuya library is replaced even when it is installed (the meter is a real device)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import dump_api_contract
    dump_api_contract._stub_dsf_python()
    sys.modules["tinytuya"] = types.ModuleType("tinytuya")
    if DSF not in sys.path:
        sys.path.insert(0, DSF)


def default_model():
    """A small invented object model: enough for the operations that read the state of the machine. Not a capture of a real one."""
    return {
        "state": {"status": "idle", "upTime": 3600, "machineMode": "Laser", "laserPwm": 0, "currentTool": -1, "atxPower": True},
        "job": {"file": {"fileName": None}, "duration": None, "lastFileName": None},
        "move": {"axes": [{"letter": a, "homed": True, "machinePosition": 0, "userPosition": 0, "min": 0, "max": 300} for a in "XYZ"],
                 "currentMove": {"topSpeed": 0, "requestedSpeed": 0}, "workplaceNumber": 0},
        "boards": [{"name": "Duet 3 MB6HC", "shortName": "MB6HC", "firmwareVersion": "3.6.3", "vIn": {"current": 24.1}, "mcuTemp": {"current": 38.0}}],
        "global": {"selectedMode": "laser", "powerOffOnFinish": False, "workshopLanguage": "es"},
        "heat": {"heaters": [], "bedHeaters": []}, "tools": [], "fans": [], "sensors": {"endstops": [], "probes": []},
        "inputs": [{"name": n, "state": "idle"} for n in ("HTTP", "Telnet", "File", "USB", "Aux", "Trigger", "Queue", "LCD", "SBC", "Daemon", "Aux2", "Autopause")],
        "network": {"hostname": "dev-sim", "interfaces": [{"actualIP": "127.0.0.1", "type": "lan"}]},
        "plugins": {},
    }


class DevSubscription:
    """Stands in for machine_state.Subscription: the model is a dict of this process, changed through set() / patch()."""

    def __init__(self, model):
        self.model = model
        self.listeners = []
        self.changed = _real_mono()
        self.filters = []

    def launch(self):
        return None

    def status(self, timeout=3):
        return self.model

    def read_in(self, route, default=None, timeout=3):
        import machine_state
        try:
            value = machine_state._path(self.model, route)
        except Exception:
            return default
        return default if value is None else value

    def snapshot(self, timeout=3):
        return self.model, self.age()

    def age(self):
        return round(_real_mono() - self.changed, 1)

    def stats(self):
        return {"live": True, "patches_s": 0, "kb_s": 0, "age_last_s": self.age(), "connections": 1, "reconnections": 0, "error": None, "per_key": {}, "filters": 0}

    def remove_listener(self, fn):
        if fn in self.listeners:
            self.listeners.remove(fn)

    def listener_stats(self):
        return []

    def patch(self, patch):
        import machine_state
        machine_state.apply_patch(self.model, patch)
        self.changed = _real_mono()
        for fn in list(self.listeners):
            try:
                fn(patch, False)
            except Exception:
                pass


class DevBridge:
    """Stands in for main.Bridge. Publishes into a dict, records every G-code and answers it from a script, saves the settings."""

    def __init__(self, config, on_publish=None, on_code=None):
        self.config = config
        self.on_code = on_code          # fn(code): what a code does to the pretend machine (a `set global...` changes the object model)
        self.payload = {}               # what the service itself reads back (state.get, camera load): the values as they were set
        self.published = {}             # what a page receives: every message as {"key", "params"}, as the real publisher sends it
        self.sent = []                  # {"t", "code", "reply"}
        self.replies = {}               # prefix of a code -> reply text (the longest prefix wins); default ""
        self.lock = threading.RLock()
        self.conn = None
        self.on_publish = on_publish

    def set_status(self, key, value, **options):
        import messages
        self.payload[key] = value
        self.published[key] = messages.data(value)
        if self.on_publish:
            self.on_publish(key, self.published[key])

    def send(self, gcode):
        code = str(gcode)
        hit = max((p for p in self.replies if code.startswith(p)), key=len, default=None)
        reply = self.replies[hit] if hit is not None else ""
        self.sent.append({"t": time.strftime("%H:%M:%S"), "code": code, "reply": reply})
        del self.sent[:-2000]
        if isinstance(reply, Exception):
            raise reply
        if self.on_code:
            self.on_code(code)
        return reply

    def save_config(self):
        import config_store
        config_store.save(self.config)

    def _ensure_connected(self):
        return None


class Backend:
    """The registry on top of the stand-ins. One per process (the modules of dsf/ keep their state at module level)."""

    def __init__(self, data_root, log=None):
        self.root = isolate(data_root)
        _stub_modules()
        self.log_lines = []
        self.log = log or (lambda *a: self.log_lines.append(" ".join(str(x) for x in a)))
        self.model = default_model()
        self.registry = None
        self.config = {}                # ONE settings object and ONE bridge for the life of the process: the loops of the service keep them
        self.bridge = DevBridge(self.config, on_publish=self._on_publish, on_code=self._on_code)
        self.subscription = DevSubscription(self.model)
        self.loops = False
        self.sticky = {}                # key -> the last value a change-only publisher of the service gave
        self.unhealthy = {}             # process id -> error text
        self.stopped = set()            # process ids whose loop is not alive
        self.late = set()               # process ids that stopped beating
        self.started = None

    def start(self):
        import api_ops
        import config_store
        import db
        import heartbeats
        import machine_state
        import messages
        import paths
        import process_registry
        import service_restart
        import users
        with open(os.path.join(DSF, "config.example.json"), encoding="utf-8") as f:
            fresh = json.load(f)
        saved = config_store.load_data()
        config = self.config
        config.clear()
        config.update(saved if saved is not None else fresh)
        for store in (self.bridge.payload, self.bridge.published, self.unhealthy):
            store.clear()
        del self.bridge.sent[:]
        self.stopped.clear()
        self.late.clear()
        self.model.clear()
        self.model.update(default_model())
        machine_state._their = self.subscription
        machine_state.read_one_shot = lambda filters, timeout=5: self.model
        machine_state._read_first_message = lambda filters, timeout: self.model
        db.init_db()
        with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.version = manifest["version"]
        for key, value in manifest.get("data", {}).items():
            self.bridge.set_status(key, value)
        self.registry = api_ops.init(self.bridge, config, PLUGIN_ID, self.version, log=self.log, log_file=self.log,
                                     keys_file=paths.CONF + "/workshop-keys.json", users_file=users.USERS_FILE, token_file=paths.CONF + "/workshop-token")
        self.registry.has_password = lambda: False
        # service.restart: the real op, but the "exit" publishes a new start instead of ending the process (see restart_mode)
        self.restart_mode = "returns"   # returns | never (accepted, nothing happens) | gone (the service does not come back)
        service_restart.reset()
        service_restart.configure(cleanup=lambda: None, exit_fn=self._fake_exit, log=self.log)
        if not heartbeats._info:
            for row in process_registry.heartbeat_rows(messages.M):
                heartbeats.register(*row)
        self.pid = 4242
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")
        self.bridge.set_status("serviceStarted", self.started)
        self.bridge.set_status("connected", True)
        self.publish_base()
        self.beat()
        return self

    # ---- published data ----
    def publish_base(self):
        """The published data of a healthy machine: the keys only a process of the Pi writes come from dev_fixtures (built by hand with the
        documented shapes); the ones the service can work out on a PC are published by its own code."""
        import dev_fixtures
        for key, value in dev_fixtures.base().items():
            self.bridge.set_status(key, value)
        self._real("notifications", lambda: __import__("notifier").init(self.bridge, self.config))
        self._real("communication", lambda: __import__("communication").emit(self.bridge, self.config, force=True))
        self._real("machine", lambda: __import__("machine_ops").publish(self.bridge))
        self._real("shutdownMethod", lambda: __import__("shutdown_method").emit(self.bridge, self.config, force=True))

        def motion():
            import motion_owner
            motion_owner.configure(self.config)
            motion_owner.publish(self.bridge, force=True)
        self._real("motion", motion)
        self._start_loops()

    def _real(self, what, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a publisher that needs the board says so in the log and its key stays as it was
            self.log("dev: %s is not published by the service's own code here (%s: %s)" % (what, type(e).__name__, e))
        # a publisher that only speaks when its value changes says nothing after a reset: what it said the first time is still true
        if what in self.bridge.payload:
            self.sticky[what] = self.bridge.payload[what]
        elif what in self.sticky:
            self.bridge.set_status(what, self.sticky[what])

    def _start_loops(self):
        """The two loops of the service that need no board and that a page verifies its writes against: the shutdown timer (publishes
        shutdownTimer) and the owner of the movement (publishes motion). Started once; they run until the process ends."""
        if self.loops:
            return
        self.loops = True
        import motion_owner
        import shutdown_timer
        for name, target in (("dev-shutdown-timer", shutdown_timer.run_loop), ("dev-motion", motion_owner.run_loop)):
            threading.Thread(target=target, args=(self.bridge, self.config), daemon=True, name=name).start()

    def heal(self):
        """Every process back to healthy, with no trace of an old error (a notice starts from a healthy machine)."""
        import heartbeats
        self.unhealthy.clear()
        self.stopped.clear()
        self.late.clear()
        for info in heartbeats._info.values():
            info.update(error=None, error_ts=None, error_wall=None)

    def patch_published(self, key, partial):
        """Changes some fields of a published object and publishes it whole again (as the service does)."""
        value = dict(self.bridge.payload.get(key) or {})
        value.update(partial)
        self.bridge.set_status(key, value)

    def _on_code(self, code):
        """What a G-code does to the pretend machine. Today: `set global.<name> = <value>` (macros and power.after_job write globals)."""
        import re
        m = re.match(r"\s*set\s+global\.(\w+)\s*=\s*(.+?)\s*$", code)
        if not m:
            return
        raw = m.group(2)
        value = True if raw == "true" else False if raw == "false" else None if raw == "null" else raw.strip('"')
        if isinstance(value, str):
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                pass
        self.subscription.patch({"global": {m.group(1): value}})

    def _on_publish(self, key, value):
        self.model.setdefault("plugins", {}).setdefault(PLUGIN_ID, {"id": PLUGIN_ID, "data": {}})["data"][key] = value

    def beat(self):
        """Beats the heartbeat of every process that is not marked unhealthy and publishes servicesInternal with the service's own code."""
        import heartbeats
        import ipc_stats
        import clock
        for label in list(heartbeats._info):
            info = heartbeats._info[label]
            if label in self.stopped:
                info["live"] = False            # its loop died: the page calls it stopped
            elif label in self.late:
                info["live"] = True             # alive, and its last good loop is four times older than it promises
                info["last_ok"] = clock.mono() - 4 * (info.get("expected_s") or 5)
            elif label in self.unhealthy:
                heartbeats.ok(label)
                heartbeats.mark_live(label)
                heartbeats.error(label, self.unhealthy[label])
            else:
                heartbeats.ok(label)
                heartbeats.mark_live(label)
        process = heartbeats.process()
        process.update(pid=self.pid, memory_mb=process.get("memory_mb", 58.4), cpu_pct=process.get("cpu_pct", 3.1))
        self.bridge.set_status("servicesInternal", {"processes": heartbeats.snapshot(), "process": process, "subscription": heartbeats._subscription(),
                                                    "ipc": ipc_stats.snapshot(), "lights": heartbeats._lights(), "modules": heartbeats._modules()})

    def full_model(self):
        """The object model as a DWC receives it: the invented machine plus this plugin with its manifest, its pid and its published data."""
        with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        manifest.pop("dsfFiles", None)
        manifest.update(pid=self.pid, data=dict(self.bridge.published), dwcFiles=[], dsfFiles=[], dwcVersion="3.6", sbcDsfVersion="3.6")
        model = dict(self.model)
        model["plugins"] = {PLUGIN_ID: manifest}
        model["sbc"] = {"dsf": {"version": "3.6.3", "buildDateTime": "", "is64Bit": True, "pluginSupport": True, "rootPluginSupport": False}}
        return model

    def _fake_exit(self):
        if self.restart_mode == "never":
            return
        self.pid = 0 if self.restart_mode == "gone" else self.pid + 1
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")
        if self.restart_mode != "gone":
            self.bridge.set_status("serviceStarted", self.started)

    # ---- one request, as workshop_api.serve() handles it ----
    def handle(self, headers, body, session=None):
        """(status, body dict). `headers` is a plain dict; `session` an int for a DWC session or None."""
        import api_ops
        import workshop_api as wa
        op_name = None
        try:
            via, keyrec = self.registry.auth_of(session, headers)
            if not str(body or "").strip():
                return 200, {"ok": True, "op": "api.describe", "result": self.registry.describe(), "message": None}
            op_name, args, confirm, origin = wa.parse_request_body(body)
            ctx = {"via": via, "confirm": confirm, "origin": origin, "lang": wa.request_lang(body), "session": session if isinstance(session, int) and session >= 0 else None, "key": keyrec}
            try:
                ctx["http"] = api_ops.http_info(headers, session)
            except Exception:
                ctx["http"] = {}
            return self.registry.call(op_name, args, ctx)
        except wa.ApiError as e:
            return e.status, e.body(op_name)
        except Exception as e:  # noqa: BLE001 - same last resort as the real endpoint
            return 500, wa.ApiError("internal", str(e)).body(op_name)

    def internal(self, op, args=None, confirm=True):
        """An operation run as the service itself (no roles): the seeds use it so that what they create went through the real validation."""
        import workshop_api as wa
        status, body = self.registry.call(op, args or {}, {"via": wa.VIA_INTERNAL, "origin": "dev-seed", "confirm": confirm, "lang": "en"})
        if not body.get("ok"):
            raise RuntimeError("seed: %s %s -> %s %s" % (op, json.dumps(args, ensure_ascii=False), status, json.dumps(body.get("error"), ensure_ascii=False)))
        return body.get("result")

    def error_body(self, op, code, message, extra=None):
        import workshop_api as wa
        e = wa.ApiError(code, message or code, **(extra or {}))
        return e.status, e.body(op)
