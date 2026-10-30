"""
Frame traced by the service itself, NOT as a job (2026-10-15, request: "when I frame I want to decide if it goes on
continuously or once, to be able to stop it, and I do not want it sent as a job").

The pages used to write a G-code file and start it with M32: that makes a job (it shows as the last job, it fills the history and
the job trace, and Pause / Cancel are the only way to stop it). Here the service sends the moves one by one, like the jog does:

  - the frame is cut into pieces of at most PASO_MM and only a short time ahead (ADELANTO_S) is kept queued on the board, so a
    stop takes effect within about a second (RRF cannot cancel a move already accepted, so the pieces are short);
  - "once", "N times" or "continuous" (repetir = 1, N, 0); frame.stop ends it at any moment;
  - with the laser the power is limited like laserguard.g does (10 % at most, Laser mode, X and Y homed);
  - the movement owner is reserved while it runs (motion_owner), so the jog and the pages cannot move at the same time.

The points are HEAD positions in machine coordinates (G53), already shifted by the page for the pointer or the laser.
"""
import math
import threading
import time

STEP_MM = 15.0         # longest piece sent at once
LEAD_S = 0.6       # how much motion may be queued on the board ahead of now
MAX_PCT = 10.0         # same cap as sys/workshop/macros/laserguard.g
FEED_POINTER = 3000.0  # mm/min with the pointer (laser off)
FEED_LASER = 1500.0    # mm/min with the laser on
FEED_TRAVEL = 6000.0
MAX_POINTS = 400
MAX_TURNS = 10000

_lock = threading.Lock()
_state = {"active": False, "mode": "", "repeat": 1, "turn": 0, "error": "", "finished": "", "stopping": False}
_stop = threading.Event()
_thread = [None]


def status():
    with _lock:
        return dict(_state)


def _set(**kw):
    with _lock:
        _state.update(kw)


def _om():
    try:
        import machine_state
        return machine_state.get_status(timeout=2) or {}
    except Exception:
        return {}


def validate(om, points, kind, pct, repeat):
    """(puntos limpios, error) -- the same checks of laserguard.g plus the travel of the axes."""
    if kind not in ("pointer", "laser"):
        return None, "mode must be puntero or laser"
    try:
        pts = [(float(p[0]), float(p[1])) for p in points]
    except (TypeError, ValueError, IndexError):
        return None, "points must be a list of [x, y]"
    if len(pts) < 2 or len(pts) > MAX_POINTS:
        return None, "between 2 and %d points are needed" % MAX_POINTS
    try:
        rep = int(repeat)
    except (TypeError, ValueError):
        return None, "repeat must be a number (0 = continuous)"
    if rep < 0 or rep > MAX_TURNS:
        return None, "repeat out of range"
    mv = (om or {}).get("move") or {}
    axes = mv.get("axes") or []
    if len(axes) < 2:
        return None, "the machine state is not known yet"
    if not (axes[0].get("homed") and axes[1].get("homed")):
        return None, "home X and Y first"
    for p in pts:
        for i in (0, 1):
            lo, hi = axes[i].get("min"), axes[i].get("max")
            if lo is not None and hi is not None and (p[i] < float(lo) - 0.001 or p[i] > float(hi) + 0.001):
                return None, "the frame goes outside the travel of the axes"
    if kind == "laser":
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            return None, "laser power missing"
        if not (0 < pct <= MAX_PCT):
            return None, "laser power must be between 0 and %g %%" % MAX_PCT
        glob = (om or {}).get("global") or {}
        mode_machine = glob.get("selectedMode") or (om.get("state") or {}).get("machineMode")
        if mode_machine != "Laser":
            return None, "the machine is not in Laser mode"
    return pts, ""


def chop(pts, step=STEP_MM):
    """Every side of the frame cut into pieces of at most `paso` mm: [(x, y, largo)] for each destination."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(math.ceil(length / step)))
        for i in range(1, n + 1):
            f = i / float(n)
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, length / n))
    return out


def _run(bridge, pts, kind, pct, repeat):
    import communication
    import motion_owner
    from dsf.connections import CommandConnection
    token = None
    conn = None
    try:
        d = motion_owner.reserve(bridge, "frame", "sequence", "frame (%s)" % kind, 60)
        if d.get("decision") != "allow":
            _set(active=False, error=d.get("reason") or "the machine is busy", finished="refused")
            return
        token = d["token"]
        conn = CommandConnection()
        conn.connect()
        chan = communication.channel_jog()

        def send(code, wait_for=False):
            return conn.perform_simple_code(code, channel=chan, async_exec=not wait_for)

        feed = FEED_LASER if kind == "laser" else FEED_POINTER
        s = "%.1f" % (pct * 2.55) if kind == "laser" else "0"
        send("G90", True)
        send("G53 G0 X%.3f Y%.3f F%d S0" % (pts[0][0], pts[0][1], FEED_TRAVEL), True)
        send("M400", True)  # waits for the travel to the first corner (it is a single bounded move)
        pieces = chop(pts)
        queue_until = time.monotonic()
        turn = 0
        renewed = time.monotonic()
        while not _stop.is_set():
            turn += 1
            _set(turn=turn)
            for (x, y, length) in pieces:
                if _stop.is_set():
                    break
                waiting = queue_until - time.monotonic() - LEAD_S
                if waiting > 0 and _stop.wait(waiting):
                    break
                send("G53 G1 X%.3f Y%.3f F%d S%s" % (x, y, feed, s))
                queue_until = max(queue_until, time.monotonic()) + length / feed * 60.0
                if time.monotonic() - renewed > 20:
                    motion_owner.renew(bridge, token, 60)
                    renewed = time.monotonic()
            if repeat and turn >= repeat:
                break
        # the pieces already queued finish by themselves (they are short); then the laser is switched off for sure
        rest = queue_until - time.monotonic()
        if rest > 0:
            time.sleep(min(rest, 3.0))
        send("M400", True)
        if kind == "laser":
            send("M5", True)
        _set(finished="stopped" if _stop.is_set() else "done")
    except Exception as e:
        _set(error="%s: %s" % (type(e).__name__, e), finished="error")
    finally:
        try:
            if conn is not None:
                if kind == "laser":
                    try:
                        conn.perform_simple_code("M5", channel=communication.channel_jog())
                    except Exception:
                        pass
                conn.close()
        except Exception:
            pass
        if token:
            try:
                motion_owner.release(bridge, token)
            except Exception:
                pass
        _set(active=False, stopping=False)


def launch(bridge, points, kind, pct=0, repeat=1):
    """Starts the frame. Returns {"ok": True} or {"ok": False, "error": text}."""
    with _lock:
        if _state["active"]:
            return {"ok": False, "error": "a frame is already running"}
    om = _om()
    pts, err = validate(om, points, kind, pct, repeat)
    if err:
        return {"ok": False, "error": err}
    import motion_owner
    d = motion_owner.evaluate(bridge, "sequence", "frame")
    if d["decision"] != "allow":
        return {"ok": False, "error": d.get("reason") or "the machine is busy"}
    _stop.clear()
    _set(active=True, mode=kind, repeat=int(repeat), turn=0, error="", finished="", stopping=False)
    t = threading.Thread(target=_run, args=(bridge, pts, kind, float(pct or 0), int(repeat)), name="border", daemon=True)
    _thread[0] = t
    t.start()
    return {"ok": True}


def stop():
    """Stops it (never refused). The pieces already queued on the board finish: about a second."""
    _stop.set()
    _set(stopping=True)
    return {"ok": True, "active": status()["active"]}
