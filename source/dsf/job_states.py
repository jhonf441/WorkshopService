"""The statuses of the board that mean "a job is on": ONE place, named by what the question is, so the modules stop keeping their own lists
(about 13 copies existed and they disagreed). A set that is different ON PURPOSE has its own name and its reason here; test_job_states.py
freezes every one of them.
"""

# a file job occupies the machine, a paused one included: nothing that moves or reconfigures may start (config guard, live job, job trace,
# the motors enable, the shutdown timer, the machine safety item)
ACTIVE = frozenset({"processing", "simulating", "paused", "pausing", "resuming", "cancelling"})

# the same plus a tool change in progress: the calibrations that move axes (height, work area) are refused during it too
ACTIVE_OR_TOOL_CHANGE = ACTIVE | {"changingTool"}

# a file job is MOVING the axes right now: "paused" is not in it on purpose (the jog is allowed while a job is paused), see jog_move.JOG_STATUSES
MOVING_FILE = frozenset({"processing", "simulating", "pausing", "resuming", "cancelling"})

# job_poller: the states that open and close a job in the history. pausing and cancelling are not here on purpose: a job that is
# stopping has not ended yet and must not be counted twice when it goes on to paused / idle
POLLER_ACTIVE = frozenset({"processing", "simulating", "paused", "resuming"})

# camera relay: the states in which the relay keeps its higher frame rate for the job (a cancelling job no longer needs it)
CAMERA_ACTIVE = frozenset({"processing", "paused", "pausing", "resuming", "simulating"})
