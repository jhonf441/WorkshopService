"""Safe stop and resume of a live job (2026-10-22). Pure code: no sockets, no DSF, no clock of its own.

A live job is a program streaming G-code lines through the bridge. While it runs the bridge keeps a JOURNAL of the lines that were sent to the
board (a count, a rolling SHA-256, checkpoints of that hash, the modal state and the path done). When the person stops the job safely the
journal is saved as an INTERRUPTED record. To resume, the person relaunches the SAME job from the program: the ResumeSession swallows the lines up
to the stop (an "ok" each, nothing reaches the board) while it verifies them against the hash; if a line differs it aborts and nothing runs.
When the count is reached the bridge plays the approach lines (laser off, travel, modal state) and the job goes on for real.

The hash is taken over the NORMALIZED lines (comments out, upper case, one space), so a program that rewrites spacing or comments is still the
same job; a different path, power or speed is not.
"""
import hashlib
import re

VERSION = 1
CHECKPOINT = 50            # a prefix of the rolling hash is saved every this many lines
TAIL = 40                  # the last lines keep their own position / modal state / hash (the back-up overlap of a resume)
PATH_MAX = 3000            # points of the path kept (it is thinned when it grows past this)
HASH_CHARS = 16

_COMMENT_PAREN = re.compile(r"\([^)]*\)")
_WORD = re.compile(r"([A-Z])\s*(-?(?:\d+\.?\d*|\.\d+))")


def normalize(line):
    """The line as it is hashed: no ; or ( ) comments, upper case, words separated by one space. Empty = nothing to count."""
    text = _COMMENT_PAREN.sub(" ", str(line or ""))
    text = text.split(";", 1)[0].upper()
    return " ".join(text.split())


def words(norm):
    """[(letter, number)] of a normalized line: the program writes 'G1 X583Y258.2S255' without spaces."""
    out = []
    for letter, num in _WORD.findall(norm):
        try:
            out.append((letter, float(num)))
        except ValueError:
            continue
    return out


def _num(v, digits=3):
    return None if v is None else round(float(v), digits)


class Modal:
    """What the program set up and the board remembers between lines, plus where the program thinks the head is.

    Positions are the program's coordinates (the work coordinate system it chose), not machine coordinates."""

    def __init__(self):
        self.absolute = True          # G90 / G91
        self.units = 21               # G21 mm / G20 inch
        self.wcs = None               # "G54".."G59"
        self.motion = None            # last G0 / G1 / G2 / G3
        self.feed = None              # last F
        self.power = None             # last S
        self.spindle = "M5"           # M3 / M4 / M5 as last written
        self.coolant = "M9"           # M7 / M8 / M9 as last written (air assist)
        self.x = self.y = self.z = None
        self.bbox = None              # [xmin, ymin, xmax, ymax] of what was cut
        self.cut_mm = 0.0
        self.path = []                # [x, y, cut 0/1] after every move
        self._stride = 1
        self._seen = 0

    # -- the state as data
    def snapshot(self):
        return {"absolute": self.absolute, "units": self.units, "wcs": self.wcs, "motion": self.motion, "feed": self.feed, "power": self.power,
                "spindle": self.spindle, "coolant": self.coolant}

    def position(self):
        return {"x": _num(self.x), "y": _num(self.y), "z": _num(self.z)}

    # -- one line
    def update(self, norm):
        ws = words(norm)
        if not ws:
            return
        letters = {}
        for letter, num in ws:
            letters.setdefault(letter, []).append(num)
        gs = [int(n) for n in letters.get("G", []) if n == int(n)]
        ms = [int(n) for n in letters.get("M", []) if n == int(n)]
        for g in gs:
            if g == 90:
                self.absolute = True
            elif g == 91:
                self.absolute = False
            elif g in (20, 21):
                self.units = g
            elif 54 <= g <= 59:
                self.wcs = "G%d" % g
            elif g in (0, 1, 2, 3):
                self.motion = g
        for m in ms:
            if m in (3, 4, 5):
                self.spindle = "M%d" % m
            elif m in (7, 8, 9):
                self.coolant = "M%d" % m
        if "F" in letters:
            self.feed = letters["F"][-1]
        if "S" in letters:
            self.power = letters["S"][-1]
        if 92 in gs:
            self._set_position(letters)
            return
        if any(axis in letters for axis in "XYZ"):
            self._move(letters, gs)

    def _set_position(self, letters):
        for axis in "XYZ":
            if axis in letters:
                setattr(self, axis.lower(), letters[axis][-1])

    def _move(self, letters, gs):
        mode = next((g for g in gs if g in (0, 1, 2, 3)), self.motion)
        old = (self.x, self.y)
        for axis in "XYZ":
            if axis not in letters:
                continue
            value = letters[axis][-1]
            cur = getattr(self, axis.lower())
            if not self.absolute and cur is not None:
                value = cur + value
            elif not self.absolute:
                value = value  # relative with no known origin: the first position is the offset itself
            setattr(self, axis.lower(), value)
        if self.x is None or self.y is None:
            return
        cutting = mode in (1, 2, 3) and (self.power is None or self.power > 0)
        if cutting and old[0] is not None:
            self.cut_mm += ((self.x - old[0]) ** 2 + (self.y - old[1]) ** 2) ** 0.5
        if cutting:
            self._grow_bbox(old)
        self._add_point(1 if cutting else 0)

    def _grow_bbox(self, old):
        pts = [(self.x, self.y)] + ([old] if old[0] is not None else [])
        xs = [p[0] for p in pts] + ([self.bbox[0], self.bbox[2]] if self.bbox else [])
        ys = [p[1] for p in pts] + ([self.bbox[1], self.bbox[3]] if self.bbox else [])
        self.bbox = [min(xs), min(ys), max(xs), max(ys)]

    def _add_point(self, cut):
        self._seen += 1
        if self._seen % self._stride:
            return
        self.path.append([_num(self.x, 2), _num(self.y, 2), cut])
        if len(self.path) > PATH_MAX:
            self.path = self.path[::2]
            self._stride *= 2


