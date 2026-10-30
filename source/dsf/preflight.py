"""Pre-installation check (F2, 2026-10-21): what a machine that is not the author's must have.

run(system, options) -> {"ok": bool, "summary": {"ok", "warn", "error"}, "items": [...]}
Each item: {"id", "status": "ok"|"warn"|"error", "message", "fix", "key", "fix_key", "params"}.
message and fix are texts in the current language (messages.py keys preflight_*, es + en); fix is
the solution in words. The same code serves the API operation preflight.run (reads the installed
machine) and the command line tools/preflight.py (run on the Pi before installing).

Everything that touches the machine goes through a `System` object, so the tests give it a fake.
The base is always Duet 3 + Raspberry Pi in SBC mode, DSF 3.6 or 3.7: this is not a check for
other boards. DSF 3.7 additionally needs .NET 10 and the memory cgroup (checked only when DSF is 3.7 or newer).
"""
import errno
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys

import paths
from messages import M

OK, WARN, ERROR = "ok", "warn", "error"
MIN_DSF = (3, 6)
DSF_37 = (3, 7)
MIN_PYTHON_DSF_37 = (3, 11)  # dsf-python 3.7 says python_requires >=3.11
DOTNET_MAJOR_DSF_37 = 10
DOTNET_DIRS = ("/usr/share/dotnet", "/usr/lib/dotnet", "/opt/dotnet")
CGROUP_CONTROLLERS = "/sys/fs/cgroup/cgroup.controllers"
PROC_CMDLINE = "/proc/cmdline"
MIN_PYTHON = (3, 9)
PORTS = (("camera", 8090), ("vision", 8095))
MIN_FREE_MB = 200
WARN_FREE_MB = 2000
SUDOERS_FILE = "/etc/sudoers.d/dsf-power"
POLKIT_DIR = "/etc/polkit-1/rules.d"
APPARMOR_FLAG = "/sys/module/apparmor/parameters/enabled"
# DSF accepts ONE condition per dependency ("name==1.2"), no ranges and no lists of conditions
DEP_RX = re.compile(r"^([A-Za-z0-9_.-]+)(?:==([A-Za-z0-9_.+-]+))?$")


class System:
    """What the checks ask of the machine. The real one; tests override the methods."""

    def python_version(self):
        return sys.version_info[:2]

    def exists(self, p):
        return os.path.exists(p)

    def isdir(self, p):
        return os.path.isdir(p)

    def writable(self, p):
        return os.access(p, os.W_OK | os.X_OK)

    def read(self, p):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def listdir(self, p):
        try:
            return os.listdir(p)
        except OSError:
            return []

    def which(self, name):
        return shutil.which(name)

    def has_module(self, name):
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def pip_version(self, name):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    def run(self, argv, timeout=8):
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout
        except (OSError, subprocess.SubprocessError):
            return None, ""

    def port_free(self, port):
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError as e:
            return e.errno != errno.EADDRINUSE
        finally:
            s.close()

    def free_mb(self, p):
        try:
            return shutil.disk_usage(p).free // (1024 * 1024)
        except OSError:
            return None

    def euid(self):
        return os.geteuid() if hasattr(os, "geteuid") else None


def item(ident, status, key, fix_key=None, **params):
    return {"id": ident, "status": status, "message": M(key, **params), "fix": M(fix_key, **params) if fix_key else None,
            "key": key, "fix_key": fix_key, "params": params}


def _ver(text):
    nums = re.findall(r"\d+", str(text or ""))[:3]
    return tuple(int(x) for x in nums)


# ---- checks (each returns a list of items) ----

def dsf_version(s, opts):
    """DSF version text from the options or dpkg ("" when unknown)."""
    found = (opts.get("dsf_version") or "").strip()
    if not found:
        rc, out = s.run(["dpkg-query", "-W", "-f=${Version}", "duetsoftwareframework"])
        found = out.strip() if rc == 0 else ""
    return found


def is_dsf_37(s, opts):
    """True when DSF is known to be 3.7 or newer (the 3.7-only checks do not run for 3.6 or an unknown version)."""
    found = dsf_version(s, opts)
    return bool(found) and _ver(found)[:2] >= DSF_37


