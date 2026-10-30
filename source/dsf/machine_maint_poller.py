"""The process that feeds the maintenance counters (Machine v2, phase 4): ONE listener on the single subscription of machine_state.

It never asks DSF for anything: machine_state.on_change() wakes the loop when a patch arrives (at most every MIN_SAMPLE_S, and at least
every WAKE_S, because state.upTime changes every second) and the loop reads the model that machine_state already holds. The samples go to
machine_odometer.Odometer; the result is merged into the store `machine-maintenance` every FLUSH_S, when the module rests and when the
process ends (an atomic write through settings_store: a power cut loses at most FLUSH_S of counting, never the file).

Rests with its plugin: when WorkshopMachine is stopped or disabled (service_modules.MACHINE) it flushes what it has, forgets the previous
sample and counts nothing. A service that was down counts nothing either: the first sample after a start is only a baseline.

A file job (status `processing`) is also measured: the XY path length integrated during the job is compared, at its end, with the length
that gcode_plan computes from the file, and the ratio is kept in the counters as `crosscheck` (a job that was cancelled, or during which
a gap happened, is not compared).
"""
import os
import threading
import time

import heartbeats
import machine_odometer as odo
import machine_store
import service_modules
from messages import M

LABEL = "maintenance"
MIN_SAMPLE_S = 0.2
WAKE_S = 1.0
FLUSH_S = 300
MAX_JOB_FILE_BYTES = 8 * 1024 * 1024
_wake = threading.Event()
_live = {"running": False}
_hooks = {"released": None, "planned": None, "now": None, "flush_done": None}


def running():
    return _live["running"]


def _epoch():
    return _hooks["now"]() if _hooks["now"] else time.time()


def sample_from(model):
    """(status, {letter: machinePosition}, {letter: homed}) of the visible axes of an object model."""
    status = ((model or {}).get("state") or {}).get("status")
    pos, homed = {}, {}
    for a in ((model or {}).get("move") or {}).get("axes") or []:
        if not isinstance(a, dict) or not a.get("letter") or a.get("visible", True) is False:
            continue
        p = a.get("machinePosition")
        if isinstance(p, (int, float)) and not isinstance(p, bool) and p == p:
            pos[str(a["letter"])] = float(p)
            homed[str(a["letter"])] = bool(a.get("homed"))
    return status, pos, homed


def released_axes():
    if _hooks["released"]:
        return _hooks["released"]()
    try:
        import motor_poller
        return set(motor_poller.released())
    except Exception:  # noqa: BLE001
        return set()


def planned_mm(file_name):
    """XY length of a file job in mm, or None (file missing, too big, unreadable). The same planner the Work table uses."""
    if _hooks["planned"]:
        return _hooks["planned"](file_name)
    try:
        import sd_paths
        from handlers import jobs_view
        route = sd_paths.sd(file_name)
        if not os.path.isfile(route) or os.path.getsize(route) > MAX_JOB_FILE_BYTES:
            return None
        stats = jobs_view.summary(route, "Laser", {}, 2000)["stats"]
        return float(stats.get("dist_cut", 0.0)) + float(stats.get("dist_travel", 0.0))
    except Exception:  # noqa: BLE001
        return None


