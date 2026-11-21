"""job_layer_rules -- what the Printing page "Job in progress" shows about the layer rules armed for the file (pure: no I/O, no service import).

Two things can be armed for a job file, both in memory only (a service restart disarms them, nothing is saved):
a pellet temperature profile (pelletlayers.arm) and a temperature-by-layer recipe (layerrecipes.arm). Each run module gives `armed_info()`:
{"name", "file", "rules", "at"}; `rules` = how many layer points (changes by layer) the profile or recipe holds. `build` puts them in ONE published value:

    jobLayerRules = {
        "armed":   bool,            # something is armed for a file now
        "file":    str,             # the file of the first armed item ("" when none)
        "profile": str,             # its name: the pellet profile when one is armed, else the recipe ("" when none)
        "rules":   int,             # the layer points of ALL that is armed (0 when none)
        "at":      int,             # epoch seconds when the first armed item was armed (0 when none)
        "survivesRestart": False,   # always false: a restart of the service disarms them
        "entries": [{"kind": "pellet" | "recipe", "name", "file", "rules", "at"}, ...]   # one per armed item (pellet first)
    }

Read only. Published every pass of the run loop (pellet_layers_run.run_loop) under the plugin data key `jobLayerRules`.
"""

KEY = "jobLayerRules"


def _entry(kind, info):
    return {"kind": kind, "name": str(info.get("name") or ""), "file": str(info.get("file") or ""), "rules": int(info.get("rules") or 0),
            "at": int(info.get("at") or 0)}


def build(pellet=None, recipe=None):
    """`pellet` / `recipe`: the armed_info() of each run module, or None when nothing of that kind is armed."""
    entries = []
    if pellet:
        entries.append(_entry("pellet", pellet))
    if recipe:
        entries.append(_entry("recipe", recipe))
    first = entries[0] if entries else None
    return {"armed": bool(entries), "file": first["file"] if first else "", "profile": first["name"] if first else "",
            "rules": sum(e["rules"] for e in entries), "at": first["at"] if first else 0, "survivesRestart": False, "entries": entries}
