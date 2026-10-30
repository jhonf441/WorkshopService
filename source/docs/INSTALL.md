# Installing WorkshopService on another machine

WorkshopService is the backend (Python, under DSF) and the service page of the workshop plugins. It runs on
**a Duet 3 with a Raspberry Pi in SBC mode (DSF 3.6 or 3.7), and nothing else**: not on a Duet 2, not on a
board without a Pi. Everything else changes freely between machines (axes, tools, modes, macros, SD paths, meter,
currency, probe, camera, LED strip, shutdown relay, accessories): the service discovers what the board has
(`capabilities.get`) and reads what the owner declares (`profile.get` / `profile.set`, file
`0:/sys/workshop/config/machine.json`).

## What you need

- A Duet 3 + Raspberry Pi with DuetSoftwareFramework 3.6 or 3.7, and DWC working. The same service files run on both (`dsf/dsf_compat.py` is the only place that knows the difference). On DSF 3.7 the Pi also needs the .NET 10 runtime and the memory cgroup (see below); upgrading from 3.6 is optional: `docs/UPGRADE-3.7.md`. The dsf-python of the Pi must be the same 3.x as DSF (3.7 needs Python 3.11 or newer).
- A login user on the Pi that can write `/opt/dsf/plugins` (usually a member of the group `dsf`), or `sudo` rights (use `--sudo`).
- SSH access from the PC you install from, with a key (the installer never asks for a password: `BatchMode`).
- On the PC: `bash`, `ssh`, `scp`, `unzip`, `md5sum` and Python 3 (`python3`, or `python` / `py -3` on Windows, where `python3` is only a Microsoft Store shortcut: the script finds whichever works).
- The build of the service: `WorkshopService-<version>.zip` (it has `plugin.json`, `dsf/` with the backend and `dwc/js`, `dwc/css`). **Only the zip is needed**: the files are taken from inside it. A clone of the repository (`--repo`) is optional.

## First install or update

```
tools/install.sh --host raspberrypi.local --user pi --version 2.14.0 --zip /path/WorkshopService-2.14.0.zip
```

The script looks at the Pi and chooses by itself:

- **First install** (`WorkshopService.json` is not in `/opt/dsf/plugins` yet): it runs the pre-install check and then DSF's own
  `PluginManager install` with the zip. That is the only way to give the files the owner (`dsf`), the permissions and the executable
  bit DSF needs (a plain copy leaves `main.py` without execute permission and DSF cannot update or uninstall it later). It starts the
  service and adds `WorkshopService` to `machine.enabledPlugins` of `0:/sys/dwc-settings.json`: DWC's plugin list cannot load the page
  of a plugin whose process is already running ("partially started" with only a Stop button).
- **Update** (already installed): the steps below.

Every value can be an environment variable instead (`WORKSHOP_HOST`, `WORKSHOP_USER`, `WORKSHOP_VERSION`,
`WORKSHOP_ZIP`, `WORKSHOP_DSF_ROOT`, `WORKSHOP_SSH_OPTS`, `WORKSHOP_LANG`). `tools/install.sh --help` lists all options.

The script does, in this order, and stops at the first failure:

1. **Local checks**: the zip exists and its `plugin.json` is the version you asked for.
2. **Pre-install check** on the Pi (`tools/preflight.py`): see below. Any ERROR stops the install; warnings do not.
3. **Differences**: compares the md5 of every `.py` / `.json` in `dsf/` with the Pi and copies only what changed.
4. **Backup** in `~/sd-backup/WorkshopService-pre-<version>` on the Pi (the files about to be replaced, the old
   bundles of the page and the old manifest). A second run never overwrites the first backup.
5. **Stop** the plugins that depend on the service and have a backend (Vision, RS485...), then the service.
6. **Copy** the Python files and the page bundles, and write the manifest (`version`, `dsfFiles` and `data` from the
   repository, `dwcFiles` ONLY the files of the new build).
7. **Reload and start** the service, then the plugins stopped in step 5. Old bundles that are not in the manifest are removed.
8. **Verify**: the manifest says the new version, the service process is running, and `WorkshopService` is in
   `machine.enabledPlugins` of `0:/sys/dwc-settings.json`.

A copied file is created by the login user, so the script gives the group `dsf` and group write permission to the plugin folder and
sets the execute bit of the executable in the manifest (`--sudo` gives the owner back to `dsf:dsf` instead). Without it DSF
(which runs as `dsf`) cannot update or uninstall the plugin later; if the login user is not in the group `dsf` the script warns.

