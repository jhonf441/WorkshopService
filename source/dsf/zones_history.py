"""Retention of 0:/sys/workshop/zones/history, where the Workbench keeps a timestamped copy of every zone it replaces.

The page (src/_zones/23-zone-data-set-focus-line.js, tzDataBackupZone) writes `p<N>-<AAAAMMDD>-<HHMMSS>.g` before each change of a zone and
never removes any, so the folder grows without bound. The service applies the rule, per zone (the `p<N>` prefix):

  - the NEWEST copy of each zone is never deleted, whatever the limits say;
  - the `min_keep` newest copies of each zone are never deleted for age (a rarely edited zone keeps its few last versions);
  - beyond the `max_per_zone` newest copies a copy is deleted (a zone edited many times a day cannot fill the card);
  - a copy older than `max_age_days` (and not among the `min_keep` newest) is deleted.

Only files whose name has exactly that shape are looked at; anything else the person put there is left alone. The limits are the key
`zones_history` of the service settings {"enabled": true, "max_per_zone": 20, "max_age_days": 90, "min_keep": 3}; a value that is not a sane
number falls back to the default, and `enabled: false` turns the rule off. A file that cannot be deleted is skipped and reported, never fatal.
"""
import os
import re
import threading
import time
from datetime import datetime

import sd_paths

DIR = "sys/workshop/zones/history"
NAME_RE = re.compile(r"^(p\d+)-(\d{8})-(\d{6})\.g$")
DEFAULTS = {"enabled": True, "max_per_zone": 20, "max_age_days": 90, "min_keep": 3}
INTERVAL_S = 24 * 3600


def _int(value, default, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return default
    v = int(value)
    return v if low <= v <= high else default


def limits_of(cfg):
    """The limits of a settings value (any junk -> the defaults), with min_keep never above max_per_zone."""
    c = cfg if isinstance(cfg, dict) else {}
    out = {
        "enabled": c.get("enabled") is not False,
        "max_per_zone": _int(c.get("max_per_zone"), DEFAULTS["max_per_zone"], 1, 10000),
        "max_age_days": _int(c.get("max_age_days"), DEFAULTS["max_age_days"], 1, 36500),
        "min_keep": _int(c.get("min_keep"), DEFAULTS["min_keep"], 1, 10000),
    }
    out["min_keep"] = min(out["min_keep"], out["max_per_zone"])
    return out


def _stamp(m):
    try:
        return datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def plan(names, limits, now=None):
    """Names to delete out of the listing of the folder. Pure function: no file access."""
    now = now or datetime.now()
    zones = {}
    for n in names:
        m = NAME_RE.match(n)
        if not m:
            continue
        zones.setdefault(m.group(1), []).append((m.group(2) + m.group(3), n, _stamp(m)))
    doomed = []
    for items in zones.values():
        items.sort(reverse=True)  # newest first; the stamp sorts as text
        for rank, (_key, name, when) in enumerate(items):
            if rank == 0:
                continue  # the newest of a zone is never touched
            if rank >= limits["max_per_zone"]:
                doomed.append(name)
            elif rank >= limits["min_keep"] and when is not None and (now - when).days > limits["max_age_days"]:
                doomed.append(name)
    return sorted(doomed)


def prune(cfg=None, now=None, folder=None):
    """Applies the rule to the folder. Returns {"deleted": [...], "failed": [...], "kept": n}; never raises."""
    limits = limits_of(cfg)
    res = {"deleted": [], "failed": [], "kept": 0}
    if not limits["enabled"]:
        return res
    d = folder or sd_paths.sd(DIR)
    try:
        names = os.listdir(d)
    except OSError:
        return res
    for n in plan(names, limits, now):
        try:
            os.remove(os.path.join(d, n))
            res["deleted"].append(n)
        except OSError:
            res["failed"].append(n)
    res["kept"] = len([n for n in names if NAME_RE.match(n)]) - len(res["deleted"])
    return res


def launch(get_config, log=print):
    """Prunes now and then once a day, in a daemon thread. get_config() returns the service settings (read again each time)."""
    def run():
        while True:
            try:
                cfg = (get_config() or {}).get("zones_history")
                r = prune(cfg)
                if r["deleted"] or r["failed"]:
                    log(f"zones/history: {len(r['deleted'])} old copies deleted, {len(r['failed'])} could not be, {r['kept']} kept")
            except Exception as e:  # never takes the service down
                log(f"zones/history retention failed: {e}")
            time.sleep(INTERVAL_S)
    t = threading.Thread(target=run, name="zones-history-retention", daemon=True)
    t.start()
    return t
