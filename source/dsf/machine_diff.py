"""Pure comparison helpers of Machine v2 (phase 2): the value table of two records and the difference grid of two height maps.

diff_rows(a, b)      two dicts (the `results` or `inputs` of two records of the same kind) -> rows [{"key", "a", "b", "delta", "changed"}]
                     keys are dotted paths ("stats.stdev", "axes[0].delta"); a missing side is None; delta = b - a for two numbers.
mesh_diff(pa, pb)    two parsed height maps (machine_heightmap.parse_csv) of the SAME grid -> the grid b - a (null where either side was not probed)
                     and its statistics. A different grid is not resampled: {"ok": False, "reason": "grid_differs"}.
"""
import machine_heightmap as hm

MAX_ROWS = 300
MAX_LIST = 20          # a list longer than this is compared by its length only (the samples of a repeatability run)
_MISSING = object()


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def flatten(obj, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k in obj:
            flatten(obj[k], "%s.%s" % (prefix, k) if prefix else str(k), out)
    elif isinstance(obj, list):
        if len(obj) > MAX_LIST:
            out[prefix + ".length"] = len(obj)
        elif not obj:
            out[prefix] = []
        else:
            for i, v in enumerate(obj):
                flatten(v, "%s[%d]" % (prefix, i), out)
    else:
        out[prefix] = obj
    return out


def diff_rows(a, b):
    """{"rows": [...], "changed": n, "cut": bool}: the changed rows first, then the equal ones."""
    fa, fb = flatten(a or {}), flatten(b or {})
    rows = []
    for k in list(fa) + [k for k in fb if k not in fa]:
        va, vb = fa.get(k, _MISSING), fb.get(k, _MISSING)
        delta = round(vb - va, 6) if _is_num(va) and _is_num(vb) else None
        rows.append({"key": k, "a": None if va is _MISSING else va, "b": None if vb is _MISSING else vb, "delta": delta, "changed": va != vb})
    rows.sort(key=lambda r: not r["changed"])
    return {"rows": rows[:MAX_ROWS], "changed": sum(1 for r in rows if r["changed"]), "cut": len(rows) > MAX_ROWS}


def same_grid(ga, gb):
    keys = ("min0", "max0", "min1", "max1", "num0", "num1")
    return all(abs(ga[k] - gb[k]) < 1e-6 for k in keys)


def mesh_diff(pa, pb):
    if not (pa.get("ok") and pb.get("ok")):
        return {"ok": False, "reason": "unreadable"}
    if not same_grid(pa["grid"], pb["grid"]):
        return {"ok": False, "reason": "grid_differs", "a": pa["grid"], "b": pb["grid"]}
    rows = [[None if va is None or vb is None else round(vb - va, 4) for va, vb in zip(ra, rb)] for ra, rb in zip(pa["rows"], pb["rows"])]
    g = pa["grid"]
    parsed = {"ok": True, "grid": g, "rows": rows, "axes": pa["axes"]}
    return {"ok": True, "axes": pa["axes"], "grid": g, "rows": rows, "stats": hm.stats(parsed)}