Install with the machine **idle**: the service is down for a few seconds (jog, lights, shutdown timer and the
safety monitors rest meanwhile). `--dry-run` runs steps 1 to 3 and shows what would be copied.

On an installed plugin the script only copies files; it never runs `PluginManager install` over it (that uninstalls it first and
deletes its folder). The other plugins (Camera, Vision, Power...) are installed from DWC or with
`PluginManager install` the first time, and updated by their own build. Install the service first: every other plugin depends on it.

## Setting up a machine like another one

A new install starts with no settings: each page creates its file when somebody saves it. To leave a machine like another one, use the configuration package (service page, Database section):

1. On the machine that is already set up: *Export* and choose what goes in (page settings, work zones, macros, machine modes). Users, PINs, keys and the database never go in.
2. On the new machine: *Import*, pick the zip. It shows what it would do with every file before writing anything. Nothing existing is overwritten; a different file is kept unless you tick it, and then the old one is saved as `<file>.bak-import`.
3. The machine modes (`mode*.g`) hold the pins and drivers of the OTHER machine: they are copied to `sys/workshop/imported/` to be read, never put in place.
4. Secrets travel by hand: the camera key changes on every first install (re-flash the ESP32-CAMs or copy `/opt/dsf/conf/workshop-camera.key`) and the Tuya meter is added again from the Power page.

The *Machine setup* list at the top of the service page shows, for every INSTALLED plugin, how many steps of its start-up card are pending.

## Uninstalling

DSF refuses to uninstall a plugin other plugins depend on ("Cannot uninstall plugin because plugin X depends on it"). Uninstall every
plugin that depends on `WorkshopService` (Camera, Control Bar, Jog, Workbench, Machine, Motors, Power, Lights, PiHealth, Activity,
Printing, Vision, RS485) first and `WorkshopService` last, with `PluginManager uninstall <Id>` (stop Vision and RS485 first). Your data
is not in the plugin folder (`0:/sys/workshop`, `/opt/dsf/conf/workshop-*.json`, `workshop-camera.key`): uninstalling does not delete it,
and a later install finds it. Note that a fresh install on a Pi without `/opt/dsf/conf/workshop-camera.key` creates a NEW key: an
ESP32-CAM flashed with the old one will not authenticate.

After installing: reload every DWC tab (and the kiosk), and check that `machine.enabledPlugins` still lists your plugins.

If DWC shows a plugin with a process (Service, Vision, RS485) as "partially started" or "disabled" with only a Stop button, its process
runs but its page was never saved as enabled (typically after `PluginManager start` by hand). In *Settings > Plugins* press Stop and then
Start (stop Vision and RS485 first if Stop does nothing: they depend on the service); as a last resort add the id to
`machine.enabledPlugins` of `0:/sys/dwc-settings.json` (PUT it as `application/octet-stream`).
DWC 3.6 removes a plugin from the list when it fails to load and saves it (DWC 3.7 only logs the failure and leaves the list as it is); the reason is in the machine events.

**Load order.** DWC loads the plugins in the order of `machine.enabledPlugins` and a plugin with `dwcDependencies: ["WorkshopService"]` loads only if WorkshopService is already loaded, i.e. earlier in that list. The installer puts WorkshopService first on a first install. If you add it by hand or from *Settings > Plugins* (which appends at the end), move it to the front of the list, otherwise the plugins before it fail with "depends on WorkshopService which is not loaded" until the next reload. The service cannot reorder the list itself: DWC owns and rewrites that file from the browser.

## Pre-install check

```
python3 tools/preflight.py --lang en              # on the Pi (from a clone)
python3 dsf/preflight_cli.py --lang es --json     # the same, from the plugin folder or the zip (machine readable)
```

Each item is OK, WARNING or ERROR, with the solution in words. It checks:

