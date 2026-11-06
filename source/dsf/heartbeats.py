"""
Heartbeats of the plugin's internal processes ("Workshop services" page).

Each background thread (status lights, consumption, motors, jog...) is started
with launch(): it runs supervised (if the function ends or blows up, the
error is noted and it relaunches itself with a growing wait) and on each
good pass it calls ok(label); in its excepts it calls error(label, e). A
separate thread publishes everything every PUBLISH_S in plugin data "servicesInternal":

  {"procesos": {label: {titulo, descripcion, expected_s, vivo, age_ok_s,
   error, age_error_s, error_hour, reinicios}},
   "proceso": {...}, "suscripcion": machine_state.stats()}

Ages (seconds since the last ok / error, at the moment of publishing) and not
epochs: the browser's clock may differ from the Pi's (seen: 5 min) and
DSF rounds the large numbers of the plugin data. The UI marks "late" if
more than 3x expected_s passes without an ok().

Before this a thread could die or keep failing silently (only a line was
left in workshop-service.log) and nothing in the interface showed it.

"""
import os
import threading
import time

import ipc_stats
import messages
import process_catalog
import viewers
from messages import M

PUBLISH_S = 5  # while the Services page is open (heartbeat, viewers.py)
PUBLISH_IDLE_S = 30  # nobody looking: one IPC call every 30 s

_lock = threading.Lock()
_info = {}
_start_process = time.time()
_cpu_prev = {}      # tid -> (ticks, wall) for each thread's CPU %
try:
    _HZ = os.sysconf("SC_CLK_TCK")
except (ValueError, OSError, AttributeError):
    _HZ = 100
WINDOW_MAX_S = 300  # the maximum interval is measured in 5-minute windows


def register(label, title, description, expected_s):
    with _lock:
        _info.setdefault(label, {
            "title": title,
            "description": description,
            "expected_s": expected_s,
            "live": False,
            "last_ok": None,
            "error": None,
            "error_ts": None,
            "restarts": 0,
            # 2026-10-09 (more process health):
            "cycles": 0,             # heartbeats since the backend started
            "errors_total": 0,
            "interval_avg": None,  # s entre latidos (promedio movil)
            "interval_max": None,   # s, the longest of the current window
            "window_ts": time.time(),
            "startup_ts": None,     # last (re)start of the thread
            "tid": None,
            "detail": None,         # text set by the process itself
            # processes redesign (phase 1): group and lock of the page (process_catalog.py)
            "group": process_catalog.group_of(label),
            "locked": process_catalog.is_locked(label),
            # phase 3: the page offers pause / resume / restart only when this is true (process_catalog.PAUSABLE)
            "pausable": process_catalog.is_pausable(label),
        })


def ok(label):
    d = _info.get(label)
    if d is None:
        return
    current_time = time.time()
    previous = d["last_ok"]
    d["last_ok"] = current_time
    d["cycles"] += 1
    if not d.get("supervised"):
        # a thread nobody launches through launch() (guardian_laser, watchdogs, publisher...) has no supervisor to say it is alive:
        # a tick is the proof. Without this the page would call it "stopped". A supervised one keeps what its supervisor says.
        d["live"] = True
    if d["tid"] is None:
        d["tid"] = threading.get_native_id()
    if previous is not None:
        dt = current_time - previous
        d["interval_avg"] = dt if d["interval_avg"] is None else 0.9 * d["interval_avg"] + 0.1 * dt
        if current_time - d["window_ts"] > WINDOW_MAX_S:
            d["window_ts"] = current_time
            d["interval_max"] = dt
        elif d["interval_max"] is None or dt > d["interval_max"]:
            d["interval_max"] = dt


def detail(label, raw_text):
    """A status line of the process's own (shown in Services)."""
    d = _info.get(label)
    if d is not None:
        d["detail"] = (str(raw_text) if raw_text is not None else None)


def last_beat(label):
    """(epoch of the last ok(), expected_s) of a registered process, or None if it is not registered. For the protection
    guard (protection_guard.py): it decides by itself how late is too late."""
    d = _info.get(label)
    if d is None:
        return None
    return d["last_ok"], d["expected_s"]


def error(label, e):
    d = _info.get(label)
    if d is not None:
        if isinstance(e, messages.Msg):
            d["error"] = e  # ours: published as {"key", "params"}, the page shows it in its language
        else:
            raw_text = f"{type(e).__name__}: {e}" if isinstance(e, BaseException) else str(e)
            d["error"] = raw_text[:300]
        d["error_ts"] = time.time()
        d["errors_total"] += 1


