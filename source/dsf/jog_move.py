"""
The real engine of the CNC jog -- it runs in a background thread inside dsf/main.py (like job_poller.py / motor_poller.py) and sends the relative G1 moves of the
DIRECT jog through its own dedicated CommandConnection (a socket to DCS, not HTTP from the browser, and not shared with the other pollers -- see _JogConnection below).
It replaces the timing/watchdog that used to live entirely in EmergencyFab.js (see [[duet3-emergencyfab-camera-esp32-ota]] and the 2026-10-07 session): the kiosk's
Chromium leaked false stops ("the knob lets go by itself") and left extra movement after release, because of the browser's own jitter (setPointerCapture is not
reliable on this Wayland+touch kiosk, the main thread is shared with the camera stream added the same day, the HTTP cache, Chromium relaunching, etc). A dedicated
Python thread, with its own clock (time.sleep) and its own direct connection to DCS, depends on none of that.

The browser (see EmergencyFab.js) NO longer sends G1 itself: it only sends the TARGET state (normalised X/Y vector of the knob, or the sign of Z, plus the chosen
speed %) through the jog.* API operations (api_ops.py, handlers/jog.py). This module is the ONLY one that computes the ramp and sends real movement. If the browser
stops sending updates (tab closed, kiosk hung, whatever) for more than WATCHDOG_S, this same thread stops by itself -- the real watchdog lives here, not in JS, and
does not depend on a pointerup/pointercancel event reaching anyone.

RRF has no way to cancel a G1 that was already accepted (confirmed: neither a GRBL-style jog-cancel nor an M-code equivalent to Marlin's M410 exists in
RepRapFirmware) -- once a G1 is accepted, it runs to the end.

2026-10-08: the first design sent bridge.send() DIRECTLY from the main loop (synchronous, it waited for the reply before continuing) -- live this felt "shaky"
(reported by the user): even though the socket to DCS is fast (it is not the ~70-90 ms of HTTP that the old browser version had), it is still not instant, and with the
loop waiting for every reply before queueing the next one, RRF's motion queue was EMPTY for an instant between one G1 and the next -- the machine stopped completely at
each TICK_MS segment to start again. The same problem the JS version had, the same diagnosis.

Fix (part 1): a separate "sender" thread consumes a queue (queue.Queue, a single producer -- this loop -- and a single consumer -- the sender) and is the ONLY one that
sends codes. The main loop no longer waits for anything: it queues the code and goes on with its own clock. At most SEND_QUEUE_MAXSIZE+1 moves stay "ahead" (the
already queued ones plus the one the sender has in flight right now) -- that gives RRF real room not to empty the queue between ticks, without going back to the
~360 ms of "phantom movement" after release that the old version had with JOG_MAX_INFLIGHT=3 (deliberately lowered to a small value here, see SEND_QUEUE_MAXSIZE).
A single FIFO consumer guarantees the order (G91 ALWAYS before the first G1 that depends on it) without the race that sending each code in its own loose thread would have.

Fix (part 2, the hesitation kept happening with part 1 alone -- measured live by polling machinePosition every 100 ms): the `bridge` received as a parameter is SHARED
with motor_poller.py, which every 1 s makes SEVERAL diagnostic reads per axis (M122, gstat, m569, drv_status) through the SAME Bridge.lock -- while motor_poller holds the
lock (sometimes for quite a while: "M122 failed (TimeoutError)" was already seen in the log), the jog sender is blocked waiting for that same lock, so the real pattern
was not "it brakes every tick" but "bursts of 1-2 consecutive ticks followed by a gap of several hundred ms" each time motor_poller does its round -- THAT is the reported
shake. That is why the jog uses its OWN dedicated CommandConnection (_JogConnection below), and never shares a lock with the diagnostic pollers.

Fix (part 3): the quantisation of the feed into RAMP_STEP_FRACTION steps that the JS version had was removed (it was meant so RRF could "glue" ticks with the SAME F
when the bottleneck was the browser's HTTP latency, ~70-90 ms against a 120 ms tick). With parts 1 and 2 already solved, that quantisation became more of a problem than a
solution: the ramp (RAMP_EASE) rises continuously, but rounding it to steps meant that the F sent stayed FIXED for several ticks and then JUMPED to the next step -- each
step jump is itself a change of F, so during the ~800 ms of ramp (7-8 steps) 7-8 small acceleration/braking cycles were forced, a source of shake of its own,
independent of any network or lock problem. Now the ramp value is sent as it is (current_feed_xy/z, rounded only by the F.0f of the string), without steps.

2026-10-08 (second round, "it shakes when starting" + "Z keeps going after release"): the "protocol" (the jog.* API operations, then the dedicated DSF socket) is ALREADY the
LOWEST latency part of the whole chain -- there is no room to improve it without throwing away the whole architecture. What does have room is TICK_MS: RRF cannot cancel a G1
that was already accepted (see above), so the "overshoot" after release is, in the worst case, the distance of UP TO TWO segments (the one the sender already sent / is
sending + the one already queued waiting its turn, see SEND_QUEUE_MAXSIZE) computed with the F the ramp had at that instant. With TICK_MS=120 and Z at maximum speed (F ~2100
mm/min with speed 100%) each segment is ~4.2 mm -- up to ~8.4 mm of overshoot, quite noticeable on Z. Two changes, without touching the protocol:
(a) TICK_MS lowered from 120 to 60 -- each segment lasts half as long, so the maximum overshoot is also halved, AND the ramp (RAMP_EASE) is updated twice as often, which
    makes it feel smoother when starting (fewer perceptible "steps" even though there is no explicit quantisation any more).
(b) _drain_pending_g1(): when xy=None AND z=None is detected (knob/Z released, by a real release or by the watchdog), whatever is left in _send_queue is emptied WITHOUT
    sending it -- a G1 already computed in the previous tick that the sender has not picked up yet. That is pure gain: that segment never reaches the machine, it never
    becomes "already accepted" by RRF. It does not affect the one the sender is ALREADY sending at this instant (that is the only truly unavoidable stretch, confirmed
    that RRF cannot cancel it).

2026-10-08 (third round, REGRESSION found and fixed the same day): the user reported "it goes and stops, goes and stops" live -- measuring with a DIRECT, synchronous M114
(not the object model, confirmed throttled again, see the usual pitfall) I found the real cause: a single perform_simple_code() of ONE G1 takes ~75-80 ms round trip
(measured live, consistent), because it BLOCKS waiting for the formatted reply from RRF -- it is not network/socket latency, it is the time RRF takes to generate that
reply. Lowering TICK_MS to 60 (as had been done above in this same round) was BELOW that real floor: the sender could not send every tick in time, _send_queue filled up
often and _enqueue_g1 dropped whole ticks (by design, see above) -- THAT is the "goes and stops" (one G1 passes, the next 1-2 are discarded until the sender frees up, repeat).

Real fix: CommandConnection.perform_simple_code() accepts async_exec=True -- with that the call returns in ~1 ms (measured live, nothing like the 75-80 ms without the
parameter) because it does not wait for the formatted reply (that one comes out as a generic console message in DWC instead of being returned here, but we never used
that return value for a jog G1). Verified live that the order is preserved (G91 STILL applies before its dependent G1, critical, see above) -- a G91+G1 X2+G90 sent all
three with async_exec=True gave exactly +2.000 mm, not a step more or less. With this, TICK_MS=60 (or even lower) becomes truly safe: the sender is no longer the
bottleneck, the ~1 ms of each send leaves plenty of margin against any reasonable TICK_MS.

"""
import job_states
import paths
import math
import os
import queue
import communication
import ipc_stats  # IPC calls to DCS per minute
import threading
import time

import heartbeats
import machine_state
import json

from dsf.connections import CommandConnection
from messages import M, J, Msg


TICK_MS = 60
# 2026-10-08, fifth round: BACK from 30 to 60 -- REGRESSION of the fourth round. With 30 ms the user
# noticed a "hesitation" in X/Y when starting to move (not in Z), which did not exist with 60. Cause
# (RRF planner physics, not a code bug): RRF always plans so it can BRAKE at the end of the last G1
# it has queued, and this loop only leaves it ~1-2 segments of look-ahead. The maximum sustainable
# speed with d mm queued and acceleration a is v = sqrt(2*a*d). In Laser mode (M201 X300 Y300) at
# 50% (3000 mm/min = 50 mm/s) each 30 ms segment is 1.5 mm -> sqrt(2*300*1.5) = 30 mm/s < 50
# requested: RRF cannot sustain the speed, it brakes inside each segment, the queue builds up, it
# accelerates again... that oscillation IS the hesitation. With 60 ms the segment is twice as long
# (3 mm -> ~42 mm/s with one, ~60 mm/s with two queued) and the problem practically disappears in
# the normal range of use. Z did not show it because its real ceiling is 10 mm/s (M203 Z600): small
# segments are enough. The original reason for lowering to 30 (Z "keeps going a bit after release")
# was already solved at the root by the clamp against move.axes[].speed (see _rrf_axis_max_feed
# below), so going back to 60 does not reopen it. DO NOT lower it again without measuring on the
# real machine: the overshoot after release and the smoothness pull in opposite directions with this
# design. 2026-10-08, fourth round: lowered from 60 to 30. The user still feels a remainder of "it
# moves a bit after release" (expected -- RRF cannot cancel the segment that was already sent to it,
# see the big docstring above). The distance of THAT unavoidable segment is proportional to TICK_MS
# (feed * TICK_MS), so shrinking the tick directly shrinks that remainder. With async_exec already
# in use (~1 ms real per send, measured live) there is plenty of margin for this: at 30 ms the
# sender is still nowhere near a bottleneck (it needs ~33 sends per second, each ~1 ms). It is not
# lowered more aggressively just in case (contention of the SBC channel shared with the other
# pollers, see finding #8 in the project memory -- not confirmed to cause a real problem, but there
# is no need to risk more than necessary).
STATUS_POLL_S = 2.0
# 2026-10-09 ("the hesitation continues: it moves, tries to jam and continues"): measured on the Pi,
# reading /machine/status takes 110-130 ms and it was done INSIDE the tick every STATUS_POLL_S --
# with only ~60 ms of movement queued in RRF, the queue emptied and the machine braked for an
# instant every 2 s. Now (a) the status is refreshed by a separate thread (_status_refresher) and
# the tick only reads the cache, and (b) each segment is computed by REAL TIME: LEAD_S of movement
# is kept ahead of "now" (if a tick arrives late, the next segment is longer and the queue does not
# empty). LEAD_S is the same margin that already existed (2 segments of 60 ms), so what keeps moving
# after release does not increase.
LEAD_S = 0.12
# 2026-10-09 ("when the Z jog is released there is a slight feeling that it keeps going"): with ONLY
# Z held the cycle runs every Z_TICK_S and keeps LEAD_Z_S ahead (instead of 60 ms / 0.12 s): what
# RRF already has queued at release drops from ~1.2 mm to ~0.7 mm at 10 mm/s. It is enough not to
# brake between segments: in Laser (M201 Z100) braking from 10 mm/s needs 0.5 mm = 50 ms, and what
# is queued never drops below LEAD_Z_S - Z_TICK_S. X/Y keep TICK_MS/LEAD_S (see the fifth round:
# they did hesitate there).
Z_TICK_S = 0.03
LEAD_Z_S = 0.07
# A "z"/"xy" update that arrives up to this long AFTER its stop is a heartbeat/drag that left before
# the release and arrived late (HTTP does not guarantee the order): it is discarded, otherwise Z
# would start again until the watchdog (0.9 s). Nobody releases and grabs again in less than this.
STOP_GRACE_S = 0.15

