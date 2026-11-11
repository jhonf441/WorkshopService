"""
access_targets -- which TARGET a call of the API is about (phase 3 of informes/control-acceso/PLAN-ACCESO.md). Pure: no I/O, no service import.

A rule of a profile may name targets ("targets": ["workshop:camera:camera/cam2"]). The evaluator (access_eval) can only match them when the call
DECLARES its target, and that is what this table does: one entry per operation that works on one named thing, with the function that takes the
target out of the arguments of the call. The arguments are the ones the caller sent (never the cleaned ones), so every function tolerates
anything: a value that is not usable gives None.

    target_of(operation, args) -> "workshop:<plugin>:<type>/<id>" or None

None means "this call declares no target": it is evaluated against workshop:<namespace>:* (the default target of access_profile), so a DENY that is
restricted to one target does NOT catch it, and an ALLOW restricted to one target does not cover it. That is deliberate and it is why a sensitive
operation must be in this table. The operations that act on the whole machine, or on a set of things at once, are not in it; neither is a call
that omits its argument (bedzones.setpoint without a zone sets every zone, meter.save without a meter works on the main one).

The id is the text of the argument, stripped and percent-encoded (anything outside letters, digits and . _ - / becomes %XX, so an id can never carry
a wildcard or break the format) and cut at the size the format allows. Ids are case sensitive. Files and folders are normalised first: no drive,
no leading slash, no "." or ".." (a path without a drive and without a leading slash is under gcodes/, as for jobs.preview).

The table (test_access_targets compares it with golden/api_contract.json: every operation and argument named here exists):

    camera.capture, burst, flash, image.get, image.set      camera                         workshop:camera:camera/<id>   (empty: main)
    camera.edit, keep, remove, rename, rerender             file                           workshop:camera:media/<file>
    camera.schedule, camera.timelapse                       name                           workshop:camera:timelapse/<name>
    lights.scene                                            scene                          workshop:lights:scene/<id>
    lights.zone                                             strip, index                   workshop:lights:zone/<strip>/<index>   (strip empty: main)
    lights.apply_m950, lights.test, lights.identify         strip                          workshop:lights:strip/<n>      (empty: main)
    lights.test_state                                       state                          workshop:lights:state/<id>
    lights.pi_test                                          pin                            workshop:lights:pin/<n>
    layerrecipes.get, set, remove, preview, arm             name                           workshop:printing:recipe/<name>
    pelletlayers.get, set, remove, arm                      name                           workshop:printing:pellet/<name>
    bedzones.setpoint                                       zone                           workshop:printing:bedzone/<n>
    jobs.preview, gcodelib.info, layers, thumbnail,
      forget, refresh                                       file                           workshop:printing:file/<path>
    gcodelib.list                                           dir (default gcodes)           workshop:printing:folder/<path>
    livejob.interrupted.get, discard, hide, resume.arm      id                             workshop:workbench:interrupted/<id>
    energy.history, energy.period, meter.get, forget,
      save, settings, test                                  meter                          workshop:power:meter/<key>
    power.timer, power.timer_cancel                         (the timer itself)             workshop:power:timer/shutdown
    power.after_job                                         (the timer itself)             workshop:power:timer/after_job
    vision.get, vision.post                                 path                           workshop:vision:path/<path>
"""
import posixpath
import re
import urllib.parse

MAX_TAIL = 100  # access_profile: what follows "workshop:<plugin>:" holds at most 100 characters
_SAFE = "/._-"
_DRIVE = re.compile(r"^\d+:")


def _text(v):
    """The stripped text of a scalar argument, or "" (a list, an object, a flag or nothing is not an id)."""
    if isinstance(v, bool) or v is None or isinstance(v, (dict, list, tuple, set)):
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v).strip()


def _number(v):
    t = _text(v)
    return t if t.isdigit() else ""


