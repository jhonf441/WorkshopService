"""capabilities.get: reads what discover() needs from the live machine and the SD.

Everything here is read only and tolerant: a missing file or a board that does
not answer gives a smaller answer, never an error. The object model comes from
the single subscription (machine_state); the LED strips are outside its filters,
so they are read with a short one-shot subscription and cached for a minute.
config.g (and the macros it calls) is read as text, only to count the M671 entries and find the G31 lines.
M115 and M122 are not sent from here (they cost board time); the firmware and
the boards come from the object model, which carries the same information.
"""
import json
import os
import re
import time

import capabilities
import config_scan
import paths

CACHE_S = 30
STRIPS_CACHE_S = 60
_cache = {"at": 0.0, "value": None}
_strips = {"at": 0.0, "value": None}


def _model():
    try:
        import machine_state
        return machine_state.get_status(timeout=2)
    except Exception:
        return None


def _led_strips():
    now = time.monotonic()
    if _strips["value"] is not None and now - _strips["at"] < STRIPS_CACHE_S:
        return _strips["value"]
    try:
        import machine_state
        got = machine_state.read_one_shot(["ledStrips.**"], timeout=3)
        value = got.get("ledStrips") if isinstance(got, dict) else None
    except Exception:
        return _strips["value"]
    _strips.update(at=now, value=value if isinstance(value, list) else [])
    return _strips["value"]


def sd_listing(sys_dir=None):
    """Files of sys/ that decide the modes, plus the markers of the workshop."""
    sys_dir = sys_dir or paths.SYS
    try:
        names = os.listdir(sys_dir)
    except OSError:
        names = []
    return {
        "mode_files": sorted(n for n in names if re.match(r"^mode.+\.g$", n, re.I)),
        "auto_mode": "automodeselect.g" in names,
        "config_g": "config.g" in names,
        "workshop_dir": os.path.isdir(os.path.join(sys_dir, "workshop")),
    }


def _cameras():
    try:
        with open(paths.CONFIG_DIR + "/cameras.json", encoding="utf-8") as f:
            data = json.load(f)
        return [c for c in (data or {}).get("cameras") or [] if isinstance(c, dict)]
    except Exception:
        return []


def _settings():
    try:
        import config_store
        return config_store.load_data() or {}
    except Exception:
        return {}


def _profile():
    try:
        import machine_profile
        return machine_profile.load()
    except Exception:
        return {}


def read_sd_text(path):
    """Text of a file of the SD ("0:/sys/config.g") or None; a file bigger than 400 kB is not read (it is not a configuration file)."""
    import sd_paths
    real = sd_paths.sd(path)
    try:
        if os.path.getsize(real) > config_scan.MAX_BYTES:
            return None
        with open(real, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def scan_config():
    """config.g and the macros it calls, scanned for M671 / G31 / M208 / M557 / M558 and bed.g (read only); {} when config.g is not there."""
    try:
        return config_scan.scan(read_sd_text)
    except Exception:  # noqa: BLE001 - discovery never fails because of a strange file
        return {}


def read_env(model=None):
    env = sd_listing()
    env.update(settings=_settings(), cameras=_cameras(), profile=_profile(), ledstrips=_led_strips() if model else None,
               config_scan=scan_config())
    return env


def get(force=False):
    """The capabilities of the machine now (cached 30 s; force=True reads again)."""
    now = time.monotonic()
    if not force and _cache["value"] is not None and now - _cache["at"] < CACHE_S:
        return _cache["value"]
    model = _model()
    value = capabilities.discover(model, read_env(model))
    value["generated_at"] = int(time.time())
    _cache.update(at=now, value=value)
    return value


def reset_cache():
    _cache.update(at=0.0, value=None)
    _strips.update(at=0.0, value=None)
