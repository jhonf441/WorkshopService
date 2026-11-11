"""Decoding of the TMC driver state (pure, no I/O, imports nothing of the service): the bit maps of DRV_STATUS per format
(DRV_STATUS_MAPS), the keys of what each fault means, the chip of each Duet3D board, the CHOPCONF "enabled" bit and the dc42 pulse-rate
reference. Split out of motor_status.py (F6b), same code. The texts themselves are built by the facade (motor_status.py) and handed in as
`text_of`, so this module stays out of the import cycle of `messages`.

Two different values have each their own map: "rrf" is boards[].drivers[].status of the object model (RRF's StandardDriverStatus, same for
any board), "tmc51xx"/"tmc22xx" are the raw DRV_STATUS register of the chip. An unknown chip or format is never interpreted.
"""

# Reference of pulse rates MEASURED (not from a datasheet) and published by
# dc42 (main developer of RepRapFirmware) for the Duet 3 MB6HC -- exactly
# this board -- with stable RRF 3.2, x256 microstepping, according to the
# "step pulse timing" configured with M569 Tn (column = timing in us; "fast"
# = T0, pulses as short as possible).
# Source: https://docs.google.com/spreadsheets/d/1AWA1wLbOaYzxzdQa5LRZvn9rgEk2BuluHy6-_OnD6FY
# (dc42's public spreadsheet; a search confirmed that the "Firmware 3.2
# Stable" row is specifically for the MB6HC).
# ⚠️ It is a REFERENCE, not a guarantee for THIS machine: it is RRF 3.2 and
# this Pi runs RRF 3.6.3 (much newer -- the RRF 3.2RC1/beta1 rows of the
# same sheet already show much higher numbers, 170-250kHz, so 3.6.3 probably
# performs better than this table). The most reliable number for THIS
# specific machine is still "loop_hz_max_ever" (measured live, see
# parse_m122_board_capacity) -- this table is only an external, published,
# traceable point of comparison.
DC42_MB6HC_RRF32_KHZ = {
    "fast": {"a_motor_length": 83, "three_motors_length": 70, "three_motors_short": 41},
    "1": {"a_motor_length": 55, "three_motors_length": 51, "three_motors_short": 44},
    "2.5": {"a_motor_length": 48, "three_motors_length": 48, "three_motors_short": 40},
    "5": {"a_motor_length": 40, "three_motors_length": 40, "three_motors_short": 36},
    "10": {"a_motor_length": 30, "three_motors_length": 30, "three_motors_short": 27},
}


def _timing_key(timing_raw):
    s = (timing_raw or "").strip().lower()
    if s == "fast":
        return "fast"
    try:
        v = float(s)
    except ValueError:
        return None
    for k in ("1", "2.5", "5", "10"):
        if abs(v - float(k)) < 0.05:
            return k
    return None


def dc42_reference(timing_raw):
    key = _timing_key(timing_raw)
    if key is None or key not in DC42_MB6HC_RRF32_KHZ:
        return None
    row = DC42_MB6HC_RRF32_KHZ[key]
    return {
        "timing": key,
        "a_motor_length_khz": row["a_motor_length"],
        "three_motors_length_khz": row["three_motors_length"],
        "three_motors_short_khz": row["three_motors_short"],
    }
# Fixed 2026-10-12 (item 4). The previous note said that at rest the chip
# gave "false positives" in otpw+ot+s2ga+s2gb+s2vsa all at once: it was a
# decoding error, not the chip. The raw DRV_STATUS of a TMC2160A was read with
# the TMC2209 map, and in the TMC2160 bits 0-9 are SG_RESULT (at rest, the
# chopper on-time): any number there looked like "faults". With the correct
# map, at rest only ola/olb are meaningless (open-coil detection needs steps)
# and they are discarded; the rest of the bits are real faults both at rest
# and running.

# What each fault means (key -> text key of the catalog, severity). The severities follow the
# RRF masks (StandardDriverStatus::ErrorMask/WarningMask).
FAULT_TEXT_KEYS = {
    "otpw": ("motor_status_temperature_warning", "warning"),
    "ot": ("motor_status_overtemperature_shut_down", "error"),
    "s2ga": ("motor_status_short_to_ground_phase_a", "error"),
    "s2gb": ("motor_status_short_to_ground_phase_b", "error"),
    "s2vsa": ("motor_status_short_supply_phase", "error"),
    "s2vsb": ("motor_status_short_supply_phase_b", "error"),
    "ola": ("motor_status_possible_open_coil_phase_a", "warning"),
    "olb": ("motor_status_possible_open_coil_phase_b", "warning"),
    "ext": ("motor_status_external_driver_error", "error"),
    "pos_tol": ("motor_status_outside_position_tolerance", "warning"),
    "pos_lost": ("motor_status_does_not_hold_position", "error"),
    "setting_error": ("motor_status_closed_loop_tuning_failed", "warning"),
    "mov_ilegal": ("motor_status_move_without_closed_loop_tuned", "error"),
}

