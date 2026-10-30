"""Declared profile of the machine (F2, 2026-10-21): sys/workshop/config/machine.json.

What the board can tell (axes, probe, modes...) is discovered by capabilities.py;
this file holds what only the owner can say: the name of the machine, language,
currency, which meter and shutdown method it uses, which macro plays which role,
which probe to use, which axis index is X/Y/Z and what must NOT be used even if it
is there. Defaults are generic: a fresh machine with only a config.g gets a valid
profile that assumes nothing from the original workshop.

Schema (version 3):
    schema            int, always first
    name              text shown as the machine name ("" = not named)
    language          "" (follow DWC) | "es" | "en"
    currency          "" (the page falls back to the DWC language) | ISO-like code, 1-8 chars
    meter             {"kind": "none"|"tuya"|<other text>, "params": {...}}
    shutdown          {"method": "none"|"software"|"relay"|"tuya", "params": {...}}
    macros            {role: "0:/path.g" | null}   roles: focus home light air shutdown park
    probe             {"index": int|null}          null = the first probe the board reports
    axis_index        {"X": int|null, "Y": int|null, "Z": int|null}   null = look the letter up
    capability_overrides  {capability: bool}       false = do not use it, true = declared present
    mode_policies     {mode: {"enabled": bool, "min_role": "viewer"|"operator"|"technician"|"admin"|null}}
    interlocks        {lid|extraction|key: {"gpin": int|null, "active_when": "high"|"low", "label": text}}   (schema 2)
                      optional laser interlocks read from a Duet general purpose input (sensors.gpIn[gpin]);
                      active_when is the level of the input at which the interlock is satisfied (closed / on);
                      gpin null = not declared. Used by interlocks.py (safety.status, laser refusals).
    machine           Machine v2 (schema 3, design section 6.2). EVERYTHING is optional: the defaults below work with a plain config.g.
                      The numbers marked (guess) are starting values to tune, not facts of any machine.
        probe             {"index": int|null (null = the top level probe.index), "deploy": "auto"|"macro"|"none",
                           "deploy_macro": path|null, "retract_macro": path|null}
        levelling         {"z_leadscrew_pitch": mm|null, "probe_points": [[x, y], ...]|null (2-16 points), "max_passes": 1-20 (5, guess),
                           "tolerance_mm": 0.001-1 (0.02, guess)}
        mesh              {"default_points": [nx, ny] (2-30 each, [5, 5]), "default_probe_index": int|null,
                           "quality": {"warn_range_mm": 0.2 (guess), "bad_range_mm": 0.5 (guess)}}
        thresholds        {"probe_sigma_warn": mm (0.02, guess), "probe_sigma_bad": mm (0.05, guess)}   repeatability verdicts
        secondary_tool_pair  null | {"laser_tool": int, "pointer_tool": int}      laser <-> pointer assistant
        config_files      {"extra": [path.g, ...]}  up to 8 files besides config.g / bed.g where G31 / G10 / M671 lines may live
        maintenance       [{"id", "label", "axis": letter|null, "every_hours"|"every_km"|"every_days": number,
                          "hours_basis"?: "power_on"|"moving" (every_hours only; default power_on)}, ...]  up to 40.
                          Empty = the generic default plan of machine_maintenance.py until the owner edits it (machine.maintenance.plan.set)
        safety            {"max_probe_descent_mm": 1-200 (25, guess), "max_points_per_run": 1-500 (100, guess),
                           "max_current_ma": 100-6300 (2800, guess): the highest motor current M906 may be set to by Machine (plan or trial)}

Suggested permission level (the role table is F1-A's): profile.get = viewer,
profile.set = technician or admin.

A profile with any other `schema` is refused (it is never rewritten); a missing `schema` is read as the current one.

Saving: atomic (temp file + fsync + replace) and the previous healthy file stays
as machine.json.bak. NOTE: the shared settings_store of the f1-cfg branch is not in
master yet; when it is, save() should call it and this local writer can go.
"""
import copy
import json
import os
import re
import shutil

import paths
from messages import M

