"""
access_context -- the decision of a GOVERNED person with everything the call brings (phase 3 of informes/control-acceso/PLAN-ACCESO.md): the target the
operation declares (access_targets), the mode of the machine, the way in, and the live conditions of the machine (job_running, machine_on) read from
the object model. identity._check_role calls `decide` only when the access file is usable; a person with nothing attached is decided by
permissions.decide and never reaches the model reads here.

  via        always "session" here: a DWC session (or the open mode) is the only way that goes through the roles; keys, macros and local programs have
             their own checks (a rule with `via` is still evaluated, and a rule for another way simply does not hold)
  risk_max   is not put in the context: the evaluator derives it from the capability of the operation (access_eval._risk)
  job_running / machine_on   live_conditions(model, age): a file job is on (job_states.ACTIVE: a tool change alone is not a job) / the supply is not off
             (state.status "off" is M81). Both come from state.status of the last model of machine_state. When there is no model, it has no status, or
             it is older than machine_state.WITHOUT_DATA_S (the limit the subscription itself uses to call a connection dead), the key is LEFT OUT of the
             context: the evaluator then fails closed both ways (the condition does not hold for an allow, and holds for a deny).
"""
import access_person
import access_targets
import job_states
import machine_state


def read_live():
    """(model, age in seconds) of the last object model, or (None, None). Never raises."""
    try:
        return machine_state.last_state(), machine_state.age()
    except Exception:  # noqa: BLE001  a model that cannot be read is an unknown condition, not an error of the call
        return None, None


def live_conditions(model, age, limit=None):
    """{"job_running": bool, "machine_on": bool} from a model and its age, or {} when the model cannot be trusted."""
    limit = machine_state.WITHOUT_DATA_S if limit is None else limit
    if not isinstance(model, dict) or not isinstance(age, (int, float)) or age < 0 or age > limit:
        return {}
    state = model.get("state")
    status = str(state.get("status") or "") if isinstance(state, dict) else ""
    if not status:
        return {}
    return {"job_running": status in job_states.ACTIVE, "machine_on": status != "off"}


def decide(view, ident, operation, dctx, state_of=read_live):
    """access_eval.Decision of the person when the evaluator governs them, else None (permissions.decide decides). `dctx` is the context of
    permissions.decide (args, modes, mode...); `state_of()` gives (model, age)."""
    pr = access_person.build(view, ident)
    if pr is None:
        return None
    model, age = state_of()
    ctx = access_person.request_context(ident, dict(dctx, **live_conditions(model, age)), "session")
    return access_person.evaluate(pr, operation, ctx, access_targets.target_of(operation, dctx.get("args")))
