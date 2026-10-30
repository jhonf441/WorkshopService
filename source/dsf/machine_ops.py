"""Executor of the Machine procedures in the SERVICE, and the operations machine.* (Machine v2, phases 0 to 2; design sections 3-5).

The page asks for a procedure (`machine.run`); the service takes the reservation of the movement, sends the G-code (only the templates of
machine_gcode.py), publishes the progress and writes the result and the audit record. Closing the tab changes nothing: the page asks
`machine.runs` again and re-attaches to the run in progress. Modelled on frame_ops.py (one run at a time, a stop event, the reservation
renewed from the runner thread and released in a `finally`).

Run states:   queued -> running -> done | error | aborted        (running -> stopping when a stop is requested)
  done      the procedure finished
  aborted   stopped on request, or the machine halted / the reservation was lost; the reason is in run["error"]["code"]
  error     the board refused or answered something unreadable, the reservation was refused, or the procedure failed
Whatever the way out, the reservation is released, the probe retracted when the procedure deploys it, the connection closed, and the
end noted in the audit (`machine.run.end`, with run_id and kind) and, for the procedures that record, in the calibration history.

Phase 1 adds the procedures probe.repeat, level.g32 / g30 / measure and mesh.probe (machine_probe.py, machine_level.py, machine_mesh.py: they
register themselves in machine_procedures.py), `Procedure.check` (reasons to refuse before the run starts, from the machine and the profile), and the
operations machine.mesh.* (machine_mesh.py) and machine.config.plan / apply (machine_config.py), which are added to the table by ops() below.
`geometry_send()` is the only other way to the board: the lines of mesh load / clear / taper and the M671 now, from the same closed list.

Phase 2 adds the run kinds safety.check (read only: Procedure(reserves=False, prechecks=False), no reservation, no connection) and homing.verify
(machine_safety.py, machine_limits.py) and the operations of history, report, offsets, limits, try and mark_cross (phase2_ops() below).

Published (plugin data `machine`, codes and numbers only -- the page translates): {"v", "current", "runs": [summary], "updated"}.
"""
import threading
import time

import audit
import capabilities
import identity
import machine_gcode
import machine_procedures as procs
import motion_owner
from messages import M
from workshop_api import MOTION, READ, STOP, Arg, ApiError, Op

ORIGIN = "machine"
STATES = ("queued", "running", "stopping", "done", "error", "aborted")
ACTIVE = ("queued", "running", "stopping")
MAX_RUNS = 20            # finished runs kept in memory
PUBLISHED_RUNS = 5
RESERVE_S = 60
RENEW_S = 20

REFUSALS = {
    "unsupported_kinematics": "machine_refuse_unsupported_kinematics", "no_probe": "machine_refuse_no_probe",
    "not_homed": "machine_refuse_not_homed", "heater_fault": "machine_refuse_heater_fault",
    "no_model": "machine_refuse_no_model",
}

_lock = threading.Lock()
_runs = []                # dicts, oldest first
_active = [None]          # run id of the one in progress
_stop = threading.Event()
_hooks = {"connection": None, "channel": None, "status": None, "model": None, "caps": None, "read": None, "profile": None}  # tests replace them