# 2026-10-09: MACHINE settings made from the jog's gear (WorkshopJog 18-settings.js) ->
# /opt/dsf/sd/sys/workshop/config/jog.json {feedMax, zRatio, exponent, deadzone}. It is re-read (by
# mtime) in the state thread; with no file or with odd values the constants below stay.
SETTINGS_FILE = paths.CONFIG_DIR + "/jog.json"
_AJ_LIMITS = {
    "feedMax": ("FEED_MAX", 600.0, 15000.0),
    "zRatio": ("Z_FEED_RATIO", 0.05, 1.0),
    "exponent": ("EXPONENT", 1.0, 3.0),
    "deadzone": ("DEADZONE", 0.02, 0.4),
}
_aj_mtime = [None]
_AJ_FACTORY = {}
SEC_MIN_S = 0.02  # less than this ahead is not worth a G1 (there is already a queue)
SEC_MAX_S = 0.25  # cap in case the loop falls far behind (do not send long segments)
DEADZONE = 0.12
WATCHDOG_S = 0.9  # knob: with no new update from the browser in this span, it cuts
# 2026-10-08: lowered from 5.0 to 0.9 (same as XY's WATCHDOG_S). The 5.0 value never had a real
# reason to be longer than XY -- a LEGITIMATE hold always refreshes every JOG_HEARTBEAT_MS (300 ms
# on the JS side), well inside either value; the watchdog only matters when SOMETHING went wrong on
# the browser side (a pointerup that never arrives, a hung connection, etc), and there 5 s is too
# much time of uncontrolled movement. Confirmed live in the log (workshop-service.log, 11:22:00):
# "watchdog z: no update from the browser, cutting" -- the ONLY reason it took so long to cut was
# this 5.0 value, not a tick/send problem (those are already solved, see TICK_MS/async_exec below).
Z_HOLD_MAX_S = 0.9
X_SIGN = 1
Y_SIGN = 1
FEED_MIN = 60.0
FEED_MAX = 6000.0
Z_FEED_RATIO = 0.35
EXPONENT = 1.6
RAMP_EASE = 0.35

# "idle" or "busy" -- see EmergencyFab.js, same reasoning: while the jog is sending G1 one after
# another the machine is physically moving, so state.status is never "idle", it is "busy". What must
# keep being blocked is everything else (processing = a real job,
# paused/pausing/resuming/cancelling, changingTool, halted, simulating, off, etc).
SAFE_STATUSES = {"idle", "busy"}
# 2026-10-12 (user decision): with a FILE job paused the jog DOES move (RRF saves the positions and
# restores them on resume). The no-limits mode keeps SAFE_STATUSES.
JOG_STATUSES = SAFE_STATUSES | {"paused"}

_log_file = [None]  # mutable cell -- main.py sets it after importing


def set_log_file(path):
    _log_file[0] = path


