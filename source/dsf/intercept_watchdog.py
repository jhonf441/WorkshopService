"""In-process watchdog of the G-code interception (A-12).

DuetControlServer holds a intercepted code until the service answers it (ignore or resolve). If the service hangs while it handles
one (a lock that never frees, a blocked call), every code of that channel waits behind it and DWC shows buttons stuck in
"sending" until DSF is restarted. The service is a DSF plugin process (DSF starts it, `sbcAutoRestart` revives it), so there is no systemd
unit of ours to give a WatchdogSec to: the watchdog is a thread of the process itself.

The interception loop calls begin() when it takes a code and end() when it has answered it. A thread calls check() every second; when a
code has been in progress longer than LIMIT_S it runs the release function (answer the code with an error, hand back what is queued, close
the connection) and then the exit function, which ends the process so DSF starts it again. Both functions are injected, so a test needs no DSF.
"""
import threading
import time

LIMIT_S = 20.0        # handling one code takes milliseconds; the sockets of the loop time out in 3 s


class InterceptWatchdog:
    def __init__(self, release, exit_process, log=print, limit_s=LIMIT_S, clock=time.monotonic):
        self._release = release
        self._exit = exit_process
        self._log = log
        self.limit_s = limit_s
        self._clock = clock
        self._since = None
        self._key = None
        self._lock = threading.Lock()
        self.fired = False

    def begin(self, key):
        with self._lock:
            self._since, self._key = self._clock(), key

    def end(self):
        with self._lock:
            self._since = self._key = None

    def check(self):
        """True when it fired (the process is going down)."""
        with self._lock:
            since, key = self._since, self._key
        if since is None or self._clock() - since <= self.limit_s:
            return False
        self.fired = True
        self._log("interception watchdog: %s has been in progress for %d s, releasing the channel and restarting the service"
                  % (key, self._clock() - since))
        try:
            self._release()
        except Exception as e:  # noqa: BLE001 - the exit below must happen whatever the release does
            self._log("interception watchdog: release failed: %s" % e)
        self._exit()
        return True

    def run(self, stop=None):
        while not (stop and stop.is_set()):
            time.sleep(1.0)
            if self.check():
                return
