"""
Reader of the Tuya meter/breaker "Impresora" (category dlq -- WIFI
intelligent leakage switch) for the consumption monitor (see
consumption_poller.py and handlers/consumption*.py).

The same device that cuts the power in handlers/shutdown_all.py. The
credentials (ID/IP/local_key) live ONLY in config.json["medidor"] (which does
not go to git), loaded from the Consumption > Meter page. Without a
configured meter, meter_current() returns None and read() raises MeterNotConfigured.

Dp "6" (phase_a) is a Raw field (base64) not decoded by the standard
tinytuya/Tuya Cloud schema -- format discovered by inspecting the snapshot
of the Tuya Cloud API (~/tuya-raw.json on the Pi) and confirmed against live
readings (2026-10-06): 8 bytes = [voltage:2][current:3][power:3], big-endian
unsigned. Voltage in tenths of a volt (/10), current in mA, power already in
W (no scale).
"total_forward_energy" (dp "1") is the meter's lifetime accumulated value in
kWh (scale 2 -> divide by 100) -- it is used for per-period reports by
subtracting two readings, instead of integrating power by hand.

"""
import base64
import time

import tinytuya

import json
import os


# 2026-10-09: the meter can be changed from the Consumption page
# (Meter settings -> handlers/consumption_meter.py), which saves it in
# config.json under "medidor" {id, ip, key, version, offset_kwh}. If nothing
# is saved, the constants of shutdown_all.py are used as always.
# It is read from the file (cached by mtime) because the poller does not
# receive main.py's config dict.
import config_store  # settings on the card and keys in /opt/dsf/conf (2026-10-11)
from messages import M
_cache = {"mtime": None, "meter": None}


def meter_saved():
    """config.json["medidor"] o None."""
    try:
        mtime = config_store.mtime()
        if mtime != _cache["mtime"]:
            _cache["meter"] = (config_store.load_data() or {}).get("meter") or None
            _cache["mtime"] = mtime
    except Exception:
        pass
    return _cache["meter"]


def meter_current():
    """{id, ip, key, version, offset_kwh, origin} of the MAIN meter (the one that
    powers the Pi, see meters.py), or None."""
    import meters
    p = meters.main()
    if meters.configured(p):
        return meters.as_dev(p)
    m = meter_saved()
    if m and m.get("id") and m.get("ip") and m.get("key"):
        return {
            "id": m["id"], "ip": m["ip"], "key": m["key"],
            "version": str(m.get("version") or "3.3"),
            "offset_kwh": float(m.get("offset_kwh") or 0.0),
            "origin": "config",
        }
    return None


def cut(dev, attempts=4, log=None):
    """Opens the meter's switch (dp 16 = False). True if it confirmed it.
    It retries: the local network fails sometimes (same as the reading)."""
    for attempt in range(1, attempts + 1):
        try:
            d = tinytuya.Device(dev["id"], dev["ip"], dev["key"])
            d.set_version(float(dev["version"]))
            d.set_socketTimeout(3)
            r = d.set_value(16, False)
            if log:
                log(f"cut {dev['id']} attempt {attempt}: {r}")
            if not (isinstance(r, dict) and r.get("Error")):
                return True
        except Exception as e:
            if log:
                log(f"cut {dev['id']} attempt {attempt} exception: {e}")
        if attempt < attempts:
            time.sleep(0.7)
    return False


class MeterNotConfigured(RuntimeError):
    """No meter is configured (config.json["medidor"])."""

# The updatedps("6") of this meter fails (returns None) plainly in ~1 out of
# every 3 attempts over the local network -- confirmed live (2026-10-06), the
# same kind of flakiness that already forced retrying in
# handlers/shutdown_all.py (CUT_ATTEMPTS). It is not a bug of this code,
# so it is retried instead of failing on the first attempt.
PHASE_READ_ATTEMPTS = 4


def read(dev=None):
    """Dict with voltage (V), current_a (A), power_w (W) and energy_kwh
    (lifetime accumulated total of the meter, in kWh). Raises an exception
    if the meter does not answer or returns something unexpected.

    Dp "6" (phase_a, instantaneous volt/current/power) does NOT come
    included in a normal d.status() in this firmware -- confirmed live
    (2026-10-06): status() only returns the "background" dps (1, 9, 11-16,
    19, 104, 105), never 6, even though the Tuya Cloud API does list it. It
    has to be requested explicitly with updatedps(), which fires a DP_QUERY and
    if it waits (nowait=False) the answer arrives with that dp already inside.
    """
    if dev is None:
        dev = meter_current()
    if dev is None:
        raise MeterNotConfigured(M("tuya_meter_no_power_meter_configured_consumption_meter"))
    d = tinytuya.Device(dev["id"], dev["ip"], dev["key"])
    d.set_version(float(dev["version"]))
    d.set_socketTimeout(4)

    status = d.status()
    if not isinstance(status, dict) or "dps" not in status:
        raise RuntimeError(M("tuya_meter_invalid_answer_from_meter_status", status=status))
    if "Error" in status or "1" not in status["dps"]:
        raise RuntimeError(M("tuya_meter_device_answered_but_not_compatible_meter", sorted=sorted(status['dps'])))
    # offset_kwh: when changing meter the new one's accumulated value starts at
    # another number; the offset splices it with the last saved value so that
    # the kWh per period do not jump.
    energy_raw = status["dps"].get("1", 0) / 100.0
    energy_kwh = energy_raw + float(dev.get("offset_kwh") or 0.0)

    phase = None
    for attempt in range(1, PHASE_READ_ATTEMPTS + 1):
        result = d.updatedps(["6"], nowait=False)
        if isinstance(result, dict) and "6" in result.get("dps", {}):
            phase = result
            break
        if attempt < PHASE_READ_ATTEMPTS:
            time.sleep(0.5)
    if phase is None:
        raise RuntimeError(
            M("tuya_meter_meter_did_not_return_dp_6", PHASE_READ_ATTEMPTS=PHASE_READ_ATTEMPTS)
        )

    raw = base64.b64decode(phase["dps"]["6"])
    voltage = int.from_bytes(raw[0:2], "big") / 10.0
    current_a = int.from_bytes(raw[2:5], "big") / 1000.0
    power_w = float(int.from_bytes(raw[5:8], "big"))

    return {
        "voltage": voltage,
        "current_a": current_a,
        "power_w": power_w,
        "energy_kwh": energy_kwh,
        "energy_raw_kwh": energy_raw,
        "switch": status["dps"].get("16"),
        "attempts": attempt,  # dp 6 requests until it answered (meter health)
    }
