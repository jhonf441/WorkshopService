"""Pellet extruder temperature by layer: the PURE logic (no I/O, no clock, no imports of the service but messages).

A pellet barrel has several heating zones (heaters) that RRF handles as ONE tool: `M568 P<tool> S<t1>:<t2>:...` sets the active
temperature of every heater of the tool in the order of `tool.heaters` (the same code handlers/pid_zones.py already uses). This module
decides WHEN a job gets a new set of temperatures and WHICH ones, always inside limits. The thread that reads the object model and sends
the code is pellet_layers_run.py; the operations are pellet_layers_ops.py. Design: informes/pellet-temperatura-por-capa/DISENO.md.

A profile (saved by name in the settings area "pellet-layers"):

    {"tool": 0, "heaters": [1, 2, 3], "mode": "steps" | "ramp", "axis": "layer" | "z",
     "max_temp": 260, "max_step": 10, "max_spread": 60,
     "points": [{"at": 1, "temps": [200, 210, 220]}, ...]}

Rules (each one has a test):
  - Nothing happens unless a Run is armed for ONE file (arming is explicit, per job, in memory).
  - A temperature is never above min(profile max_temp, heater max - HEADROOM_C), never below MIN_TEMP (a profile cannot switch a heater off).
  - A heater moves at most max_step degrees per layer advanced since the last change; the zones never end more than max_spread apart.
  - It only sends while the machine is "processing". A pause HOLDS (sends nothing, switches nothing off, stays armed). Cancel, end or a lost
    job DISARM and leave the temperatures as they are. A heater that is off is never switched on; after the first change a heater that
    went off disarms the run (someone or a protection turned it off).
"""
from messages import M

AREA = "pellet-layers"

MODES = ("steps", "ramp")
AXES = ("layer", "z")

MIN_TEMP = 30.0            # C: a profile never asks for less (an off heater is not a profile's business)
HARD_MAX_TEMP = 450.0      # C: no profile may set a bigger max_temp than this
HEADROOM_C = 10.0          # C below the heater's own maximum (heat.heaters[h].max) that is never crossed
MAX_PROFILES = 40
MAX_POINTS = 60
MAX_ZONES = 8
MAX_STEP_LIMIT = 50.0
SPREAD_MIN, SPREAD_MAX = 5.0, 200.0
NAME_MAX = 40
ARM_TTL_S = 3600           # an armed run that never saw its job start is dropped after this
OVERRIDE_POLLS = 3         # polls with the board holding other temperatures than the applied ones before saying so
OVERRIDE_TOL = 2.0         # C
Z_TOL = 0.01               # mm: same rule as gcode_plan.py and fff-layers.js (a new layer is a rise of more than this)

HOLD_STATES = ("pausing", "paused", "resuming")
LOST_HEATER_STATES = ("fault", "offline", "tuning")


class ProfileError(Exception):
    """errors: [{"field", "message"}], every problem found."""

    def __init__(self, errors):
        super().__init__("; ".join(str(e["message"]) for e in errors))
        self.errors = errors


def _err(field, key, **params):
    return {"field": field, "message": M(key, field=field, **params)}


def _num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and lo <= v <= hi


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _fmt(t):
    return ("%.1f" % t).rstrip("0").rstrip(".")


# ---- profiles ----

def clean_name(name):
    """The name as it is stored: a trimmed text of 1 to NAME_MAX characters. Raises ProfileError."""
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= NAME_MAX:
        raise ProfileError([_err("name", "pellet_layers_err_name", max=NAME_MAX)])
    return name.strip()


