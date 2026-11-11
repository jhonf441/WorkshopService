"""The ONE launcher of operating-system processes (decision D-24 of the redesign plan), layer L0: standard library only.

Every module that needs to run a program calls `run()` here instead of importing subprocess. The gateway:
  - accepts only an argv LIST of strings (never a shell string, never `shell=True`);
  - requires a timeout (a launch without a deadline can hang a service thread for ever);
  - checks the program against a CLOSED list of executables (ALLOWED). It is compared by base name; a path is accepted only when it
    points into a fixed system folder (SYSTEM_DIRS), so a relative or arbitrary path never runs. `nice -n N <program>` is allowed
    as a wrapper, and the wrapped program must be on the list too.
A policy violation raises OSGatewayError. Everything the operating system raises (FileNotFoundError, TimeoutExpired...) is passed
on UNCHANGED: each caller already decides what it catches, and this module must not change that.

Adding an executable here is a security decision: add it to ALLOWED with the module that needs it.
"""
import os
import subprocess

# base name -> the modules that launch it today (documentation; the check only uses the keys)
ALLOWED = {
    "ffmpeg": "camera_assembly, camera_notice, camera_timelapse",
    "nice": "camera_assembly, camera_notice, camera_timelapse (wrapper of ffmpeg)",
    "systemctl": "bridge_service, health_poller",
    "journalctl": "health_poller, preflight",
    "vcgencmd": "health_poller",
    "nmcli": "health_poller",
    "ip": "health_poller",
    "ping": "health_poller",
    "ss": "health_poller",
    "timedatectl": "health_poller",
    "pinctrl": "pi_leds",
    "dpkg-query": "preflight",
    "dotnet": "preflight",
}
SYSTEM_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/local/sbin")
WRAPPERS = ("nice",)

# Re-exported so a caller can catch what the OS raises without importing subprocess.
SubprocessError = subprocess.SubprocessError
TimeoutExpired = subprocess.TimeoutExpired
CompletedProcess = subprocess.CompletedProcess


class OSGatewayError(Exception):
    """The launch was refused by the policy of the gateway (nothing was started)."""


def _base(program):
    if not isinstance(program, str) or not program:
        raise OSGatewayError("executable must be a non-empty string")
    if "/" in program or "\\" in program:
        folder, name = program.replace("\\", "/").rsplit("/", 1)
        if folder not in SYSTEM_DIRS:
            raise OSGatewayError(f"executable path not allowed: {program!r}")
        return name
    return program


def check_argv(argv):
    """Raises OSGatewayError unless `argv` is a list of strings whose program (behind `nice -n N`) is on the closed list."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise OSGatewayError("argv must be a non-empty list of strings (no shell strings)")
    rest = argv
    while True:
        name = _base(rest[0])
        if name not in ALLOWED:
            raise OSGatewayError(f"executable not allowed: {name!r}")
        if name not in WRAPPERS:
            return name
        if len(rest) < 4 or rest[1] != "-n" or not rest[2].lstrip("-").isdigit():
            raise OSGatewayError("a wrapper must be used as: nice -n <number> <program> ...")
        rest = rest[3:]


def run(argv, *, timeout, input=None, check=False, env=None, cwd=None, text=True, **extra):
    """subprocess.run with the policy above. Output is always captured; `text` chooses str (default) or bytes.
    Returns the CompletedProcess of subprocess.run; its exceptions are not translated."""
    if "shell" in extra:
        raise OSGatewayError("shell is not allowed")
    if extra:
        raise OSGatewayError("unknown option(s): " + ", ".join(sorted(extra)))
    if timeout is None or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise OSGatewayError("a positive timeout is required")
    check_argv(argv)
    return subprocess.run(argv, capture_output=True, text=text, timeout=timeout, input=input, check=check, env=env, cwd=cwd)
