"""
health_poller -- health of the Raspberry Pi and of the workshop services.

Shown by the "Pi health" page (WorkshopPiHealth plugin). It publishes the
plugin data "healthPi" every INTERVAL_S. It sends NO code to RRF: it only
reads the operating system (vcgencmd, /proc, /sys, nmcli, systemctl, ping,
journalctl) and DSF's shared state (machine_state.get_status).

Requested 2026-10-09 (session system32-69): CPU state, temperature, RAM and
storage (those are published by DSF itself, see Health.vue) + low voltage and
thermal throttling, WiFi, services, link with the Duet, load of the
screens, and ALERTS that can be turned on/off.

Alerts: activity.log_event (they go to Activity and to the phone if the type
is enabled in notifier.KINDS / Activity page / Health page):
  health_temp      high CPU temperature (sustained)
  health_voltage   low voltage in the Pi's power supply
  health_wifi      WiFi down or the router does not answer (sustained)
  health_service  a workshop service stopped running
  health_restart  the Pi restarted without an orderly shutdown
  health_disk     little free space on the Pi's card or the service's
                  database too big (2026-10-10)
Each alert has a margin (sustained N s) and waits WAIT_REPEAT_S before
repeating; when it returns to normal "OK again" is recorded.

"""
import paths
import json
import os
import socket
import sqlite3
import subprocess
import time

import heartbeats
import viewers
import urllib.error
import urllib.request

import activity
import cpu_meter
import health_history
import machine_state
from messages import M, J, B, Msg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "workshop-service.log")
STATE_FILE = os.path.join(BASE_DIR, "health_state.json")
try:
    import db as _db
    DB_FILE = _db.DB_FILE  # the database has been on DSF's SD since 2026-10-10
except Exception:
    DB_FILE = os.path.join(BASE_DIR, "duet.db")

INTERVAL_S = 10
PUBLISH_IDLE_S = 30  # nobody looking at the Health page: one set_plugin_data every 30 s
NETWORK_EACH_S = 30          # pings / HTTP
JOURNAL_EACH_S = 60      # counts in the journal (expensive: DWS logs a lot)
BASE_EACH_S = 300        # database state (row count)
SAVE_STATE_EACH_S = 60
WAIT_REPEAT_S = 30 * 60

# Default thresholds (can be changed in config.json -> "salud")
DEFAULTS = {
    "temp_alert_c": 75,      # an SBC slows down (throttling) at ~80 C
    "temp_sustained_s": 60,
    "wifi_sustained_s": 60,
    "service_sustained_s": 30,
    "disk_alert_gb": 2,     # free on the system card (or less than 10 %)
    "disk_alert_pct": 10,
    "base_alert_mb": 200,    # the service's database should not exceed a few MB
    # DuetControlServer keeps ~6 sockets per minute open after their client is gone (measured
    # 2026-10-13: 6000 open after 17 h and the process at 180 % CPU; a restart brings it to ~20 %)
    "dcs_fds_alert": 2500,
    "history_days": 7,       # days of Pi health history kept in the database (health_history.py)
}

SERVICES = [
    (M("svc_dcs"), "duetcontrolserver"),
    (M("svc_dws"), "duetwebserver"),
    (M("svc_dps"), "duetpluginservice"),
    # Puente G-code (Telnet): the unit is workshop-gcode-bridge (alias workshop-bridge). It is shown only when it is
    # enabled or running.
    (M("svc_bridge"), "workshop-gcode-bridge"),
]
OPTIONAL = {"workshop-gcode-bridge"}

THROTTLE_BITS = {
    0: "low_voltage_now",
    1: "frequency_limited_now",
    2: "limited_now",
    3: "limit_temp_now",
    16: "low_voltage_since_startup",
    17: "frequency_limited_since_startup",
    18: "limited_since_startup",
    19: "limit_temp_since_startup",
}