# ---- cooperative controls from the Services page (processes redesign, phase 3) ----
# In MEMORY only: they do NOT survive a restart of the service (a paused process runs again after one; the page shows the truth because
# snapshot() publishes them). Only the loops that call gate() obey (process_catalog.PAUSABLE); the rest ignore them. A thread that is
# blocked inside a call cannot see a restart request: restart_pending_s keeps growing and the page says it did not answer.
_control = {}   # label -> {"paused": bool, "restart_at": epoch or None, "paused_detail": bool}


def _ctl(label):
    return _control.setdefault(label, {"paused": False, "restart_at": None, "paused_detail": False})


def pause(label):
    with _lock:
        _ctl(label)["paused"] = True


def resume(label):
    with _lock:
        c = _ctl(label)
        c["paused"] = False
        if c["paused_detail"]:  # take back the line gate() wrote; the process writes its own on its next pass
            c["paused_detail"] = False
            d = _info.get(label)
            if d is not None:
                d["detail"] = None


def paused(label):
    c = _control.get(label)
    return bool(c and c["paused"])


def request_restart(label):
    with _lock:
        c = _ctl(label)
        if c["restart_at"] is None:  # a second request does not reset the clock of the first one
            c["restart_at"] = time.time()


def restart_requested(label):
    c = _control.get(label)
    return bool(c and c["restart_at"] is not None)


def clear(label):
    """Forget the pause and the restart request of a label."""
    with _lock:
        _control.pop(label, None)


def _take_restart(label):
    """True (and the request is cleared) when a restart was requested: the supervisor calls it when the target returned."""
    with _lock:
        c = _control.get(label)
        if c and c["restart_at"] is not None:
            c["restart_at"] = None
            return True
    return False


def gate(label):
    """What a pausable loop does at the top of each pass: "restart" (return), "pause" (rest about 1 s and `continue`; the heartbeat is
    marked ok, so the page does not call it late, with a detail line) or "run". It never raises: on any problem it says "run"."""
    try:
        c = _control.get(label)
        if not c:
            return "run"
        if c["restart_at"] is not None:
            return "restart"
        if c["paused"]:
            ok(label)
            d = _info.get(label)
            if d is not None:
                d["detail"] = M("heartbeats_paused_from_page")  # a message, not text: the page translates it
            c["paused_detail"] = True
            return "pause"
    except Exception:  # noqa: BLE001 - a control hook must never break the loop it sits in
        pass
    return "run"


def launch(label, target, *args):
    """Runs target(*args) in a supervised daemon thread. A process that depends on a plugin does not start until
    that plugin is active (service_modules.PROCESSES): it stays idle and starts by itself when needed."""
    if label in _info:
        _info[label]["supervised"] = True  # its supervisor decides "live"; a plain tick must not (see ok())
    def _supervisor():
        waiting = 5
        import service_modules
        while not service_modules.process(label):
            _info[label]["effective"] = "idle"  # phase 2: what the supervisor decided (shown by modules.list)
            _info[label]["live"] = True
            _info[label]["idle"] = True
            _info[label]["last_ok"] = time.time()
            _info[label]["detail"] = M("heartbeats_at_rest_no_plugin_uses_active")
            time.sleep(3)
        _info[label]["idle"] = False
        # phase 2: decision at launch (modules.list compares it with the stored mode to say "applies at the next start")
        _info[label]["launch_mode"] = service_modules.kind(label)
        _info[label]["effective"] = "forced" if _info[label]["launch_mode"] == "on" else "running"
        while True:
            _info[label]["live"] = True
            begin = time.time()
            _info[label]["startup_ts"] = begin
            _info[label]["tid"] = threading.get_native_id()
            clean = False
            try:
                target(*args)
                if _take_restart(label):
                    clean = True  # returned because the page asked for a restart: not an error
                else:
                    error(label, M("heartbeats_process_ended_by_itself"))
            except BaseException as e:
                error(label, e)
                _take_restart(label)  # the relaunch below answers the request too
            _info[label]["live"] = False
            if clean:
                _info[label]["restarts"] += 1
                continue  # relaunch at once: no error, no backoff
            # If it ran a good while before dying, retry quickly.
            waiting = 5 if time.time() - begin > 300 else min(waiting * 2, 120)
            time.sleep(waiting)
            _info[label]["restarts"] += 1

    threading.Thread(target=_supervisor, daemon=True, name=f"latido-{label}").start()


