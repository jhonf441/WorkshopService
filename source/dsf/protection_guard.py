"""
Protection guard (rediseno F1-C): an alarm when a safety process dies or a protection is left unwatched.

Before this, if Vision (fire / smoke watch of the laser), RS485 (pause on a servo alarm), the camera relay or
status_light died, the protection simply disappeared and nobody knew; the LED strip stayed frozen on the last frame,
which could be "green / ready" with the machine in fault.

What it does, every PERIOD_S:
  - compares what is EXPECTED to be alive (a process that the mode and the enabled plugins say must run: service_modules,
    the plugin installed and enabled in DWC) with what was SEEN (the last heartbeat: heartbeats.last_beat for the
    internal processes, an HTTP answer of Vision, a changing "seq" in the RS485 plugin data),
  - an expected protection with no heartbeat for longer than its tolerance is DOWN: it is published in plugin data
    "guardStatus" (degraded = true), a "guard" event goes to Activity (and to the phone, with a debounce) and the
    status lights stop showing "ready" (status_light reads degraded() and paints the "risk" state of Lights; the
    colors are the ones of the Lights configuration, nothing is fixed here),
  - if a laser / CNC job is running and the fallen protection is the fire watch or the servo alarm, the event is an
    alarm (urgent). With the setting action = "pause" a file job is also paused (M25); the default only warns.
  - no false alarms: a plugin stopped or disabled on purpose is not expected (it rests); a protection that becomes
    expected again, and every protection at a service restart, gets a grace period before its first heartbeat.

Who watches the watchers: the guard watches status_light (and the other processes); status_light calls degraded(),
which also reports True when the guard's own loop stopped ticking, so a dead guard shows on the strip too. If the whole
service dies, sys/daemon.g takes the LEDs back after 10 s without the Pi heartbeat (CLAUDE.md).

Settings: config["guard"] (see DEFAULTS); read live, changed with the API operation guard.set (admin).
"""
import threading
import time

import heartbeats
import messages
import service_modules
from messages import M

PERIOD_S = 5.0
STALE_S = 30.0  # the guard's own loop silent for this long counts as degraded (status_light asks)
ACTIONS = ("notify", "pause")
DEFAULTS = {
    "enabled": True,
    "action": "notify",           # "notify" (only warn loudly) | "pause" (also pause a file job when fire / servo protection is down)
    "tolerance_factor": 3.0,      # internal processes: late after this many times their expected pace
    "min_tolerance_s": 20.0,
    "external_tolerance_s": 30.0,  # Vision / RS485: seconds without a sign of life
    "grace_s": 60.0,              # extra time for the first heartbeat after a start / restart / enabling
    "renotify_s": 600.0,          # debounce: the same protection does not warn the phone again before this
}
LIMITS = {"tolerance_factor": (1.5, 20.0), "min_tolerance_s": (5.0, 600.0), "external_tolerance_s": (10.0, 600.0),
          "grace_s": (10.0, 900.0), "renotify_s": (60.0, 86400.0)}

HEARTBEAT, VISION, RS485 = "heartbeat", "vision", "rs485"
# protects: what is lost when it dies. "fire" and "servo" are the ones that matter while a laser / CNC job runs.
WATCHES = (
    {"id": "status_light", "source": HEARTBEAT, "protects": "lights", "process": "status_light"},
    {"id": "camera", "source": HEARTBEAT, "protects": "camera", "process": "camera"},
    {"id": "events", "source": HEARTBEAT, "protects": "events", "process": "events"},
    {"id": "motion", "source": HEARTBEAT, "protects": "motion", "process": "motion"},
    {"id": "risk", "source": HEARTBEAT, "protects": "risk", "process": "risk"},
    {"id": "health", "source": HEARTBEAT, "protects": "health", "process": "health"},
    {"id": "vision", "source": VISION, "protects": "fire", "plugin": service_modules.VISION},
    {"id": "rs485", "source": RS485, "protects": "servo", "plugin": service_modules.RS485},
)
_BY_ID = {w["id"]: w for w in WATCHES}
CRITICAL = ("fire", "servo")
JOB_MODES = ("Laser", "CNC")