def check_dsf(s, opts):
    need = ".".join(map(str, MIN_DSF))
    found = dsf_version(s, opts)
    if not found:
        return [item("dsf_version", WARN, "preflight_dsf_unknown", "preflight_fix_dsf_install", need=need)]
    if _ver(found)[:2] < MIN_DSF:
        return [item("dsf_version", ERROR, "preflight_dsf_old", "preflight_fix_dsf_update", found=found, need=need)]
    return [item("dsf_version", OK, "preflight_dsf_ok", found=found, need=need)]


def check_dotnet(s, opts):
    """DSF 3.7 runs on .NET 10 (it dropped .NET 9). Not asked for DSF 3.6."""
    if not is_dsf_37(s, opts):
        return []
    majors = set()
    for root in DOTNET_DIRS:
        for name in s.listdir(root + "/shared/Microsoft.NETCore.App"):
            m = re.match(r"(\d+)\.", name)
            if m:
                majors.add(int(m.group(1)))
    rc, out = s.run(["dotnet", "--list-runtimes"])
    if rc == 0:
        for m in re.finditer(r"Microsoft\.NETCore\.App (\d+)\.", out or ""):
            majors.add(int(m.group(1)))
    need = DOTNET_MAJOR_DSF_37
    if need in majors or any(x > need for x in majors):
        return [item("dotnet_runtime", OK, "preflight_dotnet_ok", need=need)]
    if not majors and rc is None and not s.which("dotnet"):
        return [item("dotnet_runtime", WARN, "preflight_dotnet_unknown", "preflight_fix_dotnet", need=need)]
    found = ", ".join(str(x) for x in sorted(majors)) or "-"
    return [item("dotnet_runtime", WARN, "preflight_dotnet_old", "preflight_fix_dotnet", found=found, need=need)]


def check_memory_cgroup(s, opts):
    """DSF 3.7 reserves memory for DuetControlServer with MemoryMin, which only works with the memory cgroup controller.
    Without it the setting is ignored (not fatal), so this is a warning. Not asked for DSF 3.6."""
    if not is_dsf_37(s, opts):
        return []
    controllers = s.read(CGROUP_CONTROLLERS)
    if controllers is not None and "memory" in controllers.split():
        return [item("memory_cgroup", OK, "preflight_cgroup_ok")]
    cmdline = s.read(PROC_CMDLINE) or ""
    if "cgroup_enable=memory" in cmdline.split() and controllers is None:
        return [item("memory_cgroup", OK, "preflight_cgroup_ok")]
    return [item("memory_cgroup", WARN, "preflight_cgroup_missing", "preflight_fix_cgroup")]


def check_dsf_python(s, opts):
    """dsf-python must be the version of DSF (3.7 needs Python 3.11 or newer). Silent when it cannot be read."""
    found = dsf_version(s, opts)
    have = s.pip_version("dsf-python")
    if not found or not have:
        return []
    dsf_mm, lib_mm = _ver(found)[:2], _ver(have)[:2]
    if dsf_mm != lib_mm:
        return [item("dsf_python", WARN, "preflight_dsf_python_mismatch", "preflight_fix_dsf_python", found=have, dsf=found)]
    if lib_mm >= DSF_37 and tuple(s.python_version()) < MIN_PYTHON_DSF_37:
        return [item("dsf_python", ERROR, "preflight_dsf_python_needs_python", "preflight_fix_python", found=have,
                     python=".".join(map(str, s.python_version())), need=".".join(map(str, MIN_PYTHON_DSF_37)))]
    return [item("dsf_python", OK, "preflight_dsf_python_ok", found=have)]


def check_python(s, opts):
    v = s.python_version()
    need = ".".join(map(str, MIN_PYTHON))
    found = ".".join(map(str, v))
    if tuple(v) < MIN_PYTHON:
        return [item("python_version", ERROR, "preflight_python_old", "preflight_fix_python", found=found, need=need)]
    return [item("python_version", OK, "preflight_python_ok", found=found, need=need)]


def check_sbc(s, opts):
    live = opts.get("sbc")
    if live is False or not s.isdir(paths.ROOT) or not s.exists(paths.ROOT + "/bin/DuetControlServer"):
        return [item("sbc_active", ERROR, "preflight_sbc_missing", "preflight_fix_sbc", root=paths.ROOT)]
    if not s.isdir(paths.SD):
        return [item("sbc_active", ERROR, "preflight_sd_missing", "preflight_fix_sbc", sd=paths.SD)]
    return [item("sbc_active", OK, "preflight_sbc_ok", root=paths.ROOT)]


