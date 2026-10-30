"""Duet 3 boards the service knows by their object model shortName.

Adapted (read only) from the discovery engine of the WorkshopConfig plugin
(core/boards.js). Only Duet 3 hardware in SBC mode is listed: the service never
runs on a Duet 2 or without a Raspberry Pi. An unknown board is still reported
(with chip None); this table only adds the nice name and the driver chip.

kind: main (CAN 0), expansion, tool, probe, motor.
drivers: amount the board has (None = read maxMotors from the object model),
smart: drivers with their own diagnostics (TMC), closed_loop: encoder drivers.
"""

BOARDS = {
    "MB6HC": {"name": "Duet 3 Main Board 6HC", "kind": "main", "drivers": 6, "chip": "TMC5160", "smart": True, "closed_loop": False},
    "MB6XD": {"name": "Duet 3 Main Board 6XD", "kind": "main", "drivers": 6, "chip": None, "smart": False, "closed_loop": False},
    "Mini5plus": {"name": "Duet 3 Mini 5+", "kind": "main", "drivers": 5, "chip": "TMC2209", "smart": True, "closed_loop": False},
    "EXP3HC": {"name": "Duet 3 Expansion 3HC", "kind": "expansion", "drivers": 3, "chip": "TMC5160", "smart": True, "closed_loop": False},
    "EXP1XD": {"name": "Duet 3 Expansion 1XD", "kind": "expansion", "drivers": 1, "chip": None, "smart": False, "closed_loop": False},
    "EXP1HCL": {"name": "Duet 3 Expansion 1HCL", "kind": "expansion", "drivers": 1, "chip": "TMC5160", "smart": True, "closed_loop": True},
    "M23CL": {"name": "Duet 3 Motor 23CL", "kind": "motor", "drivers": 1, "chip": "TMC5160", "smart": True, "closed_loop": True},
    "TOOL1LC": {"name": "Duet 3 Tool Board 1LC", "kind": "tool", "drivers": 1, "chip": "TMC2209", "smart": True, "closed_loop": False},
    "TOOL1RR": {"name": "Duet 3 Roto Tool Board", "kind": "tool", "drivers": 1, "chip": None, "smart": True, "closed_loop": False},  # chip NOT verified (two sources disagreed: TMC2209 / TMC2240); the owner has no such board, so it is left unknown and Motors reads no raw driver register of it
    "SZP": {"name": "Duet 3 Scanning Z-Probe", "kind": "probe", "drivers": 0, "chip": None, "smart": False, "closed_loop": False},
}

_BY_LOWER = {k.lower(): k for k in BOARDS}


def lookup(short_name):
    """Table entry for a shortName (case-insensitive), or None."""
    if not short_name:
        return None
    key = _BY_LOWER.get(str(short_name).lower())
    return BOARDS[key] if key else None
