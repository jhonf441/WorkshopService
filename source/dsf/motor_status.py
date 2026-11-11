"""
Facade of the motor status (F6b). The code lives in tmc_decode (DRV_STATUS decoding), m122_parse (M122 text), driver_reads
(the only read-only M569.2 / M569 reads) and motor_report (the report); this module keeps the texts and fetch_status and re-exports
every name that motor_poller, the pages and the tests use.

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
import real_mode
import json
import re
import time
from messages import M
from tmc_decode import (  # noqa: F401  (facade: the names other modules and tests use)
    DC42_MB6HC_RRF32_KHZ, FAULT_TEXT_KEYS, DRV_STATUS_MAPS, CHIP_BY_BOARD, CHOPCONF_TOFF_MASK,
    dc42_reference, chip_of_board, enabled_of_chopconf, decode_driver_status as _decode_driver_status)
from m122_parse import parse_m122_board_capacity, parse_m122_drivers  # noqa: F401
from driver_reads import (  # noqa: F401
    GSTAT_REGISTER, DRV_STATUS_REGISTER, CHOPCONF_REGISTER, read_gstat, read_drv_status_raw, read_chopconf_raw, read_m569)
from motor_report import (  # noqa: F401
    THRESHOLD_ALERT_PCT, THRESHOLD_LIMIT_PCT, THRESHOLD_OFFSET_MM, VIN_MIN_DRIVERS_V,
    board_local, local_driver_indices, drivers_without_power_supply, estimate_cs_current_ma,
    speed_motion_current, axis_in_motion, steps_per_rev_resolver,
    board_inventory as _board_inventory, compute_motor_report as _compute_motor_report,
    motor_entry as _motor_entry, prev_axis_pos as _prev_axis_pos)

# The pure modules never import `messages` (that would put them in its import cycle): the messages are built here, once, at import like
# before, and handed in. Same objects, same languages as when this was one file.
_FAULT_MESSAGES = {msg_key: M(msg_key) for msg_key, _severity in FAULT_TEXT_KEYS.values()}
DRIVER_FAULTS = {key: (_FAULT_MESSAGES[msg_key], severity) for key, (msg_key, severity) in FAULT_TEXT_KEYS.items()}

# Compatibility: list of (bit, key, text, severity) of RRF's format.
DRIVER_STATUS_BITS = [
    (bit, key) + DRIVER_FAULTS[key] for bit, key in DRV_STATUS_MAPS["rrf"]["faults"]
]


def _fault_label(msg_key):
    return _FAULT_MESSAGES[msg_key]


def decode_driver_status(status_raw, fmt="rrf"):
    """Decodes a driver state with the map of `format` (see DRV_STATUS_MAPS): "rrf" for boards[].drivers[].status of the object model,
    "tmc51xx"/"tmc22xx" for the raw DRV_STATUS of M569.2. If there is no value or the format is not known, it invents nothing: no flags
    and with the fields at None."""
    return _decode_driver_status(status_raw, fmt, _fault_label)


def fetch_status():
    import machine_state  # single DSF subscription: in memory, no request

    return machine_state.get_status()


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


def board_inventory(status, drv_status_raw_by_local_driver=None, chip_local=None, lookup=None):
    """Inventory of ALL connected boards and ALL their drivers (see motor_report.board_inventory), with the fault texts."""
    return _board_inventory(status, drv_status_raw_by_local_driver, chip_local, lookup, text_of=_fault_label)


def compute_motor_report(status, full_steps_per_rev=200, m122_text=None, steps_per_rev_of=None,
                         gstat_by_local_driver=None, loop_hz_max_ever=None,
                         m569_by_local_driver=None, drv_status_raw_by_local_driver=None,
                         chip_local=None, chopconf_by_local_driver=None):
    """The motor report (see motor_report.compute_motor_report), with the fault texts and the kinematics notes."""
    return _compute_motor_report(
        status, full_steps_per_rev, m122_text, steps_per_rev_of, gstat_by_local_driver, loop_hz_max_ever,
        m569_by_local_driver, drv_status_raw_by_local_driver, chip_local, chopconf_by_local_driver,
        text_of=_fault_label, kinematics_note=kinematics_sharing_note)