def settings(config):
    """config["guard"] with defaults and valid values only."""
    raw = (config or {}).get("guard")
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    if isinstance(raw.get("enabled"), bool):
        out["enabled"] = raw["enabled"]
    if raw.get("action") in ACTIONS:
        out["action"] = raw["action"]
    for k, (lo, hi) in LIMITS.items():
        try:
            out[k] = min(hi, max(lo, float(raw[k]))) if k in raw else out[k]
        except (TypeError, ValueError):
            pass
    return out


def _lasted(seconds):
    s = int(seconds)
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


class Guard:
    """The decision logic, with every outside thing injected (so the tests drive it with a fake clock).

    settings_fn() -> settings; expected_fn(watch) -> bool; beat_fn(watch) -> (epoch of last heartbeat or None,
    expected_s or None); job_fn() -> {"active", "file_job", "live_job", "mode"}; emit(type, message, detail);
    pause_fn() -> None (raises if it cannot)."""

    def __init__(self, settings_fn, expected_fn, beat_fn, job_fn, emit, pause_fn, clock=time.time):
        self.settings_fn, self.expected_fn, self.beat_fn = settings_fn, expected_fn, beat_fn
        self.job_fn, self.emit, self.pause_fn, self.clock = job_fn, emit, pause_fn, clock
        self.st = {w["id"]: {"expected_since": None, "down_since": None, "announced": False, "alarmed": False,
                             "paused": False, "notified_at": None, "reminded_at": None} for w in WATCHES}

    @staticmethod
    def _title(w):
        return M("protection_guard_watch_" + w["id"])

    def _tolerance(self, w, cfg, expected_s):
        if w["source"] == HEARTBEAT:
            return max(cfg["min_tolerance_s"], cfg["tolerance_factor"] * float(expected_s or 10))
        return cfg["external_tolerance_s"]

    def _is_down(self, w, cfg, now, state):
        last, expected_s = self.beat_fn(w)
        fresh = last is not None and last >= state["expected_since"]
        limit = self._tolerance(w, cfg, expected_s) + (0 if fresh else cfg["grace_s"])
        ref = max(last or 0, state["expected_since"])
        return now - ref > limit

    def evaluate(self):
        """One pass. Returns the list of {id, protects, state, since} (state: ok | down | rest)."""
        now, cfg = self.clock(), self.settings_fn()
        out = []
        job = None
        for w in WATCHES:
            state = self.st[w["id"]]
            if not cfg["enabled"] or not self.expected_fn(w):
                if state["down_since"] is not None or state["expected_since"] is not None:
                    self._reset(state)  # stopped on purpose: no alarm, no event
                out.append({"id": w["id"], "protects": w["protects"], "state": "rest", "since": None})
                continue
            if state["expected_since"] is None:
                state["expected_since"] = now
            down = self._is_down(w, cfg, now, state)
            if down and state["down_since"] is None:
                state["down_since"] = now
            if down and job is None:
                job = self.job_fn()
            if down:
                self._while_down(w, state, cfg, now, job)
            elif state["down_since"] is not None:
                self._back(w, state, now)
            out.append({"id": w["id"], "protects": w["protects"], "state": "down" if down else "ok",
                        "since": int(state["down_since"]) if down else None})
        return out

    @staticmethod
    def _reset(state):
        state.update(expected_since=None, down_since=None, announced=False, alarmed=False, paused=False)

    def _while_down(self, w, state, cfg, now, job):
        critical_job = bool(job and job.get("active")) and w["protects"] in CRITICAL
        title = self._title(w)
        seconds = int(now - state["down_since"])
        detail = {"watch": w["id"], "protects": w["protects"], "seconds": seconds}
        # debounce: a protection that flaps does not ring the phone every time
        recent = state["notified_at"] is not None and now - state["notified_at"] < cfg["renotify_s"]
        if not state["announced"]:
            state["announced"] = True
            if not recent:
                self._notify(w, state, now, critical_job, title, seconds, detail)
            else:
                state["reminded_at"] = state["notified_at"]
        elif critical_job and not state["alarmed"]:
            self._notify(w, state, now, True, title, seconds, detail)  # a job started while it was down: escalate once
        elif state["reminded_at"] is not None and now - state["reminded_at"] >= cfg["renotify_s"]:
            self._notify(w, state, now, critical_job, title, seconds, detail)
        if critical_job and cfg["action"] == "pause" and not state["paused"]:
            self._pause(w, state, job, title, detail)

    def _notify(self, w, state, now, critical_job, title, seconds, detail):
        state["notified_at"] = state["reminded_at"] = now
        if critical_job:
            state["alarmed"] = True
            self.emit("guard_alarm", M("protection_guard_down_in_job", name=title, seconds=seconds), detail)
        else:
            self.emit("guard", M("protection_guard_down", name=title, seconds=seconds), detail)

    def _pause(self, w, state, job, title, detail):
        state["paused"] = True
        if not job.get("file_job"):
            self.emit("guard_alarm", M("protection_guard_cannot_pause", name=title), detail)
            return
        try:
            self.pause_fn()
            self.emit("guard_alarm", M("protection_guard_job_paused", name=title), detail)
        except Exception as e:
            self.emit("guard_alarm", M("protection_guard_pause_failed", name=title, error=str(e)[:120]), detail)

    def _back(self, w, state, now):
        lasted = now - state["down_since"]
        announced = state["announced"]
        state.update(down_since=None, announced=False, alarmed=False, paused=False)  # still expected: no new grace
        if announced:
            self.emit("guard", M("protection_guard_back", name=self._title(w), lasted=_lasted(lasted)),
                      {"watch": w["id"], "protects": w["protects"], "seconds": int(lasted)})

    def snapshot(self, rows, cfg=None):
        """What is published: plain data, stable between passes (no ticking counters)."""
        cfg = cfg or self.settings_fn()
        titles = {w["id"]: self._title(w) for w in WATCHES}
        down = [r for r in rows if r["state"] == "down"]
        return {"enabled": cfg["enabled"], "degraded": bool(down), "action": cfg["action"],
                "since": min((r["since"] for r in down), default=None),
                "down": [r["id"] for r in down],
                "watches": [{"id": r["id"], "title": titles[r["id"]], "protects": r["protects"], "state": r["state"],
                             "since": r["since"]} for r in rows]}


