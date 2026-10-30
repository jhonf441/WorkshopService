"""
Motor status calculation (pulse frequency, RPM, mm/min, and how close
they are to the configured limit) from the standard RRF/DSF object model,
read from the single DSF subscription (machine_state.get_status, in
memory; until 2026-10-12 it was GET /machine/status over HTTP).

It also decodes the read-only field boards[].drivers[].status (the TMC
driver's DRV_STATUS register, which RRF exposes as is in the object model)
and runs M122 periodically to get the diagnostic text RRF already computes
by itself (standstill, SG min, mspos) -- see below for why this is safe and
why M569.2 is NOT used for any of this.

⚠️ It deliberately does NOT use M569.2 (read/write of raw TMC driver
registers) for any of this -- the Duet3D documentation warns that some
parameters sent with M569.2 can permanently damage the driver chip.
Everything used here is:
  - boards[].drivers[].status: a READ-ONLY object model field (RRF already
    reads the driver's DRV_STATUS register by itself during the normal TMC
    polling and publishes it; this sends nothing to the driver, it only
    reads what DSF already has cached).
  - M122: the standard RRF diagnostic command (the same one anyone runs by
    hand to ask for a status report) -- it does NOT write any register, it
    only asks for a text dump of what the firmware already knows. It is the
    official, supported way to "read" the driver state as human text
    (standstill/SG min/mspos), and it is categorically different from
    M569.2 (which can write registers and is what must be avoided).
  If something only M569.2 exposes is ever needed, stop and think it over
  carefully; do not send it just in case.

Speed / pulse frequency (fixed 2026-10-12, item 5): RRF does not expose the
INSTANTANEOUS speed of each axis (it lives in the pulse generator). What it
does expose, live, is move.currentMove.topSpeed/requestedSpeed: the VECTOR
speed of the move being executed (0 if there is none). To know WHICH axes
take part, the standstill bit of each driver is used
(boards[].drivers[].status, standard RRF format, bit 16; the chip sets it
~0.1 s after the last step): an axis with any driver not in standstill is
moving and its speed is that of the current move (capped to its M203
maximum); an axis with all its drivers in standstill goes at 0. It is EXACT
in single-axis moves (the common case: back-and-forth engraving, straight
cuts) and CONSERVATIVE on diagonals (each axis goes slower than the
vector). If it is not known whether a board's drivers report standstill
(boards without known TMC drivers, CAN boards), "the position changed since
the previous reading" is used. The previous version used the NET
displacement over ~1 s: in back-and-forth engraving that gives almost 0
(it returns to the same place) -> "~3 Hz".

RPM: RRF does not expose motor-steps-per-revolution either (that
information is implicit in how stepsPerMm was computed -- it already
includes pulley/screw reduction and microstepping). A standard stepper
motor of 200 full steps per revolution (1.8 degrees) is assumed unless
the person says otherwise: per axis (and in general) in Motors > Advisor
> "Steps per revolution" (settings file "motors", read every cycle by
steps_per_rev_resolver; 0.9 degrees = 400, etc), or for the whole machine
in config.json -> "motor_status" -> "full_steps_per_rev". The entry says
which number it used ("full_steps_per_rev").

Driver state decoding (fixed 2026-10-12, item 4). There are TWO different
values and each one has its own bit map:

1. boards[].drivers[].status of the object model: it is NOT the chip's
   register. It is RRF's StandardDriverStatus (CANlib/src/RRF3Common.h),
   the same format for any board and driver (TMC2209, TMC2160/5160,
   TMC2660, external drivers of the MB6XD/EXP1XD): bits 0-7 otpw, ot,
   s2ga, s2gb, s2vsa, s2vsb, ola, olb; 8 stall; 9 external driver error;
   10-14 closed loop; 16 standstill; 17 driver not present; 22-31 minimum
   SG. RRF builds it from the chip's register (TMC51xx.cpp,
   TmcDriverState::GetStatus) and ALREADY discards ola/olb at standstill,
   at low speed and with current < 500 mA. It is LIVE (flag
   liveNotPanelDue), so it arrives with every /machine/status. The "fixed
   0x10000 on the 6 drivers" seen on 2026-10-07 and taken for a "broken
   field" was bit 16 = standstill (machine at rest), not CS_ACTUAL=1.
2. The raw DRV_STATUS register (0x6F) read with M569.2 R111 (local drivers
   only): THIS one does depend on the chip. Maps (RRF TMC51xx.cpp and
   TMC22xx.cpp, Klipper tmc5160.py/tmc2208.py, Trinamic/ADI datasheets):
     TMC2160/5130/5160 ("tmc51xx"): 0-9 SG_RESULT, 12 s2vsa, 13 s2vsb,
       14 stealth, 15 fsactive, 16-20 CS_ACTUAL, 24 stallGuard, 25 ot,
       26 otpw, 27 s2ga, 28 s2gb, 29 ola, 30 olb, 31 stst.
     TMC2208/2209/2224 ("tmc22xx"): 0 otpw, 1 ot, 2-3 s2g, 4-5 s2vs,
       6-7 ol, 8-11 t120..t157, 16-20 CS_ACTUAL, 30 stealth, 31 stst.
   The previous version read this raw value of the 6HC (TMC2160A) with the
   TMC2209 map: bits 0-7 are SG_RESULT (at rest, the chopper on-time), which
   is why false "overtemperature + shorts" showed up at rest and false
   alarms while moving.
   ola/olb of the raw value only count while moving: with stst active they
   are discarded (as RRF does). If the board's chip is not known, the raw
   value is NOT interpreted (nor requested): the object model one (point 1)
   is used, which does not depend on the chip.

CS_ACTUAL (0-31, only in the raw value): current scale the driver applies
NOW. See estimate_cs_actual_ma for the conversion to mA.

"""
import json
import re
import time
from messages import M

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