class Aborted(Exception):
    """The run must end now (not an error): .code says why (stop, machine_halted, reservation_lost)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---- what the runner needs from the outside (replaceable) ----

def open_connection():
    if _hooks["connection"]:
        return _hooks["connection"]()
    from dsf.connections import CommandConnection
    conn = CommandConnection()
    conn.connect()
    return conn


def channel():
    if _hooks["channel"]:
        return _hooks["channel"]()
    import communication
    return communication.channel_jog()


def machine_status():
    return _hooks["status"]() if _hooks["status"] else motion_owner._status()


def model():
    if _hooks["model"]:
        return _hooks["model"]()
    try:
        import machine_state
        return machine_state.get_status(timeout=2) or {}
    except Exception:
        return {}


def _caps():
    if _hooks["caps"]:
        return _hooks["caps"]()
    try:
        import capabilities_io
        return capabilities_io.get()
    except Exception:
        return {}


def read_sd(path):
    """Text of a file of the SD ("0:/sys/bed.g") or None."""
    if _hooks["read"]:
        return _hooks["read"](path)
    import capabilities_io
    return capabilities_io.read_sd_text(path)


def profile_block():
    """The `machine` block of the profile (generic defaults for what the owner did not declare)."""
    import machine_profile
    if _hooks["profile"]:
        return _hooks["profile"]()
    try:
        return machine_profile.load().get("machine") or machine_profile.default_machine()
    except Exception:  # noqa: BLE001
        return machine_profile.default_machine()


def geometry_send(lines):
    """For the operations that change the compensation (mesh load / clear / taper, M671 now): every line is rendered from a template of the
    closed list and sent on a short connection of its own. `lines` = [(template, numbers)]; returns the replies. The caller has already
    asked the movement owner (class geometry)."""
    rendered = [machine_gcode.render(t, **n) for t, n in lines]
    conn = open_connection()
    chan = channel()
    replies = []
    try:
        for line in rendered:
            replies.append(str(conn.perform_simple_code(line, channel=chan, async_exec=False) or ""))
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return replies


# ---- the run ----

def _now():
    return int(time.time())


def _set(run, bridge=None, **kw):
    with _lock:
        run.update(kw)
    publish(bridge)


def _run_id():
    import secrets
    return "r-%d-%s" % (_now(), secrets.token_hex(2))


def summary(run):
    """What is published: codes and numbers, no parameters or results."""
    return {k: run.get(k) for k in ("id", "kind", "state", "user", "step", "total", "phase", "created", "started", "finished", "record_id")} \
        | {"error": (run.get("error") or {}).get("code")}


def view(full=False):
    """{"current", "runs"}: newest first. full=True gives the whole run (parameters, result, error with its message)."""
    with _lock:
        runs = [dict(r) for r in reversed(_runs)]
        current = _active[0]
    if full:
        return {"current": current, "runs": runs}
    return {"v": 1, "current": current, "runs": [summary(r) for r in runs[:PUBLISHED_RUNS]], "updated": _now()}


def publish(bridge):
    if bridge is None:
        return
    try:
        bridge.set_status("machine", view())
    except Exception:
        pass


class RunContext:
    """What a procedure sees. The only way to the board is send()."""

    def __init__(self, bridge, run, conn, chan, token):
        self.bridge, self.run, self.conn, self.chan, self.token = bridge, run, conn, chan, token
        self._renewed = time.monotonic()
        self.partial = False
        self.params = run.get("params") or {}

    def send(self, template, **numbers):
        """Sends one line of the closed list and returns the board's reply (text). ForbiddenCode for anything else."""
        line = machine_gcode.render(template, **numbers)
        if self.conn is None:
            raise procs.ProcedureFailed("no_connection")
        return str(self.conn.perform_simple_code(line, channel=self.chan, async_exec=False) or "")

    def check(self):
        """Call between steps: ends the run (Aborted) on a stop request, a halted machine or a lost reservation; renews the reservation."""
        if _stop.is_set():
            raise Aborted("stop")
        if not self.run.get("reserved"):
            return  # a read-only run (safety.check) moves nothing: a halted machine is no reason to end it, it is what it must report
        if machine_status() in motion_owner.STOPPED:
            raise Aborted("machine_halted")
        if time.monotonic() - self._renewed > RENEW_S:
            r = motion_owner.renew(self.bridge, self.token, RESERVE_S, actor=_actor_of(self.run))
            if not r.get("ok"):
                raise Aborted("reservation_lost")
            self._renewed = time.monotonic()

    def wait(self, seconds):
        """Sleeps up to `seconds`, waking at once on a stop request; checks afterwards."""
        _stop.wait(max(0.0, seconds))
        self.check()

    def progress(self, step, total, phase=""):
        _set(self.run, self.bridge, step=int(step), total=int(total), phase=str(phase))

    def set_result(self, result):
        with _lock:
            self.run["result"] = result

    def use_probe(self, k):
        """Notes which probe the run uses, so the runner retracts the right one at the end."""
        with _lock:
            self.run["probe_index"] = int(k)

    def set_record(self, summary):
        """The small part of the result that goes into the calibration history (a record is limited to a few kB)."""
        with _lock:
            self.run["record_results"] = summary

    def model(self):
        return model()

    def caps(self):
        return _caps()

    def profile(self):
        return profile_block()

    def read(self, path):
        return read_sd(path)


def _actor_of(run):
    return {"device": run.get("device", ""), "user": run.get("user", ""), "role": run.get("role", "")}


def _retract(conn, chan, run, proc):
    """A procedure that deploys the probe leaves it retracted, whatever happened (M402 is in the closed list)."""
    if conn is None or not proc.deploys:
        return
    try:
        idx = run.get("probe_index")
        if idx is None:
            idx = (run.get("params") or {}).get("probe")
        if idx is None:
            return
        idx = int(idx)
        conn.perform_simple_code(machine_gcode.render("probe_retract", index=idx), channel=chan, async_exec=False)
    except Exception:  # noqa: BLE001 - best effort; the run already has its own outcome
        pass