def log_file(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [health_poller] {msg}\n")
    except Exception:
        pass


def _sh(cmd, timeout=4):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


# ---------------- lecturas ----------------

def read_throttled():
    out = _sh(["vcgencmd", "get_throttled"])
    if not out or "=" not in out:
        return None
    try:
        raw = int(out.strip().split("=", 1)[1], 16)
    except ValueError:
        return None
    d = {"raw": hex(raw)}
    for bit, name in THROTTLE_BITS.items():
        d[name] = bool(raw & (1 << bit))
    return d


_cpu_meter = cpu_meter.CpuMeter()


def read_cpu():
    """Temperature, frequency, load average and CPU use in % (`use_pct`: the camera relay reads it from the published data instead of measuring)."""
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    freq = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    load = _read("/proc/loadavg")
    use = _cpu_meter.read()
    return {
        "temp_c": round(int(temp) / 1000.0, 1) if temp else None,
        "freq_mhz": round(int(freq) / 1000) if freq else None,
        "load": [float(x) for x in load.split()[:3]] if load else None,
        "use_pct": None if use is None else round(use, 1),
    }


def read_ram_pct():
    """% of the memory in use (MemTotal and MemAvailable of /proc/meminfo), or None."""
    try:
        v = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    v[k] = float(rest.split()[0])
        return 100.0 * (v["MemTotal"] - v["MemAvailable"]) / v["MemTotal"]
    except Exception:
        return None


def history_sample(cpu, wifi, disk):
    """The values saved in the health history (units of the charts of the Pi health page)."""
    return {"cpu": cpu.get("use_pct"), "temp": cpu.get("temp_c"), "ram": read_ram_pct(),
            "disk": None if not disk or disk.get("free_pct") is None else 100.0 - disk["free_pct"],
            "wifi": (wifi.get("signal_pct") or 0) if wifi.get("connected") else 0}


def read_wifi():
    w = {"connected": False}
    out = _sh(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,RATE,CHAN", "dev", "wifi", "list", "--rescan", "no"])
    if out:
        for line in out.splitlines():
            # nmcli -t escapes ':' as '\:' inside the fields
            parts = line.replace("\\:", "\x00").split(":")
            parts = [p.replace("\x00", ":") for p in parts]
            if parts and parts[0] == "yes" and len(parts) >= 5:
                w.update({
                    "connected": True,
                    "ssid": parts[1],
                    "signal_pct": int(parts[2]) if parts[2].isdigit() else None,
                    "speed": parts[3],
                    "channel": parts[4],
                })
                break
    wl = _read("/proc/net/wireless")
    if wl:
        for line in wl.splitlines()[2:]:
            if line.strip().startswith("wlan0:"):
                f = line.split()
                try:
                    w["dbm"] = int(float(f[3].rstrip(".")))
                except (IndexError, ValueError):
                    pass
    ip = _sh(["ip", "-4", "-o", "addr", "show", "wlan0"])
    if ip:
        try:
            w["ip"] = ip.split()[3].split("/")[0]
        except IndexError:
            pass
    gw = _sh(["ip", "route", "show", "default"])
    if gw and gw.split():
        f = gw.split()
        if "via" in f:
            w["router"] = f[f.index("via") + 1]
    return w


def ping_ms(host):
    if not host:
        return None
    out = _sh(["ping", "-c", "1", "-W", "2", host], timeout=4)
    if not out:
        return None
    for tok in out.split():
        if tok.startswith("time="):
            try:
                return round(float(tok[5:]), 1)
            except ValueError:
                return None
    return None


def http_ms(url):
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, method="HEAD")
        urllib.request.urlopen(req, timeout=4)
    except urllib.error.HTTPError:
        pass  # it answered (even if 4xx): there is a connection
    except Exception:
        return None
    return round((time.monotonic() - t0) * 1000)


def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except Exception:
        return False


def read_dcs():
    """Open file descriptors of DuetControlServer (the same user, so /proc/<pid>/fd is readable).
    They grow ~6 per minute for a reason not found yet; the CPU of the process follows them."""
    # the pid comes from systemd: pgrep reads /proc of every process and AppArmor denies that (ptrace read)
    out = _sh(["systemctl", "show", "-p", "MainPID", "--value", "duetcontrolserver"])
    try:
        pid = int((out or "").split()[0])
        if pid <= 0:
            return None
        return {"pid": pid, "fds": len(os.listdir(f"/proc/{pid}/fd"))}
    except Exception:
        return None


def read_services():
    out = []
    for label, unit in SERVICES:
        is_active = (_sh(["systemctl", "is-active", unit]) or "").strip()
        if unit in OPTIONAL and is_active != "active":
            able = (_sh(["systemctl", "is-enabled", unit]) or "").strip()
            if able != "enabled":
                continue  # not installed / replaced: it is not a failure
        since = (_sh(["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", unit]) or "").strip()
        out.append({"name": label, "unit": unit, "active": is_active == "active", "state": is_active or "?", "since": since or None})
    return out


def port_bridge():
    # the port is configured on the Services page (0:/sys/workshop/config/bridge.json)
    try:
        import json as _json
        with open(paths.DATA_DIR + "/bridge-state.json") as f:
            d = _json.load(f)
            return int(d.get("port") or d.get("port") or 23)  # "puerto": bridge 2.x
    except Exception:
        return 23


def clients_bridge():
    out = _sh(["ss", "-Htn", "state", "established", f"( sport = :{port_bridge()} )"])
    if out is None:
        return None
    return len([l for l in out.splitlines() if l.strip()])


def programs_bridge():
    """Names of those connected to the bridge (the ones set with
    BRIDGE NAME or in Services > Bridge > Names by IP; otherwise, clientN)."""
    try:
        import json as _json
        with open(paths.DATA_DIR + "/bridge-state.json") as f:
            d = _json.load(f)
            return [f"{c.get('name')} ({c.get('ip')})" for c in (d.get("clients") or [])]
    except Exception:
        return None


def _local_a_dwc():
    out = _sh(["ss", "-Htn", "state", "established", "( dport = :80 )"])
    if out is None:
        return None
    loc = set()
    for l in out.splitlines():
        p = l.split()
        if len(p) >= 2 and p[-2].startswith(("127.", "[::1]", "[::ffff:127.")):
            loc.add(p[-2])
    return loc


def kiosk_active():
    """The kiosk is Chromium on the Pi's screen with DWC open on
    localhost: it has a FIXED connection (websocket) from localhost to port 80.
    2026-10-11: before with pgrep, but WorkshopService's AppArmor profile does
    not allow looking at other processes (ptrace) and it always said "not running"; ss reads
    /proc/net/tcp, which is allowed. Two separate reads: the short queries
    to localhost (from the service itself) come and go, the kiosk's stays.
    None if it could not be known."""
    a = _local_a_dwc()
    if not a:
        return None if a is None else False
    time.sleep(1.5)
    b = _local_a_dwc()
    if b is None:
        return None
    return bool(a & b)


def journal_count(unit, since, pattern, patron2=None):
    """Number of lines of the journal of `unit` that contain `pattern`
    (and `pattern2`, if given).
    None if there is no permission to read the system journal."""
    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, "--since", since, "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if r.returncode != 0 or "No journal files were opened" in r.stderr or "insufficient permissions" in (r.stderr or "").lower():
        return None
    return sum(1 for l in r.stdout.splitlines() if pattern in l and (patron2 is None or patron2 in l))


def read_duet(status):
    if not status:
        return None
    boards = status.get("boards") or []
    main = boards[0] if boards else {}
    board_list = []
    for b in boards:
        board_list.append({
            "name": b.get("shortName") or b.get("name"),
            "can": b.get("canAddress"),
            "state": b.get("state"),
            "firmware": b.get("firmwareVersion"),
        })
    return {
        "state": (status.get("state") or {}).get("status"),
        "firmware": main.get("firmwareVersion"),
        "mcu_temp_c": ((main.get("mcuTemp") or {}).get("current")),
        "vin_v": ((main.get("vIn") or {}).get("current")),
        "boards": board_list,
    }


def age_data(status=None):
    """Seconds since the last update of the other readers' data.
    2026-10-12: from the heartbeat of the motors thread (same process); the
    single subscription does not bring plugins.* (our own data would come back
    as patches with every set_status)."""
    out = {}
    try:
        d = heartbeats._info.get("motors") or {}
        if d.get("last_ok"):
            out["motors_s"] = round(time.time() - d["last_ok"])
    except Exception:
        pass
    return out


def boot_id():
    return _read("/proc/sys/kernel/random/boot_id")


def uptime_s():
    u = _read("/proc/uptime")
    return float(u.split()[0]) if u else None


def clock_synchronized():
    out = _sh(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    return None if out is None else out.strip() == "yes"


# ---------------- alertas ----------------

class Alert:
    def __init__(self, type_name, sustained_s):
        self.type_name = type_name
        self.sustained_s = sustained_s
        self.since = None       # when the condition started
        self.active = False     # already notified
        self.last_notice = 0

    def evaluate(self, bridge, condition, text_bad, text_well):
        current_time = time.time()
        if condition:
            if self.since is None:
                self.since = current_time
            if current_time - self.since >= self.sustained_s and (not self.active or current_time - self.last_notice >= WAIT_REPEAT_S):
                self.active = True
                self.last_notice = current_time
                _event(bridge, self.type_name, text_bad)
        else:
            if self.active:
                _event(bridge, self.type_name, text_well)
            self.since = None
            self.active = False


def _event(bridge, type_name, raw_text):
    log_file(f"{type_name}: {raw_text}")
    try:
        activity.log_event(bridge, type_name, raw_text)
    except Exception as e:
        log_file(f"could not record {type_name}: {e}")


def check_restart(bridge):
    """At startup: if the Pi restarted (different boot_id) WITHOUT a recorded
    orderly shutdown ('power' event near the last data seen), notify."""
    bid = boot_id()
    try:
        with open(STATE_FILE) as f:
            prev = json.load(f)
    except Exception:
        prev = None
    if not prev or not bid or prev.get("boot_id") == bid:
        return None
    last = prev.get("last_seen") or 0
    clean = False
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last - 900))
        until = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last + 120))
        n = con.execute("select count(*) from actividad where tipo = 'power' and ts between ? and ?", (since, until)).fetchone()[0]
        con.close()
        clean = n > 0
    except Exception:
        pass
    info = {"last_datum": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)) if last else None, "ordenado": clean}
    if not clean and last:
        _event(bridge, "health_restart", M("health_restart", datum=info["last_datum"]))
    return info


