"""Mesh (height map) of Machine v2 (phase 1): the `mesh.probe` procedure and the operations machine.mesh.* of the library and the compensation.

mesh.probe   server side, not an M32 job. Order (GCODE-REFERENCE section 9.6: G32 clears the local height map, so it comes FIRST):
               1. G32 when the machine levels with leadscrews and has a bed.g (param run_g32: true / false / auto)
               2. M557 (grid over the whole reach of the probe, or the region asked, minus a margin)
               3. G29 S0 K.. (explicit S0: sys/mesh.g is NOT run; the firmware probes, writes sys/heightmap.csv and activates it)
               4. the map is read from the SD, its statistics computed and the quality gate applied: a map with points the probe could not
                  reach (or none) is "partial": it is kept in the library flagged as such and NOT left active (G29 S2)
               5. a library entry is written (map + metadata: who, probe, G31 trigger height, hash of the configuration, G32 done, statistics)
             Limits (profile machine.safety): max_points_per_run bounds the grid (and the firmware's own 961 points). A stop request is honoured
             between the steps; the G29 itself cannot be interrupted by the service (only the emergency stop of DWC / Jog cuts it).
Operations   list / get (operator), load / clear / taper (technician, movement class geometry: denied with a job), save / delete (technician).
             The library is on the SD of the Pi (machine_heightmap.py); `G29 S3 P"<sub-folder>"` is never used (the documentation does not say
             whether the firmware accepts a sub-folder), `load` puts the map in sys/heightmap.csv and sends `G29 S1`.
"""
import machine_geometry as geo
import machine_heightmap as hm
import machine_probe as probe_mod
import machine_parsers as parsers
import machine_procedures as procs
from messages import M
from workshop_api import ApiError, Arg, MOTION, READ, WRITE, Op

MAX_FIRMWARE_POINTS = 961    # working limit of the 6HC on 3.6.x (GCODE-REFERENCE section 1, M557)
HARD_ERRORS = ("not_triggered", "already_triggered", "probe_enable_failed", "too_few_points", "bad_scan_reading", "tool_deselected")


# ---- parameters and checks ----

def _region(params):
    r = params.get("region")
    if r is None:
        return None
    if not isinstance(r, dict) or set(r) != {"x0", "x1", "y0", "y1"}:
        raise procs.BadParams("region", "{x0, x1, y0, y1}")
    return {k: procs._num(r, k, 0, -5000, 5000) for k in ("x0", "x1", "y0", "y1")}


def validate(params):
    procs._only(params, ("probe", "nx", "ny", "region", "margin", "run_g32", "name", "save"))
    name = params.get("name", "")
    if not isinstance(name, str) or len(name) > 40:
        raise procs.BadParams("name", "text up to 40")
    g32 = params.get("run_g32")
    if g32 is not None and not isinstance(g32, bool):
        raise procs.BadParams("run_g32", "true/false/absent")
    out = {"probe": procs._int(params, "probe", 0, 0, 15) if params.get("probe") is not None else None,
           "nx": procs._int(params, "nx", 5, 2, 31) if params.get("nx") is not None else None,
           "ny": procs._int(params, "ny", 5, 2, 31) if params.get("ny") is not None else None,
           "margin": procs._num(params, "margin", 5.0, 0.0, 50.0), "run_g32": g32, "name": name.strip(), "save": procs._bool(params, "save", True)}
    region = _region(params)
    if region:
        out["region"] = region
    return out


def mesh_probe_index(params, prof, om):
    if params.get("probe") is not None:
        return params["probe"]
    idx = (prof.get("mesh") or {}).get("default_probe_index")
    if idx is None:
        idx = (prof.get("probe") or {}).get("index")
    return idx if idx is not None else geo.first_probe_index(om)


def grid_size(params, prof):
    nx, ny = (prof.get("mesh") or {}).get("default_points") or [5, 5]
    return params.get("nx") or nx, params.get("ny") or ny


def wants_g32(params, caps):
    """True when G32 has to run first: asked, or (auto) the machine levels with leadscrews and has a bed.g."""
    lev = ((caps or {}).get("capabilities") or {}).get("levelling") or {}
    can = lev.get("mode") == "leadscrews" and bool(lev.get("bed_g"))
    return can if params.get("run_g32") is None else params["run_g32"]


