"""Network guards shared by the camera relay: CORS origin rule and the camera address check.

    cors_origin(origin, host_header)   -> the Origin to echo, or None
    check_camera_url(url)              -> (True, "") or (False, reason)

The relay and the Vision server are reached from DWC pages, so a page of any other site must not be able to read
their answers (CORS) and the relay must not be turned into a proxy to the internet or to link-local services
(cloud metadata 169.254.169.254, ...) through the camera address.
"""
import ipaddress
import socket
import urllib.parse


def _host_of_header(host_header):
    """Host name of a Host header value (no port, no brackets), lower case; "" if there is none."""
    h = str(host_header or "").strip().lower()
    if not h:
        return ""
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else ""
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def cors_origin(origin, host_header):
    """The Origin only if its host is the host the request was made to (any port, http/https): the own DWC.
    Returns the origin to put in Access-Control-Allow-Origin, or None (no header: the browser blocks the read)."""
    if not origin:
        return None
    try:
        u = urllib.parse.urlsplit(str(origin))
        host = (u.hostname or "").lower()
        scheme = u.scheme
        u.port  # raises ValueError on a bad port
    except ValueError:
        return None
    if scheme not in ("http", "https") or not host:
        return None
    if host != _host_of_header(host_header):
        return None
    return str(origin)


def _addr_ok(text):
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return False
    return ip.is_private


def _resolve(host):
    return [i[4][0] for i in socket.getaddrinfo(host, None)]


def check_camera_url(url, resolver=None):
    """Only http/https to a private-network or loopback host (every address the name resolves to)."""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
        host = u.hostname
        u.port
    except ValueError:
        return False, "invalid"
    if u.scheme.lower() not in ("http", "https"):
        return False, "scheme"
    if not host:
        return False, "invalid"
    try:
        addrs = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addrs = (resolver or _resolve)(host)
        except (OSError, UnicodeError):
            return False, "unresolved"
    if not addrs:
        return False, "unresolved"
    if not all(_addr_ok(a) for a in addrs):
        return False, "not_private"
    return True, ""
