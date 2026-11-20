"""Example values of the data the service publishes, for the development backend (tools/dev/dev_backend.py).

On the machine these keys are written by processes that do not run on a PC (the health poller, the protection guard, the black box,
the configuration guard, the risk rules). They are built BY HAND here with the shapes documented in the redesign
(informes/rediseno-ui-service/arquitectura/capacidades/B-operacion-datos.md, part 2): they are NOT captures of a real machine, and a
screen that passes on them proves the screen, not the service. The keys the service can publish with its own code on a PC
(servicesInternal, motion, communication, notifications, machine, shutdownTimer, shutdownMethod) are not here: dev_backend.py calls
that code.

    base(now)                 { key: value } of a healthy machine
    NOTICES                   name -> what it does to the published data: every notice the home can show, one at a time
    apply_notice(backend, name)

Texts the service writes go out as {"key", "params"} like the real ones (the pages translate them); no secret, address or key of a
real installation is used.
"""
import time

WATCHES = [("status_light", "lights"), ("camera", "camera"), ("events", "events"), ("motion", "motion"), ("risk", "risk"), ("health", "health"),
           ("guardian_laser", "laser_off"), ("intercept_watchdog", "interception"), ("vision", "fire"), ("rs485", "servo")]


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def db_status(check="ok"):
    return {"file": "0:/sys/workshop/duet.db", "mb": 4.1, "wal_mb": 0.2, "modified": _iso(time.time() - 120), "check": check, "location": "sd", "version_schema": 7,
            "tables": [{"name": "activity", "rows": 1240}, {"name": "commands", "rows": 5200}, {"name": "audit", "rows": 860}, {"name": "consumption", "rows": 20110}, {"name": "health_samples", "rows": 60480}],
            "backups": [], "backup": {"active": True, "late": False, "failures": [], "last": {"date": _iso(time.time() - 6 * 3600)}}}


def guard_status(down=()):
    now = int(time.time())
    watches = [{"id": wid, "title": {"key": "protection_guard_watch_" + wid, "params": {}}, "protects": protects,
                "state": "down" if wid in down else "ok", "since": now - 3600} for wid, protects in WATCHES]
    return {"enabled": True, "degraded": bool(down), "action": "notify", "since": now - 60 if down else None, "down": list(down), "watches": watches}


def health_pi(base_check="ok"):
    now = time.time()
    return {
        "updated_at": _iso(now), "uptime_s": 86400 * 3 + 4000,
        "cpu": {"temp_c": 51.2, "freq_mhz": 1500, "load": [0.42, 0.38, 0.35], "use_pct": 11.0},
        "throttled": {"raw": "0x0"}, "clock_synchronized": True,
        "wifi": {"connected": True, "ssid": "TALLER-DEV", "signal_pct": 78, "speed": "72 Mb/s", "channel": 6},
        "red": {"router_ms": 3, "meter_ms": 12, "camera": True},
        "services": [{"name": "G-code bridge", "unit": "workshop-gcode-bridge", "active": True, "state": "active", "since": _iso(now - 86400)}],
        "kiosk": True, "bridge_clients": 1, "bridge_programs": 1, "data": {"motors_s": 4},
        "duet": {"state": "idle", "firmware": "3.6.3", "mcu_temp_c": 38.0, "vin_v": 24.1, "boards": [{"name": "MB6HC", "can": 0, "state": "running", "firmware": "3.6.3"}]},
        "screens": {"sessions": 2, "origenes": ["kiosk", "pc"], "devices": [{"origin": "kiosk", "sessions": 1}, {"origin": "pc", "sessions": 1}], "status_per_min": 0},
        "reenvios_1h": 0, "restart": {"last_datum": _iso(now - 86400 * 3), "ordenado": True},
        "base": db_status(base_check), "disk": {"total_gb": 29.0, "free_gb": 18.4, "free_pct": 63.0}, "dcs": {"pid": 812, "fds": 41},
        "thresholds": {"temp_alert_c": 75, "temp_sustained_s": 120, "wifi_sustained_s": 120, "service_sustained_s": 60, "disk_alert_gb": 2, "disk_alert_pct": 10, "base_alert_mb": 200, "dcs_fds_alert": 400},
    }


