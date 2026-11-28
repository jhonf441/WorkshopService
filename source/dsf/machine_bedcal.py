"""Bed zones calibration, the part that heats: the procedures `bedcal.preheat` and `bedcal.tune` of machine.run.

They run INSIDE machine_ops.py, so they inherit what every Machine procedure has: one procedure at a time (`busy_run`, which machine.config.apply
also refuses), the reservation of the movement of class "sequence" (denied with a job, a paused job, a live job or the bridge active), the
role (technician) and the delegable capability `machine.procedures`, the closed list of G-code (`ctx.send(template, **numbers)`: machine_gcode.py),
`machine.stop`, and the audit row at the end. The plan (what is sent, every temperature bounded) is machine_bedcal_plan.py; the operations that
start them are bed_calibration_ops.py (`bedcal.preheat`, `bedcal.tune`, `bedcal.stop`, `bedcal.status`).

HEATERS ARE NEVER LEFT ON. Every way out of a procedure runs `_all_off()`: success (a preheat holds the zones hot for `hold_min` minutes so the person
can measure, then turns them off), Stop (ctx.wait wakes at once), a refusal of the board, a heater in fault, a job that started, a cap reached, an
unexpected error. If the turn-off through the connection fails it is tried again through the bridge. If the service itself stops (`atexit`) the zones of the
run in progress are turned off with the same connection. The zones are the ones of the plan only.

Sequence of a tuning (the same as handlers/pid_zones.py does for the zones of a tool, with M140 instead of M568): the tuned zone is turned off and has to
be cold (MARGIN_COLD under the target: RRF refuses M303 otherwise) while the neighbours are held at the working temperature (`together`) or off;
then `M303 H<h> S<t>`; when the heater leaves the `tuning` state `M303` reports the result and `M307 H<h>` reads the model, which is taken from the
object model (the numbers of the line). The chart of the tuning is pid_trace.py (it samples any heater in `tuning`, whoever started it).

Progress: `ctx.progress` (step, total, phase) and `ctx.set_result` after every poll (zones with their temperature and state): machine.runs and
bedcal.status read it. All the waits go through `ctx.wait`, so a test with a fake context drives the whole run without a clock.
"""
import atexit
import copy
import json
import os
import time

import fs_atomic
import machine_bedcal_plan as plan
import machine_gcode
import paths
from messages import M

POLL_S = 1.0
REACH_MAX_S = 30 * 60        # a preheat that has not arrived by then is turned off
WAIT_MAX_S = 30 * 60         # neighbours to temperature + the tuned zone to cool, per zone
STILL_WINDOW_S = 60          # the readings that decide "still" are the ones of this last window
STILL_MIN_S = 30             # ... and they must cover at least this long (the first minute is no longer waited blindly)
STILL_SPAN = 1.5
SERIES_EVERY_S = 3           # the chart before the M303 (preparing and waiting): one point of every zone this often
SERIES_MAX = 720
STUCK_S = 180                # still but too hot for that long: it will not drop
CALIBRATES_MAX_S = 60 * 60   # one M303
TOTAL_MAX_S = 6 * 3600
UNSEEN_S = 15                # an M303 that never shows `tuning` after this long was refused or already over
MISS_MAX = 60                # polls in a row without a model
JOB = ("processing", "simulating", "pausing", "paused", "resuming", "cancelling")
STOP = ("halted", "off", "disconnected", "updating", "starting")
RISK_ID = "bedcal_tune"
RISK_PREHEAT_ID = "bedcal_preheat"
LIVE_FILE = os.path.join(paths.DATA_DIR, "bedcal-live.json")   # the zones a run has hot: written at the start, removed when they are off

# What machine_procedures.py hands over when it registers the procedures (register() below): its exception classes and risk_rules. This file imports
# neither of them, so it stays out of the import cycle of the machine modules.
_p = {"procs": None, "risk": None}
_live = {"ctx": None, "beds": []}   # the run that has zones hot, for the exit of the service


