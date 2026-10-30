"""
Origin of every received API call ("Comandos recibidos" card).

Only what the service really knows when it runs the call, no extra polling:
  - how the call arrived (workshop_api.py "via"): a DWC session, open access
    (DWC without password), the local key of a system program (Vision, the
    G-code bridge), a macro of the SD (global variable mailbox, api_macros.py)
    or the service itself;
  - the "origin" field of the request (Id of the plugin or page, "macro",
    "bridge", "vision", "external:<name>");
  - for HTTP: client address, user agent, referer and DWC session id from the
    headers DWS forwards.

The history is a bounded memory ring (RING_MAX) used for the hourly counters;
the origin is also saved in the same row of the commands table (no extra
writes). This module has no DSF imports so it can be tested on a PC.
"""
import collections
import json
import re
import threading
import time

TAG_MAX = 40
RING_MAX = 1500          # about an hour of a busy machine; old entries fall out
WINDOW_S = 3600
_TAG_OK = re.compile(r"[^A-Za-z0-9_./: -]")

BLOCKED_CODES = ("motion_denied", "confirm_required", "forbidden", "auth_required")

# via (workshop_api) -> (kind, label)
_WAYS = {
    "session": ("page", "page (DWC session)"),
    "open": ("page", "page"),
    "token": ("local", "program of this computer"),
    "key": ("external", "external service (key)"),
    "macro": ("macro", "macro (SD)"),
    "internal": ("service", "this service"),
}


def clean_tag(value):
    t = _TAG_OK.sub("", str(value or "")).strip()
    return t[:TAG_MAX]


def _header(headers, name):
    try:
        for k, v in dict(headers or {}).items():
            if str(k).lower() == name:
                if isinstance(v, (list, tuple)):
                    v = v[0] if v else ""
                return str(v)
    except Exception:
        pass
    return ""


def http_info_headers(headers, session=None):
    """What the HTTP endpoint knows about the request. The DWC session key is
    never kept, only the numeric session id."""
    fwd = _header(headers, "x-forwarded-for") or _header(headers, "x-real-ip")
    return {
        "addr": fwd.split(",")[0].strip()[:64],
        "agent": _header(headers, "user-agent")[:200],
        "referer": _header(headers, "referer")[:200],
        "origin_header": _header(headers, "origin")[:100],
        "session": session if isinstance(session, int) and session >= 0 else None,
    }


def _page_from_referer(ref):
    m = re.search(r"//[^/]+/([^?#]*)(?:[?#].*)?$", str(ref or ""))
    sec = (m.group(1) if m else "").strip("/")
    return clean_tag(sec.split("/")[-1]) if sec else ""


def _browser(agent):
    a = str(agent or "")
    return "Mozilla/" in a or "Chrome/" in a


def result_of(ok, code=None, message=""):
    """('ok'|'error'|'blocked', reason)."""
    if ok:
        return "ok", ""
    msg = str(message or "")[:160]
    if code in BLOCKED_CODES:
        return "blocked", msg
    return "error", msg


def describe_api(ctx, ok, message, code=None, dur_ms=0, wait_ms=0):
    """Origin dict for a recorded API call (ctx from workshop_api.Registry.call)."""
    ctx = ctx or {}
    via = ctx.get("via") or "internal"
    kind, label = _WAYS.get(via, ("external", via))
    o = {"kind": kind, "channel": "global" if via == "macro" else "API", "label": label, "via": via}
    http = ctx.get("http")
    if isinstance(http, dict):
        for k in ("addr", "agent", "referer", "session", "origin_header"):
            if http.get(k) not in (None, ""):
                o[k] = http[k]
    origin = clean_tag(ctx.get("origin"))
    if via == "key" and isinstance(ctx.get("key"), dict):
        o["label"] = "external service: " + str(ctx["key"].get("name") or "?")
        o["key"] = str(ctx["key"].get("name") or "")
        o["key_id"] = str(ctx["key"].get("id") or "")
    if via in ("session", "open"):
        if origin.lower() == "console":
            o["kind"], o["label"] = "console", "DWC console"
        elif origin.lower().startswith("external") or (isinstance(http, dict) and http.get("agent") and not _browser(http.get("agent"))):
            o["kind"], o["label"] = "external", "external program"
    elif via == "token" and origin.lower() == "bridge":
        o["kind"], o["label"] = "bridge", "G-code bridge"
    plugin = origin or (_page_from_referer(o.get("referer")) if o["kind"] == "page" else "")
    if plugin and o["kind"] != "console":
        o["plugin"] = plugin
        o["tagged"] = bool(origin)
    res, reason = result_of(ok, code, message)
    o["result"] = res
    if reason:
        o["reason"] = reason
    if code and not ok:
        o["error"] = code
    o["ms"] = int(dur_ms or 0)
    if wait_ms:
        o["wait_ms"] = int(wait_ms)
    return o


_bridge_cache = {"at": 0.0, "clients": []}


def bridge_clients(path, now=None):
    """Clients in bridge-state.json (cached 2 s). Empty list if unknown."""
    now = time.time() if now is None else now
    if now - _bridge_cache["at"] < 2.0:
        return _bridge_cache["clients"]
    _bridge_cache["at"] = now
    out = []
    try:
        with open(path) as f:
            d = json.load(f) or {}
            out = list(d.get("clients") or [])
    except Exception:
        out = []
    _bridge_cache["clients"] = out
    return out


# ---- memory ring and hourly counters ----

_ring = collections.deque(maxlen=RING_MAX)
_ring_lock = threading.Lock()


def remember(o, now=None):
    now = time.time() if now is None else now
    with _ring_lock:
        _ring.append((now, o.get("kind", "?"), o.get("channel", "?"), o.get("plugin", ""), o.get("result", "ok")))


def counters(window_s=WINDOW_S, now=None):
    """Counts per kind / channel / plugin / result over the last window."""
    now = time.time() if now is None else now
    out = {"window_s": window_s, "total": 0, "kind": {}, "channel": {}, "plugin": {}, "result": {}}
    with _ring_lock:
        items = list(_ring)
    for t, kind, ch, plugin, res in items:
        if now - t > window_s:
            continue
        out["total"] += 1
        for key, val in (("kind", kind), ("channel", ch), ("plugin", plugin or "-"), ("result", res)):
            out[key][val] = out[key].get(val, 0) + 1
    return out


def reset_ring():
    with _ring_lock:
        _ring.clear()
