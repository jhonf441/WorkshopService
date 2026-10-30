"""API operations of F2: capabilities.get, profile.get, profile.set, preflight.run.

api_ops.py registers them with one line (`+ profile_ops.ops()`). The role levels are decided
by F1-A's table; the suggestion is: capabilities.get, profile.get, preflight.run = viewer,
profile.set = technician or admin (it is an ADMIN operation: a DWC session, never a macro).
"""
from workshop_api import ADMIN, READ, Arg, ApiError, Op


def _capabilities_get(args, ctx):
    import capabilities_io
    return capabilities_io.get(force=bool(args.get("refresh")))


def _profile_get(args, ctx):
    import capabilities_io
    import machine_profile
    return machine_profile.public_view(machine_profile.load(), capabilities_io.get())


def _profile_set(args, ctx):
    import capabilities_io
    import machine_profile
    current = machine_profile.load()
    changes = args["changes"]
    if not isinstance(changes, dict):
        raise ApiError("invalid_args", "argument 'changes' must be an object", field="changes")
    new = changes if args.get("replace") else machine_profile.merge(current, changes)
    try:
        saved = machine_profile.save(new)
    except machine_profile.ProfileError as e:
        raise ApiError("invalid_args", e.errors[0]["message"], field=e.errors[0]["field"],
                       errors=[{"field": x["field"], "message": str(x["message"])} for x in e.errors])
    capabilities_io.reset_cache()
    return machine_profile.public_view(saved, capabilities_io.get())


def _preflight_run(args, ctx):
    import preflight
    opts = preflight.options_from_machine()
    if args.get("features"):
        opts["features"] = list(args["features"])
    try:
        import machine_state
        model = machine_state.last_state()
        if isinstance(model, dict):
            opts["sbc"] = bool(model.get("sbc"))
            opts["dsf_version"] = ((model.get("sbc") or {}).get("dsf") or {}).get("version")
    except Exception:
        pass
    return preflight.run(options=opts)


def ops():
    S, B, O, L = "str", "bool", "obj", "list"
    a = Arg
    return [
        Op("capabilities.get", _capabilities_get, READ,
           {"refresh": a(B, desc="true reads the board again instead of using the answer cached for 30 seconds.")},
           "What this machine has, discovered from the live board and the SD: board and firmware, axes with their range, boards and driver chips, tools, heaters, fans, "
           "probe, modes, laser, spindle, extruder, LED strip, cameras, meter and light scenes. Each capability has present (true/false) and source "
           "(discovered, declared or default). Works with a plain config.g; nothing of the workshop is assumed.", log=False),
        Op("profile.get", _profile_get, READ, {},
           "The declared machine profile (name, language, currency, meter, shutdown method, macro roles, probe, axis indexes, capability overrides, mode policies), "
           "the macro paths that really exist and the axis indexes found on the board.", log=False),
        Op("profile.set", _profile_set, ADMIN,
           {"changes": a(O, True, desc="Fields to change (the macros, axis_index, capability_overrides and mode_policies objects are merged by key; the others are replaced)."),
            "replace": a(B, desc="true takes changes as the whole profile instead of merging it into the current one.")},
           "Validates and saves the machine profile (sys/workshop/config/machine.json, atomic). Invalid fields answer invalid_args with one message per field."),
        Op("preflight.run", _preflight_run, READ,
           {"features": a(L, desc="Optional features to check as well: camera, vision (default: those enabled in DWC).")},
           "Checks this installation (DSF and Python versions, SBC, folders, AppArmor, pip dependencies, power rules, ffmpeg/OpenCV, ports 8090/8095, DWC password, free space) "
           "and answers one item per check with ok, warn or error plus the fix in words.", slow=True, log=False),
    ]