def validate_profile(raw):
    """The profile in its stored form (numbers as floats), or ProfileError with one message per problem."""
    errors = []
    if not isinstance(raw, dict):
        raise ProfileError([_err("profile", "pellet_layers_err_profile")])
    tool = raw.get("tool")
    if not _int(tool, 0, 31):
        errors.append(_err("tool", "pellet_layers_err_tool"))
    heaters = raw.get("heaters")
    if (not isinstance(heaters, list) or not 1 <= len(heaters) <= MAX_ZONES or not all(_int(h, 0, 63) for h in heaters)
            or len(set(heaters)) != len(heaters)):
        errors.append(_err("heaters", "pellet_layers_err_heaters", max=MAX_ZONES))
        heaters = None
    mode = raw.get("mode")
    if mode not in MODES:
        errors.append(_err("mode", "pellet_layers_err_mode"))
    axis = raw.get("axis")
    if axis not in AXES:
        errors.append(_err("axis", "pellet_layers_err_axis"))
    max_temp = raw.get("max_temp")
    if not _num(max_temp, MIN_TEMP + 1, HARD_MAX_TEMP):
        errors.append(_err("max_temp", "pellet_layers_err_max_temp", min=int(MIN_TEMP) + 1, max=int(HARD_MAX_TEMP)))
        max_temp = None
    max_step = raw.get("max_step")
    if not _num(max_step, 1, MAX_STEP_LIMIT):
        errors.append(_err("max_step", "pellet_layers_err_max_step", max=int(MAX_STEP_LIMIT)))
    max_spread = raw.get("max_spread")
    if not _num(max_spread, SPREAD_MIN, SPREAD_MAX):
        errors.append(_err("max_spread", "pellet_layers_err_max_spread", min=int(SPREAD_MIN), max=int(SPREAD_MAX)))
        max_spread = None
    points = raw.get("points")
    out_points = []
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        errors.append(_err("points", "pellet_layers_err_points", max=MAX_POINTS))
    else:
        last = None
        for i, p in enumerate(points):
            field = "points[%d]" % i
            if not isinstance(p, dict):
                errors.append(_err(field, "pellet_layers_err_point"))
                continue
            at = p.get("at")
            at_ok = _int(at, 1, 100000) if axis == "layer" else _num(at, 0, 100000)
            if not at_ok:
                errors.append(_err(field + ".at", "pellet_layers_err_point_at"))
                continue
            if last is not None and at <= last:
                errors.append(_err(field + ".at", "pellet_layers_err_point_order"))
            last = at
            temps = p.get("temps")
            if not isinstance(temps, list) or (heaters is not None and len(temps) != len(heaters)):
                errors.append(_err(field + ".temps", "pellet_layers_err_point_temps"))
                continue
            cap = max_temp if max_temp is not None else HARD_MAX_TEMP
            if not all(_num(t, MIN_TEMP, cap) for t in temps):
                errors.append(_err(field + ".temps", "pellet_layers_err_point_range", min=int(MIN_TEMP), max=int(cap)))
                continue
            if max_spread is not None and max(temps) - min(temps) > max_spread:
                errors.append(_err(field + ".temps", "pellet_layers_err_point_spread", max=int(max_spread)))
            out_points.append({"at": float(at) if axis == "z" else int(at), "temps": [float(t) for t in temps]})
    if errors:
        raise ProfileError(errors)
    return {"tool": tool, "heaters": list(heaters), "mode": mode, "axis": axis, "max_temp": float(max_temp),
            "max_step": float(max_step), "max_spread": float(max_spread), "points": out_points}


def validate_store(value):
    """The whole stored value {"profiles": {name: profile}}; a missing value is no profiles. Raises ProfileError."""
    if value is None:
        return {"profiles": {}}
    if not isinstance(value, dict) or not isinstance(value.get("profiles"), dict):
        raise ProfileError([_err("profiles", "pellet_layers_err_profile")])
    if len(value["profiles"]) > MAX_PROFILES:
        raise ProfileError([_err("profiles", "pellet_layers_err_too_many", max=MAX_PROFILES)])
    return {"profiles": {clean_name(n): validate_profile(p) for n, p in value["profiles"].items()}}


def summary(name, profile):
    """One line of the list: what the page shows before opening a profile."""
    pts = profile["points"]
    return {"name": name, "tool": profile["tool"], "heaters": list(profile["heaters"]), "mode": profile["mode"], "axis": profile["axis"],
            "points": len(pts), "first": pts[0]["at"], "last": pts[-1]["at"]}


# ---- the curve ----

def raw_targets(profile, key):
    """The temperatures the curve asks for at `key` (a layer number or a Z in mm, as the profile's axis says), before any limit.
    Before the first point the first point rules; after the last one the last."""
    pts = profile["points"]
    if key <= pts[0]["at"]:
        return list(pts[0]["temps"])
    if key >= pts[-1]["at"]:
        return list(pts[-1]["temps"])
    j = max(i for i, p in enumerate(pts) if p["at"] <= key)
    a = pts[j]
    if profile["mode"] == "steps":
        return list(a["temps"])
    b = pts[j + 1]
    f = (key - a["at"]) / float(b["at"] - a["at"])
    return [round(x + (y - x) * f, 2) for x, y in zip(a["temps"], b["temps"])]


def next_point(profile, key):
    """The next point of the curve after `key`: {"at", "temps"} or None when the curve has ended."""
    for p in profile["points"]:
        if p["at"] > key:
            return {"at": p["at"], "temps": list(p["temps"])}
    return None


def layer_from_z(layer_z, z):
    """The layer a height belongs to: how many layers of the table start at or below z (+ Z_TOL). None with no table or below layer 1."""
    if not layer_z or not isinstance(z, (int, float)):
        return None
    n = sum(1 for h in layer_z if h <= z + Z_TOL)
    return n if n >= 1 else None


# ---- limits ----