def _log(msg):
    path = _log_file[0]
    if not path:
        return
    try:
        with open(path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [jog_move] {msg}\n")
    except Exception:
        pass


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.xy = None  # (nx, ny) normalizado -1..1, None = perilla centrada/suelta
        self.xy_last_update = 0.0
        self.gap_n, self.gap_max, self.gap_slow = 0, 0.0, 0
        # 2026-10-08, fourth round: Z went from being a simple sign (-1/0/1, a press/release button)
        # to a CONTINUOUS value -1..1, like xy -- see the new single-axis slider in EmergencyFab.js.
        # None = fully released (different from "held at the centre", which is 0.0 but is still
        # "grabbed" -- the same distinction that already existed for xy/None).
        self.z = None
        self.z_last_update = 0.0
        self.speed_percent = 50.0
        self.xy_stop_at = 0.0
        self.z_stop_at = 0.0
        # after an automatic exit from the no-limits mode (crash, lock, job): do not keep moving
        # with what the browser keeps sending while the person still has their finger pressed; wait
        # until they release.
        self.lock_xy = False
        self.lock_z = False
        # 2026-10-10 ("assign new axes to move from the jog"): one extra axis held at a time (hold
        # +/- in the Step tab). (letter, value -1..1) or None; same watchdog as Z.
        self.ext = None
        self.ext_last_update = 0.0
        self.ext_stop_at = 0.0
        self.lock_ext = False
        # wakes the cycle on release (it does not wait for the next tick to empty the queue and stop
        # sending)
        self.wake = threading.Event()
        # the device (browser id) that holds the control now: only it can change the held vector or release it
        # (the stop operations without `release` still stop everything). "" = an unidentified caller (compatibility).
        self.who = None

    def held(self):
        return self.xy is not None or self.z is not None or self.ext is not None

    def may(self, owner):
        """The caller may change the held vector: nothing is held, or it is the holder, or either side has no device."""
        return not self.held() or not self.who or not owner or self.who == owner

    def claim(self, owner):
        if not self.held():
            self.who = owner or ""

    def forget_if_free(self):
        if not self.held():
            self.who = None

    def block_until_release(self):
        with self.lock:
            self.lock_xy = self.lock_z = self.lock_ext = True
            self.xy = None
            self.z = None
            self.ext = None
            self.who = None
        self.wake.set()

    def set_xy(self, nx, ny, speed_percent, owner=""):
        with self.lock:
            if self.lock_xy or not self.may(owner):
                return
            now = time.monotonic()
            if self.xy is None and now - self.xy_stop_at < STOP_GRACE_S:
                return  # arrived late, after the stop (see STOP_GRACE_S)
            # Diagnosis (2026-10-09, "the sliders hesitate"): gap between browser updates while
            # holding. The jog heartbeat sends every 300 ms; > 450 ms = something delayed it (busy
            # browser or slow HTTP). It is summarised on release.
            if self.xy is not None and self.xy_last_update:
                gap = now - self.xy_last_update
                self.gap_n += 1
                self.gap_max = max(self.gap_max, gap)
                if gap > 0.45:
                    self.gap_slow += 1
            else:
                self.gap_n, self.gap_max, self.gap_slow = 0, 0.0, 0
            self.claim(owner)
            self.xy = (nx, ny)
            self.xy_last_update = now
            self.speed_percent = speed_percent

    def stop_xy(self, owner="", release=False):
        with self.lock:
            if release and not self.may(owner):
                return  # another device let go of ITS control: this one keeps moving
            if self.xy is not None and self.gap_n >= 3 and self.gap_slow:
                _log(f"xy session: {self.gap_n} updates, max gap {self.gap_max * 1000:.0f} ms, {self.gap_slow} gaps > 450 ms")
            self.xy = None
            self.xy_stop_at = time.monotonic()
            self.lock_xy = False
            self.forget_if_free()
        self.wake.set()

    def set_z(self, z_val, speed_percent, owner=""):
        with self.lock:
            if self.lock_z or not self.may(owner):
                return
            now = time.monotonic()
            if self.z is None and now - self.z_stop_at < STOP_GRACE_S:
                return  # arrived late, after the stop (see STOP_GRACE_S)
            self.claim(owner)
            self.z = z_val
            self.z_last_update = now
            self.speed_percent = speed_percent

    def stop_z(self, owner="", release=False):
        with self.lock:
            if release and not self.may(owner):
                return
            self.z = None
            self.z_stop_at = time.monotonic()
            self.lock_z = False
            self.forget_if_free()
        self.wake.set()

    def set_ext(self, letter, val, speed_percent, owner=""):
        with self.lock:
            if self.lock_ext or not self.may(owner):
                return
            now = time.monotonic()
            if self.ext is None and now - self.ext_stop_at < STOP_GRACE_S:
                return
            self.claim(owner)
            self.ext = (letter, val)
            self.ext_last_update = now
            self.speed_percent = speed_percent

    def stop_ext(self, owner="", release=False):
        with self.lock:
            if release and not self.may(owner):
                return
            self.ext = None
            self.ext_stop_at = time.monotonic()
            self.lock_ext = False
            self.forget_if_free()
        self.wake.set()

    def snapshot_ext(self):
        with self.lock:
            return self.ext, self.ext_last_update

    def snapshot(self):
        with self.lock:
            return self.xy, self.xy_last_update, self.z, self.z_last_update, self.speed_percent


_state = _State()


def set_xy(nx, ny, speed_percent, owner=""):
    _state.set_xy(nx, ny, speed_percent, owner)


def stop_xy(owner="", release=False):
    """release=True: the device `owner` lets go of its control (ignored when another device holds it); without it, it stops everything."""
    _state.stop_xy(owner, release)


def set_z(z_val, speed_percent, owner=""):
    _state.set_z(z_val, speed_percent, owner)


def stop_z(owner="", release=False):
    _state.stop_z(owner, release)


def stop_all():
    """Stops every held control (a take over of the control, the emergency stop)."""
    _state.stop_xy()
    _state.stop_z()
    _state.stop_ext()


def held():
    """Some control is held (a gesture in progress)."""
    with _state.lock:
        return _state.held()


def holder():
    """Device that holds the jog now ("" = unknown or nobody)."""
    with _state.lock:
        return (_state.who or "") if _state.held() else ""


AXES_JOG = ("X", "Y", "Z")


def set_ext(letter, val, speed_percent, owner=""):
    letter = str(letter or "").strip().upper()
    if len(letter) == 1 and letter.isalpha() and letter not in AXES_JOG:
        _state.set_ext(letter, val, speed_percent, owner)


def stop_ext(owner="", release=False):
    _state.stop_ext(owner, release)


def _max_feed_xy(speed_percent):
    return FEED_MIN + (speed_percent / 100.0) * (FEED_MAX - FEED_MIN)


def _max_feed_z(speed_percent):
    return _max_feed_xy(speed_percent) * Z_FEED_RATIO


def _get_status(cache):
    now = time.monotonic()
    if cache["status"] is not None and now - cache["at"] < STATUS_POLL_S:
        return cache["status"]
    try:
        # 2026-10-12: from the single subscription to DSF (in memory; before, a GET /machine/status
        # of 110-130 ms). STATUS_POLL_S is kept.
        data = machine_state.get_status(timeout=2)
        cache["status"] = (data.get("state") or {}).get("status")
        # Machine mode ("FFF" | "CNC" | "Laser"): in Laser every jog G1 carries an explicit S0 (see
        # how the G1 is built in the loop).
        cache["machine_mode"] = (data.get("state") or {}).get("machineMode")
        cache["fail_count"] = 0
        # 2026-10-08, fourth round: it also caches the CONFIGURED maximum speed (M203,
        # move.axes[].speed) of each axis -- see _rrf_axis_max_feed() below. It reuses this same
        # poll (it already ran every STATUS_POLL_S for the SAFE_STATUSES check), it does not add a
        # separate call.
        axes = (data.get("move") or {}).get("axes") or []
        axis_max = {}
        pos = {}
        limits = {}
        for a in axes:
            letter = a.get("letter")
            speed = a.get("speed")
            if letter and isinstance(speed, (int, float)) and speed > 0:
                axis_max[letter] = speed
            # 2026-10-08: position and limits (M208) of each axis with homing, to clip the jog
            # segments to the limit (see _clamp_to_limit)
            if letter and a.get("homed") and isinstance(a.get("machinePosition"), (int, float)):
                pos[letter] = a["machinePosition"]
                if isinstance(a.get("min"), (int, float)) and isinstance(a.get("max"), (int, float)):
                    limits[letter] = (a["min"], a["max"])
        if axis_max:
            cache["axis_max_feed"] = axis_max
        cache["pos"] = pos
        cache["limits"] = limits
        # No-limits mode (see "No-limits mode" below): what has to be saved on entering to restore
        # it on exit, and which axes have no homing.
        mv = data.get("move") or {}
        cache["limit_axes"] = mv.get("limitAxes")
        cache["no_moves_before_homing"] = mv.get("noMovesBeforeHoming")
        cache["pct"] = {
            a.get("letter"): a.get("percentCurrent")
            for a in axes
            if a.get("letter") and isinstance(a.get("percentCurrent"), (int, float))
        }
        cache["without_homing"] = [a.get("letter") for a in axes if a.get("letter") and a.get("visible", True) and not a.get("homed")]
        cache["axes_extra"] = [a.get("letter") for a in axes if a.get("letter") and a.get("letter") not in AXES_JOG and a.get("visible", True)]
        cache["global_free"] = bool(((data.get("global") or {}).get("jogFree")))
    except Exception as e:
        cache["fail_count"] = cache.get("fail_count", 0) + 1
        _log(f"state check failed ({e}), fail_count={cache['fail_count']}")
        # Tolerate an isolated failure before really assuming the connection is lost -- same
        # reasoning as the catch() of jogCheckEnabled in EmergencyFab.js.
        if cache["fail_count"] >= 2:
            cache["status"] = None
    cache["at"] = now
    return cache["status"]


def _load_settings():
    """Applies SETTINGS_FILE if it changed (mtime). It never raises."""
    import os
    g = globals()
    if not _AJ_FACTORY:
        for k, (name, lo, hi) in _AJ_LIMITS.items():
            _AJ_FACTORY[name] = g[name]
    try:
        mt = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        mt = None
    if mt == _aj_mtime[0]:
        return
    _aj_mtime[0] = mt
    payload = {}
    if mt is not None:
        try:
            with open(SETTINGS_FILE) as f:
                payload = json.load(f) or {}
        except Exception as e:
            _log(f"settings: could not read {SETTINGS_FILE} ({e}), the factory ones stay")
            payload = {}
    applied = []
    for k, (name, lo, hi) in _AJ_LIMITS.items():
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            g[name] = min(max(float(v), lo), hi)
        else:
            g[name] = _AJ_FACTORY[name]
        applied.append(f"{name}={g[name]:g}")
    idle = payload.get("free") if isinstance(payload, dict) else None
    _FREE_CFG.clear()
    _FREE_CFG.update(_free_cfg_clean(idle))
    _log("settings: " + ", ".join(applied) + f"; without limits: {_FREE_CFG}")


def _rrf_axis_max_feed(cache, letter):
    # None = no data yet (first tick, or the last poll failed) -- the caller must treat it as "no
    # additional ceiling known", NOT as 0 (that would cut the whole jog because of a network
    # hiccup).
    return (cache.get("axis_max_feed") or {}).get(letter)


# How many codes can be waiting in the queue (not counting the one the sender already has in flight
# right now) -- see the big comment at the top of the file. Small on purpose: the goal is to give
# RRF just the margin it needs not to empty its queue between ticks, not to accumulate a big
# remainder of movement after release.
SEND_QUEUE_MAXSIZE = 1

_send_queue = None
_sender_started = False


class _JogConnection:
    """The jog's OWN CommandConnection, never shared with main.py's `bridge` (used by motor_poller/consumption_poller/etc) -- see the big comment at the top of the file about why sharing that connection (and its lock) caused the real shake."""

    def __init__(self):
        self.lock = threading.Lock()
        self.conn = None
        # how many times it connected (the first counts): the sender sends G91 again before the
        # first G1 that goes out through a new connection (2026-10-12, finding 1 of MOVEMENT-AUDIT;
        # see _sender_loop)
        self.connections = 0

    def _ensure_connected(self, attempts=None):
        """attempts=None: wait as long as needed (as always). With a number, it gives up after that many attempts (ConnectionError): the closing G90 cannot hang forever in a thread."""
        n = 0
        while self.conn is None:
            n += 1
            try:
                conn = CommandConnection()
                conn.connect()
                self.conn = conn
                self.connections += 1
                _log("dedicated CommandConnection of the jog connected")
            except Exception as e:
                if attempts is not None and n >= attempts:
                    raise ConnectionError(M("jog_move_no_connection_dsf", e=e))
                _log(f"could not connect the dedicated CommandConnection ({e}), retrying in 2s")
                time.sleep(2)

    def connect_to(self):
        """Connects if needed (before deciding whether the G91 has to be repeated)."""
        with self.lock:
            self._ensure_connected()

    def send(self, gcode, chan=None):
        with self.lock:
            self._ensure_connected()
            try:
                # async_exec=True -- see the note "2026-10-08 (third round)" at the top of the file:
                # perform_simple_code WITHOUT this blocks ~75-80 ms waiting for the formatted reply
                # from RRF (measured live), well above any reasonable TICK_MS. With async_exec=True
                # the call returns in ~1 ms (also measured) -- the reply is discarded (it comes out
                # as a generic console message in DWC instead of being returned here), but we do not
                # need it: we never read the return value of a jog G1.
                return ipc_stats.call("code", "jog_move", self.conn.perform_simple_code, gcode, channel=chan or communication.channel_jog(), async_exec=True)
            except Exception as e:
                _log(f"error sending '{gcode}' on the dedicated connection ({e}), it will reconnect")
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                raise

    def send_sync(self, gcode, chan=None, attempts_connection=None):
        """Like send() but WAITING for RRF's reply (text). Only for the rare things (enter/exit the no-limits mode, query M915, G90/G91): never for the jog G1s (see async_exec in send)."""
        with self.lock:
            self._ensure_connected(attempts_connection)
            try:
                return str(ipc_stats.call("code", "jog_move", self.conn.perform_simple_code, gcode, channel=chan or communication.channel_jog()) or "")
            except Exception as e:
                _log(f"error sending (sync) '{gcode}' ({e}), it will reconnect")
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                raise


_jog_conn = _JogConnection()


# ---- Jog G91/G90: the closing G90 is never dropped ----
# 2026-10-12 (finding 1 of docs-internal/MOVEMENT-AUDIT.md): the releasing G90 went through the same
# size-1 queue as the G1s and _drain_pending_g1() emptied it entirely on the next pass; a failed
# send also lost it. The jog channel (SBC by default, the G-code bridge's) stayed in G91 and the
# next absolute G1 from another program came out relative. Now:
# - the queue only drops G1s; G90/G91 stay (_drain_pending_g1);
# - the sender sends them WAITING for the reply and retries (_send_modal);
# - the channel where the G91 was left open is remembered (_modal["open"], also on disk: G91_MARK)
# and the G90 goes to THAT channel, even if the jog channel changed in between;
# - if the G90 does not go out: active risk (red bar and lights, risk_rules.py) and the loop retries
# it every G90_RETRY_S until it goes out;
# - when the service starts with a gesture that was left open (G91_MARK), or after reconnecting,
# G90/G91 again before going on.
MODAL = ("G90", "G91")
G90_ATTEMPTS = 4
G90_WAIT_S = 0.3
G90_RETRY_S = 2.0
G90_RISK_ID = "jog_g91"
MARK_G91 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jog_g91_open.json")
_modal = {
    "open": None,  # name of the channel with a G91 without a confirmed G90 (None = none)
    "failure_g91": False,  # the last G91 was not confirmed: do not send G1 (they would come out absolute)
    "connection": 0,  # _jog_conn.connections when the last G91 was sent
    "g90_in_queue": False,
    "last_attempt": 0.0,  # monotonic of the last requested G90 (retries of the loop)
    "risk": False,
}


def _name_channel(ch):
    n = getattr(ch, "name", None) or str(ch or "")
    return n.split(".")[-1]


def _channel_of(label):
    try:
        return communication._code_channel(label)
    except Exception:
        return None


def _mark_save(label):
    try:
        tmp = MARK_G91 + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"channel": label, "since": int(time.time())}, f)
        os.replace(tmp, MARK_G91)
    except Exception as e:
        _log(f"G91: could not save the mark ({e})")


def _mark_delete():
    try:
        os.remove(MARK_G91)
    except OSError:
        pass


def _mark_load():
    """On startup: a gesture that was left open (service down in the middle)."""
    try:
        with open(MARK_G91) as f:
            n = str((json.load(f) or {}).get("channel") or "")
    except Exception:
        return
    if n:
        _modal["open"] = n
        _log(f"G91: a gesture was left open on {n} before the restart; G90 is sent there")


def _send_with_retry(code, chan):
    for i in range(G90_ATTEMPTS):
        try:
            r = _jog_conn.send_sync(code, chan=chan, attempts_connection=1)
            if not _free_error(r):
                return True
            _log(f"'{code}' answered {r.strip()} (attempt {i + 1})")
        except Exception as e:
            _log(f"'{code}' was not sent ({type(e).__name__}: {e}) (attempt {i + 1})")
        time.sleep(G90_WAIT_S)
    return False


def _g90_en(label):
    """Synchronous G90 on the channel `name`. True if RRF confirmed it."""
    if _send_with_retry("G90", _channel_of(label)):
        if _modal["open"] == label:
            _modal["open"] = None
            _mark_delete()
        if _modal["risk"]:
            _modal["risk"] = False
            try:
                import risk_rules
                risk_rules.finish(G90_RISK_ID)
            except Exception:
                pass
            _log(f"G90: finally confirmed on {label}")
        return True
    _log(f"G90: could NOT be sent on {label}; the channel may still be in G91 (relative). Retrying every {G90_RETRY_S:g} s")
    heartbeats.error("jog", RuntimeError(f"G90 not confirmed on {label}"))
    if not _modal["risk"]:
        _modal["risk"] = True
        try:
            import risk_rules
            risk_rules.launch(G90_RISK_ID, M("jog_move_channel_may_have_been_left_g91", label=label), 6 * 3600)
        except Exception:
            pass
    return False


def _send_modal(code):
    chan = communication.channel_jog()
    label = _name_channel(chan)
    if code == "G90":
        _modal["g90_in_queue"] = False
        _g90_en(_modal["open"] or label)
        return
    # G91: if one was left open on another channel (the jog channel changed), it is closed there
    # first. It is marked BEFORE sending: if the reply is lost but RRF applied it, the closing G90
    # still goes out.
    if _modal["open"] and _modal["open"] != label:
        _g90_en(_modal["open"])
    if _modal["open"] != label:
        _modal["open"] = label
        _mark_save(label)
    ok = _send_with_retry("G91", chan)
    _modal["failure_g91"] = not ok
    _modal["connection"] = _jog_conn.connections
    if not ok:
        _log(f"G91: not confirmed on {label}; the G1s of this gesture are not sent")


