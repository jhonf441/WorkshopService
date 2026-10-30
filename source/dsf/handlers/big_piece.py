"""
Internal implementation of the API operation(s) bigpart.read, bigpart.counts, bigpart.marks, bigpart.part, bigpart.fit (api_ops.py maps their named
arguments to the one-letter parameters below).

Big piece assistant (see dsf/big_piece.py). Used by the Zones >
Big piece page (WorkshopJog, 48-large.js).

Usage: <params> S"leer"   J"<hex {archivo}>"
         -> summary; leaves the drawing in 0:/sys/workshop/data/big-part.json
     <params> S"cuentas" J"<hex {archivo, T, area, hechas}>"
     <params> S"marcas"  J"<hex {archivo, T, area, hechas, corr, pct, vel}>"
         -> chooses where the crosses go and writes 0:/sys/workshop/gcodes/big-part-marks.gcode
     <params> S"parte"   J"<hex {archivo, T, area, hechas, corr, n}>"
         -> writes 0:/sys/workshop/gcodes/big-part-piece.gcode
     <params> S"ajustar" J"<hex {diseno: [[x,y]..], cama: [[x,y]..]}>"
         -> rotation and translation measured with the marks
T = {rotation (degrees), tx, ty}: design -> bed. area = {xmin, xmax, ymin, ymax}
(bed). hechas = [T of each part already cut]. corr = [x, y] of the laser.
None of this moves the machine: the jobs are started by the page (M32).

"""
import json

import big_piece as pg
from messages import M

MARKS = "sys/workshop/gcodes/big-part-marks.gcode"
PART = "sys/workshop/gcodes/big-part-piece.gcode"


def run(params, bridge, config):
    action = str(params.get("S", "")).strip().lower()
    try:
        j = params.get("J")
        b = j if isinstance(j, dict) else json.loads(bytes.fromhex(str(j or "7b7d")).decode("utf-8"))
    except Exception:
        return json.dumps({"ok": False, "error": M("big_piece_j_must_be_hex_json")})
    try:
        if action == "read":
            return json.dumps(dict(pg.preview(b["file"]), ok=True, preview="0:/" + pg.PREVIEW))
        if action == "adjust":
            return json.dumps(dict(pg.adjust(b["design"], b["bed"]), ok=True))
        T, area, done = b.get("T") or {}, b.get("area"), b.get("done") or []
        if not area:
            return json.dumps({"ok": False, "error": M("big_piece_cut_area_missing_measure_zones_cut")})
        if action == "counts":
            return json.dumps(dict(pg.counts(b["file"], T, area, done), ok=True))
        if action == "marks":
            r = pg.choose_marks(b["file"], T, area, done)
            if not r["ok"]:
                return json.dumps(r)
            pct = max(1.0, min(30.0, float(b.get("pct") or 8)))
            velocity = max(100, min(6000, int(b.get("speed") or 800)))
            g = pg.generate_marks(r["marks"], T, b["correction"], pct, velocity, MARKS)
            return json.dumps(dict(g, marks=r["marks"], ok=True, file="0:/" + MARKS))
        if action == "part":
            r = pg.generate_part(b["file"], T, area, done, b["correction"], PART, int(b.get("n") or 1))
            if r.get("ok"):
                r["file"] = "0:/" + PART
            return json.dumps(r)
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": M("big_piece_file_does_not_exist", file=str(b.get("file")))})
    except (ValueError, KeyError) as e:
        return json.dumps({"ok": False, "error": str(e)})
    return "Error: unknown big part action"
