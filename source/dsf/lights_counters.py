"""
Status strip, the traffic counters (published in servicesInternal.luces). They live apart, with no import of the service, so that heartbeats.py can read them without a cycle.
"""
import threading
import time


# ---------------------------------------------------------------------------
# IPC counters (published in servicesInternal.luces)
# ---------------------------------------------------------------------------
# What this module asks of DSF / the board, to measure the cost on the Pi:
#   reads     spot reads of the object model (leer_puntual, RS485 data) and the
#             one-off M98 that tells daemon.g the Pi paints
#   commands  G-code sent to the board (M150, macros)
#   publishes plugin data written (set_status)
# The idle paint loop makes none of them: it reads the shared subscription
# (state_machine, in memory) and only talks when a frame really changed.
COUNTER = {"reads": 0, "commands": 0, "publishes": 0, "since": time.time()}


COUNTER_TS = {"reads": [], "commands": [], "publishes": []}


COUNTER_LOCK = None


def count(type_name, n=1, current_time=None):
    global COUNTER_LOCK
    if COUNTER_LOCK is None:
        COUNTER_LOCK = threading.Lock()
    current_time = time.time() if current_time is None else current_time
    with COUNTER_LOCK:
        COUNTER[type_name] += n
        COUNTER_TS[type_name].extend([current_time] * n)
        # keep only the last minute
        cut = current_time - 60
        while COUNTER_TS[type_name] and COUNTER_TS[type_name][0] < cut:
            COUNTER_TS[type_name].pop(0)


def ipc_stats(current_time=None):
    """{reads_min, commands_min, publishes_min, total_*}: calls of the last
    minute and since the service started."""
    current_time = time.time() if current_time is None else current_time
    out = {"since_s": int(current_time - COUNTER["since"])}
    for k in ("reads", "commands", "publishes"):
        out[k + "_min"] = len([x for x in COUNTER_TS[k] if x >= current_time - 60])
        out["total_" + k] = COUNTER[k]
    return out


def counters_a_zero():
    """For tests."""
    for k in ("reads", "commands", "publishes"):
        COUNTER[k] = 0
        COUNTER_TS[k].clear()
    COUNTER["since"] = time.time()
