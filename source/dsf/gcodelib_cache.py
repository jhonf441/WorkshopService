"""Cache of the G-code library on the SD (0:/sys/workshop/data/gcodelib/): what the parser found, kept so a file is read ONCE.

Layout of the folder (everything is rebuildable: deleting it only costs a re-index):
    index.json        {"version", "entries": {key: entry}} -- one small entry per file (summary only), loaded in memory once
    <key>.json        the detail of one file: header comments, temperature commands, layers table, layer offsets, thumbnail list
    <key>.geo         the geometry: the zlib blobs of the layers one after the other (gcodelib_geo.pack_layer); offsets are in <key>.json
    <key>.<i>.png     the thumbnails embedded in the file
    <key>.thumb.png   a synthetic thumbnail drawn by gcodelib_thumb when the file has geometry but no thumbnail of its own
`key` is the sha1 of the path of the file (a file that moves is a new file). An entry is valid while its parser VERSION, the size and the
modification time of the file are the same as when it was read; anything else makes the file "pending" again. Every write is atomic
(temporary file + os.replace), so a power cut leaves the old or the new file, never half of one.

The total size is capped (cap_bytes). Over the cap the entries used LEAST recently lose their heavy files (geometry, thumbnails, detail)
but keep their summary in the index: the list still shows them and nothing is re-parsed in a loop; a page that asks for the geometry or the
thumbnail of an evicted file makes the indexer read it again (state "pending").
"""
import hashlib
import json
import os
import struct
import threading
import time

VERSION = 4   # 4: thumbnail palette without light blue (every file is drawn again); 3: synthetic thumbnails (<key>.thumb.png) and summary.has_preview_thumb; 2: kind / tags / plane, 2D toolpaths, .gc .ngc .tap
DEFAULT_CAP = 200 * 1024 * 1024
FLUSH_EVERY_S = 60


def key_of(path):
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()


def _atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


class Writer:
    """Receives the layers of ONE file while it is parsed (streamed to a temporary file): add_layer(blob) -> nothing in memory."""

    def __init__(self, tmp_path, max_bytes):
        self.tmp = tmp_path
        self.fh = open(tmp_path, "wb")
        self.offsets = []  # [offset, length] of every layer
        self.pos = 0
        self.max_bytes = max_bytes
        self.truncated = False

    def add_layer(self, blob):
        if self.truncated or self.pos + len(blob) > self.max_bytes:
            self.truncated = True
            self.offsets.append([self.pos, 0])  # keeps the layer numbers aligned, nothing to read
            return
        self.fh.write(blob)
        self.offsets.append([self.pos, len(blob)])
        self.pos += len(blob)

    def close(self):
        if not self.fh.closed:
            self.fh.close()

    def abort(self):
        self.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass


