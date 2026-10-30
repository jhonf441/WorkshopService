"""
Recorder of the TRAJECTORY of the job in progress (requested 2026-10-08: "in
work zones a part that draws what has been cut or what is being done, with
power, speed, air...").

While there is a job (a file job: state.status processing/paused/...; or
live: current_job.json of handlers/job.py) it saves one sample per second
when the head moved, the laser power changed or the air did:
    [t (s since the start), x, y, z, pwm (0..1), v (mm/s), air (0/1), ...]
(x/y/z = MACHINE position; the page converts it to where the beam lands).

NO LOAD (2026-10-12, request: "drawing the job cannot load the Pi"):
before, it asked for the full GET /machine/status 5 times per second (90 KB
and ~300 ms of DuetWebServer each: DWS at 100% of one core) and also wrote
to /opt/dsf/sd/sys/sys/... (SD_SYS + "sys/..."), so it drew nothing. Now:
  - It only works while someone is watching: the page (Zones > Job, or the
    map with a job in progress) calls the API (trace) every ~10 s (handlers/
    trace.py). With no heartbeat within SLEEP_S it sleeps: it closes the
    connection and reads nothing (it only checks the heartbeat, in memory).
  - Awake, it reads the object model from the single DSF subscription
    (machine_state.get_status: in memory, no HTTP or own connection;
    2026-10-12, before it opened its own subscription with filters without
    "**" that did not bring the position changes).
  - One sample per second (SAMPLE_S).
  - The G-code path (gcode_plan.py) is built once per file: if the same file
    repeats (same size, date and zone) it is reused.
If it fell asleep with a job half done, on waking it follows the same job
(with a travel in the gap, without drawing a false cut) or, if that one
finished, closes it and archives it. A job that starts and ends with nobody
watching is not recorded (file jobs are still drawn whole with the G-code
path when the view is opened in the middle of the job).

The file 0:/sys/workshop/data/trace.json is rewritten about every 1 s while
the job lasts and keeps the last finished job until another one starts.

History (requested 2026-10-10: "job history"): each job that finishes is
also copied to 0:/sys/workshop/data/jobs/<id>.json and noted in
0:/sys/workshop/data/jobs/indice.json (summary for the page's list, without
the samples). The last HIST_MAX jobs are kept and at most
HIST_MAX_BYTES in total; the oldest are deleted. The page can delete
files: when archiving the next one, the index is cleaned of the missing ones.

"""
import fs_atomic
import job_states
import json
import os
import threading
import time

import machine_state
import gcode_plan
import heartbeats
import sd_paths
from messages import M

# Where the job trace is kept on the SD.
TRACE_FILE = sd_paths.sd("sys/workshop/data/trace.json")
# Planned path of the file job (gcode_plan.py): fixed during the job,
# kept apart so as not to rewrite it with every sample.
PLAN_FILE = sd_paths.sd("sys/workshop/data/trace-plan.json")
HIST_DIR = sd_paths.sd("sys/workshop/data/jobs")
HIST_INDEX = os.path.join(HIST_DIR, "index.json")
SD_ROOT = sd_paths.SD
HIST_MAX = 50
HIST_MAX_BYTES = 100 * 1024 * 1024
JOB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_current.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop-service.log")

SAMPLE_S = 0.25  # 4 samples per second: with the single subscription reading the model costs nothing (the 1/s trace drew long straight lines)
SLEEP_S = 30  # no heartbeat from the page in this time: it sleeps
ASLEEP_STEP_S = 1.0  # asleep: how often the heartbeat is checked (in memory)
RETRY_S = 5  # there is no DSF state (no connection)
MIN_MOVE_MM = 0.05
REPLAN_MIN_S = 10.0  # rebuild the toolpath at most this often when the zone changes during a job
REPLAN_MAX = 5
AIR_GPOUT = 7  # air output if config.json says otherwise (air_assist.gpout_index)
# What it reads from the model (all inside machine_state.FILTERS): state.status,
# state.machineMode, state.gpOut, move.axes, move.currentMove, move.extruders,
# move.workplaceNumber, job.file.fileName, job.filePosition, job.layer,
# job.duration, job.lastFileCancelled/Aborted, spindles, global.selectedMode,
# global.laserOffsetOn.
# 2026-10-09 ("what happens with a print of many layers?"): before, it was
# cut at 60000 samples (~3 h) and rewrote the whole file every 1 s. Now on
# reaching MAX_SAMPLES it keeps 1 out of every 2 samples
# (trace["reduccion"] counts how many times) and keeps recording, and the
# writing is spaced according to the size (_write_every).
MAX_SAMPLES = 80000


