"""API operations bedzones.get, bedzones.set, bedzones.setpoint, bedzones.off (api_ops.init registers them through build(ctx), like settings_ops).

The logic is bed_zones.py, the configuration bed_zones_config.py (settings area "bed-zones"), the G-code interception bed_zones_intercept.py.
Roles (permissions.py): get = viewer, setpoint = operator, set = technician, off = a stop (never blocked, like pid.cancel).
The page arms the heating buttons with its own "tap again" step (level 2 of DESIGN.md); the service asks for no confirmation of its own.
"""
import activity
import bed_zones
import bed_zones_config
import settings_store
from messages import M
from workshop_api import READ, STOP, WRITE, Arg, ApiError, Op


def _errors(error):
    return [{"field": x["field"], "message": str(x["message"])} for x in error.errors]


def _detected(heat):
    """What the board says about the beds: [{bed, heater}] for every bed heater slot (heater None = the slot is empty)."""
    heat = heat if isinstance(heat, dict) else {}
    slots = heat.get("bedHeaters") or []
    return [{"bed": i, "heater": h if isinstance(h, int) and h >= 0 else None} for i, h in enumerate(slots)]


def _send(ctx, codes):
    """Sends the codes in order. The API runs on its own thread, so this does not touch the channel of an intercepted code."""
    bridge = ctx["bridge"]
    for i, code in enumerate(codes):
        try:
            bridge.send(code)
        except Exception as e:  # noqa: BLE001 - answered as a failed dependency, never an unhandled crash
            raise ApiError("failed", M("bed_zones_send_failed"), sent_before=codes[:i], error=str(e))


def build(ctx):
    def get(args, c):
        import machine_state
        config, problem = bed_zones_config.load()
        return {"config": config, "rev": settings_store.get(bed_zones_config.AREA)["rev"],
                "problems": _errors(problem) if problem else [],
                "detected": _detected(machine_state.read_in("heat", default={}))}

    def set_(args, c):
        try:
            clean = bed_zones_config.validate(args["config"])
        except bed_zones_config.ConfigError as e:
            raise ApiError("invalid_args", e.errors[0]["message"], field=e.errors[0]["field"], errors=_errors(e))
        try:
            r = settings_store.set(bed_zones_config.AREA, clean, args["base_rev"])
        except settings_store.Conflict as x:
            raise ApiError("conflict", "the bed zones changed since they were read", current={"value": x.value, "rev": x.rev})
        if r["changed"]:
            try:
                activity.log_event(ctx.get("bridge"), "config", M("settings_changed", name=bed_zones_config.AREA))
            except Exception as e:  # noqa: BLE001 - the record must never undo a saved change
                ctx["log_file"](f"bed zones: could not note the change in Activity: {e}")
        return {"config": clean, "rev": r["rev"], "changed": r["changed"]}

    def setpoint(args, c):
        config, problem = bed_zones_config.load()
        if problem:
            raise ApiError("invalid_args", M("bed_zones_config_invalid"), errors=_errors(problem))
        logic = bed_zones_config.for_logic(config)
        zone = args.get("zone")
        if zone is not None:
            code, error = bed_zones.zone_code(zone, args["temperature"], logic)
            if error:
                raise ApiError("invalid_args", M(error[0], **error[1]), field="temperature")
            codes = [code]
        else:
            result = bed_zones.translate("M140", {"S": str(args["temperature"])}, logic)
            if result["action"] == bed_zones.ERROR:
                raise ApiError("invalid_args", M(result["error"], **result["params"]), field="temperature")
            if result["action"] == bed_zones.PASS:
                raise ApiError("invalid_args", M("bed_zones_no_active_zones"), field="zone")
            codes = result["codes"]
        _send(ctx, codes)
        return {"codes": codes}

    def off(args, c):
        config, _problem = bed_zones_config.load()  # an invalid config still turns its zones off: a stop must always work
        codes = bed_zones.off_codes(bed_zones_config.for_logic(config))
        _send(ctx, codes)
        return {"codes": codes}

    a = Arg
    return [
        Op("bedzones.get", get, READ, {},
           "The configuration of the bed zones (enabled, zones with their bed number, active flag and offset, maximum temperature, maximum offset, "
           "tolerance, M190 timeout, map layout), its revision, the problems found in the saved file (the zones are then not used) and the bed heater "
           "slots the board reports: {config, rev, problems, detected: [{bed, heater}]}.", log=False),
        Op("bedzones.set", set_, WRITE,
           {"config": a("obj", True, desc="The whole configuration (see bedzones.get)."),
            "base_rev": a("str", True, desc="The rev returned by bedzones.get (\"0\" for a file that does not exist yet).")},
           "Validates and saves the bed zones configuration only if nobody changed it since base_rev; otherwise error 'conflict' with error.current. "
           "Invalid fields answer invalid_args with one message per field. While enabled is false M140 / M190 go through to the firmware untouched."),
        Op("bedzones.setpoint", setpoint, WRITE,
           {"temperature": a("num", True, desc="Setpoint in C; 0 turns off. With no zone it is the global setpoint (each active zone gets it plus its offset)."),
            "zone": a("int", min=0, desc="Bed number of ONE zone to set by hand (no offset added); omit it for all the active zones.")},
           "HEATS the bed: sends M140 P<bed> S<setpoint> to the zones. A setpoint over the configured maximum, an offset over its limit or an unknown zone is "
           "refused and nothing is sent. Returns the codes sent."),
        Op("bedzones.off", off, STOP, {},
           "Turns every configured zone off (M140 P<bed> S-273.15), active or not. Never blocked. Returns the codes sent.", exclusive=False),
    ]