def caps_for(profile, heater_models):
    """The highest temperature each heater of the profile may be asked for, or None when a heater does not tell its maximum.
    heater_models: the heat.heaters entries of the profile's heaters, in order."""
    out = []
    for h in heater_models:
        top = h.get("max") if isinstance(h, dict) else None
        if not isinstance(top, (int, float)) or isinstance(top, bool) or top != top or top <= 0:
            return None
        out.append(min(profile["max_temp"], float(top) - HEADROOM_C))
    return out


def _spread(t):
    return max(t) - min(t)


def limit_change(profile, raw, previous, caps, layers_advanced):
    """(temps, notes) the board may be given now: raw clamped to the caps and to a move of max_step x layers from `previous`, then
    pulled back toward `previous` until the zones are within max_spread. temps is None (hold) when no such set exists.
    notes: short codes of what was limited: "cap", "step", "spread"."""
    notes = []
    room = profile["max_step"] * max(1, int(layers_advanced))
    out = []
    for r, p, cap in zip(raw, previous, caps):
        t = min(r, cap)
        if t < r:
            notes.append("cap")
        t = max(MIN_TEMP, t)
        moved = min(max(t, p - room), p + room)
        if moved != t:
            notes.append("step")
        out.append(min(moved, cap))  # the cap wins even when the board sits above it: coming down is always allowed
    if _spread(out) > profile["max_spread"] + 1e-9:
        notes.append("spread")
        found = None
        for tenth in range(9, -1, -1):
            f = tenth / 10.0
            cand = [min(p + f * (t - p), cap) for t, p, cap in zip(out, previous, caps)]
            if _spread(cand) <= profile["max_spread"] + 1e-9:
                found = cand
                break
        if found is None:
            return None, sorted(set(notes))
        out = found
    return [round(t, 1) for t in out], sorted(set(notes))


def code_for(tool, temps):
    """The code that sets the active temperature of every heater of the tool, in the order of tool.heaters (as pid_zones.py does)."""
    return "M568 P%d S%s" % (tool, ":".join(_fmt(t) for t in temps))


# ---- reading the object model ----

def _number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def snapshot(status, layer_z=None):
    """What a step needs, from the object model dict: {status, file, layer, z, layer_z, tool, heaters}. Never raises on missing parts."""
    status = status if isinstance(status, dict) else {}
    job = status.get("job") or {}
    layer = job.get("layer")
    z = None
    for a in ((status.get("move") or {}).get("axes") or []):
        if isinstance(a, dict) and a.get("letter") == "Z":
            z = _number(a.get("userPosition"))
    return {
        "status": str((status.get("state") or {}).get("status") or "").lower(),
        "file": (job.get("file") or {}).get("fileName"),
        "layer": layer if isinstance(layer, int) and not isinstance(layer, bool) and layer >= 1 else None,
        "z": z,
        "layer_z": layer_z,
        "tools": [t for t in (status.get("tools") or []) if isinstance(t, dict)],
        "heaters": list((status.get("heat") or {}).get("heaters") or []),
    }


# ---- the run ----