class _SkipZone(Exception):
    """This zone could not be tuned; .code says why; the next one goes on."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---- validation and refusal (the parts machine_ops asks for) ----

def _fail(code):
    return _p["procs"].ProcedureFailed(code)


def _bad(field):
    return _p["procs"].BadParams(field)


def _validated(builder):
    def validate(params):
        try:
            return builder(params)
        except plan.Refused as e:
            raise _bad(str(e.params.get("field", "params")))
    return validate


def _preheat_params(params):
    plan.only(params, ("beds", "temp", "stagger_s", "hold_min"))
    return {"beds": plan.clean_beds(params.get("beds")), "temp": plan.clean_temp(params.get("temp")),
            "stagger_s": plan.bounded("stagger_s", params.get("stagger_s", 30), *plan.STAGGER_RANGE),
            "hold_min": plan.bounded("hold_min", params.get("hold_min", plan.DEFAULT_HOLD_MIN), *plan.HOLD_RANGE)}


def _tune_params(params):
    plan.only(params, ("beds", "temp", "together", "only"))
    together = params.get("together", True)
    if not isinstance(together, bool):
        raise plan.Refused("bad_param", field="together")
    out = {"beds": plan.clean_beds(params.get("beds")), "temp": plan.clean_temp(params.get("temp")), "together": together}
    if params.get("only") is not None:
        out["only"] = plan.clean_beds(params["only"])
    return out


def _check(planner):
    def check(params, env):
        try:
            planner(env["om"], plan.read_settings(env["read"](plan.SETTINGS_PATH)), params)
        except plan.Refused as e:
            return "bedcal_" + e.code
        return None
    return check


# ---- the zones that are hot (the file a restart reads) ----

def _live_write(beds):
    """The zones this run turns on, kept in a file so a service that dies (killed, power cut) can turn them off at its next start. Never raises."""
    try:
        fs_atomic.write_json(LIVE_FILE, {"beds": list(beds), "since": int(time.time())})
    except Exception:  # noqa: BLE001 - the run goes on: the turn-off at its end does not depend on this file
        pass


def _live_clear():
    try:
        os.remove(LIVE_FILE)
    except OSError:
        pass


def _off_beds(ctx, beds):
    """Turns the zones off through the connection of the run and, when that fails, through the bridge. Returns the list of {bed, error} that stayed on."""
    errors = []
    for bed in beds:
        first = ""
        try:
            ctx.send("bed_off", bed=bed)
            continue
        except Exception as e:  # noqa: BLE001 - the next route is tried
            first = str(e)[:80]
        try:
            ctx.bridge.send(machine_gcode.render("bed_off", bed=bed))
        except Exception as e:  # noqa: BLE001 - reported in the result: the person is told it may still be on
            errors.append({"bed": bed, "error": first + " / " + str(e)[:80]})
    return errors


def sweep_at_start(send, log):
    """At the start of the service: zones a run left hot (the service died with it) are turned off, once, and the person is told.
    `send` takes one line of G-code (the bridge); `log` takes a message. The file stays when a line fails, so the next start tries again."""
    try:
        with open(LIVE_FILE, encoding="utf-8") as f:
            beds = [int(b) for b in (json.load(f).get("beds") or [])]
    except (OSError, ValueError, TypeError):
        return False
    failed = []
    for bed in beds:
        try:
            send(machine_gcode.render("bed_off", bed=bed))
        except Exception as e:  # noqa: BLE001
            failed.append(bed)
    if failed:
        return False
    _live_clear()
    log(M("bedcal_swept_at_start", beds=", ".join(str(b) for b in beds)))
    return True


# ---- the live state of a run ----

class _Run:
    """What a run keeps: the plan, the result the page reads, the elapsed seconds (the sum of its waits) and the misses of the model."""

    def __init__(self, ctx, p):
        self.ctx, self.p, self.t, self.misses, self.step = ctx, p, 0.0, 0, 0
        self._series_at = -SERIES_EVERY_S
        self.result = {"kind": p["kind"], "phase": "preparing", "temp": p["temp"], "elapsed_s": 0, "off": False, "off_errors": [], "series": [],
                       "zones": [{"bed": z["bed"], "heater": z["heater"], "target": z["target"], "current": None, "state": None, "result": "pending",
                                  "error": None, "model": None, "model_line": None, "wait": None} for z in p["zones"]]}
        for z, rz in zip(p["zones"], self.result["zones"]):
            if z.get("tune") is False:
                rz["result"] = "held"
        _live["ctx"], _live["beds"] = ctx, [z["bed"] for z in p["zones"]]
        _live_write(_live["beds"])

    def publish(self, phase=None, step=None):
        if phase:
            self.result["phase"] = phase
        self.result["elapsed_s"] = int(self.t)
        self.sample()
        self.ctx.set_result(copy.deepcopy(self.result))
        if step is not None:
            self.step = step
        if step is not None or phase:
            self.ctx.progress(self.step, sum(1 for z in self.p["zones"] if z.get("tune", True)), self.result["phase"])

    def wait(self, seconds):
        """The elapsed time is the clock's: a wait that lasted longer than asked (a slow board) counts what it lasted. A test context that returns at once counts the nominal seconds."""
        before = time.monotonic()
        self.ctx.wait(seconds)
        self.t += max(float(seconds), time.monotonic() - before)

    def sample(self):
        """One point of every zone for the chart before the tuning starts (the chart of the tuning itself is pid_trace.py): every SERIES_EVERY_S, at most SERIES_MAX points."""
        if self.t - self._series_at < SERIES_EVERY_S:
            return
        self._series_at = self.t
        series = self.result["series"]
        series.append([int(self.t)] + [z["current"] for z in self.result["zones"]])
        if len(series) > SERIES_MAX:
            del series[:len(series) - SERIES_MAX]

    def read(self):
        """The object model now; the zones' readings are updated. Raises ProcedureFailed no_model after MISS_MAX polls without one."""
        om = self.ctx.model()
        if not om:
            self.misses += 1
            if self.misses >= MISS_MAX:
                raise _fail("no_model")
            return None
        self.misses = 0
        for z in self.result["zones"]:
            cur, st, _ = plan.reading(om, z["heater"])
            z["current"] = round(cur, 1) if cur is not None else None
            z["state"] = st
        return om

    def zone(self, bed):
        return next(z for z in self.result["zones"] if z["bed"] == bed)

    def watch(self, om, expect_on=(), limit=TOTAL_MAX_S):
        """The checks of every poll; raises ProcedureFailed. expect_on = beds that must be on (a neighbour someone turned off ends the run)."""
        if self.t > limit:
            raise _fail("too_long")
        if om is None:
            return
        status = str(((om.get("state") or {}).get("status")) or "").lower()
        if status in JOB:
            raise _fail("job_started")
        if status in STOP:
            raise _fail("board_stopped")
        for z, pz in zip(self.result["zones"], self.p["zones"]):
            cur, st, cap = plan.reading(om, z["heater"])
            if st == "fault":
                raise _fail("heater_fault")
            if cur is None:
                continue
            if cap is not None and cur >= cap:
                raise _fail("over_cap")
            if cur > pz["target"] + plan.OVER_TARGET:
                raise _fail("over_target")
            if z["bed"] in expect_on and st == "off":
                raise _fail("heaters_turned_off")


