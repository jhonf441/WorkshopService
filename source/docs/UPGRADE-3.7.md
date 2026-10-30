# Upgrading the Pi from DSF 3.6 to DSF 3.7 (optional)

WorkshopService runs on DSF 3.6 and on DSF 3.7 with the same files. Nothing here is required: stay on 3.6 as long as
you like. This is the ordered list for the day you decide to upgrade. Steps marked **[SUDO]** need administrator
rights on the Pi; steps marked **[FREE MACHINE]** must be done with the machine idle (no job, no live job, motors
not in use, nobody on the kiosk), because DSF and every plugin restart.

What changes in DSF 3.7.0 (release notes of 8 October): IPC protocol 13 (the commands SetObjectModel, LockObjectModel
and UnlockObjectModel are gone, PatchObjectModel is the only writer), .NET 10, the memory cgroup for
`MemoryMin` of DuetControlServer, plugin www files installed by symlink, plugin ids compared without case, and the
root plugin service no longer overrides `KillMode`. The audit of this service against each item is at the end.

## Before

1. Check the current state (no sudo): `python3 dsf/preflight_cli.py --lang en` from the plugin folder, or the
   preflight on the service page. Everything must be OK or WARNING for DSF 3.6.
2. **[FREE MACHINE]** Back up (no sudo needed for the first two):
   - `0:/sys` of the SD (`/opt/dsf/sd/sys`, includes `config.g`, `workshop/config`, `workshop/data/duet.db`).
   - `/opt/dsf/conf/workshop-secrets.json` and `workshop-users.json` (mode 600: copy them, do not print them).
   - `/opt/dsf/plugins/*.json` and the plugin folders (the installer also leaves `~/sd-backup/WorkshopService-pre-<version>`).
   - The DSF package version you have now: `dpkg-query -W duetsoftwareframework` (write it down for the rollback).
3. Copy the backup off the Pi (PC or USB stick). A backup that lives only on the SD card is not a backup.
4. Read the 3.7 `config.json` note: DSF migrates an unmodified `/opt/dsf/conf/config.json` by itself; a file you edited
   (regex settings are plain patterns now, configured lists replace the defaults) must be reviewed by hand.

## Upgrade

5. **[SUDO] [FREE MACHINE]** Update the package source and check the plan first: `sudo apt update` and
   `apt list --upgradable | grep -i duet`. Follow the Duet3D guide for 3.7 if it asks for a different apt source.
   The upgrade brings .NET 10 (the runtime `dotnet-runtime-10.0`; DSF 3.7 dropped .NET 9).
6. **[SUDO] [FREE MACHINE]** Upgrade: `sudo apt install --only-upgrade duetsoftwareframework` (and the DWC and RRF
   firmware packages the guide lists; RepRapFirmware 3.7 goes to the board through DSF). DuetControlServer restarts.
7. **[SUDO]** Memory cgroup. Edit the kernel command line: `sudo nano /boot/firmware/cmdline.txt`
   (`/boot/cmdline.txt` on older images). The file is ONE line: add ` cgroup_enable=memory` at the end of that
   line (a space before it, no new line). Keep a copy first: `sudo cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak`.
   Reboot (**[FREE MACHINE]**). Check: `grep memory /sys/fs/cgroup/cgroup.controllers` must print a line.
   Without it DSF 3.7 still runs, the memory reservation of DuetControlServer just has no effect.
8. dsf-python. The library on the Pi must be the same 3.x as DSF: a 3.7 server and the 3.6 library (or the other way
   round) is a warning in the preflight. dsf-python 3.7.0 needs Python 3.11 or newer (Raspberry Pi OS Bookworm has it).
   **[SUDO]** `sudo pip3 install dsf-python==3.7.0` (add `--break-system-packages` if pip refuses, as on Bookworm).
   This is used by WorkshopService and by the G-code bridge (it runs with the system python3).

## After

