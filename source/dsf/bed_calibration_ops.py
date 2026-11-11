"""API operations of the bed zones calibration assistant: bedcal.plan, bedcal.preheat, bedcal.tune, bedcal.stop, bedcal.status
(api_ops.init registers them through build(ctx), like bed_zones_ops).

The assistant used to only SHOW G-code. Now the SERVICE does the work, with the person present:
  bedcal.plan      READ (technician): what a preheat or a tuning would send, every line from the closed list, every temperature bounded (the page shows it
                   before asking for the confirmation and in its "show the G-code" section). Sends nothing.
  bedcal.preheat   technician, confirmation level 3: heats the zones in the given order with the stagger between starts, holds them for `hold_min` minutes
                   and turns them off.
  bedcal.tune      technician, confirmation level 4: the M303 of each zone in order, alone or with the neighbours held at the working temperature.
  bedcal.stop      a STOP (never blocked, no login, like bedzones.off): ends the run and turns EVERY configured zone off at once.
  bedcal.status    READ (viewer): the run in progress or the last one, with its zones, temperatures, results and error code.
Both starts are the procedures of machine_bedcal.py started through machine_ops.start: one procedure at a time, the movement reserved (denied with a job, a
live job or the bridge active), the audit row at the end (`machine.run.end`); here the audit row of the START (who started what with which numbers) and an
Activity entry are added. The role and the capability are the ones of the table (permissions.OP_ROLES, permission_caps `system.bed_calibration`).
"""
import activity
import audit
import bed_zones_config
import identity
import machine_bedcal_plan as plan
import machine_gcode
import machine_ops
import messages
from messages import M
from workshop_api import MOTION, READ, STOP, ApiError, Arg, Op

CONFIRM_TEXTS = {key: {lang: {"title": messages.render(lang, "bedcal_confirm_%s_title" % kind), "text": messages.render(lang, "bedcal_confirm_%s_text" % kind)}
                       for lang in ("es", "en")} for key, kind in (("bedcal.preheat", "preheat"), ("bedcal.tune", "tune"))}
KINDS = {"preheat": "bedcal.preheat", "tune": "bedcal.tune"}
ACTIVE = machine_ops.ACTIVE


def _refuse(e):
    return ApiError("refused", M("bedcal_refuse_" + e.code, **{k: v for k, v in e.params.items() if k != "field"}, field=e.params.get("field", "")),
                    reason="bedcal_" + e.code, field=e.params.get("field"))


def _planned(kind, args):
    """The plan of `kind` for the arguments, with the live model and the saved zone settings. ApiError refused for anything that cannot run."""
    params = {k: v for k, v in args.items() if v is not None and k != "kind"}
    planner = plan.plan_preheat if kind == "preheat" else plan.plan_tune
    try:
        allowed = ("beds", "temp", "stagger_s", "hold_min") if kind == "preheat" else ("beds", "temp", "together", "only")
        plan.only(params, allowed)
        return planner(machine_ops.model(), plan.read_settings(machine_ops.read_sd(plan.SETTINGS_PATH)), params)
    except plan.Refused as e:
        raise _refuse(e)


def _public(p):
    """The plan as the page sees it: the zones with their targets, the lines in the order they are sent and the lines that turn everything off."""
    out = {"kind": p["kind"], "temp": p["temp"], "tolerance": p["tolerance"], "off": p["off"],
           "zones": [{k: z[k] for k in ("bed", "heater", "cap", "offset", "target")} for z in p["zones"]], "steps": p["steps"]}
    if p["kind"] == "preheat":
        out.update(stagger_s=p["stagger_s"], hold_s=p["hold_s"], zones=[dict(z, start_s=pz["start_s"]) for z, pz in zip(out["zones"], p["zones"])])
    else:
        out["together"] = p["together"]
        out["zones"] = [dict(z, tune=pz["tune"]) for z, pz in zip(out["zones"], p["zones"])]
    return out


def _slim(run):
    return {k: run.get(k) for k in ("id", "kind", "state", "user", "step", "total", "phase", "created", "started", "finished", "error", "params", "result")}


def current_run():
    """The newest bed calibration run (the one in progress, else the last finished) or None."""
    runs = machine_ops.view(full=True)["runs"]
    return next((r for r in runs if str(r.get("kind", "")).startswith("bedcal.")), None)


