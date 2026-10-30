"""
Central API of the workshop plugins (2026-10-13). Every page, macro and
program calls named operations with
JSON arguments over the HTTP endpoint of the plugin.

Transport (what DSF already provides, nothing of our own):
  POST /machine/<plugin>/api   {"op": "<group>.<action>", "args": {...},
                                "confirm": false, "origin": "<who>"}
  GET  /machine/<plugin>/api   description of every operation (schema)
DWS serves both on its own port with the DWC session (permission
"registerHttpEndpoints" in plugin.json). Nothing goes through a G-code
channel of the board, so a slow macro never delays a call and a stopped
plugin answers 502/503 instead of leaving a channel stuck.

Answer: {"ok": true, "op", "result", "message"} or
        {"ok": false, "op", "error": {"code", "message", ...}} with an HTTP
status (see ApiError). Documentation: docs/api/DESIGN.md (Spanish) and
docs/api/README.md (English, for external programs).

This file is the same in WorkshopService and WorkshopRS485: keep them equal.
It has no DSF import at module level so it can be tested on a PC.
"""
import asyncio
import fnmatch
import json
import os
import secrets
import threading
import time

import messages

API_VERSION = 1
MAX_BODY = 1024 * 1024  # bytes of a request (dsf-python alone stops reading at 32 KB)
LOCK_WAIT_S = 20  # an exclusive operation waits this long for another one, then 503 "busy"
TOKEN_HEADER = "x-workshop-token"
KEY_HEADER = "x-workshop-key"  # key of an external service (api_keys.py): its own permissions

# operation classes (who may call what, see Registry._allowed)
READ, WRITE, MOTION, STOP, POWER, ADMIN = "read", "write", "motion", "stop", "power", "admin"
KINDS = (READ, WRITE, MOTION, STOP, POWER, ADMIN)
# ways a request can arrive
VIA_SESSION = "session"    # DWC session (page or external program that logged in)
VIA_OPEN = "open"          # no session and DWC has no password: like /machine/code
VIA_TOKEN = "token"        # local system program with the local key (Vision, G-code bridge)
VIA_KEY = "key"            # external service with its own key and permissions (never admin operations)
VIA_MACRO = "macro"        # macro of the SD through the global variable mailbox
VIA_INTERNAL = "internal"  # code inside the service itself (tests, other modules)


class ApiError(Exception):
    """An answer with ok=false. status = HTTP status code."""

    STATUS = {
        "bad_request": 400, "auth_required": 401, "forbidden": 403, "unknown_op": 404,
        # Each answer that a client treats differently has its own status; error.code stays the contract (clients branch on it first).
        "confirm_required": 428,   # Precondition Required: repeat with confirm true
        "motion_denied": 423,      # Locked: the owner of the movement (or a laser interlock) refuses now
        "interlock_open": 423,
        "conflict": 409,           # the state changed under the caller (old settings revision, self demotion...)
        "failed": 424,             # Failed Dependency: the operation ran and the machine or a program answered with an error
        "invalid_args": 422,
        "internal": 500, "busy": 503,
    }

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message if isinstance(message, str) else str(message)  # a messages.Msg stays one (it is localized at the end)
        self.extra = extra
        self.status = self.STATUS.get(code, 400)

    def body(self, op=None):
        err = {"code": self.code, "message": self.message}
        err.update(self.extra)
        return {"ok": False, "op": op, "error": err}