def check_folders(s, opts):
    out = []
    ws = paths.WORKSHOP
    if s.isdir(ws):
        if s.writable(ws):
            out.append(item("folder_workshop", OK, "preflight_folder_ok", path=ws))
        else:
            out.append(item("folder_workshop", ERROR, "preflight_folder_readonly", "preflight_fix_folder_owner", path=ws))
    elif s.isdir(paths.SYS) and s.writable(paths.SYS):
        out.append(item("folder_workshop", OK, "preflight_folder_will_create", path=ws))
    else:
        out.append(item("folder_workshop", ERROR, "preflight_folder_cannot_create", "preflight_fix_folder_owner", path=ws))
    out.append(_apparmor(s))
    return out


def _apparmor(s):
    db_dir = paths.WORKSHOP
    if not db_dir.startswith(paths.SYS + "/"):
        return item("apparmor_sqlite", ERROR, "preflight_db_outside_sys", "preflight_fix_apparmor", path=db_dir)
    flag = (s.read(APPARMOR_FLAG) or "").strip()
    if flag != "Y":
        return item("apparmor_sqlite", OK, "preflight_apparmor_off")
    rc, out = s.run(["journalctl", "-k", "--no-pager", "-n", "300"])
    if rc == 0 and re.search(r"DENIED.*Workshop", out):
        return item("apparmor_sqlite", WARN, "preflight_apparmor_denied", "preflight_fix_apparmor")
    return item("apparmor_sqlite", OK, "preflight_apparmor_ok", path=db_dir)


def parse_dependency(text):
    """'tinytuya==1.13.0' -> ('tinytuya', '1.13.0'); None if DSF would not accept it (ranges, lists)."""
    m = DEP_RX.match(str(text).strip())
    return (m.group(1), m.group(2)) if m else None


def check_pip(s, opts):
    out = []
    deps = [str(d) for d in opts.get("python_dependencies") or []]
    for d in deps:
        parsed = parse_dependency(d)
        if parsed is None:
            out.append(item("pip_" + re.sub(r"\W+", "_", d), ERROR, "preflight_dep_bad_format", "preflight_fix_dep_format", dep=d))
            continue
        name, want = parsed
        have = s.pip_version(name)
        if have is None:
            out.append(item("pip_" + name, WARN, "preflight_dep_missing", "preflight_fix_dep_install", dep=d))
        elif want and have != want:
            out.append(item("pip_" + name, WARN, "preflight_dep_version", "preflight_fix_dep_install", dep=d, found=have))
        else:
            out.append(item("pip_" + name, OK, "preflight_dep_ok", dep=d, found=have))
    if opts.get("meter_kind") == "tuya" and "tinytuya" not in [(parse_dependency(d) or ("",))[0] for d in deps]:
        have = s.pip_version("tinytuya")
        if have is None:
            out.append(item("pip_tinytuya", WARN, "preflight_dep_missing", "preflight_fix_dep_install", dep="tinytuya"))
        else:
            out.append(item("pip_tinytuya", OK, "preflight_dep_ok", dep="tinytuya", found=have))
    return out


def check_power_rules(s, opts):
    """Only when the machine shuts down through the Pi (software, relay or Tuya)."""
    if opts.get("shutdown_method", "none") == "none":
        return []
    rules = [n for n in s.listdir(POLKIT_DIR) if "dsf" in n.lower() or "power" in n.lower()]
    if s.exists(SUDOERS_FILE) or rules:
        return [item("power_rules", OK, "preflight_power_rules_ok", file=SUDOERS_FILE)]
    if s.euid() not in (0, None):
        return [item("power_rules", WARN, "preflight_power_rules_unknown", "preflight_fix_power_rules", file=SUDOERS_FILE)]
    return [item("power_rules", WARN, "preflight_power_rules_missing", "preflight_fix_power_rules", file=SUDOERS_FILE)]


def check_media(s, opts):
    features = set(opts.get("features") or [])
    out = []
    if features & {"camera", "vision"}:
        if s.which("ffmpeg"):
            out.append(item("ffmpeg", OK, "preflight_ffmpeg_ok"))
        else:
            out.append(item("ffmpeg", WARN, "preflight_ffmpeg_missing", "preflight_fix_ffmpeg"))
    if "vision" in features:
        if s.has_module("cv2"):
            out.append(item("opencv", OK, "preflight_opencv_ok"))
        else:
            out.append(item("opencv", WARN, "preflight_opencv_missing", "preflight_fix_opencv"))
    return out


