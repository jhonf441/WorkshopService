"""
Several energy meters (2026-10-10: "what happens if I had another meter,
for example for the bed because it is high power").

config.json "medidores": list of
  {slot, name, id, ip, key, version, offset_kwh,   <- the Tuya meter (slot = our identifier of the meter; key = the Tuya local key)
   inside_of,     null = own line; "<slot>" = measures a PART of another
                  (not added to the total: it is already counted in the other)
   feeds_pi,   true on the one that powers the Pi: it is ALWAYS cut last
   corta,         true = Shut down / at the end / timer cut it
   orden,         cut order among those that do not power the Pi (lower first)
   vigila}        null or {calentador: "cama"|"camara"|"H<n>", threshold_w, cortar}:
                  alarm if it consumes with that heater off (stuck relay or SSR)

config["meter"] is written with the main one (the mirror that tuya_meter reads).

"""
import json
import os
import re

import config_store  # settings on the card and keys in /opt/dsf/conf (2026-10-11)
from messages import M, J
_cache = {"mtime": None, "list": None}

FIELDS_TUYA = ("id", "ip", "key", "version", "offset_kwh")


def _normalize(m, i):
    slot = re.sub(r"[^a-z0-9_-]", "", str(m.get("slot") or "").lower())[:24] or ("m" + str(i + 1))
    v = m.get("watches")
    if isinstance(v, dict) and v.get("heater"):
        v = {"heater": str(v["heater"]), "threshold_w": float(v.get("threshold_w") or 40), "cut": bool(v.get("cut"))}
    else:
        v = None
    return {
        "slot": slot,
        "name": str(m.get("name") or slot)[:30],
        "id": str(m.get("id") or ""), "ip": str(m.get("ip") or ""), "key": str(m.get("key") or ""),
        "version": str(m.get("version") or "3.3"), "offset_kwh": float(m.get("offset_kwh") or 0.0),
        "inside_of": (str(m["inside_of"]) if m.get("inside_of") else None),
        "feeds_pi": bool(m.get("feeds_pi")),
        "short": bool(m.get("short", True)),
        "order": int(m.get("order") or 0),
        "watches": v,
    }


def since_config(cfg):
    """List normalized from a config dict (in memory or from disk)."""
    lst = cfg.get("meters")
    if not isinstance(lst, list):
        lst = []
    out = [_normalize(m, i) for i, m in enumerate(lst)]
    # unique keys; inside_of only to one that exists and not to itself
    views = set()
    for m in out:
        while m["slot"] in views:
            m["slot"] += "x"
        views.add(m["slot"])
    for m in out:
        if m["inside_of"] not in views or m["inside_of"] == m["slot"]:
            m["inside_of"] = None
    if out and not any(m["feeds_pi"] for m in out):
        pass  # none powers the system (e.g. cut by PS_ON): valid
    return out


def entries():
    """From the config.json on disk (cached by date), for the threads that do not
    have the config in memory (poller, shutdown)."""
    try:
        mt = config_store.mtime()
    except OSError:
        return []
    if mt is None:
        return []
    if _cache["mtime"] != mt:
        try:
            _cache["list"] = since_config(config_store.load_data() or {})
        except Exception:
            _cache["list"] = _cache["list"] or []
        _cache["mtime"] = mt
    return [dict(m) for m in (_cache["list"] or [])]


def main(lst=None):
    lst = entries() if lst is None else lst
    for m in lst:
        if m["feeds_pi"]:
            return m
    return lst[0] if lst else None


def configured(m):
    return bool(m and m.get("id") and m.get("ip") and m.get("key"))


def as_dev(m):
    """Format understood by tuya_meter.read()."""
    return {"id": m["id"], "ip": m["ip"], "key": m["key"], "version": m["version"], "offset_kwh": m["offset_kwh"], "origin": "config"}


def of_line_own(lst):
    """Those that add to the total (they are not inside another)."""
    return [m for m in lst if not m["inside_of"]]


def save(config, lst):
    """Writes the list into the in-memory config (the caller does save_config)."""
    lst = since_config({"meters": lst})
    config["meters"] = lst
    p = main(lst)
    if p and configured(p):
        config["meter"] = {k: p[k] for k in FIELDS_TUYA}
    else:
        config.pop("meter", None)
    return lst


def order_of_cut(lst):
    """Those that are cut on shutdown: first those that do NOT power the Pi (by
    'orden'), and at the end the one that powers the Pi (cutting it turns everything off)."""
    cut = [m for m in lst if m["short"] and configured(m)]
    others = sorted([m for m in cut if not m["feeds_pi"]], key=lambda m: (m["order"], m["name"]))
    pi = [m for m in cut if m["feeds_pi"]]
    return others + pi


def breakdown(since_iso, until_iso):
    """Energy of each meter that is NOT the main one over a range (e.g. a
    job). -> {"extra_kwh": what the own-line ones add up to (it has to be
    added to the main one's total), "texto": "Bed 0.420 kWh (inside
    General)"} or None if there are no other meters."""
    import db
    lst = [m for m in entries() if configured(m)]
    prin = main(lst)
    others = [m for m in lst if not prin or m["slot"] != prin["slot"]]
    if not others:
        return None
    names = {m["slot"]: m["name"] for m in lst}
    extra = 0.0
    parts = []
    for m in others:
        try:
            r = db.consumption_span_summary(since_iso, until_iso, m["slot"])
        except Exception:
            r = None
        if not r:
            continue
        kwh = max(0.0, r["consumption_kwh"])
        if kwh < 0.005 and r["samples"]:
            # steps of 0.01 kWh: estimate with the average power
            import datetime
            try:
                t0 = datetime.datetime.fromisoformat(since_iso)
                t1 = datetime.datetime.fromisoformat(until_iso)
                kwh = r["average_w"] * (t1 - t0).total_seconds() / 3600000.0
            except Exception:
                pass
        if m["inside_of"]:
            parts.append(M("meter_inside", name=m["name"], kwh=kwh, parent=names.get(m["inside_of"], m["inside_of"])))
        else:
            extra += kwh
            parts.append(M("meter_aside", name=m["name"], kwh=kwh))
    return {"extra_kwh": round(extra, 4), "text": J(parts, "; ")} if parts else None