class Arg:
    """One named argument. type: str, int, num, bool, obj (dict or list),
    list (list of strings; a comma separated string is accepted too), any."""

    TYPES = ("str", "int", "num", "bool", "obj", "list", "any")

    def __init__(self, type="str", required=False, default=None, choices=None, desc="", min=None, max=None):
        if type not in self.TYPES:
            raise ValueError("unknown argument type " + type)
        self.type = type
        self.required = required
        self.default = default
        self.choices = tuple(choices) if choices else None
        self.desc = desc
        self.min = min
        self.max = max

    def clean(self, name, v):
        t = self.type
        try:
            if t == "str":
                if isinstance(v, (dict, list)):
                    raise ValueError
                v = "" if v is None else str(v)
            elif t == "int":
                if isinstance(v, bool):
                    v = int(v)
                f = float(v)
                if f != int(f):
                    raise ValueError
                v = int(f)
            elif t == "num":
                if isinstance(v, bool):
                    raise ValueError
                v = float(v)
            elif t == "bool":
                if isinstance(v, str):
                    s = v.strip().lower()
                    if s in ("1", "true", "yes", "on", "si"):
                        v = True
                    elif s in ("0", "false", "no", "off", ""):
                        v = False
                    else:
                        raise ValueError
                elif isinstance(v, (int, float)):
                    v = bool(v)
                elif not isinstance(v, bool):
                    raise ValueError
            elif t == "obj":
                if not isinstance(v, (dict, list)):
                    raise ValueError
            elif t == "list":
                if isinstance(v, str):
                    v = [x.strip() for x in v.split(",") if x.strip()]
                elif not isinstance(v, list):
                    raise ValueError
                v = [str(x) for x in v]
        except (TypeError, ValueError):
            raise ApiError("invalid_args", f"argument '{name}' must be of type {t}", field=name)
        if self.choices is not None and v not in self.choices:
            raise ApiError("invalid_args", f"argument '{name}' must be one of: {', '.join(map(str, self.choices))}", field=name)
        if t in ("int", "num"):
            if self.min is not None and v < self.min:
                raise ApiError("invalid_args", f"argument '{name}' must be >= {self.min}", field=name)
            if self.max is not None and v > self.max:
                raise ApiError("invalid_args", f"argument '{name}' must be <= {self.max}", field=name)
        return v

    def describe(self):
        d = {"type": self.type}
        if self.required:
            d["required"] = True
        if self.default is not None:
            d["default"] = self.default
        if self.choices:
            d["choices"] = list(self.choices)
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.desc:
            d["desc"] = self.desc
        return d


class Op:
    """One operation.
    fn(args, ctx) -> result: a dict/list (JSON result), a str (message) or
    None. Raise ApiError to answer an error.
    kind: READ/WRITE/MOTION/STOP/POWER/ADMIN.
    confirm: None or {"level": 2|3|4, "key": "<text key>"}: without
        "confirm": true the call answers 428 confirm_required.
    motion: None or the class of the motion owner (move, job, sequence,
        geometry, power, channel) asked before running.
    exclusive: one at a time with the other exclusive operations (default:
        write, power and admin).
    macro: may be called by a macro of the SD (mailbox).
    log: kept in the history of received commands.
    extra: arguments not in `args` are accepted (passed through)."""

    def __init__(self, name, fn, kind=READ, args=None, desc="", confirm=None, motion=None, exclusive=None,
                 macro=False, log=True, extra=False, slow=False):
        if kind not in KINDS:
            raise ValueError("unknown kind " + kind)
        self.name = name
        self.fn = fn
        self.kind = kind
        self.args = dict(args or {})
        self.desc = desc
        self.confirm = confirm
        self.motion = motion
        self.exclusive = kind in (WRITE, POWER, ADMIN) if exclusive is None else exclusive
        self.macro = macro
        self.log = log
        self.extra = extra
        self.slow = slow

    def describe(self):
        d = {"op": self.name, "kind": self.kind, "desc": self.desc,
             "args": {k: a.describe() for k, a in self.args.items()}}
        if self.confirm:
            d["confirm"] = dict(self.confirm)
        if self.motion:
            d["motion"] = self.motion
        if self.macro:
            d["macro"] = True
        if self.extra:
            d["extra_args"] = True
        if self.slow:
            d["slow"] = True
        return d


