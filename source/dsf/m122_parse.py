"""Parsing of the M122 diagnostic text (pure, no I/O): the per-driver lines ("SG min" is a number or the literal n/a) and the pulse
generator section (loop frequency, hiccups). M122 writes nothing to the drivers. Split out of motor_status.py (F6b), same code."""
import re

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