def _sender_loop():
    while True:
        code = _send_queue.get()
        try:
            if code in MODAL:
                _send_modal(code)
            else:
                # a relative G1 through a channel without a confirmed G91 would come out ABSOLUTE:
                # if the jog channel changed or the connection was rebuilt (the board may have
                # restarted), G91 again first
                _jog_conn.connect_to()
                if _modal["open"] != _name_channel(communication.channel_jog()) or _modal["connection"] != _jog_conn.connections:
                    _send_modal("G91")
                if not _modal["failure_g91"]:
                    _jog_conn.send(code)
        except Exception as e:
            _log(f"error sending '{code}': {type(e).__name__}: {e}")
            heartbeats.error("jog", e)
        _send_queue.task_done()


def _ensure_sender():
    global _send_queue, _sender_started
    if _sender_started:
        return
    _send_queue = queue.Queue(maxsize=SEND_QUEUE_MAXSIZE)
    threading.Thread(target=_sender_loop, daemon=True).start()
    _sender_started = True


def _enqueue_g1(code):
    try:
        _send_queue.put_nowait(code)
        return True
    except queue.Full:
        # The sender cannot keep up at this instant -- skip this tick instead of blocking the
        # scheduler (better to lose a segment of ~TICK_MS than to let the loop fall behind and
        # desynchronise the watchdog).
        pass


def _enqueue_mode(code, wait_s=0.5):
    # G91/G90: unlike the G1s (see _enqueue_g1), these always have to arrive -- they are rare (once
    # per gesture), so waiting for room in the queue here does not affect the real cadence of the
    # tick. With a cap: if the sender is stuck (no connection) the loop does not hang; the caller
    # retries (False = it did not go in).
    try:
        _send_queue.put(code, timeout=wait_s)
    except queue.Full:
        return False
    if code == "G90":
        _modal["g90_in_queue"] = True
        _modal["last_attempt"] = time.monotonic()
    return True


def _request_g90():
    """Queues the closing G90 if there is not one already waiting. True if it stayed requested (queued or already queued)."""
    if _modal["g90_in_queue"]:
        return True
    return _enqueue_mode("G90")


def _g90_due():
    """A G91 was left unclosed (failed G90, gesture open before a restart, channel change): the G90 has to be retried."""
    return bool(_modal["open"]) and not _modal["g90_in_queue"] and time.monotonic() - _modal["last_attempt"] >= G90_RETRY_S


def _drain_pending_g1():
    # Empties any G1 that was left queued WITHOUT being sent (the sender has not picked it up yet)
    # at the moment of release -- see the note "2026-10-08 (second round)" at the top of the file.
    # That segment never reaches the machine. What the sender is already sending at this instant (if
    # any) is still unavoidable, but this avoids adding a second stretch of overshoot on top.
    # 2026-10-12: ONLY the G1s. A queued G90/G91 goes back to the queue in the same order (before,
    # the releasing G90 was discarded: finding 1). The loop is the only one that queues, so there is
    # room again.
    remaining = []
    while True:
        try:
            c = _send_queue.get_nowait()
            _send_queue.task_done()
        except queue.Empty:
            break
        if c in MODAL:
            remaining.append(c)
    for c in remaining:
        _send_queue.put(c)


# ---- No-limits mode (requested 2026-10-10) ----
#
# "Move the axes without homing or outside the limits, with many warnings, that switches itself off
# if there is no movement, and with guards: the drivers, to see when an axis hits something or goes
# a few extra millimetres beyond what is defined."
#
# RRF blocks G1 on axes without homing ("insufficient axes homed") and outside M208. G1 H2 allows
# them by movement, but each H2 WAITS for the machine to stop before and after (RRF 3.6.1
# GCodes.cpp: LockCurrentMovementSystemAndWaitForStandstill + waitingForSpecialMoveToComplete): with
# the short jog segments it would be jerky. That is why, only while the mode lasts: M564 S0 H0, and
# on exit the values that were there are restored (move.limitAxes / move.noMovesBeforeHoming).
# Guards, all at once:
# 1. margin: on axes WITH homing the jog does not go past M208 +- marginMm;
# 2. ceiling speed (speedPct of the jog's maximum);
# 3. reduced current (M913): if it hits something, the motor skips steps instead of forcing;
# 4. crash detection by driver (StallGuard, M915 X Y Z ... R2): RRF runs sys/driver-stall.g, which
# raises global.jogFreeStallN (api_macros.py sees it in the subscription and calls free_crash) -> it
# cuts and exits; it only detects above crashSteps full steps/s;
# 5. it exits by itself: timeoutS without movement, a job that starts, or a live job;
# 6. backup on the board: while it lasts, a heartbeat is sent (global.jogFreeTs);
# sys/workshop/macros/jogFreeFailsafe.g (called from sys/daemon.g) restores everything if 10 s pass
# without a heartbeat (Pi or plugin down);
# 7. lock (requested 2026-10-10): while it lasts, an InterceptConnection of its own checks
# G0-G3/G28-G30/M32/M37 on all channels EXCEPT the jog's (jog_channel; intercepting its own channel
# made the jog hesitate, see _lock_loop). The ones from the HTTP channel (DWC console and motion
# panel) also pass; any other origin (file job, other macros/services, starting a job) is rejected
# with an error, the mode switches off and a notice (M291) appears so the person checks.
# NOTE (2026-10-12, finding 3 of MOVEMENT-AUDIT): the bridge's live job sends through SBC. If the
# jog also goes through SBC (the default), what the bridge sends does NOT pass through this lock.
# That is why, with the jog on the bridge's channel, the mode is not activated if there are
# connections or recent activity from the bridge, and it switches off by itself if they appear
# (_free_bridge_reason). With the jog on Aux2 (its own channel) the lock does cover the bridge.
# Two modes: "noHoming" (M564 S0 H0: no homing and outside M208) and "outsideLimits" (M564 S0 H1:
# requires homing of X/Y/Z, only lets the margin through).
# When the plugin starts, if global.jogFree was left true, it is restored anyway.
FREE_MODES = ("withoutHoming", "outsideLimits")
_FREE_DEF = {"mode": "withoutHoming", "color": "#ff1744", "timeoutS": 60, "marginMm": 5.0, "speedPct": 25, "correctionXY": 50, "correctionZ": 100, "crash": True, "crashSens": 8, "crashSteps": 100}
_FREE_LIM = {"timeoutS": (10, 600), "marginMm": (0.0, 30.0), "speedPct": (5, 100), "correctionXY": (20, 100), "correctionZ": (40, 100), "crashSens": (-64, 63), "crashSteps": (20, 400)}
_FREE_CFG = dict(_FREE_DEF)
STALL_MACRO = paths.SYS + "/driver-stall.g"
STALL_MACRO_MARK = "workshop-JOG-free"
DAEMON_G = paths.SYS + "/daemon.g"
FAILSAFE_MACRO = "0:/sys/workshop/macros/jogFreeSet.g"
FREE_HEARTBEAT_S = 2.0
FREE_PUBLISH_S = 1.0
STALL_MACRO_TEXT = f"""; driver-stall.g -- RepRapFirmware runs it when a driver configured with
; M915 ... R2 detects a stall (StallGuard). WorkshopService created it for the
; "without limits" mode of the WorkshopJog jog. If you change it, delete the mark
; below and the jog never touches it again (and does not use the stall detection).
; {STALL_MACRO_MARK}
; Crash calibration (Motors page, sys/workshop/macros/crash-cal.g): only counts. With the
; jog without limits active it ALWAYS stops (even if a calibration cut halfway
; left global.crashCal at true).
if exists(global.crashCal) && global.crashCal && !(exists(global.jogFree) && global.jogFree)
  if exists(global.crashCalHit)
    set global.crashCalHit = global.crashCalHit + 1
elif exists(global.jogFree) && global.jogFree
  ; WorkshopService sees these two globals in its object model subscription and stops the jog
  if !exists(global.jogFreeStallN)
    global jogFreeStallN = 0
  if !exists(global.jogFreeStallDrv)
    global jogFreeStallDrv = ""
  set global.jogFreeStallDrv = param.B ^ "." ^ param.D
  set global.jogFreeStallN = global.jogFreeStallN + 1
else
  var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false
  if var.en
    echo "Stall detected on driver " ^ param.B ^ "." ^ param.D ^ ": " ^ param.S
  else
    echo "Choque detectado en el driver " ^ param.B ^ "." ^ param.D ^ ": " ^ param.S
"""


def _free_cfg_clean(o):
    c = dict(_FREE_DEF)
    if isinstance(o, dict):
        for k, (lo, hi) in _FREE_LIM.items():
            v = o.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                c[k] = min(max(v, lo), hi)
        if isinstance(o.get("crash"), bool):
            c["crash"] = o["crash"]
        if o.get("mode") in FREE_MODES:
            c["mode"] = o["mode"]
        import re as _re

        if isinstance(o.get("color"), str) and _re.fullmatch(r"#[0-9a-fA-F]{6}", o["color"]):
            c["color"] = o["color"]
    return c


class _Free:
    def __init__(self):
        self.lock = threading.Lock()
        self.is_active = False
        self.request = None  # None | ("on", "") | ("off", motivo)
        self.since = 0.0  # time.time()
        self.last_mov = 0.0  # time.monotonic() of the last segment sent
        self.gesture_since = 0.0  # time.monotonic() of the first segment of the current gesture
        self.cfg = dict(_FREE_DEF)
        self.prev = {}
        self.crash_on = False
        self.crash_mms = None
        self.without_homing = []
        self.last = None  # {motivo, texto, at}
        self.notice = ""
        self.last_heartbeat = 0.0
        self.last_published = 0.0


_free = _Free()

_FREE_TEXTS = {
    "user": M("jog_move_left_on_request"),
    "inactive": M("jog_move_turned_itself_off_no_movement"),
    "job": M("jog_move_turned_itself_off_job_started"),
    "in_live": M("jog_move_turned_itself_off_there_live_job"),
    "crash": M("jog_move_crash_detected_by_driver"),
    "startup": M("jog_move_restored_when_service_started"),
    "error": M("jog_move_could_not_activate"),
    "blocked": M("jog_move_blocked_move_arrived_not_from_jog"),
    "bridge": M("jog_move_turned_itself_off_g_code_bridge"),
}


def free_request(on, reason="user"):
    with _free.lock:
        _free.request = ("on", "") if on else ("off", reason)
    _state.wake.set()


CRASH_IGNORE_STARTUP_S = 0.4  # when starting, the acceleration gives false StallGuard readings
CRASH_STILL_S = 0.6  # with no segments sent in this span the motor is still: no crash is possible


