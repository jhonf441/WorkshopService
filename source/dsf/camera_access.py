"""Who may call what on the camera relay (port 8090) once the machine has users (G-A of the redesign, 2026-10-21).

The pages read the relay directly (stream, photos, the lists and the files of the captures and the videos: an <img> and a <video> cannot carry
the headers of the API), so the roles of the API (permissions.py) would not reach those reads. The relay runs INSIDE the service, so it asks the
user store in process (no HTTP, no local key): `bind(lambda: users_store)` is called by api_ops.init.

Everything that CHANGES something is an operation of the API (camera.capture, burst, remove, keep, rename, edit, rerender, timelapse, schedule,
flash, image.set...): its role is in permissions.py and every call is in the audit. This port only reads media, with two exceptions that do not
fit the API: the upload of a look file (POST /luts: up to 6 MB, the body of the API is 1 MB) and its removal (POST /luts/remove).

Rules (the table is ROUTES / `classify`; a route that is not in it needs admin, and test_camera_access.py fails if the relay has a route
that is not classified):
  - machine WITHOUT users (nothing bound, no store, or `configured()` is False): a request from the Pi itself (loopback) is not limited; from
    the network it can only LOOK (the reads of the table) and everything that changes something answers 403 `first_admin_required` until
    the first administrator is created. The exception is a machine whose owner switched the roles OFF on purpose (people exist,
    `network_open()`): there nothing changes, as before;
  - the Pi itself (loopback, no Origin header, no X-Workshop-Token): macros, Vision, the service. It passes. A browser always sends Origin on
    a POST, and the kiosk page on the Pi is checked like any other screen;
  - reads (state, stream, snapshot, mosaic, images, videos): a viewer only with the camera (`camera_for_viewer`, the same calculation as
    permissions.py: user flag or global setting); operator and above always;
  - /control (camera settings, passed to the ESP32-camera), POST /luts and POST /luts/remove: technician; /control with ONLY the flash value
    (led_intensity): operator;
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

# exact path -> rule, per method
ROUTES = {
    ("GET", "/state"): VIEW,
    ("GET", "/captures"): VIEW,
    ("GET", "/timelapses"): VIEW,
    ("GET", "/timelapse/last"): VIEW,
    ("GET", "/per_delete"): VIEW,
    ("GET", "/luts"): VIEW,
    ("GET", "/timelapse/preview"): VIEW,
    ("GET", "/key"): ANY,
    ("POST", "/luts"): TECHNICIAN,
    ("POST", "/luts/remove"): TECHNICIAN,
}
# path prefix -> rule (a file name follows), GET only
PREFIXES = (("/captures/", VIEW), ("/timelapses/", VIEW))
# the camera routes the handler tests on `rest` (the path after /c/<id>), by prefix: the same startswith the handler uses
CAMERA_REST_EXACT = {"/stream": VIEW, "/": VIEW, "/snapshot": VIEW}
CAMERA_REST_PREFIX = (("/control", TECHNICIAN), ("/status", VIEW))

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


FLASH_VAR = "led_intensity"   # the one setting of /control that the operator may change


def _flash_only(query):
    """True when every `var` of the /control query is the flash intensity (and there is at least one)."""
    names = (query or {}).get("var") or []
    return bool(names) and all(n == FLASH_VAR for n in names)


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
                # ONLY the flash value is the operator's, never another setting of the camera
                if prefix == "/control" and _flash_only(query):
                    return OPERATOR
                return rule
        for prefix, rule in PREFIXES:
            if path.startswith(prefix):
                return rule
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


def decide_open(client_ip, rule, network_open):
    """(allowed, http_status, code) on a machine without users. The Pi itself and a machine whose owner switched the roles off on purpose
    are not limited; anyone else on the network only reads (a rule that needs more than a viewer is a change)."""
    if network_open or is_loopback(client_ip) or rule in (VIEW, ANY):
        return True, 200, ""
    return False, 403, "first_admin_required"


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
            return decide_open(client_ip, rule, bool(store is not None and store.network_open()))
        if store.damaged:
            return False, 503, "service_unreachable"
        ident = store.resolve(session) or store.anonymous()
    except Exception:  # noqa: BLE001  any failure means "could not ask"
        return False, 503, "service_unreachable"
    return decide(ident, rule)
