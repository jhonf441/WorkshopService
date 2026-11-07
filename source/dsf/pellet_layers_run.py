"""Pellet layers, the part that touches the world: the armed run, the thread that reads the object model and sends the code.

The decisions are pellet_layers.py (pure). Here: who armed what (in memory, never saved: a restart disarms), reading the single DSF
subscription, sending `M568 P<tool> S...` through the bridge, and recording every change (activity -> black box, audit). Never raises out of
the loop. Design: informes/pellet-temperatura-por-capa/DISENO.md.
"""
import re
import threading
import time

import audit
import heartbeats
import pellet_layers as pl
import settings_store
from messages import M

LABEL = "pellet_layers"
KEY_STATE = "pelletLayers"
POLL_S = 2

_lock = threading.RLock()
_state = {"run": None, "last": None, "tables": {}}


def _is_error(answer):
    return bool(re.search(r"error|abort", str(answer or ""), re.I))


def load_store():
    """The saved profiles {"profiles": {name: profile}}. A damaged file raises pl.ProfileError (nothing is armed from it)."""
    return pl.validate_store(settings_store.get(pl.AREA)["value"])


def arm(name, file, who, now=None):
    """Arms the profile `name` for the job whose file is `file`. Raises LookupError (no such profile), ValueError (a Msg) otherwise."""
    now = time.time() if now is None else now
    if not isinstance(file, str) or not file.strip():
        raise ValueError(M("pellet_layers_err_file"))
    profiles = load_store()["profiles"]
    if name not in profiles:
        raise LookupError(name)
    with _lock:
        cur = _state["run"]
        if cur is not None and not cur.ended:
            raise ValueError(M("pellet_layers_err_already_armed", profile=cur.name))
        _state["run"] = pl.Run(name, profiles[name], file.strip(), now, who)
        _state["last"] = None
    return status()


def armed_profile():
    with _lock:
        run = _state["run"]
        return run.name if run is not None and not run.ended else None


def disarm(who=None, record=None):
    """The person's stop: ends the run and leaves the temperatures as they are."""
    with _lock:
        run = _state["run"]
        if run is None or run.ended:
            return status()
        events = run.disarm()
        _state["last"] = run.view()
    for e in events:
        _record_disarm(run, e, record)
    return status()


def status():
    with _lock:
        run = _state["run"]
        view = run.view() if run is not None else _state["last"]
    if view is None:
        return {"armed": False, "phase": "off", "profile": None, "file": None, "layer": None, "applied": None, "next": None,
                "changes": 0, "reason": None}
    return view


def _who(run):
    return run.armed_by if run is not None else {}


def _record_apply(run, e, record):
    text = M("pellet_layers_applied", layer=e["layer"], temps=" / ".join(pl._fmt(t) for t in e["temps"]), code=e["code"])
    try:
        record("config", text)  # activity.log_event: history, black box
    except Exception:  # noqa: BLE001 - a record that fails must not undo or repeat a change already made
        pass
    audit.event("pelletlayers.apply", {"profile": run.name, "layer": e["layer"], "code": e["code"], "limited": ",".join(e["notes"])},
                _who(run))


def _record_disarm(run, e, record):
    text = M(e["reason"], **e["params"])
    kind = "error" if e["warn"] else "config"
    try:
        record(kind, M("pellet_layers_disarmed", profile=run.name, reason=text))
    except Exception:  # noqa: BLE001
        pass
    audit.event("pelletlayers.disarm", {"profile": run.name, "reason": e["reason"]}, _who(run), ok=not e["warn"], code=e["reason"],
                message=str(text))


def _layer_table(file):
    """Heights of the layers of the job file (the plan of gcode_plan.py), built once per file. None when it cannot be read."""
    cache = _state["tables"]
    if file in cache:
        return cache[file]
    table = None
    try:
        import gcode_plan
        import sd_paths
        stats = {}
        gcode_plan.arm(sd_paths.sd(file), "FFF", {"move": {}}, stats=stats)
        table = stats.get("layer_z") or None
    except Exception:  # noqa: BLE001 - no table: the layer comes from job.layer or the run waits
        table = None
    if len(cache) > 3:
        cache.clear()
    cache[file] = table
    return table


def tick(status_model, send, record, now=None, table=None):
    """One pass. send(code) -> answer text (raises on a failed send); record(kind, message). Returns the events it handled."""
    now = time.time() if now is None else now
    with _lock:
        run = _state["run"]
        if run is None or run.ended:
            return []
        snap = pl.snapshot(status_model)
        if snap["file"] == run.file and (run.profile["axis"] == "z" or snap["layer"] is None):
            snap["layer_z"] = (table or _layer_table)(run.file)
        events = run.step(snap, now)
        handled = []
        for e in events:
            if e["type"] == "apply":
                try:
                    answer = send(e["code"])
                except Exception as ex:  # noqa: BLE001 - a send that fails is a rejection: stop, say so
                    answer = "error: %s" % ex
                if _is_error(answer):
                    for d in run.rejected(answer):
                        _record_disarm(run, d, record)
                        handled.append(d)
                    break
                run.commit(e, now)
                _record_apply(run, e, record)
            elif e["type"] == "note":
                try:
                    record("config", M(e["key"], **e["params"]))
                except Exception:  # noqa: BLE001
                    pass
            elif e["type"] == "disarm":
                _record_disarm(run, e, record)
            handled.append(e)
        if run.ended:
            _state["last"] = run.view()
        return handled


def run_loop(bridge, config):
    import activity
    import machine_state
    import service_modules

    def send(code):
        return bridge.send(code)

    def record(kind, text):
        activity.log_event(bridge, kind, text)

    while True:
        try:
            if not service_modules.is_active(service_modules.PRINTING):
                heartbeats.ok(LABEL)
                heartbeats.detail(LABEL, M("pellet_layers_at_rest_printing_plugin_stopped"))
                time.sleep(3)
                continue
            model = machine_state.get_status(timeout=2)
            tick(model, send, record)
            try:
                import messages
                bridge.set_status(KEY_STATE, messages.data(status()))
            except Exception:  # noqa: BLE001 - the page can also ask pelletlayers.status
                pass
            heartbeats.ok(LABEL)
        except Exception as e:  # noqa: BLE001 - one bad pass must not kill the thread
            heartbeats.error(LABEL, e)
        time.sleep(POLL_S)