def check(params, env):
    om, prof, caps = env["om"], env["profile"], env["caps"]
    k = mesh_probe_index(params, prof, om)
    if k is None or geo.probe_of(om, k) is None:
        return "no_probe_index"
    nx, ny = grid_size(params, prof)
    if nx * ny > min((prof.get("safety") or {}).get("max_points_per_run", 100), MAX_FIRMWARE_POINTS):
        return "too_many_points"
    region, why = geo.grid_region(om, k, params["margin"], params.get("region"))
    if region is None:
        return why
    lev = ((caps or {}).get("capabilities") or {}).get("levelling") or {}
    if params.get("run_g32") is True and lev.get("mode") != "leadscrews":
        return "no_m671" if lev.get("mode") == "missingM671" else "no_levelling"
    if params.get("run_g32") is True and not lev.get("bed_g"):
        return "no_bed_g"
    bound, limit = geo.descent_bound(om, k), (prof.get("safety") or {}).get("max_probe_descent_mm")
    return "descent_limit" if bound is not None and limit is not None and bound > limit else None


# ---- the run ----

def run_g32_first(ctx):
    reply = ctx.send("bed_level")
    parsed = parsers.parse_g32(reply)
    hard = [e for e in parsed["errors"] if e["code"] in HARD_ERRORS]
    if hard or (parsed["last"] or {}).get("kind") in ("failure", "factors", "points", "exceeds", "error"):
        raise procs.ProcedureFailed(hard[0]["code"] if hard else "g32_failed", parsed["raw"][:120])
    return {"kind": (parsed["last"] or {}).get("kind"), "deviation": ((parsed["last"] or {}).get("before") or {}).get("deviation")}


def read_map(ctx):
    """The map G29 S0 wrote: the file the object model names, else sys/heightmap.csv. (text, path)"""
    comp = parsers.parse_compensation(ctx.send("compensation_om"))
    path = comp["file"] if isinstance(comp["file"], str) and comp["file"].startswith("0:/") and ".." not in comp["file"] else hm.CURRENT
    return ctx.read(path), path, comp


def run_mesh(ctx, params):
    om, prof = ctx.model(), ctx.profile()
    k = mesh_probe_index(params, prof, om)
    probe = geo.probe_of(om, k)
    if probe is None:
        raise procs.ProcedureFailed("no_probe_index")
    ctx.use_probe(k)
    probe_mod.descent_guard(om, k, prof, probe_mod.z_state(ctx, om))
    nx, ny = grid_size(params, prof)
    region, why = geo.grid_region(om, k, params["margin"], params.get("region"))
    if region is None:
        raise procs.ProcedureFailed(why)
    g32 = wants_g32(params, ctx.caps())
    state = {"stage": "start", "g32": None}
    steps = 4 + (1 if g32 else 0)
    try:
        before = parsers.parse_compensation(ctx.send("compensation_om"))
        if g32:
            state["stage"] = "g32"
            ctx.progress(1, steps, "g32")
            state["g32"] = run_g32_first(ctx)
        ctx.check()
        state["stage"] = "grid"
        ctx.progress(steps - 3, steps, "grid")
        ctx.send("grid_define", x0=region["xmin"], x1=region["xmax"], y0=region["ymin"], y1=region["ymax"], nx=nx, ny=ny)
        ctx.check()
        state["stage"] = "probing"
        ctx.progress(steps - 2, steps, "probing")
        g29 = parsers.parse_g29(ctx.send("grid_probe", k=k))
        hard = [e for e in g29["errors"] if e["code"] in HARD_ERRORS]
        if hard:
            raise procs.ProcedureFailed(hard[0]["code"], hard[0]["text"])
        ctx.check()
        state["stage"] = "reading"
        ctx.progress(steps - 1, steps, "reading")
        text, path, comp = read_map(ctx)
        outcome = finish_map(ctx, params, prof, om, k, probe, text, path, g29, state, before, (nx, ny), region)
    except Exception:
        ctx.set_result({"outcome": "failed", "stage": state["stage"], "g32": state["g32"]})
        raise
    ctx.progress(steps, steps, "done")
    return outcome


def finish_map(ctx, params, prof, om, k, probe, text, path, g29, state, before, grid, region):
    """Statistics, quality gate, library entry and the result. Leaves a partial map not active."""
    parsed = hm.parse_csv(text) if text else {"ok": False, "error": "no_heightmap"}
    if not parsed["ok"]:
        raise procs.ProcedureFailed("no_heightmap", parsed.get("error") or "")
    quality = prof.get("mesh", {}).get("quality") or {}
    st = hm.stats(parsed, quality)
    reasons = hm.gate(parsed, st, grid[0] * grid[1] - len(g29["skipped"]))
    partial = bool(reasons)
    if partial:
        ctx.send("mesh_clear")
        ctx.partial = True
    meta = None
    if params["save"]:
        meta = hm.save(text, library_meta(ctx, params, prof, k, probe, state, g29, partial, quality, region))
    result = {"outcome": "partial" if partial else "done", "mesh_id": meta["id"] if meta else None, "stats": st, "gate": reasons, "active": not partial,
              "grid": {"nx": grid[0], "ny": grid[1]}, "region": {a: geo.rnd(b, 2) for a, b in region.items()}, "map_file": path, "g32": state["g32"],
              "g29": {k2: g29[k2] for k2 in ("points", "min_error", "max_error", "mean", "deviation", "skipped", "offset_warning")},
              "compensation_before": before["type"], "light": st["light"]}
    ctx.set_result(result)
    ctx.set_record({"outcome": result["outcome"], "mesh_id": result["mesh_id"], "light": st["light"], "gate": reasons, "grid": result["grid"],
                    "stats": {a: st[a] for a in ("probed", "unprobed", "min", "max", "range", "mean", "rms", "stdev")}, "g32": bool(state["g32"]),
                    "skipped": len(g29["skipped"]), "probe": k})
    return result