def build(ctx):
    def _start(kind):
        def fn(args, c):
            params = {k: v for k, v in args.items() if v is not None}
            _planned(kind, params)  # the refusal with its numbers (bed, temperature, cap) comes from here; machine_ops asks again with its own checks
            started = machine_ops.start(ctx["bridge"], KINDS[kind], params, c)
            who = identity.actor(c)
            audit.event("bedcal.%s.start" % kind, dict(params, run_id=started["run_id"]), who)
            try:
                activity.log_event(ctx.get("bridge"), "calibration", M("bedcal_started_" + kind, user=who["user"] or "-", temp=params["temp"]))
            except Exception as e:  # noqa: BLE001 - the record must never undo a start
                ctx["log_file"]("bed calibration: could not note the start in Activity: %s" % e)
            return started
        return fn

    def plan_op(args, c):
        kind = args["kind"]
        return _public(_planned(kind, args))

    def stop(args, c):
        run = current_run()
        was = bool(run and run["state"] in ACTIVE)
        if was:
            machine_ops.stop()
        # every configured zone off AT ONCE, without waiting for the run to wake up (its own turn-off follows and is harmless)
        config, _problem = bed_zones_config.load()
        codes = [machine_gcode.render("bed_off", bed=z["bed"]) for z in config.get("zones", [])]
        failed = []
        for code in codes:
            try:
                ctx["bridge"].send(code)
            except Exception as e:  # noqa: BLE001 - every other zone is still turned off
                failed.append({"code": code, "error": str(e)[:120]})
        if failed:
            raise ApiError("failed", M("bedcal_stop_failed"), sent=[c for c in codes if c not in [f["code"] for f in failed]], failed=failed, stopped=was)
        audit.event("bedcal.stop", {"run_id": (run or {}).get("id") or "", "was_running": was}, identity.actor(c))
        return {"stopped": was, "codes": codes}

    def status(args, c):
        run = current_run()
        return {"active": bool(run and run["state"] in ACTIVE), "run": _slim(run) if run else None}

    a, O = Arg, "obj"
    start_args = {"beds": a(O, True, desc="Bed numbers (the P of M140) of the zones in the order they are to be used, edges first (the page computes it from the map)."),
                  "temp": a("num", True, min=plan.TUNE_TEMP_RANGE[0], max=plan.TUNE_TEMP_RANGE[1], desc="Working temperature in C (30 to 150).")}
    preheat_args = dict(start_args, stagger_s=a("int", min=plan.STAGGER_RANGE[0], max=plan.STAGGER_RANGE[1], desc="Seconds between two zone starts (0 to 600; default 30)."),
                        hold_min=a("int", min=plan.HOLD_RANGE[0], max=plan.HOLD_RANGE[1],
                                   desc="Minutes the zones stay at temperature once they arrive, then they are turned off (0 to 60; default 15)."))
    tune_args = dict(start_args, together=a("bool", desc="true (default): the other zones are held at the working temperature while one is tuned; false: they are off."),
                     only=a(O, desc="Bed numbers to tune, a subset of beds (default all of them): the others of beds are the neighbours that are held or turned off."))
    return [
        Op("bedcal.plan", plan_op, READ,
           dict(preheat_args, kind=a("str", True, choices=tuple(KINDS), desc="preheat or tune."), together=tune_args["together"], only=tune_args["only"]),
           "What a preheat or a tuning of the bed zones would do, WITHOUT sending anything: the zones with their heater, cap, offset and target, the lines in the "
           "order they are sent (all from the closed G-code list) and the lines that turn everything off. Refused (reason bedcal_*) when the machine is not idle, a "
           "zone has no heater of its own, a heater is in fault or a temperature is over the zone maximum or the heater cap.", log=False),
        Op("bedcal.preheat", _start("preheat"), MOTION, preheat_args,
           "HEATS the bed zones: starts them in the order given, one every stagger_s seconds (M140 P<bed> S<temp + offset>), waits until they arrive, holds them hold_min minutes "
           "and turns them off. Needs the confirmation of level 3, the technician role, an idle machine and no other procedure; it is a procedure of machine.run "
           "(machine.runs, bedcal.status). bedcal.stop turns every zone off. Answers {run_id, kind, state}.",
           confirm={"level": 3, "key": "bedcal.preheat"}, exclusive=False),
        Op("bedcal.tune", _start("tune"), MOTION, tune_args,
           "TUNES the PID of each bed zone in the order given (M303 H<heater> S<temp>), one at a time, alone or with the neighbours held at the working temperature; "
           "the new model stays in use on the board (save it with machine.config.plan kind config.heater_model). Needs the confirmation of level 4, the technician "
           "role, an idle machine and no other procedure; opens an active risk. bedcal.stop turns every zone off. Answers {run_id, kind, state}.",
           confirm={"level": 4, "key": "bedcal.tune"}, exclusive=False),
        Op("bedcal.stop", stop, STOP, {},
           "Stops the heating or tuning of the bed zones in progress and turns EVERY configured zone off at once (M140 P<bed> S-273.15). Never blocked, any role, no login.",
           exclusive=False),
        Op("bedcal.status", status, READ, {},
           "The bed calibration run in progress or the last one: {active, run: {id, kind, state, phase, step, total, user, params, error {code}, result: {zones: "
           "[{bed, heater, target, current, state, result, error, model, model_line}], phase, off, elapsed_s}} | null}.", log=False),
    ]
