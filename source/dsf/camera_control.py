"""What the service does to a camera ITSELF, not to its video: it reaches the camera (`reach`, `ask`) and switches its flash (camera.flash).
The image settings of the camera (camera_image.py) are asked through the same two functions.

The flash used to be the browser's: the viewer sent `GET /control?var=led_intensity` straight to the camera (or `light.set` for the work lights),
remembered "how it was" in its own variables and put it back when the viewer closed. With two screens the second one "restored" what the first one
had left, a closed tab left the LED on for good, and an operator tapped a button that the relay refused. Now the service holds it:

  - `set_flash(camera, on)` switches it (the LED of an ESP32-camera through its own /control, or the work lights through `light.set`, as the
    `flash_source` of that camera in cameras.json says) and remembers it (camera_sources.flash_since, published with each camera: flash {capable, on});
  - `flash_tick` (the loop of the relay) switches it off when nobody looks at the camera any more or after FLASH_MAX_S, so a viewer that closes, a
    tab that dies or a screen that loses the network never leaves it on;
  - the operator may use it (`camera.flash`, the role of `light.set`): nothing else of the camera is opened to the operator.
"""
import threading
import time
import urllib.request

import camera_context
import camera_sources
import net_guard
from camera_context import MAIN
from messages import M

FLASH_ON_VALUE = 255   # led_intensity of the ESP32-camera firmware, 0..255
FLASH_MAX_S = 600      # a flash left on is switched off after this long
FLASH_ALONE_S = 30     # ... and when nobody has asked this camera for a photo or its video for this long
FLASH_GIVE_UP_S = 120  # a camera that does not answer to be switched off is left alone this long after FLASH_MAX_S (then the service forgets it)
_lock = threading.Lock()


def _entry(cid):
    for c in camera_sources.camera_list():
        if c["id"] == cid:
            return c
    return None


def reach(entry):
    """(address of the camera the service can ask, None) or (None, why not): the control server of the camera (the relay's source when it has one).
    An address with [HOSTNAME] is the machine the BROWSER connects to, which the service cannot resolve."""
    if "[HOSTNAME]" in entry["url"]:
        return None, M("camera_control_no_address")
    f = camera_sources.source(entry["id"])
    base = f.base if f is not None else camera_sources.base_of(entry["url"])
    if not base:
        return None, M("camera_control_no_address")
    if not net_guard.check_camera_url(base)[0]:
        return None, M("camera_relay_invalid_address")
    return base, None


def ask(entry, path, timeout=4, changes=False):
    """GET `path` on the camera of the list record `entry`: (the body, None) or (None, why not). `changes`: the call changes a setting, so the next
    photo of the relay has to be from the new one."""
    base, error = reach(entry)
    if error is not None:
        return None, error
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            body = r.read(65536)
    except Exception as e:  # noqa: BLE001
        return None, M("camera_control_not_answered", error=type(e).__name__)
    f = camera_sources.source(entry["id"])
    if changes and f is not None:
        f.invalidate()
    return body, None


def _strip(on):
    """The work lights as the flash: the API operation light.set (as an internal call, so it is in the history like any other). (ok, error)."""
    try:
        import api_ops
        body = api_ops.call("light.set", {"on": bool(on)}, origin="camera")
    except Exception as e:  # noqa: BLE001  the registry is not there (a test, the service starting): the flash is not switched
        return False, type(e).__name__ + ": " + str(e)
    if body.get("ok"):
        return True, None
    return False, str((body.get("error") or {}).get("message") or "error")


def _led(entry, on):
    """The LED of the ESP32-camera through its own /control. (ok, error)."""
    body, error = ask(entry, f"/control?var=led_intensity&val={FLASH_ON_VALUE if on else 0}", changes=True)
    return body is not None, error


def _apply(entry, on):
    return _strip(on) if entry["flash_source"] == "strip" else _led(entry, on)


def set_flash(cid, on):
    """Switches the flash of the camera `cid` ({ok, camera, flash: {capable, on}} or {ok: false, error}). The same call is made when it already is
    as asked (the camera may have been restarted: the LED is off whatever the service remembers)."""
    cid = str(cid or MAIN)
    entry = _entry(cid)
    if entry is None:
        return {"ok": False, "error": M("camera_control_unknown_camera")}
    if entry["flash_source"] != "strip" and (entry.get("flash") or {}).get("capable") is False:
        return {"ok": False, "error": M("camera_control_no_flash")}
    with _lock:
        ok, error = _apply(entry, bool(on))
        if not ok:
            return {"ok": False, "error": error}
        if on:
            camera_sources.flash_since[cid] = time.time()
        else:
            camera_sources.flash_since.pop(cid, None)
    f = camera_sources.source(cid)
    if f is not None and on:
        f.seen()  # the person who switched it on is looking
    camera_context.log(f"camera {cid}: flash {'on' if on else 'off'}")
    return {"ok": True, "camera": cid, "flash": camera_sources.flash_of(entry)}


def flash_tick(shutdown=False):
    """Switches off the flashes that nobody needs: switched on for more than FLASH_MAX_S, a camera of the relay that nobody has looked at for
    FLASH_ALONE_S and has no video open, or all of them (`shutdown`: no plugin can look at a camera any more)."""
    now = time.time()
    for cid, since in list(camera_sources.flash_since.items()):
        f = camera_sources.source(cid)
        forgotten = f is not None and not f.watched() and now - f.last_view > FLASH_ALONE_S
        if not (shutdown or now - since > FLASH_MAX_S or forgotten):
            continue
        entry = _entry(cid)
        if entry is not None:
            ok, error = _apply(entry, False)
            if not ok and now - since < FLASH_MAX_S + FLASH_GIVE_UP_S:
                camera_context.log(f"camera {cid}: could not switch the flash off ({error}); it is tried again")
                continue
        with _lock:
            camera_sources.flash_since.pop(cid, None)
        camera_context.log(f"camera {cid}: flash off (nobody is looking, or it was on too long)")
