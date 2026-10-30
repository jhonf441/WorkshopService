# WorkshopService -- version history

Workshop backend (central API, pollers, database)
and its control page. Before 1.3.0 it was not versioned: versions
1.0-1.2 were reconstructed by grouping the commits by day.

## Unreleased

- Camera relay: optional `bind` in `camera_relay` (default all interfaces, `"127.0.0.1"` keeps it on the Pi). Vision: `WORKSHOP_VISION_BIND`.
- `bridge/install.sh uninstall` removes the unit, the polkit rule and `/opt/workshop-bridge`.
- `security.md`: every permission is explained, plus a table of changes made outside DSF and how to undo them, and the open-access warning while no user exists.

## 2.21.34 -- 2026-10-30

- `machine.workarea.positions` (read only, operator): the positions saved by the jog, so Machine can take two of them as the corners of a work area.

## 2.21.33 -- 2026-10-30

- Work area: measuring a corner, going to a point and walking the area now ask for a level 3 confirmation before the machine moves.

## 2.21.32 -- 2026-10-30

- Service page on phones (checked at 390 and 375 px): Processes (the readings per minute wrap), Database (the select of the copies) and API and keys (the header and the example of each operation wrap) no longer push the page sideways.

## 2.21.31 -- 2026-10-30

- DWC password: the copy of config.g made before a change (`config.g.bak-password-<date>`) no longer keeps the password (its M551 line is commented out); before, every change left the OLD password in plain text in a backup. Restoring such a copy leaves DWC without a password.

## 2.21.30 -- 2026-10-30

- Motors: the RPM no longer assumes 200 full steps per revolution for every motor. `motor_status.steps_per_rev_resolver` reads the steps per revolution that the person saves per axis (and in general) in Motors > Advisor (settings file `motors`), every cycle; without it, config.json / 200 as before. Each motor entry says which number it used (`full_steps_per_rev`).

## 2.21.29 -- 2026-10-30

- Service page: the design family css is regenerated (44 px tap targets in the section bars on phones; the Vuetify 2 name of the small-button rule now lives in the family, not in the 3.6 theme).

## 2.21.28 -- 2026-10-30

- Interrupted live jobs: new operation `livejob.interrupted.hide` takes a record off the work table (or puts it back) WITHOUT deleting it; the list marks `hidden`. Before, the only way to remove one from the table was Discard, which deletes the record. The hidden marks live in `data/live-interrupted-hidden.json` and are forgotten when the record is discarded.

## 2.21.27 -- 2026-10-30

- Permissions: `readSystem` is no longer asked. Measured on the Pi with the AppArmor profile of each permission removed one at a time (`tools/permission_probe.py`, `docs/PERMISSIONS.md`): without it nothing is denied, because `fileSystemAccess` already lets the service read the SD card. The other three stay, each with the exact reason.

## 2.21.26 -- 2026-10-29

- Manifest: the tags no longer say `custom-gcode` (there are no custom G-codes any more; everything goes through the API).

## 2.21.25 -- 2026-10-29

- G-code bridge, debug: you choose how the countdown behaves. New switch "Start the countdown again while this panel is open" (on = as before, looking at the panel renews it; off = the countdown is fixed from turning debug on) and an "Extend" button that gives the whole time again in either mode. The bridge itself (`bridge/gcode_bridge.py`) needs `sudo bridge/install.sh` to take the change.

## 2.21.24 -- 2026-10-29

- API keys: an expired key shows its switch disabled with a line saying it does not work even if it is on (it said "Vencida" next to an active switch).
- The counters of the service say the same thing the same way: "With problems: n", "With warnings: n", "Stopped: n", "Up to date: n".
- Side bars: icon-only items carry their name as the accessible name; an item may say why it is disabled.

## 2.21.23 -- 2026-10-29

- Interrupted live jobs: each record that cannot be resumed because the board restarted now carries `rebooted_at` (when the board started), so the page can say when it restarted and how long after the stop (a power cut is no longer read as a consequence of the stop).

## 2.21.22 -- 2026-10-29

- Start-up list of the machine: while there are no users, its first row is "First administrator" (pending) with a button to the Users section, so a new install does not stay open by accident. It is never forced: a machine that works without users keeps working.

## 2.21.21 -- 2026-10-29

- Architecture review: the DWC 3.6 page copies of the shared client (`workshop-api.js`, `workshop-auth.js`, `workshop-ids.js`, `service-text.js`, `theme.css`) are refreshed from `vue/_shared36` (the 3.6 page had drifted) and a test compares them; the side bar keeps its height when a shorter section opens.
- One list of the statuses that mean "a job is on" (`job_states.py`) instead of about 13 copies; one atomic file write (`fs_atomic.py`) used by the plain writers; a size rule for the modules (`test_module_sizes.py`).

## 2.21.20 -- 2026-10-29

- Live job: the `liveJob` data is published in order (it went out from a new thread on every update, so two quick updates could arrive reversed and leave a stale "active" state).
- `machine.try`: keeping or reverting a trial needs the `gcode_kind` of that trial (the role is decided from that argument, so another kind could be used to cancel the auto-revert of an admin trial).
- Removed the dead setting `air_assist.physical_port` and the unused settings name `stacks`; the thread-dump request file is now `workshop-stacks.request`.

## 2.21.19 -- 2026-10-29