# Bit maps per format. "faults": (bit, DRIVER_FAULTS key).
# rrf -> boards[].drivers[].status of the object model (RRF's
# StandardDriverStatus, the same for any board/driver; CANlib RRF3Common.h)
# tmc51xx -> raw DRV_STATUS of TMC2160/TMC5130/TMC5160/TMC5161
# tmc22xx -> raw DRV_STATUS of TMC2208/TMC2209/TMC2224
DRV_STATUS_MAPS = {
    "rrf": {
        "faults": [(0, "otpw"), (1, "ot"), (2, "s2ga"), (3, "s2gb"), (4, "s2vsa"),
                   (5, "s2vsb"), (6, "ola"), (7, "olb"), (9, "ext"), (10, "pos_tol"),
                   (11, "pos_lost"), (13, "setting_error"), (14, "mov_ilegal")],
        "stst": 16, "stall": 8, "no_present": 17, "stealth": None,
        "cs_current": None, "sg": (22, 0x3FF),
        # RRF already discards ola/olb at rest, at low speed and with low current
        "ol_only_in_motion": False,
    },
    "tmc51xx": {
        "faults": [(26, "otpw"), (25, "ot"), (27, "s2ga"), (28, "s2gb"), (12, "s2vsa"),
                   (13, "s2vsb"), (29, "ola"), (30, "olb")],
        "stst": 31, "stall": 24, "no_present": None, "stealth": 14,
        "cs_current": (16, 0x1F), "sg": (0, 0x3FF),
        "ol_only_in_motion": True,
    },
    "tmc22xx": {
        "faults": [(0, "otpw"), (1, "ot"), (2, "s2ga"), (3, "s2gb"), (4, "s2vsa"),
                   (5, "s2vsb"), (6, "ola"), (7, "olb")],
        "stst": 31, "stall": None, "no_present": None, "stealth": 30,
        "cs_current": (16, 0x1F), "sg": None,
        "ol_only_in_motion": True,
    },
}

# Chip of the own drivers of each Duet3D board (boards[].shortName). Only
# to read the raw DRV_STATUS (M569.2): if the board is not here, the raw
# value is neither read nor interpreted and the object model state is used,
# which does not depend on the chip. Boards with external drivers (MB6XD,
# EXP1XD) or TMC2660 (Duet 2) do not belong: their raw value is not a
# DRV_STATUS of these maps.
CHIP_BY_BOARD = {
    "MB6HC": "tmc51xx",     # 6 x TMC2160A (v1.01+); v1.0 TMC5160, mismo mapa
    "EXP3HC": "tmc51xx",    # TMC2160A/TMC5160
    "EXP1HCL": "tmc51xx",   # TMC2160A
    "Mini5plus": "tmc22xx",  # TMC2209
    "TOOL1LC": "tmc22xx",   # TMC2209
}


def chip_of_board(board, forced=None):
    """Format of the raw DRV_STATUS of the drivers of `board` (a dict of
    boards[]), or None if unknown. `forced` (config.json ->
    motor_status -> chip_drivers_local) wins if it is a known format."""
    if forced in ("tmc51xx", "tmc22xx"):
        return forced
    if not isinstance(board, dict):
        return None
    return CHIP_BY_BOARD.get((board.get("shortName") or "").strip())
CHOPCONF_TOFF_MASK = 0x0F  # bits 0-3: TOFF. 0 = driver off (no current)


def enabled_of_chopconf(raw):
    """True if the driver is enabled (TOFF != 0), False if it is off, None if
    there is no reading."""
    if not isinstance(raw, int):
        return None
    return (raw & CHOPCONF_TOFF_MASK) != 0


def decode_driver_status(status_raw, fmt="rrf", text_of=None):
    """Decodes a driver state with the map of `format` (see DRV_STATUS_MAPS):
    "rrf" for boards[].drivers[].status of the object model, "tmc51xx"/"tmc22xx"
    for the raw DRV_STATUS of M569.2. If there is no value or the format is
    not known, it invents nothing: no flags and with the fields at None. `text_of(key)` turns the text key of a fault into its message."""
    mapping = DRV_STATUS_MAPS.get(fmt) if status_raw is not None else None
    if mapping is None:
        return {
            "raw": status_raw,
            "raw_hex": f"0x{status_raw:08X}" if isinstance(status_raw, int) else None,
            "format": None,
            "flags": [],
            "cs_current": None,
            "cs_current_max": None,
            "standstill": None,
            "stall": None,
            "stealth": None,
            "sg_result": None,
            "ol_discarded": False,
        }
    v = int(status_raw) & 0xFFFFFFFF

    def bit(n):
        return None if n is None else bool(v & (1 << n))

    standstill = bit(mapping["stst"])
    flags = []
    ol_discarded = False
    for b, key in mapping["faults"]:
        if not v & (1 << b):
            continue
        # open coil: only meaningful while the motor is stepping
        if key in ("ola", "olb") and mapping["ol_only_in_motion"] and standstill:
            ol_discarded = True
            continue
        msg_key, severity = FAULT_TEXT_KEYS[key]
        flags.append({"key": key, "label": text_of(msg_key) if text_of else msg_key, "severity": severity})
    cs = mapping["cs_current"]
    sg = mapping["sg"]
    return {
        "raw": v,
        "raw_hex": f"0x{v:08X}",
        "format": fmt,
        "flags": flags,
        "cs_current": ((v >> cs[0]) & cs[1]) if cs else None,
        "cs_current_max": 31 if cs else None,
        "standstill": standstill,
        "stall": bit(mapping["stall"]),
        "stealth": bit(mapping["stealth"]),
        # at rest the TMC2160 returns the chopper time, not the load
        "sg_result": ((v >> sg[0]) & sg[1]) if sg and not standstill else None,
        "ol_discarded": ol_discarded,
    }
