"""
Commands of OTHER plugins in the "Received commands" history (2026-10-10:
"what happened with the other codes, like those of the RS485 bus? add them").

Each plugin that handles its own codes (today WorkshopRS485) appends
a JSON line per command to EXTRA_FILE:
    {"ts": "2026-10-10T23:18:00", "nombre": "rs485 escanear", "codigo": "rs485.scan ...",
     "ok": true, "ms": 120, "respuesta": "...", "via": "pagina (HTTP)", "lectura": false,
     "origen": {"kind": "page", "channel": "HTTP", "plugin": "RS485"}}   <- "origen" is optional (2026-10-12)
and this thread moves them to the comandos table (the same as the API call one) every
few seconds. The file is renamed before reading it: whatever arrives in
the meantime goes to a new file and is not lost.

"""
import paths
import json
import os
import threading
import time

import db

EXTRA_FILE = paths.DATA_DIR + "/extra-commands.jsonl"
EACH_S = 3
MAX_BYTES = 5 * 1024 * 1024  # if something writes non-stop, it does not grow without limit


def _origin(d):
    """Optional origin of the command, as the other plugin knows it. Without it
    the row is marked as coming from that plugin ("plugin" kind)."""
    o = d.get("origin")
    o = dict(o) if isinstance(o, dict) else {}
    out = {}
    for k, v in o.items():
        if isinstance(v, (str, int, float, bool)) and len(str(k)) <= 30:
            out[str(k)[:30]] = v[:200] if isinstance(v, str) else v
    out.setdefault("kind", "plugin")
    out.setdefault("channel", "plugin")
    out.setdefault("label", "another plugin")
    out["result"] = out.get("result") if out.get("result") in ("ok", "error", "blocked") else ("ok" if d.get("ok") else "error")
    out["ms"] = int(d.get("ms") or 0)
    try:
        import origin_track
        origin_track.remember(out)
    except Exception:
        pass
    return out


def _pass(log):
    if not os.path.exists(EXTRA_FILE):
        return 0
    claimed = EXTRA_FILE + ".reading"
    try:
        if os.path.getsize(EXTRA_FILE) > MAX_BYTES:
            os.remove(EXTRA_FILE)
            log("commands_extra: file larger than 5 MB, discarded")
            return 0
        os.replace(EXTRA_FILE, claimed)
    except OSError:
        return 0
    n = 0
    try:
        with open(claimed, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                    db.command_insert(d.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"), str(d.get("name") or "?")[:60],
                                      str(d.get("code") or "")[:400], bool(d.get("ok")), int(d.get("ms") or 0),
                                      str(d.get("response") or "")[:1000], str(d.get("via") or "")[:40], bool(d.get("reading")),
                                      _origin(d))
                    n += 1
                except Exception:
                    continue
    finally:
        try:
            os.remove(claimed)
        except OSError:
            pass
    return n


def loop(log=print):
    while True:
        try:
            _pass(log)
        except Exception as e:
            log(f"commands_extra: {e!r}")
        time.sleep(EACH_S)


def launch(log=print):
    threading.Thread(target=loop, args=(log,), name="commands_extra", daemon=True).start()