- The start no longer logs "could not protect secrets.json": the fallback `secrets.json` next to the code is only protected when it is the store in use (a leftover made by hand as another user cannot be chmod'ed by `dsf`).
- State chips with an icon: the icon carries the state color and there is no dot beside it (family.css regenerated); a chosen chip is tinted.

## 2.21.18 -- 2026-10-29

- PID tuning record: the service samples the temperature and power of the heater while `M303` runs (`pid_trace.py`, process `pid_trace`, rests with 3D Printing) and keeps the last one, so its chart can be seen from any screen or session and goes on with the page closed. New API operation `pid.trace`.
- Backups list: "deleted on" is a plain state (dot and text) instead of an orange chip whose letters and icon were hard to read.
- Page header: the health state shows the colored dot and the text, without a second icon.

## 2.21.17 -- 2026-10-29

- API operations: the whole list shows when the page opens (choosing a category or typing in Find filters it). The sub-group buttons are plain outlines when off and solid when chosen, and their names and the operation names no longer sit in a gray box.

## 2.21.16 -- 2026-10-29

- Side bars: no gray line at the right of the bar (the same in every plugin) and choosing an item from far down the page goes back to the start of that section.

## 2.21.15 -- 2026-10-29

- API reference and key permissions: if the service does not answer `api.describe` when the page opens (busy or restarting), the page retries until it does, instead of staying empty ("0 operations").

## 2.21.14 -- 2026-10-28

- Design family: no uppercase group titles in the side menu, the section color reaches the top line of the cards, small buttons keep their 12 px label (family.css regenerated).

## 2.21.13 -- 2026-10-28

- The service page moves to the design family of the plugins: one page bar (badge, name, one line, state with the count of processes) instead of the title card, the shared side menu and cards (a 2 px line on top, no shadow, no side bars or tints), outline chips with a dot, gray icons, one blue main button ("New key" is no longer pink) and the "How it works" notes folded inside their card. The second bar of "API and keys" is now a normal section heading; the category filters of "API operations" are the family pills.

## 2.21.12 -- 2026-10-28

- Service page, "API operations": the category tags are colored again (soft color, solid when chosen) and a chosen category shows its sub-groups (the operation prefix, e.g. `machine.workarea`) with their counts, to filter a big category (Machine has 72 operations).

## 2.21.11 -- 2026-10-28

- Service page, "API and keys", minimalist look: neutral header and cards (no tinted backgrounds, gradients or shadows), the categories as text tabs with a colored underline on the active one (they wrap, never scroll), gray icons, a 2 px colored line on top of each card.

## 2.21.10 -- 2026-10-28

- Service page, "API and keys" redesigned (same look as the pellet setup): welcome header, colored cards, the nine categories as selectable tiles with their counts (no repeated chip row or folded group headers), search and read/write filter in one toolbar, the list of the chosen category or of the search, and the keys card with its own header and help block.
- `machine.workarea.save` also saves the FFF area (before: Laser and CNC only). Nobody else writes `cutAreaFFF`; `workplaces.g`, `saveworkplace.g` and `framecutarea.g` only read it, FFF included. `machine.workarea.get` answers `edit_modes` with the three modes.
- Vision keeps its area through `machine.workarea.save` (the service is the only writer of `cutarea.g`).

## 2.21.9 -- 2026-10-28

- Work area (`machine_workarea.py`): the usable area of each mode (`cutarea.g`) moves from the Workbench to Machine, like the height calibration did. New operations `machine.workarea.get` (operator), `machine.workarea.save` (technician; Laser or CNC, checked like the old card: 10 mm minimum, inside the travel; keeps the other modes and a `.bak`), `machine.workarea.release` (technician, level 4: X and Y off for the hand measurement) and `machine.workarea.step` (capture the corner, take the pointer to a point, walk the area with the pointer). New closed-list templates `area_*`. The corner macros stay on the SD, shipped by the Workbench package.

## 2.21.8 -- 2026-10-28

- Service page, "API operations": the 235 operations are grouped in nine categories (machine and motion, jobs and laser, lights, energy, activity and notices, camera and vision, users and security, settings, other), each folded by default with its count; they open by themselves while searching or filtering, and there are "Open all" and "Fold all" buttons. Before, seven categories and one "System" bucket took everything else (the 37 `machine.*` among them).
- `theme.css`: `--tp-font-mono` token (the one monospace stack of the pages).

## 2.21.7 -- 2026-10-27

- Safety check (`safety.check`, read only): a halted machine no longer ends it with `machine_halted`; a run that reserves nothing moves nothing, so the check finishes and reports the halted state as a problem.
- Confirmation dialogs of the service page use the look of the DWC dialogs (flat card, text buttons).

## 2.21.6 -- 2026-10-27

- Consumption history (`energy.history`): a long range (30 days) now covers the WHOLE range. Up to 2000 readings come as they were read; with more, they are averaged in equal time buckets and the answer carries `serial_step_s` (width of a bucket, 0 = raw). Before, only the most recent 2000 readings (about 16 hours) were kept, so the 30-day chart showed almost nothing.

## 2.21.5 -- 2026-10-26

- Service page, "Processes and automations": one list feeds the PROCESSES tile, the summary chips and the chip next to the title (internal processes plus separate services), so the numbers agree; with the service not connected they say "Not available" instead of zeros or old warnings; the title chip words warnings as warnings; the tile grid follows the width of the strip (no tile alone on a last row, container queries). Both page trees.
- Service page (DWC 3.7): stopping the plugin takes the page route and the "System service" menu entry out (`dwcPluginUnloaded`); the expanding blocks use the shared ExpandTransition instead of the unregistered `<v-expand-transition>`.
- Machine setup card (redesign since 2.21.4): rows grouped, wrapping text, narrow layout (the right-hand text no longer takes half of the row at 375 px).
- Camera relay: a failed `/status` is retried instead of being stored as "no ESP32, no flash". Backup: a file the card cannot read is left out and named instead of stopping the whole backup.

## 2.21.4 -- 2026-10-25

- Service page, "Machine setup" list: without a session it says "Sign in to check" with a Sign in button (it showed "not checked" for every plugin because `readiness.list` needs a login); it reads again by itself when the person signs in or out.

## 2.21.3 -- 2026-10-24

- The status light macros `enable_pi_status.g` / `disable_pi_status.g` (hand-over of the LED strip to `sys/daemon.g`) are written by the service in `sys/workshop/macros/` at start (a file without our mark is never touched) and called from there; a new machine no longer logs "Failed to start macro file" every time the service stops.
- Service page: the Vision card asks through `vision.get` instead of calling port 8095 from the browser (with users on, Vision refuses a call without a session and the card said "does not answer: HTTP 401").
- Packaging: the zip no longer carries the local files of the development copy (`dsf/secrets.json`, logs, `__pycache__`): the update of an installed machine stopped on `secrets.json` (mode 600). Clean the git-ignored files of `dsf/` before building (`git clean -ndX dsf` lists them).

## 2.21.2 -- 2026-10-24

- A new install starts like the owner's machine: the status light states have the owner's colors, effects and on/off (`lights_config.STATES`), with no repeated or confusable default color (a test keeps at least 70 apart, modes included), and `config.example.json` uses the English keys the code reads (`camera_relay`, `shutdown`, `consumption_tariff`, `communication`, `job_in_live`, `active`, `led_strip`, `led_start`) instead of the old Spanish ones.

## 2.21.1 -- 2026-10-24

- `trace.since`: deleting the trace (Delete button of the job card, which removes `data/trace.json`) also forgets the last closed job kept in memory, so `"current"` answers nothing recorded until another job starts. The history copy `data/jobs/<id>.json` stays and is still read by its id. No new operation. Tests in `test_trace_since.py`, documented in docs/api.

## 2.21.0 -- 2026-10-24

Camera relay, phase 2 of the cinema controls.

- Rebuild a video with another look: `POST /rerender?file=<video>&cfg=<json>` assembles a NEW video (`<name>-rrN`) from the stills kept with the original (`-frames.zip`), starting from the settings the original was made with (new `look` block in its .json) plus what the `cfg` changes: codec, framing, grade, speed, stabilization. Technician role. One edit or rebuild at a time. A video recorded without "keep the stills" cannot be rebuilt.
- Stabilization: `stabilize` 0 / 1 / 2 (deshake, before the crop) in the cinema keys; only in the one-video-per-camera mode.
- Burst of captures: `POST /burst?c=&count=2..30&gap=0.3..10` takes a series of photos in the background (operator role, one burst at a time); `/state` -> `timelapse.burst` is how many are left.
- `timelapse_look.unpack_frames` (inverse of `pack_frames`), tests `test_camera_rerender.py`.
- No PNG capture: the camera only gives JPEG, a PNG made from it would be a bigger file with the same picture.

## 2.20.0 -- 2026-10-24

Made from the new-user test (a person who installs everything from the zips and has none of the owner's files).

- Configuration package: `package.export`, `package.preview`, `package.apply` (`dsf/config_package.py`). One zip with the settings of the pages (`sys/workshop/config/*.json`, secrets taken out), the work zones, the person's macros (`macros/**`) and the machine modes (`sys/mode*.g`, `modestate.g`, `automodeselect.g`). Importing never overwrites: it creates what is missing, leaves identical files alone, keeps the person's file on a conflict (it can be replaced by name, the old one stays as `.bak-import`) and copies the modes only as a reference under `sys/workshop/imported/`. Paths and sizes are checked (no `..`, only the allowed folders, hash of every file). Technician exports and previews; only an admin imports. Card in the service page, section Database.
- Machine setup list: `readiness.report` / `readiness.list` (`dsf/startup_summary.py`). Every plugin's start-up card reports how many rows are pending (only after reading its files, only when the numbers change, never asking for a PIN); the service page lists the INSTALLED plugins with what each one said, "not checked" for one never opened, and nothing for a plugin that is not installed.

## 2.19.3 -- 2026-10-24

- plugin.json `dsfFiles` lists `config_package.py` and `startup_summary.py`: 2.19.2 was built without them and the service did not start (`No module named startup_summary`) when installed from the zip.

## 2.19.2 -- 2026-10-24

- New operation `trace.since`: returns only the samples of a job trace that are new since a cursor (running job, last closed job or a job of the history), for file jobs and live jobs; operator role, read only. Documented in docs/api.

## 2.19.1 -- 2026-10-24

- tools/install.sh works for a FIRST install: when WorkshopService is not on the Pi it runs DSF's own `PluginManager install` with the zip (a copy left `main.py` without the execute bit and every file owned by the login user, so DSF could neither start it nor update or uninstall it later: "Access to the path ... is denied"), starts the service and adds it to `machine.enabledPlugins` of DWC.
- tools/install.sh needs only the zip: the files and the manifest are taken from inside it (`--repo` is optional); the local Python is found as `python3`, `python` or `py -3` (on Windows `python3` is only a Microsoft Store shortcut).
- tools/install.sh update: files it creates get group `dsf`, group write and the execute bit of the manifest's executable (it warns if the login user is not in the group `dsf`; `--sudo` still gives the owner back to `dsf:dsf`).
- The pre-install check command line moved to `dsf/preflight_cli.py` so it travels inside the zip; `tools/preflight.py` is a thin wrapper.
- docs/INSTALL.md: first install vs update, zip-only, Windows, uninstalling in dependency order, "partially started" in DWC.

## 2.19.0 -- 2026-10-24

- Camera relay, cinema controls for the timelapse (dsf/timelapse_look.py): codec H.264 / H.265 / ProRes / DNxHR (mp4 or mov, tagged Rec.709), quality, 10-bit, frame rate 5-120 (23.976 / 29.97 / 59.94 exact), height up to 4K, cinema aspect crop with position, slow push (zoom + drift), LUT .cube, brightness / contrast / saturation / gamma, frame blending, fade in / out, interval ramp, stills kept as a zip with frames.csv
- A take can carry its own settings (POST /timelapse?action=begin&cfg=), frozen when it starts; presets saved in camera_service.presets
- New relay routes: GET /timelapse/preview (a still with the look applied), GET /luts, POST /luts, POST /luts/remove; /state brings encoders and luts
- Videos can be .mov and the kept stills .zip: listing, deleting and the space limits count them

## 2.18.15 -- 2026-10-24

- A save of the configuration that does not mention the keys (secrets file) no longer erases them: the Tuya meter key had vanished that way (test_config_store.py)
- tools/restore_meter_key.py puts the meter key back from the tinytuya devices.json (run with sudo)

## 2.18.14 -- 2026-10-23

- Service page: a sign-in or a logout made in another tab is followed by this one

## 2.18.13 -- 2026-10-23

- Service page: one sign-in is valid for every tab of the browser (the token lives in localStorage)

## 2.18.12 -- 2026-10-23

- Service page: the health chip sits right after the title, in the same place as in the other pages

## 2.18.11 -- 2026-10-23

- Service page: the section body no longer widens the page on narrow screens (under 900 px); wide content scrolls inside its section

## 2.18.10 -- 2026-10-22

- Fix: cutting a big piece in parts failed with "module math has no attribute without" (a wrong translation of math.sin in big_piece.py and gcode_plan.py); new test checks every math.<name> exists

## 2.18.9 -- 2026-10-22

- Height calibration of the tool moves from the Workbench to Machine: `machine.height.get / save / hook / step` (`machine_height.py`: saved calibration with revision, `zcal.g` generated by the service, hook in the mode files, the assistant steps with the movement reserved); closed G-code list: `zcal_*` macros and `jog_z`
- Sessions: 12 h without activity by default

## 2.18.8 -- 2026-10-22

- Board panel: the status strip marks the real faults itself (`fault`), the red board LEDs are no longer counted as faults
- Side-bar pin only while the bar is open

## 2.18.7 -- 2026-10-22

- Side bar of the page: the pin (keep the bar open) is always visible, also when the bar is folded.

## 2.18.6 -- 2026-10-22

- Sessions: new "session never expires" switch in Users (it disables the two duration fields). The sign-in dialog no longer opens by itself.

## 2.18.5 -- 2026-10-22

- Post-migration audit: capabilities read `ledHasStrip`, region arguments of `machine.layout` described, bridge client role class, load class and `anchor` deep link fixed.

## 2.18.4 -- 2026-10-22


## 2.18.3 -- 2026-10-22

- Sessions made clear: texts `api.signInNeeded`, `api.signedOut`, `api.signInAction` (es/en); the client of the service page opens the sign-in on the 403 of a visitor and tells the person when an action they started is refused.

## 2.18.2 -- 2026-10-22

- Sign-in dialog: DWC font and the first empty field always gets the focus (the kiosk keyboard comes out through `kiosk/kiosk-osk.py`).

## 2.18.1 -- 2026-10-22

- Sign-in dialog redesigned (icon header, 44 px fields, eye for the PIN) and the on-screen keyboard opens on touch; the dialog opens on the person's action even after a cancel; Service page keeps visited sections mounted and the side bar folds with a transition.

## 2.18.0 -- 2026-10-22

- New: the settings store `machine-pointsets` (named point sets of the Machine bed view, shared by Mesh and Level). An ordinary store: `settings.get` for the operator, `settings.set` / `settings.merge` for the technician; no new operation. Contract: `docs/MACHINE-POINTSETS-CONTRACT.md`.

## 2.17.0 -- 2026-10-22

- New: `machine.layout` (operator, read only), the data for the bed view of the Machine Mesh and Level pages: axis limits, probe offsets, where the probe can reach, M671 leadscrews, which mesh / levelling points would be probed and why one would not (outside the bed, head outside the limits because of the probe offset, inside the margin, duplicate), and the last mesh and levelling measurements. Contract: `docs/MACHINE-LAYOUT-CONTRACT.md`.

## 2.16.0 -- 2026-10-21

- New: `users.enable` (administrator): switches the roles and PINs off WITHOUT deleting the people. Off needs the PIN of the logged in administrator (counted like a login attempt), ends every session and goes back to the compatibility mode (everybody is an administrator, camera and Vision open); on needs at least one person. Users page: "Switch users off" with the PIN dialog, and a card "Users switched off" with "Switch users on". `auth.whoami` says `users_disabled`. A damaged users file still fails closed.
- PIN sign: when the PIN has the length that worked last time for that person in this browser, it enters by itself (no Enter). The service is never asked the length; a wrong automatic try forgets it.

## 2.15.3 -- 2026-10-21

- Commands history: a refusal by login or role no longer says "needs an updated WorkshopService" (that hint is only for other errors).
- Boards table: the Roto Tool Board chip is left unknown (two sources disagreed; no such board in the workshop).

## 2.15.2 -- 2026-10-21

- Audit: the date filters use the same calendar menu as Activity (no native date input); the other two filters lose the outline to match.
- Side bar: a small pin next to the fold arrow keeps the bar open when an item is chosen (remembered per page in this browser).

## 2.15.1 -- 2026-10-21

- Users page: an eye button shows the PIN while it is typed (first administrator, new user, change PIN); the PINs hide again when the dialog closes.

## 2.15.0 -- 2026-10-21

Machine v2 (phases 1 to 5, service side): see the entries below.


## Unreleased -- Machine v2 phase 4 (service)

- New: maintenance counters. A process (`maintenance`) integrates, from the single subscription of `machine_state`, power-on hours, moving hours and ESTIMATED distance per axis and for the machine, into the store `machine-maintenance` (atomic, every 5 minutes and on rest). A gap (service down, subscription lost) counts nothing and makes no jump; homing and impossible speeds are ignored; it rests when WorkshopMachine is stopped. A file job's integrated XY length is compared with the planned path (`crosscheck`).
- New: maintenance plan: `machine.maintenance.get` (operator), `machine.maintenance.done` (technician, audited, resets the item), `machine.maintenance.plan.set` (technician: items, defaults, opt-in notices). Generic default items (Z screws, belts, lens, Z couplers) until the owner edits the plan; intervals in hours (power-on or moving), distance or days; status `ok`, `due_soon`, `due`, `overdue`. Phone notice (activity type `maintenance`) once per level and cycle, in DWC's language. The overview carries the light. The profile accepts `hours_basis` in a maintenance item.
- New: run kind `offsets.verify` (camera verification of work system or tool offsets through Vision, error in mm with uncertainty) behind the capability `vision.measure`, refused with `no_vision_measure` unless Vision announces `capabilities: ["measure"]` in `GET /state`. `vision.post` allows `/measure`; `handlers/vision_call.py` takes a timeout. Contract for Vision: `docs/MACHINE-PHASE4-CONTRACT.md`. Closed-list templates `move_xy` and `move_xy_machine` (`G53`, unverified on the board).
- `PLANNED_OP_ROLES` is empty: the maintenance operations moved to `OP_ROLES`.

## Unreleased -- Machine v2 phase 3 (service)

- New: `machine.calc` (steps/mm, skew from the diagonals -> M556, backlash -> M425, ringing frequency), `machine.motion.get` (motion parameters per axis and extruder, nothing invented), `machine.shaping.get` and `machine.shaping.test` (ringing-test G-code as text). Plan kinds `config.m556`, `config.m425`, `config.m593`, `config.m203`, `config.m201`, `config.m205`, `config.m566` and the admin kinds `config.m906`, `config.m913`, `config.m917`, `config.m569` (direction and driver mode only). Contract: `docs/MACHINE-PHASE3-CONTRACT.md`.
- New: `machine.try` for M92, M906, M913, M917, M203, M201, M205, M566, M425, M556 and M593 with the automatic revert (pending file, revert after a restart, retry of a refused revert, refused with a job); M906 within the current cap of the profile (`machine.safety.max_current_ma`, default 2800 mA, hard ceiling 6300 mA).
- New: run kind `shaping.tune` (accelerometer, refused with `no_accelerometer` unless the capability is there); `capabilities.accelerometers` items give `sampling_rate` and `resolution`.
- Safety: `machine.config.apply` and `machine.try` called without `kind` / `gcode_kind` need admin; the closed list gets no template for `M569`, and any `M569.<n>` is refused.
- Fix: the multi-driver notice (`X80:80`) now also applies to M906, M913, M917, M203, M201, M205 and M566.

## Unreleased -- Machine v2 phase 2 (service)

- New: history of the calibrations (`machine.history.list/get/compare/restore`), report data (`machine.report`), tool and work offsets (`machine.offsets.get/snapshot`), limits (`machine.limits.get`), the volatile `machine.try` for M208 with automatic revert, the laser <-> pointer cross on the server (`machine.mark_cross`), run kinds `safety.check` (read only) and `homing.verify`. Plan kinds `config.g31`, `config.m208`, `config.m92` (admin), `config.g10`, `config.workplaces`. Contract: `docs/MACHINE-PHASE2-CONTRACT.md`.
- Fix: `capabilities` crashed on a real `tools[].offsetsProbed` (it is a bitmap, not a list) and read the obsolete `move.workplaceNumber` only.

## 2.14.0 -- 2026-10-21

- New: people with name + PIN and the roles viewer / operator / technician / admin, applied by the server (`users.*`, `auth.*`, `audit.list`; users file outside the SD). Without users everybody is admin as before; the first user created turns it on. Append-only audit; the history rows carry the user.
- New: machine profile (`capabilities.get`, `profile.get/set`, `preflight.run`, schema 2 with optional interlocks), `tools/preflight.py`, a generic installer `tools/install.sh` and `docs/INSTALL.md`; every `/opt/dsf` path comes from `paths.py`.
- New: shared settings with a revision (`settings.get/set/merge`), the operator work state (`workstate.get/set`), pi health history (`health.history`, database schema 6), `mine` / `user` filters in the activity list.
- New: protection guard (a safety process that alarms and lights the strip when Vision, RS485, the camera relay or another watcher dies), optional laser interlocks (`safety.status`, `docs/INTERLOCKS.md`), motion ownership per person and device (`motion.take_over`).
- Safety: the safety processes (events, jobs, risk, config guard, motion, health) no longer depend on a screen plugin; camera relay and Vision accept only their own origin (CORS), fail closed when the relay does not answer, and the camera address must be in a private network; Vision laser-cross calibration checks the machine is idle first.
- Fix: `crashSens` replaces `choqueSens`.
- Update order: install the service first, then the plugins. Back up `duet.db` first (schema 6 is applied at the first start).

## 2.13.1 -- 2026-10-21

- Fix: the black box and API key dates, and the bridge test hour, use the DWC language instead of the browser's.
- Fix: the page loads again when the DWC language changes (the process groups and other fixed texts stayed in the previous language).
- Fix: the title row of the automation cards wraps its chip instead of leaving the card.

## 2.13.0 -- 2026-10-21

- Every text the service publishes on its own (plugin data, process details, pop-ups, console messages, phone notices) goes out as a key with parameters and each page translates it in its own language; outside a request the language is DWC's (`global.workshopLanguage`). About 350 backend messages moved to the catalogs.
- Default names (live job, light scenes, zones, strips) show in the viewer's language while they are not renamed.
- New: `vision.get` and `vision.post` (the pages reach Vision through the service API), the motors released list and its automatic level 4 risk, the lights crash state fix (`crash:<drv>`).
- Fix: black box charts and the process sparklines were not drawn (component tag left by the rename); the lights row of the service page wraps instead of overflowing.
- The bridge only understands the English command words (`BRIDGE HELP|STATUS|LIST|NAME|USE|RELEASE|KEY|JOB`); the Spanish `PUENTE` aliases are gone. Run `sudo ./install.sh` in `bridge/` to apply it.

## 2.12.1 -- 2026-10-20

- Fix: the identifier of a power meter and the Tuya local key had both ended up called `key` after the rename to English, so the meter lost its key and failed with "Check device key or version". The identifier is `slot` again (the Tuya key keeps `key`). The secrets file is converted by the one-off migration.

## 2.12.0 -- 2026-10-20

- The messages that people read are keys plus parameters (`dsf/messages.py`, catalogs `dsf/i18n/es.json` and `en.json`), not finished sentences. The activity history stores `message_key` and `message_params` next to the Spanish text (schema version 4), so the page and the phone ask for the language they need. The old Spanish-to-English dictionaries of the backend (`i18n_events.py`, `i18n_notices.py`, `phrases_en.json`) are gone. Free text that is not ours (a firmware error, something a user typed) is stored and shown as it is.
- Done: every event of the history (jobs, zones, mode, power, shutdown, settings, notifications, meters, health, camera, backups, rollback, black box), the notification titles, and the texts of the phone notices.
- Still plain Spanish sentences: the answers of the API and the status texts of some modules (listed in PENDIENTES).
- The one-off migration script converts the old rows of the history that one template explains.

## 2.11.1 -- 2026-10-20

- More Spanish ids and values changed to English; the old path/folder migration code was removed (the old layouts no longer exist); the black box card and two page attributes broken by the rename were fixed.

## 2.11.0 -- 2026-10-20

- All the code is in English now: names of functions, variables, files, folders, settings keys, data keys, enum values, SQLite tables and columns (activity, consumption, commands), the global variables of the G-code macros and the i18n keys. Only the texts shown to people are still Spanish (and English in the language switch).
- Stored data is converted ONCE by a separate script (not part of the service): settings and data files in sys/workshop, the database, the macros of the SD and the maintenance file (mantenimiento.json is maintenance.json). Run it with the service stopped; it backs up everything first.
- The service no longer migrates old layouts at start: the database is created with the English schema (version 3) and the old paths/tables are not looked for.
- Settings of the browser (localStorage) have new names: the pages start with the default look once.

## 2.10.26 -- 2026-10-20

- G-code bridge: new setting "Skip the material G-code the program sends" (off by default). When on, the M98 lines that call a material macro (macros/laser, laserfocus.g, livemark.g) are answered ok and not run. Needs the bridge restarted.

## 2.10.25 -- 2026-10-19

- Database page: the backups that will be deleted on their own are now marked in the list of copies (orange tag with the date, stripe and tinted row), not only in the notice above.

## 2.10.24 -- 2026-10-18

- Black box: new verdict "stuck" when the last line shows a lock or a slow task of a minute or more (16-oct case: bridge busy 13 min, status light and motors slow 12-14 min). Before it said "calm: power cut".
- Comments of the page code in English; `safe-saving.js` synced with the shared copy (remembers files that do not exist for the session).

## 2.10.23 -- 2026-10-18

- G-code bridge 3.5.0 (needs `sudo` to install, see bridge/README.md): a job sent before the homing no longer runs on its own afterwards. Cause found 2026-10-18 10:53 in the DSF log: the material macro (mdf6mm.g -> laserfocus.g) was aborted for lack of homing, the program kept streaming its lines, and when the homing ended the lines that were still coming ran without the macro (zone, focus, laser offset) and cut. Now: (1) while any axis is not homed (and the firmware does not allow moves before homing) the bridge refuses the orders that move or fire the laser, only G28 passes (`motion.state` now says `needs_homing`); (2) after one order of a job is refused, the rest of that job is refused too (30 s after the last refused order, or until a new BRIDGE JOB START), so the program has to be sent again from the start.

## 2.10.22 -- 2026-10-18

- Laser guard (`laser_guard.py`): a laser power that nobody turned off no longer stays set. A program that left (cancelled, connection dropped, final M5 timed out, first move refused for lack of homing) could leave the power set and the next move without its own S (the jog buttons of DWC) marked the work. In Laser mode, after any bridge activity or power above zero, once the machine has been idle 5 s, no live job is open and the bridge has been quiet 10 s, the service sends one M5. It never acts during a live job or while the bridge is still sending.

## 2.10.21 -- 2026-10-18

- Internal: first step of the migration of the code to English. About 1700 identifiers of the Python code (functions, variables, parameters, attributes, constants; 10000 uses) were renamed word by word with `TallerPlugins/tools/refactor/rename_py.py`. Nothing visible changes: keys of the JSON, dicts, SQL columns, API operations, configuration and file names were NOT touched. Module (file) names and names that would clash are left for the next steps.

## 2.10.20 -- 2026-10-18

- Access keys: an expired key now shows a red "Expired" label and its row is dimmed; a key that expires within 7 days shows an orange "Expires soon" label. Before, only the date was shown.

## 2.10.19 -- 2026-10-18

- The two times of the live job are kept separate and explained as two steps of the same timeline: "Consider it free after" (Machine movement) frees the movement, asking to confirm if the job is still open; "Finish after" (Live job) closes the job and releases the block. Each text now says what it does and how it relates to the other.

## 2.10.18 -- 2026-10-18

- Live job texts (Services page, card and "More detail"): they no longer present the raw "BRIDGE JOB START / END" line as the way to mark a job (a program's G-code cannot send it). They now say how it really works: it starts with a material macro (livemark.g) or the line M118 P0 S"BRIDGE JOB START name", and ends with M118 P0 S"BRIDGE JOB END", on stop or cancel, if the machine halts, or after the chosen rest time.
- Automatic air card: the turn-off delay is no longer a select in the middle of a sentence; the rule is one line and "Turn off after M5" is a row of quick buttons (0, 2, 5, 10, 30 s, plus the saved value if it is another).

## 2.10.17 -- 2026-10-18

- Services page: the movement settings have their own card, "Machine movement" (they belong to the movement owner, not to the live job). It shows the current state (Free, File job, Live job, Bridge orders...) and two boxed options written as what happens: "Nobody (recommended)" and "I decide" (only a file job blocks, as DWC does; machine settings stay protected). The seconds that free the movement are quick buttons under "Advanced". The live job card keeps only how it is finished: the program's end signal, or a rest time. The 30 minute "no activity" timeout is no longer shown (it stays as an internal safety value).
- Black box card: a note says the small charts are the minutes before the shutdown (saved, not live) and that the live charts are in System health.

## 2.10.16 -- 2026-10-18

- Black box card: new green block "It is working again now" (the Pi started again by itself, nothing to do to get back to normal; home the machine if the Duet board also lost power; the notice stays until Hide is pressed). The calm verdict now says plainly that a power cut is the most likely cause, and "What to do" became "So it does not happen again".

## 2.10.15 -- 2026-10-17

- Movement lock settings, one place for everything that moves (jog, Workbench, Vision, frame...): Services page, live job card, "Movement lock". Mode "Protected" (a live job or bridge orders block; the quiet time that frees it is configurable, 3-120 s, default 20) or "Like Duet" (only a file job and a stopped machine block, as DWC does; settings changes stay protected). The seconds of idle after which an open live job is closed by itself are configurable too. API: movement.lock (mode, release_s, idle_s), published in data.motion.settings. Test: dsf/test_mode_lock.py.

## 2.10.14 -- 2026-10-17

- The jog is free at once when a job is over: when the program ends the live job (BRIDGE JOB END / CANCEL) or the person closes it, the orders sent up to then no longer count as bridge activity, so the jog does not wait 20 s more ("the G-code bridge sent orders N s ago") with the machine already parked. Test: dsf/test_bridge_job_end.py.

## 2.10.13 -- 2026-10-17

- Last unclean shutdown card: a "What to do" list with concrete steps for each diagnosis (calm = check cable, plug, Consumption chart of that hour and the meter schedules; heat; CPU load; memory; unclear; no data), and the calm diagnosis says plainly that the power was most likely cut at once.

## 2.10.12 -- 2026-10-17

- Raw lines of the last unclean shutdown card: readable code font, more line spacing, a dark framed box and thin dark scrollbars instead of the thick light browser ones.

## 2.10.11 -- 2026-10-17

- Last unclean shutdown card redone: it says in a few words what happened (calm up to the last data = power cut, or heat / CPU / memory), draws the last minutes (CPU, memory, temperature, load), shows the machine state and the locks and slow tasks of the last reading, and keeps the raw lines one tap away.
- Services page: the process search finds what a person types ("luz" finds "Luces de estado", "gcode" finds G-code, accents and capitals do not matter, words in any order) and also looks in the category and in the explanations of each process; the separate service "G-code bridge" had no texts in its detail (it showed the raw keys).

## 2.10.10 -- 2026-10-17

- Camera status now reports what captures and timelapse need on the Pi (`requisitos`: ffmpeg, Pillow, writable folder and free space, a clock that is not in the past), so the start-up card of the Camera page can say what is missing. Nothing is changed by reading it.

## 2.10.9 -- 2026-10-17

- Job preview: a file made of tens of thousands of tiny separate strokes (a 4.4 MB engraving gave a 9 MB answer that took 40 s and left the Workbench on "Reading...") now stays under the vertex budget: the travel moves go first, then the shortest strokes. The numbers of the job still come from the whole file; the page already says "simplified n of total".

## 2.10.8 -- 2026-10-16

- Live job: it now ends by itself when it is stopped. M0 / M112 from the program, the machine halting, or the machine resting 30 s without activity close it (before: it stayed open until the 30 min timeout and the jog showed "live job open ... move anyway?"). Setting `trabajo_en_vivo.parada_reposo_s` (0 = off).
- Live job: two starts in a row (the material macro and the program's own mark) are one job, not two.
- Status strip: the "laser firing" state is held for 4 s after the last shot, so the strip no longer re-splits every second while cutting.
- Services page: a fixed "Last fall" row stays after the unclean-shutdown card is hidden (View report / Download); new operation blackbox.show.

## 2.10.7 -- 2026-10-16

- Black box: the NUL bytes a power cut leaves in the log no longer show as boxes in the report.
- Job trace: the toolpath no longer shifts while the machine moves (tool offset measured idle, plan key without the machine position, rebuild starts in the zone the job began in).
- Services page: the status lights row shows On / Off; the live-job text no longer mentions M118.

## 2.10.6 -- 2026-10-16

- API keys: the copy buttons of the key and of the curl example copy again (inside a dialog the fallback textarea must live inside the dialog: Vuetify keeps the focus there); they only show the check if the copy worked. The received commands page uses the same helper.

## 2.10.5 -- 2026-10-16

- API keys: the extra allowed and the refused operations are lists to pick from (with the description of each one; a pattern like light.* can still be typed) and each key of the table lists them instead of a counter.

## 2.10.4 -- 2026-10-16

- The Activity history records when the G-code bridge starts and stops and why: at the Pi boot, from the page, by itself (unexpected exit) or stopped (bridge_watchdog.py, watched by salud_poller from the systemd start time of the unit).

## 2.10.3 -- 2026-10-16

- API keys: the Cancel button of "Create key" showed the name of its text key (the text "common.cancel" was missing in es / en).

## 2.10.2 -- 2026-10-15

- Bridge switch: the permission is probed by trying the real action (pkcheck only lets root pass details); with the bridge stopped the permission is "not known" and the switch stays usable.

## 2.10.1 -- 2026-10-15

- Services > Bridge: start / stop of the bridge with polkit instead of sudo (DSF starts its plugins without the right to change user, so sudo never worked from the service). One rule (bridge/install.sh, "control") lets dsf start and stop ONLY the bridge unit. "Stays on after a power cut" = the unit is always enabled and a flag file (sys/workshop/data/bridge-disabled, ExecCondition of the unit) decides if it comes back at boot.

## 2.10.0 -- 2026-10-15

- Services > Bridge: a switch starts / stops the bridge of THIS Pi (enable + start, stop + disable: it survives a power cut). The permission is one polkit rule limited to that unit (bridge/install.sh, "control" / "no-control"). Operations bridge.service and bridge.service.set.
- Live job: the start is refused when the machine is paused, halted by an error, cancelling, off or updating.
- Jog: the "orders sent 0 s ago" block no longer comes from the rounded epochs of bridge-state.json (the ages of the clients are used).
- Bridge 3.4.0: refuses movement / laser orders while the machine is paused or halted (block_when_unfit).

## 2.9.8 -- 2026-10-15

- frame.start / frame.stop / frame.status: the service traces a frame itself (not a job): once, N times or until stopped, with the laser limited to 10 %; the movement owner is reserved while it runs

## 2.9.7 -- 2026-10-15

- jobs.preview: the work runs also carry their feed (layers of a laser job: power + feed)

## 2.9.6 -- 2026-10-15

- Job trace: a trace left active on disk by an earlier run (service restarted in the middle of a job) is closed as interrupted when no job runs, so the page can take it off the map

## 2.9.5 -- 2026-10-15

- jobs.preview: reads a G-code file of 0:/gcodes without running it (path, estimated time, distances, pieces, box and outline) for the Work table
- The Spanish messages shown to the person have accents; the English translation matches with or without them

## 2.9.4 -- 2026-10-15

- Spanish texts with accents and enie; example files offered once (examples.list, examples.create)

## 2.9.3 -- 2026-10-15

- Removed the on-screen keyboard workarounds (op kiosk.hide_keyboard, its handler and the kiosk helper): the cause was the closing tap falling on a text field, fixed in the Jog and Camera plugins

## 2.9.2 -- 2026-10-15

- Processes list: each internal process shows when it runs (Auto / Always / Never) with the reason (which plugins need it), and a process at rest shows "At rest" instead of a heartbeat warning; the choice is saved with modules.set
- G-code interceptor: connects to DSF only while the automatic air is on (or forced on in the processes list); it rests otherwise
- Database section: the option about old meter readings appears only when Power Usage is installed and enabled
- Lights at rest publish an empty status text (test updated)

## 2.9.1 -- 2026-10-14

- Processes list: the link "see details and settings" of the G-code bridge and of the database goes to their section (the cards only exist while their section of the side bar is shown, so the link did nothing)
- Health: the bridge is looked for under its real unit, workshop-gcode-bridge (alias taller-puente); the old duet-bridge unit is gone

## 2.9.0 -- 2026-10-14

- Processes and automations section redesigned: a strip of tiles (service state, CPU and memory with their last minutes, how many processes are fine / late / failing, restarts and errors, load on the board); filters by category, "only with problems" and search; each process is a card with its heartbeat pace (average interval against the expected one), CPU, loops, errors and relaunches, and unfolds into what it is, what it is for, what happens if it stops, what it relies on, where it is adjusted, plus the history of its CPU and interval over the last minutes (kept in memory in the page, nothing is asked of the board)
- Each automation (air, status lights, turn off when done, live job) unfolds into what it does, when it acts and what to keep in mind
- Status lights: the copy of the board's virtual strip (laser, outputs, fans...) is only worked out and published while the Lights page (Advanced tab, board signals panel) is open, and then at most every 2 s; it followed every on/off of the beam during a cut and made about 160 calls a minute to the board's server even with the status lights off (new viewing topic lights_board)
- docs/PROCESSES.md: the same documentation of every process and automation

## 2.8.5 -- 2026-10-14

- Cleanup: the page route is /Plugins/WorkshopService (the repo folder, the page file and the translation namespace lose the old name); the log is workshop-service.log; the LED handshake macros live in 0:/macros/workshop/; no more migration from the old plugin Id, and no mentions of the removed custom G-codes
- G-code bridge page: switch "Allow position queries during a live job" (queries_in_job); bridge 3.2.0: the queries use their own code channel (Telnet) so a slow cut does not make them time out
- G-code bridge page: "Wait per order (s)" (order_timeout_s, up to 300) in the limits; the bridge answered an error to the program when the board took more than 15 s to accept a line of a slow cut
- Job trace: 4 samples per second instead of 1 (the path of a live job was drawn with long straight chords); the file is rewritten less often as it grows
- Status lights: while a job runs without effects the turns mode no longer rotates the strip and the board LEDs (it shows the states split in zones, or only the first one if they do not fit)

## 2.8.4 -- 2026-10-14

- G-code bridge page: restart button in the card header (double tap; the bridge leaves and its unit starts it again, no sudo). Bridge: the automatic client name stays with the IP (client1, client1-2) instead of growing with every connection

## 2.8.3 -- 2026-10-14

- Status lights: lightOn (the Light on / Light off buttons and their state) follows the real zone colour of the lighting on every tick, so a light switched on or off by another path no longer leaves the buttons stale

## 2.8.2 -- 2026-10-14

- statusIndicator carries how the states combine (combine: priority / split / turns, turn_s) so the arrow tab of the control bar can show stripes or take turns

## 2.8.1 -- 2026-10-14

- Services page: the load on the Duet explains its color (limit, which area generates the calls, share of each call with a bar); header is a card like the other pages
- Status lights: the mirror the pages get (statusLightSegs, ledTira, statusLightColor, statusLightModos, lightsInfo power) comes from a frozen frame with every effect lit, so a blinking state repaints the strip (M150) but no longer publishes a new value per phase (about 400 fewer plugin-data calls per minute with a blinking state)

## 2.8.0 -- 2026-10-14

- Activity summary: new API operation activity.summary (events per type, jobs started / finished / cancelled, job time and kWh, the finished jobs and the last failures of a date range, with the English text)
- Test of one notification type: notifications.test accepts a type and sends what a real event of that type would send (its attachment, priority and camera), marked as a test, skipping the type switch, the quiet hours and the mute

## 2.7.1 -- 2026-10-14

- Services page: the title card (with the state summary) and the stopped-service notice are a header that always shows, whatever section of the side bar is open, like in the other plugins

## 2.7.0 -- 2026-10-13

- The Services page has a side bar like the ones of Vision and the Work table (Summary, Processes and automations, G-code bridge, Received commands, Database, API and keys, DWC password); the heavy sections load only when they are opened
- The G-code bridge debug view can be filtered by client

## 2.6.0 -- 2026-10-13

- A stopped or disabled plugin now stops its part of the service: Camera (timelapse and watcher; the camera relay rests only when Camera, Vision and the Work table are all stopped, because they share it), Power (meter reader) and Motors (driver polling), besides Lights. They come back by themselves when the plugin is enabled (service_modules.py)
- Lights stopped also clears the data the screens mirror (statusIndicator, lightsInfo)

## 2.5.0 -- 2026-10-13

- English for the texts the service sends to the pages: the activity history carries descripcion_en (hand written patterns per event in i18n_events.py, then the phrase table phrases_en.json), the notification types carry etiqueta_en and the Lights states texto_en. The history stays stored in Spanish. First step to remove the DOM translation layer.

## 2.4.0 -- 2026-10-13

- Lights: the M150 of one paint go to the board in ONE call (58 ms against 230 ms for three codes): the same animation costs about a quarter of the board time
- Database: the repair of bad dates is gone (db.repair_dates, the button and the table fechas_reparadas, dropped at start): it was a development bug that cannot come back

## 2.3.2 -- 2026-10-13

- Lights: the strip is repainted only when what the STRIP shows changes. The previews of the page (the states, the modes, their colours) changed with their own effects and each change repainted the strip: ~180 M150 per minute with nothing changing
- Lights: the end-of-job flash starts dark, so N flashes are N visible flashes (when the state showing had the same colour as the notice, e.g. the green of a live job, the first one melted into it and only N - 1 were seen)
- Lights: a heater without sensor (about -273 C) is not listed in the board signals in Laser / CNC mode

## 2.3.1 -- 2026-10-13

- Lights: the CAN LED of the board stays lit while the communication is fine (before it blinked slowly like the real one and cost ~182 M150 per minute, shown in yellow on the Services page); it blinks fast only on a CAN problem. Setting leds_placa.can_parpadeo: falla (default) / siempre (the slow blink again)

## 2.3.0 -- 2026-10-13

- Everything the service writes is in English: lights.g and config.g comments, driver-stall.g, black box keys and report, the log files, the default reasons of the configuration history, the large-part job comments. The readers of these files accept the old Spanish ones too
- Active risks carry both languages (texts {es, en}; texto stays Spanish for old pages) and risk.start takes the optional text_en; the power-off method text is bilingual (desc_en / aviso_en, global.apagadoDescEn)

## 2.2.2 -- 2026-10-13

- Fix: the Lights handler dropped leds_placa.con_iluminacion when saving, so the option "board LEDs do the same as the zone when the lighting takes it" never stayed saved. It now does (with a test of what the page sends)

## 2.2.0 -- 2026-10-13

- API access keys for external services: each service gets its own key (header X-Workshop-Key) with its own permissions (operation classes, patterns, refused patterns, expiry), shown once and stored only as SHA-256; managed from the service page (keys.list / create / update / revoke, DWC session only). A key never reaches the administration operations; an invalid key is refused (401), never treated as the open mode; the history of received commands shows the name of the key
- Lights: a heater without sensor (about -273 C) in Laser / CNC mode is shown as "no sensor", not as a red fault

## 2.1.0 -- 2026-10-13

- Lights: while a job runs (file or live) the strip and the board LEDs keep their colours but not their effects, and are repainted at most twice per second (and less when the Duet takes long to answer a paint). Setting status_light.efectos_en_trabajo: sin_efectos (default) / con_efectos. Emergency stop, crash, risk, jog without limits, cancelling and paused keep their effect; the screens always animate

## 2.0.2 -- 2026-10-13

- Fix: the spot reads (inputs for the communication channels every 10 s, the RS485 data every 5 s) left a closed subscription open in DuetControlServer each time, because it only notices a gone subscriber when it sends the next patch and those fields rarely change: ~6 sockets per minute, 6000 after 17 h and the process at 180 % CPU. The short subscription now also asks for state.upTime (changes every second), so it is released within a second (measured: 30 reads left 29 open without it and 0 after 10 s with it)

## 2.0.1 -- 2026-10-13

- Health: the health data now carries the open sockets of DuetControlServer (dcs.fds) and an alert (salud_servicio) when they pass 2500: it keeps ~6 sockets per minute open after the client is gone and its CPU follows them (measured 6000 sockets and 180 % CPU after 17 h; a restart brings it to ~20 %). The cause is not found yet

## 2.0.0 -- 2026-10-13

- Central API instead of the custom codes: POST/GET /machine/WorkshopService/api with named operations (api.describe lists them); M9003 is no longer intercepted (only M3/M4/M5), the /code endpoint and the Spanish aliases are gone
- Single owner of the movement (motion.state / ask / reserve / renew / release, data.motion): the jog, the pages, Vision and programs ask it; a reservation of another page or orders of the G-code bridge block moves with the reason
- Confirmations decided by the service (level 3 / 4 with texts in Spanish and English); local key for the programs of this computer (0:/sys/workshop/data/.api-token)
- Macros call the service through 0:/sys/workshop/macros/service-call.g (global variable mailbox, written at start); driver-stall.g raises global variables instead of a custom code
- Removed (only used by BtnCmd): activity and energy reports to globals, energy read to globals; help and echo replaced by api.describe / api.ping
- G-code bridge 3.1.0: BRIDGE JOB START / END / CANCEL tell the service through the API
- Services page: list of the API operations with a test field; official DWC localization of the API client texts

## 1.37.0 -- 2026-10-13

- Services pages use the official DWC localization (plugins.WorkshopService.*, es.json / en.json)
- Lights: when more states are active than LEDs in the status zone they rotate (or the least important are hidden, chosen in the Lights page); board LEDs can follow the lighting

## 1.36.0 -- 2026-10-13

- Notifications: the camera of the photo / video can be chosen (default for all notifications and one per event type)
- Activity history: every event keeps its data, the machine context at that moment and its origin; text search; camera events carry the camera and the time it was silent

## 1.35.1 -- 2026-10-13

- Communication with the Duet: the channel selects open once the advanced unlock is done (they were read-only), plus an explanation of what each option does
- Services: new card with the DSF subscription state, board calls per minute by type and the lights load
- Black box: the "top" line only measures this service's own threads (no other process is read, so AppArmor no longer logs denials)

## 1.35.0 -- 2026-10-13

- DCS load: IPC call counter (Services and black box), publish only on change, pollers read drivers only while the Motors page is open (heartbeat)
- Received commands: origin detail (channel, kind, page/plugin tag, client, job file, result, timing), filters and last-hour counters
- Database settings only in Services; Health keeps a read-only summary
- G-code bridge 3.0 readers (jog activity, origin, health)
- System wording instead of "Pi" in texts

## 1.34.0 -- 2026-10-13

- Live job closes when the machine (Duet) restarts; default inactivity timeout 30 min
- Jog moves with a paused file job; quiet live job asks for confirmation (C1); active live job or bridge activity blocks
- Communication channels: jog channel "auto" (Aux2 when free), manual change locked behind an advanced unlock (A1 K"entiendo")
- Lights and status: the status indicator module follows whether the Lights plugin is enabled
- Removed the name of any specific cutting program from texts and comments

## 1.33.0 -- 2026-10-13

- A single subscription to DSF for the whole service (nobody asks for /machine/status); counter in Services
- Lightweight black box: a circular log that survives a forced shutdown, report and notice at startup after an unclean shutdown
- Closing of live and file jobs (inactivity deadline, Close job button, hours and kWh cut at the last activity)
- Lightweight job trace (only with the view open); DRV_STATUS according to the chip and speed from the current move
- Notices by type (photo, short video, quiet hours) and repair of damaged dates
- Habilitar y deshabilitar motores (M9003 P"motors")
- Jog: the G90 on release is not lost, it refuses to move with a job or bridge activity, the channel is not changed in the middle of a gesture
- RS485 sin dispositivos y reglas de Duet3D (dwcVersion 3.6, sbcConfigFiles)

## 1.15.1 -- 2026-10-10

- Consumption: the kWh of a period add up only the increases between readings (a meter counter restart or a reading at 0 no longer leave the month or year at zero); the reader splices a real restart

## 1.15.0 -- 2026-10-10

- Several consumption meters (for example the bed separately): the history stores which meter each reading belongs to (the previous ones stay as general); consumoActual carries each meter and the total; queries by meter or total
- Shut down everything first cuts the extra meters in their order and the one that powers the Pi last
- New notice medidor_alarma (stuck relay or SSR); the jobs add up or break down the other meters

## 1.14.4 -- 2026-10-10

- The page warns when the service backend is stopped; "connected" requires the process to be running

## 1.14.3 -- 2026-10-10

- Pi service: Vision (OpenCV, TallerVision) appears separately in Services with its state

## 1.14.2 -- 2026-10-10

- Tipo de evento fuego (Vision vio llama o humo durante un trabajo): aviso urgente en Actividad y al celular
- Pi service: small status chip with an outline (DISENO.md)

## 1.14.1 -- 2026-10-10

- Relay: after changing exposure or light (/control) it no longer returns the old photo; /snapshot?fresca=1 asks for a new photo

## 1.14.0 -- 2026-10-10

- Camera relay: several cameras (the main one and those of taller-camaras.json, /c/<id>/stream); state with fps, kB/s, delay and clients; dated captures; timelapse per job (ffmpeg, in 0:/camara/); photo of the main one attached to the end, pause, error and emergency notices; notice if a camera drops (type camera in notifications)

## 1.13.3 -- 2026-10-10

- The "Command is not supported" notices while the service restarts are noted in Activity as type service, with an explanation; the console's origin shows as "DWC (G-code)"
- The page sends its commands over HTTP from the first one (taller-http.js) and retries ~15 s if the service is restarting

## 1.13.2 -- 2026-10-10

- M9003 P"log" accepts N (name of what was saved): saved calibrations and settings are noted in Activity

## 1.13.1 -- 2026-10-10

- Communication: SBC comes out Free or Shared according to real use (programs connected to the G-code bridge, checked every 10 s); texts with "live jobs"

## 1.13.0 -- 2026-10-10

- Received commands shows where each one came from (page over HTTP, network, Telnet, USB, job...); the history table gains the column by itself at startup
- Riesgo activo: motores sueltos solo mientras X/Y no tengan homing
- Activity: the active risk is noted at the start and at the end with its duration; "risk" and "calibration" notifications; M9003 P"log" T"calibration|config|warning" M"text" to note calibrations and changes
- Tarjeta "Trabajo en vivo" (nombre nuevo)

## 1.12.1 -- 2026-10-10

- The job card is renamed "Live job" (also through the board's USB)

## 1.12.0 -- 2026-10-10

- DWC password: card to set it, change it or remove it (M551 in sys/config.g with a backup, valid instantly); M9003 P"password"; it never stays in the command history
- Riesgo activo (estandar de advertencias, nivel 4): risk_rules.py publica riesgoActivo; detecta calibracion de choque, PID en curso y motores sueltos
- Crash: with the no-limits jog active, driver-stall.g always cuts
- Visible name: Pi Service (Workshop - Pi Service)

## 1.11.0 -- 2026-10-10

- The pages send their M9000/M9003 commands to the service over HTTP (POST /machine/PiCustomCodes/code) instead of through the Duet's queue; only those commands, on one line; with a password in DWC it requires a session. New DSF permission: registerHttpEndpoints (approved by the user 2026-10-10). The macros and live jobs keep using M9003

## 1.10.0 -- 2026-10-10

- M9003 commands in English (P"job" S"start", P"power" S"method", P"lights"...); the names in Spanish keep working as aliases
- Camera relay: the url is shown and can be changed (S"url")
- driver-stall.g manda P"jog" S"crash"

## 1.9.1 -- 2026-10-10

- Communication with the Duet: lists the 14 RRF channels with their use; only the safe ones can be chosen (free Aux2 and Aux, SBC); those reserved by DWC or the Duet and those taken by a PanelDue cannot be chosen; a saved one that is no longer valid goes back to auto or SBC with a notice; How it works explained on the card, which is at the very top

## 1.9.0 -- 2026-10-10

- Shutdown: Relay method (a Duet output that cuts all the power, M42 P<n> S<0|1>, config apagado.rele); Automatic chooses meter, then relay, then PS_ON, and if there is nothing it only shuts down the Pi

## 1.8.2 -- 2026-10-10

- No-limits jog crash: driver-stall.g with a calibration mode (global.choqueCal only counts, does not cut), for the Crash tab of Motors; it updates by itself at startup if it is an earlier version
- jogLibre publishes vMaxMmS (from what speed crashes are detected)

## 1.8.1 -- 2026-10-10

- Communication with the Duet: the channel through which the Pi sends its G-code is no longer fixed (it was Aux2). It is chosen on the page (Automatic / Aux2 / Aux / SBC for the service's codes; SBC / Aux2 / Aux for the jog) or with M9003 P"comunicacion"; it shows which channel is free, taken by a PanelDue or terminal (M575 in config.g) or does not exist on the board
- The no-limits jog block lets only the jog's channel through (before, always SBC)

## 1.8.0 -- 2026-10-10

- Shutdown: choose how it turns off (Automatic / Meter / PS_ON with M81, M81 S1 if something is hot) and whether the Pi is also shut down; Shut down now, at the end and the timer use it and say exactly what is going to happen (apagadoMetodo, global.apagadoDesc)

## 1.7.4 -- 2026-10-10

- Live job: the trace reads the G-code of the file job (gcode_plan.py) and saves the exact path with the position in the file
- Lights: the no-limits jog (and a crash) show on the strip even if the status lights are off (it can be turned off in Lights); its color is converted to LED values (gamma 2.2: red looked pink)
- Trabajos en vivo (por red o USB): textos genericos
- Pagina de control: tema claro y linea de diseno comun

## 1.7.3 -- 2026-10-10

- No-limits jog: the axes no longer hesitate nor keep moving after release (the block on foreign moves no longer holds back the jog's own moves)
- Luces: valores de fabrica 10 LEDs de iluminacion + 10 de estado (para tiras de otras maquinas)

## 1.7.2 -- 2026-10-10

- Page: common design line of the plugins (colors by meaning, menu icon in the header)

## 1.7.1 -- 2026-10-10

- Lights: on stop, crash or no-limits jog the legend shows only that state (before it added the mode color, which is not seen on the strip)
- Publishes the colors of each mode (statusLightModoColores) so that the sidebar's mode buttons use the color assigned in Lights

## 1.7.0 -- 2026-10-10

- Lights: 'Supply off' is combined like the other states; selectable status zone (main strip, zone of an additional strip or none)
- Page: legible texts with DWC's light theme; the LED strip scales with any number of LEDs

## 1.6.7 -- 2026-10-10

- Lights: "Supply off" state (state.status off after M81 / PSU Stop): the whole zone in amber while the supply is off, with priority right after stop

## 1.6.6 -- 2026-10-10

- Status lights: with the no-limits jog active, the whole zone blinks with the color chosen in the jog (without sharing with other states); a crash or an axis out of limits takes the whole zone in fast red

## 1.6.5 -- 2026-10-10

- Luces: colores de fabrica sin repetidos (modo Laser violeta, cancelando magenta, falla RS485 rosa, aviso RS485 azul celeste, laser amarillo, trabajo en vivo verde lima, sin homing turquesa)
- New status lights: "crash or axis out of limits" (fast blinking: a driver crash in the last 15 s or an axis with homing outside M208) and "no-limits jog" (slow blinking while the mode is active)

## 1.6.4 -- 2026-10-10

- Job history: each finished job is saved in 0:/sys/taller-trabajos/ (indice.json + one per job; last 50, up to 100 MB) with its result finished/cancelled
- Jog: extra axes (U, V, W, A, B, C) held from the jog (`M9003 P"jog" S"eje" L"U" V<-1..1> F<%>` / `S"stop_eje"`), with the same watchdog, limits, speed and no-limits mode as X/Y/Z

## 1.6.3 -- 2026-10-10

- No-limits jog: fewer false driver crashes (filter F1, sensitivity 8 by default, the warnings at the start of each move and with the motor still are ignored); the driver id comes out right (0.0, not 0.0.0.0)
- If the mode turns off by itself (crash, block, job), the jog does not keep moving with the finger still pressed: you have to release and touch again
- Outside the mode, the jog does not send moves of axes without homing (before every segment gave "G1: insufficient axes homed")

## 1.6.2 -- 2026-10-10

- Lights: the page's JSON can arrive by file (`F"0:/sys/taller-luces-envio.json"`) besides `J"hex"`: with several strips and zones the command went over DSF's maximum length ("Failed to serialize code (too long?)" -> "Could not apply: Unexpected token 'E'")

## 1.6.1 -- 2026-10-10

- No-limits jog: the heartbeat for the board's fallback is sent directly (before, the jog's queue emptied it and the board restored the limits after 10 s: "G1: insufficient axes homed")
- Two modes: "sinHoming" (M564 S0 H0) and "fueraLimites" (M564 S0 H1, requires homing of X/Y/Z); configurable blink color
- Block while it lasts: only the moves of the jog and the HTTP channel pass (DWC's console and panel); a job, a live one or another macro/service is rejected with an error, the mode turns off and an M291 notice appears

## 1.6.0 -- 2026-10-10

- Jog: "no-limits" mode (`M9003 P"jog" S"libre" A1|A0`) to move without homing or a few mm outside M208: `M564 S0 H0` only while it lasts and it is restored on exit; margin over M208 on axes with homing, reduced speed and current (`M913`), per-driver crash (`M915 ... R2` + `sys/driver-stall.g`, `M9003 P"jog" S"choque"`), exits by itself without movement / with a job / with a live job, heartbeat `global.jogLibreTs` for the board's fallback (`sys/taller/jogFreeFailsafe.g` from `daemon.g`) and restoration at startup. Settings in `sys/taller-jog.json` "libre"; state in the `jogLibre` data
- Jog: the clipping to the limit no longer jumps at once when the axis is outside M208 and moves inwards
- kiosk: `wifi-vigilante.sh` (now `wifi-watchdog.sh`) keeps the Pi on the DUET Wi-Fi

## 1.5.0 -- 2026-10-10

- Lights: configurable from the Lights page (`handlers/lights.py`): strip order, extra zones in any order with color and switch, several strips (other outputs `M950 E<n>`), startup animation, effects (end of job, pause), preview without saving with the real calculation, "no LED strip"
- Status lights: simultaneous states (laser, air, live job, no homing, failure and RS485 notice) combined by priority, turns or split; the strip is painted ONLY by the Pi (`daemon.g` no longer paints)
- The interface copies the strip: `statusLightSegs`, `statusLightActivos`, `statusLightModos` and `ledTira` (the whole strip in order, for when the lighting has control)
- Shutdown with timer: `M9003 P"apagado" S"temporizar" N<min>` / `S"cancelar_temporizador"` (supervised process, notice 1 min before, never cuts a job)
- Services: metrics per process, G-code (Telnet) bridge card with control, charts and security, history of received commands, test each M9003 from the list, other workshop services (RS485)
- Interceptor: when it stops it answers the code in progress and returns the pending ones (an orphan M9003 used to jam the HTTP channel)
- No secrets in the code: Tuya meter configurable from the UI and only in `config.json` (permissions 600); notifications in DWC's language
- Less sudo: camera relay inside the plugin; `reset_total` asks for the Pi restart before the M999
- jog_move reads the machine's settings (`sys/taller-jog.json`); motor_poller publishes accumulated hiccups

## 1.4.0 -- 2026-10-09

- "Workshop services" page redone: state of the internal processes (up to date / late / with errors, last error, relaunches), automatisms with a switch (air with M3/M4 and its delay, status lights, shut down at the end), last M9000/M9003 received and M9003 command reference taken from the docstrings. The duplicate bar buttons, echo/beep and the presets table were removed (M9000 keeps working)
- `heartbeats.py`: the background threads start supervised (they relaunch themselves if they die) and publish `serviciosInternos`; also `ultimosComandos`, `handlersInfo`, `servicioIniciado`, `airAssistRetardo`
- `M9003 P"airassist" S"retardo" D<s>`: seconds between M5 and turning the air off
- Errors of a plugin in Activity: consecutive "[Plugin]: ..." lines are merged into ONE event (a traceback was ~20 "Error" events); uncaught thread errors go complete to picustomcodes.log and to DWC as a single line
- ntfy: the repo's `config.json` no longer carries a topic; on the first start a random one is generated (`taller-<host>-<hex>`). `M9003 P"notificaciones" C"nuevo_topic"` creates another

## 1.3.0 -- 2026-10-09

- Activity: delete an event (`M9003 P"actividad_consulta" C"borrar" I<id>`) or everything that matches the filter (`C"limpiar"`); the query now returns the `id` of each row
- Pi health (`health_poller.py`, plugin data `saludPi`): voltage/throttling, WiFi, services, Duet, screens grouped by computer, state requests per minute; `salud_*` alerts to the phone
- `job_trace.py`: records the trajectory of the job in progress (5 Hz: position, laser power, speed, air) in `sys/taller-traza.json` for Zones > Job
- Lectura de `/machine/status` compartida entre motor_poller, job_poller y trabajo_traza (menos pedidos al Duet)
- jog_move: records the gaps between browser updates (diagnosis of the sliders' hesitation)

## 1.2.0 -- 2026-10-08

- Base de datos SQLite (`db.py`): presets, consumo e historial de actividad; pollers de trabajo y motores
- A single event flow with configurable ntfy notifications (live jobs, emergencies, pauses, errors, zones); mute for a while
- Consumption/Motors/Activity pages separated into their own plugins (TallerPlugins); here remain the control page and the backend
- Jog with the movement engine in the backend (`jog_move.py`): S0 in Laser mode, clipping to the axes' limit, block only during a job
- Own codes through the Aux2 channel (they no longer share a queue with the G-code bridge: the Timeouts are over)
- `trabajoEnVivo` on start/end/cancel of live jobs; air taken from output 7 in Laser mode
- Motors: speed of each axis by real displacement (the false red is over); it does not query drivers with the supply off
- Job: estimated kWh with the average power if the meter hardly moved
- Camera: stop/start the process; hide the on-screen keyboard
- Nombre visible en ingles: "Workshop - Services"

## 1.1.0 -- 2026-10-07

- Consumption monitor (power, voltage, current, history and reports) with the Tuya meter
- Total software reset button (M999 + Pi restart)

## 1.0.0 -- 2026-10-06

- Code recovered from the Pi (there was no repository)
- No pop-ups on every code; on-screen keyboard that stayed open
- Material presets (M9000) with named properties
