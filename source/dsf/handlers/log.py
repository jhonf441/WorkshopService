"""
Internal implementation of the API operation(s) activity.log (api_ops.py maps their named
arguments to the one-letter parameters below).

Notes an event in Activity from a page or a macro (2026-10-10,
request: "check whether there is anything new to add to the activity
plugin"). It serves for what happens on the pages and leaves no trace on the
machine: saved calibrations (camera, probe offset, cutting area,
PID, crash detection, mesh), head changes, steps of the
commissioning.

Usage: <params> T"<type>" N"<text>"   (M"<text>" also works)
     types: calibration (saved calibration), config (settings change),
            warning (notice), fire (Vision saw flame or smoke: urgent),
            safety_check (the operator confirmed the manual safety checklist before a cut: Z"<zone>" P"id,id"),
            job_start (a job started from a page: N"<job name>" Z"<zone>")
     <params> T"calibration" M"Camera calibrated (error 0.4 mm)"
The text stays in the history, shows in Activity and, if that type is
enabled in the notifications, reaches the phone.

"""
import activity
from messages import M

KINDS = {
    "calibration": "calibration",
    "config": "config",
    "warning": "notice", "notice": "notice",
    # Vision: llama o humo detectado durante un trabajo laser (fuego.py)
    "fire": "fire",
    # F3-S: the manual checklist before a cut and the start of a job from a page; the user is the caller (activity.log_event)
    "safety_check": "safety_check",
    "job_start": "job_start",
}
MAX = 300
MAX_POINTS = 20
MAX_POINT = 40


def _user():
    try:
        import identity
        u = identity.current()
        return u["name"] if u else ""
    except Exception:
        return ""


def _points(raw):
    out = []
    for p in str(raw or "").split(","):
        p = p.strip()[:MAX_POINT]
        if p and p not in out:
            out.append(p)
    return out[:MAX_POINTS]


def _structured(type_name, params, bridge):
    """safety_check and job_start: the sentence is made here from the user, the zone and the points (keys es/en)."""
    user, zone = _user(), str(params.get("Z") or "").strip()[:60]
    if type_name == "safety_check":
        points = _points(params.get("P"))
        if not points:
            return M("log_safety_points_missing")
        activity.log_event(bridge, type_name, M("log_safety_check", user=user or M("log_unknown_user"), zone=zone or "-", count=len(points)),
                           detail={"user": user, "zone": zone, "points": points})
    else:
        label = str(params.get("N") or params.get("M") or "").strip()[:MAX]
        activity.log_event(bridge, type_name, M("log_job_start", user=user or M("log_unknown_user"), label=label or M("no_name"),
                                                zone=" (%s)" % zone if zone else ""),
                           detail={"user": user, "zone": zone, "name": label})
    return M("log_noted_in_activity")


def run(params, bridge, config):
    type_name = KINDS.get(str(params.get("T", "")).strip().lower())
    if not type_name:
        return "Error: activity.log needs type calibration, config, warning, fire, safety_check or job_start"
    if type_name in ("safety_check", "job_start"):
        return _structured(type_name, params, bridge)
    # N"<text>" also works: by G-code a loose M may be taken by the Duet
    # as another command (that is why the pages send N)
    raw_text = str(params.get("N") or params.get("M") or "").strip()[:MAX]
    if not raw_text:
        return M("log_text_missing")
    activity.log_event(bridge, type_name, raw_text)
    return M("log_noted_in_activity")
