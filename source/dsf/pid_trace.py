"""The record of a PID tuning (M303): the service samples the heater while the board tunes it, so the chart can be seen from any screen or
session, and the record goes on when nobody has the page open.

ONE listener on the single subscription of machine_state (it never asks DSF for anything): while a heater is in state `tuning` it takes a
point every SAMPLE_S, [seconds since the start, temperature, power 0..1 or null]. Only the last tuning is kept (memory + the file
`pid-trace.json` in the data folder, written atomically every FLUSH_S while it runs and when it ends), so a restart of the service keeps
what was drawn. A tuning that was running when the service went down is closed at the first start (nothing is invented for the gap).

Rests with its plugin: when WorkshopPrinting is stopped or disabled (service_modules.PRINTING) it takes no samples.
Read it with the API operation `pid.trace`.
"""
import fs_atomic
import json
import os
import threading
import time

import heartbeats
import paths
import service_modules
from messages import M

LABEL = "pid_trace"
SAMPLE_S = 1.0
FLUSH_S = 15
MAX_POINTS = 3000          # 50 minutes at one point per second
FILE = os.path.join(paths.DATA_DIR, "pid-trace.json") if hasattr(paths, "DATA_DIR") else "pid-trace.json"
_wake = threading.Event()
_lock = threading.Lock()
_state = {"trace": None, "loaded": False, "dirty": False, "flushed": 0.0}
_hooks = {"now": None, "file": None}


def _epoch():
    return _hooks["now"]() if _hooks["now"] else time.time()


def _file():
    return _hooks["file"] or FILE


def _load():
    """The trace of the file (once). A tuning that was open is closed: the service was down, so it has no more points."""
    if _state["loaded"]:
        return
    _state["loaded"] = True
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            t = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(t, dict) and isinstance(t.get("points"), list):
        if t.get("ended_at") is None:
            last = t["points"][-1][0] if t["points"] else 0
            t["ended_at"] = (t.get("started_at") or 0) + last
        _state["trace"] = t


def _save(force=False):
    """Atomic write of the trace; on failure it is tried again at the next flush."""
    t = _state["trace"]
    if t is None or not (_state["dirty"] or force):
        return
    try:
        fs_atomic.write_json(_file(), t, separators=(",", ":"))
        _state["dirty"] = False
    except OSError:
        pass


def heater_tuning(model):
    """(index, heater) of the first heater in state `tuning`, or (None, None)."""
    hs = ((model or {}).get("heat") or {}).get("heaters") or []
    for i, h in enumerate(hs):
        if isinstance(h, dict) and h.get("state") == "tuning":
            return i, h
    return None, None


def step(model, epoch=None):
    """One sample of the model: starts, extends or closes the trace. Returns True when something changed."""
    epoch = _epoch() if epoch is None else epoch
    with _lock:
        _load()
        t = _state["trace"]
        i, h = heater_tuning(model)
        if h is None:
            if t is not None and t.get("ended_at") is None:
                t["ended_at"] = round(epoch, 1)
                _state["dirty"] = True
                _save()
                return True
            return False
        cur = h.get("current")
        if not isinstance(cur, (int, float)) or isinstance(cur, bool) or cur != cur or cur < -200 or cur >= 1000:
            return False
        if t is None or t.get("ended_at") is not None or t.get("heater") != i:
            active = h.get("active")
            t = {"heater": i, "target": round(float(active), 1) if isinstance(active, (int, float)) and not isinstance(active, bool) and active > 0 else 0,
                 "started_at": round(epoch, 1), "ended_at": None, "points": []}
            _state["trace"] = t
        sec = round(epoch - t["started_at"], 1)
        if t["points"] and sec - t["points"][-1][0] < SAMPLE_S * 0.9:
            return False
        pwm = h.get("avgPwm")
        pwm = round(max(0.0, min(1.0, float(pwm))), 3) if isinstance(pwm, (int, float)) and not isinstance(pwm, bool) and pwm == pwm else None
        t["points"].append([sec, round(float(cur), 1), pwm])
        if len(t["points"]) > MAX_POINTS:
            del t["points"][0]
        _state["dirty"] = True
        if epoch - _state["flushed"] >= FLUSH_S:
            _state["flushed"] = epoch
            _save()
        return True


def get():
    """{"trace": the last record or None, "running": a tuning is being recorded now}. A copy: the caller cannot change the record."""
    with _lock:
        _load()
        t = _state["trace"]
        if t is None:
            return {"trace": None, "running": False}
        return {"trace": dict(t, points=[list(p) for p in t["points"]]), "running": t.get("ended_at") is None}


def reset_for_tests():
    with _lock:
        _state.update(trace=None, loaded=False, dirty=False, flushed=0.0)


def _wait(seconds):
    _wake.wait(seconds)
    _wake.clear()
    time.sleep(0.2)


def run_loop(bridge, config, stop=lambda: False, model_source=None, sleep=None, subscribe=True):
    """The process (heartbeats.launch). The arguments after `stop` are for the tests: model_source() -> model or raises, sleep(seconds)."""
    import machine_state
    model_source = model_source or (lambda: machine_state.get_status(timeout=2))
    sleep = sleep or _wait
    listener = lambda patch, full=False: _wake.set()  # noqa: E731 - fast: it only wakes the loop
    if subscribe:
        machine_state.on_change(listener)
    try:
        while not stop():
            _cycle(model_source, sleep)
    finally:
        with _lock:
            _save(force=True)
        if subscribe:
            machine_state.unsubscribe(listener)


def _cycle(model_source, sleep):
    if not service_modules.is_active(service_modules.PRINTING):
        heartbeats.ok(LABEL)
        heartbeats.detail(LABEL, M("pid_trace_at_rest_printing_plugin_stopped"))
        sleep(3)
        return
    try:
        model = model_source()
    except Exception:  # noqa: BLE001 - no subscription: nothing is recorded in the gap
        heartbeats.ok(LABEL)
        sleep(SAMPLE_S)
        return
    step(model)
    heartbeats.ok(LABEL)
    sleep(SAMPLE_S)
