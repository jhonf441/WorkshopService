"""
Probes and job context of the protection guard (protection_guard.py): how it sees that a process outside the service
(Vision, RS485) is alive, whether a plugin is installed, and whether a laser / CNC job is running.

Vision answers HTTP on 127.0.0.1 (ports.VISION; any answer, even an error status, is a sign of life; a refused or timed out
connection is not). RS485 publishes its state in its own plugin data every few seconds with a small "seq" counter
that changes on every publication; a value that stops changing is a plugin that stopped (the last data stays in the
object model after the process dies, so the value alone proves nothing).
"""
import os
import time
import urllib.error
import urllib.request

import paths
import ports
import service_modules

PLUGINS_DIR = paths.PLUGINS
VISION_URL = "http://127.0.0.1:%d/state" % ports.VISION
VISION_TIMEOUT_S = 3
RS485_EVERY_S = 10
RS485_FILTER = "plugins.%s.data.rs485.**" % service_modules.RS485


def installed(plugin_id, plugins_dir=None):
    """The manifest of the plugin exists: enabled-but-not-installed is not an outage."""
    return os.path.isfile(os.path.join(plugins_dir or PLUGINS_DIR, plugin_id + ".json"))


class VisionProbe:
    def __init__(self, opener=None, clock=time.time):
        self.last_ok = None
        self._opener = opener or (lambda: urllib.request.urlopen(VISION_URL, timeout=VISION_TIMEOUT_S).close())
        self._clock = clock

    def poll(self):
        try:
            self._opener()
        except urllib.error.HTTPError:
            pass  # it answered
        except (urllib.error.URLError, OSError, ValueError):
            return False
        self.last_ok = self._clock()
        return True


EMPTY_CONFIRM_S = 15  # "no device configured" must read so for this long before the protection rests (a start or a reload can show none for a moment)


class Rs485Probe:
    def __init__(self, read=None, clock=time.time):
        self.last_ok = None
        self._empty_since = None
        self._seq = None
        self._read = read or self._read_one_shot
        self._clock = clock
        self._next = 0.0

    @staticmethod
    def _read_one_shot():
        import machine_state
        return {"plugins": machine_state.read_plugins(max_age=8.0)}

    def poll(self):
        now = self._clock()
        if now < self._next:
            return None
        self._next = now + RS485_EVERY_S
        try:
            data = (((self._read() or {}).get("plugins") or {}).get(service_modules.RS485) or {}).get("data") or {}
            seq = (data.get("rs485") or {}).get("seq")
            self._note_devices((data.get("rs485") or {}).get("devices"), now)
        except Exception:
            self._empty_since = None  # not readable: keep watching
            return False
        if seq is None:
            return False
        changed = self._seq is not None and seq != self._seq
        self._seq = seq
        if changed:
            self.last_ok = now
        return changed

    def no_devices(self):
        """True only when the plugin published its list of devices, the list was empty and it has been empty for EMPTY_CONFIRM_S.
        Anything else (never read, unreadable, not a list, a device back) is "there may be devices": the servo stays watched."""
        return self._empty_since is not None and self._clock() - self._empty_since >= EMPTY_CONFIRM_S

    def _note_devices(self, devices, now):
        if isinstance(devices, list) and not devices:
            if self._empty_since is None:
                self._empty_since = now
        else:
            self._empty_since = None  # a device (or a list that is not one): watched again, with the normal grace


def job_context():
    """{"mode", "file_job", "live_job", "active"}: a laser / CNC job (file or live) is running now."""
    import live_job
    import machine_state
    try:
        status = machine_state.read_in("state.status")
        mode = machine_state.read_in("state.machineMode")
    except Exception:
        status = mode = None
    file_job = status in ("processing", "simulating", "resuming")
    try:
        live = live_job.read_in() is not None
    except Exception:
        live = False
    return {"mode": mode, "file_job": file_job, "live_job": live, "active": (file_job or live) and mode in ("Laser", "CNC")}