class Registry:
    """Operations of one plugin and the rules to call them."""

    def __init__(self, plugin_id, version="", log=print):
        self.plugin_id = plugin_id
        self.version = version
        self.log = log
        self.ops = {}
        self.lock = threading.Lock()
        # hooks set by the plugin
        self.motion_check = None   # fn(op, args, ctx) -> None or raises ApiError
        self.on_call = None        # fn(op_name, args, ctx, ok, result, message, error_code, dur_ms, wait_ms)
        self.confirm_texts = {}    # key -> {"es": {"title", "text"}, "en": {...}}
        self.has_password = None   # fn() -> bool (DWC password set)
        self.token = None          # local key for system programs (see load_token)
        self.key_lookup = None     # fn(plain key) -> record {id, name, kinds, ops, deny} or None (invalid / revoked / expired)
        self.add(Op("api.describe", lambda a, c: self.describe(), READ, desc="All operations with their arguments", log=False))
        self.add(Op("api.ping", lambda a, c: {"pong": True, "time": int(time.time())}, READ, desc="Check that the API answers", log=False))

    def add(self, op):
        if op.name in self.ops:
            raise ValueError("duplicated operation " + op.name)
        self.ops[op.name] = op
        return op

    def describe(self):
        return {"plugin": self.plugin_id, "version": self.version, "api": API_VERSION,
                "ops": [self.ops[k].describe() for k in sorted(self.ops)]}

    # -- validation --
    def clean_args(self, op, args):
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ApiError("invalid_args", "args must be an object")
        out = {}
        for name, a in op.args.items():
            if name in args and args[name] is not None:
                out[name] = a.clean(name, args[name])
            elif a.required:
                raise ApiError("invalid_args", f"missing argument '{name}'", field=name)
            elif a.default is not None:
                out[name] = a.default
        unknown = [k for k in args if k not in op.args]
        if unknown:
            if not op.extra:
                raise ApiError("invalid_args", "unknown argument(s): " + ", ".join(sorted(unknown)), field=unknown[0])
            for k in unknown:
                out[k] = args[k]
        return out

    def _key_allows(self, op, rec):
        """Permissions of a key: its kinds and its operation patterns, minus its deny patterns.
        Administration operations are never allowed to a key."""
        name = op.name
        if op.kind == ADMIN:
            raise ApiError("forbidden", f"'{name}' needs a DWC session: a key cannot call administration operations")
        if any(fnmatch.fnmatchcase(name, p) for p in rec.get("deny") or ()):
            raise ApiError("forbidden", f"the key '{rec.get('name', '?')}' does not allow '{name}'")
        if op.kind in (rec.get("kinds") or ()) or any(fnmatch.fnmatchcase(name, p) for p in rec.get("ops") or ()):
            return
        raise ApiError("forbidden", f"the key '{rec.get('name', '?')}' does not allow '{name}' (kind {op.kind})")

    def _allowed(self, op, via, ctx=None):
        if via == VIA_KEY:
            self._key_allows(op, (ctx or {}).get("key") or {})
        elif via == VIA_MACRO:
            if not op.macro:
                raise ApiError("forbidden", f"'{op.name}' cannot be called from a macro")
        elif via == VIA_TOKEN:
            if op.kind == ADMIN:
                raise ApiError("forbidden", f"'{op.name}' needs a DWC session")

    def confirm_info(self, op, reason=None, level=None):
        c = dict(op.confirm or {})
        if level:
            c["level"] = level
        c.setdefault("level", 3)
        c.setdefault("key", op.name)
        texts = self.confirm_texts.get(c["key"]) or {}
        if texts:
            c["texts"] = texts
        if reason:
            c["reason"] = reason  # localized with the rest of the answer (language of the request)
        return c

    # -- call --
    def call(self, op_name, args=None, ctx=None):
        """Run one operation. Returns (http status, body dict). Never raises."""
        ctx = dict(ctx or {})
        ctx.setdefault("via", VIA_INTERNAL)
        lang = "en" if str(ctx.get("lang") or "").lower().startswith("en") else "es"
        lang_token = messages.set_language(lang)  # the messages made while this call runs are in the language of whoever asked
        t_en = time.time()
        t0 = t_en
        op = self.ops.get(str(op_name or ""))
        clean = args if isinstance(args, dict) else {}
        result = message = None
        code = None
        held = False
        try:
            if op is None:
                raise ApiError("unknown_op", f"unknown operation '{op_name}' (GET /machine/{self.plugin_id}/api lists them)")
            self._allowed(op, ctx["via"], ctx)
            clean = self.clean_args(op, args)
            confirmed = bool(ctx.get("confirm"))
            if op.confirm and not confirmed and op.confirm.get("level", 3) >= 3:
                raise ApiError("confirm_required", "this operation needs a confirmation", confirm=self.confirm_info(op))
            if op.motion and self.motion_check is not None:
                self.motion_check(op, clean, ctx)
            if op.exclusive:
                if not self.lock.acquire(timeout=LOCK_WAIT_S):
                    raise ApiError("busy", "another operation is still running; try again")
                held = True
            t0 = time.time()
            out = op.fn(clean, ctx)
            result, message = split_result(out)
            if isinstance(message, str) and message.lstrip().lower().startswith("error"):
                raise ApiError("failed", message.strip())
            body = {"ok": True, "op": op.name, "result": result, "message": message}
            status = 200
        except ApiError as e:
            code = e.code
            body, status = e.body(op.name if op else op_name), e.status
            message = e.message
        except Exception as e:  # noqa: BLE001 - an operation must never break the endpoint
            code = "internal"
            message = f"Error in '{op_name}': {e}"
            self.log(message)
            body, status = ApiError("internal", message).body(op_name), 500
        finally:
            if held:
                self.lock.release()
            messages.reset_language(lang_token)
        body = messages.localize(body, lang)  # also the messages made at import time (tables)
        if op is not None and op.log and self.on_call is not None:
            try:
                self.on_call(op.name, clean, ctx, body.get("ok"), result, message, code,
                             int((time.time() - t0) * 1000), int((t0 - t_en) * 1000))
            except Exception as e:  # noqa: BLE001
                self.log(f"api history: {e}")
        return status, body

    # -- who is calling --
    def via_of(self, session_id, headers):
        """VIA_SESSION / VIA_TOKEN / VIA_KEY / VIA_OPEN, or raises ApiError auth_required."""
        return self.auth_of(session_id, headers)[0]

    def auth_of(self, session_id, headers):
        """(via, key record or None). A key that is sent but is not valid is refused: it never
        falls back to the open mode."""
        if isinstance(session_id, int) and session_id >= 0:
            return VIA_SESSION, None
        tok = header(headers, TOKEN_HEADER)
        if tok and self.token and secrets.compare_digest(tok, self.token):
            return VIA_TOKEN, None
        k = header(headers, KEY_HEADER)
        if k:
            rec = None
            try:
                rec = self.key_lookup(k.strip()) if self.key_lookup else None
            except Exception as e:  # noqa: BLE001
                self.log(f"api: key lookup failed ({e})")
            if rec is None:
                raise ApiError("auth_required", "the key is not valid, has expired or was revoked")
            return VIA_KEY, rec
        has = True
        try:
            has = bool(self.has_password()) if self.has_password else False
        except Exception:
            has = True  # unknown: ask for a session
        if has:
            raise ApiError("auth_required", "DWC has a password: log in (GET /machine/connect?password=...) and send X-Session-Key, or send X-Workshop-Key")
        return VIA_OPEN, None

    def load_token(self, path):
        """The local key of the system programs: read it or create it (mode 640).
        Returns the token or None (the endpoint then only knows sessions)."""
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    t = f.read().strip()
                if len(t) >= 32:
                    self.token = t
                    return t
            os.makedirs(os.path.dirname(path), exist_ok=True)
            t = secrets.token_hex(24)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(t + "\n")
            try:
                os.chmod(tmp, 0o640)
            except OSError:
                pass
            os.replace(tmp, path)
            self.token = t
            return t
        except OSError as e:
            self.log(f"api: local key not available ({e})")
            return None


