"""
permissions -- who may call what (F1-A of the redesign, 2026-10-21).

One table, one pure function. The server applies it (identity.AuthRegistry); the pages read the same table
(`auth.whoami` sends it) only to hide what the role cannot do: hiding buttons is NOT the security, this is.

Roles, from the lowest:
  viewer      reads the state of the machine (no camera unless the user has `camera_for_viewer`)
  operator    moves, runs jobs of the modes it is allowed, work lights, camera, captures
  technician  calibrates, edits the configuration of the plugins, RS485, Motors, offsets, changes mode / head
  admin       users, API keys, shutdown / restart, M950 of the lights, deletes history, passwords

`can(role, op, ctx)` is pure (no I/O). ctx keys (all optional):
  args      cleaned arguments of the call (a few operations depend on them, e.g. vision.post)
  mode      mode of the machine now: "laser", "cnc", "fff" (None = unknown)
  modes     modes the user may operate (an operator); technician and admin always have all of them
  camera    the user may see the camera although it is a viewer (`camera_for_viewer`)

Operations that are not in OP_ROLES need admin (a new operation is closed until somebody classifies it) and a test
(test_permissions.py) fails if the registry has an operation that is not here.

Machine v2: the operations of the design that are not registered yet live in PLANNED_OP_ROLES; the ones whose role depends on what they
write (the hardware-risk kinds M208, M92, M906/M913/M917, M569, M584 need admin) have a rule in ESCALATE_IN.

External keys (api_keys.py) do NOT go through this table: they keep their own model (kinds / ops / deny).
"""

VIEWER, OPERATOR, TECHNICIAN, ADMIN = "viewer", "operator", "technician", "admin"
ROLES = (VIEWER, OPERATOR, TECHNICIAN, ADMIN)
RANK = {r: i for i, r in enumerate(ROLES)}
MODES = ("laser", "cnc", "fff")

# operations that need no identity at all: logging in and asking who one is
PUBLIC_OPS = frozenset({"auth.login", "auth.whoami", "api.ping"})
# stopping is never blocked: any caller may stop (no login needed), like the emergency stop of DWC
STOP_OPS = frozenset({"jog.stop_xy", "jog.stop_z", "jog.stop_axis", "frame.stop", "pid.cancel", "machine.stop", "livejob.stop_safe"})
# an operator may run these only in a mode it is allowed (the others need the camera / mode rules below)
MODE_GATED = frozenset({"jog.xy", "jog.z", "jog.axis", "jog.free", "frame.start", "motion.reserve", "job.start"})
# a viewer may call these only when it has the camera (the camera relay key and the Vision answers)
CAMERA_OPS = frozenset({"camera.status", "camera.token", "vision.get"})
# some operations are an operator's until the arguments say they CHANGE settings: then they need more
#   vision.post: the paths that only look (operator); the rest (/config) is a technician's
#   camera.service: without `changes` it only reads the settings of the camera service (operator)
ESCALATE = {
    "vision.post": {"arg": "path", "unless_in": ["/photo", "/detect", "/record/search", "/measure"], "role": "technician"},
    "camera.service": {"arg": "changes", "when_present": True, "role": "technician"},
}

# Machine v2 (decisions of the owner, 2026-10-21): only an administrator writes the parameters that can hurt the hardware.
# The kinds are the `kind` of a configuration record / plan (machine_store.KINDS); the gcode kinds are those of machine.try.
MACHINE_ADMIN_KINDS = ("config.m208", "config.m92", "config.m906", "config.m913", "config.m917", "config.m569", "config.m584")
MACHINE_ADMIN_TRY = ("M208", "M92", "M906", "M913", "M917")
# an operation whose role depends on the value of an argument: {op: {"arg", "when_in": [...], "role"}}. Kept apart from ESCALATE
# because the pages of 2026-10 only know that one (unless_in / when_present): they publish this one as `escalate_in`.
ESCALATE_IN = {
    # when_missing: a call that does not say WHAT it writes needs the higher role too (fail closed; the arguments are required anyway)
    "machine.config.apply": {"arg": "kind", "when_in": list(MACHINE_ADMIN_KINDS), "role": ADMIN, "when_missing": True},
    "machine.history.restore": {"arg": "kind", "when_in": list(MACHINE_ADMIN_KINDS), "role": ADMIN},
    "machine.try": {"arg": "gcode_kind", "when_in": list(MACHINE_ADMIN_TRY), "role": ADMIN, "when_missing": True},
}

