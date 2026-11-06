"""G-code interception of M140 / M190 for the bed zones (the logic is bed_zones.py, the configuration bed_zones_config.py).

Its OWN InterceptConnection (Pre mode, filters M140 and M190 only, so no other code pays any latency), separate from the air-assist one of main.py:
that one rests when the automatic air is off and the interceptor watchdog restarts the service after 20 s, which an M190 wait would trip.
This connection has its own watchdog whose limit is the configured timeout plus a margin.

Every intercepted code is answered, whatever happens: ignore_code() when it is not ours, resolve_code() when it is replaced or refused. The one
in progress is also answered on shutdown (release()), because DSF 3.6 leaves an unanswered code waiting forever and jams its channel.

M140 without P: the code is answered at once and the per-zone M140s are sent from a thread of their own (sending to RRF from the callback that
handles an intercepted code deadlocks, see airassist.py). M190 without P: the zones are set the same way and the code is HELD until every zone has
arrived (tolerance), a zone is in fault, or the timeout passes; only that channel waits (the receive loop of this connection waits with it: another
M140 / M190 from a different channel is read after this one is answered).
TODO (hardware): confirm on the machine that the M140s sent from the thread while the M190 is held are not queued behind it (they go to the
plugin's own channel, communication.channel_plugin()).
TODO (dsf-python 3.6, not installed in the dev machine): confirm CodeParameter.string_value for a number letter; this file reads it with a fallback to .value.
"""
import os
import threading
import time

import bed_zones
import bed_zones_config
import heartbeats
import intercept_watchdog
import machine_state
import service_modules
from messages import M

LABEL = "bed_zones"
FILTERS = ["M140", "M190"]
WATCHDOG_MARGIN_S = 30.0
SEND_WAIT_S = 10.0   # longest wait for the per-zone M140s to be sent (they take milliseconds)
POLL_S = 0.5         # reads of the object model kept by machine_state.py (no request to DSF)
REST_S = 3.0


def zone_readings(heat, beds):
    """(temps, faults) of the given M140 bed numbers from the `heat` part of the object model.
    heat.bedHeaters[bed] is the heater number (negative or missing: no heater), heat.heaters[h] has `current` and `state`."""
    heat = heat if isinstance(heat, dict) else {}
    bed_heaters = heat.get("bedHeaters") or []
    heaters = heat.get("heaters") or []
    temps, faults = {}, []
    for bed in beds:
        number = bed_heaters[bed] if 0 <= bed < len(bed_heaters) else None
        heater = heaters[number] if isinstance(number, int) and 0 <= number < len(heaters) else None
        if not isinstance(heater, dict):
            temps[bed] = None
            continue
        temps[bed] = heater.get("current")
        if heater.get("state") == "fault":
            faults.append(bed)
    return temps, faults


def params_of(code):
    """The letters this module cares about as plain strings; a letter that is not in the code is not in the dict."""
    out = {}
    for letter in ("S", "P", "H"):
        p = code.parameter(letter)
        if p is None:
            continue
        text = getattr(p, "string_value", None)
        out[letter] = str(p.value if text is None else text).strip()
    return out


class Handler:
    """Answers one intercepted code. Everything it needs from outside is injected, so a test needs no DSF."""

    def __init__(self, conn, send, read_heat, success, error, clock=time.monotonic, sleep=time.sleep, log=print, stop=None,
                 note=lambda *a, **k: None):
        self.conn, self.send, self.read_heat = conn, send, read_heat
        self.success, self.error = success, error
        self.clock, self.sleep, self.log, self.note = clock, sleep, log, note
        self.stop = stop or threading.Event()

    # -- answers --
    def _ok(self, text):
        self.conn.resolve_code(self.success, str(text))

    def _fail(self, text):
        self.conn.resolve_code(self.error, str(text))

    def _send_in_thread(self, codes):
        """Sends the codes from a thread of its own; returns an Event set when done and a list with the error, if any."""
        done, problem = threading.Event(), []

        def work():
            try:
                for c in codes:
                    self.send(c)
            except Exception as e:  # noqa: BLE001 - reported to the caller, never raised in a thread
                problem.append(e)
                self.log(f"bed zones: could not send {c!r}: {e}")
            finally:
                done.set()

        threading.Thread(target=work, name="bed-zones-send", daemon=True).start()
        return done, problem

    # -- the code --
    def handle(self, key, params, config):
        """Answers the code (always) and returns what was done: "pass", "refused", "set", "reached", "timeout", "fault" or "error"."""
        try:
            return self._handle(key, params, config)
        except Exception as e:  # noqa: BLE001 - the code must be answered whatever happened
            self.log(f"bed zones: error handling {key}: {type(e).__name__}: {e}")
            try:
                self._fail(M("bed_zones_internal_error", e=e))
            except Exception:  # noqa: BLE001 - the connection may be gone; the caller reconnects
                pass
            return "error"

    def _handle(self, key, params, config):
        result = bed_zones.translate(key, params, bed_zones_config.for_logic(config))
        action = result["action"]
        if action == bed_zones.PASS:
            self.conn.ignore_code()
            return "pass"
        if action == bed_zones.ERROR:
            self._fail(M(result["error"], **result["params"]))
            self.note("refused", result["error"])
            return "refused"
        if not result["wait"]:
            self._ok(M("bed_zones_set", n=len(result["codes"])))  # answered first: the sends below must not run inside the callback
            _done, _problem = self._send_in_thread(result["codes"])
            self.note("set", None)
            return "set"
        done, problem = self._send_in_thread(result["codes"])
        if not done.wait(SEND_WAIT_S) or problem:
            self._fail(M("bed_zones_send_failed"))
            self.note("error", "send")
            return "error"
        return self._wait(result["targets"], config)

    def _wait(self, targets, config):
        logic = bed_zones_config.for_logic(config)
        started = self.clock()
        while True:
            temps, faults = zone_readings(self.read_heat(), list(targets))
            p = bed_zones.progress(targets, temps, self.clock() - started, logic, faults)
            state = p["state"]
            if state == bed_zones.REACHED:
                self._ok(M("bed_zones_reached"))
                self.note("reached", None)
                return "reached"
            if state == bed_zones.FAULT:
                self._fail(M("bed_zones_fault", beds=", ".join(str(b) for b in p["fault"])))
                self.note("fault", p["fault"])
                return "fault"
            if state == bed_zones.TIMEOUT:
                self._fail(M("bed_zones_timeout", beds=", ".join(str(b) for b in p["pending"]), seconds=int(logic["timeout_s"])))
                self.note("timeout", p["pending"])
                return "timeout"
            if self.stop.is_set():
                self._fail(M("main_workshopservice_restarting_try_again_few_seconds"))
                return "error"
            self.sleep(POLL_S)