def split_result(out):
    """Handler output -> (result, message). A JSON text becomes the result."""
    if out is None:
        return None, None
    if isinstance(out, (dict, list)):
        return out, None
    if isinstance(out, (bytes, bytearray)):
        out = out.decode("utf-8", "replace")
    s = str(out)
    t = s.strip()
    if t[:1] in ("{", "[") and t[-1:] in ("}", "]"):
        try:
            return json.loads(t), None
        except ValueError:
            pass
    return None, s


def header(headers, name):
    try:
        for k, v in dict(headers or {}).items():
            if str(k).lower() == name:
                return str(v[0] if isinstance(v, (list, tuple)) and v else v).strip()
    except Exception:
        pass
    return ""


def parse_request_body(body):
    """POST body -> (op, args, confirm, origin). Raises ApiError bad_request."""
    try:
        d = json.loads(body or "")
    except ValueError:
        raise ApiError("bad_request", "the body must be JSON: {\"op\": \"...\", \"args\": {...}}")
    if not isinstance(d, dict) or not isinstance(d.get("op"), str) or not d["op"].strip():
        raise ApiError("bad_request", "missing \"op\"")
    origin = "".join(ch for ch in str(d.get("origin") or "") if ch.isalnum() or ch in "-_.:/ ")[:60].strip()
    return d["op"].strip(), d.get("args"), bool(d.get("confirm")), origin


def request_lang(body):
    """"en" or "es": the language the caller wants the texts in (field "lang" of the body; Spanish if it does not say)."""
    try:
        d = json.loads(body or "")
        if d.get("lang"):
            messages.note_request_language(d["lang"])  # the machine's language while global.workshopLanguage does not exist
        return "en" if str(d.get("lang") or "").lower().startswith("en") else "es"
    except (ValueError, AttributeError):
        return "es"