def _all_off(run):
    """Every zone of the plan off. Through the connection of the run; when that fails, through the bridge. Never raises."""
    errors = _off_beds(run.ctx, [z["bed"] for z in run.p["zones"]])
    if not errors:
        _live_clear()
    run.result["off"] = not errors
    run.result["off_errors"] = errors
    _live["ctx"], _live["beds"] = None, []
    for z in run.result["zones"]:
        if z["state"] != "fault":
            z["state"] = "off" if not errors else z["state"]
    try:
        run.publish()
    except Exception:  # noqa: BLE001
        pass


def _mark_cut(run):
    for z in run.result["zones"]:
        if z["result"] in ("pending", "in_progress", "heating"):
            z["result"] = "cut"


def turn_off_live():
    """The service is stopping with a run that has zones on: they are turned off with the connection of the run and, when that fails, through the bridge.
    Called by the clean stop (after the run was asked to stop) and at exit. The file of hot zones is removed only when all of them are off."""
    ctx, beds = _live["ctx"], list(_live["beds"])
    if ctx is None or not beds:
        return True
    errors = _off_beds(ctx, beds)
    if not errors:
        _live_clear()
        _live["ctx"], _live["beds"] = None, []
    return not errors


atexit.register(turn_off_live)


def _start(ctx, planner, params):
    """Plans again with the model of THIS moment (the plan of the page is not trusted) and turns Refused into a failure of the run."""
    try:
        p = planner(ctx.model(), plan.read_settings(ctx.read(plan.SETTINGS_PATH)), params)
    except plan.Refused as e:
        raise _fail("bedcal_" + e.code)
    return _Run(ctx, p)


# ---- the preheat ----

def _arrived(run):
    return all(z["current"] is not None and z["current"] >= z["target"] - run.p["tolerance"] for z in run.result["zones"])