SCHEMA = 3
FILE = paths.CONFIG_DIR + "/machine.json"
MACRO_ROLES = ("focus", "home", "light", "air", "shutdown", "park")
DEFAULT_MACROS = {
    "focus": "0:/macros/focus.g", "home": "0:/sys/homeall.g", "light": "0:/macros/light.g",
    "air": "0:/macros/air.g", "shutdown": "0:/macros/shutdown.g", "park": "0:/macros/park.g",
}
METER_KINDS_KNOWN = ("none", "tuya")
SHUTDOWN_METHODS = ("none", "software", "relay", "tuya")
LANGUAGES = ("", "es", "en")
ROLES = ("viewer", "operator", "technician", "admin")
AXIS_LETTERS = ("X", "Y", "Z")
INTERLOCK_NAMES = ("lid", "extraction", "key")
LEVELS = ("high", "low")
DEPLOY_MODES = ("auto", "macro", "none")
MACHINE_AXES = ("X", "Y", "Z", "U", "V", "W", "A", "B", "C")
CURRENT_CEILING_MA = 6300         # hard ceiling of the motor current Machine will ever set (the rating of a MB6HC driver); no profile can raise it
DEFAULT_CURRENT_CAP_MA = 2800     # guess: the default cap of the profile (a NEMA 23 motor); the administrator lowers or raises it up to the ceiling
MACHINE_KEYS = ("probe", "levelling", "mesh", "thresholds", "secondary_tool_pair", "config_files", "maintenance", "safety")
MAINTENANCE_INTERVALS = ("every_hours", "every_km", "every_days")
HOURS_BASES = ("power_on", "moving")
MAX_MAINTENANCE = 40
MAX_EXTRA_FILES = 8


class ProfileError(ValueError):
    """Invalid profile: .errors is a list of {"field", "message"} (message is an M())."""

    def __init__(self, errors):
        super().__init__("; ".join("%s: %s" % (e["field"], e["message"]) for e in errors))
        self.errors = errors


def defaults():
    return {
        "schema": SCHEMA, "name": "", "language": "", "currency": "",
        "meter": {"kind": "none", "params": {}},
        "shutdown": {"method": "none", "params": {}},
        "macros": dict(DEFAULT_MACROS),
        "probe": {"index": None},
        "axis_index": {"X": None, "Y": None, "Z": None},
        "capability_overrides": {},
        "mode_policies": {},
        "interlocks": default_interlocks(),
        "machine": default_machine(),
    }


def default_machine():
    """Machine v2 block: generic defaults, nothing assumed from any workshop. The numbers are starting values (guesses) to tune."""
    return {
        "probe": {"index": None, "deploy": "auto", "deploy_macro": None, "retract_macro": None},
        "levelling": {"z_leadscrew_pitch": None, "probe_points": None, "max_passes": 5, "tolerance_mm": 0.02},
        "mesh": {"default_points": [5, 5], "default_probe_index": None, "quality": {"warn_range_mm": 0.2, "bad_range_mm": 0.5}},
        "thresholds": {"probe_sigma_warn": 0.02, "probe_sigma_bad": 0.05},
        "secondary_tool_pair": None,
        "config_files": {"extra": []},
        "maintenance": [],
        "safety": {"max_probe_descent_mm": 25.0, "max_points_per_run": 100, "max_current_ma": DEFAULT_CURRENT_CAP_MA},
    }


def default_interlocks():
    return {n: {"gpin": None, "active_when": "high", "label": ""} for n in INTERLOCK_NAMES}


# ---- validation ----

def _err(field, key, **params):
    return {"field": field, "message": M(key, field=field, **params)}


def _text(p, key, limit, errors, out):
    v = p.get(key, out[key])
    if v is None:
        v = ""
    if not isinstance(v, str) or len(v.strip()) > limit:
        errors.append(_err(key, "profile_err_text", limit=limit))
        return
    out[key] = v.strip()


def _kind_block(p, key, kinds, errors, out, strict):
    v = p.get(key)
    if v is None:
        return
    if not isinstance(v, dict):
        errors.append(_err(key, "profile_err_object"))
        return
    name = "kind" if key == "meter" else "method"
    val = v.get(name, out[key][name])
    ok = isinstance(val, str) and re.match(r"^[a-z0-9_-]{1,24}$", val) and (not strict or val in kinds)
    if not ok:
        errors.append(_err(key + "." + name, "profile_err_choice", allowed=", ".join(kinds)))
        return
    params = v.get("params", {})
    if not isinstance(params, dict):
        errors.append(_err(key + ".params", "profile_err_object"))
        return
    out[key] = {name: val, "params": copy.deepcopy(params)}