OP_ROLES = {
    # -- the session itself (any logged in user; the unlogged ones are refused by identity) --
    "auth.login": VIEWER, "auth.logout": VIEWER, "auth.whoami": VIEWER, "auth.keepalive": VIEWER, "auth.change_pin": VIEWER,
    "api.describe": VIEWER, "api.ping": VIEWER,
    "auth.resolve": ADMIN,  # for local programs (Vision :8095) with the local key; a session needs admin so nobody probes tokens
    # -- users, audit --
    "users.list": ADMIN, "users.add": ADMIN, "users.set": ADMIN, "users.remove": ADMIN, "users.reset_pin": ADMIN,
    "users.settings": ADMIN, "users.enable": ADMIN, "audit.list": ADMIN,
    # -- state (viewer) --
    "state.get": VIEWER, "motion.state": VIEWER, "motion.ask": VIEWER, "frame.status": VIEWER, "view.heartbeat": VIEWER,
    "job.get": VIEWER, "risk.list": VIEWER, "pid.status": VIEWER, "pid.trace": VIEWER, "blackbox.status": VIEWER, "config.guard": VIEWER,
    "lights.get": VIEWER, "motors.reread": VIEWER, "activity.list": VIEWER, "activity.summary": VIEWER,
    "health.history": VIEWER, "energy.history": VIEWER, "energy.period": VIEWER, "energy.rate_get": VIEWER, "db.status": VIEWER,
    # -- camera and Vision answers (viewer only with camera_for_viewer, see CAMERA_OPS) --
    "camera.status": OPERATOR, "camera.token": OPERATOR, "vision.get": OPERATOR,
    # -- operator: move, run jobs, work lights, camera, captures --
    "jog.xy": OPERATOR, "jog.z": OPERATOR, "jog.axis": OPERATOR, "jog.free": OPERATOR,
    "jog.stop_xy": VIEWER, "jog.stop_z": VIEWER, "jog.stop_axis": VIEWER, "frame.stop": VIEWER, "pid.cancel": VIEWER,
    "frame.start": OPERATOR, "motion.reserve": OPERATOR, "motion.renew": OPERATOR, "motion.release": OPERATOR,
    "motion.take_over": TECHNICIAN,
    "job.start": OPERATOR, "job.end": OPERATOR, "job.cancel": OPERATOR, "job.close": OPERATOR,
    # safe stop and resume of the live job (live_job_stop.py): stopping is never blocked (anybody may stop, like the other stops); resuming is an operator's
    "livejob.stop_safe": VIEWER, "livejob.interrupted.list": OPERATOR, "livejob.interrupted.get": OPERATOR, "livejob.resume.arm": OPERATOR,
    "livejob.resume.disarm": OPERATOR, "livejob.interrupted.discard": OPERATOR, "livejob.interrupted.hide": OPERATOR,
    "risk.start": OPERATOR, "risk.end": OPERATOR, "motors.enable": OPERATOR,
    "light.set": OPERATOR, "lights.zone": OPERATOR, "lights.scene": OPERATOR,
    "air.set": OPERATOR, "air.auto": OPERATOR, "air.delay": OPERATOR, "sound.beep": OPERATOR,
    "camera.start": OPERATOR, "camera.stop": OPERATOR, "camera.capture": OPERATOR, "camera.timelapse": OPERATOR,
    "vision.post": OPERATOR, "camera.service": OPERATOR,
    "bigpart.read": OPERATOR, "bigpart.counts": OPERATOR, "bigpart.marks": OPERATOR, "bigpart.part": OPERATOR, "bigpart.fit": OPERATOR,
    "jobs.preview": OPERATOR, "history.list": OPERATOR, "trace.since": OPERATOR,
    "activity.log": OPERATOR, "blackbox.note": OPERATOR,
    "power.after_job": OPERATOR, "power.timer": OPERATOR, "power.timer_cancel": OPERATOR,
    "notifications.mute": OPERATOR, "notifications.test": OPERATOR, "notifications.send": OPERATOR,
    # -- technician: calibrate, configuration of the plugins, RS485, Motors, offsets, mode / head --
    "motors.disable": TECHNICIAN, "pid.start": TECHNICIAN, "movement.lock": TECHNICIAN, "job.timeout": TECHNICIAN,
    "camera.url": TECHNICIAN,
    "lights.save": TECHNICIAN, "lights.pi_pins": TECHNICIAN, "lights.pi_test": TECHNICIAN, "lights.test": TECHNICIAN,
    "lights.identify": TECHNICIAN, "lights.animation": TECHNICIAN, "lights.preview": TECHNICIAN,
    "lights.schedule": TECHNICIAN, "lights.test_state": TECHNICIAN, "lights.import": TECHNICIAN,
    "statuslight.set": TECHNICIAN,
    "config.snapshot": TECHNICIAN, "config.list": TECHNICIAN, "config.get": TECHNICIAN, "config.commit": TECHNICIAN,
    "config.lock": TECHNICIAN, "config.unlock": TECHNICIAN, "config.arm": TECHNICIAN, "config.confirm": TECHNICIAN,
    "config.rollback": TECHNICIAN, "comms.get": TECHNICIAN,
    "meter.get": TECHNICIAN, "meter.search": TECHNICIAN, "meter.test": TECHNICIAN, "meter.save": TECHNICIAN,
    "meter.forget": TECHNICIAN, "meter.settings": TECHNICIAN, "energy.rate_set": TECHNICIAN,
    "notifications.get": TECHNICIAN, "notifications.active": TECHNICIAN, "notifications.destination": TECHNICIAN,
    "notifications.new_topic": TECHNICIAN, "notifications.type": TECHNICIAN, "notifications.option": TECHNICIAN,
    "notifications.quiet_hours": TECHNICIAN, "notifications.video": TECHNICIAN,
    "db.places": TECHNICIAN, "db.backup": TECHNICIAN, "db.keep": TECHNICIAN, "db.settings": TECHNICIAN,
    "modules.list": TECHNICIAN, "modules.set": TECHNICIAN, "examples.list": TECHNICIAN, "examples.create": TECHNICIAN,
    "blackbox.lines": TECHNICIAN, "blackbox.hide": TECHNICIAN, "blackbox.show": TECHNICIAN,
    "bridge.test": TECHNICIAN, "bridge.service": TECHNICIAN, "bridge.service.set": TECHNICIAN,
    "power.method": TECHNICIAN, "password.status": TECHNICIAN,
    # shared settings with a revision (cameras.json holds camera addresses, so reading needs a login as operator)
    "settings.get": OPERATOR, "settings.set": TECHNICIAN, "settings.merge": TECHNICIAN,
    # protection guard: watching state is public to everyone who can see the machine, tuning it is the admin's
    "guard.status": VIEWER, "guard.set": ADMIN,
    # machine profile and discovery: pages of every role need them to hide what the machine does not have
    "workstate.get": VIEWER, "workstate.set": OPERATOR, "safety.status": VIEWER,
    "package.export": TECHNICIAN, "package.preview": TECHNICIAN, "package.apply": ADMIN,
    "readiness.report": OPERATOR, "readiness.list": VIEWER,
    "capabilities.get": VIEWER, "profile.get": VIEWER, "preflight.run": TECHNICIAN, "profile.set": ADMIN,
    # -- Machine v2 (registered by machine_ops.py): the overview is for every role (traffic lights and ages, no values) --
    "machine.overview": VIEWER, "machine.state": OPERATOR, "machine.runs": OPERATOR, "machine.stop": VIEWER,
    "machine.run": TECHNICIAN,
    # phase 1: the library of meshes and the compensation (list / get are an operator's), the configuration plan and apply
    "machine.mesh.list": OPERATOR, "machine.mesh.get": OPERATOR,
    "machine.mesh.load": TECHNICIAN, "machine.mesh.clear": TECHNICIAN, "machine.mesh.save": TECHNICIAN,
    "machine.mesh.delete": TECHNICIAN, "machine.mesh.taper": TECHNICIAN,
    "machine.config.plan": TECHNICIAN, "machine.config.apply": TECHNICIAN,
    # phase 2: history (list / get / compare / restore-plan), report data, offsets, limits, the volatile trial, the laser cross
    "machine.history.list": TECHNICIAN, "machine.history.get": TECHNICIAN, "machine.history.compare": TECHNICIAN,
    "machine.history.restore": TECHNICIAN, "machine.report": TECHNICIAN,
    "machine.offsets.get": OPERATOR, "machine.offsets.snapshot": TECHNICIAN, "machine.limits.get": OPERATOR,
    "machine.layout": OPERATOR,
    "machine.try": TECHNICIAN, "machine.try.pending": TECHNICIAN, "machine.mark_cross": TECHNICIAN,
    # height calibration of the tool (was a card of the Workbench): reading is an operator's, everything that changes or moves a technician's
    "machine.height.get": OPERATOR, "machine.height.save": TECHNICIAN, "machine.height.hook": TECHNICIAN, "machine.height.step": TECHNICIAN,
    # work area of each mode (was a card of the Workbench): reading is an operator's, saving and moving a technician's
    "machine.workarea.get": OPERATOR, "machine.workarea.save": TECHNICIAN, "machine.workarea.step": TECHNICIAN, "machine.workarea.release": TECHNICIAN,
    # phase 3: calibration arithmetic (may store a record), motion parameters and input shaping (reads), the ringing-test text
    "machine.calc": TECHNICIAN, "machine.motion.get": OPERATOR, "machine.shaping.get": OPERATOR, "machine.shaping.test": TECHNICIAN,
    # phase 4: maintenance counters and plan (the plan only drives reminders, so a technician edits it)
    "machine.maintenance.get": OPERATOR, "machine.maintenance.done": TECHNICIAN, "machine.maintenance.plan.set": TECHNICIAN,
    # phase 5: the one-time import from Machine 0.3.0 (reading the state is an operator's; the import writes history and library, so admin)
    # -- admin: shutdown / restart, M950, deleting history, passwords, communication, keys, restoring --
    "power.off": ADMIN, "power.full_reset": ADMIN, "lights.apply_m950": ADMIN,
    "activity.delete": ADMIN, "activity.clear": ADMIN, "history.delete": ADMIN,
    "db.folder": ADMIN, "db.delete_previous": ADMIN, "config.restore": ADMIN, "comms.set": ADMIN,
    "password.set": ADMIN, "password.clear": ADMIN,
    "keys.list": ADMIN, "keys.create": ADMIN, "keys.update": ADMIN, "keys.revoke": ADMIN,
}


