"""
Listens to DSF LIVE and records in the activity what job_poller.py's 5 s
poll does not see well. 2026-10-12: it no longer opens its own subscription;
it receives the patches of the single subscription (machine_state.on_change):

  - EMERGENCY STOP (state.status -> "halted")              -> "emergencia"
  - pause / resume of a job                                 -> "job_pause"
  - RRF errors / warnings                                   -> "error" / "aviso"
    Two sources: the object model messages (notices that RRF sends to
    everyone, e.g. from a file job or from daemon.g) and, above all, the
    RRF event log (sys/eventlog.txt, M929), which also keeps the errors of
    codes sent over a specific channel -- e.g. the "G1:
    target position outside machine limits" of a live job, which as a direct
    response NEVER appear in the object model messages.
  - if RRF's event log turns off (it happened on 2026-10-08 at
    09:08 without anyone asking), it is reactivated and a notice is given.

RRF messages are transient: they appear in an object model patch and are
erased right away, so polling them over HTTP every so often is no use.
The same message repeated in a burst (a live job out of
limits throws the same error on every line) is recorded ONCE, and if it was
repeated a summary is added when the burst ends.

Ported from ~/duet-notify/notify.py (a separate service that is replaced):
notifications now come out of activity.log_event() -> notifier.py.

"""
import paths
import os
import queue
import re
import threading
import time

import heartbeats

import activity
import machine_state
from messages import M, Msg

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop-service.log")
REPEAT_WINDOW_S = 30  # same message within this window = same burst
EVENTLOG = paths.SYS + "/eventlog.txt"
EVENTLOG_POLL_S = 2
LOGCHECK_S = 60
MSG_MAX = 300
QUEUE_MAX = 1000  # patches pending to process (if it fills up they are discarded)
_listener = [None]

# DSF MessageType: 0 = success/info, 1 = warning, 2 = error
_KIND_MSG = {1: "notice", 2: "error"}

# Output of a plugin redirected to DWC (sbcOutputRedirected): DSF sends ONE
# message per line, "[Plugin]: text". A Python traceback used to arrive as
# ~20 loose "Error" events (seen 2026-10-08 22:49). Consecutive lines
# from the same plugin are merged into a single event.
_PLUGIN_LINE = re.compile(r"^\[([A-Za-z0-9_. -]+)\]: ?(.*)$", re.S)
PLUGIN_QUIET_S = 2  # no new lines in this time = complete message


def _summary_plugin(lines):
    """A readable line of an output block: if it is a traceback, the final
    exception (the last line with text, not the ^^^ / ~~~)."""
    useful = [l.strip() for l in lines if l.strip() and not set(l.strip()) <= set("^~ ")]
    if not useful:
        return ""
    es_tb = any(l.startswith("Traceback") or l.startswith("Exception in thread") for l in useful)
    if es_tb:
        return M("event_watcher_traceback_summary", line=useful[-1][:MSG_MAX - 100], n=len(lines))
    return useful[0] if len(useful) == 1 else M("event_watcher_more_lines", line=useful[0][:MSG_MAX - 40], n=len(useful) - 1)


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [event_watcher] {msg}\n")
    except Exception:
        pass