def free_crash(board, driver):
    """Called by api_macros.py when sys/driver-stall.g raises global.jogFreeStallN: cut RIGHT NOW (state only, never G-code from the handler) and leave the mode on the next tick. 2026-10-10: in the test a false crash fired when starting to move X; those of the first instant of each gesture and those with the motor still are discarded."""

    def _n(v):
        try:
            return str(int(float(v)))
        except (TypeError, ValueError):
            return str(v)

    drv = f"{_n(board)}.{_n(driver)}"
    if not _free.is_active:
        return
    now = time.monotonic()
    if now - _free.gesture_since < CRASH_IGNORE_STARTUP_S:
        _log(f"without limits: stall of driver {drv} ignored (start of the move, unreliable reading)")
        return
    if now - _free.last_mov > CRASH_STILL_S:
        _log(f"without limits: stall of driver {drv} ignored (motor still)")
        return
    _log(f"without limits: STALL on driver {drv}")
    _state.stop_xy()
    _state.stop_z()
    with _free.lock:
        _free.request = ("off", f"crash:{drv}")
    _state.wake.set()


def free_active():
    return _free.is_active


def free_color():
    """Colour of the blink chosen in the jog, as an LED colour {r,g,b,w} (for the status lights while the mode lasts)."""
    h = str((_free.cfg or {}).get("color") or "").lstrip("#")
    if len(h) != 6:
        return None
    # 2026-10-10 ("it is not a red like in the interface"): the colour comes from a screen selector
    # (#ff1744) and the screen has gamma; the LED is linear: 27 % of blue, almost invisible on
    # screen, looked pink on the strip. It is converted to LED values with gamma 2.2 (#ff1744 ->
    # 255, 1, 13).
    def led(c):
        return int(round(255 * (c / 255.0) ** 2.2))

    try:
        return {"r": led(int(h[0:2], 16)), "u": led(int(h[2:4], 16)), "b": led(int(h[4:6], 16)), "w": 0}
    except ValueError:
        return None


_cache_ref = [None]  # the loop's status_cache (for limits_alert)
CRASH_ALERT_S = 15


def alert_limits():
    """For the status lights (status_light, "crash" state): a crash detected less than CRASH_ALERT_S ago, or some axis with homing outside its M208 limits (it happens in the no-limits mode, inside the margin)."""
    u = _free.last
    if u and u.get("reason") == "crash" and time.time() * 1000 - u.get("at", 0) < CRASH_ALERT_S * 1000:
        return True
    c = _cache_ref[0] or {}
    pos, lim = c.get("pos") or {}, c.get("limits") or {}
    for L, p in pos.items():
        if L in lim and (p < lim[L][0] - 0.05 or p > lim[L][1] + 0.05):
            return True
    return False


def _free_publish(bridge, force=False):
    now = time.monotonic()
    if not force and now - _free.last_published < FREE_PUBLISH_S:
        return
    _free.last_published = now
    c = _free.cfg
    remaining = max(0.0, c["timeoutS"] - (now - _free.last_mov)) if _free.is_active else None
    try:
        bridge.set_status(
            "jogFree",
            {
                "active": _free.is_active,
                "mode": c.get("mode"),
                "color": c.get("color"),
                "since": int(_free.since * 1000) if _free.is_active else None,
                "remainingS": round(remaining, 1) if remaining is not None else None,
                "timeoutS": c["timeoutS"],
                "marginMm": c["marginMm"],
                "speedPct": c["speedPct"],
                "vMaxMmS": round(FEED_MAX / 60.0 * c["speedPct"] / 100.0, 1),
                "correctionXY": c["correctionXY"],
                "correctionZ": c["correctionZ"],
                "crash": _free.crash_on,
                "crashMmS": _free.crash_mms,
                "withoutHoming": _free.without_homing,
                "backup": _free_backup_installed(),
                "last": _free.last,
                "notice": _free.notice,
            },
        )
    except Exception as e:
        _log(f"without limits: could not publish ({e})")


def _free_backup_installed():
    try:
        with open(DAEMON_G, encoding="utf-8", errors="replace") as f:
            return "jogFreeFailsafe" in f.read()
    except OSError:
        return False


def _free_macro_crash():
    """True if sys/driver-stall.g is ours (it creates it if it does not exist). If it is somebody else's it is not touched, and the mode runs without crash detection."""
    import os

    try:
        if os.path.exists(STALL_MACRO):
            with open(STALL_MACRO, encoding="utf-8", errors="replace") as f:
                current = f.read()
            if STALL_MACRO_MARK not in current:
                return False
            if current == STALL_MACRO_TEXT:
                return True
            # ours but from an earlier version: it is updated
        with open(STALL_MACRO, "w", encoding="utf-8") as f:
            f.write(STALL_MACRO_TEXT)
        _log("without limits: sys/driver-stall.g created or updated")
        return True
    except OSError as e:
        _log(f"without limits: could not create driver-stall.g ({e})")
        return False


def _parse_m915(raw_text):
    """'Driver 0.0: stall threshold 3, filter on, full steps/sec 200 (40.0 mm/sec),
    ... action on stall: none' -> [{id, sgt, filt, pasos, mms, accion}]"""
    import re

    out = []
    for m in re.finditer(
        r"Driver ([\d.]+): stall threshold (-?\d+), filter (on|off), full steps/sec (\d+) \(([\d.]+) mm/sec\).*?action on stall: (none|log|raise event)",
        raw_text,
    ):
        out.append(
            {
                "id": m.group(1),
                "sgt": int(m.group(2)),
                "filt": m.group(3) == "on",
                "steps": int(m.group(4)),
                "mms": float(m.group(5)),
                "action": {"none": 0, "log": 1, "raise event": 2}[m.group(6)],
            }
        )
    return out


def _free_error(raw_text):
    return "error" in str(raw_text or "").lower()


def _free_enter(bridge, status_cache):
    status_cache["at"] = 0.0
    status = _get_status(status_cache)
    if status not in SAFE_STATUSES:
        _free.last = {"reason": "error", "text": M("jog_move_could_not_activate_machine_not_free", status=str(status)), "at": int(time.time() * 1000)}
        return
    if _in_live(bridge):
        _free.last = {"reason": "error", "text": M("jog_move_could_not_activate_live_job"), "at": int(time.time() * 1000)}
        return
    pm = _free_bridge_reason(force=True)
    if pm:
        _free.last = {"reason": "error", "text": M("jog_move_could_not_activate_reason", reason=pm), "at": int(time.time() * 1000)}
        return
    c = dict(_FREE_CFG)
    _free.cfg = c
    if c["mode"] == "outsideLimits" and status_cache.get("without_homing"):
        _free.last = {
            "reason": "error",
            "text": M("jog_move_could_not_activate_outside_limits_needs_homing", axes=", ".join(status_cache["without_homing"])),
            "at": int(time.time() * 1000),
        }
        return
    the, nm = status_cache.get("limit_axes"), status_cache.get("no_moves_before_homing")
    prev = {
        "S": 1 if the is not False else 0,
        "H": 1 if nm is not False else 0,
        "pct": {k: v for k, v in (status_cache.get("pct") or {}).items()},
        "m915": [],
    }
    _free.prev = prev  # before changing anything: if something fails, this is restored
    _free.notice = ""
    _free.crash_on = False
    _free.crash_mms = None
    try:
        _drain_and_wait_for()
        # a crash calibration cut in the middle may have left global.crashCal true (driver-stall.g
        # only counted). If the global does not exist RRF answers an error that does not matter.
        try:
            _jog_conn.send_sync("set global.crashCal = false")
        except Exception:
            pass
        r = _jog_conn.send_sync(f'M98 P"{FAILSAFE_MACRO}" A1')
        if _free_error(r):
            raise RuntimeError(M("jog_move_failsafe_macro_missing", macro=FAILSAFE_MACRO, answer=r.strip()))
        if c["crash"]:
            if _free_macro_crash():
                prev["m915"] = _parse_m915(_jog_conn.send_sync("M915 X Y Z"))
                r = _jog_conn.send_sync(f'M915 X Y Z S{int(c["crashSens"])} F1 H{int(c["crashSteps"])} R2')
                if _free_error(r):
                    _free.notice = M("jog_move_crash_detection_not_available", answer=r.strip())
                else:
                    _free.crash_on = True
                    info = _parse_m915(_jog_conn.send_sync("M915 X Y Z"))
                    if info:
                        _free.crash_mms = max(d["mms"] for d in info)
            else:
                _free.notice = M("jog_move_crash_detection_disabled_sys_driver_stall")
        r = _jog_conn.send_sync("M564 S0 H0" if c["mode"] == "withoutHoming" else "M564 S0 H1")
        if _free_error(r):
            raise RuntimeError(r.strip())
        extra = "".join(f" {L}{int(c['correctionXY'])}" for L in (status_cache.get("axes_extra") or []))
        _jog_conn.send_sync(f'M913 X{int(c["correctionXY"])} Y{int(c["correctionXY"])} Z{int(c["correctionZ"])}' + extra)
    except Exception as e:
        _log(f"without limits: could not enter ({e}), restoring")
        _free.is_active = True  # so that _free_exit restores what it managed to change
        _free_exit(bridge, "error", detail=e.args[0] if e.args and isinstance(e.args[0], Msg) else str(e))
        return
    now = time.monotonic()
    _free.is_active = True
    _free.since = time.time()
    _free.last_mov = now
    _free.last_heartbeat = now
    _free.without_homing = list(status_cache.get("without_homing") or [])
    _free.last = None
    _block_start()
    _log(f"without limits: ON {c}; not homed: {_free.without_homing}; stall: {_free.crash_on} ({_free.crash_mms} mm/s)")


def _free_exit(bridge, reason, detail="", cause=None):
    if not _free.is_active:
        return
    _state.stop_xy()
    _state.stop_z()
    _drain_and_wait_for()
    p = _free.prev or {}
    ok = True
    codes = [f'M564 S{p.get("S", 1)} H{p.get("H", 1)}']
    pct = p.get("pct") or {}
    codes.append("M913 " + " ".join(f"{k}{int(round(v))}" for k, v in sorted(pct.items())) if pct else "M913 X100 Y100 Z100")
    if _free.crash_on or p.get("m915"):
        if p.get("m915"):
            for d in p["m915"]:
                drv = d["id"][2:] if d["id"].startswith("0.") else d["id"]  # placa principal: P3, expansion: P40.0
                codes.append(f'M915 P{drv} S{d["sgt"]} F{1 if d["filt"] else 0} H{d["steps"]} R{d["action"]}')
        else:
            codes.append("M915 X Y Z R0")
    for code in codes:
        try:
            r = _jog_conn.send_sync(code)
            if _free_error(r):
                ok = False
                _log(f"without limits: '{code}' answered {r.strip()}")
        except Exception as e:
            ok = False
            _log(f"without limits: could not restore with '{code}' ({e})")
    if ok:
        try:
            _jog_conn.send_sync("set global.jogFree = false")
        except Exception as e:
            _log(f"without limits: could not clear global.jogFree ({e}); the board failsafe will do it")
    else:
        _log("without limits: incomplete restore; global.jogFree stays true and the board restores by itself in 10 s (jogFreeFailsafe.g)")
    base = reason.split(":")[0]
    raw_text = _FREE_TEXTS.get(base, reason)
    if cause is None and base in ("crash", "blocked") and ":" in reason:
        cause = reason.split(":", 1)[1]
    if cause:
        raw_text = J([raw_text, M("in_parentheses", text=cause)], sep="")
    if detail:
        raw_text = J([raw_text, detail], sep=": ")
    _free.is_active = False
    _free.crash_on = False
    _block_stop()
    if base != "user":
        _state.block_until_release()
    _free.last = {"reason": base, "text": raw_text, "at": int(time.time() * 1000)}
    if base in ("crash", "blocked", "job", "in_live", "bridge"):
        _free_alert(raw_text)
    _log(f"without limits: off ({raw_text}); restored {'OK' if ok else 'with errors'}")