def library_meta(ctx, params, prof, k, probe, state, g29, partial, quality, region):
    import machine_store
    run = ctx.run
    return {"name": params["name"], "user": run.get("user", ""), "role": run.get("role", ""), "run_id": run.get("id"), "kind": "probed",
            "probe": {"index": k, "type": probe.get("type"), "trigger_height": geo.num(probe.get("triggerHeight")), "offsets": list(geo.offsets_of(probe))},
            "config_sha": hm.config_fingerprint(ctx.read), "machine": machine_store.fingerprint_of(ctx.caps()), "g32": bool(state["g32"]),
            "partial": partial, "active_after": not partial, "quality_thresholds": quality,
            "region": {a: geo.rnd(b, 2) for a, b in region.items()}, "g29": {"points": g29["points"], "deviation": g29["deviation"]}}


procs.register(procs.Procedure("mesh.probe", run_mesh, validate, motion="sequence", needs_probe=True, needs_homed=True, deploys=True, check=check))


# ---- operations of the library and the compensation ----

def _mo():
    import machine_ops
    return machine_ops


def _current(meta, mo):
    om = mo.model()
    idx = (meta.get("probe") or {}).get("index")
    probe = geo.probe_of(om, idx) if idx is not None else None
    cur = {"config_sha": hm.config_fingerprint(mo.read_sd)}
    if idx is not None:
        cur["probe_index"] = idx if probe is not None else -1
    if probe is not None and geo.num(probe.get("triggerHeight")) is not None:
        cur["trigger_height"] = geo.num(probe.get("triggerHeight"))
    return cur


def _with_validity(meta, mo):
    if meta.get("kind") not in ("probed", "saved"):
        return dict(meta, validity={"valid": None, "old": None, "age_days": None, "reasons": ["no_metadata"]})
    return dict(meta, validity=hm.validity(meta, _current(meta, mo)))


def _active(mo):
    comp = (((mo.model() or {}).get("move") or {}).get("compensation")) or {}
    dev = comp.get("meshDeviation") if isinstance(comp.get("meshDeviation"), dict) else {}
    return {"type": comp.get("type") or "none", "file": comp.get("file"), "fade_height": geo.num(comp.get("fadeHeight")),
            "mean": geo.num(dev.get("mean")), "deviation": geo.num(dev.get("deviation"))}


def _list(args, ctx):
    mo = _mo()
    return {"meshes": [_with_validity(m, mo) for m in hm.listing()], "active": _active(mo), "limit": hm.MAX_LIBRARY}


def _get(args, ctx):
    mo = _mo()
    meta, text = hm.meta_of(args["id"]), hm.csv_of(args["id"])
    if meta is None or text is None:
        raise ApiError("not_found", M("machine_mesh_not_found"))
    parsed = hm.parse_csv(text)
    if not parsed["ok"]:
        raise ApiError("failed", M("machine_mesh_unreadable", reason=parsed["error"]))
    quality = mo.profile_block().get("mesh", {}).get("quality") or {}
    return {"mesh": _with_validity(meta, mo), "axes": parsed["axes"], "grid": parsed["grid"], "rows": parsed["rows"], "stats": hm.stats(parsed, quality)}


def _refuse_if_running(mo):
    if mo._active[0]:
        raise ApiError("refused", M("machine_refuse_busy_run"), reason="busy_run", run_id=mo._active[0])


def _comp_after(mo, lines):
    replies = mo.geometry_send(lines + [("compensation_om", {})])
    errors = parsers.find_errors("\n".join(replies[:-1]))
    if errors:
        raise ApiError("failed", M("machine_mesh_board_error", text=errors[0]["text"]))
    return replies[:-1], parsers.parse_compensation(replies[-1])