# Machine v2 operations of the design (section 4.1) that are NOT registered yet: their role is decided here already, so the
# phase that registers one only moves it to OP_ROLES (test_identity fails for a ghost in OP_ROLES, test_machine_permissions
# for an operation in both tables or one that is registered and still here). Hardware-risk writes are the technician's
# operations escalated to admin by ESCALATE_IN according to the kind they write.
PLANNED_OP_ROLES = {
}


def required_role(op):
    """Lowest role that may call `op` (an operation that is not in the table needs admin)."""
    op = str(op)
    return OP_ROLES.get(op) or PLANNED_OP_ROLES.get(op) or ADMIN


def is_known(op):
    return str(op) in OP_ROLES


def clean_modes(modes):
    """List of valid modes in lower case, in the order of MODES (None -> the default: laser only)."""
    if modes is None:
        return ["laser"]
    if isinstance(modes, str):
        modes = [x for x in modes.replace(";", ",").split(",")]
    got = {str(m).strip().lower() for m in (modes or [])}
    return [m for m in MODES if m in got]


def decide(role, op, ctx=None):
    """(allowed, reason). reason: "" | "role" | "mode" | "camera" | "mode_unknown" | "unknown_role"."""
    ctx = ctx or {}
    op = str(op)
    if role not in RANK:
        return False, "unknown_role"
    if op in STOP_OPS:
        return True, ""
    need = needed_role(op, ctx)
    if op in CAMERA_OPS and role == VIEWER:
        return (True, "") if ctx.get("camera") else (False, "camera")
    if RANK[role] < RANK[need]:
        return False, "role"
    if role == OPERATOR and op in MODE_GATED:
        modes = clean_modes(ctx.get("modes"))
        mode = str(ctx.get("mode") or "").strip().lower()
        if len(modes) < len(MODES):
            if mode not in MODES:
                return False, "mode_unknown"
            if mode not in modes:
                return False, "mode"
    return True, ""


