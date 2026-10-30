"""
Internal implementation of the API operation(s) meter.get, meter.search, meter.test, meter.save, meter.forget, meter.settings (api_ops.py maps their named
arguments to the one-letter parameters below).

Consumption meter configuration (Consumption page -> "Meter"):
query which one is used, search for Tuya devices on the network, test one before
saving it and save it in config.json["medidor"] (read by tuya_meter.py).

Usage: <params>                     -> query (JSON, the key is masked)
     <params> C"buscar"             -> scans the local network (~8 s)
     <params> C"probar"  I"<id>" H"<ip>" K"<hex>" V"3.3"
     <params> C"guardar" I"<id>" H"<ip>" K"<hex>" V"3.3"
     <params> C"olvidar"            -> deletes the configured meter ("restaurar" = old alias)
  Several meters (2026-10-10, meters.py): M"<key>" chooses which one (without M =
  the main one, the one that powers the Pi). Also:
     <params> C"guardar" M"cama" N"Bed" I.. H.. K.. V..   -> adds or changes one
     <params> C"ajustes" M"cama" J"<hex json>"   -> name, inside_of, feeds_pi,
                                                                   corta, orden, vigila
     <params> C"olvidar" M"cama"                  -> removes that meter
  K = local key encoded in HEX (the key usually carries quotes, apostrophes
      or parentheses, which RRF/DSF's G-code parser would alter). Empty =
      keep the saved key.
  "guardar" tests first and only saves if the meter answers.

The power cut of handlers/shutdown_all.py does NOT change: it still uses its
own constants (see its header, not touched without need).

"""
import json
import re

import activity
import db
import meters
import tuya_meter
from messages import M, J, B, Msg

# tinytuya error codes -> explanation for the user
ERRORS = {
    "900": M("consumption_meter_device_answered_something_could_not_read"),
    "901": M("consumption_meter_could_not_connect_check_ip"),
    "902": M("consumption_meter_device_did_not_answer_time"),
    "904": M("consumption_meter_device_did_not_understand_answer_local"),
    "905": M("consumption_meter_device_was_not_found_at_ip"),
    "914": M("consumption_meter_local_key_version_do_not_match"),
}


def _mask(key):
    if not key:
        return ""
    return key[:2] + "•" * max(0, len(key) - 4) + key[-2:]


def _public(dev):
    if not dev:
        return None
    return {
        "id": dev["id"], "ip": dev["ip"], "version": dev["version"],
        "key_mask": _mask(dev["key"]), "origin": dev["origin"],
        "offset_kwh": round(dev.get("offset_kwh") or 0.0, 3),
    }


def _explain(e):
    txt = str(e)
    first = e.args[0] if e.args else None
    m = re.search(r"'Err': '(\d+)'", txt)
    if m and m.group(1) in ERRORS:
        return ERRORS[m.group(1)]
    if "dp 6" in txt:
        return (M("consumption_meter_device_answers_but_does_not_deliver"))
    if isinstance(first, Msg) and first.key == "tuya_meter_device_answered_but_not_compatible_meter":
        return first
    return f"Error: {txt}"


def _params_device(params, current):
    dev_id = str(params.get("I", "")).strip()
    ip = str(params.get("H", "")).strip()
    version = str(params.get("V", "")).strip() or "3.3"
    key_hex = str(params.get("K", "")).strip()
    if key_hex:
        try:
            key = bytes.fromhex(key_hex).decode("utf-8")
        except ValueError:
            raise ValueError(M("consumption_meter_key_arrived_badly_encoded_k_must"))
    else:
        key = current["key"] if current and dev_id == current["id"] else ""
    missing = [n for n, v in ((M("consumption_meter_device_id"), dev_id), ("IP", ip), (M("consumption_meter_local_key"), key)) if not v]
    if missing:
        raise ValueError(M("consumption_meter_missing_fields", fields=J(missing)))
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
        raise ValueError(M("consumption_meter_ip_must_look_like"))
    if version not in ("3.1", "3.2", "3.3", "3.4", "3.5"):
        raise ValueError(M("consumption_meter_invalid_protocol_version_3_1_3"))
    return {"id": dev_id, "ip": ip, "key": key, "version": version, "offset_kwh": 0.0, "origin": "config"}


def _probe(dev):
    try:
        r = tuya_meter.read(dev)
        return {"ok": True, "reading": {
            "power_w": r["power_w"], "voltage_v": r["voltage"],
            "current_a": r["current_a"], "energy_kwh": r["energy_raw_kwh"],
        }}
    except Exception as e:
        return {"ok": False, "error": _explain(e)}