class Collector:
    """The state of the process, without a thread: step() once per sample, flush(), rest(). The loop and the tests drive it."""

    def __init__(self):
        self.odo = odo.Odometer()
        self.last_flush = None
        self.job = None            # {"xy": xy_total at the start, "file": name}
        self.void = False          # a gap happened: the job in progress (or the one that resumes) cannot be compared

    def step(self, t, model, epoch):
        status, pos, homed = sample_from(model)
        if not pos:
            return
        self.odo.feed(t, status, pos, homed, released_axes())
        self._job(status, model)
        if self.last_flush is None:
            self.last_flush = t
        elif t - self.last_flush >= FLUSH_S:
            self.flush(epoch)
            self.last_flush = t

    def lost(self):
        """The subscription is not alive: whatever comes next is only a new baseline, and the interval is a gap."""
        self.odo.reset_baseline(count_gap=True)
        self.void = True

    def rest(self, epoch):
        self.flush(epoch)
        self.odo.reset_baseline()
        self.job = None
        self.void = False
        self.last_flush = None

    def flush(self, epoch):
        """Adds what accumulated to the store (no-op when nothing did). On a failure the delta is kept for the next try."""
        delta = self.odo.take()
        if not odo.has_content(delta):
            return False
        try:
            machine_store.update_maintenance(lambda v: dict(v, counters=odo.merge_counters(v.get("counters") or {}, delta, epoch)))
        except Exception:  # noqa: BLE001 - the counting goes on; the next flush tries again
            self.odo.put_back(delta)
            return False
        self._notify()
        return True

    def _notify(self):
        try:
            import machine_maintenance
            machine_maintenance.check_notifications(None)
        except Exception:  # noqa: BLE001 - a notice must never stop the counting
            pass

    def _job(self, status, model):
        job = ((model or {}).get("job") or {})
        if status == "processing" and self.job is None:
            name = ((job.get("file") or {}).get("fileName")) or ""
            self.job = {"xy": self.odo.xy_total, "file": name}
        elif status != "processing" and self.job is not None:
            done, self.job = self.job, None
            if not job.get("lastFileCancelled") and not job.get("lastFileAborted") and not self.void and done["file"]:
                self._compare(done["file"], self.odo.xy_total - done["xy"])
        if status != "processing":
            self.void = False

    def _compare(self, file_name, estimated):
        threading.Thread(target=self.compare_now, args=(file_name, estimated), daemon=True, name="maint-crosscheck").start()

    def compare_now(self, file_name, estimated):
        planned = planned_mm(file_name)
        if not planned or planned <= 0 or estimated <= 0:
            return None
        cc = {"job": os.path.basename(str(file_name)), "estimated_mm": round(estimated, 1), "planned_mm": round(planned, 1),
              "ratio": round(estimated / planned, 4), "ts": int(_epoch())}
        machine_store.update_maintenance(lambda v: dict(v, counters=dict(v.get("counters") or {}, crosscheck=cc)))
        return cc


def _wait(seconds):
    """Sleeps until a patch arrives (or `seconds`), then keeps MIN_SAMPLE_S between two samples."""
    _wake.wait(seconds)
    _wake.clear()
    time.sleep(MIN_SAMPLE_S)


def run_loop(bridge, config, stop=lambda: False, model_source=None, sleep=None, clock=time.monotonic, subscribe=True):
    """The process (heartbeats.launch). The arguments after `stop` are for the tests: model_source() -> model or raises, sleep(seconds)."""
    import machine_state
    model_source = model_source or (lambda: machine_state.get_status(timeout=2))
    sleep = sleep or _wait
    col = Collector()
    listener = lambda patch, full=False: _wake.set()  # noqa: E731 - fast: it only wakes the loop
    if subscribe:
        machine_state.on_change(listener)
    try:
        while not stop():
            _cycle(col, model_source, sleep, clock)
    finally:
        _live["running"] = False
        col.rest(_epoch())
        if subscribe:
            machine_state.unsubscribe(listener)


def _cycle(col, model_source, sleep, clock):
    if not service_modules.is_active(service_modules.MACHINE):
        if _live["running"]:
            col.rest(_epoch())
        _live["running"] = False
        heartbeats.ok(LABEL)
        heartbeats.detail(LABEL, M("maint_poller_at_rest_machine_plugin_stopped"))
        sleep(3)
        return
    try:
        model = model_source()
    except Exception:  # noqa: BLE001 - no subscription: a gap, not an error
        col.lost()
        _live["running"] = False
        heartbeats.ok(LABEL)
        sleep(WAKE_S)
        return
    _live["running"] = True
    col.step(clock(), model, _epoch())
    heartbeats.ok(LABEL)
    sleep(WAKE_S)