# ---- HTTP endpoint (DSF) ----

async def _read_full_request(conn):
    """The request JSON sent by DWS (dsf-python reads only 32 KB at once)."""
    data = b""
    while len(data) <= MAX_BODY + 65536:
        try:
            chunk = await asyncio.wait_for(conn.reader.read(65536), timeout=5 if data else 30)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        data += chunk
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            continue
    return json.loads(data.decode("utf-8"))  # raises: incomplete or too big


def serve(registry, namespace, path="api", http_info=None):
    """Registers GET and POST /machine/<namespace>/<path> in a thread of its own
    and keeps them alive (re-registers if the connection to DSF drops).
    http_info(request) -> dict with client data for the history (optional)."""

    def handler():
        async def _h(conn):
            from dsf.http import HttpResponseType
            op_name = None
            try:
                try:
                    d = await _read_full_request(conn)
                except Exception:
                    raise ApiError("bad_request", "request too big or incomplete (max 1 MB)")
                session = d.get("sessionId")
                headers = d.get("headers") or {}
                loop = asyncio.get_running_loop()
                via, keyrec = await loop.run_in_executor(None, registry.auth_of, session, headers)
                body = d.get("body") or ""
                if not str(body).strip():  # GET (or an empty POST): description
                    status, out = 200, {"ok": True, "op": "api.describe", "result": registry.describe(), "message": None}
                else:
                    op_name, args, confirm, origin = parse_request_body(body)
                    ctx = {"via": via, "confirm": confirm, "origin": origin, "lang": request_lang(body), "session": session if isinstance(session, int) and session >= 0 else None, "key": keyrec}
                    if http_info is not None:
                        try:
                            ctx["http"] = http_info(headers, session)
                        except Exception:
                            ctx["http"] = {}
                    status, out = await loop.run_in_executor(None, registry.call, op_name, args, ctx)
            except ApiError as e:
                status, out = e.status, e.body(op_name)
            except Exception as e:  # noqa: BLE001
                status, out = 500, ApiError("internal", str(e)).body(op_name)
            try:
                await conn.send_response(status, json.dumps(out, ensure_ascii=False, default=str), HttpResponseType.JSON)
            except Exception:
                pass
        return _h

    def loop():
        from dsf.connections import CommandConnection
        from dsf.object_model import HttpEndpointType
        wait = 5
        while True:
            conn = None
            eps = []
            try:
                conn = CommandConnection()
                conn.connect()
                if registry.has_password is None:
                    registry.has_password = _password_checker(conn)
                ep = conn.add_http_endpoint(HttpEndpointType.POST, namespace, path)
                ep.set_endpoint_handler(handler())
                eps.append(ep)
                try:  # GET (the description) is a convenience: never block the POST for it
                    ep = conn.add_http_endpoint(HttpEndpointType.GET, namespace, path)
                    ep.set_endpoint_handler(handler())
                    eps.append(ep)
                except Exception as e:
                    registry.log(f"api: GET endpoint not available ({e}); POST api.describe still works")
                wait = 5
                while True:
                    time.sleep(3600)
            except Exception as e:
                msg = str(e)
                if "ermission" in msg or "not allowed" in msg.lower():
                    registry.log(f"api: no permission for the HTTP endpoint ({msg})")
                    return
                if wait == 5:
                    registry.log(f"api endpoint: {msg}; retry in {wait} s")
            finally:
                for x in eps + [conn]:
                    try:
                        if x is not None:
                            x.close()
                    except Exception:
                        pass
            time.sleep(wait)
            wait = min(wait * 2, 120)

    t = threading.Thread(target=loop, name=f"api-{namespace}", daemon=True)
    t.start()
    return t


def _password_checker(conn):
    """fn() -> True if DWC has a password (cached 30 s). DSF answers true to
    any password when there is none (or the factory one, "reprap")."""
    cache = {"has": True, "ts": 0.0}
    lock = threading.Lock()

    def has():
        with lock:
            if time.time() - cache["ts"] > 30:
                try:
                    r = conn.check_password("workshop-no-password-9f3k")
                    cache["has"] = not bool(getattr(r, "result", r))
                except Exception:
                    cache["has"] = True
                cache["ts"] = time.time()
            return cache["has"]

    return has