class _Bursts:
    """Groups equal repeated messages: records the first one instantly and,
    when the burst ends, how many times it repeated."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.seen = {}  # (tipo, texto) -> {"ultimo": t, "repetidos": n}
        self.blocks = {}  # plugin -> {"tipo", "lineas", "ultimo"}
        self.lock = threading.Lock()

    def message(self, type_name, raw_text):
        m = _PLUGIN_LINE.match(raw_text)
        if m:
            with self.lock:
                b = self.blocks.setdefault(m.group(1), {"kind": type_name, "lines": [], "last": 0})
                if type_name == "error":
                    b["kind"] = "error"
                b["lines"].append(m.group(2))
                b["last"] = time.time()
            return
        self._register(type_name, raw_text)

    def close_blocks(self):
        current_time = time.time()
        ready = []
        with self.lock:
            for plugin, b in list(self.blocks.items()):
                if current_time - b["last"] >= PLUGIN_QUIET_S:
                    ready.append((plugin, b))
                    del self.blocks[plugin]
        for plugin, b in ready:
            r = _summary_plugin(b["lines"])
            if r:
                m = M("event_watcher_plugin_output", plugin=plugin, text=r)
                if len(m) > MSG_MAX:  # cut the plugin's own text, so the message keeps its key (the page translates it)
                    m = M("event_watcher_plugin_output", plugin=plugin, text=str(r)[:max(0, len(str(r)) - (len(m) - MSG_MAX))])
                self._register(b["kind"], m)

    def _register(self, type_name, raw_text):
        # the same key whether it comes from the object model ("G1: ...") or from the eventlog
        # ("Error: G1: ..."): an error is not recorded twice
        for pre in ("Error: ", "Warning: "):
            if not isinstance(raw_text, Msg) and raw_text.startswith(pre):
                raw_text = raw_text[len(pre):]
        current_time = time.time()
        key = (type_name, raw_text)
        with self.lock:
            v = self.seen.get(key)
            if v and current_time - v["last"] < REPEAT_WINDOW_S:
                v["last"] = current_time
                v["repeated"] += 1
                return
            self.seen[key] = {"last": current_time, "repeated": 0}
        activity.log_event(self.bridge, type_name, raw_text)

    def close_old(self):
        current_time = time.time()
        shut = []
        with self.lock:
            for key, v in list(self.seen.items()):
                if current_time - v["last"] >= REPEAT_WINDOW_S:
                    if v["repeated"] > 0:
                        shut.append((key, v["repeated"]))
                    del self.seen[key]
        for (type_name, raw_text), n in shut:
            activity.log_event(self.bridge, type_name, M("repeated", n=n, text=raw_text if isinstance(raw_text, Msg) else raw_text[:MSG_MAX]))


def _follow_eventlog(bursts):
    """Reads the new lines of sys/eventlog.txt ("YYYY-MM-DD HH:MM:SS text")."""
    pos = None
    rest = ""
    while True:
        try:
            length = os.path.getsize(EVENTLOG)
            if pos is None or length < pos:  # startup (from the end) or new file
                pos = length if pos is None else 0
                rest = ""
            elif length > pos:
                with open(EVENTLOG, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    payload = f.read()
                    pos = f.tell()
                lines = (rest + payload).split("\n")
                rest = lines.pop()
                for line in lines:
                    raw_text = line[20:].strip() if len(line) > 20 and line[4] == "-" else line.strip()
                    if _PLUGIN_LINE.match(raw_text.split(": ", 1)[-1] if raw_text.startswith(("Error:", "Warning:")) else raw_text):
                        continue  # output of a plugin: it already arrives (grouped) through the object model
                    if raw_text.startswith("Error:"):
                        bursts.message("error", raw_text[:MSG_MAX])
                    elif raw_text.startswith("Warning:"):
                        bursts.message("notice", raw_text[:MSG_MAX])
        except FileNotFoundError:
            pos = 0
        except Exception as e:
            log_file(f"eventlog: {e}")
        time.sleep(EVENTLOG_POLL_S)


def _watch_record_rrf(bridge):
    """Keeps RRF's event log (M929) turned on."""
    while True:
        try:
            st = machine_state.read_in("state", {}) or {}
            if not st.get("logFile"):
                bridge.send('M929 P"eventlog.txt" S1')
                activity.log_event(bridge, "notice", M("eventlog_reactivated"))
        except Exception as e:
            log_file(f"RRF log: {e}")
        time.sleep(LOGCHECK_S)


def run_loop(bridge, config):
    bursts = _Bursts(bridge)
    threading.Thread(target=_follow_eventlog, args=(bursts,), daemon=True).start()
    threading.Thread(target=_watch_record_rrf, args=(bridge,), daemon=True).start()

    def _sweep():
        while True:
            time.sleep(1)
            try:
                bursts.close_blocks()
                bursts.close_old()
            except Exception as e:
                log_file(f"sweep: {e}")

    threading.Thread(target=_sweep, daemon=True).start()

    backlog = queue.Queue(maxsize=QUEUE_MAX)

    def listener(patch, full):
        # in the subscription thread: only enqueue
        if full or "messages" in patch or "status" in (patch.get("state") or {}):
            try:
                backlog.put_nowait((patch, full))
            except queue.Full:
                pass

    if _listener[0] is not None:  # the thread was relaunched: out with the old listener
        machine_state.unsubscribe(_listener[0])
    _listener[0] = listener
    machine_state.on_change(listener)
    log_file("listening to the single subscription (state.status, messages)")
    try:
        status = machine_state.read_in("state.status", timeout=10)
    except Exception:
        status = None
    while True:
        try:
            patch, full = backlog.get(timeout=3)
        except queue.Empty:
            heartbeats.ok("events")  # no change: normal
            continue
        heartbeats.ok("events")
        try:
            status = process(bridge, bursts, patch, full, status)
        except Exception as e:
            log_file(f"error processing a patch: {e}")
            heartbeats.error("events", e)


def process(bridge, bursts, patch, full, status):
    """A subscription patch -> events. Returns the new state.status."""
    if full:
        # (re)connection: the whole model; old messages are not repeated
        new = (patch.get("state") or {}).get("status")
        if new != status:
            log_file(f"state on connecting: {new}")
        return new
    for m in patch.get("messages") or []:
        type_name = _KIND_MSG.get(m.get("type"))
        raw_text = str(m.get("content") or "").strip()
        if type_name and raw_text:
            bursts.message(type_name, raw_text[:MSG_MAX])
    st = patch.get("state") or {}
    if "status" not in st:
        return status
    new = st["status"]
    if new != status:
        if new == "halted":
            activity.log_event(bridge, "emergency", M("emergency_stop"))
        elif new == "paused" and status in ("processing", "pausing"):
            activity.log_event(bridge, "job_pause", M("job_paused"))
        elif new == "processing" and status in ("paused", "resuming"):
            activity.log_event(bridge, "job_pause", M("job_resumed"))
    return new