def _write_every(n):
    # The page no longer follows the job live (it reads the file once a minute while the job runs), so the
    # file is rewritten at that pace: 15 s while small, 30 s, then 60 s for a long job.
    return 15.0 if n < 2000 else 30.0 if n < 12000 else 60.0


JOB_STATES = job_states.ACTIVE

# Texts of the Services page (heartbeats.detail)
DETAIL_ASLEEP = M("job_trace_asleep_nobody_has_job_view_open")
DETAIL_AWAKE = M("job_trace_awake_someone_watches_job")


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [job_trace] {msg}\n")
    except Exception:
        pass


# The same repeated error comes out once every LOG_REPEATED_S (2026-10-11: 5777
# "could not write" in the log because of the broken path)
LOG_REPEATED_S = 600
_last_log = {}


def log_a_time(msg, key=None):
    k = key or msg
    current_time = time.monotonic()
    t = _last_log.get(k)
    if t is not None and current_time - t < LOG_REPEATED_S:
        return
    _last_log[k] = current_time
    log_file(msg)


# ---- Heartbeat of the page (handlers/trace.py) ----

_heartbeat = {"t": None}


def beat(current_time=None):
    """Someone is watching the job: it stays awake SLEEP_S more."""
    _heartbeat["t"] = time.monotonic() if current_time is None else current_time
    return True


def awake(current_time=None):
    t = _heartbeat["t"]
    if t is None:
        return False
    return (time.monotonic() if current_time is None else current_time) - t < SLEEP_S


# ---- Object model (single subscription of machine_state) ----

def _read_model():
    return machine_state.get_status(timeout=2)


def _close(conn):
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


def _read_globals():
    """global.selectedMode and global.laserOffsetOn (of the workshop; on another
    machine they do not exist and state.machineMode is used). Only if they did
    not come in the model (global.** is in the single subscription); once per job."""
    out = {}
    try:
        from dsf.connections import CommandConnection

        c = CommandConnection()
        c.connect()
        try:
            for k in ("selectedMode", "laserOffsetOn"):
                try:
                    out[k] = c.evaluate_expression("global." + k).result
                except Exception:
                    pass
        finally:
            _close(c)
    except Exception as e:
        log_a_time(f"could not read the global variables ({e})", "globals")
    return out


def _job_in_live():
    try:
        with open(JOB_FILE) as f:
            return json.load(f)
    except Exception:
        return None


# ---- Archivos ----

def _write_json(path, data):
    fs_atomic.write_json(path, data, separators=(",", ":"))


def _write(trace):
    try:
        _write_json(TRACE_FILE, trace)
    except Exception as e:
        log_a_time(f"could not write {TRACE_FILE} ({e})", "write")


