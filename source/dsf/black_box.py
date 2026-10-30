"""
Lightweight black box of the service (2026-10-12, item 11 of the diagnosis).

The Pi hung with a job and when it was force-restarted nothing was left (the
journal only kept ~2 h). This leaves its own circular log on the SD that
survives a forced shutdown:

- Every `interval_s` (5 s) ONE compact line (~150 bytes):
    2026-10-12 14:03:05 up=11532 load=1.23/1.10/0.95 cpu=37 svc=4 ram=41 temp=52.3 dsf=0.8s machine=processing job=pieza.gcode:34%
  and only if something happens: lock=bridge:25s (lock taken between samples), slow=trace:65s
  (internal process not beating), sd=230ms (the last fsync was slow), thr=0x50005
  (low voltage / throttling, from the last Health data), live=<live job>.
- Every `top_s` (60 s) a "top" line with the 3 threads of this service that used the most CPU (it does not look at other processes: AppArmor denies it).
- Loose events (everything that goes through activity.log_event, notices like
  "BRIDGE LOCK HELD >20 s", the API (blackbox) S"note"): "* type: text".
- Marks: "# start ..." and "# clean shutdown ...".

Files (0:/sys/workshop/data/blackbox/): blackbox-a.log and blackbox-b.log of
`file_kb` (512 KB) each. One is written until full and then it switches to
the other (emptying it): there are always between 1 and 2 files of history
(~5 to 10 h at 5 s). blackbox-state.json: boot_id, active file and whether the
shutdown was clean.

Writing: flush() on every line (it reaches the kernel: it survives the
service dying) and os.fsync() only every `fsync_s` (30 s) or right away with
an event or a mark. With the Pi hung at most ~30 s (6 lines) are lost. Why
not fsync on every line: each fsync forces rewriting at least one page of the
card (4-16 KB) plus the ext4 journal for ~150 useful bytes; every 30 s
that is ~2880 fsyncs/day (~30-50 MB/day of physical writing in the worst
case) against ~17000 if it were per line. The kernel flushes what is
pending every ~30 s anyway (dirty_expire), so a more frequent fsync adds
almost no safety. Useful data: ~2.5 MB/day. (DSF's journal wrote ~2 GB/day.)

At startup (check_startup): if the previous state has no clean shutdown
AND the boot_id changed (or, without boot_id, the uptime is less than the time
since the last data), the Pi was shut down without a close: a report with the last
lines in blackbox/unclean-report.txt (+ .json for the page), a "box_black"
event in Activity (phone notice if the type is active) and an "Last unclean
shutdown" card on the Services page (plugin data "boxBlack"). A service
restart (SIGTERM -> shut()) is clean; a service that dies on its own with the
Pi running (same boot_id) is noted but is not an unclean shutdown. A
requested full shutdown ("power" event) shortly before the last data is not either.

It reads the machine state ONLY from what someone else already read (machine_state,
without asking DSF for anything): the black box cannot add load or hang with DSF.

"""
import paths
import json
import os
import threading
import time
from messages import M, J, B

DEFAULTS = {
    "active": True,
    "interval_s": 5,
    "fsync_s": 30,
    "file_kb": 512,
    "top_s": 60,
    "lines_report": 120,   # lines in the report file
    "lines_page": 40,     # lines published for the card
    "power_margin_s": 900,   # "power" event up to 15 min before the last data = requested shutdown
}
FILES = ("blackbox-a.log", "blackbox-b.log")
STATE = "blackbox-state.json"
REPORT_TXT = "unclean-report.txt"
REPORT_JSON = "unclean-report.json"
PATH_SD = "sys/workshop/data/blackbox"
LOCK_EVENT_S = 20   # a lock held for that long also goes as an event
SD_SLOW_MS = 100    # an fsync slower than this shows in the line


def _dir_default():
    try:
        import sd_paths
        return sd_paths.sd(PATH_SD)
    except Exception:
        return paths.sd_file(PATH_SD)


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _ts(epoch=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch if epoch is not None else time.time()))