class InterlockWatch:
    """F3-S: a declared laser interlock (lid, extraction, key; interlocks.py) that is not ok during a laser job is an urgent alarm.

    state_fn() -> [{name, state, ...}] (interlocks.state); the rest is injected like in Guard. The alarm goes out at the first
    pass that sees it; the same interlock does not ring the phone again before renotify_s (a contact that bounces makes ONE alarm),
    and a closing after an alarm is noted once. Interlocks that are not ok with no laser job running are not an event here:
    the refusals of the API and the manual list cover that. The firmware stops the laser by itself (docs/INTERLOCKS.md)."""

    SETTLE_S = 10.0  # closed this long after an alarm = recovered (a bouncing contact is not "back" every time)

    def __init__(self, settings_fn, state_fn, job_fn, emit, clock=time.time):
        self.settings_fn, self.state_fn, self.job_fn, self.emit, self.clock = settings_fn, state_fn, job_fn, emit, clock
        self.last_alarm = {}  # name -> epoch of the last alarm sent (the debounce)
        self.closed_since = {}  # name -> epoch since it reads ok, for the interlocks with an alarm not yet closed

    def evaluate(self):
        """One pass; returns the names of the interlocks that raised an alarm now."""
        cfg, now, rows, fired = self.settings_fn(), self.clock(), self.state_fn(), []
        if not cfg["enabled"]:
            self.last_alarm.clear()
            self.closed_since.clear()
            return fired
        job = None
        for row in rows:
            name = row["name"]
            if row["state"] == "ok":
                self._closed(row, now)
                continue
            self.closed_since.pop(name, None)
            job = job if job is not None else self.job_fn()
            last = self.last_alarm.get(name)
            if not (job.get("active") and str(job.get("mode")) == "Laser") or (last is not None and now - last < cfg["renotify_s"]):
                continue
            self.last_alarm[name] = now
            self.closed_since[name] = None  # an alarm is open until it reads ok for SETTLE_S
            fired.append(name)
            self.emit("guard_alarm", M("protection_guard_interlock_open", name=self._title(row), state=M("interlock_state_" + row["state"])),
                      {"interlock": name, "state": row["state"], "gpin": row.get("gpin")})
        return fired

    def _closed(self, row, now):
        name = row["name"]
        if name not in self.closed_since:
            return
        since = self.closed_since[name]
        if since is None:
            self.closed_since[name] = now
        elif now - since >= self.SETTLE_S:
            del self.closed_since[name]
            self.emit("guard", M("protection_guard_interlock_back", name=self._title(row)), {"interlock": name})

    @staticmethod
    def _title(row):
        import interlocks
        return interlocks.title(row)