THRESHOLD_ALERT_PCT = 80
THRESHOLD_LIMIT_PCT = 95

# Fixed 2026-10-12 (item 4). The previous note said that at rest the chip
# gave "false positives" in otpw+ot+s2ga+s2gb+s2vsa all at once: it was a
# decoding error, not the chip. The raw DRV_STATUS of a TMC2160A was read with
# the TMC2209 map, and in the TMC2160 bits 0-9 are SG_RESULT (at rest, the
# chopper on-time): any number there looked like "faults". With the correct
# map, at rest only ola/olb are meaningless (open-coil detection needs steps)
# and they are discarded; the rest of the bits are real faults both at rest
# and running.

# What each fault means (key -> text, severity). The severities follow the
# RRF masks (StandardDriverStatus::ErrorMask/WarningMask).
DRIVER_FAULTS = {
    "otpw": (M("motor_status_temperature_warning"), "warning"),
    "ot": (M("motor_status_overtemperature_shut_down"), "error"),
    "s2ga": (M("motor_status_short_to_ground_phase_a"), "error"),
    "s2gb": (M("motor_status_short_to_ground_phase_b"), "error"),
    "s2vsa": (M("motor_status_short_supply_phase"), "error"),
    "s2vsb": (M("motor_status_short_supply_phase_b"), "error"),
    "ola": (M("motor_status_possible_open_coil_phase_a"), "warning"),
    "olb": (M("motor_status_possible_open_coil_phase_b"), "warning"),
    "ext": (M("motor_status_external_driver_error"), "error"),
    "pos_tol": (M("motor_status_outside_position_tolerance"), "warning"),
    "pos_lost": (M("motor_status_does_not_hold_position"), "error"),
    "setting_error": (M("motor_status_closed_loop_tuning_failed"), "warning"),
    "mov_ilegal": (M("motor_status_move_without_closed_loop_tuned"), "error"),
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

# Compatibility: list of (bit, key, text, severity) of RRF's format.
DRIVER_STATUS_BITS = [
    (bit, key) + DRIVER_FAULTS[key] for bit, key in DRV_STATUS_MAPS["rrf"]["faults"]
]

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


def board_local(status):
    for board in (status or {}).get("boards", []) or []:
        if (board.get("canAddress") or 0) == 0:
            return board
    return None

_M122_DRIVER_RE = re.compile(
    r"^Driver (\d+): ([^,]+), SG min (-?\d+|n/a), mspos (\d+), "
    r"reads (\d+), writes (\d+) timeouts (\d+)",
    re.MULTILINE,
)

# "Phase step loop runtime (us): min=0, max=2, frequency (Hz): min=1937, max=2054"
#
# ⚠️ FIXED 2026-10-07 after a real test (macros/motores/
# calibrate_pulses.g, X axis, 300mm at 18000 mm/min, x256 without
# interpolation): this was assumed to be the REAL pulse generation frequency
# during the move (the "most honest answer" to how many pulses the board can
# generate). THE REAL TEST CONTRADICTED IT: this number stayed at ~2000 Hz,
# THE SAME before and after a move that generated 384,000 real steps, with 0
# hiccups. So this field is NOT measuring the pulse frequency of the move --
# it is probably the background polling/communication loop with the TMCs
# (fixed, independent of whether there is movement or not), not the step
# generation ISR. The field is kept (it is still a real firmware measurement,
# not invented) but WITHOUT the confidence it had before -- "hiccups" (see
# below) is the one that WAS validated with a real test: it stayed at a clean
# 0/0 in the same test, exactly the signal dc42 recommends watching. Prefer
# hiccups over this field to judge the real margin.
_M122_PHASE_LOOP_RE = re.compile(
    r"Phase step loop runtime \(us\): min=(\d+), max=(\d+), "
    r"frequency \(Hz\): min=(\d+), max=(\d+)"
)

# "Segments created 6, maxWait 0ms, ..., hiccups added 0/0 (0.00/0.00ms), max steps late 0, ..."
# -- "hiccups" is the count of times the pulse generator did NOT arrive on
# time (lost a step) -- the most direct signal of "the board could not
# generate the pulses the move asked for". 0 is good.
_M122_HICCUPS_RE = re.compile(
    r"hiccups added (\d+)/(\d+) \(([\d.]+)/([\d.]+)ms\), max steps late (\d+)"
)


_M569_2_READ_RE = re.compile(r"Register 0x[0-9A-Fa-f]+ value 0x([0-9A-Fa-f]+)")
GSTAT_REGISTER = 1  # GSTAT: identical in TMC2209 and TMC5160 (confirmed in both datasheets)


def read_gstat(bridge, local_driver_idx):
    """Reads GSTAT (register 0x01) of ONE local driver via M569.2 -- this is the
    ONLY function in the whole plugin that sends M569.2, and it is
    structurally read-only: it has no value parameter, so there is no way it
    could end up sending V by accident (never add one to this function).
    Confirmed live (2026-10-07) that "M569.2 P<n> R<reg>" without V answers
    "Register 0x01 value 0x........" and writes nothing.

    GSTAT is different from DRV_STATUS (boards[].drivers[].status, which
    already comes for free in the object model): DRV_STATUS is the
    INSTANTANEOUS state; GSTAT is a LATCH -- bit0 says whether the driver
    reset and bit1 whether there was an error (overtemperature or short) at
    some point since the last time someone cleared the register, even if it is
    not happening now. Per the datasheet, GSTAT is "read + write-clear":
    READING it does not clear it (writing a 1 by hand is needed, something this
    function never does) -- so besides being read-only, it does not even erase
    the history it is reporting.
    """
    try:
        reply = bridge.send(f"M569.2 P{local_driver_idx} R{GSTAT_REGISTER}")
    except Exception:
        return None
    m = _M569_2_READ_RE.search(reply or "")
    if not m:
        return None
    raw = int(m.group(1), 16)
    return {
        "raw": raw,
        "reset_detected": bool(raw & 0x1),
        "driver_error_latched": bool(raw & 0x2),
    }


DRV_STATUS_REGISTER = 111  # 0x6F: DRV_STATUS, identical in TMC2209 and TMC5160 (confirmed in both datasheets)


def read_drv_status_raw(bridge, local_driver_idx):
    """Reads DRV_STATUS (register 0x6F) of ONE local driver via M569.2 --
    READ-ONLY, the exact same pattern as read_gstat() (no value parameter,
    there is no way it sends V). Returns the raw 32-bit integer, or None if it
    failed.

    The raw value has the CHIP's bit map (see DRV_STATUS_MAPS and
    chip_of_board): it is only requested if the chip of the local board is known.
    Fixed 2026-10-12: the previous note said that
    boards[].drivers[].status of the object model was "broken" because it gave
    0x10000 on the 6 drivers. It is not: it is RRF's standard format (not the
    chip's register) and 0x10000 is bit 16 = standstill. The raw value is still
    read because it carries CS_ACTUAL, SG_RESULT and stealth, which the object
    model does not publish."""
    try:
        reply = bridge.send(f"M569.2 P{local_driver_idx} R{DRV_STATUS_REGISTER}")
    except Exception:
        return None
    m = _M569_2_READ_RE.search(reply or "")
    if not m:
        return None
    return int(m.group(1), 16)


CHOPCONF_REGISTER = 108  # 0x6C: CHOPCONF, read and write in TMC2160/5160 and TMC2209 (both datasheets)
CHOPCONF_TOFF_MASK = 0x0F  # bits 0-3: TOFF. 0 = driver off (no current)


def read_chopconf_raw(bridge, local_driver_idx):
    """Reads CHOPCONF (register 0x6C) of ONE local driver via M569.2 --
    READ-ONLY, the exact same pattern as read_gstat() (no value parameter,
    there is no way it sends V). Returns the raw integer or None.

    2026-10-12 (enable/disable motors): RRF does NOT publish in the object
    model whether a motor is enabled. On the main board (MB6HC, EXP3HC, Mini
    5+) the TMC drivers have no enable pin: RRF enables and disables them by
    writing TOFF in CHOPCONF (TOFF=0 = off; RepRapFirmware 3.6,
    TMC51xx.cpp/TMC22xx.cpp UpdateChopConfRegister). Reading CHOPCONF then
    tells the REAL state of each driver, one by one."""
    try:
        reply = bridge.send(f"M569.2 P{local_driver_idx} R{CHOPCONF_REGISTER}")
    except Exception:
        return None
    m = _M569_2_READ_RE.search(reply or "")
    if not m:
        return None
    return int(m.group(1), 16)


def enabled_of_chopconf(raw):
    """True if the driver is enabled (TOFF != 0), False if it is off, None if
    there is no reading."""
    if not isinstance(raw, int):
        return None
    return (raw & CHOPCONF_TOFF_MASK) != 0


def local_driver_indices(status):
    """LOCAL indices (canAddress 0, the main board) of all the drivers that are
    assigned to an axis or extruder right now.
    M569.2 can only address local drivers of the main board, not those of a
    remote CAN expansion board -- those are left without GSTAT data
    (documented limitation, not a bug)."""
    move = status.get("move", {}) or {}
    ids = set()
    for coll in (move.get("axes", []) or []) + (move.get("extruders", []) or []):
        for did in coll.get("drivers") or []:
            board, _, idx = did.partition(".")
            if board == "0":
                try:
                    ids.add(int(idx))
                except ValueError:
                    pass
    return ids


_M569_RE = re.compile(
    r"timing (\S+?), mode (\w+).*?iRun/iHold (\d+)/(\d+), current ([\d.]+)"
)


def read_m569(bridge, local_driver_idx):
    """Reads the configuration of ONE local driver via "M569 P<n>" WITHOUT more
    parameters -- that is a read-only REPORT (the same M569 used to configure,
    but it writes nothing if no more parameters are passed), nothing to do
    with M569.2. It gives the "timing" (Tn of M569, to cross against
    DC42_MB6HC_RRF32_KHZ), the mode (spreadCycle/stealthChop) and "current" --
    the current RRF computes for iRun/gs, in mA. ⚠️ That "current" may NOT
    match the mA configured by M906 (axis.current of the object model) -- no
    attempt is made to reconcile the two here, both are shown in the UI as each
    one reports them, instead of inventing an unverified explanation."""
    try:
        reply = bridge.send(f"M569 P{local_driver_idx}")
    except Exception:
        return None
    m = _M569_RE.search(reply or "")
    if not m:
        return None
    timing_raw, mode, irun, ihold, current_ma = m.groups()
    return {
        "timing_raw": timing_raw,
        "mode": mode,
        "irun": int(irun),
        "ihold": int(ihold),
        "current_ma_m569": float(current_ma),
        "dc42_ref": dc42_reference(timing_raw),
    }


def board_inventory(status, drv_status_raw_by_local_driver=None, chip_local=None, lookup=None):
    """Inventory of ALL connected boards and ALL their drivers, whether or not
    they are assigned to an axis/extruder right now -- unlike
    compute_motor_report()["entries"] (which only lists those IN use), this
    answers "what is connected" in general. It serves the "Connected boards"
    section of the UI. Each driver is decoded the same way as in
    _driver_lookup() (the M569.2 raw value if the chip is known, otherwise the
    standard object model state)."""
    if lookup is None:
        lookup = _driver_lookup(status, drv_status_raw_by_local_driver, chip_local)
    move = status.get("move", {}) or {}
    assigned = {}
    for ax in move.get("axes", []) or []:
        for did in ax.get("drivers") or []:
            assigned[did] = ax.get("letter", "?")
    for i, ex in enumerate(move.get("extruders", []) or []):
        for did in ex.get("drivers") or []:
            assigned[did] = f"E{i}"

    boards = []
    for board in status.get("boards", []) or []:
        can_addr = board.get("canAddress", 0) or 0
        drivers = []
        for idx, _drv in enumerate(board.get("drivers", []) or []):
            did = f"{can_addr}.{idx}"
            drivers.append({
                "id": did,
                "assigned_to": assigned.get(did),
                **lookup.get(did, decode_driver_status(None)),
            })
        boards.append({
            "name": board.get("name"),
            "short_name": board.get("shortName"),
            "can_address": can_addr,
            "is_local": can_addr == 0,
            "drivers": drivers,
        })
    return boards


def _aggregate_board_motion(boards, entries):
    """Adds, for EACH board (from board_inventory), the pulse load that its own
    motors are generating right now -- requested by the user 2026-10-07:
    "there should be two tables of mm and of pulses for each board... and the
    motors that are configured on it belong to each one". For each driver of
    the board that is assigned to an axis/extruder (assigned_to, from
    board_inventory), it looks up that entry in `entries` (by "label") and:
      - SUMS current_freq_hz/max_freq_hz PER DRIVER (if an axis has 2 drivers on
        the SAME board -- e.g. dual Z -- each one generates its own pulses, both
        must be counted for the board's real load).
      - builds a `motors` list WITHOUT duplicating axes (for the UI tables, an
        axis with 2 drivers on the same board appears only once).
    It does not modify `boards` -- it returns a copy with the added fields."""
    by_label = {e["label"]: e for e in entries}
    out = []
    for board in boards:
        combined_freq_hz = 0.0
        combined_max_freq_hz = 0.0
        combined_speed_mm_min = 0.0
        combined_max_speed_mm_min = 0.0
        seen_labels = set()
        motors = []
        for drv in board["drivers"]:
            label = drv.get("assigned_to")
            if not label:
                continue
            entry = by_label.get(label)
            if not entry:
                continue
            combined_freq_hz += entry["current_freq_hz"]
            combined_max_freq_hz += entry["max_freq_hz"]
            combined_speed_mm_min += entry["current_speed_mm_min"]
            combined_max_speed_mm_min += entry["max_speed_mm_min"]
            if label not in seen_labels:
                seen_labels.add(label)
                motors.append({
                    "label": label,
                    "current_speed_mm_min": entry["current_speed_mm_min"],
                    "max_speed_mm_min": entry["max_speed_mm_min"],
                    "current_freq_hz": entry["current_freq_hz"],
                    "max_freq_hz": entry["max_freq_hz"],
                    "pct_of_max": entry["pct_of_max"],
                })
        out.append({
            **board,
            "motors": motors,
            "combined_freq_hz": combined_freq_hz,
            "combined_max_freq_hz": combined_max_freq_hz,
            "combined_speed_mm_min": combined_speed_mm_min,
            "combined_max_speed_mm_min": combined_max_speed_mm_min,
        })
    return out


def parse_m122_board_capacity(m122_text):
    """What M122 says about the REAL capacity of the board's pulse generator at
    this moment -- see the docstrings of the regexes above. Returns None if the
    text does not have that section (e.g. the first M122 has not arrived yet)."""
    if not m122_text:
        return None
    loop = _M122_PHASE_LOOP_RE.search(m122_text)
    hic = _M122_HICCUPS_RE.search(m122_text)
    if not loop and not hic:
        return None
    out = {}
    if loop:
        out["loop_us_min"] = int(loop.group(1))
        out["loop_us_max"] = int(loop.group(2))
        out["loop_hz_min"] = int(loop.group(3))
        out["loop_hz_max"] = int(loop.group(4))
    if hic:
        out["hiccups_ring0"] = int(hic.group(1))
        out["hiccups_ring1"] = int(hic.group(2))
        out["max_steps_late"] = int(hic.group(5))
    return out


VIN_MIN_DRIVERS_V = 10.0  # below this the TMC5160 drivers are not powered


def drivers_without_power_supply(status):
    """True if the power supply is off (M81 -> state.status "off") or the main
    board's VIN is below VIN_MIN_DRIVERS_V. With the PSU off the board stays
    alive (separate 5 V) but the drivers do not respond: M569/M569.2 only give
    timeouts."""
    if ((status.get("state") or {}).get("status")) == "off":
        return True
    try:
        vin = status["boards"][0]["vIn"]["current"]
    except (KeyError, IndexError, TypeError):
        return False
    return vin is not None and vin < VIN_MIN_DRIVERS_V


def fetch_status():
    import machine_state  # single DSF subscription: in memory, no request

    return machine_state.get_status()


def _level(pct):
    # Do not return color emoji here (🔴🟡🟢): they need a color emoji font that
    # the Pi's kiosk Chromium does not have installed -- they looked fine in a
    # normal desktop Chrome but as "tofu" on the Pi. The frontend (Motors.vue)
    # already draws the color dot with CSS from "nivel", which does not depend
    # on any font.
    if pct >= THRESHOLD_LIMIT_PCT:
        return "limit"
    if pct >= THRESHOLD_ALERT_PCT:
        return "alert"
    return "ok"


def decode_driver_status(status_raw, fmt="rrf"):
    """Decodes a driver state with the map of `format` (see DRV_STATUS_MAPS):
    "rrf" for boards[].drivers[].status of the object model, "tmc51xx"/"tmc22xx"
    for the raw DRV_STATUS of M569.2. If there is no value or the format is
    not known, it invents nothing: no flags and with the fields at None."""
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
        label, severity = DRIVER_FAULTS[key]
        flags.append({"key": key, "label": label, "severity": severity})
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


def _driver_lookup(status, drv_status_raw_by_local_driver=None, chip_local=None,
                   chopconf_by_local_driver=None):
    """Map "<canAddress>.<index>" -> decoded dict, so it can be looked up by the
    same id used by move.axes[].drivers / extruders[].drivers.

    LOCAL drivers with a raw M569.2 R111 reading and a known chip
    (chip_of_board): the raw value is decoded with the chip's map (it carries
    CS_ACTUAL). The rest (CAN boards, unknown chip, no reading): RRF's standard
    state from the object model, which is valid for any board.

    Each driver also carries "in_idle_live": the standstill bit of the object
    model of THIS reading (the raw one is up to ~5 s old), or None if it cannot
    be trusted (see _standstill_reliable). It is what the speed calculation
    uses to know whether the axis is moving.

    And "enabled": True/False read from CHOPCONF (read_chopconf_raw) on local
    drivers with a known chip; None on CAN boards, unknown chip or no reading
    (RRF does not publish it in the object model)."""
    drv_status_raw_by_local_driver = drv_status_raw_by_local_driver or {}
    chopconf_by_local_driver = chopconf_by_local_driver or {}
    lookup = {}
    for board in status.get("boards", []) or []:
        can_addr = board.get("canAddress", 0) or 0
        chip = chip_of_board(board, chip_local) if can_addr == 0 else None
        reliable = _standstill_reliable(board, can_addr, chip)
        for idx, drv in enumerate(board.get("drivers", []) or []):
            om_raw = drv.get("status") if isinstance(drv, dict) else None
            raw = drv_status_raw_by_local_driver.get(idx) if can_addr == 0 else None
            if raw is not None and chip:
                d = decode_driver_status(raw, chip)
            else:
                d = decode_driver_status(om_raw, "rrf")
            live = None
            if reliable and isinstance(om_raw, int):
                live = bool(om_raw & (1 << DRV_STATUS_MAPS["rrf"]["stst"]))
            d["in_idle_live"] = live
            d["enabled"] = (enabled_of_chopconf(chopconf_by_local_driver.get(idx))
                               if can_addr == 0 and chip else None)
            lookup[f"{can_addr}.{idx}"] = d
    return lookup


def _standstill_reliable(board, can_addr, chip):
    """The standstill bit 16 of the object model is only set by TMC drivers: the
    external ones (MB6XD/EXP1XD) never set it and would always look like they
    are running. For CAN boards it is not confirmed that it arrives at the
    object model's rate. It is only trusted on the local board with a known TMC
    chip."""
    return can_addr == 0 and chip is not None


def parse_m122_drivers(m122_text):
    """Extracts the "Driver N: standstill, SG min 0, mspos 312, ..." lines from
    the M122 report (=== Move === section). M122 is a read-only diagnostic
    command (it writes nothing to the driver) -- see the module docstring."""
    out = {}
    for m in _M122_DRIVER_RE.finditer(m122_text or ""):
        idx, status, sg_min, mspos, reads, writes, timeouts = m.groups()
        out[int(idx)] = {
            "state": status.strip(),
            "sg_min": int(sg_min) if sg_min != "n/a" else None,
            "mspos": int(mspos),
            "timeouts": int(timeouts),
        }
    return out


def estimate_cs_current_ma(cs_current, m569, current_ma_configured):
    """Converts CS_actual (0-31, from DRV_STATUS) to an ESTIMATE in mA,
    calibrated against the current CONFIGURED by M906 (current_ma_configured
    -- the same one already shown in the table as "Configured current",
    2700 mA on this machine). The CS -> current relation is LINEAR by the
    Trinamic datasheet formula (I_rms proportional to (CS+1), for a fixed
    GLOBALSCALER/Vfs/Rsense), and RRF documents that iRun=31 (the maximum CS)
    corresponds exactly to 100% of that configured current (confirmed against
    the "100% run" that M906 reports) -- that is the calibration point:

        mA(CS) = current_ma_configured * (CS + 1) / (iRun + 1)

    2026-10-07: BEFORE, this function calibrated against "current" of M569
    (812.5 mA at CS=31 on this machine) instead of M906 -- a user pointed out
    that this "maximum" was BELOW the 2700 mA configured, which makes no sense
    (812.5 < 2700). With gs=32/256 (low GLOBALSCALER) visible in M569, M569's
    "current" does not reliably reflect the real configured current on this
    board/firmware -- it was abandoned as a calibration source. Using M906
    instead is consistent with what the UI already shows (same source for
    "Configured current" and for the 100% of this scale) and avoids the
    self-contradictory number. It is still an ESTIMATE (not a lab measurement):
    the datasheet's linear formula is correct, but the chip may be applying a
    real current different from the configured one via CoolStep/StealthChop at
    any instant -- which is why CS_actual is read live in the first place."""
    if cs_current is None or not m569 or not current_ma_configured or m569.get("irun") is None:
        return None
    irun = m569["irun"]
    if irun < 0:
        return None
    return current_ma_configured * (cs_current + 1) / (irun + 1)


# Last machine position of each axis (letter -> mm) and when it was read.
# It is NO LONGER used to compute the speed (the net displacement over ~1 s
# gives almost 0 in back-and-forth engraving): only to know WHETHER the axis
# moved, when there is no reliable standstill bit for its drivers.
_prev_axis_pos = {"t": None, "pos": {}}

THRESHOLD_OFFSET_MM = 0.005  # less than this between readings = still


def _axis_deltas_from_positions(axes):
    """letter -> (displacement in mm since the previous reading, dt in s)."""
    now = time.monotonic()
    pos = {}
    for ax in axes:
        mp = ax.get("machinePosition")
        if isinstance(mp, (int, float)):
            pos[ax.get("letter")] = float(mp)
    prev_t, prev = _prev_axis_pos["t"], _prev_axis_pos["pos"]
    _prev_axis_pos["t"], _prev_axis_pos["pos"] = now, pos
    out = {}
    if prev_t is None:
        return out
    dt = now - prev_t
    if not (0.2 <= dt <= 5.0):
        return out  # reading too close or too old: not reliable
    for letter, p in pos.items():
        if letter in prev:
            out[letter] = (abs(p - prev[letter]), dt)
    return out


def speed_motion_current(current_move):
    """Vector speed (mm/s) of the move being executed now, from move.currentMove
    (live in the object model; RRF gives 0 if there is no movement). topSpeed
    is the cruise speed already limited by M203/M201/M566; if it came as 0,
    requestedSpeed is used. None if the object model has no currentMove (old
    DSF): then it is not known."""
    if not isinstance(current_move, dict) or not current_move:
        return None
    top = current_move.get("topSpeed") or 0
    req = current_move.get("requestedSpeed") or 0
    return float(top if top > 0 else req)


def axis_in_motion(driver_ids, driver_lookup, offset=None):
    """(True/False/None, source). First the live standstill bit of the axis's
    drivers (if ALL of them are reliable): running if any is not at rest.
    Otherwise, whether the position changed since the previous reading. None
    if there is no way to know (first reading)."""
    live = [(driver_lookup.get(d) or {}).get("in_idle_live") for d in driver_ids or []]
    if live and all(v is not None for v in live):
        return (not all(live)), "standstill"
    if offset is None:
        return None, None
    return offset[0] > THRESHOLD_OFFSET_MM, "position"


def steps_per_rev_resolver(motors_file, default=200):
    """label -> full steps per revolution of that motor. The page "Motors > Advisor" saves, per axis and in general, the steps per revolution of
    the motor (200 = 1.8 degrees, 400 = 0.9 degrees, ...) in the settings file "motors" ({general, axes}); the motor of an axis wins over the
    general one, and a value that is not a sensible number (24 to 1000) is ignored. `default` is the last resort (config.json, 200)."""
    def usable(d):
        if not isinstance(d, dict):
            return None
        try:
            v = int(round(float(d.get("steps_per_rev"))))
        except (TypeError, ValueError):
            return None
        return v if 24 <= v <= 1000 else None
    f = motors_file if isinstance(motors_file, dict) else {}
    general = usable(f.get("general"))
    axes = f.get("axes") if isinstance(f.get("axes"), dict) else {}
    return lambda label: usable(axes.get(label)) or general or default


def _motor_entry(label, steps_per_mm, max_speed_mm_min, acceleration, microstep_value,
                  vector_speed_mm_s, full_steps_per_rev, driver_ids, driver_lookup,
                  m122_by_local_driver, current_ma, percent_current, percent_stst_current,
                  gstat_by_local_driver=None, m569_by_local_driver=None,
                  in_motion=None, offset=None, es_axis=False):
    if not steps_per_mm or not max_speed_mm_min:
        return None

    max_speed_mm_s = max_speed_mm_min / 60.0
    max_freq_hz = max_speed_mm_s * steps_per_mm
    micro = microstep_value or 1
    max_rpm = (max_freq_hz / (full_steps_per_rev * micro)) * 60.0

    # 2026-10-12 (item 5, "pulses ~3 Hz" while engraving): before, with
    # position, the NET displacement over ~1 s was used (in back-and-forth
    # engraving it gives almost 0). Now: speed of the CURRENT move
    # (move.currentMove, live) for the axes that are moving (see
    # axis_in_motion), 0 for the still ones. 2026-10-08: a still Z no longer gets
    # the vector speed of an XY travel (it gave thousands of % -> false red): it
    # stays at 0 by standstill.
    # Cap: the axis's M203 maximum (on a diagonal each axis goes slower than the
    # vector; it can never go faster than its own maximum).
    cap = max_speed_mm_s * 1.02  # tolera redondeos
    if in_motion is False or vector_speed_mm_s == 0:
        current_speed_mm_s = 0.0
        speed_source = "still"
    elif in_motion is None and es_axis:
        # axis without reliable standstill and without a previous position reading
        # (first cycle): it is not known whether it takes part, nothing is invented
        current_speed_mm_s = 0.0
        speed_source = "without_datum"
    elif vector_speed_mm_s is not None:
        current_speed_mm_s = min(vector_speed_mm_s, cap)
        speed_source = "motion_current"
    elif offset is not None:
        # object model without currentMove: all that is left is the average
        current_speed_mm_s = min(offset[0] / offset[1], cap)
        speed_source = "position"
    else:
        current_speed_mm_s = 0.0
        speed_source = "without_datum"
    current_freq_hz = current_speed_mm_s * steps_per_mm
    current_rpm = (current_freq_hz / (full_steps_per_rev * micro)) * 60.0

    pct = (current_speed_mm_s / max_speed_mm_s * 100.0) if max_speed_mm_s > 0 else 0.0
    level = _level(pct)

    gstat_by_local_driver = gstat_by_local_driver or {}
    m569_by_local_driver = m569_by_local_driver or {}
    drivers = []
    for did in driver_ids or []:
        decoded = driver_lookup.get(did, {})
        board, _, idx_str = did.partition(".")
        local_idx = None
        if board == "0":
            try:
                local_idx = int(idx_str)
            except ValueError:
                pass
        m122 = m122_by_local_driver.get(local_idx) if local_idx is not None else None
        gstat = gstat_by_local_driver.get(local_idx) if local_idx is not None else None
        m569 = m569_by_local_driver.get(local_idx) if local_idx is not None else None
        drivers.append({
            "id": did,
            **decoded,
            "m122": m122,
            "gstat": gstat,
            "gstat_supported": local_idx is not None,
            "m569": m569,
            "cs_current_ma": estimate_cs_current_ma(decoded.get("cs_current"), m569, current_ma),
            # Driver at rest: from the stst bit of the same decoded value (so it matches
            # the flags that are shown); if there is none, M122.
            # At rest ola/olb are already discarded (decode_driver_status);
            # the other flags are real at rest too.
            "in_standstill": (decoded.get("standstill")
                              if decoded.get("standstill") is not None
                              else bool(m122 and m122.get("state") == "standstill")),
        })

    return {
        "label": label,
        "steps_per_mm": steps_per_mm,
        "microstepping": micro,
        "acceleration": acceleration,
        "max_speed_mm_min": max_speed_mm_min,
        "max_freq_hz": max_freq_hz,
        "full_steps_per_rev": full_steps_per_rev,
        "max_rpm": max_rpm,
        "current_speed_mm_min": current_speed_mm_s * 60.0,
        "current_freq_hz": current_freq_hz,
        "current_rpm": current_rpm,
        "pct_of_max": pct,
        "level": level,
        "speed_source": speed_source,
        "current_ma": current_ma,
        "percent_current": percent_current,
        "percent_stst_current": percent_stst_current,
        "drivers": drivers,
    }


_KINEMATICS_SHARING_NOTES = {
    "cartesian": (
        M("motor_status_each_motor_independent_straight_cut")
    ),
    "coreXY": (
        M("motor_status_coupled_any_movement_x_y_moves")
    ),
    "coreXZ": (
        M("motor_status_coupled_like_corexy_between_x_z")
    ),
    "linearDelta": (
        M("motor_status_coupled_any_xyz_move_moves_3_towers")
    ),
    "rotaryDelta": (
        M("motor_status_coupled_like_linear_delta_3_motors")
    ),
}


def kinematics_sharing_note(kinematics_name):
    return _KINEMATICS_SHARING_NOTES.get(
        kinematics_name,
        M("motor_status_kinematics_not_recognized_by_plugin"),
    )


def compute_motor_report(status, full_steps_per_rev=200, m122_text=None, steps_per_rev_of=None,
                          gstat_by_local_driver=None, loop_hz_max_ever=None,
                          m569_by_local_driver=None, drv_status_raw_by_local_driver=None,
                          chip_local=None, chopconf_by_local_driver=None):
    move = status.get("move", {}) or {}
    global_vars = status.get("global", {}) or {}
    current_move = move.get("currentMove") or {}
    kinematics_name = (move.get("kinematics", {}) or {}).get("name", "unknown")

    # requestedSpeed: what the G-code asked for (F) for this move, BEFORE
    # applying limits. topSpeed: the cruise speed the RRF planner will actually
    # use, AFTER applying M203 (per-axis limit), M201 (acceleration) and M566
    # (jerk/corners) -- topSpeed is never greater than requestedSpeed, and if it
    # is quite a bit lower it means one of those limits is braking the move below
    # what was asked. Both are exposed separately (besides the usual combined
    # maximum) so that the difference can be seen in the UI.
    requested_speed_mm_s = current_move.get("requestedSpeed", 0) or 0
    top_speed_mm_s = current_move.get("topSpeed", 0) or 0
    vector_speed_mm_s = max(requested_speed_mm_s, top_speed_mm_s)
    # the one distributed to the moving axes (None = no currentMove)
    speed_current = speed_motion_current(move.get("currentMove"))
    deltas = _axis_deltas_from_positions(move.get("axes", []) or [])

    driver_lookup = _driver_lookup(status, drv_status_raw_by_local_driver, chip_local,
                                   chopconf_by_local_driver)
    m122_by_local_driver = parse_m122_drivers(m122_text) if m122_text else {}

    entries = []
    for ax in move.get("axes", []) or []:
        if not ax.get("visible", True):
            continue
        micro = (ax.get("microstepping") or {}).get("value", 1)
        offset = deltas.get(ax.get("letter"))
        in_mov, _source = axis_in_motion(ax.get("drivers"), driver_lookup, offset)
        e = _motor_entry(
            ax.get("letter", "?"), ax.get("stepsPerMm"), ax.get("speed"),
            ax.get("acceleration"), micro, speed_current, (steps_per_rev_of(ax.get("letter", "?")) if steps_per_rev_of else full_steps_per_rev),
            ax.get("drivers"), driver_lookup, m122_by_local_driver,
            ax.get("current"), ax.get("percentCurrent"), ax.get("percentStstCurrent"),
            gstat_by_local_driver, m569_by_local_driver,
            in_motion=in_mov, offset=offset, es_axis=True,
        )
        if e:
            entries.append(e)

    for i, ex in enumerate(move.get("extruders", []) or []):
        micro = (ex.get("microstepping") or {}).get("value", 1)
        in_mov, _source = axis_in_motion(ex.get("drivers"), driver_lookup)
        e = _motor_entry(
            f"E{i}", ex.get("stepsPerMm"), ex.get("speed"),
            ex.get("acceleration"), micro, speed_current, (steps_per_rev_of(f"E{i}") if steps_per_rev_of else full_steps_per_rev),
            ex.get("drivers"), driver_lookup, m122_by_local_driver,
            ex.get("current"), ex.get("percentCurrent"), ex.get("percentStstCurrent"),
            gstat_by_local_driver, m569_by_local_driver,
            in_motion=in_mov,
        )
        if e:
            entries.append(e)

    # Combined pulses/s being generated NOW, adding up all the active motors --
    # it is not a new measurement, it is just the sum of current_freq_hz of each
    # entry (already computed above from the standard object model). Together
    # with loop_hz_max_ever (the highest ceiling the firmware measured in some
    # previous M122, see motor_poller.py) it gives a "% of maximum capacity" --
    # but it is an OBSERVED capacity, not a datasheet figure: it is only reliable
    # after the machine has been seen cutting/moving fast at least once; before
    # that the "maximum" is just the background loop at rest and the % comes out
    # artificially high. It is exposed anyway, but with that warning for the UI.
    combined_current_freq_hz = sum(e["current_freq_hz"] for e in entries)
    pct_of_board_capacity = None
    if loop_hz_max_ever:
        pct_of_board_capacity = (combined_current_freq_hz / loop_hz_max_ever) * 100.0

    return {
        "mode": global_vars.get("selectedMode"),
        "kinematics": kinematics_name,
        "kinematics_note": kinematics_sharing_note(kinematics_name),
        "vector_speed_mm_s": vector_speed_mm_s,
        "requested_speed_mm_s": requested_speed_mm_s,
        "top_speed_mm_s": top_speed_mm_s,
        "entries": entries,
        "board_capacity": parse_m122_board_capacity(m122_text),
        "combined_actual_freq_hz": combined_current_freq_hz,
        "loop_hz_max_ever": loop_hz_max_ever,
        "pct_of_board_capacity": pct_of_board_capacity,
        "boards": _aggregate_board_motion(board_inventory(status, lookup=driver_lookup), entries),
        "updated_at": None,  # completed by motor_poller.py with the real time of the cycle
    }