def _free_alert(raw_text):
    """Window in DWC (M291 S1: only a Close button, it blocks nothing) so the person checks the machine. Text in DWC's language."""
    m = M("jog_move_check_machine_before_going_on", text=raw_text)
    es = m.text("es").replace('"', "'")
    en = m.text("en").replace('"', "'")
    body = '{(exists(global.workshopLanguage) && global.workshopLanguage == "en") ? "' + en + '" : "' + es + '"}'
    try:
        _jog_conn.send("M291 P" + body + ' R"Jog" S1 T0')
    except Exception as e:
        _log(f"without limits: could not show the warning ({e})")


# ---- Lock of foreign movements while the mode lasts ----
BLOCK_FILTERS = ["G0", "G1", "G2", "G3", "G28", "G29", "G30", "M32", "M37"]
_block = {"thread": None, "stop": None}


def _block_start():
    if _block["thread"] is not None:
        return
    stop = threading.Event()
    _block["stop"] = stop
    h = threading.Thread(target=_block_loop, args=(stop,), daemon=True)
    _block["thread"] = h
    h.start()


def _block_stop():
    if _block["stop"] is not None:
        _block["stop"].set()
    _block["thread"] = None
    _block["stop"] = None


def _block_decide(code, jog_id):
    """None = let it pass; text = reject (and switch the mode off)."""
    type_name = str(getattr(code.type, "value", code.type))
    label = f"{type_name}{code.majorNumber}"
    chan = str(getattr(code.channel, "value", code.channel))
    if label in ("M32", "M37"):
        return M("jog_move_code_from_channel", code=label, channel=chan)
    if jog_id is not None and code.sourceConnection == jog_id:
        return None
    if chan == "HTTP":
        return None
    return M("jog_move_code_from_channel", code=label, channel=chan)


def _block_loop(stop):
    from dsf.connections import InterceptConnection, InterceptionMode
    from dsf.object_model.messages import MessageType

    conn = None
    try:
        # 2026-10-10 ("in no-limits mode the axes hesitate and Z went up and down when only up was
        # sent"): before, ALL the channels were intercepted, including the SBC one through which the
        # jog itself sends its G1s. Each segment made a round trip through this thread before
        # running: the movement arrived jerkily and kept moving ~2 s after release. The SBC channel
        # is now left out (it is the jog's and the Pi services'); jobs (File), queues, Telnet, USB,
        # etc. stay blocked, and HTTP (DWC) is still checked as before. The channel left out is the
        # jog's (config communication.jog_channel, SBC by default); it is read on entering the mode,
        # so a channel change applies from the next no-limits jog.
        from dsf.commands.code_channel import CodeChannel

        own = communication.channel_jog()
        chans = [c for c in CodeChannel if c != own and c.value != "Unknown"]
        conn = InterceptConnection(InterceptionMode.PRE, channels=chans, filters=BLOCK_FILTERS, timeout=1)
        conn.connect()
        _log("without limits: blocking of foreign moves on")
        while not stop.is_set():
            try:
                code = conn.receive_code()
            except TimeoutError:
                continue
            jog_id = getattr(_jog_conn.conn, "id", None) if _jog_conn.conn is not None else None
            reason = None
            try:
                reason = _block_decide(code, jog_id)
            except Exception as e:
                _log(f"without limits: the block could not decide ({e}); letting it through")
            if reason is None:
                conn.ignore_code()
                continue
            # the firmware console shows one plain text: it goes in the language of the records (Spanish)
            conn.resolve_code(MessageType.Error, str(M("jog_move_without_limits_move_blocked", reason=reason)))
            _log(f"without limits: BLOCKED {reason}: {code}")
            _state.stop_xy()
            _state.stop_z()
            with _free.lock:
                _free.request = ("off", "blocked", reason)
            _state.wake.set()
    except Exception as e:
        _log(f"without limits: the block failed ({type(e).__name__}: {e})")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        _log("without limits: blocking of foreign moves ended")


def _drain_and_wait_for():
    _drain_pending_g1()
    try:
        _send_queue.join()
    except Exception:
        pass


def _in_live(bridge):
    v = (getattr(bridge, "payload", {}) or {}).get("liveJob")
    return bool(v.get("active")) if isinstance(v, dict) else bool(v)


# ---- Who else is moving: the jog refuses (2026-10-12) ----
# Finding 2 of docs-internal/MOVEMENT-AUDIT.md: the jog backend only looked at state.status
# (idle/busy). A live job leaves the machine "busy", so the only lock was the page (up to 2 s late
# and free after 5 s without busy). Now the jog itself refuses, with the reason:
# - file job (job state.status; it used to just not send, now it says why);
# - open live job (plugins.WorkshopService.data.liveJob, live_job.py; all the time it is open, still
# or not);
# - recent G-code bridge activity (less than BRIDGE_RECENT_S). The service does not see the bridge's
# lines (it is another program, only on the Pi); what it can know:
# a) bridge-state.json written by the bridge. Bridge 3.0 (schema 2): `activity` with the absolute
# time of the last non-query order (`last_order_at`, from any client, received or finished) and the
# pending orders (`pending_orders`); see bridge_state_age_s().
# b) M3/M4/M5 on the SBC channel that are not the jog's (seen by main.py's interceptor:
# mark_bridge_if). The live job sends them at every cut.
# A client that is only connected, sending nothing, does not block (AUDIT 4.8.3). The threshold (20
# s) is greater than the per-line waits already measured in the bridge (15 s, pending item 3 of the
# diagnosis).
BRIDGE_RECENT_S = 20
BRIDGE_STATE = paths.DATA_DIR + "/bridge-state.json"
BRIDGE_QUERIES = ("M114", "M115", "M105", "M119", "M122", "M408", "M503", "M27", "M20", "M36", "BRIDGE")
STATES_FILE = job_states.MOVING_FILE  # "paused" no: ver JOG_STATUSES
_bridge = {"last_order": 0.0, "arch_at": 0.0, "arch": None, "cli_at": 0.0, "cli": 0, "end": 0.0}


# The program said the job is over (BRIDGE JOB END / CANCEL, or the person closed it): the orders it sent up to then (the end
# marker itself included) are no longer "activity", so the jog does not wait RECENT_S more seconds after a finished cut.
END_TOL_S = 3.0


def bridge_end_job(ts=None):
    _bridge["end"] = float(ts or time.time())
    _bridge["arch_at"] = 0.0  # the cached age of bridge-state.json is older than this mark


def mark_bridge_si(code, jog_id=None):
    """Called by main.py's interceptor with every M3/M4/M5: if it came through SBC and is not the jog's, it is bridge activity (or from another program through SBC)."""
    try:
        if _name_channel(getattr(code, "channel", None)) != "SBC":
            return
        if jog_id is None and _jog_conn.conn is not None:
            jog_id = getattr(_jog_conn.conn, "id", None)
        if jog_id is not None and getattr(code, "sourceConnection", None) == jog_id:
            return
        _bridge["last_order"] = time.time()
    except Exception:
        pass


BRIDGE_STATE_FRESH_S = 10  # a bridge-state.json older than this does not prove orders are still pending


def bridge_state_age_s(state, file_age_s=0.0, now=None):
    """Seconds since the last non-query line of any client, from a parsed
    bridge-state.json; None if there is no data.

    Schema 2 (bridge 3.0): state["activity"] has absolute times, so the age
    does not depend on when the file was written:
      pending_orders  orders sent to the machine and not finished yet (counted
                      only while the file is fresh, so a dead bridge cannot
                      block the jog forever);
      last_order_at   epoch of the last non-query line (received or finished).
    A state without either returns None."""
    now = time.time() if now is None else now
    # Bridge 3.x: the clients carry RELATIVE ages in whole seconds. The absolute epochs of the file reach us rounded to 6
    # digits (1.7921e9 = steps of 27 h), which made "last order 0 s ago" true half of the time (2026-10-15: the jog stayed
    # blocked after the live job had ended). The relative ages are the reliable data.
    cls = state.get("clients") if isinstance(state, dict) else None
    if isinstance(cls, list) and any(isinstance(c, dict) and "last_order_age_s" in c for c in cls):
        val = None
        for c in cls:
            if not isinstance(c, dict):
                continue
            if (c.get("pending_orders") or 0) > 0 and file_age_s <= BRIDGE_STATE_FRESH_S:
                return 0.0
            ag = c.get("last_order_age_s")
            if isinstance(ag, (int, float)):
                h = float(ag) + file_age_s
                val = h if val is None else min(val, h)
        return val
    act = state.get("activity") if isinstance(state, dict) else None
    if isinstance(act, dict):
        gen = act.get("generated_at")
        fresh = isinstance(gen, (int, float)) and (now - gen) <= BRIDGE_STATE_FRESH_S
        if fresh and (act.get("pending_orders") or 0) > 0:
            return 0.0
        last = act.get("last_order_at")
        return max(0.0, now - float(last)) if isinstance(last, (int, float)) else None
    return None


def _bridge_file_does_s():
    """Seconds since the last line (that is not a query) from any client according to bridge-state.json; None if there is no data. 1 s cache."""
    now = time.monotonic()
    if now - _bridge["arch_at"] < 1.0:
        return _bridge["arch"]
    _bridge["arch_at"] = now
    val = None
    try:
        route = BRIDGE_STATE
        age = max(0.0, time.time() - os.path.getmtime(route))
        with open(route) as f:
            e = json.load(f) or {}
        val = bridge_state_age_s(e, age)
    except Exception:
        val = None
    _bridge["arch"] = val
    return val


def bridge_activity_does_s():
    """Seconds since the last known activity of the bridge; None = never."""
    vals = []
    now = time.time()
    cut = _bridge["end"] + END_TOL_S if _bridge["end"] else 0.0
    if _bridge["last_order"] and _bridge["last_order"] > cut:
        vals.append(max(0.0, now - _bridge["last_order"]))
    a = _bridge_file_does_s()
    if a is not None and now - a > cut:
        vals.append(a)
    return min(vals) if vals else None


def _clients_bridge(force=False):
    """Connections open to the bridge (health_poller, `ss`). 2 s cache."""
    now = time.monotonic()
    if force or now - _bridge["cli_at"] >= 2.0:
        _bridge["cli_at"] = now
        try:
            import health_poller
            _bridge["cli"] = int(health_poller.clients_bridge() or 0)
        except Exception:
            _bridge["cli"] = 0
    return _bridge["cli"]


