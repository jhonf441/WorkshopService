"""
Internal implementation of the API operation(s) vision.get and vision.post (api_ops.py maps their named arguments to the one-letter
parameters below).

The Vision service (OpenCV, runs inside the WorkshopVision plugin, port 8095) answers JSON to a few requests. The pages of the other
plugins (Workbench) used to call that port from the browser; now they ask the service API and this handler makes the call from the
Pi itself, so the browser needs no second port, no CORS and no camera key, and a Vision that is off gives a clear answer.

Usage: <params> M"get"|"post" P"<path>" [J"<json body>"] [T<timeout seconds, 1-90>]

/measure (Machine v2 phase 4, docs/MACHINE-PHASE4-CONTRACT.md) is the call that asks Vision for the position of a mark in bed coordinates;
Vision may not have it yet: machine_measure.py asks /state for the capability first.

Only the paths listed in GET_PATHS / POST_PATHS can be called; images (frame.jpg, mark.png) are not here: they are shown with
an <img> straight from the Vision service.
"""
import json
import urllib.error
import urllib.request

from messages import M

VISION_URL = "http://127.0.0.1:8095"
GET_PATHS = ("/state", "/orientation", "/head", "/lens")
POST_PATHS = ("/photo", "/detect", "/record/search", "/config", "/measure")
TIMEOUT_S = 90  # a detection with a new photo takes some seconds


def _body(j):
    if j in (None, "", {}):
        return {}
    if isinstance(j, dict):
        return j
    try:
        return json.loads(bytes.fromhex(str(j).strip()).decode("utf-8"))
    except Exception:
        return None


def run(params, bridge, config):
    method = str(params.get("M", "get")).strip().lower()
    path = str(params.get("P", "")).strip()
    allowed = POST_PATHS if method == "post" else GET_PATHS
    if method not in ("get", "post") or path not in allowed:
        return M("vision_call_path_not_allowed", path=path)
    body = _body(params.get("J"))
    if body is None or not isinstance(body, dict):
        return M("vision_call_body_not_json")
    data = json.dumps(body).encode("utf-8") if method == "post" else None
    try:
        timeout = min(TIMEOUT_S, max(1.0, float(params.get("T") or TIMEOUT_S)))
    except (TypeError, ValueError):
        timeout = TIMEOUT_S
    req = urllib.request.Request(VISION_URL + path, data=data, method=method.upper(),
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # Vision answers {"ok": false, "error": ...} with a 4xx/5xx: the page reads that body
        try:
            return e.read().decode("utf-8")
        except Exception:
            return M("vision_call_vision_answered_error", status=e.code)
    except (urllib.error.URLError, OSError):
        return M("vision_call_vision_is_off")
