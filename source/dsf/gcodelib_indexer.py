"""The ONE background worker of the G-code library: reads a file once, streaming, and stores what it found in the cache.

    instance()                 the shared Indexer (cache under 0:/sys/workshop/data/gcodelib/, created on first use)
    Indexer.enqueue(path, urgent=False) / .state_of(...) / .index_one(path) / .rescan(dirs) / .run_loop(bridge, config)

The worker watches the folders the list looked at and, on its own, every sub-folder below them (files.scan_tree: 4 levels, no hidden
folders, 5000 files per folder and scan), so a file in a sub-folder is already indexed when somebody opens that folder.
One file at a time, at low priority (the thread asks the OS for a nice value and sleeps `throttle_s` after every chunk of lines, so the
machine's own work and the page are never starved). Pending files start NEWEST first; a file somebody asked for (urgent) jumps the queue.
Nothing here runs in an API request: the ops only queue and read the cache. The worker rests when the plugin that uses it (Printing)
is stopped (service_modules, process "gcodelib"), and when the setting `enabled` is false.
"""
import itertools
import os
import threading
import time

import gcode_temps
import gcodelib_cache as cache_mod
import gcodelib_files as files
import gcodelib_geo as geo
import gcodelib_parse as parse
import gcodelib_thumb as thumb
import heartbeats
import sd_paths
import service_modules
from messages import M

LABEL = "gcodelib"
SCAN_S = 30
DEFAULT_SETTINGS = {"enabled": True, "cache_mb": 200, "auto_index": True}
FOLDER = "sys/workshop/data/gcodelib"


class Abort(Exception):
    """The worker was asked to stop in the middle of a parse (nothing is stored)."""


def settings_from(value):
    """The `gcodelib` settings with their defaults and limits (a damaged value falls back to the defaults)."""
    out = dict(DEFAULT_SETTINGS)
    if isinstance(value, dict):
        if isinstance(value.get("enabled"), bool):
            out["enabled"] = value["enabled"]
        if isinstance(value.get("auto_index"), bool):
            out["auto_index"] = value["auto_index"]
        mb = value.get("cache_mb")
        if isinstance(mb, (int, float)) and not isinstance(mb, bool):
            out["cache_mb"] = max(10, min(4000, int(mb)))
    return out


def temps_summary(commands):
    """{"nozzle_c", "bed_c", "chamber_c"}: the first value above zero each kind of temperature command asks for."""
    out = {}
    for c in commands:
        temps = c.get("temps") or []
        if not temps or max(temps) <= 0:
            continue
        name = {"extruder": "nozzle_c", "bed": "bed_c", "chamber": "chamber_c"}.get(c["kind"])
        if name and name not in out:
            out[name] = max(temps)
    return out


