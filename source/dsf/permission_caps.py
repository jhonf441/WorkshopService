"""
permission_caps -- the capabilities: named groups of API operations that a custom role may be granted or denied (phase 1 of
informes/permisos-por-rol/DISENO.md). Pure data and pure functions, no I/O, nothing from the service is imported.

NOT to be confused with capabilities.py, which is what the board can do (`capabilities.get`).

A capability has three fixed attributes (in code, never editable by anybody):
  category  one of CATEGORIES (the nine groups of the API page of the service page)
  klass     read, write, motion, stop, power or admin (the same words as workshop_api's operation classes)
  risk      1 (harmless) to 4 (can hurt the hardware or lock the workshop out)
and the operations it groups (`ops`: names or fnmatch patterns). The lowest role that may call an operation is NOT here: it stays in
permissions.OP_ROLES, so the four base roles behave exactly as before (a golden fixture proves it). A capability only names a group
of operations so a role can say "plus these" or "minus these".

Rules kept here and tested (test_permission_caps.py):
  - every operation registered in the API belongs to exactly one capability;
  - a capability is either delegable (every operation of it may be granted to a custom role) or not (none may): NOT_DELEGABLE;
  - a capability that holds a STOP operation (stopping is never blocked) can never be denied.
`machine.hardware_params` has no operations of its own: it is the explicit key that lets a custom role write the hardware-risk
parameters (M208, M92, M906, M913, M917, M569, M584, the prologue) that permissions.ESCALATE_IN asks an administrator for.
"""
import fnmatch

CATEGORIES = ("machine", "jobs", "lights", "energy", "activity", "camera", "security", "config", "system")
CLASSES = ("read", "write", "motion", "stop", "power", "admin")

HARDWARE_PARAMS = "machine.hardware_params"

# Operations that can NEVER be granted to a role that is not an administrator (the owner's list of 2026-11-06).
NOT_DELEGABLE = ("users.*", "roles.*", "keys.*", "password.*", "auth.resolve", "package.apply", "profile.set", "config.restore",
                 "power.full_reset", "comms.set", "guard.set", "db.folder", "db.delete_previous", "activity.delete", "activity.clear",
                 "history.delete", "lights.apply_m950")


def _c(category, klass, risk, *ops):
    return {"category": category, "class": klass, "risk": risk, "ops": tuple(ops)}


