"""
trace.since -- only the NEW samples of a job's trace since a cursor (2026-10-24).

The Workbench page used to read the whole trace (trace.json, every sample) and rebuild it each time. This operation gives
it only what was added since its last call, for file jobs and live jobs (network or USB bridge) alike, because both are
recorded by the same job_trace.Recorder.

Where the samples come from (nothing is duplicated, nothing new is written):
  - the job being recorded and the last one the recorder closed: job_trace.recorder().trace / .finished, in memory
    (a slice of the list, no file read at all);
  - an older job: its history file jobs/<id>.json (or trace.json when it is that one), parsed once and kept in a small
    cache keyed by size and date, so paging through it does not parse it again.

Cursor: "<job id>.<reduction>.<count>" (opaque for the client). count = samples already sent; reduction = how many times
the recorder halved the samples of a long job (job_trace.MAX_SAMPLES). A cursor of another job, of another reduction or
past the end answers from the first sample with reset = true (the client drops what it had). Asking for the job that is
being recorded (or "current") is also the heartbeat of the trace view: it keeps the recorder awake (job_trace.beat).

Deleting the trace: the job card's Delete button removes trace.json (a plain file delete through DSF, no operation of this
API), and so does anything else that removes that file. The recorder writes it before it keeps a closed job in memory
(atomic replace, never missing while it exists), so a missing trace.json with a closed job in memory means it was deleted:
the closed job is forgotten (job_trace.Recorder.forget_finished, plus the cached parse of trace.json) and "current" answers
nothing recorded until another job starts. Its history file jobs/<id>.json stays and is still read by its id.
"""
import json
import os
import re
import threading

import job_trace
from messages import M
from workshop_api import READ, Arg, ApiError, Op

CURRENT = "current"
LIMIT_DEFAULT = 2000
LIMIT_MAX = 10000
CACHE_MAX = 2  # parsed job files kept (the one being paged and the one before)
META_KEYS = ("name", "origin", "mode", "zone", "start", "end", "end_approximate", "duration_s", "result", "state",
             "laserOffsetOn", "plan", "fields", "reduction")

_JOB_ID = re.compile(r"^\d{8}-\d{6}$")
_CURSOR = re.compile(r"^(\d{8}-\d{6})\.(\d+)\.(\d+)$")

_cache = {}  # path -> ((mtime_ns, size), trace)
_cache_lock = threading.Lock()


def _load(path):
    """A trace file, parsed once per version of the file (size + date); None when missing or unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            trace = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(trace, dict):
        return None
    with _cache_lock:
        _cache.pop(path, None)
        _cache[path] = (key, trace)
        while len(_cache) > CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    return trace


def _forget_deleted(rec):
    """Forgets the closed job in memory when trace.json was deleted (see the module docstring)."""
    finished = rec.finished if rec is not None else None
    if finished is None or os.path.exists(job_trace.TRACE_FILE):
        return
    if rec.forget_finished(finished):
        with _cache_lock:
            _cache.pop(job_trace.TRACE_FILE, None)


def resolve(job):
    """(trace, in_memory) of a job id or CURRENT (the job being recorded, else the last one recorded); (None, False) when unknown."""
    rec = job_trace.recorder()
    _forget_deleted(rec)
    in_memory = [t for t in ((rec.trace, rec.finished) if rec is not None else ()) if t is not None]
    if job == CURRENT:
        if in_memory:
            return in_memory[0], True
        return _load(job_trace.TRACE_FILE), False
    for trace in in_memory:
        if job_trace.job_id(trace) == job:
            return trace, True
    trace = _load(os.path.join(job_trace.HIST_DIR, job + ".json"))
    if trace is None:
        last = _load(job_trace.TRACE_FILE)
        trace = last if last is not None and job_trace.job_id(last) == job else None
    return trace, False


def _snapshot(trace):
    """(reduction, samples list, count) read together: the recorder replaces the list and then counts the reduction."""
    for _ in range(3):
        reduction = trace.get("reduction") or 0
        samples = trace.get("samples") or []
        count = len(samples)
        if (trace.get("reduction") or 0) == reduction and (trace.get("samples") or []) is samples:
            break
    return reduction, samples, count


def _parse_cursor(cursor):
    if not cursor:
        return None
    m = _CURSOR.match(cursor)
    if m is None:
        raise ApiError("invalid_args", M("trace_since_bad_cursor"), field="cursor")
    return m.group(1), int(m.group(2)), int(m.group(3))


def since(args, ctx):
    job = args.get("job") or CURRENT
    if job != CURRENT and not _JOB_ID.match(job):
        raise ApiError("invalid_args", M("trace_since_bad_job"), field="job")
    cursor = _parse_cursor(args.get("cursor"))
    limit = args.get("limit") or LIMIT_DEFAULT
    trace, in_memory = resolve(job)
    if trace is None:
        if job == CURRENT:
            job_trace.beat()  # nothing recorded yet: wake the recorder in case a job is running
            return {"job": None, "active": False, "samples": [], "cursor": "", "done": True, "more": False, "reset": False, "meta": None}
        raise ApiError("not_found", M("trace_since_unknown_job"), job=job)
    active = bool(trace.get("active"))  # read before the samples: once false, no sample is added any more
    if job == CURRENT or (active and in_memory):
        job_trace.beat()
    jid = job_trace.job_id(trace)
    reduction, samples, count = _snapshot(trace)
    start, reset = 0, False
    if cursor is not None:
        if cursor[0] == jid and cursor[1] == reduction and cursor[2] <= count:
            start = cursor[2]
        else:
            reset = True
    end = min(count, start + limit)
    return {
        "job": jid,
        "active": active,
        "samples": samples[start:end],
        "cursor": "%s.%d.%d" % (jid, reduction, end),
        "done": not active and end >= count,
        "more": end < count,
        "reset": reset,
        "meta": {k: trace.get(k) for k in META_KEYS if k in trace},
    }


def ops():
    return [
        Op("trace.since", since, READ,
           {"job": Arg("str", desc="Id of the job (YYYYMMDD-HHMMSS, the id of the history) or \"current\" (default): the job being recorded, "
                                   "else the last one recorded (nothing once trace.json was deleted)."),
            "cursor": Arg("str", desc="The cursor of the previous answer; empty = from the first sample."),
            "limit": Arg("int", min=1, max=LIMIT_MAX, default=LIMIT_DEFAULT,
                         desc="Most samples in one answer (default %d, at most %d); more = true when there are more right now." % (LIMIT_DEFAULT, LIMIT_MAX))},
           "Only the samples of a job's trace added since the cursor (file jobs and live jobs): {job, active, samples, cursor, done, more, reset, "
           "meta}. reset = true: the cursor was of another job or the samples were reduced, so they come from the first one and the client drops "
           "what it had. done = true: the job ended and every sample was sent. Asking for the job being recorded keeps the recorder awake "
           "(like view.heartbeat trace). Deleting trace.json forgets the last closed job: \"current\" answers nothing recorded until another "
           "job starts (its history copy is still read by its id). Unknown job: not_found.",
           log=False),
    ]