_WATCHDOG_BRIDGE = {}


def _events_bridge_recent(seconds=120):
    """The bridge says it was asked to restart (code 'restarting' in its events) within the last seconds."""
    try:
        with open(paths.DATA_DIR + "/bridge-state.json") as f:
            events = (json.load(f) or {}).get("events") or []
    except Exception:
        return False
    current_time = time.localtime()
    sec_today = current_time.tm_hour * 3600 + current_time.tm_min * 60 + current_time.tm_sec
    for e in events[:40]:
        if e.get("code") != "restarting":
            continue
        try:
            h, m, s = [int(x) for x in str(e.get("time")).split(":")]
        except Exception:
            continue
        if (sec_today - (h * 3600 + m * 60 + s)) % 86400 <= seconds:
            return True
    return False


def watch_bridge(bridge, services):
    """Records in Activity when the bridge starts / stops and why (bridge_watchdog.py)."""
    import bridge_watchdog
    import bridge_service
    unit = next((s for s in services if s.get("unit") == "workshop-gcode-bridge"), None)
    if unit is None:
        return
    mono = (_sh(["systemctl", "show", "-p", "ActiveEnterTimestampMonotonic", "--value", "workshop-gcode-bridge"]) or "").strip()
    since_us = int(mono) if mono.isdigit() and int(mono) > 0 else None
    request = bridge_service.LAST["t"]
    raw_text = bridge_watchdog.watch(
        _WATCHDOG_BRIDGE, bool(unit.get("active")), since_us, uptime_s(),
        request_page=(time.time() - request) if request else None,
        restart_request=_events_bridge_recent(),
        flag_shutdown=os.path.exists(bridge_service.FLAG),
    )
    if raw_text:
        _event(bridge, "system", raw_text)


