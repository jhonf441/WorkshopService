"""
Electric consumption poller -- it runs in a background thread inside
dsf/main.py (like status_light.py), querying the Tuya meter
"Impresora" (tuya_meter.py) every POLL_INTERVAL_S seconds:

  1. It adds a row to the "consumo" table of db.py (SQLite) so that
     handlers/consumption_period.py can compute consumption per period
     later, subtracting the meter's accumulated total_forward_energy
     between two timestamps -- more precise than integrating power by hand
     over a sample every 30 s.

It must never bring the plugin down if the meter does not answer (WiFi down,
meter restarting, etc.) -- any exception is logged and retried in the next
cycle; the global variables are simply not updated that cycle (they keep the
last good reading).

"""
import os
import time

import heartbeats
import service_modules
import viewers

import db
import meters
import tuya_meter
from messages import M, J, B

POLL_INTERVAL_S = 30

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Same file used by main.py and status_light.py -- so the three sources
# are interleaved in chronological order in a single log.
LOG_FILE = os.path.join(BASE_DIR, "workshop-service.log")


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [consumption_poller] {msg}\n")
    except Exception:
        pass


# Counter (dp 1) that goes down: a single reading at 0 is a read failure (it is not
# saved); if the next one is also low, the meter really restarted and
# the difference is added to the splice (offset_kwh) so the accumulated value continues.
_last_kwh = {}  # clave -> ultimo energy_kwh guardado
_low = {}  # clave -> lecturas bajas seguidas


def _check_counter(bridge, config, m, reading):
    """True = save the reading. It may correct reading and the offset."""
    key = m["slot"]
    ant = _last_kwh.get(key)
    if ant is None:
        latest = db.consumption_last(key)
        ant = latest["energy_kwh"] if latest else None
    e = reading["energy_kwh"]
    if ant is None or e >= ant - 0.02:
        _low[key] = 0
        _last_kwh[key] = e
        return True
    _low[key] = _low.get(key, 0) + 1
    if _low[key] < 2:
        log_file(f"{key}: counter {e} lower than {ant} (this reading is ignored)")
        return False
    # real counter restart: splice
    delta = round(ant - e, 3)
    try:
        lst = meters.since_config(config)
        for x in lst:
            if x["slot"] == key:
                x["offset_kwh"] = round(float(x.get("offset_kwh") or 0.0) + delta, 3)
        meters.save(config, lst)
        bridge.save_config()
        log_file(f"{key}: the meter restarted its counter ({ant} -> {e}); splice +{delta} kWh")
    except Exception as ex:
        log_file(f"{key}: could not save the splice ({ex})")
    reading["energy_kwh"] = round(e + delta, 3)
    _low[key] = 0
    _last_kwh[key] = reading["energy_kwh"]
    return True


def _append_history(ts, reading, meter="general"):
    db.insert_consumption(ts, reading["voltage"], reading["current_a"], reading["power_w"], reading["energy_kwh"], meter)


# ---- Safety alarm (2026-10-10): a meter that watches a heater ----
# If the meter consumes more than threshold_w with that heater OFF for the
# board (or in fault), something was left on from outside (stuck relay or SSR): a
# notice is given (type meter_alarm) and, if requested, that meter is cut.
_alarm = {}  # clave -> {"veces": n, "avisada": bool}
ALARM_CYCLES = 2  # 2 consecutive readings (~1 min) before warning


def _heater_shutdown(st, who):
    heat = (st or {}).get("heat") or {}
    hs = heat.get("heaters") or []
    idx = None
    if who == "bed":
        idx = next((h for h in (heat.get("bedHeaters") or []) if h is not None and h >= 0), None)
    elif who == "camera":
        idx = next((h for h in (heat.get("chamberHeaters") or []) if h is not None and h >= 0), None)
    elif str(who).upper().startswith("H"):
        try:
            idx = int(str(who)[1:])
        except ValueError:
            idx = None
    if idx is None or idx >= len(hs) or not hs[idx]:
        return None, None  # unknown: it is not watched
    h = hs[idx]
    return h.get("state") in ("off", "fault"), "H" + str(idx)


def _watch(bridge, m, reading):
    v = m.get("watches")
    if not v:
        return
    try:
        import machine_state
        st = machine_state.get_status(timeout=3, max_age_s=10)
    except Exception:
        return
    shutdown, hnom = _heater_shutdown(st, v["heater"])
    a = _alarm.setdefault(m["slot"], {"times": 0, "notified": False})
    if shutdown and reading["power_w"] > v["threshold_w"]:
        a["times"] += 1
        if a["times"] >= ALARM_CYCLES and not a["notified"]:
            a["notified"] = True
            cut_state = "none"
            if v.get("cut") and meters.configured(m):
                cut_state = "cut" if tuya_meter.cut(meters.as_dev(m), log=log_file) else "failed"
            raw_text = M("meter_alarm_" + cut_state, name=m["name"], power_w=reading["power_w"], heater=hnom, threshold_w=v["threshold_w"])
            log_file("ALARM " + raw_text)
            try:
                import activity
                activity.log_event(bridge, "meter_alarm", raw_text)
            except Exception:
                pass
    else:
        if a["notified"] and not shutdown is None:
            try:
                import activity
                activity.log_event(bridge, "meter_alarm", M("meter_alarm_normal", name=m["name"]))
            except Exception:
                pass
        a["times"] = 0
        a["notified"] = False