def _epoch(txt):
    try:
        return time.mktime(time.strptime(str(txt)[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _clean(raw_text, n=120):
    return " ".join(str(raw_text or "").split())[:n]


class BlackBox:
    def __init__(self, folder=None, cfg=None, proc="/proc", sys_dir="/sys", log=None):
        c = dict(DEFAULTS)
        c.update(cfg or {})
        self.cfg = c
        self.dir = folder or _dir_default()
        self.proc = proc
        self.sys = sys_dir
        self.log = log or (lambda m: None)
        self.max_bytes = max(4096, int(float(c["file_kb"]) * 1024))
        # RLock: shut() runs in the SIGTERM handler, which can land in
        # the same thread (the main one) in the middle of a write
        self.lock = threading.RLock()        # file of lines
        self.lock_state = threading.RLock() # blackbox-state.json
        self.f = None
        self.is_active = 0
        self.last_fsync = 0.0
        self.sd_ms = None
        self.status = {}
        self.closed = False
        self.locks = {}             # nombre -> threading.Lock a vigilar
        self._lock_since = {}       # name -> monotonic since it was seen taken
        self._lock_notified = set()
        self._cpu_prev = None
        self._svc_prev = None
        self._top_prev = None
        self._top_t = 0.0
        self.sources = {}           # funciones opcionales (estado, latidos, salud...)

    # ---------------- system readings ----------------

    def boot_id(self):
        return _read(os.path.join(self.proc, "sys/kernel/random/boot_id"))

    def uptime_s(self):
        u = _read(os.path.join(self.proc, "uptime"))
        try:
            return float(u.split()[0])
        except Exception:
            return None

    def _load(self):
        try:
            if self.proc == "/proc":
                return os.getloadavg()
        except (OSError, AttributeError):
            pass
        t = _read(os.path.join(self.proc, "loadavg"))
        try:
            return [float(x) for x in t.split()[:3]]
        except Exception:
            return None

    def _cpu_pct(self):
        t = _read(os.path.join(self.proc, "stat"))
        try:
            fields = [int(x) for x in t.split("\n", 1)[0].split()[1:]]
        except Exception:
            return None
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields[:8])
        prev, self._cpu_prev = self._cpu_prev, (total, idle)
        if not prev or total <= prev[0]:
            return None
        return round(100 * (1 - (idle - prev[1]) / (total - prev[0])))

    def _svc_pct(self):
        t = _read(os.path.join(self.proc, "self/stat"))
        try:
            c = t.rsplit(")", 1)[1].split()
            ticks = int(c[11]) + int(c[12])
        except Exception:
            return None
        current_time = time.monotonic()
        prev, self._svc_prev = self._svc_prev, (ticks, current_time)
        if not prev or current_time <= prev[1]:
            return None
        return round((ticks - prev[0]) / _hz() / (current_time - prev[1]) * 100)

    def _ram_pct(self):
        t = _read(os.path.join(self.proc, "meminfo"))
        try:
            d = {}
            for line in t.splitlines():
                k, v = line.split(":", 1)
                d[k] = int(v.split()[0])
            return round(100 * (1 - d["MemAvailable"] / d["MemTotal"]))
        except Exception:
            return None

    def _temp(self):
        t = _read(os.path.join(self.sys, "class/thermal/thermal_zone0/temp"))
        try:
            return round(int(t) / 1000.0, 1)
        except Exception:
            return None

    def _top(self):
        """CPU of this service's own threads since the previous round (every
        top_s). It never opens another process's /proc entries: AppArmor denies
        that for this plugin (ptrace read) and logs a DENIED line each time."""
        current_time = time.monotonic()
        ticks = {}
        base = os.path.join(self.proc, "self", "task")
        try:
            tids = os.listdir(base)
        except OSError:
            return None
        for tid in tids:
            t = _read(os.path.join(base, tid, "stat"))
            if not t:
                continue
            try:
                label = t[t.index("(") + 1:t.rindex(")")]
                c = t.rsplit(")", 1)[1].split()
                ticks[tid] = (label, int(c[11]) + int(c[12]))
            except (ValueError, IndexError):
                continue
        prev, self._top_prev = self._top_prev, (ticks, current_time)
        if not prev or current_time <= prev[1]:
            return None
        dt = current_time - prev[1]
        uses = []
        for tid, (label, tk) in ticks.items():
            before = prev[0].get(tid)
            if before and before[0] == label and tk >= before[1]:
                pct = (tk - before[1]) / _hz() / dt * 100
                if pct >= 1:
                    uses.append((pct, label))
        uses.sort(reverse=True)
        return " ".join(f"{n.replace(' ', '_')}={round(p)}%" for p, n in uses[:3]) or "-"

    # ---------------- linea ----------------

    def _source(self, label, *a):
        f = self.sources.get(label)
        if f is None:
            return None
        try:
            return f(*a)
        except Exception:
            return None

    def line(self):
        parts = []
        up = self.uptime_s()
        if up is not None:
            parts.append(f"up={int(up)}")
        loading = self._load()
        if loading:
            parts.append("load=" + "/".join(f"{x:.2f}" for x in loading))
        for k, v in (("cpu", self._cpu_pct()), ("svc", self._svc_pct()), ("ram", self._ram_pct()), ("temp", self._temp())):
            if v is not None:
                parts.append(f"{k}={v}")
        lect = self._source("reading")
        if lect:
            ms, age = lect.get("ms"), lect.get("age_s")
            # with the common subscription there are no requests: only the age of the last patch
            txt = "dsf=" + ("" if ms is None else f"{int(ms)}ms")
            if age is not None:
                txt += ("" if ms is None else "/") + f"{age:.1f}s"
            elif ms is None:
                txt += "?"
            if lect.get("error"):
                txt += "/" + _clean(lect["error"], 30).replace(" ", "_")
            parts.append(txt)
        ipc = self._source("ipc")
        if ipc is not None:
            parts.append(f"ipc={int(ipc)}")  # IPC calls to DCS in the last minute (ipc_stats.py)
        st = self._source("state")
        if isinstance(st, dict):
            machine = ((st.get("state") or {}).get("status")) or "?"
            parts.append(f"machine={machine}")
            job = st.get("job") or {}
            file = (job.get("file") or {})
            label = file.get("fileName")
            if label:
                pct = ""
                try:
                    pct = f":{100 * float(job.get('filePosition') or 0) / float(file.get('size')):.0f}%"
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
                parts.append("job=" + os.path.basename(str(label)).replace(" ", "_")[:60] + pct)
        live = self._source("live")
        if live:
            parts.append("live=" + _clean(live, 40).replace(" ", "_"))
        taken = self._locks_taken()
        if taken:
            parts.append("lock=" + ",".join(f"{n}:{int(s)}s" for n, s in taken))
        slow = self._source("slow")
        if slow:
            parts.append("slow=" + ",".join(f"{n}:{int(s)}s" for n, s in slow))
        if self.sd_ms is not None and self.sd_ms >= SD_SLOW_MS:
            parts.append(f"sd={int(self.sd_ms)}ms")
        thr = self._source("throttled")
        if thr:
            parts.append(f"thr={thr}")
        return " ".join(parts)

    def _locks_taken(self):
        current_time = time.monotonic()
        out = []
        for n, lk in self.locks.items():
            try:
                claimed = lk.locked()
            except Exception:
                continue
            if not claimed:
                self._lock_since.pop(n, None)
                self._lock_notified.discard(n)
                continue
            since = self._lock_since.setdefault(n, current_time)
            dur = current_time - since
            if dur > 0:
                out.append((n, dur))
            if dur >= LOCK_EVENT_S and n not in self._lock_notified:
                self._lock_notified.add(n)
                self.event("notice", f"{n.upper()} LOCK HELD >{LOCK_EVENT_S} s")
        return out

    # ---------------- archivos ----------------

    def _path(self, i):
        return os.path.join(self.dir, FILES[i])

    def _read_state(self):
        try:
            with open(os.path.join(self.dir, STATE)) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    def _save_state(self, **changes):
        with self.lock_state:
            self.status.update(changes)
            p = os.path.join(self.dir, STATE)
            tmp = p + ".tmp"
            try:
                with open(tmp, "w") as f:
                    json.dump(self.status, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, p)
                self._fsync_dir()
            except Exception as e:
                self.log(f"black box: could not save the state ({e})")

    def _fsync_dir(self):
        if os.name != "posix":
            return
        try:
            fd = os.open(self.dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def _open(self, i, empty=False):
        if self.f is not None:
            try:
                self.f.close()
            except Exception:
                pass
        self.is_active = i
        self.f = open(self._path(i), "wb" if empty else "ab")

    def write_out(self, raw_text, sync=False):
        """A line with a time. It rotates to the other file if it does not fit."""
        line = (f"{_ts()} {raw_text}".replace("\n", " ") + "\n")
        payload = line.encode("utf-8")
        with self.lock:
            if self.f is None:
                return
            try:
                if self.f.tell() + len(payload) > self.max_bytes:
                    self._sync()
                    self._open(1 - self.is_active, empty=True)
                    self._save_state(active=self.is_active)
                self.f.write(payload)
                self.f.flush()
                if sync or time.monotonic() - self.last_fsync >= float(self.cfg["fsync_s"]):
                    self._sync()
            except Exception as e:
                self.log(f"black box: could not write ({e})")

    def _sync(self):
        t0 = time.monotonic()
        try:
            self.f.flush()
            os.fsync(self.f.fileno())
        except Exception:
            pass
        self.last_fsync = time.monotonic()
        self.sd_ms = (self.last_fsync - t0) * 1000

    def last_lines(self, n, is_active=None):
        """The last n lines of the history (old file + active)."""
        if is_active is None:
            is_active = self.is_active
        out = []
        for i in (1 - is_active, is_active):
            try:
                with open(self._path(i), "rb") as f:
                    f.seek(0, os.SEEK_END)
                    length = f.tell()
                    f.seek(max(0, length - 400 * n))
                    # after a power cut the file can end with a block of NUL bytes (allocated, never written): drop them
                    piece = f.read().decode("utf-8", "replace").replace(chr(0), "")
                lines = piece.split("\n")
                if length > 400 * n:
                    lines = lines[1:]  # the first one may be cut off
                out.extend(x for x in lines if x.strip())
            except OSError:
                continue
        return out[-n:]

    # ---------------- arranque / cierre ----------------

    def check_startup(self):
        """Before writing anything: what happened the previous time.
        Returns (type, info) with type in primera | limpio | servicio |
        shutdown_request | no_clean."""
        prev = self._read_state()
        bid = self.boot_id()
        up = self.uptime_s()
        current_time = time.time()
        if not prev:
            return "first", {}
        is_active = prev.get("active") if prev.get("active") in (0, 1) else 0
        lines = self.last_lines(int(self.cfg["lines_report"]), is_active)
        last_txt = lines[-1][:19] if lines else None
        last = _epoch(last_txt) or prev.get("last_datum")
        info = {
            "boot_previous": prev.get("boot_id"),
            "boot_current": bid,
            "start_previous": prev.get("start"),
            "last_datum": last_txt,
            "lines": lines,
        }
        if prev.get("close"):
            return "clean", info
        if bid and prev.get("boot_id"):
            restart_pi = bid != prev.get("boot_id")
        else:
            # without boot_id: did the Pi boot after the last data?
            ref = last or prev.get("start_epoch")
            restart_pi = bool(up is not None and ref and up < current_time - float(ref))
        if not restart_pi:
            return "service", info
        p = prev.get("power_epoch")
        ref = last or prev.get("start_epoch") or 0
        if p and ref and -60 <= float(ref) - float(p) <= float(self.cfg["power_margin_s"]):
            return "shutdown_request", info
        return "no_clean", info

    def save_report(self, info):
        lines = info.get("lines") or []
        cab = [
            "Workshop black box: unclean shutdown of the system",
            f"Detected: {_ts()}",
            f"Last data: {info.get('last_datum') or '?'} (previous boot {info.get('boot_previous') or '?'}, service started {info.get('start_previous') or '?'})",
            f"New boot: {info.get('boot_current') or '?'}",
            f"One line every {self.cfg['interval_s']} s. Last {len(lines)} lines:",
            "",
        ]
        rep = {
            "detected": _ts(),
            "last_datum": info.get("last_datum"),
            "boot_previous": info.get("boot_previous"),
            "start_previous": info.get("start_previous"),
            "lines": lines[-int(self.cfg["lines_page"]):],
            "total_lines": len(lines),
            "file": "0:/" + PATH_SD + "/" + REPORT_TXT,
            "seen": False,
        }
        try:
            for label, content in ((REPORT_TXT, "\n".join(cab + lines) + "\n"), (REPORT_JSON, json.dumps(rep, ensure_ascii=False))):
                p = os.path.join(self.dir, label)
                with open(p + ".tmp", "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(p + ".tmp", p)
        except Exception as e:
            self.log(f"black box: could not save the report ({e})")
        return rep

    def report(self):
        try:
            with open(os.path.join(self.dir, REPORT_JSON), encoding="utf-8") as f:
                rep = json.load(f)
            return rep
        except Exception:
            return None

    def mark_seen(self):
        rep = self.report()
        if not rep:
            return None
        rep["seen"] = True
        p = os.path.join(self.dir, REPORT_JSON)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        return rep

    def mark_not_seen(self):
        rep = self.report()
        if not rep:
            return None
        rep["seen"] = False
        p = os.path.join(self.dir, REPORT_JSON)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        return rep

    def open_it(self):
        """Checks the previous startup, opens the file and writes the startup mark.
        Returns (type, info, report_or_None)."""
        os.makedirs(self.dir, exist_ok=True)
        type_name, info = self.check_startup()
        prev = self._read_state() or {}
        rep = None
        if type_name == "no_clean":
            rep = self.save_report(info)
        is_active = prev.get("active") if prev.get("active") in (0, 1) else 0
        with self.lock:
            self._open(is_active)
        current_time = time.time()
        self.status = {"boot_id": self.boot_id(), "pid": os.getpid(), "start": _ts(current_time),
                       "start_epoch": int(current_time), "active": self.is_active, "close": False}
        self._save_state()
        self.write_out(f"# start boot={(self.status['boot_id'] or '?')[:8]} pid={os.getpid()} "
                      f"interval={self.cfg['interval_s']}s previous={type_name}"
                      + (f" last_data={info.get('last_datum')}" if type_name not in ("first", "clean") else ""),
                      sync=True)
        return type_name, info, rep

    def sample(self):
        self.write_out(self.line())
        top_s = float(self.cfg.get("top_s") or 0)
        if top_s > 0 and time.monotonic() - self._top_t >= top_s:
            self._top_t = time.monotonic()
            t = self._top()
            if t:
                self.write_out("top " + t)

    def event(self, type_name, raw_text):
        if type_name == "power":
            self._save_state(power_epoch=int(time.time()))
        self.write_out(f"* {type_name}: {_clean(raw_text, 200)}", sync=True)

    def shut(self, reason=""):
        if self.closed:
            return
        self.closed = True
        # the state first (what matters); the line with the bounded lock
        self._save_state(close=True, cierre_ts=_ts(), last_datum=int(time.time()))
        if self.lock.acquire(timeout=2):
            try:
                if self.f is not None:
                    self.f.write((f"{_ts()} # clean shutdown {reason}".rstrip() + "\n").encode("utf-8"))
                    self._sync()
                    self.f.close()
                    self.f = None
            except Exception:
                pass
            finally:
                self.lock.release()


def _hz():
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        return 100


# ---------------- integration with the service ----------------

_box = {"c": None, "pending": [], "bridge": None}


def _sources_service(bridge):
    """What the black box reads from the rest of the service, without asking for anything new."""
    import machine_state

    def reading():
        f = getattr(machine_state, "last_reading", None)
        if f:
            return f()
        c = getattr(machine_state, "_cache", None) or {}
        return {"ms": None, "age_s": (time.monotonic() - c["at"]) if c.get("at") else None}

    def status():
        f = getattr(machine_state, "last_state", None)
        if f:
            return f()
        return (getattr(machine_state, "_cache", None) or {}).get("status")

    def live():
        st = (getattr(bridge, "payload", None) or {}).get("liveJob")
        if isinstance(st, dict) and st.get("active"):
            return st.get("name")
        return None

    def slow():
        import heartbeats
        current_time = time.time()
        out = []
        for n, d in list(heartbeats._info.items()):
            u, e = d.get("last_ok"), d.get("expected_s") or 0
            if d.get("live") and u and e and current_time - u > 2 * e:
                out.append((n, current_time - u))
        return out

    def throttled():
        thr = ((getattr(bridge, "payload", None) or {}).get("healthPi") or {}).get("throttled") or {}
        raw = thr.get("raw")
        return raw if raw and raw != "0x0" else None

    def ipc():
        import ipc_stats
        return ipc_stats.per_minute()

    return {"reading": reading, "ipc": ipc, "state": status, "live": live, "slow": slow, "throttled": throttled}


def emit(bridge=None):
    b = bridge or _box["bridge"]
    c = _box["c"]
    if b is None or c is None:
        return
    rep = c.report()
    try:
        b.set_status("boxBlack", {
            "active": True,
            "interval_s": c.cfg["interval_s"],
            "file_kb": int(c.max_bytes / 1024),
            "folder": "0:/" + PATH_SD,
            "report": rep if rep and not rep.get("seen") else None,
            # fixed row of the Services page: stays after the card is hidden (the report file is never deleted)
            "last_drop": {"last_datum": rep.get("last_datum"), "detected": rep.get("detected"), "file": rep.get("file"), "seen": bool(rep.get("seen"))} if rep else None,
        })
    except Exception:
        pass


def run_loop(c):
    import heartbeats
    interval = max(1.0, float(c.cfg["interval_s"]))
    prox = time.monotonic()
    while not c.closed:
        c.sample()
        heartbeats.ok("box_black")
        prox += interval
        waiting = prox - time.monotonic()
        if waiting < 0:  # atrasada (Pi trabada): no recuperar muestras perdidas
            prox = time.monotonic()
            waiting = 0
        time.sleep(waiting)


def launch(bridge, config, log=None, locks=None, box=None):
    """Call it from main.py after notifier.init (the phone notice
    needs the notifier). locks: {"bridge": bridge.lock, ...}.
    box: an already built BlackBox (tests)."""
    cfg = dict(DEFAULTS)
    cfg.update(config.get("box_black") or {})
    if not cfg.get("active", True):
        return None
    import activity
    import heartbeats
    c = box or BlackBox(cfg=cfg, log=log)
    c.locks = dict(locks or {})
    c.sources = _sources_service(bridge)
    _box["bridge"] = bridge
    try:
        type_name, info, rep = c.open_it()
    except Exception as e:
        if log:
            log(f"black box: does not start ({e})")
        return None
    _box["c"] = c
    for t, x in _box["pending"]:
        c.event(t, x)
    _box["pending"].clear()
    if log:
        log(f"black box: {c.dir} (previous: {type_name})")
    if type_name == "no_clean":
        latest = (info.get("lines") or [""])
        last_state = next((x for x in reversed(latest) if " up=" in x), "")
        summary = _clean(last_state[20:], 160)
        raw_text = M("box_black_unclean", datum=info.get("last_datum") or "?", summary=M("box_black_summary", text=summary) if summary else "")
        try:
            activity.log_event(bridge, "box_black", raw_text)
        except Exception as e:
            if log:
                log(f"black box: could not record the warning ({e})")
    emit(bridge)
    heartbeats.register("box_black", M("black_box_black_box"),
                      M("black_box_one_line_load_cpu_ram_temperature", interval_s=cfg['interval_s']),
                      max(30, 6 * int(cfg["interval_s"])))
    heartbeats.launch("box_black", run_loop, c)
    return c


def event(type_name, raw_text):
    """Loose event (called by activity.log_event with all the events)."""
    c = _box["c"]
    if c is None:
        if len(_box["pending"]) < 50:
            _box["pending"].append((type_name, raw_text))
        return
    c.event(type_name, raw_text)


def shut(reason="SIGTERM"):
    c = _box["c"]
    if c is not None:
        c.shut(reason)


def show(bridge=None):
    c = _box["c"]
    if c is None:
        return None
    rep = c.mark_not_seen()
    emit(bridge)
    return rep


def hide(bridge=None):
    c = _box["c"]
    if c is None:
        return None
    rep = c.mark_seen()
    emit(bridge)
    return rep