# ---- the connection loop (runs supervised by heartbeats.launch) ----

_state = {"conn": None, "code": None, "stop": threading.Event()}


def release(log=print):
    """Answers the code in progress and closes the connection (shutdown, watchdog, feature turned off)."""
    conn, code = _state["conn"], _state["code"]
    _state["stop"].set()
    if conn is None:
        return
    try:
        if code is not None:
            from dsf.object_model.messages import MessageType
            conn.resolve_code(MessageType.Error, str(M("main_workshopservice_restarting_try_again_few_seconds")))
            _state["code"] = None
    except Exception as e:  # noqa: BLE001
        log(f"bed zones: could not answer the code in progress: {e}")
    try:
        conn.socket.settimeout(0.3)
        for _ in range(20):
            conn.receive_code()
            conn.ignore_code()
    except Exception:  # noqa: BLE001 - nothing more is waiting
        pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    _state["conn"] = None


def run_loop(bridge, log=print):
    from dsf.connections import InterceptConnection, InterceptionMode
    from dsf.object_model.messages import MessageType

    conn, watchdog, wd_stop = None, None, threading.Event()

    def rest(reason):
        nonlocal conn, watchdog
        if conn is not None:
            wd_stop.set()
            release(log)
            conn = None
            log(f"bed zones: interception released ({reason})")
        _state["stop"] = threading.Event()
        heartbeats._info[LABEL]["idle"] = True
        heartbeats._info[LABEL]["detail"] = M("bed_zones_at_rest")
        heartbeats.ok(LABEL)
        time.sleep(REST_S)

    def note(state, detail):
        try:
            bridge.set_status("bedZones", {"state": state, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        except Exception:  # noqa: BLE001 - a status that cannot be published is not worth failing a code
            pass

    while True:
        if not service_modules.process(LABEL):
            rest("its plugin is stopped")
            continue
        config, problem = bed_zones_config.load()
        if problem is not None:
            heartbeats.error(LABEL, M("bed_zones_config_invalid"))
        if not config["enabled"]:
            rest("zones turned off" if problem is None else "configuration not valid")
            continue
        heartbeats._info[LABEL]["idle"] = False
        heartbeats._info[LABEL]["detail"] = ""
        if conn is None:
            try:
                conn = InterceptConnection(InterceptionMode.PRE, filters=FILTERS, timeout=3)
                conn.connect()
                _state["conn"], _state["code"], _state["stop"] = conn, None, threading.Event()
                watchdog = intercept_watchdog.InterceptWatchdog(
                    lambda: release(log), lambda: os._exit(1), log=log, limit_s=config["timeout_s"] + WATCHDOG_MARGIN_S)
                wd_stop = threading.Event()
                threading.Thread(target=watchdog.run, args=(wd_stop,), name="bed-zones-watchdog", daemon=True).start()
                log("bed zones: InterceptConnection connected (Pre, filters: " + ", ".join(FILTERS) + ")")
            except Exception as e:  # noqa: BLE001
                log(f"bed zones: could not connect InterceptConnection ({e}), retrying in 5 s")
                conn = None
                time.sleep(5)
                continue
        try:
            code = conn.receive_code()
            _state["code"] = code
            heartbeats.ok(LABEL)
        except TimeoutError:
            heartbeats.ok(LABEL)
            continue
        except Exception as e:  # noqa: BLE001
            log(f"bed zones: InterceptConnection lost ({e}), reconnecting...")
            heartbeats.error(LABEL, e)
            wd_stop.set()
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn, _state["conn"] = None, None
            continue
        key = f"{code.type.value if hasattr(code.type, 'value') else code.type}{code.majorNumber}"
        watchdog.begin(key)
        handler = Handler(conn, lambda c: bridge.send(c), lambda: machine_state.read_in("heat", default={}),
                          MessageType.Success, MessageType.Error, log=log, stop=_state["stop"], note=note)
        handler.handle(key, params_of(code), config)
        _state["code"] = None
        watchdog.end()