# DCS load: the live reading card (consumptionCurrent) is published at most every PUBLISH_MIN_S when nobody looks at the
# Consumption page (viewers.py, topic "power") and at least every PUBLISH_REFRESH_S (fresh last-reading stamp).
PUBLISH_MIN_S = 60
PUBLISH_REFRESH_S = 300


def run_loop(bridge, config):
    log_file(f"starting (poll every {POLL_INTERVAL_S}s)")
    cycle = 0
    notified_without = False
    while True:
        cycle += 1
        # the Power plugin is stopped or disabled (Settings > Plugins): the meter is not read (service_modules.py)
        if not service_modules.is_active(service_modules.POWER):
            heartbeats.ok("consumption")
            heartbeats.detail("consumption", M("consumption_poller_at_rest_consumption_plugin_stopped"))
            time.sleep(POLL_INTERVAL_S)
            continue
        try:
            lst = [m for m in meters.entries() if meters.configured(m)]
            if not lst:
                if not notified_without:
                    log_file("no meter configured: consumption is not measured (configure it in Consumption > Meters)")
                    notified_without = True
                heartbeats.ok("consumption")
                heartbeats.detail("consumption", M("consumption_poller_no_meter_configured"))
                time.sleep(POLL_INTERVAL_S)
                continue
            notified_without = False
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")  # the same for all: they can be added
            main = meters.main(lst)
            published = []
            detail = []
            read_items = 0
            for m in lst:
                try:
                    t0 = time.monotonic()
                    reading = tuya_meter.read(meters.as_dev(m))
                    ms = (time.monotonic() - t0) * 1000
                except BaseException as e:
                    published.append({"key": m["slot"], "name": m["name"], "ok": False, "error": f"{type(e).__name__}: {e}",
                                       "inside_of": m["inside_of"], "feeds_pi": m["feeds_pi"]})
                    detail.append(M("consumption_poller_meter_no_reading", name=m['name']))
                    if cycle == 1 or cycle % 20 == 0:
                        log_file(f"cycle {cycle} {m['slot']} error ({type(e).__name__}: {e})")
                    continue
                read_items += 1
                if _check_counter(bridge, config, m, reading):
                    _append_history(ts, reading, m["slot"])
                published.append({"key": m["slot"], "name": m["name"], "ok": True, "power_w": reading["power_w"],
                                   "voltage_v": reading["voltage"], "current_a": reading["current_a"], "energy_kwh": reading["energy_kwh"],
                                   "switch": reading.get("switch"), "inside_of": m["inside_of"], "feeds_pi": m["feeds_pi"]})
                retry = max(0, int(reading.get("attempts", 1)) - 1)
                if retry:
                    detail.append(M("consumption_poller_meter_reading_retries", name=m['name'], power_w=reading['power_w'], ms=ms, retry=retry))
                else:
                    detail.append(M("consumption_poller_meter_reading", name=m['name'], power_w=reading['power_w'], ms=ms))
                _watch(bridge, m, reading)
                if cycle == 1 or cycle % 20 == 0:
                    log_file(f"cycle {cycle} {m['slot']} OK: {reading}")

            # What was there before (power_w... of the main one) + all the meters and the
            # total: only those on their own line add up (the ones "inside" another are
            # already counted in that other).
            prin = next((x for x in published if main and x["key"] == main["slot"] and x["ok"]), None)
            own = [x for x in published if x["ok"] and not x["inside_of"]]
            act = {
                "power_w": prin["power_w"] if prin else None,
                "voltage_v": prin["voltage_v"] if prin else None,
                "current_a": prin["current_a"] if prin else None,
                "energy_kwh": prin["energy_kwh"] if prin else None,
                "ts": ts,
                "meters": published,
                "total_w": sum(x["power_w"] for x in own) if own else None,
            }
            if viewers.active("power"):
                bridge.set_status("consumptionCurrent", act)
            else:  # nobody looking: no new timestamp as a change, at most one send a minute
                bridge.set_status("consumptionCurrent", act, volatile=("ts",), min_interval=PUBLISH_MIN_S, keepalive_s=PUBLISH_REFRESH_S)
            if read_items:
                heartbeats.ok("consumption")
            else:
                heartbeats.error("consumption", M("consumption_poller_no_meter_answered"))
            heartbeats.detail("consumption", J(detail, sep=" · "))
        except BaseException as e:
            # BaseException (not just Exception) on purpose: if tinytuya
            # ever raises SystemExit/etc instead of a normal exception
            # on a broken socket, we do not want this thread to die
            # silently without leaving a trace in the log.
            log_file(f"cycle {cycle} error reading/publishing ({type(e).__name__}: {e})")
            heartbeats.error("consumption", e)

        time.sleep(POLL_INTERVAL_S)
