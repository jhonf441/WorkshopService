"""API operations of the power off and the restart: power.after_job / timer / timer_cancel / method (power_config), power.off (power_off)
and power.full_reset (power_reset). api_ops.init registers them through build(ctx), like energy_ops. The class, arguments, roles
(permissions.py) and flags of each operation are the ones they had when they were handlers/shutdown.py, shutdown_all.py and reset_all.py.
"""
import power_config
import power_off
import power_reset
from workshop_api import POWER, WRITE, Arg, Op


def _armed_of(v):
    """The value of power.after_job -> True (arm), False (disarm) or None (toggle)."""
    if isinstance(v, str):
        s = v.strip().lower()
        return None if s == "toggle" else s in ("1", "true", "on", "yes", "arm")
    return bool(v)


def build(ctx):
    """The operations; ctx is api_ops._ctx (bridge, config)."""
    S, I, B = "str", "int", "bool"
    a = Arg

    def after_job(args, c):
        return power_config.after_job(ctx["bridge"], ctx["config"], _armed_of(args.get("armed")))

    def timer(args, c):
        return power_config.timer(ctx["bridge"], ctx["config"], args["minutes"])

    def timer_cancel(args, c):
        return power_config.timer_cancel(ctx["bridge"], ctx["config"])

    def method(args, c):
        return power_config.method(ctx["bridge"], ctx["config"], method=args.get("method"), power_off_system=args.get("power_off_system"),
                                   relay_output=args.get("relay_output"), relay_value=args.get("relay_value"))

    def off(args, c):
        return power_off.power_off(ctx["bridge"], ctx["config"])

    def full_reset(args, c):
        return power_reset.restart_all(ctx["bridge"])

    return [
        Op("power.after_job", after_job, WRITE, {"armed": a("any", True, desc="true arms, false disarms, \"toggle\" switches the current state.")},
           "Arms or disarms the power off at the end of the current job (or of the next one that starts); sys/daemon.g then runs the power off of power.off. "
           "Saved, mirrored in global.powerOffOnFinish and logged in Activity.", macro=True),
        Op("power.timer", timer, WRITE,
           {"minutes": a(I, True, min=1, max=720, desc="Minutes from now until the power off, 1 to 720.")},
           "Schedules the power off of the whole machine in N minutes (the same power off as power.off; with a job running at that time it arms "
           "power.after_job instead). Saved, survives a restart of the service; logged in Activity."),
        Op("power.timer_cancel", timer_cancel, WRITE, {},
           "Cancels the scheduled power off timer, if any (logged in Activity when there was one)."),
        Op("power.method", method, WRITE,
           {"method": a(S, choices=("auto", "meter", "relay", "pson"),
                        desc="auto (the meter if one is configured, else the relay if set, else PS_ON if the board has it, else only the system), "
                             "meter (the Tuya meter cuts the whole machine), relay (an output of the board cuts all the power), "
                             "pson (M81 switches off the power supply controlled by PS_ON)."),
            "power_off_system": a(B, desc="With PS_ON, also shut the Raspberry Pi (the system) down; the meter and relay methods always shut it down."),
            "relay_output": a(I, min=0, max=63, desc="Board output that drives the relay (the P number of its M950 line), 0 to 63."),
            "relay_value": a(I, min=0, max=1, desc="Value written with M42 to that output to CUT the power: 0 or 1.")},
           "Chooses how power.off, the timer and the power off after the job cut the power. Only the arguments given change; saved, logged in Activity; "
           "the answer says what will happen."),
        Op("power.off", off, POWER, {},
           "Cuts the power of the whole machine with the chosen method (power.method): extra meters first, then sync, cut and system shutdown. "
           "Whatever is running stops. Needs a confirmation.", confirm={"level": 3, "key": "power.off"}, macro=True),
        Op("power.full_reset", full_reset, POWER, {},
           "Restarts everything by software without cutting the power: asks the system to reboot and resets the board with M999. "
           "Whatever is running stops and homing is lost. Needs a confirmation.", confirm={"level": 3, "key": "power.full_reset"}, macro=True),
    ]
