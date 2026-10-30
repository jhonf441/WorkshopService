"""Version of the camera relay contract (port 8090) and the old route names.

The relay used to have no version, so a plugin page and the service could silently disagree. Now `/state` carries `proto`
and the page (WorkshopCamera 13-service.js) compares it with the one it was written for:

  proto 1   the relay before this field existed (the page sees "no proto" and treats it as 1)
  proto 2   `proto` in /state, one set of English routes; the old Spanish names still work (aliases below)

Change PROTO only when a route or an answer changes in a way an older page would not understand, and change the same number
in the page (CAMERA_RELAY_PROTO). Routes are never removed without a PROTO bump.

`upgrade(path, query)` turns the old Spanish routes and query names into the current ones, so the handler only knows one set.
It is pure (no I/O) and tested in test_camera_proto.py.
"""

PROTO = 2

# old route -> current route (exact match)
ROUTE_ALIASES = {
    "/estado": "/state",
    "/detectar": "/detect",
    "/capturar": "/capture",
    "/capturas": "/captures",
    "/borrar": "/remove",
    "/renombrar": "/rename",
    "/conservar": "/keep",
    "/editar": "/edit",
    "/clave": "/key",
    "/timelapse/ultimo": "/timelapse/last",
}
# old route prefix -> current prefix (a route that carries a file name after it)
PREFIX_ALIASES = {"/capturas/": "/captures/"}

# old query name -> current query name
QUERY_ALIASES = {
    "archivo": "file", "nombre": "name", "valor": "value", "desde": "since", "hasta": "until", "velocidad": "speed",
    "accion": "action", "fresca": "fresh", "descargar": "download",
}
# old values of ?action= -> current values
ACTION_ALIASES = {"empezar": "begin", "parar": "stop", "programar": "schedule", "desprogramar": "unschedule"}


def upgrade(path, query):
    """(path, query) with the old Spanish names replaced by the current ones. `query` is the dict parse_qs returns."""
    path = ROUTE_ALIASES.get(path, path)
    for old, new in PREFIX_ALIASES.items():
        if path.startswith(old):
            path = new + path[len(old):]
    query = query or {}
    out = {k: v for k, v in query.items() if k not in QUERY_ALIASES}  # the current name wins when a client sends both
    for k, v in query.items():
        if k in QUERY_ALIASES:
            out.setdefault(QUERY_ALIASES[k], v)
    if "action" in out:
        out["action"] = [ACTION_ALIASES.get(a, a) for a in out["action"]]
    return path, out


def describe():
    """What /state publishes about the contract."""
    return {"proto": PROTO}