class Run:
    """One armed job. step(snap, now) proposes events; the caller (pellet_layers_run.py) does the I/O and answers with commit() or
    rejected(). Events: {"type": "apply", ...} to send, {"type": "note", ...} to record, {"type": "disarm", ...} the run is over."""

    def __init__(self, name, profile, file, armed_at, armed_by=None):
        self.name = name
        self.profile = profile
        self.file = file
        self.armed_at = armed_at
        self.armed_by = armed_by or {}
        self.seen_job = False
        self.ended = False
        self.reason = None          # {"key", "params", "warn"} of the end
        self.phase = "waiting"      # waiting, waiting_heat, waiting_layer, running, holding, ended
        self.applied = None         # temperatures the board was last given (or already had)
        self.last_layer = None
        self.key = None
        self.changes = 0
        self.last_change_at = None
        self.limited = []
        self._mismatch = 0
        self._noted = False

    # -- helpers --

    def _end(self, key, warn, **params):
        self.ended = True
        self.phase = "ended"
        self.reason = {"key": key, "params": params, "warn": warn}
        return [{"type": "disarm", "reason": key, "params": params, "warn": warn}]

    def disarm(self, key="pellet_layers_off_by_user", warn=False):
        return [] if self.ended else self._end(key, warn)

    def rejected(self, answer):
        return self._end("pellet_layers_off_rejected", True, answer=str(answer or "")[:160])

    def commit(self, event, now):
        """The caller sent the code and the board took it."""
        self.applied = list(event["temps"])
        self.last_layer = event["layer"]
        self.key = event["key"]
        self.changes += 1
        self.last_change_at = now
        self.limited = list(event.get("notes") or [])
        self.phase = "running"
        self._noted = False
        self._mismatch = 0

    def view(self):
        """What the page shows (no messages: the reason travels as key + params)."""
        nxt = next_point(self.profile, self.key) if self.key is not None else next_point(self.profile, -1)
        return {"armed": not self.ended, "phase": self.phase, "profile": self.name, "file": self.file, "tool": self.profile["tool"],
                "heaters": list(self.profile["heaters"]), "layer": self.last_layer, "key": self.key, "applied": self.applied,
                "limited": self.limited, "changes": self.changes, "last_change_at": self.last_change_at, "next": nxt,
                "armed_by": self.armed_by.get("user", ""), "reason": self.reason}

    # -- the step --

    def step(self, snap, now):
        if self.ended:
            return []
        status = snap["status"]
        if not self.seen_job and now - self.armed_at > ARM_TTL_S:
            return self._end("pellet_layers_off_expired", False)
        in_job = status == "processing" or status in HOLD_STATES
        if not in_job:
            if status == "simulating" or not self.seen_job:
                self.phase = "waiting"  # a simulation heats nothing; a job that has not started yet is just waited for
                return []
            return self._end("pellet_layers_off_job_ended", False)
        if snap["file"] != self.file:
            return self._end("pellet_layers_off_other_job", True, file=str(snap["file"] or ""))
        self.seen_job = True
        tool = next((t for t in snap["tools"] if t.get("number") == self.profile["tool"]), None)
        if tool is None:
            return self._end("pellet_layers_off_tool_missing", True, tool=self.profile["tool"])
        if list(tool.get("heaters") or []) != self.profile["heaters"]:
            return self._end("pellet_layers_off_heaters_changed", True, tool=self.profile["tool"])
        models = []
        for h in self.profile["heaters"]:
            m = snap["heaters"][h] if h < len(snap["heaters"]) else None
            if not isinstance(m, dict):
                return self._end("pellet_layers_off_heater_missing", True, heater=h)
            models.append(m)
        for h, m in zip(self.profile["heaters"], models):
            if m.get("state") in LOST_HEATER_STATES:
                return self._end("pellet_layers_off_heater_fault", True, heater=h, state=str(m.get("state")))
        for h, m in zip(self.profile["heaters"], models):
            if m.get("state") == "off":
                if self.applied is None:
                    self.phase = "waiting_heat"  # never switch a heater on: wait for the G-code to heat it
                    return []
                return self._end("pellet_layers_off_heater_off", True, heater=h)
        if status in HOLD_STATES or tool.get("state") != "active" or any(m.get("state") == "standby" for m in models):
            self.phase = "holding"
            return []
        caps = caps_for(self.profile, models)
        if caps is None:
            return self._end("pellet_layers_off_no_limit", True)
        active = [_number(a) for a in (tool.get("active") or [])]
        if len(active) != len(models) or any(a is None for a in active):
            return self._end("pellet_layers_off_no_active", True)
        events = self._override_note(active)
        layer = snap["layer"] or layer_from_z(snap["layer_z"], snap["z"])
        if layer is None:
            self.phase = "waiting_layer"
            return events
        if self.last_layer is not None and layer <= self.last_layer:
            self.phase = "running"
            return events
        if self.profile["axis"] == "layer":
            key = layer
        else:
            lz = snap["layer_z"]
            key = lz[layer - 1] if lz and len(lz) >= layer else snap["z"]
            if key is None:
                self.phase = "waiting_layer"
                return events
        raw = raw_targets(self.profile, key)
        previous = self.applied if self.applied is not None else active
        advanced = 1 if self.last_layer is None else layer - self.last_layer
        temps, notes = limit_change(self.profile, raw, previous, caps, advanced)
        if temps is None:
            self.phase = "running"
            self.limited = notes
            return events
        self.last_layer, self.key, self.limited = layer, key, notes
        if all(abs(t - p) < 0.05 for t, p in zip(temps, previous)):
            self.applied = list(temps)  # the board already has it: nothing to send, nothing to record
            self.phase = "running"
            return events
        events.append({"type": "apply", "tool": self.profile["tool"], "code": code_for(self.profile["tool"], temps), "temps": temps,
                       "raw": raw, "layer": layer, "key": key, "notes": notes, "heaters": list(self.profile["heaters"])})
        return events

    def _override_note(self, active):
        if self.applied is None:
            return []
        if any(abs(a - t) > OVERRIDE_TOL for a, t in zip(active, self.applied)):
            self._mismatch += 1
            if self._mismatch >= OVERRIDE_POLLS and not self._noted:
                self._noted = True
                return [{"type": "note", "key": "pellet_layers_overridden", "params": {"layer": self.last_layer}}]
        else:
            self._mismatch = 0
        return []