def _outcome(bridge, run, proc):
    """Runs the reserved part. Returns (state, error dict or None, partial). Cleanup is the caller's."""
    res = {"token": None, "conn": None, "chan": None}
    try:
        if _stop.is_set():
            return "aborted", {"code": "stop"}, False, res
        if proc.reserves:
            d = motion_owner.reserve(bridge, ORIGIN, proc.motion, run["kind"], RESERVE_S, actor=_actor_of(run))
            if d.get("decision") != "allow":
                return "error", {"code": "reserved", "message": d.get("reason")}, False, res
            res["token"] = d["token"]
        _set(run, bridge, state="stopping" if _stop.is_set() else "running", started=_now(), reserved=proc.reserves)
        if proc.reserves:
            res["conn"] = open_connection()
            res["chan"] = channel()
        ctx = RunContext(bridge, run, res["conn"], res["chan"], res["token"])
        ctx.check()
        proc.fn(ctx, run["params"])
        return "done", None, ctx.partial, res
    except Aborted as e:
        return "aborted", {"code": e.code}, False, res
    except machine_gcode.ForbiddenCode as e:
        return "error", {"code": "forbidden_code", "detail": e.reason}, False, res
    except procs.ProcedureFailed as e:
        return "error", {"code": e.code}, False, res
    except Exception as e:  # noqa: BLE001 - a run must always end in a state
        return "error", {"code": "failed", "detail": "%s: %s" % (type(e).__name__, e)}, False, res


def _cleanup(bridge, run, proc, res):
    """The reservation is released, the probe retracted and the connection closed, in this order of importance."""
    try:
        _retract(res["conn"], res["chan"], run, proc)
    finally:
        try:
            if res["conn"] is not None:
                res["conn"].close()
        except Exception:  # noqa: BLE001
            pass
        if res["token"]:
            try:
                motion_owner.release(bridge, res["token"], actor=_actor_of(run))
            except Exception:  # noqa: BLE001
                pass


def _record(run, proc, state, partial, log=print):
    """Stores the run in the calibration history when its procedure records. Returns the record id or None."""
    if not proc.records:
        return None
    import machine_store
    mapped = {"done": "partial" if partial else "done", "aborted": "stopped", "error": "error"}[state]
    try:
        fp = machine_store.fingerprint_of(_caps())
        results = run.get("record_results") or run.get("result") or {"error": (run.get("error") or {}).get("code")}
        if run.get("error"):
            results = dict(results, error=run["error"].get("code"))
        for attempt in (results, {"error": (run.get("error") or {}).get("code"), "outcome": results.get("outcome")}):
            try:
                rec = machine_store.make_record(run["kind"], _actor_of(run), run_id=run["id"], machine=fp, inputs=run["params"],
                                                results=attempt, state=mapped)
                return machine_store.append(rec, log=log)["id"]
            except machine_store.StoreError as e:
                if e.code != "too_large":
                    raise
        return None
    except Exception as e:  # noqa: BLE001 - not recording must not hide how the run ended
        log("machine: could not store the record of %s: %s" % (run["id"], e))
        return None


def _run(bridge, run, proc):
    state, err, partial, res = "error", {"code": "failed"}, False, {"token": None, "conn": None, "chan": None}
    try:
        state, err, partial, res = _outcome(bridge, run, proc)
    finally:
        try:
            _cleanup(bridge, run, proc, res)
        finally:
            _finish(bridge, run, proc, state, err, partial)


def _finish(bridge, run, proc, state, err, partial):
    _set(run, bridge, state=state, error=err, finished=_now(), reserved=False)
    try:
        rec_id = _record(run, proc, state, partial)
        if rec_id:
            _set(run, bridge, record_id=rec_id)
        audit.event("machine.run.end", {"run_id": run["id"], "kind": run["kind"], "state": state, "record": rec_id}, _actor_of(run),
                    ok=state == "done", code=(err or {}).get("code", ""), message=(err or {}).get("code", ""))
    finally:
        with _lock:
            _active[0] = None
            while len(_runs) > MAX_RUNS:
                _runs.pop(0)
        publish(bridge)


# ---- pre-checks and start ----