def _macros(p, errors, out):
    v = p.get("macros")
    if v is None:
        return
    if not isinstance(v, dict):
        errors.append(_err("macros", "profile_err_object"))
        return
    for role, path in v.items():
        if role not in MACRO_ROLES:
            errors.append(_err("macros." + str(role), "profile_err_macro_role", allowed=", ".join(MACRO_ROLES)))
        elif path is None:
            out["macros"][role] = None
        elif not (isinstance(path, str) and re.match(r"^(\d+:)?/[^\0]{1,200}\.g$", path) and ".." not in path):
            errors.append(_err("macros." + role, "profile_err_macro_path"))
        else:
            out["macros"][role] = path


def _int_or_none(v, lo, hi):
    return v is None or (isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi)


def _indexes(p, errors, out):
    pr = p.get("probe")
    if pr is not None:
        if isinstance(pr, dict) and _int_or_none(pr.get("index"), 0, 15):
            out["probe"] = {"index": pr.get("index")}
        else:
            errors.append(_err("probe.index", "profile_err_index"))
    ax = p.get("axis_index")
    if ax is not None:
        if not isinstance(ax, dict):
            errors.append(_err("axis_index", "profile_err_object"))
            return
        for letter, idx in ax.items():
            if letter not in AXIS_LETTERS or not _int_or_none(idx, 0, 24):
                errors.append(_err("axis_index." + str(letter), "profile_err_index"))
            else:
                out["axis_index"][letter] = idx


def _overrides(p, errors, out):
    v = p.get("capability_overrides")
    if v is None:
        return
    if not isinstance(v, dict):
        errors.append(_err("capability_overrides", "profile_err_object"))
        return
    for name, flag in v.items():
        if not re.match(r"^[a-z][a-z0-9_]{0,31}$", str(name)) or not isinstance(flag, bool):
            errors.append(_err("capability_overrides." + str(name), "profile_err_bool"))
        else:
            out["capability_overrides"][name] = flag


def _policies(p, errors, out):
    v = p.get("mode_policies")
    if v is None:
        return
    if not isinstance(v, dict):
        errors.append(_err("mode_policies", "profile_err_object"))
        return
    for mode, pol in v.items():
        f = "mode_policies." + str(mode)
        if not isinstance(pol, dict) or not re.match(r"^[A-Za-z0-9_-]{1,24}$", str(mode)):
            errors.append(_err(f, "profile_err_object"))
            continue
        enabled, role = pol.get("enabled", True), pol.get("min_role")
        if not isinstance(enabled, bool) or (role is not None and role not in ROLES):
            errors.append(_err(f, "profile_err_policy", allowed=", ".join(ROLES)))
            continue
        out["mode_policies"][mode] = {"enabled": enabled, "min_role": role}


def _interlocks(p, errors, out):
    v = p.get("interlocks")
    if v is None:
        return
    if not isinstance(v, dict):
        errors.append(_err("interlocks", "profile_err_object"))
        return
    for name, item in v.items():
        f = "interlocks." + str(name)
        if name not in INTERLOCK_NAMES or not isinstance(item, dict):
            errors.append(_err(f, "profile_err_interlock", allowed=", ".join(INTERLOCK_NAMES)))
            continue
        cur = out["interlocks"][name]
        gpin, level, label = item.get("gpin", cur["gpin"]), item.get("active_when", cur["active_when"]), item.get("label", cur["label"])
        if not _int_or_none(gpin, 0, 31) or level not in LEVELS or not isinstance(label, str) or len(label.strip()) > 40                 or set(item) - {"gpin", "active_when", "label"}:
            errors.append(_err(f, "profile_err_interlock", allowed=", ".join(INTERLOCK_NAMES)))
            continue
        out["interlocks"][name] = {"gpin": gpin, "active_when": level, "label": label.strip()}


# ---- machine block (schema 3) ----