def black_box(report=False, hidden=False):
    now = time.time()
    drop = {"last_datum": _iso(now - 9 * 3600).replace("T", " ")[:16], "detected": _iso(now - 8 * 3600), "file": "0:/sys/workshop/data/blackbox/unclean-report.txt", "seen": hidden}
    out = {"active": True, "interval_s": 5, "file_kb": 180, "folder": "0:/sys/workshop/data/blackbox", "report": None, "last_drop": drop if (report or hidden) else None}
    if report and not hidden:
        lines = ["%s state=processing job=part.nc cpu=41 temp=58" % _iso(now - 9 * 3600 + i * 5) for i in range(12)]
        out["report"] = {"detected": drop["detected"], "last_datum": drop["last_datum"], "boot_previous": "b-1041", "start_previous": _iso(now - 30 * 3600),
                         "lines": lines, "total_lines": 2890, "file": drop["file"], "seen": False}
    return out


def base(now=None):
    return {
        "guardStatus": guard_status(),
        "healthPi": health_pi(),
        "boxBlack": black_box(),
        "configGuard": {"state": "inactive", "snapshot": None, "tx": None, "deadline_s": 0, "expires": 0, "remaining_s": 0, "restart_seen": False, "startup_ok": True,
                        "failure": None, "waiting": None, "last": None},
        "riskActive": [],
        "liveJob": {"active": False, "name": None, "since": None, "file": None, "lastActivity": None, "deadlineMin": None},
        "jogFree": {"active": False, "mode": None, "color": None, "since": None, "remainingS": None, "timeoutS": 60},
        "jogBlock": {"reason": None, "confirm": False, "at": int(time.time())},
        "lastCode": "M5", "lastCodeTime": _iso(time.time() - 600),
    }


# every notice a test can switch on, one at a time: POST /__dev/published {"_notice": "name"} ; "_notice": "none" puts the base back
def _process(pid, text):
    return lambda b: b.unhealthy.__setitem__(pid, text)


NOTICES = {
    "none": lambda b: None,
    "process_error": _process("jobs", "it crashed: KeyError 'layer'"),
    "process_stopped": lambda b: b.stopped.add("trace"),
    "process_late": lambda b: b.late.add("consumption"),
    "safety_down": lambda b: b.bridge.set_status("guardStatus", guard_status(down=("guardian_laser",))),
    "vision_down": lambda b: b.bridge.set_status("guardStatus", guard_status(down=("vision",))),
    "database_damaged": lambda b: b.bridge.set_status("healthPi", health_pi(base_check="malformed page 12")),
    "unclean_shutdown": lambda b: b.bridge.set_status("boxBlack", black_box(report=True)),
    "unclean_shutdown_hidden": lambda b: b.bridge.set_status("boxBlack", black_box(report=True, hidden=True)),
    "channel_warning": lambda b: b.patch_published("communication", {"warning": "The jog shares the SBC channel with the service codes: a long job can delay it.",
                                                                     "notices": ["The Aux2 port is taken by a PanelDue."]}),
    "risk": lambda b: b.bridge.set_status("riskActive", [{"id": "laser_door", "text": {"key": "risk_laser_door_open", "params": {}}, "since": int(time.time() * 1000) - 60000, "auto": True}]),
    "live_job": lambda b: b.bridge.set_status("liveJob", {"active": True, "name": "", "since": _iso(time.time() - 900), "file": None, "lastActivity": _iso(time.time() - 20), "deadlineMin": 15}),
    "config_rollback_armed": lambda b: b.bridge.set_status("configGuard", {"state": "armed", "snapshot": "snap-20261117-1", "tx": "tx-1", "deadline_s": 300, "expires": int(time.time()) + 240,
                                                                            "remaining_s": 240, "restart_seen": False, "startup_ok": False, "failure": None, "waiting": "confirm", "last": None}),
    "wifi_weak": lambda b: b.patch_published("healthPi", {"wifi": {"connected": True, "ssid": "TALLER-DEV", "signal_pct": 18, "speed": "6 Mb/s", "channel": 6}}),
    "disk_low": lambda b: b.patch_published("healthPi", {"disk": {"total_gb": 29.0, "free_gb": 1.1, "free_pct": 3.8}}),
    "backup_late": lambda b: b.patch_published("healthPi", {"base": dict(db_status(), backup={"active": True, "late": True, "failures": ["no space left"], "last": {"date": _iso(time.time() - 4 * 86400)}})}),
}


def apply_notice(backend, name):
    if name not in NOTICES:
        raise ValueError("notice: one of " + ", ".join(sorted(NOTICES)))
    backend.heal()
    backend.publish_base()
    NOTICES[name](backend)
    backend.beat()
    return name
