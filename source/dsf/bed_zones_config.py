"""Configuration of the bed zones: defaults, strict validation and the load the interceptor trusts.

Stored in the settings area "bed-zones" (0:/sys/workshop/config/bed-zones.json, settings_store.py: revision, .bak, atomic write), the
same mechanism of every other area. Whoever writes it (settings.set of the page) is not trusted: the interceptor validates what it reads
and, when the file is not valid, behaves as if the feature were off (every M140 / M190 goes through to the firmware untouched).

`enabled` is False until somebody turns it on, so installing the service changes nothing on a machine.
"""
import copy

import settings_store
from messages import M

import bed_zones

AREA = "bed-zones"
MAX_TEMP_LIMIT = 200.0     # no setpoint above this is ever accepted, whatever the user types
MAX_OFFSET_LIMIT = 30.0
MAX_TIMEOUT_S = 3600.0
MAX_BED = 31               # RRF bed heater slots
LAYOUT_MAX = 4             # rows / columns of the map
MAX_ZONES = LAYOUT_MAX * LAYOUT_MAX  # what the map draws; how many beds the BOARD supports (limits.bedHeaters) is checked by the page, a zone of a missing bed is flagged


def defaults():
    out = copy.deepcopy(bed_zones.DEFAULTS)
    out["enabled"] = False
    out["layout"] = {"rows": 2, "columns": 2}
    return out


class ConfigError(Exception):
    """errors: [{"field", "message"}], every problem found."""

    def __init__(self, errors):
        super().__init__("; ".join(str(e["message"]) for e in errors))
        self.errors = errors


def _err(field, key, **params):
    return {"field": field, "message": M(key, field=field, **params)}


def _num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and lo <= v <= hi


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _zones(raw, errors):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ZONES:
        errors.append(_err("zones", "bed_zones_err_zone_count", max=MAX_ZONES))
        return None
    out, seen = [], set()
    for i, z in enumerate(raw):
        field = f"zones[{i}]"
        if not isinstance(z, dict):
            errors.append(_err(field, "bed_zones_err_zone"))
            continue
        bed = z.get("bed")
        if not _int(bed, 0, MAX_BED) or bed in seen:
            errors.append(_err(field + ".bed", "bed_zones_err_bed", max=MAX_BED))
            continue
        seen.add(bed)
        active = z.get("active", True)
        offset = z.get("offset", 0.0)
        if not isinstance(active, bool):
            errors.append(_err(field + ".active", "bed_zones_err_flag"))
            continue
        if not _num(offset, -MAX_OFFSET_LIMIT, MAX_OFFSET_LIMIT):
            errors.append(_err(field + ".offset", "bed_zones_err_number", lo=-MAX_OFFSET_LIMIT, hi=MAX_OFFSET_LIMIT))
            continue
        out.append({"bed": bed, "active": active, "offset": float(offset)})
    return out


def validate(raw):
    """Raw value -> clean config with defaults filled in, or ConfigError with every problem found."""
    p = raw if isinstance(raw, dict) else {}
    errors, out = [], defaults()
    if "enabled" in p:
        if isinstance(p["enabled"], bool):
            out["enabled"] = p["enabled"]
        else:
            errors.append(_err("enabled", "bed_zones_err_flag"))
    if "zones" in p:
        zones = _zones(p["zones"], errors)
        if zones is not None:
            out["zones"] = zones
    for key, hi in (("max_temp", MAX_TEMP_LIMIT), ("max_offset", MAX_OFFSET_LIMIT), ("tolerance", 20.0), ("timeout_s", MAX_TIMEOUT_S)):
        if key in p:
            if _num(p[key], 0.5 if key == "tolerance" else 1, hi):
                out[key] = float(p[key])
            else:
                errors.append(_err(key, "bed_zones_err_number", lo=0.5 if key == "tolerance" else 1, hi=hi))
    layout = p.get("layout", out["layout"])
    if isinstance(layout, dict) and _int(layout.get("rows"), 1, LAYOUT_MAX) and _int(layout.get("columns"), 1, LAYOUT_MAX):
        out["layout"] = {"rows": layout["rows"], "columns": layout["columns"]}
    else:
        errors.append(_err("layout", "bed_zones_err_layout", max=LAYOUT_MAX))
    if not errors and len(out["zones"]) > out["layout"]["rows"] * out["layout"]["columns"]:
        errors.append(_err("layout", "bed_zones_err_layout_small"))
    if not errors and any(abs(z["offset"]) > out["max_offset"] for z in out["zones"]):
        errors.append(_err("max_offset", "bed_zones_err_offset_over_limit"))
    if errors:
        raise ConfigError(errors)
    return out


def load():
    """(config, problem). The saved config when it is valid; defaults (feature off) when there is none or it is not valid, with the
    reason in `problem` (a ConfigError) so the caller can say it."""
    value = settings_store.get(AREA)["value"]
    if value is None:
        return defaults(), None
    try:
        return validate(value), None
    except ConfigError as e:
        off = defaults()
        off["enabled"] = False
        return off, e


def for_logic(config):
    """The part bed_zones.py needs."""
    return {k: config[k] for k in ("zones", "max_temp", "max_offset", "tolerance", "timeout_s")}