def _num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi and v == v


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _macro_path(v):
    return v is None or (isinstance(v, str) and re.match(r"^(\d+:)?/[^\0]{1,200}\.g$", v) is not None and ".." not in v)


def _only(item, allowed, field, errors):
    """The object has no keys besides `allowed` (a typo must not be saved in silence)."""
    extra = sorted(set(item) - set(allowed))
    if extra:
        errors.append(_err(field + "." + extra[0], "profile_err_unknown_field", allowed=", ".join(allowed)))
        return False
    return True


def _block(v, cur, field, errors):
    """v is an object whose keys are all known (the keys of `cur`)."""
    if not isinstance(v, dict):
        errors.append(_err(field, "profile_err_object"))
        return False
    return _only(v, cur, field, errors)


def _m_probe(v, cur, errors):
    f = "machine.probe"
    if not _block(v, cur, f, errors):
        return cur
    out = dict(cur, **v)
    if not _int_or_none(out["index"], 0, 15):
        errors.append(_err(f + ".index", "profile_err_index"))
    if out["deploy"] not in DEPLOY_MODES:
        errors.append(_err(f + ".deploy", "profile_err_choice", allowed=", ".join(DEPLOY_MODES)))
    for k in ("deploy_macro", "retract_macro"):
        if not _macro_path(out[k]):
            errors.append(_err(f + "." + k, "profile_err_macro_path"))
    if out["deploy"] == "macro" and not (out["deploy_macro"] and out["retract_macro"]):
        errors.append(_err(f + ".deploy", "profile_err_deploy_macros"))
    return out


def _m_points(v, field, errors):
    ok = isinstance(v, list) and 2 <= len(v) <= 16 and all(
        isinstance(p, list) and len(p) == 2 and all(_num(c, -10000, 10000) for c in p) for p in v)
    if not ok:
        errors.append(_err(field, "profile_err_points"))
    return v


def _m_levelling(v, cur, errors):
    f = "machine.levelling"
    if not _block(v, cur, f, errors):
        return cur
    out = dict(cur, **v)
    if out["z_leadscrew_pitch"] is not None and not _num(out["z_leadscrew_pitch"], 0.01, 100):
        errors.append(_err(f + ".z_leadscrew_pitch", "profile_err_number", lo=0.01, hi=100))
    if out["probe_points"] is not None:
        _m_points(out["probe_points"], f + ".probe_points", errors)
    if not _int(out["max_passes"], 1, 20):
        errors.append(_err(f + ".max_passes", "profile_err_number", lo=1, hi=20))
    if not _num(out["tolerance_mm"], 0.001, 1):
        errors.append(_err(f + ".tolerance_mm", "profile_err_number", lo=0.001, hi=1))
    return out


def _m_mesh(v, cur, errors):
    f = "machine.mesh"
    if not _block(v, cur, f, errors):
        return cur
    out = dict(cur, **v)
    pts = out["default_points"]
    if not (isinstance(pts, list) and len(pts) == 2 and all(_int(n, 2, 30) for n in pts)):
        errors.append(_err(f + ".default_points", "profile_err_number", lo=2, hi=30))
    if not _int_or_none(out["default_probe_index"], 0, 15):
        errors.append(_err(f + ".default_probe_index", "profile_err_index"))
    q = out["quality"]
    if not _block(q, cur["quality"], f + ".quality", errors):
        return dict(out, quality=cur["quality"])
    q = dict(cur["quality"], **q)
    if not (_num(q["warn_range_mm"], 0.001, 10) and _num(q["bad_range_mm"], 0.001, 10)):
        errors.append(_err(f + ".quality", "profile_err_number", lo=0.001, hi=10))
    elif q["warn_range_mm"] > q["bad_range_mm"]:
        errors.append(_err(f + ".quality", "profile_err_order"))
    return dict(out, quality=q)


def _m_thresholds(v, cur, errors):
    f = "machine.thresholds"
    if not _block(v, cur, f, errors):
        return cur
    out = dict(cur, **v)
    if not (_num(out["probe_sigma_warn"], 0.0001, 5) and _num(out["probe_sigma_bad"], 0.0001, 5)):
        errors.append(_err(f, "profile_err_number", lo=0.0001, hi=5))
    elif out["probe_sigma_warn"] > out["probe_sigma_bad"]:
        errors.append(_err(f, "profile_err_order"))
    return out