def save_state():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"boot_id": boot_id(), "last_seen": int(time.time())}, f)  # entero: ver apagado.py
            f.flush()
            os.fsync(f.fileno())  # to the card before the rename (power cut)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


# ---------------- bucle ----------------

def run_loop(bridge, config):
    log_file(f"starting (every {INTERVAL_S}s)")
    cfg = dict(DEFAULTS)
    cfg.update(config.get("health") or {})
    health_history.set_retention(cfg.get("history_days", health_history.RETENTION_DAYS))
    try:
        restart = check_restart(bridge)
    except Exception as e:
        restart = None
        log_file(f"check_restart failed: {e}")
    save_state()

    a_temp = Alert("health_temp", cfg["temp_sustained_s"])
    a_volt = Alert("health_voltage", 0)
    a_wifi = Alert("health_wifi", cfg["wifi_sustained_s"])
    a_serv = {u: Alert("health_service", cfg["service_sustained_s"]) for _, u in SERVICES}
    a_disk = Alert("health_disk", 60)
    a_base = Alert("health_disk", 0)
    a_dcs = Alert("health_service", 300)

    network = {}
    jour = {}
    t_network = t_jour = t_save = t_base = 0
    base_state = None
    cycle = 0
    while True:
        cycle += 1
        try:
            current_time = time.time()
            status = None
            try:
                status = machine_state.get_status()  # single subscription (in memory)
            except Exception:
                pass
            cpu = read_cpu()
            thr = read_throttled()
            wifi = read_wifi()
            services = read_services()
            try:
                watch_bridge(bridge, services)
            except Exception as e:
                log_file(f"watch_bridge failed: {e}")

            if current_time - t_network >= NETWORK_EACH_S:
                t_network = current_time
                try:
                    import tuya_meter
                    tuya_ip = (tuya_meter.meter_current() or {}).get("ip")
                except Exception:
                    tuya_ip = None
                network = {
                    "router_ms": ping_ms(wifi.get("router")),
                    "internet_ms": ping_ms("1.1.1.1"),
                    "meter_ms": ping_ms(tuya_ip),
                    "notices_ms": http_ms("https://ntfy.sh/"),
                    "camera": port_open(8090),
                }
            if current_time - t_jour >= JOURNAL_EACH_S:
                t_jour = current_time
                jour = {
                    "reenvios_1h": journal_count("duetcontrolserver", "-1h", "Resending packet"),
                    # only "Request starting": each request appears twice in the log
                    # (starting/finished)
                    "status_per_min": journal_count("duetwebserver", "-60s", "Request starting", "/machine/status"),
                }

            if current_time - t_base >= BASE_EACH_S:
                t_base = current_time
                try:
                    import db as _db

                    base_state = _db.state_base()
                except Exception as e:
                    base_state = {"error": str(e)[:200]}

            disk = None
            try:
                sv = os.statvfs(paths.SD)
                total, idle = sv.f_blocks * sv.f_frsize, sv.f_bavail * sv.f_frsize
                disk = {"total_gb": round(total / 1e9, 1), "free_gb": round(idle / 1e9, 1), "free_pct": round(100 * idle / total, 1) if total else None}
            except Exception:
                pass

            dcs = read_dcs()

            sessions = []
            try:
                for s in ((status or {}).get("sbc") or {}).get("dsf", {}).get("userSessions") or []:
                    o = str(s.get("origin") or "").replace("::ffff:", "")
                    # localhost = the kiosk + the internal programs (other plugins
                    # that ask for the state over HTTP; WorkshopService no longer: 2026-10-12)
                    sessions.append(M("health_poller_this_computer_kiosk_internal_programs") if o in ("::1", "127.0.0.1") else o)
            except Exception:
                pass

            data = {
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "uptime_s": uptime_s(),
                "cpu": cpu,
                "throttled": thr,
                "clock_synchronized": clock_synchronized(),
                "wifi": wifi,
                "red": network,
                "services": services,
                "kiosk": kiosk_active(),
                "bridge_clients": clients_bridge(),
                "bridge_programs": programs_bridge(),
                "data": age_data(status),
                "duet": read_duet(status),
                # DSF sessions grouped by computer: each load/reload of DWC
                # creates a session and the old ones can stay registered for a while,
                # so the number of COMPUTERS is what matters.
                "screens": {
                    "sessions": len(sessions),
                    "origenes": sessions,
                    "devices": [{"origin": o, "sessions": sessions.count(o)} for o in sorted(set(sessions), key=lambda x: (not isinstance(x, Msg), x))],
                    "status_per_min": jour.get("status_per_min"),
                },
                "reenvios_1h": jour.get("reenvios_1h"),
                "restart": restart,
                # service database (only if it exists; measured every 5 min)
                "base": base_state,
                "disk": disk,
                "dcs": dcs,
                "thresholds": cfg,
            }
            # DCS load: the cycle (local reads, alerts) keeps its pace, but the plugin data
            # goes to DCS at most every PUBLICAR_IDLE_S unless the Health page is open
            # (heartbeat, viewers.py topic "health"); nobody looking: no timestamp counts as a change
            if viewers.active("health"):
                bridge.set_status("healthPi", data)
            else:
                bridge.set_status("healthPi", data, min_interval=PUBLISH_IDLE_S)
            heartbeats.ok("health")
            try:
                health_history.record(history_sample(cpu, wifi, disk))
            except Exception as e:
                log_file(f"history failed: {e}")

            # --- alertas ---
            t = cpu.get("temp_c")
            a_temp.evaluate(bridge, t is not None and t >= cfg["temp_alert_c"],
                           M("health_temp_high", t=t, limit=cfg["temp_alert_c"]),
                           M("health_temp_ok", t=t))
            if thr:
                a_volt.evaluate(bridge, thr["low_voltage_now"],
                               M("health_volt_low"),
                               M("health_volt_ok"))
            # down = no WiFi, or the router did not answer the last ping (every NETWORK_EACH_S)
            drop = (not wifi.get("connected")) or bool(wifi.get("router") and "router_ms" in network and network["router_ms"] is None)
            a_wifi.evaluate(bridge, drop,
                               M("health_wifi_down_net", ssid=wifi.get("ssid")) if wifi.get("ssid") else M("health_wifi_down"),
                               M("health_wifi_ok", ssid=wifi.get("ssid"), signal=wifi.get("signal_pct")))
            for s in services:
                a_serv[s["unit"]].evaluate(bridge, not s["active"],
                                             M("health_service_down", name=s["name"], unit=s["unit"], state=s["state"]),
                                             M("health_service_ok", name=s["name"]))

            if disk:
                little = disk["free_gb"] < cfg["disk_alert_gb"] or (disk["free_pct"] is not None and disk["free_pct"] < cfg["disk_alert_pct"])
                a_disk.evaluate(bridge, little,
                                M("health_disk_low", free_gb=disk["free_gb"], free_pct=disk["free_pct"]),
                                M("health_disk_ok", free_gb=disk["free_gb"]))
            if dcs:
                a_dcs.evaluate(bridge, dcs["fds"] > cfg["dcs_fds_alert"],
                              M("health_dcs_high", fds=dcs["fds"]),
                              M("health_dcs_ok", fds=dcs["fds"]))
            if base_state and base_state.get("mb") is not None:
                a_base.evaluate(bridge, base_state["mb"] > cfg["base_alert_mb"],
                               M("health_base_big", mb=base_state["mb"], limit=cfg["base_alert_mb"]),
                               M("health_base_ok", mb=base_state["mb"]))

            if current_time - t_save >= SAVE_STATE_EACH_S:
                t_save = current_time
                save_state()
            if cycle == 1 or cycle % 360 == 0:
                log_file(f"cycle {cycle} OK: temp {cpu.get('temp_c')} C, wifi {wifi.get('signal_pct')} %")
        except BaseException as e:
            log_file(f"cycle {cycle} error ({type(e).__name__}: {e})")
            heartbeats.error("health", e)
        time.sleep(INTERVAL_S)