class Journal:
    """Everything the bridge remembers of the lines of ONE live job that reached the board."""

    def __init__(self, name=None, started=None, client=None):
        self.name = name
        self.started = started
        self.client = client
        self.count = 0
        self.hash = hashlib.sha256()
        self.checkpoints = []
        self.modal = Modal()
        self.tail = []

    def add(self, line):
        """Counts a line sent to the board. False when it is empty once normalized (comments, blanks): not counted, not hashed."""
        norm = normalize(line)
        if not norm:
            return False
        self.count += 1
        self.hash.update((norm + "\n").encode("utf-8"))
        self.modal.update(norm)
        digest = self.hash.hexdigest()[:HASH_CHARS]
        if self.count % CHECKPOINT == 0:
            self.checkpoints.append(digest)
        self.tail.append({"i": self.count, "sha": digest, "pos": self.modal.position(), "modal": self.modal.snapshot()})
        if len(self.tail) > TAIL:
            self.tail.pop(0)
        return True

    def digest(self):
        return self.hash.hexdigest()

    def record(self, stopped, reason="safe_stop", extra=None):
        """The interrupted record of this journal (JSON-able)."""
        rec = {"v": VERSION, "id": "%d-%s" % (int(stopped), self.digest()[:8]), "name": self.name, "started": self.started, "stopped": stopped,
               "reason": reason, "lines": self.count, "sha": self.digest(), "every": CHECKPOINT, "checkpoints": list(self.checkpoints),
               "tail": [dict(t) for t in self.tail], "modal": self.modal.snapshot(), "program_pos": self.modal.position(),
               "bbox": [_num(v) for v in self.modal.bbox] if self.modal.bbox else None, "cut_mm": round(self.modal.cut_mm, 1),
               "path": [list(p) for p in self.modal.path], "armed": None}
        rec.update(extra or {})
        return rec