| Item | Error when | Warning when |
|---|---|---|
| DSF version | older than 3.6 | cannot be read |
| .NET 10 (only DSF 3.7) | | DSF 3.7 and no .NET 10 runtime found (`dotnet --list-runtimes`, `/usr/share/dotnet`) |
| Memory cgroup (only DSF 3.7) | | `memory` is not in `/sys/fs/cgroup/cgroup.controllers`: add `cgroup_enable=memory` to the single line of `/boot/firmware/cmdline.txt` (`/boot/cmdline.txt` on older images) and reboot |
| dsf-python | dsf-python 3.7 on Python older than 3.11 | its major.minor is not DSF's |
| Python | older than 3.9 | |
| SBC | no DSF in `/opt/dsf` (or `WORKSHOP_DSF_ROOT`) | |
| Folders | `sys/workshop` not writable or not creatable | |
| AppArmor / SQLite | the database would be outside `0:/sys` | the kernel log shows `DENIED ... Workshop` |
| pip dependencies | a `sbcPythonDependencies` entry DSF would not accept (ranges, two conditions: use one `==`) | a dependency is missing or has another version |
| Shutdown rules | | the shutdown function is used and `/etc/sudoers.d/dsf-power` (or a polkit rule) is missing |
| ffmpeg / OpenCV | | Camera / Vision are enabled and the program is missing |
| Ports 8090 / 8095 | busy on a fresh install with that feature enabled | busy otherwise (normal if it is the service itself) |
| DWC password | | `M551` has no password: anyone on the network can control the machine |
| Free space | under 200 MB | under 2 GB |

The same check is available from the page and any client: API operation `preflight.run` (read only, technician role when people are configured).

## The machine profile

`machine.json` is created the first time something saves it; until then the service uses generic defaults that assume
nothing from any particular workshop (no meter, no currency, no shutdown method, macros named
`0:/macros/<role>.g`, reported as `null` when the file does not exist). Edit it with `profile.set`
(administrator only; `profile.get`, `capabilities.get` and `preflight.run` are for any logged in person, the last one for technicians) or by hand while the service is stopped. Fields:

- `name`, `language` (`""` follows DWC), `currency` (`""` follows the DWC language).
- `meter`: `{kind: none | tuya | <other>, params}`; `shutdown`: `{method: none | software | relay | tuya, params}`.
- `macros`: role (`focus`, `home`, `light`, `air`, `shutdown`, `park`) to a path such as `0:/macros/focus.g`, or `null`.
- `interlocks` (schema 2): optional laser lid / extraction / key inputs, `{gpin, active_when, label}` each (`docs/INTERLOCKS.md`).
- `probe.index`, `axis_index` (`X`, `Y`, `Z` positions in the board's axes; `null` looks the letter up).
- `capability_overrides` (`{"camera": false}` = do not use it even if it is there), `mode_policies`.

The file has a `schema` number (currently 3). A file of any other schema is refused and never rewritten (the defaults are used).

## Update flow

1. Build the page (`node scripts/build-plugin.js` in the DWC source folder) and keep the zip.
2. `tools/install.sh ... --dry-run` to see the differences and the pre-install check.
3. Wait for the machine to be idle. Run the same command without `--dry-run`.
4. Reload the DWC tabs. Open the service page and check the process list.
5. Keep the backup folder until the new version has worked for some days.

## Rollback

Every install leaves `~/sd-backup/WorkshopService-pre-<version>` on the Pi. To go back to the state before `<version>`:

```
tools/install.sh --host raspberrypi.local --user pi --rollback 2.14.0
```

It stops the service (and its dependants), puts back the saved `.py` files, the old manifest and the old bundles, removes the
files the new version added, reloads and starts again. Settings are not touched: they live outside the plugin folder
(`0:/sys/workshop/config/*.json`, `/opt/dsf/conf/workshop-secrets.json`) and the database is `0:/sys/workshop/duet.db`.
If a new version changed the database or `machine.json` schema (the database is at schema 6: the table `health_samples` came with it;
tables are only added; not verified that every older version ignores them), the older service refuses a newer `machine.json` and never rewrites it: restore
`machine.json.bak` (the service keeps the last healthy copy) if that happens.

## Another DSF folder, another user

- DSF in a folder other than `/opt/dsf`: set `WORKSHOP_DSF_ROOT` for the service (in the unit that starts DCS) and pass `--dsf-root`.
- A login user without write access to `/opt/dsf/plugins`: add `--sudo`; the installer gives the files back to `dsf:dsf`.
- A non-standard SSH port or key: `--ssh-opts "-p 2222 -i ~/.ssh/workshop"`.

## Wrappers

Values that belong to one workshop (address, login, paths of the build) do not go in this repository's scripts. Keep them in a
thin wrapper that calls `tools/install.sh`; `tools/author/install-service.sh` is an example.