class Indexer:
    def __init__(self, cache, settings=lambda: dict(DEFAULT_SETTINGS), sd_root=None, throttle_s=0.01, chunk_lines=4000, sleep=time.sleep,
                 log=print):
        self.cache = cache
        self.settings = settings
        self.sd_root = sd_root or (lambda: sd_paths.SD)
        self.throttle_s = throttle_s
        self.chunk_lines = chunk_lines
        self.sleep = sleep
        self.log = log
        self.lock = threading.Lock()
        self.queue = {}  # real path -> (urgent sequence, mtime_ns); urgent ones sort first
        self.current = None
        self.dirs = {files.DEFAULT_DIR}  # folders the list looked at (display form)
        self.wake = threading.Event()
        self.stop_flag = False
        self._seq = itertools.count(1)
        self.last_scan = 0.0
        self.parsed = 0  # files parsed since start (the tests and the status read it)

    # ---- queue ----
    def enqueue(self, path, urgent=False, mtime_ns=0):
        with self.lock:
            if path == self.current:
                return
            seq = next(self._seq) if urgent else 0
            old = self.queue.get(path)
            self.queue[path] = (max(seq, old[0]) if old else seq, mtime_ns or (old[1] if old else 0))
        self.wake.set()

    def pending_count(self):
        with self.lock:
            return len(self.queue) + (1 if self.current else 0)

    def next_path(self):
        """Urgent requests first (the latest asked first), then the newest file."""
        with self.lock:
            if not self.queue:
                return None
            path = max(self.queue, key=lambda p: (self.queue[p][0], self.queue[p][1]))
            del self.queue[path]
            return path

    def is_queued(self, path):
        with self.lock:
            return path in self.queue

    def state_of(self, path, size, mtime_ns):
        """(state, entry) of a file as the list shows it: ready / error / working / pending."""
        entry = self.cache.lookup(path, size, mtime_ns)
        if entry:
            return entry["state"], entry
        return ("working" if path == self.current else "pending"), None

    def rescan(self, force=False):
        """Queues every file of the watched folders AND of their sub-folders (files.scan_tree: bounded depth and count, no hidden folders) that
        has no valid entry; drops the entries of deleted files. Returns how many were queued. Never parses."""
        root = self.sd_root()
        queued = 0
        seen = set()
        self.cache.prune(os.path.exists)
        for d in sorted(self.dirs):
            try:
                real = files.resolve_dir(d, root)
            except (ValueError, OSError):
                continue
            found, truncated = files.scan_tree(real)
            if truncated:
                self.log("gcodelib: %s has more than %d G-code files with its sub-folders; the rest waits" % (d, files.MAX_FILES_PER_SCAN))
            for f in found:
                if f["path"] in seen:  # a watched folder inside another watched one
                    continue
                seen.add(f["path"])
                if self.cache.lookup(f["path"], f["size"], f["mtime_ns"]) is None:
                    self.enqueue(f["path"], mtime_ns=f["mtime_ns"])
                    queued += 1
        self.last_scan = time.monotonic()
        return queued

    # ---- indexing one file ----
    def _chunk(self, _lines):
        heartbeats.ok(LABEL)
        if self.stop_flag:
            raise Abort()
        if self.throttle_s:
            self.sleep(self.throttle_s)

    def index_one(self, path):
        """Reads `path` once and stores the result (or the error). Returns "ready", "error", "gone" or "changed"."""
        try:
            st = os.stat(path)
        except OSError:
            self.cache.drop(path)
            return "gone"
        size, mtime = st.st_size, st.st_mtime_ns
        writer = self.cache.begin(path)

        sampler = thumb.Sampler()

        def on_layer(info, segs, travel):
            writer.add_layer(geo.pack_layer(info["z"], segs, travel))
            sampler.add_layer(info, segs, travel)

        self.current = path
        try:
            with open(path, "rb") as fh:
                result = parse.parse_stream(fh, on_layer, self._chunk, self.chunk_lines, name=os.path.basename(path))
            if not result["thumbs"]:
                result["synth_thumb"] = sampler.render(result.get("plane", "3d"), result["types"])
            result["summary"]["has_preview_thumb"] = bool(result["thumbs"] or result.get("synth_thumb"))
            temps = gcode_temps.scan_file(path, 400)
            result["summary"].update(temps_summary(temps["commands"]))
            after = os.stat(path)
            if (after.st_size, after.st_mtime_ns) != (size, mtime):
                writer.abort()
                self.enqueue(path, mtime_ns=after.st_mtime_ns)  # it changed while it was read: again
                return "changed"
            self.cache.commit(path, size, mtime, result, writer, temps)
            self.parsed += 1
            return "ready"
        except Abort:
            writer.abort()
            return "stopped"
        except OSError as e:
            writer.abort()
            self.cache.mark_error(path, size, mtime, "gcodelib_err_unreadable", {"reason": str(e)[:80]})
            return "error"
        except Exception as e:  # noqa: BLE001 - a file the parser chokes on must not stop the worker
            writer.abort()
            self.cache.mark_error(path, size, mtime, "gcodelib_err_parse", {"reason": ("%s: %s" % (type(e).__name__, e))[:80]})
            return "error"
        finally:
            self.current = None

    # ---- the thread ----
    def _low_priority(self):
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass

    def run_once(self):
        """One pass of the loop; returns True when it indexed a file. Never raises."""
        cfg = self.settings()
        self.cache.cap = int(cfg["cache_mb"]) * 1024 * 1024
        if not service_modules.is_active(service_modules.PRINTING):
            heartbeats.ok(LABEL)
            heartbeats.detail(LABEL, M("gcodelib_at_rest_printing_plugin_stopped"))
            return False
        if not cfg["enabled"]:
            heartbeats.ok(LABEL)
            heartbeats.detail(LABEL, M("gcodelib_off_in_settings"))
            return False
        if cfg["auto_index"] and time.monotonic() - self.last_scan >= SCAN_S:
            self.rescan()
        self.cache.flush(force=False)
        path = self.next_path()
        heartbeats.ok(LABEL)
        if path is None:
            heartbeats.detail(LABEL, M("gcodelib_idle", files=len(self.cache.entries or {})))
            return False
        heartbeats.detail(LABEL, M("gcodelib_indexing", file=os.path.basename(path), pending=self.pending_count()))
        self.index_one(path)
        return True

    def run_loop(self, bridge=None, config=None, stop=lambda: False):
        self._low_priority()
        self.last_scan = -SCAN_S  # the first pass scans
        while not stop():
            try:
                busy = self.run_once()
            except Exception as e:  # noqa: BLE001
                heartbeats.error(LABEL, e)
                busy = False
            if not busy:
                self.wake.wait(3)
                self.wake.clear()
            else:
                self.sleep(self.throttle_s)


_instance = [None]


def _read_settings():
    import settings_store
    try:
        return settings_from(settings_store.get("gcodelib")["value"])
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_SETTINGS)


def instance():
    if _instance[0] is None:
        cache = cache_mod.Cache(sd_paths.sd(FOLDER))
        _instance[0] = Indexer(cache, settings=_read_settings)
    return _instance[0]


def configure(indexer):
    """For tests: another indexer (or None to start again)."""
    _instance[0] = indexer
