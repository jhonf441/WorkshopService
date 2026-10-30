"""
Internal implementation of the API operation(s) sound.beep (api_ops.py maps their named
arguments to the one-letter parameters below).

Plays a pattern of beeps via M300 (DWC plays it through the speaker on
any screen where it is open, without additional hardware).

Usage: <params> S"ok"|"done"|"error"|"attention"
Meant to be placed at the end of a job or before a manual pause,
as an audible notice that does not depend on looking at the screen or the phone.

"""
import threading
import time

PATTERNS = {
    "ok": [(1000, 150)],
    "done": [(1000, 100), (0, 60), (1500, 100), (0, 60), (2000, 150)],
    "error": [(400, 300), (0, 100), (400, 300)],
    "attention": [(800, 100), (0, 80), (800, 100), (0, 80), (800, 100)],
}


def _play(seq, bridge):
    for freq, dur in seq:
        if freq > 0:
            bridge.send(f'M300 P{dur} S{freq}')
        time.sleep(dur / 1000)


def run(params, bridge, config):
    pattern = str(params.get("S", "ok")).strip().lower()
    seq = PATTERNS.get(pattern, PATTERNS["ok"])
    # In another thread: the sequence has several M300s with pauses in
    # between, there is no point blocking the resolution of the API call for that.
    threading.Thread(target=_play, args=(seq, bridge), daemon=True).start()
    return f"Beep '{pattern}' reproducido"