def run_preheat(ctx, params):
    run = _start(ctx, plan.plan_preheat, params)
    try:
        n = len(run.p["zones"])
        risk = M("bedcal_risk_preheat_one", temp=int(run.p["temp"])) if n == 1 else M("bedcal_risk_preheat", zones=n, temp=int(run.p["temp"]))
        _p["risk"].launch(RISK_PREHEAT_ID, risk, REACH_MAX_S + run.p["hold_s"] + n * run.p["stagger_s"] + 120)
        run.publish("staggering", 0)
        for k, z in enumerate(run.p["zones"]):
            if k > 0 and run.p["stagger_s"]:
                _wait_watching(run, run.p["stagger_s"])
            ctx.send("bed_set", bed=z["bed"], set_temp=z["target"])
            run.zone(z["bed"])["result"] = "heating"
            run.publish("staggering", k + 1)
        t0 = run.t
        run.publish("reaching")
        while True:
            run.watch(run.read())
            if _arrived(run):
                break
            if run.t - t0 >= REACH_MAX_S:
                raise _fail("not_reached")
            run.publish()
            run.wait(POLL_S)
        for z in run.result["zones"]:
            z["result"] = "reached"
        run.publish("holding")
        _wait_watching(run, run.p["hold_s"], publish_every=5)
    except Exception:
        _mark_cut(run)
        raise
    finally:
        _p["risk"].finish(RISK_PREHEAT_ID)
        _all_off(run)
    run.publish("finished")


def _wait_watching(run, seconds, publish_every=0):
    """Waits `seconds` in polls of POLL_S, reading and watching the heaters at each one."""
    left, n = float(seconds), 0
    while left > 0:
        step = min(POLL_S, left)
        run.watch(run.read())
        n += 1
        if publish_every and n % publish_every == 0:
            run.result["hold_left_s"] = int(left)
            run.publish()
        run.wait(step)
        left -= step


# ---- the tuning ----

def _send_prepare(run, i):
    """The lines that put the zones as the tuning of zone i needs: the tuned one off, the others at the working temperature or off."""
    p, z = run.p, run.p["zones"][i]
    for o in p["zones"]:
        if o is z or not p["together"]:
            run.ctx.send("bed_off", bed=o["bed"])
        else:
            run.ctx.send("bed_set", bed=o["bed"], set_temp=p["temp"])


def _wait_detail(run, expect, cur, cold_limit, hist, stuck):
    """What the zone is waiting for, so the page can say it: the neighbours (bed, now, goal), the tuned zone (now, the limit it must go under),
    how long it has been still and how long it needs, how long it has been stuck."""
    p = run.p
    still_s = int(run.t - hist[0][0]) if hist and max(h[1] for h in hist) - min(h[1] for h in hist) <= STILL_SPAN else 0
    return {"neighbours": [[b, run.zone(b)["current"], p["temp"]] for b in expect], "zone_current": cur, "cold_limit": cold_limit,
            "still_s": min(still_s, STILL_MIN_S), "still_need_s": STILL_MIN_S if expect else 0,
            "stuck_s": int(run.t - stuck) if stuck is not None else 0, "stuck_max_s": STUCK_S}


def _wait_ready(run, i):
    """Neighbours at temperature (together) and the tuned zone cold and still. _SkipZone when it will not drop, ProcedureFailed when the neighbours never arrive.
    Still is asked only when there are neighbours held hot (alone, a cold zone is ready at once) and it needs STILL_MIN_S of readings, not a fixed minute."""
    p, z, bed = run.p, run.p["zones"][i], run.p["zones"][i]["bed"]
    expect = [o["bed"] for o in p["zones"] if o is not z and p["together"]]
    hist, stuck, t0 = [], None, run.t
    cold_limit = p["temp"] - plan.MARGIN_COLD
    while True:
        om = run.read()
        waited = run.t - t0
        run.watch(om, expect_on=expect if waited > 30 else ())
        cur = run.zone(bed)["current"]
        near = all(run.zone(b)["current"] is not None and abs(run.zone(b)["current"] - p["temp"]) <= p["tolerance"] for b in expect)
        if cur is not None:
            hist = [h for h in hist if run.t - h[0] <= STILL_WINDOW_S] + [(run.t, cur)]
        still = bool(hist) and run.t - hist[0][0] >= STILL_MIN_S and max(h[1] for h in hist) - min(h[1] for h in hist) <= STILL_SPAN
        cold = cur is not None and cur <= cold_limit
        run.zone(bed)["wait"] = _wait_detail(run, expect, cur, cold_limit, hist, stuck)
        if near and cold and (still or not expect):
            run.zone(bed)["wait"] = None
            return
        if expect and near and still and not cold:
            stuck = run.t if stuck is None else stuck
            if run.t - stuck >= STUCK_S:
                run.zone(bed)["wait"] = None
                raise _SkipZone("not_cold")
        else:
            stuck = None
        if waited >= WAIT_MAX_S:
            run.zone(bed)["wait"] = None
            if not near:
                raise _fail("neighbours_not_ready")
            raise _SkipZone("not_cold")
        run.publish()
        run.wait(POLL_S)