def _load(args, ctx):
    mo = _mo()
    _refuse_if_running(mo)
    meta, text = hm.meta_of(args["id"]), hm.csv_of(args["id"])
    if meta is None or text is None or args["id"] == "current":
        raise ApiError("not_found", M("machine_mesh_not_found"))
    if not hm.parse_csv(text)["ok"]:
        raise ApiError("failed", M("machine_mesh_unreadable", reason=hm.parse_csv(text)["error"]))
    info = _with_validity(meta, mo)["validity"]
    stale = [r for r in info["reasons"] if r != "no_metadata"]
    if stale and not args.get("accept_stale"):
        raise ApiError("refused", M("machine_mesh_stale", reasons=", ".join(stale)), reason="stale_mesh", validity=info)
    kept = hm.write_current(text)
    _, comp = _comp_after(mo, [("mesh_load", {})])
    return {"loaded": args["id"], "compensation": {k: comp[k] for k in ("type", "file", "fade_height", "mean", "deviation")}, "kept_previous": kept,
            "validity": info}


def _clear(args, ctx):
    mo = _mo()
    _refuse_if_running(mo)
    _, comp = _comp_after(mo, [("mesh_clear", {})])
    return {"compensation": {k: comp[k] for k in ("type", "file", "fade_height")}}


def _taper(args, ctx):
    mo = _mo()
    _refuse_if_running(mo)
    _, comp = _comp_after(mo, [("mesh_taper", {"h": args["height"]})])
    return {"height": args["height"], "compensation": {k: comp[k] for k in ("type", "file", "fade_height")}}


def _save(args, ctx):
    import identity
    mo = _mo()
    om = mo.model()
    comp = (((om or {}).get("move") or {}).get("compensation")) or {}
    path = comp.get("file") if isinstance(comp.get("file"), str) and comp["file"].startswith("0:/") and ".." not in comp["file"] else hm.CURRENT
    text = mo.read_sd(path)
    if text is None:
        raise ApiError("not_found", M("machine_mesh_no_active"))
    who = identity.actor(ctx)
    idx = (mo.profile_block().get("mesh") or {}).get("default_probe_index")
    idx = idx if idx is not None else geo.first_probe_index(om)
    probe = geo.probe_of(om, idx) or {}
    try:
        meta = hm.save(text, {"name": str(args.get("name") or "")[:40], "user": who["user"], "role": who["role"], "run_id": None, "kind": "saved",
                              "probe": {"index": idx, "type": probe.get("type"), "trigger_height": geo.num(probe.get("triggerHeight")),
                                        "offsets": list(geo.offsets_of(probe))} if probe else {},
                              "config_sha": hm.config_fingerprint(mo.read_sd), "partial": False, "source_file": path,
                              "quality_thresholds": mo.profile_block().get("mesh", {}).get("quality")})
    except hm.MeshError as e:
        raise ApiError("failed", M("machine_mesh_save_failed", reason=e.code))
    return {"mesh": meta}


def _delete(args, ctx):
    try:
        hm.delete(args["id"])
    except hm.MeshError as e:
        raise ApiError("not_found" if e.code == "not_found" else "refused", M("machine_mesh_not_found" if e.code == "not_found" else "machine_mesh_read_only"))
    return {"deleted": args["id"]}


def ops():
    S, B, N = "str", "bool", "num"
    a = Arg
    ident = {"id": a(S, True, desc="Mesh id from machine.mesh.list: m-... of the library.")}
    return [
        Op("machine.mesh.list", _list, READ, {}, "The library of height maps (newest first) with who/when/probe/statistics and whether each still matches the machine (validity: G31 trigger height, hash of "
           "the configuration, probe, age), and the compensation active now (type, file, taper height, mean and deviation).", log=False),
        Op("machine.mesh.get", _get, READ, ident, "One map: metadata, validity, the grid, the values (null = not probed) and the statistics "
           "(min, max, range, mean, RMS, deviation, share over the profile thresholds, traffic light).", log=False),
        Op("machine.mesh.load", _load, MOTION, dict(ident, accept_stale=a(B, desc="Load it although it no longer matches the machine (G31 Z or the configuration changed).")),
           "Loads a map of the library and activates it (the file is placed in sys/heightmap.csv and G29 S1 is sent). Refused with a job or "
           "a procedure running; refused when the map does not match the machine unless accept_stale is true.", motion="geometry"),
        Op("machine.mesh.clear", _clear, MOTION, {}, "Disables the mesh compensation (G29 S2). Refused with a job or a procedure running.", motion="geometry"),
        Op("machine.mesh.taper", _taper, MOTION, {"height": a(N, True, min=0, max=100, desc="Taper height in mm (M376 H): full compensation at Z=0, none from this height; 1 or less disables the taper.")},
           "Sets the taper height of the compensation (M376 H).", motion="geometry"),
        Op("machine.mesh.save", _save, WRITE, {"name": a(S, desc="Name, up to 40 characters.")},
           "Saves the map active now into the library (a copy made by the service; the firmware command G29 S3 is not used)."),
        Op("machine.mesh.delete", _delete, WRITE, ident, "Deletes a map of the library (never the active one on the board)."),
    ]