def _jog_on_bridge_channel():
    return _name_channel(communication.channel_jog()) == "SBC"


def _free_bridge_reason(force=False):
    """No-limits mode: if the jog goes through the bridge's channel (SBC), the lock does not see what the bridge sends (finding 3). Reason not to activate it / to switch it off, or "" if there is no problem."""
    if not _jog_on_bridge_channel():
        return ""
    n = _clients_bridge(force)
    if n:
        return M("jog_move_jog_goes_over_sbc_same_channel", n=n)
    h = bridge_activity_does_s()
    try:
        import motion_owner
        waiting = motion_owner.settings()[1]
    except Exception:
        waiting = BRIDGE_RECENT_S
    if h is not None and h < waiting:
        return M("jog_move_jog_goes_over_sbc_same_channel_2", int=int(h))
    return ""


def _live_does_s(bridge):
    """Seconds since the last activity of the open live job (head, M3/M4/M5, file progress); None if unknown. It reads live_job.py (memory up to date); if it is not there, the published data (up to 60 s late)."""
    latest = None
    try:
        import live_job
        latest = live_job.last_activity(live_job.read_in())
    except Exception:
        latest = None
    if not latest:
        v = (getattr(bridge, "payload", {}) or {}).get("liveJob")
        try:
            latest = time.mktime(time.strptime(v.get("lastActivity"), "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            latest = None
    return max(0.0, time.time() - latest) if latest else None


def state_block(bridge, actor=None):
    """(level, reason) why the jog does not move now, not counting confirmations. level: "" = free | "block" = does not move | "confirm" = live job open but still for more than BRIDGE_RECENT_S: it moves only if the person confirms (handlers/jog.py, parameter C1; see confirm()). 2026-10-13: the decision is the one of the single owner of the movement (motion_owner.py, class "move"): file job, bridge activity, live job and the reservations of other pages (a paused file job lets the jog move: RRF restores the positions on resume)."""
    import motion_owner

    return motion_owner.jog_block(bridge, actor)


# Jog confirmation with a still live job: the page gives it with C1 and it is valid CONFIRMATION_S
# from the last gesture; only for THAT job (name and start time) and it is lost if the job has
# activity again.
CONFIRMATION_S = 60
_conf = {"until": 0.0, "key": None, "who": ("", "")}


def _who(actor):
    a = actor or {}
    return (str(a.get("device") or ""), str(a.get("user") or ""))


def _same_who(actor):
    """The confirmation belongs to the device and person that gave it (an unidentified side matches, like before the identities)."""
    d, u = _who(actor)
    cd, cu = _conf["who"]
    return not (d and cd and d != cd) and not (u and cu and u != cu)


def _key_live(bridge):
    v = (getattr(bridge, "payload", {}) or {}).get("liveJob")
    return (v.get("name"), v.get("since")) if isinstance(v, dict) else None


def confirm(bridge, actor=None):
    """The person confirms moving with the live job still. True if it was valid. It holds for that device and person."""
    level, _ = state_block(bridge, actor)
    if level != "confirm":
        return False
    _conf["until"] = time.monotonic() + CONFIRMATION_S
    _conf["key"] = _key_live(bridge)
    _conf["who"] = _who(actor)
    return True


def confirmation_current(bridge, actor=None):
    return time.monotonic() < _conf["until"] and _conf["key"] == _key_live(bridge) and _same_who(actor)


def renew_confirmation(bridge, actor=None):
    if confirmation_current(bridge, actor):
        _conf["until"] = time.monotonic() + CONFIRMATION_S


def decide_block(bridge, actor=None):
    """(level, reason) with the confirmation applied: level "" if it can move."""
    level, reason = state_block(bridge, actor)
    if level == "confirm" and confirmation_current(bridge, actor):
        return "", ""
    return level, reason


def reason_block(bridge):
    """Why the jog cannot move now ("" = it can). Used by the loop (at the start and during each gesture) and handlers/jog.py (answer)."""
    return decide_block(bridge)[1]


_block_pub = {"reason": None}


def _publish_block(bridge, reason, level=None):
    """plugins.WorkshopService.data.jogBlock = {reason, confirm, at}; only on change. confirm=true: the page can ask for confirmation and resend with C1."""
    if level is None:
        level = "block" if reason else ""
    if (reason, level) == _block_pub["reason"]:
        return
    _block_pub["reason"] = (reason, level)
    try:
        bridge.set_status("jogBlock", {"reason": reason or None, "confirm": level == "confirm", "at": int(time.time())})
    except Exception as e:
        _log(f"could not publish jogBlock ({e})")


def gesture_active():
    """Something held, or a G91 still without its confirmed G90."""
    xy, _, z, _, _ = _state.snapshot()
    ext, _ = _state.snapshot_ext()
    return xy is not None or z is not None or ext is not None or bool(_modal["open"]) or _modal["g90_in_queue"]


def reason_cannot_change_channel(bridge):
    """Finding 9 of MOVEMENT-AUDIT: with a gesture in progress the G91 stayed on the old channel and the G90 went to the new one. "" = it can be changed."""
    if gesture_active():
        return M("jog_move_jog_moving_waiting_its_closing_g90")
    if _free.is_active:
        return M("jog_move_jog_without_limits_active")
    if (_cache_ref[0] or {}).get("status") == "paused":
        return M("jog_move_file_job_paused")
    # the channel is not changed with a live job open, neither still nor confirmed
    return state_block(bridge)[1]


def close_channel(label):
    """The jog channel changed: G90 on the one being left (the sender sends it on the next pass of the loop, never from the handler)."""
    if label and not _modal["open"]:
        _modal["open"] = label
        _modal["last_attempt"] = 0.0
        _log(f"jog channel changed: G90 on {label} (the one being left)")


def reject(bridge, reason):
    """Cuts whatever is moving and accepts nothing more until the person releases (same mechanism as the automatic exit from the no-limits mode)."""
    _state.block_until_release()
    _log(f"jog blocked: {reason}")


def _free_tick(bridge, status_cache):
    """Once per pass of the jog loop: handles requests, heartbeat, automatic exits and publishes the state."""
    with _free.lock:
        request = _free.request
        _free.request = None
    if request:
        if request[0] == "on" and not _free.is_active:
            _free_enter(bridge, status_cache)
            _free_publish(bridge, True)
        elif request[0] == "off" and _free.is_active:
            _free_exit(bridge, request[1], cause=request[2] if len(request) > 2 else None)
            _free_publish(bridge, True)
    if not _free.is_active:
        return
    now = time.monotonic()
    status = status_cache.get("status")
    if status is not None and status not in SAFE_STATUSES:
        _free_exit(bridge, "job")
    elif _in_live(bridge):
        _free_exit(bridge, "in_live")
    elif _free_bridge_reason():
        _free_exit(bridge, "bridge")
    elif now - _free.last_mov > _free.cfg["timeoutS"]:
        _free_exit(bridge, "inactive")
    if not _free.is_active:
        _free_publish(bridge, True)
        return
    if now - _free.last_heartbeat >= FREE_HEARTBEAT_S:
        _free.last_heartbeat = now
        # DIRECTLY through the connection, not through _send_queue: the loop empties that queue
        # (_drain_pending_g1) on every pass with nothing held and it took the heartbeat before it
        # went out -> the board's backup tripped after 10 s (BUG seen in the 2026-10-10 test).
        try:
            _jog_conn.send("set global.jogFreeTs = state.upTime")
        except Exception as e:
            _log(f"without limits: could not send the heartbeat ({e})")
    _free_publish(bridge)


def _free_restore_at_start(bridge, status_cache):
    """The plugin restarted with the mode active (global.jogFree true): the board does not know the jog no longer watches it. Restore the safe state."""
    status_cache["at"] = 0.0
    _get_status(status_cache)
    if not status_cache.get("global_free"):
        return
    _log("without limits: global.jogFree was left true at startup; restoring the limits")
    try:
        for code in ("M564 S1 H1", "M913 X100 Y100 Z100", "M915 X Y Z R0", "set global.jogFree = false"):
            _jog_conn.send_sync(code)
        _free.last = {"reason": "startup", "text": _FREE_TEXTS["startup"], "at": int(time.time() * 1000)}
    except Exception as e:
        _log(f"without limits: could not restore at startup ({e}); jogFreeFailsafe.g will do it")


LIMIT_MARGIN_MM = 0.05
BLOCK_CHECK_S = 0.5


def _clamp_to_limit(est, limits, letter, d):
    """2026-10-08: before, the jog sent the whole segment even if it went past the limit (M208); RRF rejected it COMPLETELY with "G1: target position outside machine limits" -- one error per tick against the edge (bursts of 6-9 errors in the activity) and the machine never reached the real limit. Now the segment is clipped to arrive just at the limit (minus a margin) and, if it is already there, that axis does not move."""
    if not d or est is None or letter not in est or letter not in limits:
        return d
    lo, hi = limits[letter]
    p = est[letter]
    # 2026-10-10: it only brakes against the limit TOWARDS where it moves. Before, min(max(...))
    # with the axis already OUTSIDE the limits (e.g. after the no-limits mode) and moving inwards
    # jumped all at once to the limit in a single segment.
    if d > 0:
        cap = hi - LIMIT_MARGIN_MM
        new = 0.0 if p >= cap else min(p + d, cap) - p
    else:
        cap = lo + LIMIT_MARGIN_MM
        new = 0.0 if p <= cap else max(p + d, cap) - p
    if abs(new) < 0.001:
        return 0.0
    return new


def run_loop(bridge, config):
    _log(f"starting (tick every {TICK_MS}ms, watchdog xy={WATCHDOG_S}s, z={Z_HOLD_MAX_S}s)")
    _mark_load()  # gesture left open before a restart: G90 on the first pass
    _ensure_sender()
    relative_active = False
    current_feed_xy = 0.0
    current_feed_z = 0.0
    current_feed_e = 0.0
    status_cache = {"status": None, "at": 0.0, "fail_count": 0}
    _cache_ref[0] = status_cache
    tick_s = TICK_MS / 1000.0
    ahead_until = 0.0  # instant (monotonic) when what is already queued ends

    def _status_refresher():
        while True:
            try:
                _load_settings()
                status_cache["at"] = 0.0
                _get_status(status_cache)
            except Exception as e:
                _log(f"state refresh failed: {e}")
            time.sleep(STATUS_POLL_S)

    threading.Thread(target=_status_refresher, daemon=True).start()
    try:
        _free_restore_at_start(bridge, status_cache)
    except Exception as e:
        _log(f"without limits: startup check failed ({e})")
    # driver-stall.g up to date (the Motors page's Calibrate crash needs it even if the no-limits
    # mode was never entered)
    _free_macro_crash()
    # Estimated position during a gesture: the real one at the start (read from the object model) +
    # the segments that were sent. None = no gesture.
    est_pos = None
    only_z = False  # the previous tick only moved Z (short cycle, see Z_TICK_S)
    last_check = 0.0  # block_reason: at the start of each gesture and every BLOCK_CHECK_S

    while True:
        # waits for the tick, or less if something was released (stop_xy/stop_z)
        _state.wake.wait(Z_TICK_S if only_z else tick_s)
        _state.wake.clear()
        heartbeats.ok("jog")
        try:
            _free_tick(bridge, status_cache)
            idle = _free.is_active
            xy, xy_at, z, z_at, speed_percent = _state.snapshot()
            ext, ext_at = _state.snapshot_ext()
            now = time.monotonic()

            if xy is not None and now - xy_at > WATCHDOG_S:
                _log(f"watchdog xy: no update from the browser for {(now - xy_at) * 1000:.0f} ms, stopping")
                _state.stop_xy()
                xy = None
            if z is not None and now - z_at > Z_HOLD_MAX_S:
                _log("watchdog z: no update from the browser, stopping")
                _state.stop_z()
                z = None
            if ext is not None and now - ext_at > Z_HOLD_MAX_S:
                _log(f"watchdog axis {ext[0]}: no update from the browser, stopping")
                _state.stop_ext()
                ext = None
            only_z = xy is None and (z is not None or ext is not None)

            if xy is None and z is None and ext is None:
                current_feed_e = 0.0
                current_feed_xy = 0.0
                current_feed_z = 0.0
                _drain_pending_g1()
                est_pos = None
                ahead_until = 0.0
                if relative_active:
                    if _request_g90():
                        relative_active = False
                elif _g90_due():
                    _request_g90()  # reintento (ver _modal)
                continue

            if est_pos is None or now - last_check >= BLOCK_CHECK_S:
                last_check = now
                level, reason = decide_block(bridge)
                _publish_block(bridge, reason, level)
                if reason:
                    reject(bridge, reason)
                    continue  # the next pass (nothing held) closes with G90

            status = status_cache.get("status")  # refreshed by _status_refresher
            if status not in JOG_STATUSES:
                # Machine busy with something else (real job, paused, tool change, etc) or unknown
                # status -- do not send movement this tick, but do NOT clear the target state: if it
                # goes back to idle/busy on the next check, it continues where the user left it
                # without having to press again.
                continue

            dx = dy = dz = 0.0
            feed_xy = feed_z = 0.0

            if xy is not None:
                nx, ny = xy
                m = min(math.hypot(nx, ny), 1.0)
                target_feed_xy = 0.0
                ux = uy = 0.0
                if m >= DEADZONE:
                    ux, uy = nx / m, ny / m
                    speed_frac = m ** EXPONENT
                    target_feed_xy = max(FEED_MIN, speed_frac * _max_feed_xy(speed_percent))
                    # 2026-10-08, fourth round: never ask for more than RRF has configured as the
                    # axis's REAL maximum (M203) -- see _rrf_axis_max_feed()/the big finding about Z
                    # below, the same reasoning applied here just in case (on this machine X/Y are
                    # already below the real ceiling so this changes nothing today, but it prevents
                    # it from happening again if FEED_MAX is ever raised or M203 is reconfigured
                    # below it).
                    rrf_caps_xy = [
                        c
                        for c in (_rrf_axis_max_feed(status_cache, "X"), _rrf_axis_max_feed(status_cache, "Y"))
                        if c is not None
                    ]
                    if rrf_caps_xy:
                        target_feed_xy = min(target_feed_xy, min(rrf_caps_xy))
                    if idle:  # no-limits: reduced ceiling speed
                        target_feed_xy = min(target_feed_xy, max(FEED_MIN, FEED_MAX * _free.cfg["speedPct"] / 100.0))
                current_feed_xy = (
                    current_feed_xy + (target_feed_xy - current_feed_xy) * RAMP_EASE
                    if target_feed_xy > current_feed_xy
                    else target_feed_xy
                )
                if current_feed_xy > 0.5:
                    feed_xy = min(current_feed_xy, _max_feed_xy(speed_percent))
                    dist = (feed_xy / 60000.0) * TICK_MS
                    dx = X_SIGN * ux * dist
                    dy = Y_SIGN * -uy * dist
            else:
                current_feed_xy = 0.0

            if z is not None:
                # 2026-10-08, fourth round: Z is now proportional to the held magnitude, exactly
                # like xy above (same DEADZONE/EXPONENT) -- it is no longer just "full speed or
                # nothing". Reason: with the old Z button (only on/off) there was no way to "ease
                # off" before releasing, as DOES happen naturally with the knob (people release near
                # the centre), so the last unavoidable segment (RRF cannot cancel a G1 already
                # accepted) came out big ALMOST ALWAYS on Z, not just in the worst case. With a
                # truly analogue control, Z inherits the same natural mitigation xy already had.
                mz = min(abs(z), 1.0)
                target_feed_z = 0.0
                zdir = 0
                if mz >= DEADZONE:
                    zdir = 1 if z > 0 else -1
                    speed_frac_z = mz**EXPONENT
                    target_feed_z = max(FEED_MIN, speed_frac_z * _max_feed_z(speed_percent))
                    # 2026-10-08, fourth round -- THE REAL FINDING behind "Z keeps going more than
                    # X/Y even with identical controls" (reported live, confirmed with the object
                    # model: this machine's real M203 is X18000 Y18000 but Z ONLY 600 mm/min).
                    # _max_feed_z() above can ask for up to Z_FEED_RATIO(0.35) * FEED_MAX(6000) =
                    # 2100 mm/min -- 3.5x the REAL ceiling of Z. RRF does not reject that: it runs
                    # the requested distance anyway, but at ITS own maximum speed (600), taking 3.5x
                    # longer than this same function assumed when it computed that distance as
                    # "feed/60000*TICK_MS". Result: the segment RRF already accepted (unavoidable,
                    # it cannot be cancelled) takes much longer to finish on Z than on X/Y, where
                    # the own ceiling (6000) is already comfortably below the real ceiling (18000)
                    # and this never happens. Fix: never ramp beyond what RRF can really deliver.
                    rrf_max_z = _rrf_axis_max_feed(status_cache, "Z")
                    if rrf_max_z is not None:
                        target_feed_z = min(target_feed_z, rrf_max_z)
                    if idle:
                        target_feed_z = min(target_feed_z, max(FEED_MIN, FEED_MAX * Z_FEED_RATIO * _free.cfg["speedPct"] / 100.0))
                current_feed_z = (
                    current_feed_z + (target_feed_z - current_feed_z) * RAMP_EASE
                    if target_feed_z > current_feed_z
                    else target_feed_z
                )
                if current_feed_z > 0.5:
                    feed_z = min(current_feed_z, _max_feed_z(speed_percent))
                    dz = zdir * ((feed_z / 60000.0) * TICK_MS)
            else:
                current_feed_z = 0.0

            if not idle:
                # 2026-10-10: an axis without homing cannot be moved outside the no-limits mode
                # (RRF: "G1: insufficient axes homed" on every segment, the console filled up). It
                # is discarded silently; the jog tells the user on screen.
                sh = status_cache.get("without_homing") or []
                if "X" in sh:
                    dx = 0.0
                if "Y" in sh:
                    dy = 0.0
                if "Z" in sh:
                    dz = 0.0

            of = 0.0
            feed_e = 0.0
            letter_e = None
            if ext is not None:
                letter_e, ve = ext
                me = min(abs(ve), 1.0)
                target_feed_e = 0.0
                if me >= DEADZONE:
                    edir = 1 if ve > 0 else -1
                    # ceiling: the axis's maximum speed in RRF (M203) times the jog's %; with no
                    # data, Z's (the most prudent)
                    cap = _rrf_axis_max_feed(status_cache, letter_e) or _max_feed_z(100)
                    target_feed_e = max(FEED_MIN, (me ** EXPONENT) * cap * speed_percent / 100.0)
                    if idle:
                        target_feed_e = min(target_feed_e, max(FEED_MIN, cap * _free.cfg["speedPct"] / 100.0))
                    current_feed_e = (
                        current_feed_e + (target_feed_e - current_feed_e) * RAMP_EASE if target_feed_e > current_feed_e else target_feed_e
                    )
                    if current_feed_e > 0.5:
                        feed_e = current_feed_e
                        of = edir * ((feed_e / 60000.0) * TICK_MS)
                else:
                    current_feed_e = 0.0
                if not idle and letter_e in (status_cache.get("without_homing") or []):
                    of = 0.0
            else:
                current_feed_e = 0.0

            if dx == 0 and dy == 0 and dz == 0 and of == 0:
                continue

            if est_pos is None:
                _free.gesture_since = time.monotonic()
                # Start of gesture: fresh real position (without waiting for the poll)
                status_cache["at"] = 0.0
                _get_status(status_cache)
                est_pos = dict(status_cache.get("pos") or {})
                now = time.monotonic()
            # Segment by time: dx/dy/dz were computed for TICK_MS; they are scaled so that what is
            # queued reaches now + LEAD_S.
            start = max(now, ahead_until)
            sec_s = min(now + (LEAD_Z_S if only_z else LEAD_S) - start, SEC_MAX_S)
            if sec_s < SEC_MIN_S:
                continue  # there is already enough ahead
            k = sec_s / tick_s
            dx, dy, dz, of = dx * k, dy * k, dz * k, of * k
            limits = status_cache.get("limits") or {}
            if idle:
                # no-limits: only a few mm beyond M208 (axes with homing; those without homing have
                # no known position)
                m = _free.cfg["marginMm"] + LIMIT_MARGIN_MM
                limits = {k: (lo - m, hi + m) for k, (lo, hi) in limits.items()}
            dx = _clamp_to_limit(est_pos, limits, "X", dx)
            dy = _clamp_to_limit(est_pos, limits, "Y", dy)
            dz = _clamp_to_limit(est_pos, limits, "Z", dz)
            if letter_e:
                of = _clamp_to_limit(est_pos, limits, letter_e, of)
            if dx == 0 and dy == 0 and dz == 0 and of == 0:
                continue  # against the limit on all the requested axes: nothing to send

            if not relative_active:
                if not _enqueue_mode("G91"):
                    continue  # the sender is stuck: this segment does not go out
                relative_active = True

            feed = max(feed_xy, feed_z, feed_e if of else 0.0, 1.0)
            parts = ["G1"]
            if dx:
                parts.append(f"X{dx:.3f}")
            if dy:
                parts.append(f"Y{dy:.3f}")
            if dz:
                parts.append(f"Z{dz:.3f}")
            if of:
                parts.append(f"{letter_e}{of:.3f}")
            parts.append(f"F{feed:.0f}")
            # 2026-10-08 (approved by the user): in Laser mode, an explicit S0 on every jog G1. M452
            # has no S1 (it is not "sticky"), but an M3 Snnn left without its M5 sets the default
            # power of the G1s that carry no S -- the jog must never be able to fire the laser. Only
            # in Laser: in FFF/CNC the S of a G1 is not power and is not sent.
            if status_cache.get("machine_mode") == "Laser":
                parts.append("S0")
            if _enqueue_g1(" ".join(parts)):
                ahead_until = start + sec_s
                if idle:
                    _free.last_mov = time.monotonic()
                for letter, d in (("X", dx), ("Y", dy), ("Z", dz), (letter_e, of)):
                    if d and letter in est_pos:
                        est_pos[letter] += d
        except BaseException as e:
            _log(f"error in tick: {type(e).__name__}: {e}")
