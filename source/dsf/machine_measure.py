"""Camera verification of offsets through Vision (Machine v2 phase 4, design 2.7 and 2.12; contract in docs/MACHINE-PHASE4-CONTRACT.md).

Vision does not expose a "measure the position of a mark in bed coordinates" operation yet, and this phase does not change Vision. The
service defines what it needs (POST /measure, announced by `capabilities: ["measure"]` in GET /state) and uses it only when Vision says it
has it. The capability is called `vision.measure`; it is ABSENT unless Vision reports it, and then `offsets.verify` is refused with the
reason `no_vision_measure`.

Vision is reached through the existing call path (handlers/vision_call.py, `api_ops.run_handler`), so its allowed paths and the roles by
path (permissions.ESCALATE: /measure only looks, like /detect) stay in one place. Tests replace the call with a mocked Vision.

This module has: the capability probe (cached 30 s), the client (`measure`) that validates the answer, the pure arithmetic of the
comparison (`judge`) and the run kind offsets.verify (machine_verify.py registers it with these pieces).
"""
import json
import math
import time

CAPABILITY = "vision.measure"
PROBE_TTL_S = 30.0
PROBE_TIMEOUT_S = 2
MEASURE_TIMEOUT_S = 25
MAX_FRAME_AGE_S = 30.0
BED_MARGIN_MM = 10.0
WHATS = ("crosshair", "mark")
_cache = {"at": None, "value": None}
_hooks = {"vision": None, "now": None}     # tests: vision(method, path, body, timeout) -> dict | None; now() -> epoch s


class MeasureError(Exception):
    """The measurement could not be made. .code: vision_unavailable | vision_not_found | vision_bad_answer; .reason: Vision's own reason."""

    def __init__(self, code, reason=""):
        super().__init__("%s%s" % (code, ": " + reason if reason else ""))
        self.code = code
        self.reason = reason


def _now():
    return _hooks["now"]() if _hooks["now"] else time.time()


def call(method, path, body=None, timeout=MEASURE_TIMEOUT_S):
    """The answer of Vision as a dict, or None when Vision is off or answered something that is not JSON."""
    if _hooks["vision"]:
        return _hooks["vision"](method, path, body, timeout)
    import api_ops
    raw = api_ops.run_handler("vision_call", {"M": method, "P": path, "J": body or {}, "T": timeout})
    try:
        doc = json.loads(str(raw))
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


# ---- the capability ----

def has_measure(state):
    """True when a GET /state answer announces the measure operation (pure)."""
    caps = state.get("capabilities") if isinstance(state, dict) else None
    return isinstance(caps, list) and "measure" in caps


def capability(force=False):
    """{"measure": bool, "checked_at": epoch}. False for a Vision that is off, old (no `capabilities`) or without measure."""
    at = _now()
    if not force and _cache["at"] is not None and at - _cache["at"] < PROBE_TTL_S:
        return dict(_cache["value"])
    state = None
    try:
        state = call("get", "/state", None, PROBE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - a Vision that cannot be asked is an absent capability
        state = None
    _cache["at"], _cache["value"] = at, {"measure": has_measure(state), "checked_at": int(at)}
    return dict(_cache["value"])


def reset():
    """For the tests."""
    _cache["at"] = _cache["value"] = None
    _hooks["vision"] = _hooks["now"] = None


# ---- the client ----

def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def clean_answer(doc, bounds=None):
    """The measured point of a Vision answer {x, y, sigma_mm, confidence, frame_ts, calibration}, validated; MeasureError otherwise."""
    if not isinstance(doc, dict):
        raise MeasureError("vision_unavailable")
    if doc.get("ok") is False:
        raise MeasureError("vision_unavailable", str(doc.get("error") or "")[:80])
    if doc.get("found") is False:
        raise MeasureError("vision_not_found", str(doc.get("reason") or ""))
    x, y, sigma, ts = _num(doc.get("x")), _num(doc.get("y")), _num(doc.get("sigma_mm")), _num(doc.get("frame_ts"))
    if doc.get("found") is not True or None in (x, y, sigma, ts) or sigma <= 0:
        raise MeasureError("vision_bad_answer", "fields")
    if _now() - ts > MAX_FRAME_AGE_S:
        raise MeasureError("vision_bad_answer", "old_frame")
    if bounds and not (bounds["xmin"] - BED_MARGIN_MM <= x <= bounds["xmax"] + BED_MARGIN_MM
                       and bounds["ymin"] - BED_MARGIN_MM <= y <= bounds["ymax"] + BED_MARGIN_MM):
        raise MeasureError("vision_bad_answer", "outside_bed")
    conf = _num(doc.get("confidence"))
    return {"x": x, "y": y, "sigma_mm": sigma, "confidence": conf if conf is not None and 0 <= conf <= 1 else None,
            "frame_ts": ts, "calibration": doc.get("calibration") if isinstance(doc.get("calibration"), dict) else None}


def measure(what, near, radius_mm=15, bounds=None):
    """Asks Vision where the crosshair / mark is, near a point (bed coordinates). Returns the cleaned answer or raises MeasureError."""
    if what not in WHATS:
        raise ValueError(what)
    body = {"schema": 1, "what": what, "near": {"x": round(near["x"], 3), "y": round(near["y"], 3)}, "radius_mm": radius_mm, "fresh": True}
    try:
        doc = call("post", "/measure", body, MEASURE_TIMEOUT_S)
    except MeasureError:
        raise
    except Exception:  # noqa: BLE001
        doc = None
    return clean_answer(doc, bounds)


# ---- the comparison (pure) ----

def judge(expected, samples, tolerance):
    """measured, error and verdict from the cleaned samples [{x, y, sigma_mm, confidence}] (at least one).

    measured   mean of the samples; spread_mm = the largest distance of a sample from the mean; sigma_mm combines the mean sigma of Vision
               (mostly the calibration, which does not average down) with the standard error of the samples
    verdict    ok when dist + 2 sigma <= tolerance, out when dist - 2 sigma > tolerance, inconclusive between (the camera cannot decide)
    """
    n = len(samples)
    mx, my = sum(s["x"] for s in samples) / n, sum(s["y"] for s in samples) / n
    dist_from_mean = [math.hypot(s["x"] - mx, s["y"] - my) for s in samples]
    spread = max(dist_from_mean)
    sd = math.sqrt(sum(d * d for d in dist_from_mean) / (n - 1)) if n > 1 else 0.0
    sigma = math.hypot(sum(s["sigma_mm"] for s in samples) / n, sd / math.sqrt(n))
    dx, dy = mx - expected["x"], my - expected["y"]
    dist, uncertainty = math.hypot(dx, dy), 2 * sigma
    outcome = "ok" if dist + uncertainty <= tolerance else ("out" if dist - uncertainty > tolerance else "inconclusive")
    r = lambda v: round(v, 4)  # noqa: E731
    return {"outcome": outcome, "measured": {"x": r(mx), "y": r(my), "sigma_mm": r(sigma), "n": n, "spread_mm": r(spread)},
            "error": {"dx": r(dx), "dy": r(dy), "dist": r(dist)}, "tolerance": tolerance, "uncertainty_mm": r(uncertainty)}