def _m_pair(v, errors):
    f = "machine.secondary_tool_pair"
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) != {"laser_tool", "pointer_tool"} or not all(_int(v[k], 0, 31) for k in v) \
            or v["laser_tool"] == v["pointer_tool"]:
        errors.append(_err(f, "profile_err_tool_pair"))
        return None
    return {"laser_tool": v["laser_tool"], "pointer_tool": v["pointer_tool"]}


def _m_files(v, errors):
    f = "machine.config_files"
    extra = v.get("extra") if isinstance(v, dict) else None
    if not isinstance(extra, list) or len(extra) > MAX_EXTRA_FILES or set(v) - {"extra"} \
            or not all(isinstance(x, str) and _macro_path(x) for x in extra):
        errors.append(_err(f, "profile_err_files", limit=MAX_EXTRA_FILES))
        return {"extra": []}
    return {"extra": list(dict.fromkeys(extra))}


def _m_maintenance(v, errors):
    f = "machine.maintenance"
    if not isinstance(v, list) or len(v) > MAX_MAINTENANCE:
        errors.append(_err(f, "profile_err_maintenance", limit=MAX_MAINTENANCE))
        return []
    out, seen = [], set()
    for i, item in enumerate(v):
        g = "%s[%d]" % (f, i)
        keys = ("id", "label", "axis", "hours_basis") + MAINTENANCE_INTERVALS
        ok = isinstance(item, dict) and not set(item) - set(keys) and re.match(r"^[a-z][a-z0-9_.-]{0,39}$", str(item.get("id"))) \
            and item["id"] not in seen and isinstance(item.get("label", ""), str) and len(item.get("label", "")) <= 80 \
            and item.get("axis") in (None,) + MACHINE_AXES \
            and sum(k in item for k in MAINTENANCE_INTERVALS) == 1 \
            and item.get("hours_basis", "power_on") in HOURS_BASES and ("hours_basis" not in item or "every_hours" in item) \
            and all(_num(item[k], 0.01, 1000000) for k in MAINTENANCE_INTERVALS if k in item)
        if not ok:
            errors.append(_err(g, "profile_err_maintenance", limit=MAX_MAINTENANCE))
            continue
        seen.add(item["id"])
        interval = next(k for k in MAINTENANCE_INTERVALS if k in item)
        row = {"id": item["id"], "label": item.get("label", ""), "axis": item.get("axis"), interval: item[interval]}
        if "hours_basis" in item:
            row["hours_basis"] = item["hours_basis"]
        out.append(row)
    return out


def _m_safety(v, cur, errors):
    f = "machine.safety"
    if not _block(v, cur, f, errors):
        return cur
    out = dict(cur, **v)
    if not _num(out["max_probe_descent_mm"], 1, 200):
        errors.append(_err(f + ".max_probe_descent_mm", "profile_err_number", lo=1, hi=200))
    if not _int(out["max_points_per_run"], 1, 500):
        errors.append(_err(f + ".max_points_per_run", "profile_err_number", lo=1, hi=500))
    if not _int(out["max_current_ma"], 100, CURRENT_CEILING_MA):
        errors.append(_err(f + ".max_current_ma", "profile_err_number", lo=100, hi=CURRENT_CEILING_MA))
    return out


def current_cap(machine_block):
    """The highest M906 current (mA) Machine may set: the profile's cap, never above the hard ceiling (a damaged value falls back to the default)."""
    v = ((machine_block or {}).get("safety") or {}).get("max_current_ma")
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and 100 <= v
    return int(min(v, CURRENT_CEILING_MA)) if ok else DEFAULT_CURRENT_CAP_MA


