"""API operations of the live job and the jobs: jobs.preview (jobs_preview.py). api_ops.init registers them through build(ctx),
like settings_ops. The class, arguments, role (permissions.py) and flags are the ones it had when it was handlers/jobs_view.py.
"""
import jobs_preview
from workshop_api import READ, Arg, Op


def _preview(args, c):
    return jobs_preview.preview(file=args["file"], max_vertices=args.get("max_vertices", 30000), mode=args.get("mode", ""))


def build(ctx):
    S, I = "str", "int"
    a = Arg
    return [
        Op("jobs.preview", _preview, READ,
           {"file": a(S, True, desc="G-code file under 0:/gcodes (for example Taller/frame.gcode)."),
            "max_vertices": a(I, min=2000, max=100000, default=30000, desc="Most vertices of the path that come back (the numbers are exact anyway)."),
            "mode": a(S, choices=("Laser", "CNC", "FFF"), desc="Mode used to read the file (default: the mode of the machine).")},
           "Reads a G-code file WITHOUT running it: the planned path in machine coordinates of the active work zone, estimated time, distances, feed range, pieces, layers, bounding box and the outline (convex hull) of what it works on.", log=False),
    ]
