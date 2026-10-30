"""
Internal implementation of the API operation(s) bridge.test (api_ops.py maps their named
arguments to the one-letter parameters below).

Tests a command of the G-code Bridge (Telnet) from the Pi itself and returns the
response (Services > Bridge page). It opens a short connection to
127.0.0.1:<configured port>, sends ONE line and reads the response.

Only query commands: BRIDGE HELP|STATE|LIST|NAME and the G-codes of the
bridge's query list (M114, M115, M119... they move nothing). TAKE/RELEASE make no sense from a
test connection that closes right away, and nothing that moves the machine.

Usage: <params> C"BRIDGE STATUS"

"""
import paths
import json
import socket
import time

from messages import M


STATE = paths.DATA_DIR + "/bridge-state.json"
CONFIG = paths.CONFIG_DIR + "/bridge.json"
ALLOWED = ("BRIDGE HELP", "BRIDGE STATUS", "BRIDGE LIST", "BRIDGE NAME")
# G-code: only the bridge's queries (they move nothing; edited in Configure)
QUERIES_DEFAULT = ["M114", "M115", "M105", "M119", "M122", "M408", "M503", "M27", "M20", "M36"]


def _queries():
    try:
        with open(CONFIG) as f:
            d = json.load(f)
            # "queries": bridge 3.0; "consultas": bridge 2.x
            return [str(x).upper() for x in d.get("queries") or d.get("queries") or QUERIES_DEFAULT]
    except Exception:
        return QUERIES_DEFAULT


def _allowed(line):
    u = line.upper()
    if u in ALLOWED:
        return True
    return bool(u) and u.split()[0] in _queries() and len(line) <= 80


def _port():
    try:
        with open(STATE) as f:
            d = json.load(f)
            return int(d.get("port") or d.get("port") or 23)  # "puerto": bridge 2.x
    except Exception:
        return 23


def _read(s, still=0.6, total=4.0):
    payload, end, last = b"", time.time() + total, time.time()
    s.settimeout(0.2)
    while time.time() < end and time.time() - last < still:
        try:
            part = s.recv(4096)
        except socket.timeout:
            continue
        if not part:
            break
        payload += part
        last = time.time()
    return payload.decode("utf-8", "replace")


def run(params, bridge, config):
    line = " ".join(str(params.get("C", "")).split()).strip()
    if not _allowed(line):
        return json.dumps({"error": M("bridge_probe_only_query_commands", commands=", ".join(ALLOWED[:4]), queries=", ".join(_queries()))})
    port_name = _port()
    t0 = time.time()
    try:
        with socket.create_connection(("127.0.0.1", port_name), timeout=3) as s:
            _read(s, still=0.3, total=1.0)  # greeting ("Connected!")
            s.sendall((line + "\n").encode())
            resp = _read(s)
    except Exception as e:
        return json.dumps({"error": M("bridge_probe_could_not_connect_bridge_port", port=port_name, e=e)})
    return json.dumps({"port": port_name, "ms": int((time.time() - t0) * 1000),
                       "response": resp.replace("\r\n", "\n").strip()}, ensure_ascii=False)