def _path(v, under=""):
    """A normalised path: no drive, no leading slash, no dots; a relative one without a drive goes under `under`."""
    t = _text(v).replace("\\", "/")
    if not t:
        return ""
    if _DRIVE.match(t) or t.startswith("/"):
        t = "/" + _DRIVE.sub("", t).lstrip("/")
    else:
        t = "/" + (under + "/" if under else "") + t
    t = posixpath.normpath(t).lstrip("/")
    return "" if t == "." else t


def _tail(kind, ident):
    return (kind + "/" + urllib.parse.quote(ident, safe=_SAFE))[:MAX_TAIL]


def _from(plugin, kind, getter):
    """A table function: `getter(args)` gives the id as text ("" = the call names none: no target)."""
    def fn(args):
        ident = getter(args)
        return ("workshop:%s:%s" % (plugin, _tail(kind, ident))) if ident else None
    return fn


def _arg(name, conv=_text, default=""):
    return lambda a: conv(a.get(name)) or default


def _strip_of(a):
    return _text(a.get("strip")) or "main"


def _zone_of(a):
    index = _number(a.get("index"))
    return _strip_of(a) + ("/" + index if index else "")


def _fixed(plugin, kind, ident):
    return lambda args: "workshop:%s:%s" % (plugin, _tail(kind, ident))


TABLE = {}  # operation -> (the arguments its function reads, the function)


def _add(names, reads, fn):
    for n in names.split():
        TABLE[n] = (tuple(reads), fn)


_add("camera.capture camera.burst camera.flash camera.image.get camera.image.set", ("camera",), _from("camera", "camera", _arg("camera", default="main")))
_add("camera.edit camera.keep camera.remove camera.rename camera.rerender", ("file",), _from("camera", "media", _arg("file")))
_add("camera.schedule camera.timelapse", ("name",), _from("camera", "timelapse", _arg("name")))
_add("lights.scene", ("scene",), _from("lights", "scene", _arg("scene")))
_add("lights.zone", ("strip", "index"), _from("lights", "zone", _zone_of))
_add("lights.apply_m950 lights.test lights.identify", ("strip",), _from("lights", "strip", _strip_of))
_add("lights.test_state", ("state",), _from("lights", "state", _arg("state")))
_add("lights.pi_test", ("pin",), _from("lights", "pin", _arg("pin", _number)))
_add("layerrecipes.get layerrecipes.set layerrecipes.remove layerrecipes.preview layerrecipes.arm", ("name",), _from("printing", "recipe", _arg("name")))
_add("pelletlayers.get pelletlayers.set pelletlayers.remove pelletlayers.arm", ("name",), _from("printing", "pellet", _arg("name")))
_add("bedzones.setpoint", ("zone",), _from("printing", "bedzone", _arg("zone", _number)))
_add("jobs.preview gcodelib.info gcodelib.layers gcodelib.thumbnail gcodelib.forget gcodelib.refresh", ("file",),
     _from("printing", "file", lambda a: _path(a.get("file"), "gcodes")))
_add("gcodelib.list", ("dir",), _from("printing", "folder", lambda a: _path(a.get("dir"), "gcodes") or "gcodes"))
_add("livejob.interrupted.get livejob.interrupted.discard livejob.interrupted.hide livejob.resume.arm", ("id",), _from("workbench", "interrupted", _arg("id")))
_add("energy.history energy.period meter.get meter.forget meter.save meter.settings meter.test", ("meter",), _from("power", "meter", _arg("meter")))
_add("power.timer power.timer_cancel", (), _fixed("power", "timer", "shutdown"))
_add("power.after_job", (), _fixed("power", "timer", "after_job"))
_add("vision.get vision.post", ("path",), _from("vision", "path", lambda a: _path(a.get("path"))))


def target_of(operation, args):
    """The target the call declares, "workshop:<plugin>:<type>/<id>", or None (no entry, or the arguments name nothing usable)."""
    entry = TABLE.get(str(operation))
    if entry is None:
        return None
    try:
        return entry[1](args if isinstance(args, dict) else {})
    except (TypeError, ValueError, OverflowError):  # a value no function expected: the call declares nothing
        return None
