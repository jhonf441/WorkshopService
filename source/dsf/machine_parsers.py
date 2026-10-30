"""Parsers of the board's replies for the Machine procedures (Machine v2, phase 1).

The wording of G30 / G29 / G32 / M671 replies changes with the firmware and only SOME of it is verified (GCODE-REFERENCE sections 1-2:
the strings quoted from RepRapFirmware 3.6.1 sources are tagged "src"; the `bed probe heights:` line was only seen in forum posts, tagged
"forum"). So every parser here is tolerant:

  - it takes anything (None, bytes, a number) and NEVER raises;
  - it returns the raw text (cut to RAW_MAX) plus the fields it could read, and `matched` says whether it read anything;
  - a field that is not in the reply is simply missing (never a guess); the caller decides what to do without it.

Numbers accept the exponent form that RRF 3.6 may use in JSON (1.5e-3).
"""
import json
import re

RAW_MAX = 600
_N = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_LIST = r"(?:\s+%s)+" % _N


def _text(reply):
    if reply is None:
        return ""
    if isinstance(reply, bytes):
        return reply.decode("utf-8", "replace")
    return str(reply)


def _f(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _floats(s):
    return [x for x in (_f(t) for t in str(s or "").split()) if x is not None]


def _base(text):
    return {"raw": text[:RAW_MAX], "matched": False}


# ---- errors the firmware reports as text (src = verified in the 3.6.1 source, GCODE-REFERENCE 1-2) ----

ERROR_PATTERNS = (
    ("already_triggered", re.compile(r"Probe already triggered", re.I)),                                 # src
    ("probe_enable_failed", re.compile(r"Failed to enable probe", re.I)),                                 # src
    ("not_triggered", re.compile(r"Probe was not triggered", re.I)),                                      # src
    ("too_few_points", re.compile(r"Too few points probed", re.I)),                                       # src
    ("bad_scan_reading", re.compile(r"Bad reading from scanning probe", re.I)),                           # src
    ("tool_deselected", re.compile(r"Tool was deselected during G30", re.I)),                             # src
    ("factors_mismatch", re.compile(r"Number of calibration factors", re.I)),                             # src
    ("cannot_calculate", re.compile(r"Unable to calculate screw corrections", re.I)),                     # src
    ("calibration_failed", re.compile(r"Calibration failed", re.I)),                                      # src
    ("corrections_exceed", re.compile(r"Some computed corrections exceed configured limit", re.I)),       # src
    ("m671_count", re.compile(r"Specify 1, 2, 3 or 4 X and Y coordinates in M671", re.I)),                # src
    ("not_homed", re.compile(r"(?:Insufficient axes homed|must home .* first|axes? .* not homed)", re.I)),
    ("generic", re.compile(r"(?:^|\n)\s*Error\b[:\s]", re.I)),
)


def find_errors(reply):
    """[{"code", "text"}]: every known error in the text (the line that contains it), in order. [] when there is none."""
    text = _text(reply)
    out = []
    for line in text.splitlines():
        for code, rx in ERROR_PATTERNS:
            if rx.search(line) or (code == "generic" and re.match(r"\s*Error\b[:\s]", line, re.I)):
                out.append({"code": code, "text": line.strip()[:200]})
                break
    return out


# ---- G30 ----

_STOPPED = re.compile(r"Stopped at height\s+(%s)\s*mm" % _N, re.I)             # src: `Stopped at height %.3f mm`
_TRIGGER_SET = re.compile(r"Z probe trigger height set to\s+(%s)\s*mm" % _N, re.I)  # src (G30 S-3)


def parse_g30(reply):
    """G30 without P (S-1): {"raw", "matched", "height", "errors"}. `height` is the stop height in mm."""
    text = _text(reply)
    out = dict(_base(text), height=None, errors=find_errors(text))
    m = _STOPPED.search(text)
    if m:
        out["height"], out["matched"] = _f(m.group(1)), True
    m = _TRIGGER_SET.search(text)
    if m:
        out["trigger_height_set"], out["matched"] = _f(m.group(1)), True
    if out["height"] is None and "trigger_height_set" not in out:
        out["matched"] = False
    return out


# `G32 bed probe heights: -0.193 -0.174, mean -0.183, deviation from mean 0.010` (forum only; "not set" / "probing failed" per point)
_HEIGHTS = re.compile(r"bed probe heights:(.*?),\s*mean\s+(%s),\s*deviation from mean\s+(%s)" % (_N, _N), re.I | re.S)


def parse_bed_heights(reply):
    """{"raw", "matched", "heights": [float or None], "mean", "deviation"}"""
    text = _text(reply)
    out = dict(_base(text), heights=[], mean=None, deviation=None)
    m = _HEIGHTS.search(text)
    if not m:
        return out
    items = re.sub(r"not set|probing failed", "x", m.group(1), flags=re.I).split()
    out["heights"] = [_f(t) for t in items]
    out["mean"], out["deviation"], out["matched"] = _f(m.group(2)), _f(m.group(3)), True
    return out


# ---- G32 / the end of G30 Pn ... Sk (ZLeadscrewKinematics, src) ----

_SETTING = re.compile(r"Leadscrew adjustments made:(%s),\s*points used\s+(\d+),\s*\(mean, deviation\) before \((%s),\s*(%s)\) after \((%s),\s*(%s)\)"
                      % (_LIST, _N, _N, _N, _N))
_MANUAL = re.compile(r"Manual corrections required:((?:\s+%s turn (?:up|down) \(%smm\))+)" % (_N, _N))
_TURN = re.compile(r"(%s) turn (up|down) \((%s)mm\)" % (_N, _N))
_EXCEEDS = re.compile(r"Some computed corrections exceed configured limit of\s+(%s)mm:(%s)" % (_N, _LIST))
_FAILURE = re.compile(r"Calibration failed, computed corrections:([^\n]*)")
_FACTORS = re.compile(r"Number of calibration factors \((\d+)\) not equal to number of leadscrews \((\d+)\)")
_POINTS = re.compile(r"Unable to calculate screw corrections")


def parse_g32(reply):
    """Everything the board says when a levelling pass ends (more than one thing may come in the same text), in order:
    {"raw", "matched", "results": [{"kind", ...}], "last", "errors"}. Kinds: setting (motors moved: before/after mean and deviation),
    manual (turns of the screws), exceeds, failure, factors, points, heights (measure only), error."""
    text = _text(reply)
    out = dict(_base(text), results=[], last=None, errors=find_errors(text))
    found = []
    for m in _SETTING.finditer(text):
        found.append((m.start(), {"kind": "setting", "adjustments": _floats(m.group(1)), "points": int(m.group(2)),
                                  "before": {"mean": _f(m.group(3)), "deviation": _f(m.group(4))},
                                  "after": {"mean": _f(m.group(5)), "deviation": _f(m.group(6))}}))
    for m in _MANUAL.finditer(text):
        screws = [{"turns": _f(t[0]), "direction": t[1], "mm": _f(t[2])} for t in _TURN.findall(m.group(1))]
        found.append((m.start(), {"kind": "manual", "screws": screws}))
    for m in _EXCEEDS.finditer(text):
        found.append((m.start(), {"kind": "exceeds", "limit": _f(m.group(1)), "adjustments": _floats(m.group(2))}))
    for m in _FAILURE.finditer(text):
        found.append((m.start(), {"kind": "failure", "adjustments": _floats(m.group(1))}))
    for m in _FACTORS.finditer(text):
        found.append((m.start(), {"kind": "factors", "factors": int(m.group(1)), "leadscrews": int(m.group(2))}))
    for m in _POINTS.finditer(text):
        found.append((m.start(), {"kind": "points"}))
    hm = parse_bed_heights(text)
    if hm["matched"]:
        found.append((text.lower().find("bed probe heights"), {"kind": "heights", "heights": hm["heights"], "mean": hm["mean"],
                                                               "deviation": hm["deviation"]}))
    for e in out["errors"]:
        if e["code"] == "generic":
            found.append((text.find(e["text"]), {"kind": "error", "text": e["text"]}))
    found.sort(key=lambda t: t[0])
    out["results"] = [r for _, r in found]
    out["last"] = out["results"][-1] if out["results"] else None
    out["matched"] = bool(out["results"])
    return out


# ---- M671 ----

_M671 = re.compile(r"Z leadscrew coordinates\s+((?:\(\s*%s\s*,\s*%s\s*\)\s*)+),?\s*factor\s+(%s),\s*maximum correction\s+(%s)\s*mm,\s*manual adjusting screw pitch\s+(%s)\s*mm"
                   % (_N, _N, _N, _N, _N), re.I)
_XY = re.compile(r"\(\s*(%s)\s*,\s*(%s)\s*\)" % (_N, _N))


def parse_m671(reply):
    """Reply of `M671` without parameters (src): {"raw", "matched", "configured", "x": [], "y": [], "factor", "max_correction", "pitch"}"""
    text = _text(reply)
    out = dict(_base(text), configured=None, x=[], y=[], factor=None, max_correction=None, pitch=None)
    if re.search(r"Z leadscrew coordinates are not configured", text, re.I):
        out.update(configured=False, matched=True)
        return out
    m = _M671.search(text)
    if not m:
        return out
    pairs = _XY.findall(m.group(1))
    out.update(configured=True, matched=True, x=[_f(a) for a, _ in pairs], y=[_f(b) for _, b in pairs], factor=_f(m.group(2)),
               max_correction=_f(m.group(3)), pitch=_f(m.group(4)))
    return out


# ---- G29 (gridProbing7, src) ----

_GRID = re.compile(r"(\d+)\s+points probed,\s*min error\s+(%s),\s*max error\s+(%s),\s*mean\s+(%s),\s*deviation\s+(%s)" % (_N, _N, _N, _N), re.I)
_SKIPPED = re.compile(r"Skipping grid point\s+(\w)=(%s),\s*(\w)=(%s)\s+because the Z probe cannot reach it" % (_N, _N), re.I)
_OFFSET = re.compile(r"height map has a substantial Z offset", re.I)


def parse_g29(reply):
    """{"raw", "matched", "points", "min_error", "max_error", "mean", "deviation", "skipped": [{"a","b"}], "offset_warning", "errors"}"""
    text = _text(reply)
    out = dict(_base(text), points=None, min_error=None, max_error=None, mean=None, deviation=None, skipped=[], offset_warning=False,
               errors=find_errors(text))
    m = _GRID.search(text)
    if m:
        out.update(matched=True, points=int(m.group(1)), min_error=_f(m.group(2)), max_error=_f(m.group(3)), mean=_f(m.group(4)),
                   deviation=_f(m.group(5)))
    out["skipped"] = [{"a": _f(a), "b": _f(b)} for _, a, _, b in _SKIPPED.findall(text)]
    out["offset_warning"] = bool(_OFFSET.search(text))
    return out


# ---- M409 (object model) ----

def parse_json_result(reply):
    """The `result` of an M409 reply, or None (malformed, or the key is unknown)."""
    try:
        doc = json.loads(_text(reply))
    except ValueError:
        return None
    return doc.get("result") if isinstance(doc, dict) else None


def parse_number_result(reply):
    """M409 on a number (or an array of numbers: the first one) -> float or None."""
    res = parse_json_result(reply)
    first = res[0] if isinstance(res, list) and res else res
    return float(first) if isinstance(first, (int, float)) and not isinstance(first, bool) and first == first else None


def parse_calibration(reply):
    """M409 K"move.calibration": {"matched", "initial": {mean, deviation}, "final": {...}, "factors"}"""
    res = parse_json_result(reply)
    out = {"raw": _text(reply)[:RAW_MAX], "matched": False, "initial": None, "final": None, "factors": None}
    if not isinstance(res, dict):
        return out

    def part(d):
        if not isinstance(d, dict):
            return None
        mean, dev = _f(d.get("mean")), _f(d.get("deviation"))
        return {"mean": mean, "deviation": dev} if mean is not None or dev is not None else None

    out["initial"], out["final"] = part(res.get("initial")), part(res.get("final"))
    f = res.get("numFactors")
    out["factors"] = f if isinstance(f, int) and not isinstance(f, bool) else None
    out["matched"] = out["initial"] is not None or out["final"] is not None
    return out


def parse_compensation(reply):
    """M409 K"move.compensation": {"matched", "type", "file", "fade_height", "mean", "deviation"}"""
    res = parse_json_result(reply)
    out = {"raw": _text(reply)[:RAW_MAX], "matched": False, "type": None, "file": None, "fade_height": None, "mean": None, "deviation": None}
    if not isinstance(res, dict):
        return out
    dev = res.get("meshDeviation") if isinstance(res.get("meshDeviation"), dict) else {}
    out.update(matched=True, type=res.get("type"), file=res.get("file"), fade_height=_f(res.get("fadeHeight")), mean=_f(dev.get("mean")),
               deviation=_f(dev.get("deviation")))
    return out