def _machine(p, errors, out):
    v = p.get("machine")
    if v is None:
        return
    if not isinstance(v, dict):
        errors.append(_err("machine", "profile_err_object"))
        return
    if not _only(v, MACHINE_KEYS, "machine", errors):
        return
    cur = out["machine"]
    for key in v:
        if key == "probe":
            cur[key] = _m_probe(v[key], cur[key], errors)
        elif key == "levelling":
            cur[key] = _m_levelling(v[key], cur[key], errors)
        elif key == "mesh":
            cur[key] = _m_mesh(v[key], cur[key], errors)
        elif key == "thresholds":
            cur[key] = _m_thresholds(v[key], cur[key], errors)
        elif key == "secondary_tool_pair":
            cur[key] = _m_pair(v[key], errors)
        elif key == "config_files":
            cur[key] = _m_files(v[key], errors)
        elif key == "maintenance":
            cur[key] = _m_maintenance(v[key], errors)
        else:
            cur[key] = _m_safety(v[key], cur[key], errors)


def validate(raw, strict_kinds=False):
    """Profile -> clean profile with defaults filled in. ProfileError with
    every problem found. strict_kinds=True refuses meter kinds / shutdown methods this version does not know."""
    p = raw if isinstance(raw, dict) else {}
    errors, out = [], defaults()
    v = p.get("schema", SCHEMA)
    if isinstance(v, bool) or v != SCHEMA:
        errors.append(_err("schema", "profile_err_schema_unsupported", found=v, known=SCHEMA))
    _text(p, "name", 60, errors, out)
    _text(p, "currency", 8, errors, out)
    if p.get("language", "") not in LANGUAGES:
        errors.append(_err("language", "profile_err_choice", allowed="es, en"))
    else:
        out["language"] = p.get("language", "")
    _kind_block(p, "meter", METER_KINDS_KNOWN, errors, out, False)
    _kind_block(p, "shutdown", SHUTDOWN_METHODS, errors, out, True)
    _macros(p, errors, out)
    _indexes(p, errors, out)
    _overrides(p, errors, out)
    _policies(p, errors, out)
    _interlocks(p, errors, out)
    _machine(p, errors, out)
    if errors:
        raise ProfileError(errors)
    return out


# ---- disk ----

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load(path=None):
    """The saved profile, valid; defaults when there is none or it cannot be read."""
    path = path or FILE
    raw = _read(path)
    if raw is None:
        raw = _read(path + ".bak")
    if raw is None:
        return defaults()
    try:
        return validate(raw)
    except ProfileError:
        return defaults()


def save(profile, path=None):
    """Validates and writes atomically; returns the saved profile."""
    path = path or FILE
    clean = validate(profile)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    if _read(path) is not None:
        shutil.copy2(path, path + ".bak")
    os.replace(tmp, path)
    return clean


def merge(current, changes):
    """Top-level merge of a partial change into the current profile (objects are replaced whole,
    except macros, axis_index, capability_overrides, mode_policies, interlocks and machine, which are merged by key)."""
    out = copy.deepcopy(current)
    for key, val in (changes or {}).items():
        if key in ("macros", "axis_index", "capability_overrides", "mode_policies", "interlocks", "machine") and isinstance(val, dict) \
                and isinstance(out.get(key), dict):
            out[key].update(val)
        else:
            out[key] = val
    return out


# ---- resolved view ----

def resolve_macros(profile, exists=None):
    """{role: path or None}: the declared path, or the generic default, and None if the file is not there.
    exists(path) -> bool; by default it looks at the SD."""
    from sd_paths import sd
    exists = exists or (lambda p: os.path.isfile(sd(p)))
    out = {}
    for role in MACRO_ROLES:
        path = (profile.get("macros") or {}).get(role)
        out[role] = path if path and exists(path) else None
    return out


def axis_indexes(profile, caps):
    """{X: idx|None, ...}: declared index, else the position of that letter on the board. Never assumes axes[0..2]."""
    found = ((caps.get("capabilities") or {}).get("axes") or {}).get("index_of") or {}
    declared = profile.get("axis_index") or {}
    return {letter: declared.get(letter) if declared.get(letter) is not None else found.get(letter)
            for letter in AXIS_LETTERS}


def public_view(profile, caps=None):
    """What profile.get answers."""
    view = {"profile": profile, "schema": SCHEMA, "roles": list(MACRO_ROLES),
            "resolved_macros": resolve_macros(profile)}
    if caps is not None:
        view["axis_indexes"] = axis_indexes(profile, caps)
    return view