def _public_m(m):
    return {
        "key": m["slot"], "name": m["name"], "id": m["id"], "ip": m["ip"], "version": m["version"],
        "key_mask": _mask(m["key"]), "offset_kwh": round(m.get("offset_kwh") or 0.0, 3),
        "inside_of": m["inside_of"], "feeds_pi": m["feeds_pi"], "short": m["short"], "order": m["order"],
        "watches": m["watches"], "configured": meters.configured(m),
    }


def _state(config, extra=None):
    lst = meters.since_config(config)
    out = {"ok": True, "meter": _public(tuya_meter.meter_current()), "meters": [_public_m(m) for m in lst],
           "order_cut": [m["name"] for m in meters.order_of_cut(lst)]}
    out.update(extra or {})
    return json.dumps(out)


def run(params, bridge, config):
    action = str(params.get("C", "query")).strip().lower()
    lst = meters.since_config(config)
    key = str(params.get("M", "")).strip().lower()
    if not key:
        p = meters.main(lst)
        key = p["slot"] if p else "general"
    this = next((m for m in lst if m["slot"] == key), None)
    current = meters.as_dev(this) if this and meters.configured(this) else None

    if action == "search":
        import tinytuya
        try:
            found = tinytuya.deviceScan(False, 8, False, False)
        except Exception as e:
            return json.dumps({"ok": False, "error": M("consumption_meter_could_not_scan_network", e=e)})
        used = {m["id"]: m["name"] for m in lst if m["id"]}
        entries = [{
            "ip": d.get("ip"), "id": d.get("gwId") or d.get("id"),
            "version": str(d.get("version") or ""), "actual": (d.get("gwId") or d.get("id")) == (current or {}).get("id"),
            "used_per": used.get(d.get("gwId") or d.get("id")),
        } for d in (found or {}).values()]
        return json.dumps({"ok": True, "devices": entries})

    if action in ("forget", "restore"):
        if this:
            lst = [m for m in lst if m["slot"] != key]
            for m in lst:
                if m["inside_of"] == key:
                    m["inside_of"] = None
            if this["feeds_pi"] and lst and not any(m["feeds_pi"] for m in lst):
                lst[0]["feeds_pi"] = True  # siempre queda uno principal
            meters.save(config, lst)
            bridge.save_config()
            activity.log_event(bridge, "config", M("meter_removed", name=this["name"]))
        return _state(config)

    if action == "settings":
        if not this:
            return json.dumps({"ok": False, "error": M("consumption_meter_meter_does_not_exist", key=key)})
        try:
            j = params.get("J")
            changes = j if isinstance(j, dict) else json.loads(bytes.fromhex(str(j or "")).decode("utf-8"))
        except Exception:
            return json.dumps({"ok": False, "error": "The changes must be a JSON object"})
        for k in ("name", "inside_of", "feeds_pi", "short", "order", "watches"):
            if k in changes:
                this[k] = changes[k]
        if this.get("inside_of") == key:
            this["inside_of"] = None
        if this.get("feeds_pi"):
            for m in lst:
                if m is not this:
                    m["feeds_pi"] = False  # only one powers the system
        meters.save(config, lst)
        bridge.save_config()
        activity.log_event(bridge, "config", M("meter_settings_saved", name=this["name"]))
        return _state(config)

    if action in ("test", "save"):
        try:
            dev = _params_device(params, current)
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})
        trial = _probe(dev)
        if action == "test" or not trial["ok"]:
            return json.dumps(trial)
        other = next((m for m in lst if m["id"] == dev["id"] and m["slot"] != key), None)
        if other:
            return json.dumps({"ok": False, "error": M("consumption_meter_device_already_meter", name=other['name'])})

        # Same device (only the IP/key/version changed): the offset is
        # kept. Another device: offset = last saved accumulated value of THIS
        # meter - accumulated value of the new one, so its kWh history does not jump.
        if current and dev["id"] == current["id"]:
            dev["offset_kwh"] = current["offset_kwh"]
        else:
            last = db.consumption_last(key)
            last_kwh = (last or {}).get("energy_kwh")
            if last_kwh is not None:
                dev["offset_kwh"] = round(float(last_kwh) - trial["reading"]["energy_kwh"], 3)
        payload = {k: dev[k] for k in ("id", "ip", "key", "version", "offset_kwh")}
        if this:
            this.update(payload)
            if params.get("N"):
                this["name"] = str(params.get("N"))
        else:
            new = dict(payload, slot=key, name=str(params.get("N") or key), feeds_pi=not lst, short=True,
                         order=len(lst), inside_of=None, watches=None)
            lst.append(new)
        meters.save(config, lst)
        bridge.save_config()
        nom = next((m["name"] for m in meters.since_config(config) if m["slot"] == key), key)
        activity.log_event(bridge, "config", M("meter_set_up", name=nom, id=dev["id"], ip=dev["ip"]))
        return _state(config, {"reading": trial["reading"]})

    return _state(config)