def _is_error(reply):
    t = str(reply or "").lower()
    return "error" in t or "abort" in t


def _send_zone(run, template, **numbers):
    """A line of the tuning of one zone: a failure of the connection skips THIS zone (the next one goes on, and `watch` still ends the run for what is serious).
    The refusals of the service itself (a code not in the list, a run that must end) go through."""
    try:
        return run.ctx.send(template, **numbers)
    except (machine_gcode.ForbiddenCode, _p["procs"].ProcedureFailed, _p["procs"].BadParams):
        raise
    except Exception as e:  # noqa: BLE001
        raise _SkipZone("send_failed") from e


def _tune_one(run, i):
    p, z = run.p, run.p["zones"][i]
    res = run.zone(z["bed"])
    reply = _send_zone(run, "heater_tune", heater=z["heater"], tune_temp=z["target"])
    if _is_error(reply):
        raise _SkipZone("rejected")
    seen, t0 = False, run.t
    expect = [o["bed"] for o in p["zones"] if o is not z and p["together"]]
    while True:
        om = run.read()
        run.watch(om, expect_on=expect)
        st = res["state"]
        if st == "tuning":
            seen = True
        elif om is not None and (seen or run.t - t0 > UNSEEN_S):
            break
        if run.t - t0 > CALIBRATES_MAX_S:
            raise _fail("tune_timeout")
        run.publish()
        run.wait(POLL_S)
    run.wait(1.5)
    if not plan.tune_succeeded(_send_zone(run, "tune_report")):
        raise _SkipZone("tune_failed")
    _send_zone(run, "heater_model", heater=z["heater"])
    run.wait(1.0)
    md = plan.model_of(run.read() or run.ctx.model(), z["heater"])
    if md is None:
        raise _SkipZone("no_model")
    res["model"], res["model_line"], res["result"] = md, plan.model_line(z["heater"], md), "ok"


def run_tune(ctx, params):
    run = _start(ctx, plan.plan_tune, params)
    try:
        n = len(run.p["zones"])
        risk = M("bedcal_risk_tuning_one", temp=int(run.p["temp"])) if n == 1 else M("bedcal_risk_tuning", zones=n, temp=int(run.p["temp"]))
        _p["risk"].launch(RISK_ID, risk, TOTAL_MAX_S + 120)
        todo = [i for i, z in enumerate(run.p["zones"]) if z["tune"]]
        for n, i in enumerate(todo):
            z = run.p["zones"][i]
            res = run.zone(z["bed"])
            res["result"] = "in_progress"
            run.publish("preparing", n)
            try:
                _send_prepare(run, i)
                run.publish("waiting", n)
                _wait_ready(run, i)
                run.publish("tuning", n)
                _tune_one(run, i)
            except _SkipZone as e:
                res["result"], res["error"] = "failure", e.code
        run.publish("finished", len(todo))
    except Exception:
        _mark_cut(run)
        raise
    finally:
        _p["risk"].finish(RISK_ID)
        _all_off(run)


def register(procs, risk_rules):
    """Called by machine_procedures.py after its classes exist: registers the two procedures (machine.run needs nothing else from here)."""
    _p["procs"], _p["risk"] = procs, risk_rules
    procs.REFUSAL_KEYS.update({"bedcal_" + c: "bedcal_refuse_" + c for c in plan.REFUSALS})
    procs.register(procs.Procedure("bedcal.preheat", run_preheat, _validated(_preheat_params), motion="sequence", needs_confirm=True, records=False,
                                   prechecks=False, check=_check(plan.plan_preheat)))
    procs.register(procs.Procedure("bedcal.tune", run_tune, _validated(_tune_params), motion="sequence", needs_confirm=True, records=False,
                                   prechecks=False, check=_check(plan.plan_tune)))