def precheck(om, proc):
    """Code of the first reason the run must not start, or None. Pure: `om` is the object model (a dict)."""
    if not om:
        return "no_model"
    mv = om.get("move") or {}
    kin = str((mv.get("kinematics") or {}).get("name") or "cartesian").lower()
    if kin not in capabilities.SUPPORTED_KINEMATICS:
        return "unsupported_kinematics"
    probes = [p for p in (om.get("sensors") or {}).get("probes") or [] if isinstance(p, dict) and p.get("type") not in (None, 0)]
    if proc.needs_probe and not probes:
        return "no_probe"
    axes = [a for a in mv.get("axes") or [] if isinstance(a, dict) and a.get("visible", True)]
    if proc.needs_homed and axes and not all(a.get("homed") for a in axes):
        return "not_homed"
    heaters = (om.get("heat") or {}).get("heaters") or []
    if any(isinstance(h, dict) and h.get("state") == "fault" for h in heaters):
        return "heater_fault"
    return None


def _confirm_info(reason=None, op="machine.run"):
    try:
        import api_ops
        reg = api_ops._ctx["registry"]
        return reg.confirm_info(reg.ops[op], reason=reason, level=3)
    except Exception:  # noqa: BLE001 - tests without the registry
        return {"level": 3, "key": op, "reason": reason}


def _gate(bridge, proc, ctx):
    """The movement owner's answer, as an ApiError the page understands (deny / confirm), like api_ops.motion_check."""
    d = motion_owner.evaluate(bridge, proc.motion, ORIGIN, confirm=bool(ctx.get("confirm")), actor=identity.actor(ctx))
    if d["decision"] == "deny":
        raise ApiError("motion_denied", d["reason"], motion={"decision": "deny", "code": d["code"], "reason": d["reason"]})
    if d["decision"] == "confirm":
        raise ApiError("confirm_required", d["reason"], confirm=_confirm_info(d["reason"]), motion={"decision": "confirm", "code": d["code"]})


def start(bridge, kind, params, ctx):
    """machine.run: validates, checks, creates the run and starts its thread. Returns {"run_id", "kind", "state"}."""
    try:
        proc = procs.get(kind)
    except procs.UnknownKind:
        raise ApiError("invalid_args", M("machine_run_unknown_kind", kind=kind), field="kind")
    except procs.NotImplementedKind:
        raise ApiError("not_implemented", M("machine_run_not_implemented", kind=kind), field="kind")
    try:
        clean = proc.validate(params if isinstance(params, dict) else {})
    except procs.BadParams as e:
        raise ApiError("invalid_args", M("machine_run_bad_param", field=e.field), field="params." + e.field)
    if _active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=_active[0])
    om = model()
    code = precheck(om, proc) if proc.prechecks else None
    if code:
        raise ApiError("refused", M(REFUSALS[code]), reason=code)
    code = proc.check(clean, {"om": om, "caps": _caps(), "profile": profile_block(), "read": read_sd}) if proc.check else None
    if code:
        raise ApiError("refused", M(procs.REFUSAL_KEYS.get(code, "machine_refuse_procedure"), reason=code), reason=code)
    if proc.needs_confirm and not ctx.get("confirm"):
        raise ApiError("confirm_required", "this procedure needs a confirmation", confirm=_confirm_info())
    if proc.reserves:
        _gate(bridge, proc, ctx)
    who = identity.actor(ctx)
    user, role = audit.actor(ctx)
    run = {"id": _run_id(), "kind": kind, "state": "queued", "params": clean, "user": who["user"] or user, "role": who["role"] or role,
           "device": who["device"], "created": _now(), "started": None, "finished": None, "step": 0, "total": 0, "phase": "",
           "result": None, "error": None, "reserved": False, "record_id": None}
    with _lock:
        if _active[0]:
            raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=_active[0])
        _active[0] = run["id"]
        _runs.append(run)
    _stop.clear()
    publish(bridge)
    threading.Thread(target=_run, args=(bridge, run, proc), name="machine-" + kind, daemon=True).start()
    return {"run_id": run["id"], "kind": kind, "state": "queued"}


def stop():
    """machine.stop: never refused. The run ends at its next check (the short step in progress finishes); it does NOT send M112."""
    _stop.set()
    with _lock:
        rid = _active[0]
        run = next((r for r in _runs if r["id"] == rid), None)
        if run and run["state"] in ("queued", "running"):
            run["state"] = "stopping"
    return {"ok": True, "active": bool(rid), "run_id": rid}


def wait_idle(seconds=5.0):
    """For tests and the shutdown: waits until no run is in progress."""
    end = time.monotonic() + seconds
    while _active[0] and time.monotonic() < end:
        time.sleep(0.01)
    return not _active[0]


