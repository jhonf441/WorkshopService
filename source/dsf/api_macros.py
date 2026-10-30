"""
Macros of the SD talking to the service (2026-10-13,
docs/api/DESIGN.md section 7). A macro cannot make an HTTP request, so it
uses RepRapFirmware global variables, which the service already receives in
its single object model subscription (state_machine, filter "global.**"):

1. Mailbox for real orders (power off, restart, arm the power off after the
   job, notifications...): the helper macro
       M98 P"0:/sys/workshop/macros/service-call.g" S"<op>" [A"key=value,..."] [W<s>]
   writes "<n>|<op>|<args>" in global.wsRequest and waits. The service runs
   the operation (only the ones marked "macro" in api_ops.py, origin "macro";
   the macro already asked the person with M291 when it matters, so the
   confirmation counts as given), writes global.wsReply = "<n>|ok|<text>" or
   "<n>|error|<text>" and empties global.wsRequest.
2. Observation, no request at all: sys/driver-stall.g (written by jog_move)
   raises global.jogFreeStallN and sets global.jogFreeStallDrv; the service
   stops the jog without limits (jog_move.libre_choque).

service-call.g is written here at start (with a marker line; if somebody
removes the marker the file is left alone).
"""
import paths
import json
import os
import queue
import re
import threading
import time

import workshop_api as wa

HELPER_REL = "sys/workshop/macros/service-call.g"
HELPER_MARK = "WORKSHOP-SERVICE-CALL v1"
SD_ROOT = paths.SD
REPLY_MAX = 200

HELPER_TEXT = f"""; service-call.g -- call an operation of the WorkshopService API from a macro.
; {HELPER_MARK} (written by WorkshopService at start; remove this line to keep your own version)
; A macro cannot use HTTP: the request goes through global variables that the
; service reads in its object model subscription.
;   M98 P"0:/sys/workshop/macros/service-call.g" S"<operation>" [A"key=value,key=value"] [W<seconds>] [Q1]
;   S = operation (only the ones allowed for macros, see GET /machine/WorkshopService/api)
;   A = arguments; numbers and true/false are converted (example: A"armed=toggle")
;   W = seconds to wait for the answer (default 5; W0 = do not wait)
;   Q1 = do not echo the answer
; Answer in global.wsReply: "<n>|ok|<text>" or "<n>|error|<text>".
if !exists(param.S)
  abort "service-call.g: missing S (operation name)"
if !exists(global.wsRequest)
  global wsRequest = ""
if !exists(global.wsReply)
  global wsReply = ""
if !exists(global.wsSeq)
  global wsSeq = 0
; another call still waiting: give it up to 5 s
while global.wsRequest != "" && iterations < 50
  G4 P100
set global.wsSeq = global.wsSeq + 1
var n = global.wsSeq
var args = ""
if exists(param.A)
  set var.args = param.A
set global.wsReply = ""
set global.wsRequest = var.n ^ "|" ^ param.S ^ "|" ^ var.args
var wait = 5
if exists(param.W)
  set var.wait = param.W
if var.wait <= 0
  M99
while global.wsRequest != "" && iterations < var.wait * 10
  G4 P100
if global.wsRequest != ""
  set global.wsRequest = ""
  echo "service-call.g: WorkshopService did not answer " ^ param.S ^ " (is it running?)"
elif !exists(param.Q) || param.Q == 0
  echo global.wsReply
"""

_state = {"registry": None, "bridge": None, "log": print, "last_stall_n": None, "q": None, "started": False}


def helper_path(sd_root=None):
    return os.path.join(sd_root or SD_ROOT, HELPER_REL)


def ensure_helper(sd_root=None, log=print):
    """Writes service-call.g if missing or ours and older. True if it is ours and current."""
    path = helper_path(sd_root)
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                current = f.read()
            if HELPER_MARK.split(" v")[0] not in current:
                return False  # somebody else's file: never touched
            if current == HELPER_TEXT:
                return True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(HELPER_TEXT)
        os.replace(tmp, path)
        log(f"api_macros: {HELPER_REL} written")
        return True
    except OSError as e:
        log(f"api_macros: could not write {HELPER_REL} ({e})")
        return False


# The two small macros the status light uses to hand the strip over to sys/daemon.g (2026-10-24: they used to be the owner's own files in
# macros/workshop, which a new machine does not have: DCS logged "Failed to start macro file" every time the service stopped).
PI_STATUS_MARK = "WORKSHOP-SERVICE-MACRO"
PI_STATUS_MACROS = {
    "enable_pi_status.g": """; enable_pi_status.g -- """ + PI_STATUS_MARK + """ (written by the service; edit it and the service leaves it alone)
; Tells sys/daemon.g that the Pi paints the status LEDs (status_light.py calls this file every ~2 s as a heartbeat).
; If the heartbeat stops for more than 10 s (service down or hung), sys/daemon.g takes the LEDs back.
if !exists(global.statusLedPiControlled)
    global statusLedPiControlled = true
else
    set global.statusLedPiControlled = true
if !exists(global.statusLedPiTs)
    global statusLedPiTs = state.upTime
else
    set global.statusLedPiTs = state.upTime
""",
    "disable_pi_status.g": """; disable_pi_status.g -- """ + PI_STATUS_MARK + """ (written by the service; edit it and the service leaves it alone)
; Gives the control of the status LEDs back to sys/daemon.g. The service calls it when DCS stops it on purpose (SIGTERM),
; so the LEDs are not left frozen.
if exists(global.statusLedPiControlled)
    set global.statusLedPiControlled = false
if exists(global.statusLedKey)
    set global.statusLedKey = ""
""",
}
PI_STATUS_DIR = "sys/workshop/macros"


