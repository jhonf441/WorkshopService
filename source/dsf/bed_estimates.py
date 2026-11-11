"""The optional data of the bed power estimate and the insulation test, kept in the service so every screen sees the same (pure validation).

    {"inputs": {"ambient", "target", "thickness", "density", "cp", "power", "minutes": number or null, "material": "" or a key, "cover": bool},
     "insulation": {"before": run or null, "after": run or null}}   run = {"zone": null (whole bed) or int, "at": epoch seconds, "fit": {tau, minutes, drop, room, roomGiven, rate}}

Everything is optional: an empty input is null. The page does the calculation (bed-zones-power.js / bed-zones-insulation.js); the service only keeps the
values and refuses nonsense. Nothing here reaches the heaters. Stage 1 of informes/recetas-temperatura-por-capa/DISENO.md.
"""
from messages import M

AREA = "bed-estimates"

MATERIALS = ("", "aluminium", "steel", "glass", "copper", "custom")
LIMITS = {"ambient": (-40, 80), "target": (0, 500), "thickness": (0.1, 100), "density": (100, 30000), "cp": (50, 5000), "power": (1, 20000), "minutes": (0.5, 1440)}
RUN_KEYS = {"tau": (0.01, 100000), "minutes": (0, 100000), "drop": (0, 1000), "room": (-100, 500), "rate": (0, 1000)}


class EstimatesError(Exception):
    """errors: [{"field", "message"}]"""

    def __init__(self, errors):
        super().__init__("; ".join(str(e["message"]) for e in errors))
        self.errors = errors


def _err(field, key, **params):
    return {"field": field, "message": M(key, field=field, **params)}


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v and abs(v) != float("inf") else None
    if isinstance(v, str):
        try:
            n = float(v.strip().replace(",", "."))
        except ValueError:
            return None
        return n if n == n and abs(n) != float("inf") else None
    return None


def _run(raw, field):
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("fit"), dict):
        raise EstimatesError([_err(field, "bed_estimates_err_run")])
    fit = raw["fit"]
    out = {}
    for k, (lo, hi) in RUN_KEYS.items():
        n = _number(fit.get(k))
        if n is None or not lo <= n <= hi:
            raise EstimatesError([_err(field + ".fit." + k, "bed_estimates_err_run")])
        out[k] = n
    zone = raw.get("zone")  # missing or null = the whole bed (the test of today); an int 0..63 is a run saved by an older page
    if zone is not None and (not isinstance(zone, int) or isinstance(zone, bool) or not 0 <= zone <= 63):
        raise EstimatesError([_err(field + ".zone", "bed_estimates_err_run")])
    at = _number(raw.get("at"))
    return {"zone": zone, "at": int(at) if at is not None and at >= 0 else 0, "fit": dict(out, roomGiven=bool(fit.get("roomGiven")))}


def validate(raw):
    """The value in its stored form, or EstimatesError with one message per problem. None / {} is an empty store."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise EstimatesError([_err("estimates", "bed_estimates_err_store")])
    errors = []
    src = raw.get("inputs") or {}
    inputs = {}
    if not isinstance(src, dict):
        errors.append(_err("inputs", "bed_estimates_err_store"))
        src = {}
    for key, (lo, hi) in LIMITS.items():
        v = src.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            inputs[key] = None
            continue
        n = _number(v)
        if n is None or not lo <= n <= hi:
            errors.append(_err("inputs." + key, "bed_estimates_err_input", min=lo, max=hi))
            inputs[key] = None
        else:
            inputs[key] = n
    material = src.get("material") or ""
    if material not in MATERIALS:
        errors.append(_err("inputs.material", "bed_estimates_err_material"))
        material = ""
    inputs["material"] = material
    inputs["cover"] = bool(src.get("cover"))
    ins = raw.get("insulation") or {}
    insulation = {}
    for kind in ("before", "after"):
        try:
            insulation[kind] = _run(ins.get(kind) if isinstance(ins, dict) else None, "insulation." + kind)
        except EstimatesError as e:
            errors.extend(e.errors)
            insulation[kind] = None
    if errors:
        raise EstimatesError(errors)
    return {"inputs": inputs, "insulation": insulation}