def _close_orphan(current_time=None):
    """A trace left "activo" on disk by a service that restarted (or a machine that went off) in the middle of a job:
    nobody will ever finish it, and the page cannot take it off the map while it says active. When the machine is not
    running a job any more it is closed as interrupted (the data stays; only the flag and the end are written)."""
    try:
        with open(TRACE_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return False
    if not isinstance(d, dict) or not d.get("active"):
        return False
    current_time = time.time() if current_time is None else current_time
    d["active"] = False
    d["end"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(current_time))
    d["end_approximate"] = True
    d["result"] = "interrumpido"
    _write(d)
    log_file("a trace left open by an earlier run was closed as interrupted")
    return True


def _archive(trace):
    """Copies the finished job to the history and updates the index."""
    try:
        os.makedirs(HIST_DIR, exist_ok=True)
        hid = job_id(trace)
        path = os.path.join(HIST_DIR, hid + ".json")
        _write_json(path, trace)
        plan_bytes = 0
        if (trace.get("plan") or {}).get("ok") and os.path.exists(PLAN_FILE):
            try:
                with open(PLAN_FILE, "rb") as f:
                    payload = f.read()
                with open(os.path.join(HIST_DIR, hid + ".plan.json"), "wb") as f:
                    f.write(payload)
                plan_bytes = len(payload)
            except OSError as e:
                log_file(f"could not save the toolpath in the history ({e})")
        try:
            with open(HIST_INDEX) as f:
                idx = json.load(f)
            if not isinstance(idx, list):
                idx = []
        except Exception:
            idx = []
        # remove the ones deleted from the page (and a repeated one with the same id)
        idx = [e for e in idx if isinstance(e, dict) and e.get("id") != hid and os.path.exists(os.path.join(HIST_DIR, str(e.get("id")) + ".json"))]
        idx.append({
            "id": hid,
            "name": trace.get("name"),
            "origin": trace.get("origin"),
            "mode": trace.get("mode"),
            "zone": trace.get("zone"),
            "start": trace.get("start"),
            "end": trace.get("end"),
            "duration_s": trace.get("duration_s"),
            "result": trace.get("result"),
            "samples": len(trace.get("samples") or []),
            "bytes": os.path.getsize(path) + plan_bytes,
        })
        # limit by count and by space: the oldest go
        while len(idx) > HIST_MAX or (len(idx) > 1 and sum(e.get("bytes") or 0 for e in idx) > HIST_MAX_BYTES):
            old = idx.pop(0)
            for ext in (".json", ".plan.json"):
                try:
                    os.remove(os.path.join(HIST_DIR, str(old.get("id")) + ext))
                except OSError:
                    pass
        _write_json(HIST_INDEX, idx)
    except Exception as e:
        log_file(f"could not save in the history ({e})")


def job_id(trace):
    """Id of a job: its start as YYYYMMDD-HHMMSS (the name of its history file jobs/<id>.json; trace_since.py uses it too)."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(int(trace.get("start_epoch") or 0)))


def _remove_plan():
    try:
        os.remove(PLAN_FILE)
    except OSError:
        pass


def _path_sd(fname):
    """0:/gcodes/x.gcode -> /opt/dsf/sd/gcodes/x.gcode"""
    return sd_paths.sd(fname)


def _key_plan(fname, om):
    """What is needed to reuse an already built path: the same file
    (size and date) in the same zone with the same offsets."""
    try:
        st = os.stat(_path_sd(fname))
    except OSError:
        return None
    mv = (om or {}).get("move") or {}
    offs = []
    for a in mv.get("axes") or []:
        a = a or {}
        if a.get("letter") in ("X", "Y", "Z"):
            # no machine - user position here: while the machine moves it changes by itself and the key never repeated
            offs.append([a.get("letter"), a.get("workplaceOffsets")])
    return json.dumps([fname, st.st_size, int(st.st_mtime), mv.get("workplaceNumber"), offs], sort_keys=True)


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _sample(s, t0, current_time, air_gpout=AIR_GPOUT):
    """[t, x, y, z, pwm, v, air, e, layer, rpm, fpos] -- e = sum of the
    extruder positions (FFF), layer = job.layer, rpm = spindle,
    fpos = job.filePosition (how far the file is: done / remaining of the
    planned path)."""
    m = s.get("move") or {}
    ax = {(a or {}).get("letter"): (a or {}).get("machinePosition") for a in (m.get("axes") or [])}
    cm = m.get("currentMove") or {}
    gp = (s.get("state") or {}).get("gpOut") or []
    sal = gp[air_gpout] if 0 <= air_gpout < len(gp) else None
    air = 1 if sal and (sal.get("pwm") or 0) > 0 else 0
    v = max(_num(cm.get("topSpeed")), 0)
    e = 0.0
    for ex in m.get("extruders") or []:
        e += _num((ex or {}).get("position"))
    layer = (s.get("job") or {}).get("layer") or 0
    rpm = 0
    for sp in s.get("spindles") or []:
        rpm = max(rpm, abs(_num((sp or {}).get("current"))))
    return [
        round(current_time - t0, 1),
        round(_num(ax.get("X")), 2),
        round(_num(ax.get("Y")), 2),
        round(_num(ax.get("Z")), 2),
        round(_num(cm.get("laserPwm")), 2),
        round(float(v), 1),
        air,
        round(e, 2),
        int(layer) if isinstance(layer, (int, float)) else 0,
        int(rpm),
        int(_num((s.get("job") or {}).get("filePosition"))),
    ]


class Recorder:
    """Builds the trace from the object model passed to it (step()); it reads
    nothing on its own (the tests pass it made-up models)."""

    def __init__(self, air_gpout=AIR_GPOUT, read_globals=_read_globals, arm_plan=True):
        self.air_gpout = air_gpout
        self.read_globals = read_globals
        self.arm_plan = arm_plan
        self.trace = None
        self.key = None
        self.t0 = 0.0
        self.last_write = 0.0
        self.gap = False  # it fell asleep with the job half done
        self.plan_of = None  # key of the path that is in PLAN_FILE
        self.plans_armed = 0
        self.plan_t = 0.0   # when the toolpath was last (re)built
        self.tool_idle = None  # tool offsets measured while idle (gcode_plan.desfase_herramienta)
        self.replans = 0   # rebuilds of this job because the zone changed
        self.orphan_view = False  # the trace left open on disk was already looked at
        self.finished = None  # the last job this recorder closed, kept in memory for trace.since (trace_since.py)

    def forget_finished(self, trace):
        """Drops the closed job kept in memory when it is still `trace` (compare and clear: a job that closes meanwhile stays).
        trace_since.py calls it when trace.json was deleted (the Delete button of the job card): from then on "current" is
        nothing recorded until another job starts. Its history file jobs/<id>.json is not touched."""
        if self.finished is trace:
            self.finished = None
            return True
        return False

    # -- dormir / despertar --
    def sleep(self):
        if self.trace is not None:
            _write(self.trace)
            self.gap = True

    # -- one step (once per second, awake) --
    def step(self, s, live, current_time):
        st = (s.get("state") or {}).get("status")
        job = s.get("job") or {}
        fname = (job.get("file") or {}).get("fileName")
        # A file job running on the board is a FILE job whatever the live-job marker says: the marker of an earlier live
        # job can stay open (the program never sent the end, it closes after the inactivity time) and then the file job
        # was recorded as a live one: no toolpath, nothing drawn. A live job has no file on the board.
        if live and fname and st in JOB_STATES:
            live = None
        is_active = bool(live) or st in JOB_STATES
        if st == "idle":
            # what the tool adds to the position, measured with the machine still (used to build the toolpath)
            self.tool_idle = gcode_plan.offset_tool(s)
        if not self.orphan_view:
            self.orphan_view = True
            if self.trace is None and not is_active:
                _close_orphan(current_time)
        key = ("live", str((live or {}).get("start_ts") or (live or {}).get("name"))) if live else ("file", fname)
        if self.trace is not None and is_active and (key != self.key or self._other_job(job, current_time)):
            # mientras dormia termino ese trabajo y empezo otro
            self._finish(s, current_time)
        if is_active and self.trace is None:
            self._begin(s, live, fname, key, current_time)
        if self.trace is None:
            return
        if not is_active and self.gap:
            self._finish(s, current_time)  # it finished while asleep: no sample from afterwards
            return
        trace = self.trace
        # The start macro of a job (M98 in the file) can select another zone (G55, G56...) after the toolpath was
        # built with the zone of the moment the job began: the whole path came out shifted, outside the machine. When
        # the zone or its offsets change, the path is built again (at most REPLAN_MAX times a job, 10 s apart).
        if (trace.get("origin") == "file" and fname and self.plan_of is not None and is_active
                and self.replans < REPLAN_MAX and current_time - self.plan_t >= REPLAN_MIN_S
                and not (trace.get("plan") or {}).get("assembling")):
            new = _key_plan(fname, s)
            if new is not None and new != self.plan_of:
                self.replans += 1
                self.plan_t = current_time
                log_file(f"the zone or its offsets changed during the job: building the toolpath of {fname} again")
                self._plan(fname, s)
        smp = _sample(s, self.t0, current_time, self.air_gpout)
        mm = trace["samples"]
        if self.gap and mm:
            # it fell asleep: the stretch without samples goes as a travel (no power,
            # no spindle and no extrusion), not as a false straight cut
            p = mm[-1]
            a = list(p)
            a[0], a[4], a[9] = smp[0], 0, 0
            b = list(smp)
            b[4], b[9], b[7] = 0, 0, p[7]
            mm.extend([a, b, smp])
            trace["huecos"] = trace.get("huecos", 0) + 1
        elif not mm:
            mm.append(smp)
        else:
            p = mm[-1]
            moved = abs(smp[1] - p[1]) >= MIN_MOVE_MM or abs(smp[2] - p[2]) >= MIN_MOVE_MM or abs(smp[3] - p[3]) >= MIN_MOVE_MM
            changed = smp[4] != p[4] or smp[6] != p[6] or smp[8] != p[8] or (smp[9] > 0) != (p[9] > 0)
            if moved or changed or smp[0] - p[0] >= 5:
                mm.append(smp)
        self.gap = False
        if len(mm) >= MAX_SAMPLES:
            trace["samples"] = mm = mm[::2]
            trace["reduction"] = trace.get("reduction", 0) + 1
            log_file(f"long trace: reduced to {len(mm)} samples (time {trace['reduction']})")
        trace["state"] = st
        if st == "cancelling":
            trace["result"] = "cancelled"
        trace["duration_s"] = int(current_time - self.t0)
        if not is_active:
            self._finish(s, current_time)
        elif current_time - self.last_write >= _write_every(len(mm)):
            _write(trace)
            self.last_write = current_time

    def _other_job(self, job, current_time):
        """After sleeping, the same file may be ANOTHER pass: the
        current job has less time than the trace."""
        if not self.gap or self.key[0] != "file":
            return False
        dur = job.get("duration")
        if not isinstance(dur, (int, float)):
            return False
        return dur + 30 < current_time - self.t0

    def _begin(self, s, live, fname, key, current_time):
        g = dict((s.get("global") or {}))
        if "selectedMode" not in g and self.read_globals:
            g.update(self.read_globals())
        dur = (s.get("job") or {}).get("duration")
        # the view was opened in the middle of a file job: the real start
        t0 = current_time - dur if not live and isinstance(dur, (int, float)) and dur > 0 else current_time
        self.t0 = t0
        self.key = key
        self.replans = 0
        self.plan_t = current_time
        self.gap = False
        self.last_write = 0.0
        self.trace = {
            "active": True,
            "name": (live or {}).get("name") or (os.path.basename(fname) if fname else M("job_trace_job")),
            "origin": "live" if live else "file",
            "start": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
            "start_epoch": int(t0),
            "mode": g.get("selectedMode") or (s.get("state") or {}).get("machineMode"),
            "zone": (s.get("move") or {}).get("workplaceNumber"),
            "laserOffsetOn": g.get("laserOffsetOn"),
            "fields": ["t", "x", "y", "z", "pwm", "v", "air", "e", "layer", "rpm", "fpos"],
            "reduction": 0,
            "samples": [],
        }
        log_file(f"recording path: {self.trace['name']} ({self.trace['origin']})")
        if not live and fname:
            self._plan(fname, s)
        else:
            _remove_plan()
            self.plan_of = None

    def _plan(self, fname, om):
        trace = self.trace
        key = _key_plan(fname, om)
        if key is not None and key == self.plan_of and os.path.exists(PLAN_FILE):
            # same file in the same zone: the path is reused (only the start changes,
            # which the page compares with the trace's)
            try:
                with open(PLAN_FILE) as f:
                    d = json.load(f)
                d["start"] = trace.get("start")
                _write_json(PLAN_FILE, d)
                segments = d.get("segments") or []
                trace["plan"] = {"ok": True, "segments": len(segments), "vertices": sum(len(r.get("f") or []) for r in segments)}
                log_file(f"toolpath of {fname}: reusing the one already built")
                return
            except Exception as e:
                log_file(f"could not reuse the toolpath ({e}); building it again")
        _remove_plan()
        self.plan_of = None
        if self.arm_plan:
            self._arm_plan(fname, om, key)

    def _arm_plan(self, fname, om, key):
        """Reads the G-code in another thread (a big one takes seconds) and leaves
        trace["plan"] = {ok, vertices, tramos} or {ok: False, error}."""
        trace = self.trace
        trace["plan"] = {"ok": False, "assembling": True}
        kind = trace.get("mode")
        self.plans_armed += 1
        # copy of the model: the subscription keeps changing it while the file is read
        om = json.loads(json.dumps({"move": (om or {}).get("move") or {}}))

        def task():
            t = time.time()
            try:
                plan = gcode_plan.arm(_path_sd(fname), kind, om, tool0=self.tool_idle, wcs0=trace.get("zone"))
                rev = self.plans_armed
                _write_json(PLAN_FILE, {"file": fname, "start": trace.get("start"), "mode": kind, "rev": rev, "segments": plan})
                nv = sum(len(r["f"]) for r in plan)
                trace["plan"] = {"ok": True, "segments": len(plan), "vertices": nv, "rev": rev}
                self.plan_of = key
                log_file(f"toolpath of {fname}: {len(plan)} segments, {nv} vertices ({time.time() - t:.1f} s)")
            except Exception as e:
                trace["plan"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                log_file(f"could not read the toolpath of {fname} ({e})")

        threading.Thread(target=task, name="trace-plan", daemon=True).start()

    def _finish(self, s, current_time):
        trace = self.trace
        job = s.get("job") or {}
        trace["active"] = False
        trace["end"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(current_time))
        if self.gap:
            trace["end_approximate"] = True  # termino mientras nadie miraba
        elif trace.get("origin") == "file" and (job.get("lastFileCancelled") or job.get("lastFileAborted")):
            trace["result"] = "cancelled"  # the "cancelling" state lasts less than one sample
        trace.setdefault("result", "finished")
        if not self.gap:
            trace["duration_s"] = int(current_time - self.t0)
        _write(trace)
        _archive(trace)
        log_file(f"path finished: {len(trace['samples'])} samples, {trace.get('duration_s')} s")
        self.finished = trace  # before clearing self.trace: a reader in another thread always finds the job in one of them
        self.trace = None
        self.key = None
        self.gap = False


class Watchdog:
    """The loop: asleep it reads nothing; awake it passes the common model
    (machine_state) to the Recorder once per second. run_once() returns how
    long to wait until the next one."""

    def __init__(self, recorder, read_model=_read_model, in_live=_job_in_live, clock=time.time, monotonic=time.monotonic):
        self.g = recorder
        self.read_model = read_model
        self.in_live = in_live
        self.clock = clock
        self.monotonic = monotonic
        self.wakes = False

    def run_once(self):
        if not awake(self.monotonic()):
            if self.wakes:
                self.g.sleep()
                self.wakes = False
                log_file(f"sleeping: nobody has watched the job for {SLEEP_S} s")
            heartbeats.detail("trace", DETAIL_ASLEEP)
            heartbeats.ok("trace")
            return ASLEEP_STEP_S
        try:
            model = self.read_model()
            if not self.wakes:
                self.wakes = True
                log_file("waking up: someone is watching the job")
                heartbeats.detail("trace", DETAIL_AWAKE)
            self.g.step(model, self.in_live(), self.clock())
        except Exception as e:
            log_a_time(f"error ({type(e).__name__}: {e})", "vuelta-" + type(e).__name__)
            heartbeats.error("trace", e)
            return RETRY_S
        heartbeats.ok("trace")
        return SAMPLE_S


# The recorder of the running loop, read by trace_since.py (same process, other thread).
_running = {"recorder": None}


def recorder():
    return _running["recorder"]


def run_loop(bridge, config):
    log_file("starting (sleeps until someone opens the job view)")
    try:
        air = int(((config or {}).get("air_assist") or {}).get("gpout_index", AIR_GPOUT))
    except (TypeError, ValueError):
        air = AIR_GPOUT
    _running["recorder"] = Recorder(air_gpout=air)
    v = Watchdog(_running["recorder"])
    while True:
        time.sleep(v.run_once())