def launch_decision(label):
    """(effective, launch_mode) the supervisor recorded for a label: effective "running" | "idle" | "forced" and the stored mode
    at the moment it started; (None, None) when the label has not been launched by launch()."""
    d = _info.get(label) or {}
    return d.get("effective"), d.get("launch_mode")


def _ticks_thread(tid):
    try:
        with open(f"/proc/self/task/{tid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12])  # utime + stime
    except (OSError, IndexError, ValueError):
        return None


def _cpu_pct(tid, current_time):
    if not tid:
        return None
    t = _ticks_thread(tid)
    if t is None:
        return None
    prev = _cpu_prev.get(tid)
    _cpu_prev[tid] = (t, current_time)
    if not prev or current_time <= prev[1]:
        return None
    return round((t - prev[0]) / _HZ / (current_time - prev[1]) * 100, 1)


def process():
    """Data of the whole backend process."""
    out = {"pid": os.getpid(), "age_s": round(time.time() - _start_process), "threads": threading.active_count()}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    out["memory_mb"] = round(int(line.split()[1]) / 1024, 1)
        with open("/proc/self/stat") as f:
            c = f.read().rsplit(")", 1)[1].split()
        ticks = int(c[11]) + int(c[12])
        current_time = time.time()
        prev = _cpu_prev.get("process")
        _cpu_prev["process"] = (ticks, current_time)
        if prev and current_time > prev[1]:
            out["cpu_pct"] = round((ticks - prev[0]) / _HZ / (current_time - prev[1]) * 100, 1)
    except (OSError, IndexError, ValueError):
        pass
    return out


def snapshot():
    # Ages in seconds (small numbers): DSF stores the plugin data numbers
    # with little precision -- an epoch (~1.8e9) arrived rounded to
    # minutes and everything came out "now" (2026-10-09). Times go as text.
    current_time = time.time()
    out = {}
    with _lock:
        for k, v in _info.items():
            d = dict(v)
            d["age_ok_s"] = round(current_time - v["last_ok"], 1) if v["last_ok"] else None
            d["age_error_s"] = round(current_time - v["error_ts"], 1) if v["error_ts"] else None
            d["error_hour"] = time.strftime("%H:%M:%S", time.localtime(v["error_ts"])) if v["error_ts"] else None
            d["active_s"] = round(current_time - v["startup_ts"]) if v.get("startup_ts") and v["live"] else None
            d["interval_avg"] = round(v["interval_avg"], 2) if v.get("interval_avg") is not None else None
            d["interval_max"] = round(v["interval_max"], 2) if v.get("interval_max") is not None else None
            d["cpu_pct"] = _cpu_pct(v.get("tid"), current_time)
            d["idle"] = bool(v.get("idle"))
            c = _control.get(k) or {}
            d["paused"] = bool(c.get("paused"))
            d["restart_pending"] = c.get("restart_at") is not None
            d["restart_pending_s"] = round(current_time - c["restart_at"], 1) if c.get("restart_at") is not None else None
            for k_ in ("last_ok", "error_ts", "startup_ts", "window_ts", "tid"):
                d.pop(k_, None)
            out[k] = d
    return out


def _subscription():
    """Counter of the single DSF subscription (machine_state): patches/s,
    KB/s, whether it is alive, reconnections. To measure the load on the Pi."""
    try:
        import machine_state

        return machine_state.stats()
    except Exception:
        return None


def _modules():
    try:
        import service_modules

        return service_modules.status()
    except Exception:
        return None


def _lights():
    """What the lights loop still asks of DSF / the board per minute (it reads
    the shared subscription, so idle = 0): status_light.ipc_stats()."""
    try:
        import status_light

        return status_light.ipc_stats()
    except Exception:
        return None


def publish_loop(bridge):
    while True:
        try:
            bridge.set_status("servicesInternal", {"processes": snapshot(), "process": process(), "subscription": _subscription(),
                                                    "ipc": ipc_stats.snapshot(), "lights": _lights(), "modules": _modules()})
        except Exception:
            pass
        # a first heartbeat of the page wakes this loop at once
        viewers.sleep("health", PUBLISH_S if viewers.active("health") else PUBLISH_IDLE_S)
