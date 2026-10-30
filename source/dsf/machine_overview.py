"""machine.overview and machine.state (Machine v2, phase 0): what the page and the other plugins' cards read.

overview()  open to EVERY role (decision of the owner, Q8): per kind of calibration a traffic light and its age, what the machine is ready
            for, and whether a procedure is running. No values of offsets, limits or meshes.
state()     for operators and up: the overview plus the modules that are available or hidden WITH THE REASON, the runs, the newest
            calibration records with their values, the maintenance state and the machine block of the profile.

Everything is codes and numbers (the pages translate them with their own catalogs). The machine is always a Duet 3 + Raspberry Pi; a
non cartesian kinematics (delta, SCARA...) is reported as unsupported and its modules are hidden with the reason.
"""
import time

import machine_procedures

AGE_OLD_DAYS = 30          # a calibration older than this is "old" (a guess, to tune with use)
EXPECTED_KINDS = ("probe.repeat", "level.g32", "mesh.probe")   # shown as "never" until a record exists
LIGHTS = ("never", "ok", "old")
RECENT_RECORDS = 20


def light(entry, age_old_days=AGE_OLD_DAYS):
    """never / ok / old for the newest record of a kind (None = there is none)."""
    if entry is None:
        return "never"
    return "old" if entry["age_days"] > age_old_days else "ok"


def kinds_view(last, expected=EXPECTED_KINDS, age_old_days=AGE_OLD_DAYS):
    """{kind: {"light", "age_days", "ts"}} for the expected kinds and every kind that has a record."""
    out = {}
    for kind in list(expected) + [k for k in sorted(last) if k not in expected]:
        e = last.get(kind)
        out[kind] = {"light": light(e, age_old_days), "age_days": e["age_days"] if e else None, "ts": e["ts"] if e else None}
    return out


def readiness(caps):
    """What the machine is ready for, from capabilities.get: homed, probe, mesh active, kinematics, levelling mode, Z motors."""
    c = (caps or {}).get("capabilities") or {}
    axes = (c.get("axes") or {}).get("items") or []
    visible = [a for a in axes if a.get("visible", True)]
    kin = c.get("kinematics") or {}
    return {
        "live": bool((caps or {}).get("live")),
        "homed": bool(visible) and all(a.get("homed") for a in visible),
        "probe": bool((c.get("probe") or {}).get("present")),
        "mesh_active": bool((c.get("compensation") or {}).get("present")),
        "kinematics": kin.get("name"), "kinematics_supported": bool(kin.get("supported")),
        "levelling_mode": (c.get("levelling") or {}).get("mode"),
        "z_motors": (c.get("z_motors") or {}).get("count", 0),
    }


def modules(caps):
    """{module: {"available": bool, "reason": code or None}}: a module the machine cannot use is hidden WITH the reason."""
    c = (caps or {}).get("capabilities") or {}
    kin = c.get("kinematics") or {}
    unsupported = bool(kin.get("unsupported"))
    has_axes = bool((c.get("axes") or {}).get("present"))
    has_probe = bool((c.get("probe") or {}).get("present"))
    lev = c.get("levelling") or {}

    def need(ok, reason):
        return {"available": bool(ok), "reason": None if ok else reason}

    geometry = need(not unsupported and has_axes, "non_cartesian_kinematics" if unsupported else "no_axes")
    out = {"overview": need(True, None), "safety": need(True, None), "history": need(True, None), "maintenance": need(True, None),
           "axes": geometry, "offsets": geometry, "motion": geometry}
    probe_ok = geometry["available"] and has_probe
    probe_reason = geometry["reason"] or "no_probe"
    out["probe"] = need(probe_ok, probe_reason)
    out["mesh"] = need(probe_ok, probe_reason)
    out["levelling"] = need(geometry["available"] and has_probe and lev.get("present"), geometry["reason"] or ("no_probe" if not has_probe else lev.get("reason") or "unknown"))
    return out


def _caps():
    import machine_ops
    return machine_ops._caps()


def overview(now=None):
    import machine_ops
    import machine_store
    caps = _caps()
    try:
        last = machine_store.last_by_kind(now)
    except machine_store.StoreError:
        last = {}
    v = machine_ops.view()
    cur = next((r for r in v["runs"] if r["id"] == v["current"]), None)
    return {"schema": 1, "generated_at": int(now if now is not None else time.time()), "kinds": kinds_view(last),
            "ready": readiness(caps), "run": {"active": bool(cur), "kind": cur["kind"] if cur else None, "state": cur["state"] if cur else None},
            "age_old_days": AGE_OLD_DAYS, "maintenance": maintenance_light()}


def maintenance_light():
    """{"worst", "due_soon", "due", "overdue"} of the maintenance plan (counts only, no values: open to every role), or None."""
    try:
        import machine_maintenance
        return machine_maintenance.light()
    except Exception:  # noqa: BLE001 - the overview must answer without the store
        return None


def state(now=None):
    import machine_ops
    import machine_profile
    import machine_store
    caps = _caps()
    out = overview(now)
    out["modules"] = modules(caps)
    out["runs"] = machine_ops.view(full=True)
    try:
        out["records"] = machine_store.records(limit=RECENT_RECORDS)
        out["maintenance"] = machine_store.maintenance()
    except machine_store.StoreError as e:
        out["records"], out["maintenance"] = [], None
        out["store_error"] = e.code
    out["profile"] = machine_profile.load().get("machine")
    out["procedures"] = machine_procedures.kinds()
    out["vision"] = vision_status()
    return out


def vision_status():
    """{"measure": bool, "checked_at"}: whether Vision offers the measurement the camera verification needs (cached 30 s)."""
    try:
        import machine_measure
        return machine_measure.capability()
    except Exception:  # noqa: BLE001
        return {"measure": False, "checked_at": None}