def check_ports(s, opts):
    out = []
    installed = bool(opts.get("installed"))
    for feature, port in PORTS:
        if s.port_free(port):
            out.append(item("port_%d" % port, OK, "preflight_port_free", port=port))
        elif installed:
            out.append(item("port_%d" % port, WARN, "preflight_port_busy_installed", "preflight_fix_port", port=port))
        else:
            enabled = feature in set(opts.get("features") or [])
            out.append(item("port_%d" % port, ERROR if enabled else WARN, "preflight_port_busy", "preflight_fix_port", port=port))
    return out


def dwc_password_state(text):
    """config.g text -> 'set' | 'empty' | 'unknown' (M551 P"..." with a non-empty password)."""
    if text is None:
        return "unknown"
    pw = None
    for line in text.splitlines():
        code = line.split(";", 1)[0]
        m = re.match(r'^\s*M551\b.*?\bP"([^"]*)"', code, re.I)
        if m:
            pw = m.group(1)
    if pw is None:
        return "empty"
    return "set" if pw not in ("", "reprap") else "empty"


def check_password(s, opts):
    state = dwc_password_state(s.read(paths.CONFIG_G))
    if state == "set":
        return [item("dwc_password", OK, "preflight_password_set")]
    if state == "unknown":
        return [item("dwc_password", WARN, "preflight_password_unknown", "preflight_fix_password")]
    return [item("dwc_password", WARN, "preflight_password_empty", "preflight_fix_password")]


def check_space(s, opts):
    free = s.free_mb(paths.SD)
    if free is None:
        return [item("free_space", WARN, "preflight_space_unknown")]
    if free < MIN_FREE_MB:
        return [item("free_space", ERROR, "preflight_space_low", "preflight_fix_space", free=free, need=MIN_FREE_MB)]
    if free < WARN_FREE_MB:
        return [item("free_space", WARN, "preflight_space_tight", "preflight_fix_space", free=free, need=WARN_FREE_MB)]
    return [item("free_space", OK, "preflight_space_ok", free=free)]


CHECKS = (check_dsf, check_dotnet, check_memory_cgroup, check_dsf_python, check_python, check_sbc, check_folders, check_pip, check_power_rules, check_media,
          check_ports, check_password, check_space)


def summarize(items):
    counts = {OK: 0, WARN: 0, ERROR: 0}
    for it in items:
        counts[it["status"]] += 1
    return counts


def run(system=None, options=None):
    s = system or System()
    opts = dict(options or {})
    items = []
    for check in CHECKS:
        try:
            items.extend(check(s, opts))
        except Exception as e:  # a failing check must not hide the others
            items.append(item(check.__name__, WARN, "preflight_check_failed", check=check.__name__, error=str(e)[:120]))
    counts = summarize(items)
    return {"ok": counts[ERROR] == 0, "summary": counts, "items": items}


# ---- options from the installed machine / a manifest ----

def manifest_dependencies(manifest_text):
    try:
        return list(json.loads(manifest_text).get("sbcPythonDependencies") or [])
    except (ValueError, AttributeError):
        return []


def options_from_machine(system=None):
    """Options for preflight.run read from the installed service: manifest, enabled plugins, profile."""
    s = system or System()
    opts = {"installed": s.exists(paths.PLUGINS + "/WorkshopService.json")}
    opts["python_dependencies"] = manifest_dependencies(s.read(paths.PLUGINS + "/WorkshopService.json") or "{}")
    enabled = []
    try:
        enabled = json.loads(s.read(paths.DWC_SETTINGS) or "{}").get("machine", {}).get("enabledPlugins") or []
    except (ValueError, AttributeError):
        pass
    opts["features"] = [f for f, pid in (("camera", "WorkshopCamera"), ("vision", "WorkshopVision")) if pid in enabled]
    try:
        prof = json.loads(s.read(paths.CONFIG_DIR + "/machine.json") or "{}")
        opts["shutdown_method"] = (prof.get("shutdown") or {}).get("method", "none")
        opts["meter_kind"] = (prof.get("meter") or {}).get("kind", "none")
    except (ValueError, AttributeError):
        pass
    return opts
