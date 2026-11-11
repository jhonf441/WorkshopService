"""ONE place for where the mode system lives on the SD (SD layout, phase 4). Every module of the service takes the paths from here; a test
(`test_mode_paths.py`) fails when a literal old-layout path shows up in another module. The Vue plugins have the same single source in
TallerPlugins `vue/_shared/machine-modes.js` (MODES_DIR, MODE_FILES, AUTO_MODE_FILE, MODE_STATE_FILE); both hold the same strings and each
side tests them.

    automodeselect.g, modefff.g, modelaser.g, modecnc.g   0:/sys/workshop/modes/
    modestate.g (run-time state written by daemon.g)      0:/sys/workshop/data/modestate.g

Paths here are relative to the SD ("sys/..."); `sd()` gives the `0:/` form G-code uses.
"""
MODES_DIR = "sys/workshop/modes"
STATE_DIR = "sys/workshop/data"
AUTO = MODES_DIR + "/automodeselect.g"
STATE = STATE_DIR + "/modestate.g"
MODE_FILES = {"Laser": MODES_DIR + "/modelaser.g", "CNC": MODES_DIR + "/modecnc.g", "FFF": MODES_DIR + "/modefff.g"}
NAMES = ("automodeselect", "modestate", "modecnc", "modefff", "modelaser")

# the layout before phase 4 -> after it, in the order a move is applied (state last: nothing reads it while the others move)
MOVES = (("sys/automodeselect.g", AUTO),
         ("sys/modefff.g", MODE_FILES["FFF"]),
         ("sys/modelaser.g", MODE_FILES["Laser"]),
         ("sys/modecnc.g", MODE_FILES["CNC"]),
         ("sys/modestate.g", STATE))
OLD_PATHS = tuple(o for o, _n in MOVES)


def unmigrated(exists):
    """Old paths (layout before phase 4) of the files that are still there: `exists(rel)` -> bool over the SD (`sys/...`). The readers of the
    service look ONLY at the new paths (there is no fallback to the old ones: the owner decided it), so while this list is not empty they
    see "no modes" and must SAY why instead of proposing lines for files that are not there."""
    return [o for o, _n in MOVES if exists(o)]


def sd(rel):
    """`0:/sys/...` form of a path of the SD."""
    return "0:/" + rel


def new_path(name):
    """New SD path of a mode file by its name without extension ('modefff'), or None."""
    for o, n in MOVES:
        if o == "sys/%s.g" % name:
            return n
    return None