class Cache:
    def __init__(self, folder, cap_bytes=DEFAULT_CAP, clock=time.time, max_geo_bytes=60 * 1024 * 1024):
        self.folder = folder
        self.cap = int(cap_bytes)
        self.clock = clock
        self.max_geo = max_geo_bytes
        self.lock = threading.RLock()
        self.entries = None
        self.dirty = False
        self.last_flush = 0.0

    # ---- paths ----
    def _p(self, key, ext):
        return os.path.join(self.folder, key + ext)

    def _load(self):
        if self.entries is not None:
            return
        os.makedirs(self.folder, exist_ok=True)
        self.entries = {}
        try:
            with open(os.path.join(self.folder, "index.json"), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") == VERSION and isinstance(data.get("entries"), dict):
                self.entries = data["entries"]
            else:
                self._wipe_files()  # another parser version: everything is read again
        except (OSError, ValueError):
            pass
        for name in os.listdir(self.folder):  # leftovers of an interrupted write
            if name.endswith(".tmp"):
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass

    def _wipe_files(self):
        for name in os.listdir(self.folder):
            if name != "index.json":
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass

    def flush(self, force=True):
        with self.lock:
            self._load()
            now = self.clock()
            if not self.dirty or (not force and now - self.last_flush < FLUSH_EVERY_S):
                return
            _atomic(os.path.join(self.folder, "index.json"), json.dumps({"version": VERSION, "entries": self.entries}, separators=(",", ":")).encode("utf-8"))
            self.dirty, self.last_flush = False, now

    # ---- lookups ----
    def lookup(self, path, size, mtime_ns):
        """The entry of `path` when it is still valid for this size / mtime / version, else None (the file must be parsed)."""
        with self.lock:
            self._load()
            e = self.entries.get(key_of(path))
            if e and e.get("v") == VERSION and e.get("size") == size and e.get("mtime_ns") == mtime_ns:
                return e
            return None

    def entry(self, path):
        with self.lock:
            self._load()
            return self.entries.get(key_of(path))

    def touch(self, path):
        with self.lock:
            e = self.entry(path)
            if e:
                e["used_at"] = self.clock()
                self.dirty = True

    def total_bytes(self):
        with self.lock:
            self._load()
            return sum(int(e.get("bytes", 0)) for e in self.entries.values())

    def has_heavy(self, path):
        e = self.entry(path)
        return bool(e and e.get("heavy") and os.path.exists(self._p(e["key"], ".json")))

    # ---- writing ----
    def begin(self, path):
        with self.lock:
            self._load()
        return Writer(self._p(key_of(path), ".geo.tmp"), self.max_geo)

    def commit(self, path, size, mtime_ns, result, writer, temps):
        """Stores the result of a finished parse. `result` is parse_stream's answer, `temps` the gcode_temps scan."""
        key = key_of(path)
        writer.close()
        with self.lock:
            self._load()
            self.drop(path, save=False)
            thumbs, nbytes = [], 0
            for i, (w, h, data) in enumerate(result["thumbs"]):
                _atomic(self._p(key, ".%d.png" % i), data)
                thumbs.append({"width": w, "height": h, "file": "%s.%d.png" % (key, i)})
                nbytes += len(data)
            synth = result.get("synth_thumb")
            if synth and not thumbs:  # an embedded thumbnail always wins
                _atomic(self._p(key, ".thumb.png"), synth)
                w, h = struct.unpack(">II", synth[16:24])
                thumbs.append({"width": w, "height": h, "file": key + ".thumb.png", "synthetic": True})
                nbytes += len(synth)
            if writer.offsets:
                os.replace(writer.tmp, self._p(key, ".geo"))
                nbytes += writer.pos
            else:
                writer.abort()
            detail = {"version": VERSION, "path": path, "header": result["header"], "temps": temps["commands"][:300],
                      "temps_truncated": bool(temps.get("truncated")), "layers": result["layers"][:20000], "types": result["types"], "plane": result.get("plane", "3d"),
                      "offsets": writer.offsets, "geo_truncated": writer.truncated, "thumbs": thumbs}
            raw = json.dumps(detail, separators=(",", ":")).encode("utf-8")
            _atomic(self._p(key, ".json"), raw)
            nbytes += len(raw)
            self.entries[key] = {"v": VERSION, "key": key, "path": path, "size": size, "mtime_ns": mtime_ns, "state": "ready",
                                 "summary": result["summary"], "bytes": nbytes, "heavy": True, "used_at": self.clock()}
            self.dirty = True
            self.evict(keep=key)
            self.flush()

    def mark_error(self, path, size, mtime_ns, error_key, params=None):
        with self.lock:
            self._load()
            key = key_of(path)
            self.drop(path, save=False)
            self.entries[key] = {"v": VERSION, "key": key, "path": path, "size": size, "mtime_ns": mtime_ns, "state": "error",
                                 "error": {"key": error_key, "params": params or {}}, "bytes": 0, "heavy": False, "used_at": self.clock()}
            self.dirty = True
            self.flush()

    # ---- removing ----
    def _remove_files(self, key):
        for name in os.listdir(self.folder):
            if name.startswith(key + ".") and not name.endswith(".tmp"):  # the .tmp of a parse in progress is not ours to remove
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass

    def drop(self, path, save=True):
        """Removes the entry of one file with its files. True when there was one."""
        with self.lock:
            self._load()
            key = key_of(path)
            found = self.entries.pop(key, None) is not None
            self._remove_files(key)
            self.dirty = self.dirty or found
            if save and found:
                self.flush()
            return found

    def clear(self):
        with self.lock:
            self._load()
            n = len(self.entries)
            self.entries = {}
            self._wipe_files()
            self.dirty = True
            self.flush()
            return n

    def prune(self, exists):
        """Drops the entries whose file is gone (`exists(path) -> bool`). Returns how many."""
        with self.lock:
            self._load()
            gone = [e["path"] for e in self.entries.values() if not exists(e["path"])]
            for p in gone:
                self.drop(p, save=False)
            if gone:
                self.dirty = True
                self.flush()
            return len(gone)

    def evict(self, keep=None):
        """Over the cap: the heavy files of the least recently used entries go first (their summary stays). Returns the keys evicted."""
        with self.lock:
            total = sum(int(e.get("bytes", 0)) for e in self.entries.values())
            out = []
            for e in sorted(self.entries.values(), key=lambda x: x.get("used_at", 0)):
                if total <= self.cap:
                    break
                if e["key"] == keep or not e.get("heavy"):
                    continue
                total -= int(e.get("bytes", 0))
                self._remove_files(e["key"])
                e.update(heavy=False, bytes=0)
                out.append(e["key"])
            if out:
                self.dirty = True
            return out

    # ---- reading the heavy files ----
    def detail(self, path):
        e = self.entry(path)
        if not e or not e.get("heavy"):
            return None
        try:
            with open(self._p(e["key"], ".json"), "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def read_blobs(self, path, detail, first, last):
        """[(layer index, blob)] for the layers first..last (inclusive) of a file whose detail is given; only those bytes are read."""
        e = self.entry(path)
        out = []
        if not e:
            return out
        offsets = detail["offsets"]
        try:
            with open(self._p(e["key"], ".geo"), "rb") as fh:
                for i in range(max(0, first), min(last, len(offsets) - 1) + 1):
                    off, n = offsets[i]
                    fh.seek(off)
                    out.append((i, fh.read(n) if n else b""))
        except OSError:
            return []
        return out

    def read_thumb(self, path, detail, width=None):
        """(width, height, png bytes, synthetic) of the thumbnail closest to `width` (the smallest one that is not smaller; else the biggest)."""
        thumbs = detail.get("thumbs") or []
        if not thumbs:
            return None
        if width:
            bigger = [t for t in thumbs if t["width"] >= width]
            pick = min(bigger, key=lambda t: t["width"]) if bigger else max(thumbs, key=lambda t: t["width"])
        else:
            pick = max(thumbs, key=lambda t: t["width"])
        try:
            with open(os.path.join(self.folder, pick["file"]), "rb") as fh:
                return pick["width"], pick["height"], fh.read(), bool(pick.get("synthetic"))
        except OSError:
            return None