9. Run the preflight again (no sudo): DSF 3.7, .NET 10, memory cgroup and dsf-python must all be OK.
10. **Which plugins to reinstall.** Normally none: the installed plugin folders and manifests stay. Reinstall only a
    plugin the service page or `journalctl -u duetcontrolserver` reports as failed (a plugin that fails to load is
    logged by DWC 3.7 and shown as stopped in Settings, Plugins: it stays in `enabledPlugins`, unlike DWC 3.6 which removed it. Check
    `machine.enabledPlugins` in `0:/sys/dwc-settings.json` anyway, 15 entries here, WorkshopService FIRST (a dependent plugin
    loads only if the service comes earlier in that list, see docs/INSTALL.md), and fix it as described in CLAUDE.md). Plugin ids are case-insensitive in 3.7; ours are unchanged.
    Plugin www files are installed by symlink in 3.7: `/opt/dsf/dwc/` gets links, not copies. After the upgrade
    reload every DWC tab and the kiosk (delete its Service Worker cache, see CLAUDE.md).
    If a Workshop page does not load, update it with `tools/install.sh` (it copies and rewrites the manifest) and
    for the other plugins `python build.py <Id> --install`.
11. **[FREE MACHINE]** Restart the services that must come back: `/opt/dsf/bin/PluginManager reload WorkshopService`
    then start it (or `sudo systemctl restart duetcontrolserver`). The G-code bridge is its own systemd unit and keeps
    its own life (see below); `sudo systemctl restart workshop-gcode-bridge` is only needed if it lost the DSF socket.
12. Check on the service page: the "subscription" heartbeat is alive, jobs and the live job work, the status light
    paints, the camera and Vision answer. Dry-run a short job with the machine free.

## Rollback

- Downgrade the package: **[SUDO] [FREE MACHINE]** `sudo apt install duetsoftwareframework=<version you wrote down>`
  (apt may need `--allow-downgrades`), then `sudo pip3 install dsf-python==3.6.0`. The cmdline.txt change is harmless on
  3.6; to undo it, put back `cmdline.txt.bak` (**[SUDO]**) and reboot.
- The service files need no rollback: the same files run on both. If you installed a new service version in the
  meantime: `tools/install.sh ... --rollback <version>` (docs/INSTALL.md).
- Restore the backup of step 2 only if data was damaged (settings and the database live outside the plugin folders and
  DSF does not touch them).

## Audit of this service against the 3.7 changes

| 3.7 change | Effect on this repo | What was done |
|---|---|---|
| IPC protocol 13 | dsf-python negotiates it; a library and a server of different major.minor refuse each other | Preflight warns on a mismatch; the library is not pinned in the manifest (it lives on the Pi next to DSF) |
| SetObjectModel / Lock / Unlock removed | not affected: no call of `set_object_model`, `lock_object_model`, `unlock_object_model` or `patch_object_model` anywhere; the service only uses `perform_simple_code`, `resolve_code`, `set_plugin_data`, `add_http_endpoint`, `check_password`, intercept and subscribe connections | none |
| SubscribeInitMessage `Verbose` / `Obsolete` | DSF 3.7 leaves obsolete fields (`move.workplaceNumber`, which five modules read) and verbose ones out unless asked | `dsf/dsf_compat.py` asks for both when the installed `SubscribeConnection` has them; 3.6 is unchanged. Cannot be one code path in the library, so it is feature-detected |
| MainBoard / ExpansionBoard split | the service reads `boards[0]` (the main board: vIn, mcuTemp, firmware) and only generic fields of the others (shortName, canAddress, drivers) | not affected |
| Plugin ids case-insensitive | ids are compared in `service_modules.py` against `enabledPlugins`; the same spelling is used everywhere | not affected |
| `KillMode` of the root plugin service | WorkshopService is not a root plugin (no superUser permission); its children are short ffmpeg runs it waits for. The bridge, the camera relay and the kiosk helpers are not children of a root plugin: the bridge is its own systemd unit | not affected; a process that must survive a service stop needs its own unit, as the bridge already has |
| Plugin www by symlink | the installer copies into `<plugin>/dwc` and the DWC folder | to be confirmed on the Pi after the upgrade (step 10) |
| Memory cgroup | DSF-side setting, not used by this code | preflight check and the cmdline.txt edit above |
| .NET 10 | DSF-side | preflight check |
| Object model key queries authoritative | the service uses one Patch subscription and replaces the whole model every refresh; a missing value arrives as an explicit null and is applied as null (`machine_state.apply_patch`); nothing relies on a stale value | not affected |
| Pulsed filament monitor `position` is a raw int | no code reads `filamentMonitors` | not affected |
| `sbc.upgrade` progress | new keys only | not affected |

Items that cannot be one code path for 3.6 and 3.7: the subscription flags (isolated in `dsf/dsf_compat.py`, tested for
both signatures in `dsf/test_dsf_compat.py`), and the dsf-python library itself (a 3.7 library needs a 3.7 server;
that is a Pi setup matter, checked by the preflight). Everything else is shared.
