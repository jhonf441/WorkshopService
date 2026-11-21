#!/usr/bin/env python3
"""Read-only probe: which /proc entries of OTHER processes can the service read under its AppArmor profile?

It answers one question: can the service measure CPU and memory of a process, and of which ones? It only READS; it never writes, signals or
changes anything. Run it as the user `dsf` inside the profile of the service (it needs sudo, so the owner runs it):

    sudo -u dsf aa-exec -p '/opt/dsf/plugins/WorkshopService/**' -- /usr/bin/python3 tools/proc_probe.py

(copy the file somewhere `dsf` can read first, for example /tmp). If `aa-exec -p` refuses, run it as `dsf` without the profile and the result
only tells what the system allows, not AppArmor. The script says which of the two it was (the profile it runs under, read from /proc/self/attr/current).

For each process of a fixed list of programs (the Duet servers, this service, the G-code bridge, plus the process 1 and one root process) it
tries these files and prints OK or the error:
  stat, statm, status, cmdline   what a CPU / memory measurement needs (stat: utime and stime; statm: resident pages)
  fd                             the directory of open files (what read_dcs of health_poller.py uses for duetcontrolserver)
Afterwards, the denials the kernel logged show in the system log page of the System health plugin (unit "Kernel", text "DENIED"), or in
`journalctl -k | grep DENIED | grep Workshop`.
"""
import errno
import os

WANTED = ("DuetControlServ", "DuetWebServer", "DuetPluginServi", "python3", "python", "systemd", "chromium", "labwc")
FILES = ("stat", "statm", "status", "cmdline")


def attempt(path, listing=False):
    try:
        if listing:
            os.listdir(path)
        else:
            with open(path, "rb") as f:
                f.read(256)
        return "OK"
    except OSError as e:
        return errno.errorcode.get(e.errno, str(e.errno))


def owner_of(pid):
    try:
        return os.stat("/proc/%s" % pid).st_uid
    except OSError:
        return None


def main():
    me = os.getuid()
    try:
        with open("/proc/self/attr/current") as f:
            profile = f.read().strip()
    except OSError:
        profile = "(unknown)"
    print("running as uid %s, profile: %s" % (me, profile))
    rows = []
    try:
        pids = sorted(int(p) for p in os.listdir("/proc") if p.isdigit())
    except OSError as e:
        print("cannot list /proc: %s" % errno.errorcode.get(e.errno, e.errno))
        return 1
    seen = {}
    for pid in pids:
        comm = ""
        try:
            with open("/proc/%d/comm" % pid) as f:
                comm = f.read().strip()
        except OSError:
            pass
        if pid != 1 and comm not in WANTED:
            continue
        key = (comm, owner_of(pid))
        if key in seen and pid != 1:
            continue  # one process per program and owner is enough
        seen[key] = pid
        res = {name: attempt("/proc/%d/%s" % (pid, name)) for name in FILES}
        res["fd"] = attempt("/proc/%d/fd" % pid, listing=True)
        rows.append((pid, comm, owner_of(pid), res))
    print("%-7s %-16s %-6s %s" % ("pid", "program", "owner", "  ".join("%-6s" % n for n in FILES + ("fd",))))
    for pid, comm, uid, res in rows:
        print("%-7d %-16s %-6s %s" % (pid, comm[:16], uid, "  ".join("%-6s" % res[n] for n in FILES + ("fd",))))
    ok_stat = [r for r in rows if r[3]["stat"] == "OK" and r[3]["statm"] == "OK"]
    print()
    print("CPU and memory can be measured for: %s" % (", ".join("%s(%d)" % (r[1], r[0]) for r in ok_stat) or "none"))
    print("CPU and memory are blocked for:      %s" % (", ".join("%s(%d)" % (r[1], r[0]) for r in rows if r not in ok_stat) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