def ensure_pi_status_macros(sd_root=None, log=print):
    """Writes enable_pi_status.g / disable_pi_status.g if missing or ours and older. A file without our mark is never touched."""
    for name, text in PI_STATUS_MACROS.items():
        path = os.path.join(sd_root or SD_ROOT, PI_STATUS_DIR, name)
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    current = f.read()
                if PI_STATUS_MARK not in current or current == text:
                    continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
            log(f"api_macros: {PI_STATUS_DIR}/{name} written")
        except OSError as e:
            log(f"api_macros: could not write {PI_STATUS_DIR}/{name} ({e})")


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def parse_args(text):
    """'armed=toggle,minutes=5,on=true' -> {"armed": "toggle", "minutes": 5, "on": True}.
    A JSON object is accepted too ('{"a": 1}', quotes doubled in the macro)."""
    t = str(text or "").strip()
    if not t:
        return {}
    if t.startswith("{"):
        try:
            d = json.loads(t)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    out = {}
    for part in t.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        low = v.lower()
        if low in ("true", "on", "yes"):
            out[k] = True
        elif low in ("false", "off", "no"):
            out[k] = False
        elif _NUM.match(v):
            out[k] = float(v) if "." in v else int(v)
        else:
            out[k] = v
    return out


def parse_request(raw):
    """'<n>|<op>|<args>' -> (n, op, args dict) or None."""
    parts = str(raw or "").split("|", 2)
    if len(parts) < 2 or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip(), parse_args(parts[2] if len(parts) > 2 else "")


def _quote(text):
    """Text for a RepRapFirmware string literal: quotes doubled, one line, short."""
    t = " ".join(str(text or "").split())[:REPLY_MAX]
    return t.replace('"', '""')


def handle(raw, registry=None):
    """Runs one mailbox request. Returns the reply text ("<n>|ok|..." or None)."""
    reg = registry or _state["registry"]
    req = parse_request(raw)
    if req is None:
        return None
    n, op, args = req
    status, body = reg.call(op, args, {"via": wa.VIA_MACRO, "origin": "macro", "confirm": True})
    if body.get("ok"):
        res = body.get("message")
        if res is None and body.get("result") is not None:
            res = json.dumps(body["result"], ensure_ascii=False, separators=(",", ":"))
        return f"{n}|ok|{res or 'done'}"
    return f"{n}|error|{(body.get('error') or {}).get('message') or 'error'}"


def _send_reply(reply):
    bridge = _state["bridge"]
    if bridge is None:
        return
    try:
        if reply is not None:
            bridge.send(f'set global.wsReply = "{_quote(reply)}"')
        bridge.send('set global.wsRequest = ""')
    except Exception as e:  # noqa: BLE001
        _state["log"](f"api_macros: could not answer the macro ({e})")


def _worker():
    q = _state["q"]
    while True:
        raw = q.get()
        try:
            reply = handle(raw)
        except Exception as e:  # noqa: BLE001
            reply = None
            _state["log"](f"api_macros: {e}")
        _send_reply(reply)


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def on_patch(patch, complete=False):
    """state_machine listener: must be quick (only enqueue)."""
    g = _get(patch, "global")
    if not isinstance(g, dict):
        return
    raw = g.get("wsRequest")
    if isinstance(raw, str) and raw.strip() and _state["q"] is not None:
        raw = raw.strip()
        # the same request can come again with a complete model before it is answered
        if raw != _state.get("last_raw"):
            _state["last_raw"] = raw
            try:
                _state["q"].put_nowait(raw)
            except queue.Full:
                pass
    n = g.get("jogFreeStallN")
    if isinstance(n, (int, float)):
        last = _state["last_stall_n"]
        _state["last_stall_n"] = n
        if last is not None and n > last and not complete:
            drv = str(g.get("jogFreeStallDrv") or "")
            board, _, driver = drv.partition(".")
            try:
                import jog_move
                jog_move.free_crash(board or 0, driver or "?")
            except Exception as e:  # noqa: BLE001
                _state["log"](f"api_macros: stall: {e}")


def start(registry, bridge, log=print, sd_root=None):
    """Writes the helper macro and listens to the subscription."""
    _state.update(registry=registry, bridge=bridge, log=log)
    ensure_helper(sd_root, log)
    ensure_pi_status_macros(sd_root, log)
    if _state["started"]:
        return
    _state["started"] = True
    _state["q"] = queue.Queue(maxsize=20)
    threading.Thread(target=_worker, name="api-macros", daemon=True).start()
    try:
        import machine_state
        m = machine_state.last_state() or {}
        _state["last_stall_n"] = _get(m, "global", "jogFreeStallN")
        # a request still in global.wsRequest is a live one (the helper empties it
        # itself when it gives up): it arrives with the first complete model
        machine_state.on_change(on_patch)
    except Exception as e:  # noqa: BLE001
        log(f"api_macros: no subscription ({e}); macros cannot call the service")
