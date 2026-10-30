"""
Internal implementation of the API operation(s) power.full_reset (api_ops.py maps their named
arguments to the one-letter parameters below).

Restarts EVERYTHING by software (WITHOUT cutting the power): resets the Duet3
board (M999) and then restarts the Raspberry Pi. The user explicitly
confirmed that this button is software only -- it does not involve the
Tuya meter.

Why not a power cut + reconnection (like shutdown_all.py) instead of
this: confirmed (2026-10-07, checked twice separately) that the Tuya meter
"Impresora" has NO remote-restart dp AT ALL -- neither in the local schema
(tinytuya d.status()) nor in the "functions" that the Tuya Cloud API
publishes for this product (category "dlq"): switch_prepayment,
clear_energy, charge_energy, switch, alarm_set_1, alarm_set_2. Nothing of
countdown/timer/reboot. The only thing the meter can do is cut/restore the
switch (as shutdown_all.py already does) -- that is a physical reset, not
what this button does.

Usage: <params>

It requires a sudo NOPASSWD rule for /usr/sbin/reboot -- add it to the SAME
line that already has poweroff/shutdown in /etc/sudoers.d/dsf-power
(see shutdown_all.py): "dsf ALL=(ALL) NOPASSWD: /usr/sbin/poweroff,
/usr/sbin/shutdown, /usr/sbin/reboot".

"""
import os
import subprocess
import time

import activity
from messages import M, J, B

RESET_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reset_total.log")  # plugin folder (new or old Id)


def _log(msg):
    with open(RESET_LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}\n")


def run(params, bridge, config):
    with open(RESET_LOG, "w") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] reset_total started\n")

    activity.log_event(bridge, "power", M("restart_all"))

    # ORDER (fixed 2026-10-09): FIRST ask systemd to restart the
    # Pi and AFTER that the M999. Before it was the other way round (M999, 2 s pause, reboot) and
    # the Pi never restarted: M999 in SBC mode also restarts
    # duetcontrolserver, and DCS kills the plugins (this process) ~1 s after
    # the "Resetting controller" -- it died in the pause, before the reboot
    # (it happened twice on 2026-10-09: reset_total.log ended at "M999
    # sent" and the Pi stayed on the same boot). "reboot" returns as soon as
    # systemd (PID 1) accepts the request: even if this process is killed afterwards, the
    # restart is already under way and cannot be cut.
    os.sync()
    r = subprocess.run(
        ["sudo", "-n", "reboot"],
        capture_output=True, text=True, timeout=10,
    )
    _log(f"reboot rc={r.returncode} stderr={r.stderr.strip()}")
    if r.returncode != 0:
        raise RuntimeError(M("reset_all_could_not_restart_system", rc=r.returncode, stderr=r.stderr.strip(), log=RESET_LOG))

    # Resets the Duet3 board while DCS is still up (systemd takes a few
    # seconds to bring the services down). M999 drops the connection as soon as the board
    # restarts -- that is expected, not an error. If it did not come out, the Pi
    # restarts anyway (the important part) and the board stays as it was.
    try:
        bridge.send("M999")
        _log("M999 sent, answer received without error")
    except Exception as e:
        _log(f"M999 sent (connection cut by the reset itself, expected): {e}")

    return M("reset_all_board_reset_system_restarting")