# ---- process state read by status_light and the API ----

_lock = threading.Lock()
_now = {"snapshot": None, "tick": None}


def _store(snap):
    with _lock:
        _now["snapshot"], _now["tick"] = snap, time.time()


def degraded(now=None):
    """True while an expected protection is down, or while the guard itself stopped ticking (it was running before)."""
    now = time.time() if now is None else now
    with _lock:
        snap, tick = _now["snapshot"], _now["tick"]
    if snap is None:
        return False
    if snap["enabled"] and tick is not None and now - tick > STALE_S:
        return True
    return bool(snap["degraded"])


def status():
    with _lock:
        snap = _now["snapshot"]
    return dict(snap) if snap else None


def forget():
    """For tests: forget the published state."""
    with _lock:
        _now["snapshot"] = _now["tick"] = None


# ---- the running guard ----

def _expected(w):
    from guard_probes import installed
    if w["source"] == HEARTBEAT:
        return service_modules.process(w["process"])
    return service_modules.is_active(w["plugin"]) and installed(w["plugin"])


def run_loop(bridge, config):
    import activity
    import guard_probes as probes

    vision, rs485 = probes.VisionProbe(), probes.Rs485Probe()

    def beat(w):
        if w["source"] == VISION:
            return vision.last_ok, None
        if w["source"] == RS485:
            return rs485.last_ok, None
        return heartbeats.last_beat(w["process"]) or (None, None)

    def emit(type_name, message, detail):
        activity.log_event(bridge, type_name, message, detail=detail)

    def pause():
        bridge.send("M25")

    guard = Guard(lambda: settings(config), _expected, beat, probes.job_context, emit, pause)
    import interlocks
    watch = InterlockWatch(lambda: settings(config), lambda: interlocks.state(*interlocks.live()), probes.job_context, emit)
    published = None
    while True:
        try:
            if _expected(_BY_ID["vision"]):
                vision.poll()
            if _expected(_BY_ID["rs485"]):
                rs485.poll()
            try:
                watch.evaluate()
            except Exception as e:  # the interlock watch must never stop the guard
                heartbeats.error("guard", e)
            rows = guard.evaluate()
            snap = guard.snapshot(rows)
            _store(snap)
            key = messages.data(snap)
            if key != published:
                published = key
                bridge.set_status("guardStatus", snap)
            heartbeats.detail("guard", ", ".join(snap["down"]) or M("protection_guard_all_watched"))
            heartbeats.ok("guard")
        except Exception as e:
            heartbeats.error("guard", e)
        time.sleep(PERIOD_S)
