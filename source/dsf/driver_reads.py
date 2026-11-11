"""The ONLY place that talks to the driver chips: read-only reads of one local driver through the bridge.

  - M569.2 P<n> R<reg> asks for the raw value of a register (GSTAT, DRV_STATUS, CHOPCONF). It is a READ: no function here takes a value to
    write, so none can build a "V" by accident (test_driver_reads checks it on the AST). NEVER add a parameter that carries a value.
  - M569 P<n> with nothing else is a report of the driver configuration (nothing to do with M569.2).

Everything else (decoding, report) is in the pure modules. Split out of motor_status.py (F6b), same code.
"""
import re

from tmc_decode import dc42_reference

_M569_2_READ_RE = re.compile(r"Register 0x[0-9A-Fa-f]+ value 0x([0-9A-Fa-f]+)")
GSTAT_REGISTER = 1  # GSTAT: identical in TMC2209 and TMC5160 (confirmed in both datasheets)
DRV_STATUS_REGISTER = 111  # 0x6F: DRV_STATUS, identical in TMC2209 and TMC5160 (confirmed in both datasheets)

CHOPCONF_REGISTER = 108  # 0x6C: CHOPCONF, read and write in TMC2160/5160 and TMC2209 (both datasheets)


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