# Order is only for display; an operation matches exactly one entry (test).
CAPABILITIES = {
    # -- machine and movement --
    "machine.view": _c("machine", "read", 1, "state.get", "motion.state", "motion.ask", "frame.status", "view.heartbeat", "pid.status", "pid.trace",
                       "motors.reread", "safety.status", "guard.status", "bedzones.get", "readiness.list", "workstate.get", "machine.overview",
                       "machine.state", "machine.runs", "machine.layout", "machine.limits.get", "machine.power.get", "machine.offsets.get",
                       "machine.tool.get", "machine.beds.get", "machine.motion.get", "machine.shaping.get", "machine.workarea.get",
                       "machine.workarea.positions", "machine.mesh.list", "machine.mesh.get", "machine.maintenance.get", "machine.height.get"),
    "machine.stop": _c("machine", "stop", 1, "jog.stop_xy", "jog.stop_z", "jog.stop_axis", "frame.stop", "pid.cancel", "bedzones.off", "machine.stop",
                       "livejob.stop_safe"),
    "machine.move": _c("machine", "motion", 2, "jog.xy", "jog.z", "jog.axis", "jog.free", "frame.start", "motion.reserve", "motion.renew",
                       "motion.release"),
    "machine.motors": _c("machine", "motion", 2, "motors.enable", "motors.disable"),
    "machine.takeover": _c("machine", "motion", 3, "motion.take_over", "movement.lock"),
    "machine.height": _c("machine", "motion", 2, "machine.height.save", "machine.height.hook", "machine.height.step"),
    "machine.workarea": _c("machine", "motion", 2, "machine.workarea.save", "machine.workarea.step", "machine.workarea.release"),
    "machine.procedures": _c("machine", "motion", 3, "machine.run", "machine.mark_cross", "machine.test_move", "machine.shaping.test", "pid.start",
                             "machine.power.resume"),
    "machine.meshes": _c("machine", "write", 2, "machine.mesh.load", "machine.mesh.clear", "machine.mesh.save", "machine.mesh.delete",
                         "machine.mesh.taper", "machine.calc", "machine.offsets.snapshot"),
    "machine.maintenance": _c("machine", "write", 1, "machine.maintenance.done", "machine.maintenance.plan.set"),
    "machine.config_view": _c("machine", "read", 2, "machine.config.plan", "machine.history.list", "machine.history.get", "machine.history.compare",
                              "machine.report", "machine.tool.pins", "machine.tool.preview", "machine.beds.preview"),
    "machine.config_apply": _c("machine", "write", 3, "machine.config.apply", "machine.history.restore"),
    "machine.try": _c("machine", "motion", 3, "machine.try", "machine.try.pending"),
    HARDWARE_PARAMS: _c("machine", "admin", 4),
    "system.bedzones": _c("system", "write", 2, "bedzones.setpoint", "bedzones.set"),
    "machine.workstate": _c("machine", "write", 1, "workstate.set", "readiness.report"),
    "machine.guard": _c("machine", "admin", 3, "guard.set"),
    # -- jobs and laser --
    "jobs.view": _c("jobs", "read", 1, "job.get", "jobs.preview", "bigpart.*", "livejob.interrupted.list", "livejob.interrupted.get"),
    "jobs.run": _c("jobs", "motion", 2, "job.start", "job.end", "job.cancel", "job.close"),
    "jobs.manage": _c("jobs", "write", 2, "job.timeout", "livejob.interrupted.discard", "livejob.interrupted.hide", "livejob.resume.arm",
                      "livejob.resume.disarm"),
    "jobs.air": _c("jobs", "write", 1, "air.set", "air.auto", "air.delay"),
    # -- lights and status --
    "lights.view": _c("lights", "read", 1, "lights.get"),
    "lights.use": _c("lights", "write", 1, "light.set", "lights.zone", "lights.scene"),
    "lights.config": _c("lights", "write", 2, "lights.save", "lights.pi_pins", "lights.pi_test", "lights.test", "lights.identify", "lights.animation",
                        "lights.preview", "lights.schedule", "lights.test_state", "lights.import", "statuslight.set"),
    "lights.m950": _c("lights", "admin", 4, "lights.apply_m950"),
    # -- energy --
    "energy.view": _c("energy", "read", 1, "energy.history", "energy.period", "energy.rate_get"),
    "energy.timers": _c("energy", "power", 2, "power.after_job", "power.timer", "power.timer_cancel"),
    "energy.meter": _c("energy", "write", 2, "meter.*", "energy.rate_set", "power.method"),
    "energy.shutdown": _c("energy", "power", 3, "power.off"),
    "energy.reset": _c("energy", "power", 4, "power.full_reset"),
    # -- activity and notices --
    "activity.view": _c("activity", "read", 1, "activity.list", "activity.summary", "risk.list", "history.list", "trace.since", "blackbox.status"),
    "activity.write": _c("activity", "write", 1, "activity.log", "risk.start", "risk.end", "blackbox.note", "sound.beep", "notifications.mute",
                         "notifications.test", "notifications.send"),
    "activity.settings": _c("activity", "write", 2, "notifications.get", "notifications.active", "notifications.destination", "notifications.new_topic",
                            "notifications.type", "notifications.option", "notifications.quiet_hours", "notifications.video", "blackbox.lines",
                            "blackbox.hide", "blackbox.show"),
    "activity.delete": _c("activity", "admin", 4, "activity.delete", "activity.clear", "history.delete"),
    # -- camera and vision --
    "camera.view": _c("camera", "read", 1, "camera.status", "camera.token", "vision.get"),
    "camera.capture": _c("camera", "write", 1, "camera.capture", "camera.timelapse", "camera.flash", "camera.burst", "camera.rename"),
    "camera.vision": _c("camera", "write", 1, "vision.post", "camera.service"),
    "camera.manage": _c("camera", "write", 2, "camera.detect", "camera.remove", "camera.keep", "camera.edit", "camera.rerender", "camera.schedule"),
    "camera.settings": _c("camera", "write", 2, "camera.image.get", "camera.image.set"),
    "camera.relay": _c("camera", "write", 3, "camera.start", "camera.stop"),
    # -- users and security --
    "security.session": _c("security", "write", 1, "auth.login", "auth.logout", "auth.whoami", "auth.keepalive", "auth.change_pin"),
    "security.audit": _c("security", "admin", 3, "audit.list"),
    "security.users": _c("security", "admin", 4, "users.*", "auth.resolve"),
    "security.roles": _c("security", "admin", 4, "roles.*"),
    "security.keys": _c("security", "admin", 4, "keys.*"),
    "security.passwords": _c("security", "admin", 4, "password.*"),
    # -- configuration --
    "config.view": _c("config", "read", 1, "config.guard", "config.list", "config.get", "comms.get", "profile.get", "capabilities.get", "settings.get",
                      "modules.list", "examples.list", "package.export", "package.preview", "preflight.run", "plugins.stopped.get", "db.status"),
    "config.api": _c("config", "read", 1, "api.describe", "api.ping"),
    "config.edit": _c("config", "write", 2, "config.snapshot", "config.commit", "config.lock", "config.unlock", "config.arm", "config.confirm",
                      "config.rollback", "settings.set", "settings.merge", "examples.create"),
    "processes.control": _c("system", "write", 2, "modules.set", "processes.pause", "processes.resume", "processes.restart"),
    # restarting the whole service is its OWN capability (not part of processes.control): granting "Procesos: parar y arrancar" never grants it;
    # an administrator may still grant this one on purpose (the level 3 confirmation and the idle checks always apply)
    "service.restart": _c("system", "admin", 3, "service.restart"),
    "system.plugins": _c("system", "write", 1, "plugins.stopped.set"),
    "config.bridge": _c("config", "write", 2, "bridge.test", "bridge.service", "bridge.service.set"),
    "config.critical": _c("config", "admin", 4, "config.restore", "package.apply", "profile.set", "comms.set"),
    # -- system --
    "system.view": _c("system", "read", 1, "health.history"),
    "config.database": _c("config", "write", 2, "db.places", "db.backup", "db.keep", "db.settings"),
    "config.database_admin": _c("config", "admin", 4, "db.folder", "db.delete_previous"),
}

