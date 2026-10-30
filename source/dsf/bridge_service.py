"""
Start / stop the G-code bridge of THIS Pi from the Services page, with the least permission possible.

The bridge is a systemd unit (bridge/install.sh). The service runs as the user dsf and DSF starts its plugins without the
right to change user, so `sudo` does not work from here ("unable to change to root gid"). What works is polkit: install.sh
writes ONE rule that lets dsf start and stop exactly this unit (nothing else, no enable / disable, no other unit):

    /etc/polkit-1/rules.d/49-workshop-gcode-bridge.rules

"Stays on after a power cut" does not need `enable` either: the unit is always enabled, and a flag file decides if it comes
back at boot (the unit has ExecCondition=test ! -e <flag>). Turning the bridge on removes the flag and starts it; turning it
off creates the flag and stops it. Reading the state needs no permission at all (systemctl is-active / cat).
"""
import paths
import os
import shutil
import subprocess
import time

UNIT = "workshop-gcode-bridge.service"
ACTIONS = ("start", "stop")
FLAG = paths.DATA_DIR + "/bridge-disabled"   # exists = the bridge does not start by itself at boot
_notified = {"permission": False}
LAST = {"t": 0.0}   # when the page last asked to turn the bridge on / off (bridge_watchdog.py uses it for the reason of a start)
_permission = {"value": None, "until": 0.0}   # last known answer of the probe (True / False / None = not known yet)
PERMISSION_S = 60


def _systemctl():
    return shutil.which("systemctl") or "/usr/bin/systemctl"


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:  # no systemctl (a PC), timeout...
        return 127, "", str(e)


def _without_permission(err):
    t = (err or "").lower()
    return "authentication" in t or "access denied" in t or "not authorized" in t or "polkit" in t


def _can_control(active):
    """Whether polkit lets this process start the unit: True / False, or None when it cannot be known without changing
    something. pkcheck cannot be used (it only lets root pass details), so the real action is tried: "start" of a unit that
    is already running does nothing, so it is the probe; with the unit stopped it is not tried (the last answer is kept)."""
    current_time = time.time()
    if _permission["value"] is not None and current_time < _permission["until"]:
        return _permission["value"]
    if not active:
        return _permission["value"]
    rc, out, err = _run([_systemctl(), "--no-ask-password", "start", UNIT], timeout=20)
    _permission["value"] = True if rc == 0 else (False if _without_permission(err) else None)
    _permission["until"] = current_time + PERMISSION_S
    if _permission["value"] is False and not _notified["permission"]:
        _notified["permission"] = True  # once: why the page cannot control the unit (the log of the service shows it)
        print("bridge_servicio: the unit cannot be started from here (rc %s): %s" % (rc, (err or out)[:200]))
    return _permission["value"]


def status():
    """{installed, active, enabled, can_control}: reading needs no permission."""
    sc = _systemctl()
    rc, _, _ = _run([sc, "cat", UNIT])
    if rc != 0:
        return {"installed": False, "active": False, "enabled": False, "can_control": False}
    _, act, _ = _run([sc, "is-active", UNIT])
    _, hab, _ = _run([sc, "is-enabled", UNIT])
    starts = hab in ("enabled", "alias", "static") and not os.path.exists(FLAG)
    return {"installed": True, "active": act == "active", "enabled": starts, "can_control": _can_control(act == "active")}


def _systemctl_action(action):
    if action not in ACTIONS:
        return False, "action not allowed"
    rc, out, err = _run([_systemctl(), "--no-ask-password", action, UNIT], timeout=30)
    return rc == 0, err or out


def _flag(put):
    """Creates (True) or removes (False) the flag that stops the bridge from starting at boot."""
    try:
        if put:
            os.makedirs(os.path.dirname(FLAG), exist_ok=True)
            with open(FLAG, "w") as f:
                f.write("The bridge was turned off from the Services page: it does not start at boot until it is turned on again.\n")
        elif os.path.exists(FLAG):
            os.remove(FLAG)
        return True, ""
    except OSError as e:
        return False, str(e)


def put(switched_on):
    """True: remove the flag + start (it comes back after a power cut). False: flag + stop. Returns {ok, error, estado}."""
    e = status()
    if not e["installed"]:
        return {"ok": False, "error": "not_installed", "state": e}
    if e["can_control"] is False:
        return {"ok": False, "error": "no_permission", "state": e}
    if switched_on:
        steps = ((_flag, False), (_systemctl_action, "start"))
    else:
        steps = ((_flag, True), (_systemctl_action, "stop"))
    for fn, arg in steps:
        ok, msg = fn(arg)
        if not ok:
            if _without_permission(msg):
                _permission.update(value=False, until=time.time() + PERMISSION_S)
                return {"ok": False, "error": "no_permission", "state": status()}
            return {"ok": False, "error": msg or str(arg), "state": status()}
    _permission.update(value=True, until=time.time() + PERMISSION_S)
    LAST["t"] = time.time()
    return {"ok": True, "error": None, "state": status()}