def reset():
    """For the tests."""
    wait_idle(2.0)
    with _lock:
        _runs.clear()
        _active[0] = None
    _stop.clear()
    for k in _hooks:
        _hooks[k] = None


# ---- operations ----

def _bridge():
    import api_ops
    return api_ops._ctx["bridge"]


def _overview(args, ctx):
    import machine_overview
    return machine_overview.overview()


def _state(args, ctx):
    import machine_overview
    return machine_overview.state()


def _runs_op(args, ctx):
    v = view(full=True)
    if args.get("run_id"):
        v["runs"] = [r for r in v["runs"] if r["id"] == args["run_id"]]
    return v


def _run_op(args, ctx):
    return start(_bridge(), args["kind"], args.get("params"), ctx)


def _stop_op(args, ctx):
    return stop()


def ops():
    import machine_config
    import machine_mesh
    S, O = "str", "obj"
    a = Arg
    return [
        Op("machine.overview", _overview, READ, {},
           "Summary of the calibration state for every role: per kind of calibration its traffic light (never / ok / old) and age in days, "
           "what the machine is ready for (homed, probe, mesh active, kinematics supported, levelling mode) and whether a procedure is running. "
           "No values of offsets or limits.", log=False),
        Op("machine.state", _state, READ, {},
           "Full state for the Machine page: the overview, the modules that are available (or hidden with the reason), the procedure runs, "
           "the newest calibration records with their values, the maintenance state and the machine block of the profile.", log=False),
        Op("machine.runs", _runs_op, READ,
           {"run_id": a(S, desc="Only this run (to re-attach after the page was reloaded).")},
           "The procedures started by machine.run: the one in progress (current) and the last finished ones, newest first, with state "
           "(queued, running, stopping, done, error, aborted), progress, result and error code.", log=False),
        Op("machine.run", _run_op, MOTION,
           {"kind": a(S, True, desc="Procedure: " + ", ".join(procs.kinds()["implemented"]) + ". The others of the design answer "
                                      "not_implemented: " + ", ".join(procs.kinds()["planned"]) + "."),
            "params": a(O, desc="Parameters of the procedure. probe.read: probe 0-15, samples 1-20, interval_s 0-5. probe.repeat: probe, "
                                "samples 2-100, x and y (where the probe touches), deploy_each. level.g32 / level.g30 / level.measure: probe, "
                                "passes, tolerance, points [{x, y}], verify, rehome_z. mesh.probe: probe, nx, ny, region {x0, x1, y0, y1}, "
                                "margin, run_g32, name, save. homing.verify: axes (letters), tolerance 0.001-2 mm (needs confirm). safety.check: none. "
                                "shaping.tune (needs an accelerometer, refused with no_accelerometer): axis, accelerometer, samples, travel, start, feed, cycles (needs confirm).")},
           "Starts a calibration procedure IN THE SERVICE: it reserves the movement (denied with a job, a live job, the bridge active or "
           "somebody else holding it), sends only the G-code of a closed list, publishes the progress (plugin data machine, or machine.runs) "
           "and stores the result and the audit record. Answers {run_id, kind, state} at once; one procedure at a time. "
           "The refusal reasons are in error.reason (no_probe, not_homed, unsupported_kinematics, heater_fault, busy_run).",
           exclusive=False),
        Op("machine.stop", _stop_op, STOP, {},
           "Stops the procedure in progress (never refused, any role, no login): it ends at its next step, retracts the probe if it was "
           "deployed and releases the movement. It does NOT send M112 (the emergency stop stays the DWC / Jog function).", exclusive=False),
    ] + machine_mesh.ops() + machine_config.ops() + phase2_ops()


def phase2_ops():
    """Phase 2: history, report, offsets, limits, try, mark_cross (each module builds its own operations)."""
    import machine_cross
    import machine_height
    import machine_history
    import machine_layout
    import machine_limits
    import machine_offsets
    import machine_report
    import machine_try
    import machine_workarea
    return machine_history.ops() + machine_report.ops() + machine_offsets.ops() + machine_limits.ops() + machine_layout.ops() + machine_try.ops() + machine_cross.ops() + machine_height.ops() + machine_workarea.ops() + phase3_ops()


def phase3_ops():
    """Phase 3: calibration arithmetic, motion parameters, input shaping."""
    import machine_calc
    import machine_motion
    import machine_shaping
    return machine_calc.ops() + machine_motion.ops() + machine_shaping.ops() + phase4_ops()


def phase4_ops():
    """Phase 4: maintenance counters, plan and notices (the camera verification is the run kind offsets.verify)."""
    import machine_maintenance
    return machine_maintenance.ops()