def can(role, op, ctx=None):
    """True when a user with `role` may call `op` (see the module doc for ctx)."""
    return decide(role, op, ctx)[0]


def needed_role(op, ctx=None):
    """The role this call needs: the one of the table, or the higher one of ESCALATE when its arguments change settings."""
    op = str(op)
    need = required_role(op)
    args = (ctx or {}).get("args") or {}
    rule = ESCALATE.get(op)
    if rule:
        v = args.get(rule["arg"])
        hit = bool(v) if rule.get("when_present") else str(v or "") not in rule["unless_in"]
        if hit and RANK[rule["role"]] > RANK[need]:
            return rule["role"]
    rule = ESCALATE_IN.get(op)
    if rule and RANK[rule["role"]] > RANK[need]:
        value = str(args.get(rule["arg"]) or "")
        if value in rule["when_in"] or (rule.get("when_missing") and not value):
            return rule["role"]
    return need


def table_for_client():
    """What the pages need to hide what a role cannot do (they read it from auth.whoami)."""
    return {"roles": list(ROLES), "ops": dict(OP_ROLES), "stop": sorted(STOP_OPS), "mode_gated": sorted(MODE_GATED),
            "camera": sorted(CAMERA_OPS), "modes": list(MODES), "escalate": ESCALATE, "escalate_in": ESCALATE_IN,
            "planned": dict(PLANNED_OP_ROLES)}