# The operation an escalation lifts: permissions.ESCALATE_IN needs HARDWARE_PARAMS for these.
HARDWARE_OPS = ("machine.config.apply", "machine.history.restore", "machine.try")

_memo = {}


def _match(op, patterns):
    return any(fnmatch.fnmatchcase(op, p) for p in patterns)


def capability_of(op):
    """The capability an operation belongs to, or None (an operation that is not in any group). First match in CAPABILITIES order."""
    op = str(op)
    if op not in _memo:
        _memo[op] = next((cid for cid, c in CAPABILITIES.items() if _match(op, c["ops"])), None)
    return _memo[op]


def matches_of(op):
    """Every capability that lists `op` (the test requires at most one)."""
    return [cid for cid, c in CAPABILITIES.items() if _match(str(op), c["ops"])]


def delegable(op):
    """True when `op` may be granted to a role that is not an administrator."""
    return not _match(str(op), NOT_DELEGABLE)


def capability_ops(cid, ops):
    """Operations of `ops` (an iterable of names) that belong to capability `cid`."""
    c = CAPABILITIES.get(cid)
    return [o for o in ops if c and _match(o, c["ops"])]


def has_stop(cid, stop_ops):
    """True when the capability groups an operation that is never blocked (it cannot be denied)."""
    c = CAPABILITIES.get(cid)
    return bool(c) and any(_match(o, c["ops"]) for o in stop_ops)


def describe():
    """The table for the pages and `roles.list`: id, category, class, risk, operation patterns."""
    return [{"id": cid, "category": c["category"], "class": c["class"], "risk": c["risk"], "ops": list(c["ops"])} for cid, c in CAPABILITIES.items()]
