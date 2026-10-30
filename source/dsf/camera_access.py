"""Who may call what on the camera relay (port 8090) once the machine has users (G-A of the redesign, 2026-10-21).

The pages talk to the relay directly (stream, captures, timelapse), so the roles of the API (permissions.py) would not reach it. The relay
runs INSIDE the service, so it asks the user store in process (no HTTP, no local key): `bind(lambda: users_store)` is called by api_ops.init.

Rules (the table is ROUTES / `classify`; a route that is not in it needs admin, and test_camera_access.py fails if the relay has a route
that is not classified):
  - machine WITHOUT users (nothing bound, no store, or `configured()` is False): nothing changes, as before;
  - the Pi itself (loopback, no Origin header, no X-Workshop-Token): macros, Vision, the service. It passes. A browser always sends Origin on
    a POST, and the kiosk page on the Pi is checked like any other screen;
  - reads (state, stream, snapshot, mosaic, images, videos): a viewer only with the camera (`camera_for_viewer`, the same calculation as
    permissions.py: user flag or global setting); operator and above always;
  - capture, burst, timelapse begin / stop, rename: operator;
  - delete, keep, edit, rerender, timelapse schedule, /control (camera settings), /detect (camera search): technician;
  - users exist and the store cannot answer (damaged file, error): 503 `service_unreachable`, never let through;
  - no session and no anonymous viewer allowed: 401 `login_required`; not enough role / no camera: 403 `forbidden`.

An <img> / <video> / download cannot carry headers. For those (GET of a read route with NO X-Workshop-Token header) the day key that the
relay already has is accepted: `?t=` or the cookie `workshop_camera` (the page gets it with the API camera.token, which needs operator or a
viewer with the camera). A request that does send the session token is decided by that session only. The day key lives two days, so a
role taken away still sees images until it expires; it never opens a route that changes anything.

Pure parts (classify, decide) and the store part (authorize) are apart so the rules are tested without a service.
"""
import ipaddress

RANKS = {"viewer": 0, "operator": 1, "technician": 2, "admin": 3}
TOKEN_HEADER = "X-Workshop-Token"

VIEW = ("viewer", True)          # (lowest role, a viewer needs the camera)
OPERATOR = ("operator", False)
TECHNICIAN = ("technician", False)
ADMIN = ("admin", False)
ANY = ("viewer", False)          # any identity (loopback-only /key)

# exact path -> rule, per method (the paths are the ones camera_proto.upgrade returns)
ROUTES = {
    ("GET", "/state"): VIEW,
    ("GET", "/captures"): VIEW,
    ("GET", "/timelapses"): VIEW,
    ("GET", "/timelapse/last"): VIEW,
    ("GET", "/per_delete"): VIEW,
    ("GET", "/luts"): VIEW,
    ("GET", "/timelapse/preview"): VIEW,
    ("GET", "/key"): ANY,
    ("GET", "/detect"): TECHNICIAN,
    ("POST", "/capture"): OPERATOR,
    ("POST", "/rename"): OPERATOR,
    ("POST", "/remove"): TECHNICIAN,
    ("POST", "/keep"): TECHNICIAN,
    ("POST", "/edit"): TECHNICIAN,
    ("POST", "/rerender"): TECHNICIAN,
    ("POST", "/burst"): OPERATOR,
    ("POST", "/luts"): TECHNICIAN,
    ("POST", "/luts/remove"): TECHNICIAN,
}
# path prefix -> rule (a file name follows), GET only
PREFIXES = (("/captures/", VIEW), ("/timelapses/", VIEW))
# the camera routes the handler tests on `rest` (the path after /c/<id>), by prefix: the same startswith the handler uses
CAMERA_REST_EXACT = {"/stream": VIEW, "/": VIEW, "/snapshot": VIEW}
CAMERA_REST_PREFIX = (("/control", TECHNICIAN), ("/status", VIEW))
# POST /timelapse by ?action=
TIMELAPSE_ACTIONS = {"begin": OPERATOR, "stop": OPERATOR, "schedule": TECHNICIAN, "unschedule": TECHNICIAN}
TIMELAPSE_DEFAULT = TECHNICIAN

_store_of = [None]


def bind(store_of):
    """store_of() returns the users.UserStore (or None). Called once by api_ops.init."""
    _store_of[0] = store_of


def _camera_rest(path):
    """`rest` the handler uses for the camera routes: the path itself, or what follows /c/<id> (default /stream)."""
    if path.startswith("/c/"):
        parts = path[3:].split("/", 1)
        return "/" + parts[1] if len(parts) > 1 and parts[1] else "/stream"
    return path


def classify(method, path, query=None):
    """(lowest role, viewer needs the camera) for a call. Not in the table -> admin."""
    method = str(method).upper()
    path = str(path or "")
    if method == "GET":
        rest = _camera_rest(path)
        if rest in CAMERA_REST_EXACT:
            return CAMERA_REST_EXACT[rest]
        for prefix, rule in CAMERA_REST_PREFIX:
            if rest.startswith(prefix):
                return rule
        for prefix, rule in PREFIXES:
            if path.startswith(prefix):
                return rule
    if method == "POST" and path == "/timelapse":
        action = ((query or {}).get("action") or [""])[0]
        return TIMELAPSE_ACTIONS.get(action, TIMELAPSE_DEFAULT)
    return ROUTES.get((method, path), ADMIN)


def is_loopback(ip):
    try:
        a = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return False
    return bool(getattr(a, "ipv4_mapped", None) and a.ipv4_mapped.is_loopback) or a.is_loopback


def is_internal(client_ip, headers):
    """True for the service or a local program: loopback, no Origin, no token. A browser (even on the Pi) is not internal."""
    if not is_loopback(client_ip):
        return False
    return not (headers.get("Origin") or headers.get(TOKEN_HEADER))


def day_token(headers, query):
    """The day key a request carries: ?t= or the cookie workshop_camera ("" if none)."""
    t = ((query or {}).get("t") or [""])[0]
    if not t:
        for part in (headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "workshop_camera":
                t = v
    return t


def decide(ident, rule):
    """(allowed, http_status, code) for an identity ({role, camera} or None) and a rule (role, viewer_needs_camera)."""
    need, camera_rule = rule
    if ident is None:
        return False, 401, "login_required"
    role = ident.get("role")
    if role not in RANKS:
        return False, 401, "login_required"
    if RANKS[role] < RANKS[need]:
        return False, 403, "forbidden"
    if role == "viewer" and camera_rule and not ident.get("camera"):
        return False, 403, "forbidden"
    return True, 200, ""


def authorize(headers, client_ip, method, path, query, token_valid):
    """(allowed, http_status, code) for one request of the relay. `token_valid(t)` tells whether t is a valid day key."""
    rule = classify(method, path, query)
    if is_internal(client_ip, headers):
        return True, 200, ""
    session = headers.get(TOKEN_HEADER) or ""
    if not session and str(method).upper() == "GET" and rule == VIEW and token_valid(day_token(headers, query)):
        return True, 200, ""  # <img> / <video>: the day key the relay already has
    provider = _store_of[0]
    try:
        store = provider() if provider else None
        if store is None or not store.configured():
            return True, 200, ""  # nobody has been created yet: everybody is admin
        if store.damaged:
            return False, 503, "service_unreachable"
        ident = store.resolve(session) or store.anonymous()
    except Exception:  # noqa: BLE001  any failure means "could not ask"
        return False, 503, "service_unreachable"
    return decide(ident, rule)
