"""
audit_settings -- the settings of the activity record and the optional READ events (phase 4, PLAN-ACCESO.md 4.2 and 4.4).

They live with the other settings of the service, in the shared settings dict (service.json) under the key "audit":

    "audit": {
        "reads":  {"camera": false, "audit": false, "config": false},   # record who LOOKED (reads that succeed), by category; all OFF by default
        "read_sample": 10,        # of the reads of a category, one of every N is recorded (1 = all)
        "read_daily_cap": 200,    # at most this many read events per category and day (protects the SD card of the Pi)
        "alarms": {"access_damaged": true, "denial_burst": true, "sensitive_change": true, "chain_broken": true},   # each one can be switched off
        "burst_threshold": 8,     # refusals of one person inside burst_window_s that raise the alarm
        "burst_window_s": 60,
        "alarm_quiet_s": 21600    # the same alarm is not raised again for the same subject before this (6 h)
    }

Writes, movement, energy, people, access profiles, keys, sign-ins and every refusal are ALWAYS recorded: nothing here changes that. Only the reads that
succeed are optional, and only the ones of the three categories (the category of an operation comes from its capability: camera and config by the
category of the capability, audit by the capability security.audit). Sampling and the daily cap are applied by audit_reads.py.
"""
import copy

CATEGORIES = ("camera", "audit", "config")
ALARMS = ("access_damaged", "denial_burst", "sensitive_change", "chain_broken")
DEFAULTS = {
    "reads": {c: False for c in CATEGORIES},
    "read_sample": 10,
    "read_daily_cap": 200,
    "alarms": {a: True for a in ALARMS},
    "burst_threshold": 8,
    "burst_window_s": 60,
    "alarm_quiet_s": 21600,
}
LIMITS = {"read_sample": (1, 1000), "read_daily_cap": (1, 100000), "burst_threshold": (2, 1000), "burst_window_s": (5, 3600),
          "alarm_quiet_s": (60, 7 * 86400)}

_live = {}  # the shared settings dict (bind)


class SettingsInvalid(ValueError):
    pass


def bind(config):
    """Gives the module the shared settings dict (the live one: a change is seen at once)."""
    global _live
    _live = config if isinstance(config, dict) else {}


def get():
    """The settings now: the defaults with what the dict holds on top (a wrong value falls back to its default)."""
    raw = _live.get("audit") if isinstance(_live.get("audit"), dict) else {}
    out = copy.deepcopy(DEFAULTS)
    for k in ("reads", "alarms"):
        if isinstance(raw.get(k), dict):
            for name in out[k]:
                if isinstance(raw[k].get(name), bool):
                    out[k][name] = raw[k][name]
    for k, (lo, hi) in LIMITS.items():
        v = raw.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = v
    return out


def clean(changes):
    """Validates a change {key: value} (reads / alarms as {name: bool}); returns the cleaned change or raises SettingsInvalid."""
    out = {}
    for k, v in (changes or {}).items():
        if k in ("reads", "alarms"):
            names = CATEGORIES if k == "reads" else ALARMS
            if not isinstance(v, dict) or any(n not in names or not isinstance(b, bool) for n, b in v.items()):
                raise SettingsInvalid(k)
            out[k] = dict(v)
        elif k in LIMITS:
            lo, hi = LIMITS[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise SettingsInvalid(k)
            out[k] = v
        else:
            raise SettingsInvalid(k)
    return out


def apply(changes):
    """Writes a cleaned change into the live dict (merging reads / alarms). The caller saves the settings."""
    cur = _live.get("audit") if isinstance(_live.get("audit"), dict) else {}
    cur = copy.deepcopy(cur)
    for k, v in changes.items():
        if k in ("reads", "alarms"):
            cur[k] = dict(cur.get(k) if isinstance(cur.get(k), dict) else {}, **v)
        else:
            cur[k] = v
    _live["audit"] = cur
    return get()


def alarm_on(name):
    return bool(get()["alarms"].get(name, False))