class ResumeSession:
    """Verifies the relaunched job against an interrupted record while it swallows its lines.

    feed(line) -> (verdict, info):
      "skip"      the line belongs to the part already done: answer ok, do not run it
      "pass"      past the stop: run it (the approach was already played)
      "approach"  the first line past the stop: play the approach lines (approach()), then run this line
      "abort"     the job is not the one that was interrupted: info says where; nothing was run and nothing more must run
    """

    def __init__(self, record, overlap_lines=0):
        self.record = record
        self.every = int(record.get("every") or CHECKPOINT)
        tail = record.get("tail") or []
        self.overlap = max(0, min(int(overlap_lines or 0), len(tail) - 1 if tail else 0, int(record["lines"])))
        self.stop_at = int(record["lines"]) - self.overlap       # lines swallowed
        self.index = 0
        self.hash = hashlib.sha256()
        self.state = "skipping"                                 # skipping | ready | done | aborted
        self.reason = None
        self._tail_sha = {t["i"]: t["sha"] for t in tail}
        self._tail = {t["i"]: t for t in tail}
        if self.stop_at <= 0:
            self.state = "ready"

    @property
    def progress(self):
        return {"state": self.state, "swallowed": self.index, "of": self.stop_at, "overlap": self.overlap, "reason": self.reason}

    def feed(self, line):
        if self.state == "aborted":
            return "abort", self.reason
        norm = normalize(line)
        if self.state == "skipping":
            if not norm:
                return "skip", None
            self.index += 1
            self.hash.update((norm + "\n").encode("utf-8"))
            digest = self.hash.hexdigest()[:HASH_CHARS]
            expected = None
            if self.index % self.every == 0:
                cps = self.record.get("checkpoints") or []
                k = self.index // self.every - 1
                expected = cps[k] if k < len(cps) else None
            elif self.index in self._tail_sha:
                expected = self._tail_sha[self.index]
            if expected is not None and expected != digest:
                return self._abort("line %d is not the same as when the job was stopped (the job changed)" % self.index)
            if self.index >= self.stop_at:
                if self.overlap == 0 and self.hash.hexdigest() != self.record.get("sha"):
                    return self._abort("the lines up to %d are not the ones of the stopped job" % self.index)
                self.state = "ready"
            return "skip", None
        if self.state == "ready":
            self.state = "done"
            return "approach", None
        return "pass", None

    def _abort(self, reason):
        self.state = "aborted"
        self.reason = reason
        return "abort", reason

    def resume_state(self):
        """(modal snapshot, program position) at the line where the job really goes on (the overlap goes back in the tail)."""
        if self.overlap == 0:
            return self.record.get("modal") or {}, self.record.get("program_pos") or {}
        t = self._tail.get(self.stop_at)
        if t is None:
            return self.record.get("modal") or {}, self.record.get("program_pos") or {}
        return t.get("modal") or {}, t.get("pos") or {}


def approach_lines(modal, pos, current_z=None, travel_feed=3000.0, z_feed=300.0):
    """The lines that put the machine where the program left it: units / distance / WCS, laser off, travel in XY, Z, then the modal state.

    Everything before the travel is laser-off: G0 never fires the laser in laser mode and M5 makes sure. Absolute moves only (G90) so the
    approach does not depend on where the head is; the program's own distance mode is written back at the end."""
    lines = ["M5", "G90", "G21" if int(modal.get("units") or 21) == 21 else "G20"]
    if modal.get("wcs"):
        lines.append(modal["wcs"])
    x, y, z = pos.get("x"), pos.get("y"), pos.get("z")
    up_first = z is not None and current_z is not None and z > current_z
    if up_first:
        lines.append("G0 F%g Z%g" % (z_feed, z))
    if x is not None and y is not None:
        lines.append("G0 F%g X%g Y%g" % (travel_feed, x, y))
    if z is not None and not up_first and (current_z is None or abs(z - current_z) > 0.001):
        lines.append("G0 F%g Z%g" % (z_feed, z))
    if modal.get("coolant") in ("M7", "M8"):
        lines.append(modal["coolant"])
    if modal.get("feed") is not None:
        lines.append("G1 F%g" % modal["feed"])
    if modal.get("spindle") in ("M3", "M4"):
        lines.append("%s S%g" % (modal["spindle"], modal.get("power") or 0))
    if modal.get("absolute") is False:
        lines.append("G91")
    return lines


def describe(record):
    """Short summary of a record for the lists (no path, no checkpoints)."""
    return {k: record.get(k) for k in ("id", "name", "started", "stopped", "reason", "lines", "bbox", "cut_mm", "program_pos", "position", "mode",
                                       "resumable", "why_not", "armed")}
