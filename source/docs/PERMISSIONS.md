# DSF permissions of WorkshopService: why each one, and how it was measured

## How it got broad
Until 1.25.0 the service had almost no permissions. On 2026-10-11 (1.25.1) it started running under the AppArmor profile that DSF writes for each plugin, and it could not do what it did before (read keys, lock the database, start `ffmpeg`...). Four permissions were added at once (`readSystem`, `writeSystem`, `fileSystemAccess`, `launchProcesses`) without measuring which feature needed which. This document replaces that guess with measurements.

## What each permission becomes
DSF writes `/etc/apparmor.d/dsf.<Id>` when the plugin is INSTALLED (not when it is reloaded), from the manifest:

| Permission | Lines of the profile |
|---|---|
| `fileSystemAccess` | `/ rw`, `/** rw` |
| `launchProcesses` | `/** mix` |
| `readSystem` | `/opt/dsf/sd/sys/ r`, `/opt/dsf/sd/sys/** r` |
| `writeSystem` | `/opt/dsf/sd/sys/** wk` (write and file lock) |
| `networkAccess` | `network` |

## Measurement (2026-10-29, Duet 3 + Pi, DSF 3.6)
`tools/permission_probe.py` calls 11 API operations that touch processes, `0:/sys` and the system files; the script loaded the profile without the lines of ONE permission, restarted the service, ran the probe and read `journalctl -k | grep DENIED`.

| Profile without | Result | Evidence |
|---|---|---|
| nothing (control) | 11/11, no denial | |
| `readSystem` | 11/11, no new denial | `/** rw` already covers `sd/sys`: REMOVED from the manifest in 2.21.27 |
| `writeSystem` | 0/11, every call HTTP 500 | `file_lock` denied on `/opt/dsf/sd/sys/workshop/duet.db` (SQLite) |
| `fileSystemAccess` | 0/11, the service starts but every call is 401 | denied reads of `/opt/dsf/conf/workshop-secrets.json`, `workshop-api-token`, `config.json` and its own manifest |
| `launchProcesses` | the operations answer, but the processes are blocked | `exec` denied for `/usr/bin/ip` and `/usr/bin/vcgencmd` (health of the Pi); `ffmpeg`, `pinctrl`, `systemctl` and `sudo` use the same permission |

## What stays and why
- `writeSystem`: the history database must live under `0:/sys` (the profile grants file locks only there and in the plugin folder). The plugin folder is deleted when the plugin is reinstalled, so the database cannot live there.
- `fileSystemAccess`: keys, users and the API token live in `/opt/dsf/conf/` on purpose, outside the plugin folder, so reinstalling does not lose them. Also camera files in `/opt/dsf/sd/workshop/camera/` and the SPI device of the LED strip.
- `launchProcesses`: `ffmpeg`, `pinctrl`, `vcgencmd`, `ip`, `systemctl` (the G-code bridge) and `sudo -n shutdown`. DSF has no narrower permission per program.

To repeat the measurement: copy `tools/permission_probe.py` to the Pi, load a profile variant with `sudo apparmor_parser -r`, restart the service (stop Vision and RS485 first, they depend on it) and run the probe.
