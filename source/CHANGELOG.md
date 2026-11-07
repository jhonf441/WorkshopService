# WorkshopService -- version history

Workshop backend (central API, pollers, database)
and its control page. Before 1.3.0 it was not versioned: versions
1.0-1.2 were reconstructed by grouping the commits by day.

## 2.30.5 -- 2026-11-06

- G-code bridge contract put to work. The Services page and four readers of the service (health poller, origin of the calls, the safe-stop operations, the bridge probe) now read the bridge state through ONE adapter (`dsf/bridge_contract.py`) and the page through the same rules in `dwc36/bridge-contract.js`; both pass the same 65 test vectors (`bridge/contract/vectors.json`), so they cannot drift. With a healthy bridge nothing changes. A stopped bridge no longer shows the programs it had when it died, and a bridge state of a format the service does not know is not acted on (the safe stop says the bridge is too old; the page warns). The bridge card shows which contract version the bridge declares ("old" until the bridge is installed again).
- The bridge as a versioned artifact (`bridge/VERSION`, `bridge/bridge-manifest.json`, `bridge/bridge_manifest.py`) and a safer `install.sh`: it keeps a backup in `/opt/workshop-bridge.prev`, has `rollback` and `status`, and refuses to restart the bridge while a job or orders are active (`--force` overrides). Written and tested on a scratch root; never run on the machine yet.
- NOT moved yet, on purpose: the jog, the laser guard, the motion owner and the restart guard keep their own readers until they are tried with the machine present.

## 2.30.4 -- 2026-11-06

- G-code bridge: written contract between the service and the bridge (`bridge/CONTRACT.md`, JSON schemas in `bridge/contract/`, decision record `bridge/ARCHITECTURE.md`), a read-only adapter in the service (`dsf/bridge_contract.py`, called by nothing yet) and 38 new tests that pin how the bridge behaves today (reply framing with `ok`, query cache, ordering, state and action files). The bridge only gains the key `"contract": 1` in its state file after its next install. Nothing in what the bridge or the service do changes.
- Bridge README brought up to date with the code (version 3.8.0, `order_timeout_s` 120, the old `.api-token` file is no longer read). The address of the workshop PC that was used as an example in `docs/HARDENING.md` and in two tests is now a documentation address (192.0.2.16).

## 2.30.3 -- 2026-11-06

- Sessions survive a restart of the service (the kiosk and every browser no longer ask for the PIN after each install or restart). They are kept in a second private file next to the users file (`<users file>.sessions`, mode 600) and ONLY the SHA-256 of each token is written, never the token. At start a session is kept only if it is still alive (the same 12 h limits), its person still exists and the entry is well formed; a file that is missing, damaged or wrong opens nothing. A closed session (logout, new PIN, role change, person removed, roles switched off) is removed from the file at once, and the role used is always the current one. Writing the file never breaks a login or a request.
- New operation `users.close_sessions` (administrator only, not delegable like every `users.*`) and a button in the Users tab ("Close the other sessions", two touches): it ends every session except the caller's, now that a restart no longer does it.
- The first start after this version has no sessions file, so everybody types the PIN once more.

## 2.30.2 -- 2026-11-06

- Bridge card, port: when the bridge cannot open its port the error is now in the language of the page and appears next to the port field (it used to be the raw English text at the top of the card, far from the input); the header no longer shows a port the bridge is not listening on. While typing, a note warns about ports below 1024 and about ports that something else on a Pi normally uses (22, 80, 443). The bridge itself is not changed.

## 2.30.1 -- 2026-11-06

- Bed zones geometry: no automatic layout any more. The geometry is `{bed: {width, length}}` plus a `rect` per zone, kept exactly as the user left it; a zone without a rect is placed once in a free spot. `mode`, `gap`, `align`, `mirror` and `size` of the earlier shape are ignored when read.

## 2.30.0 -- 2026-11-06

- Bed zones: optional real geometry in the `bed-zones` config (bed size, a rectangle per zone, auto layout for any number of zones, manual placement); validated by the service (`dsf/bed_zones_geometry.py`). A config without geometry behaves as before; the heating (M140 / M190 interception) is unchanged.
- Pellet temperature by layer: profiles of temperatures per heating zone by layer or height (steps or ramp), operations `pelletlayers.list/get/status/set/remove/arm/disarm`, capability `system.pelletlayers`, and a service process `pellet_layers` that, only for an armed job and only while the machine is processing, sends `M568 P<tool> S...` at each layer change. Off by default; never above the heater maximum minus 10 C nor below 30 C; pause holds; cancel or end disarms; every change goes to the activity log and the audit.

## 2.29.4 -- 2026-11-06

- Password tab: changing or removing the DWC password is administrator-only and the tab now says so: the fields and buttons are disabled for other roles, each button carries its lock, and one reason shows at the top of the card (it blinks on a touch).
- Database tab: the card shows ONE reason instead of up to six repeated ones, the gated buttons carry their lock, and a touch on the card blinks the reason.
- Bridge card: the example address in the trusted-IP field is a documentation address (192.0.2.16), no real address of this workshop.

## 2.29.3 -- 2026-11-06

- Processes page, summary: "Restart the service" carries its own lock icon when this role cannot use it, its reason appears only after a touch on it, and the blink rings the words instead of the whole width of the card.
- Shared design family: a reason next to a locked control (`.wf-reason`) fits its text, so the blink of every page of the service no longer draws a box across the whole row.
- Bridge card: type an IP address to trust (it only offered the addresses that had already tried to connect).
- Service page: a session cover (Audit, Users, API) has no sign-in button of its own any more, the chip of the bar is the one sign-in. The mode switch of a process only calls the service when its value really changed.

## 2.29.2 -- 2026-11-06

- Internal processes page: a control this person cannot use now carries its own lock icon (inside each locked button, and once before the mode switch) instead of a loose "sign-in required" line under the group. The reason of a group appears only after a touch on THAT group, and only that reason (and the sign-in chip) blinks; the blink rings the words, not the whole width of the card.
- The last error of a process is shown in gray with "recovered" when a heartbeat arrived after it; red stays for a process that is failing now.

## 2.29.1 -- 2026-11-06

- Internal processes page, redone in three phases. Phase 1 (visibility): five groups (safety, machine, data, support, separate services) with a safety tile, filters and search; every row answers what it does, what it depends on, what stops if it fails and who reads it. Nine threads that were invisible now report heartbeats (guardian_laser, intercept_watchdog, watchdog_lock, publisher, communication, commands_extra, base_backup, api, api_macros) and the protection guard also watches the laser guardian and the interception watchdog. `dsf/process_catalog.py` classifies every process.
- Phase 2 (honest control): the auto/on/off switch says when it applies (only `bed_zones` re-reads the mode each pass; every other change applies when the service restarts) and shows a pending-restart note and banner. `modules.set` refuses the nine locked processes. New capability `processes.control` ("Procesos: parar y arrancar"); the four base roles decide as before.
- Phase 3 (real control): `processes.pause`, `processes.resume` and `processes.restart` for consumption, motors, maintenance, pid_trace and trace (cooperative, in memory, they do not survive a restart), and `service.restart` (administrator, confirmation level 3, only when the machine is idle: status off or idle, no job, no laser, no owned movement, no protection down). `service.restart` is its own capability, not part of `processes.control`. The page answers at once (spinner, state shown before the next publication, confirmation line), a paused process is unmistakable, and a touch on a locked control makes its reason blink.
- Fixed while trying it on the Pi: threads nobody launches through the supervisor showed as stopped on the page; a tick now marks them live.
- NOT tried on a real machine: that DSF revives the service after `service.restart` (exit code 1, same path as the interception watchdog) and the five pausable loops against a live job.

## 2.29.0 -- 2026-11-06

- Service page: the session follows a sign-in made in another tab (the page reconciles its token when it comes back to the front); the package card redraws with the role; the family.css copies carry the shared pieces of the side bar (icon box with a lock mark, text column).

## 2.28.4 -- 2026-11-07

- "No users" no longer means "the whole network may change things" (Duet3D catalogue review, hardening): on the camera relay (port 8090) a request from
  the network can only read until the first administrator exists (`403 first_admin_required` for the camera settings, the look files and any route not
  classified); the Pi itself is not limited; a machine whose owner switched the roles off with the administrator's PIN keeps the old open behaviour
  (`UserStore.network_open()`, also sent by `auth.resolve` and `auth.whoami` as `network_open`). Vision applies the same rule (WorkshopVision 2.7.28).
- G-code bridge: orders from the network are refused unless the Pi itself sends them, or the address is trusted, or the client typed the password, or the owner
  wrote an `allowed` list; with none set only queries are answered. `install.sh` asks for a password / allowed list / trusted address (`BRIDGE_PASSWORD`,
  `BRIDGE_ALLOW`, `BRIDGE_TRUST`, or `install.sh guard`). A bridge that had none refuses the PC's orders until one is set.
- The start-up row of the users says what a machine without users does and does not allow. Docs: README, HARDENING, api README.

## 2.28.3 -- 2026-11-06

- Nothing leaves the machine by default (Duet3D catalogue review, issue #2053): phone notifications (ntfy) are OFF until the owner turns them on; `init()` no longer creates a topic or contacts any server, the topic is created when they are turned on, and installs that already saved the setting keep it. Turning them on through the API needs `acknowledge_outbound: true` (the Activity page asks for a confirmation first); the test sends and `notifications.send` are refused while they are off.
- Pi health: the latency check to the notices server runs only while the notifications are on and uses the configured server; the ping to `1.1.1.1` runs only with `health.internet_check` true (off by default); a missing value hides its row.
- Docs: README notice at the top, outbound traffic described in "Permissions and what it changes", `security.md`, `HARDENING.md`.

## 2.28.2 -- 2026-11-06

- Roles card: the capability pills no longer redeclare the font size of the family pill (family-design rule).

## 2.28.1 -- 2026-11-06

- Service page: Database, Bridge and the black box hide button are disabled before the click when the role cannot use them, with one reason; Users and Audit decide admin with the operation table (`users.list`, `audit.list`) like the rest of the page; the start-up master tells a role refusal apart from a missing session.

## 2.28.0 -- 2026-11-06

- Own roles with capabilities: 55 capabilities, own roles (base role plus grants and denials, stored in `workshop-roles.json`), operations `roles.list/get/set/remove/effective`, `auth.whoami` with `role_name`, `allow` and `deny`; the four base roles decide exactly as before (golden fixture). See `docs/ROLES.md`.
- Roles and permissions card on the service page (matrix, own roles, what a person can do); own roles in the role selector of each user.
- API keys accept `cap:<id>` entries in `ops` and `deny`, `keys.preview`, and `allowed_ops` resolved by the service. Keys saved before this version decide exactly as before; new or re-saved keys never reach non-delegable operations.
- `plugin.json` lists `machine_bed_edit.py` and `real_mode.py` in `dsfFiles`.

## 2.27.0 -- 2026-11-06

- The macros of `sys/workshop/macros` are grouped in folders (axis, zcal, focus, work, guard, laser, probe, system): every call, the whitelist of G-code, the zcal hook and the macros the service writes (lights.g, lasercorrection.g, zcal.g, enable/disable_pi_status.g) use the new paths. Install it together with the plugins and run `tools/migrate_macro_folders.py` of TallerPlugins on the SD.
- power.off is open to every role and to nobody signed in; the last time a person was seen is kept after the session ends.

## 2.26.0 -- 2026-11-06

- Bed heaters and tool pins: new `temp` capability for the dedicated temperature inputs (temp0..temp3); thermistor and pt1000 sensors ask for it, so the io pins are no longer offered. New bed sensor types: thermocouple (MAX31855) and pt100 (MAX31865, new preset), thermistor with optional `t` and `b`.
- Keys page: the new-key button is locked with its reason when the role is not administrator.

## 2.25.0 -- 2026-11-06

- Plan kind `config.bed_edit` (`dsf/machine_bed_edit.py`): change the heater and / or the sensor number of a bed the configuration already defines, with the plan of Machine (diff of each file, snapshot, rollback). `machine.beds.get` adds `sensor` and `editable` to each defined bed.

## 2.24.3 -- 2026-11-06

- Beds: the limit of beds and heaters is the board's own (`limits.bedHeaters`, `limits.heaters` of the object model) instead of a fixed 8; without board limits the cap is the RRF ceiling (32 beds, 20 heaters). Bed zones layout cap is `LAYOUT_MAX * LAYOUT_MAX`.

## 2.24.2 -- 2026-11-05

- G-code bridge: `BRIDGE JOB START` and the material macros wait for the machine gate (mode / armed / homed); the black box records the service threads; the bridge card text and the shared family.css follow the QA batch of the other session. The bridge itself needs `bridge/install.sh` on the Pi to take effect (a plugin install does not touch it).

## 2.24.1 -- 2026-11-05

- Bed zones: an `M140` / `M190` that names its heaters with `H` goes through untouched, like one with a `P`. A slicer profile that sends one `M140 S.. H<n>` per zone (14 zones in the factory PrusaSlicer-style profiles of the owner's slicer) would otherwise have been spread across ALL the zones by every line, the last one winning. Only an `M140` / `M190` with no `P` and no `H` (the usual `M140 S60`, also the one of layer 2) is split across the zones.

## 2.24.0 -- 2026-11-05

- Plan kind `config.bed_heaters` and operations `machine.beds.get` / `machine.beds.preview` (`dsf/machine_beds.py`): the ONE way the configuration gets the bed heaters of a split bed (sensor, heater, `M143`, `M140 P H`), with the plan of Machine (exact diff, snapshot, history, rollback). The pins are chosen by the person among the free ones of the board, never guessed. It goes into the last file that really defines heaters, after its last top-level heater line (a mode file that only deletes heaters with `C"nil"` is not a definition).
- The scan of the configuration reads up to 16 files (was 8): on the real machine `config.g` calls six macros and `automodeselect.g` three mode files, so `modefff.g` was the ninth and every plan (tool, steps per mm...) saw `modecnc.g` instead.
- `machine_beds.py` joins `machine_tool.py` in the exception of the safety test that keeps `M950` text out of the Machine modules: it only builds lines for a reviewed plan and never sends.

## 2.23.0 -- 2026-11-05

- Bed zones: a bed split in several heaters, each one a bed of its own in RRF. While the setting is on, M140 / M190 with no P are answered by the service and become one `M140 P<bed> S<setpoint + offset>` per active zone; with a P they go through untouched; 0 or -273.15 turns every zone off. M190 holds the code until every zone is within the tolerance (error on a heater fault or on the timeout). Its own interception connection (Pre, only M140 / M190) with its own watchdog; the firmware keeps the PID, the M143 limits and the fault detection, the service only sends setpoints.
- API: `bedzones.get` (viewer), `bedzones.setpoint` (operator), `bedzones.set` (technician, with a revision) and `bedzones.off` (a stop, never blocked). Settings area `bed-zones` with strict validation; a file that is not valid turns the feature off. New process `bed_zones` (rests when Printing is stopped).
- `config/bedzones.g`: a copy of the settings the service writes for the board (every change and at start, never edited by hand) so the backup macro of Printing can read them with the service stopped.
- New files: `bed_zones.py`, `bed_zones_config.py`, `bed_zones_intercept.py`, `bed_zones_ops.py`, `bed_zones_mirror.py`; the texts in `i18n`. Manual test guide: `docs/BED-ZONES-MANUAL-TEST.md`.

## 2.22.18 -- 2026-11-05

- The mode of the machine is what the board applies (state.machineMode), not global.selectedMode: the select*.g macros write that variable before M452 and it stayed wrong when M452 failed, so the LEDs, job traces, activity, heights and work area could say Laser while the machine was in FFF. One module (real_mode.py) now decides it for the 12 places that read it.

## 2.22.17 -- 2026-11-04

- Sign out no longer reopens the PIN dialog at once: after signing out the touch is forgotten and nothing opens the dialog by itself for 20 s (the shared client of the pages, copied from TallerPlugins 1294722b).

## 2.22.16 -- 2026-11-04

- Camera relay: its card of the control bar is shown from the start (it was off until a screen turned it on in the gear); it can still be turned off there.
- Audit and Received commands: the date fields are the shared time-range picker (quick ranges, last N units, absolute range) like the rest of the pages, not the browser date input.
- build_release.py builds and checks only the 3.6 zip (DWC 3.7 is paused; --paused-37 brings it back).

## 2.22.15 -- 2026-11-04

- Camera relay card: a token the service no longer accepts (it forgets them on restart) counts as no session, like the header of the pages (it said "the service did not answer"); it reads the camera again as soon as the person signs in.

## 2.22.14 -- 2026-11-04

- Camera relay card: it hung from the process id 'camera_relay' (the module) but the service reports the process as 'camera', so the Stop / Start card never appeared in the row. Fixed, with a test that the id has process docs.

## 2.22.13 -- 2026-11-04

- Camera relay card: without a session it says so (a state, not a failure), offers neither button and does not read the camera, so it no longer sits on "Reading the state..." nor asks for the PIN every 15 s.

## 2.22.12 -- 2026-11-04

- Machine setup list: Camera now points at its page (Timelapses) instead of saying it lives in the side bar.

## 2.22.11 -- 2026-11-04

- The camera relay is controlled from the service: its row in the processes list has the state and Stop relay (two taps) / Start relay for technician and admin, and the control bar can show the same card as an optional tile (off until a screen turns it on in the gear of the bar). Before, Camera offered the card and it vanished with that plugin. New texts `api.relay_*` (es / en, both lines), `camera-relay.js` + `RelayCard.vue` in `dwc-src/` and `dwc36/`.
- Keys page: without a session nothing of the keys is shown or offered, only the standard sign-in notice; reads again when the person signs in.

## 2.22.10 -- 2026-11-03

- One wording for every refusal: the messages of the service for a missing session or role now start with "Sin permiso:" / "Not authorized:" (`api.signInNeeded`, `api.forbidden_*`) and say what is needed ("hace falta tecnico"). New texts `api.permissionTitle` and `api.close` for the notice card (TallerPlugins `src/_shared/09-session-notice.js`), which shows every refusal the same way on every page.
- CLAUDE.md: the sudoers rule documented is the real one (`shutdown` and `reboot`).

## 2.22.9 -- 2026-11-03

- Live job text and docs: the G-code that marks a live job through the bridge is `M118 P0 S"BRIDGE JOB START <name>"` / `M118 P0 S"BRIDGE JOB END"` / `M118 P0 S"BRIDGE JOB CANCEL"` (valid for DWC and the Duet; the bridge recognises the message and does not send that M118 to the board). The bare form stays only as a bridge shortcut. Fixed in the page text (`liveJobDesc`) and in docs/api/README.md, docs/api/DESIGN.md and docs/PROCESSES.md.
- API keys dialogs (new key / edit key): fields and long option texts fit inside the modal (branch apikeys-modal-fit).

## 2.22.8 -- 2026-11-03

- The standard message when a call needs a session (`signInNeeded`) is now "Necesitas iniciar sesion (usa el boton de abajo)." / "You need to sign in (use the button below).": it reads well inside any sentence the pages build ("No se pudo leer el historial: ...") and points to the sign-in chip. The chip itself (src/_shared/09-session-notice.js of TallerPlugins) now shows what was refused and blinks, instead of a second notice on top of it.

## 2.22.7 -- 2026-11-03

- Tool creation wizard (Machine page, DWC 3.6): new read operations `machine.tool.get` (operator), `machine.tool.pins` and `machine.tool.preview` (technician) and the plan kind `config.tool` (`machine.config.plan` / `machine.config.apply`, technician). It writes M308, M950 (heaters, fans, spindle), M143, M563 and G10 into the configuration after the last tool line, with a backup, and the machine restarts to read them. A pin is accepted only if the Duet 3 6HC has it, it can do what the use needs and no live line of the configuration uses it. Nothing is sent to the board. Tests: `test_machine_tool.py`. Not tested on the real machine.

## 2.22.6 -- 2026-11-03

- Calibration (Machine page): new operation `machine.test_move` (technician, level 3 confirmation): the test move of the steps-per-mm assistant can be sent from the page. It renders one template of the closed list (`rel_move`: `G1 X100 F600 S0`, always S0) between `G91` and `G90`, asks the movement owner for the bed and puts the machine back in absolute mode whatever happens. Refused when the machine is not idle, the axis is missing or not homed, the move would leave the travel, or the distance (0.1 to 200 mm) or the feed (1 to 6000) is out of range. Tests in `dsf/test_machine_testmove.py`.

## 2.22.5 -- 2026-11-03

- Power loss (Machine page): the page can resume the job left by a power cut. `machine.power.get` now carries `resume` (checks: resurrect.g complete, job file on the card, machine idle, mode known, supply above the restore voltage, prologue present; `can_resume`, `needs_ack`) and the new operation `machine.power.resume` (technician) sends `M916` (template `resume_print` of the closed list, through `machine_ops.apply_template`) only when every blocking check passes and, in laser / CNC, the three acknowledgements (`piece`, `tool`, `area`) are true; it checks again on its own and records the resume in the audit. Tests in `dsf/test_machine_power.py`.

## 2.22.4 -- 2026-11-03

- Power loss (Machine page): `machine.power.get` now also returns the content of `resurrect.g` and `resurrect-prologue.g` (cut at 8000 characters), what a `resurrect.g` says (job, file position, saved axes) and what a prologue does (modes it speaks of, whether it asks before resuming, switches the tool off, cancels); `is_standard` tells whether the prologue is the workshop one. New plan kind `config.prologue` (administrator): creates `resurrect-prologue.g` with the standard text when the machine has none; it never replaces an existing file (`prologue_exists`). Tests in `dsf/test_machine_power.py`.

## 2.22.3 -- 2026-11-02

- Power loss (Machine page): new operation `machine.power.get` (the M911 line of the configuration, whether `resurrect.g` and `resurrect-prologue.g` exist, the supply voltage) and the plan kind `config.m911` (administrator): changes only S and R of an existing M911 line (S 10-28 V, R 10-30 V, R above S); the P commands are never written and a missing line is not invented.

## 2.22.2 -- 2026-11-02

- The leading icon of the status chips of the bar is no longer clipped (the check of "System service"); thin scrollbar colour of the side tabs (`family.css` of the design family).

## 2.22.1 -- 2026-10-31

- The camera relay no longer counts a screen that has left. A stream whose camera was reconnecting (no frame to send) wrote nothing, so it never saw the screen close and showed "1 watching" for hours with every page closed (and kept the camera awake for it); it now looks at the socket on each idle wake-up (`camera_http.peer_closed`, test `test_camera_peer_closed`).

## 2.22.0 -- 2026-10-31 (informe 06, plan B, round 2: the camera moves into the service)

- One list of cameras (B-P4). `cameras.json` is THE list and the service owns it: the relay reads it through the settings store (`camera_sources.camera_list`), `main` is one more record with its own address, and `service.json` `camera_relay` keeps only `{active, bind}` (`url` is gone; `active` defaults to true). The service decides which cameras go through the relay and says it with each camera (`via_relay`): the main camera and the ESP32-CAMs that have an address of their own and are not set to the direct way. `camera.status` carries the whole list (`cameras`, `cameras_rev`: the revision a page writes the list back with) instead of `{id, name}` of the served ones, and no longer has `url` or `other`. The relay starts by itself as soon as the main camera has an address, and stops when it loses it.
- `camera.url` is gone (the address of the main camera is a record of the list: `settings.set` on `cameras`) and so is the route `GET /detect` of `:8090`. New operation `camera.detect {url}` (technician): whether an address is an ESP32-camera and has a flash.
- The flash is the service's (B-P5). New operation `camera.flash {camera, on}` (operator, the role of `light.set`): the LED of an ESP32-camera through its own `/control`, or the work lights through `light.set` when the camera's `flash_source` is `strip` (new module `camera_control.py`, in `dsfFiles`). The service remembers it per camera and publishes it with each camera (`camera.status` and `/state`: `flash: {capable, on}`, no longer a boolean), and its loop switches it off when nobody has asked that camera for a photo or its video for 30 s, or after 10 minutes, or when no plugin can look at a camera any more. `cameras.json` records no longer carry `flash` (`flash_source` stays). `/control?var=led_intensity` of `:8090` stays open to the operator.
- The image settings of the ESP32-cameras are the service's (B-P6). New operations `camera.image.get {camera}` and `camera.image.set {camera, profile?, settings?, auto?}` (technician), in the new module `camera_image.py` (in `dsfFiles`): the profiles with their values, the numbers of the resolutions of the camera's firmware (`resolutions`; the page keeps no table), what the camera says now (`live`) and what is saved. `camera.json` is written by the service only and has a new format: `{"version": 2, "cameras": {"<id>": {"profile", "auto", "settings"}}}` per camera (the old single record is ignored: choose the profile again or copy it by hand). The loop of the relay applies it again by itself when the camera reconnects or is found different from what is saved (a restarted ESP32 is at its factory values), and with "auto" switches to the profile that fits the machine (laser job running: `cut`, else `balanced`); it used to be a timer and a re-apply of the Camera viewer, which only worked with a screen looking. Only the variables of `camera_image.RANGES` and the resolutions by name reach `/control` from here. NOT done: Vision still keeps `photo.video_fs` and its `watch_video` (it raises a camera found at 320x240 to that resolution); with the service re-applying first it only acts on a camera that has nothing saved. Removing it is a change in the Vision plugin (see the Vision CHANGELOG of the round).
- The photo in a notice is the notifier's policy (B-P7). `camera_service` loses `photo_notice` and `notice_camera` (the relay keeps no policy of the notices; keys of an older version are not carried) and the relay offers two narrow functions, `camera_relay.snapshot(camera)` and `camera_relay.clip(seconds, camera)`, that only take the picture. Whether a notice carries a photo or a video is the `attachment` of its type (`notifications.option`), and the camera every type uses unless it chooses its own is the new `default_camera` of the notifier (`notifications.option` without `type`, `default_camera`: an id or `auto` for the main camera; shown in `notifications.get` -> `config.default_camera`). The fire notice is still sent WITHOUT a photo (its default attachment is `none`): putting the picture of a camera in it is a decision of the owner, left as it was.
- The writes of the relay are operations of the API (B-P8, step 1): `camera.burst`, `camera.remove`, `camera.keep`, `camera.rename`, `camera.edit`, `camera.rerender` and `camera.schedule {action: schedule|unschedule}` are new, and `camera.timelapse {action: start}` takes the `cfg` of the take; with `camera.capture` they do what the POST routes of `:8090` did (the same code: `camera_captures.remove` is used by both), but they are in the history and the audit with who did it, and each has the level of the route it replaces (capture, burst, rename, timelapse: operator; remove, keep, edit, rerender, schedule: technician; `test_camera_api_writes.py` compares them with `camera_access.ROUTES`). The POST routes are still on `:8090` in this step (the Camera plugin that uses the operations replaces its calls; step 2 deletes the routes). The upload of a LUT stays a POST of `:8090` (6 MB do not fit the 1 MB body of the API), with its technician role, and so does `/luts/remove`.
- Install day: write the address of the main camera into `0:/sys/workshop/config/cameras.json` (the `main` record, `url`) from what `service.json` `camera_relay.url` had, and the key `url` of `camera_relay` can be deleted. No migration is made.

## 2.21.42 -- 2026-10-31

- Service page: the line that says where the camera relay is managed shows only when the Camera plugin is active, and points to the Cameras tab of the Camera plugin page without naming other plugins.

## 2.21.41 -- 2026-10-31

- Bridge card: with the bridge stopped from its own switch, the header no longer shows what the state file held from before it stopped (security chip, version, uptime) or a restart button that could only fail; the state chip says Stopped.

- Camera relay: the old Spanish route and query names (`/estado`, `/capturar`, `?archivo=`, `?accion=empezar`...) are gone with `camera_proto.upgrade`; the relay only knows the English contract (`proto` stays 2). The camera `_id` alias, the `editado_de` key of edited videos and the `creado` key of `schedule.json` (nobody read them) are gone; the texts that were written by hand in Spanish (`no existe ese video`, the main camera name `Principal`, the `capa` stamp of the layer photo) are message keys now.
- Notifications: no more aliases for the attachment and quiet-hours mode values (`nothing`, `clip`, `callar`, `silencio`...); the API values (`none`, `photo`, `video`, `mute`, `soft`) reach the handler as they are. `capabilities` only reads `camera_relay` (not the Spanish `camara_relay`).
- The local key is read only from `/opt/dsf/conf/workshop-api-token`: the service no longer moves a key found on the SD (`migrate_token`) and the G-code bridge no longer reads `0:/sys/workshop/data/.api-token` (`docs/HARDENING.md`).
- Ports: `dsf/ports.py` holds the two ports of the workshop (camera relay 8090, Vision 8095) and `test_ports.py` fails when another module writes the number. The `port` option of `camera_relay` is gone: the relay always listens on `ports.CAMERA_RELAY` (a `port` left in `service.json` is ignored; `camera.status` still reports it).
- Camera relay: the day key of a request is read by `camera_access.day_token` only (the relay had its own copy of the same parsing). New tests tie the code that is copied by hand between repos: `test_sibling_copies.py` (messages.py equal in the service, Vision and RS485; `base_of` of the relay equals Vision's) and `test_camera_geometry_cases.py` with `dsf/fixtures/camera_geometry_cases.json`, the cases the Python geometry of Vision and the JavaScript of the map layer must both answer the same (the JavaScript reader is `tests/camera-map.test.js` of TallerPlugins).
- Camera relay: `camera_relay.py` (2444 lines) is split in layers, WITHOUT changing what it does: `camera_context`, `camera_config`, `camera_sources`, `camera_limits`, `camera_assembly`, `camera_captures`, `camera_timelapse`, `camera_notice`, `camera_key` and `camera_http`; `camera_relay.py` keeps `configure` / `request` / `status` / `run_loop` and the public functions the API handler, the notifier and `main.py` call. The state every module reads has one owner (`camera_context.cfg`, `camera_config.service`, `camera_sources.sources`). `test_camera_modules.py` keeps it that way (layers, 800 lines per module, 100 per function) and `test_module_sizes.py` no longer freezes the relay. The new modules are in `plugin.json` `dsfFiles` and the published keys still come from them (`published_texts.py`). Internal names in Spanish became English (`echar` -> `cut`, `tomando` -> `taking`). The installed manifest must receive the new `dsfFiles` (`instalar-servicio.sh`, one line) or a later uninstall leaves the new files behind.
- New operations `plugins.stopped.get` (viewer) and `plugins.stopped.set {id, stopped}` (operator): the plugins a person stopped on purpose are kept in `0:/sys/workshop/data/stopped-plugins.json` (`{"v": 1, "stopped": [...]}`, ids that start with `Workshop`), and `kiosk/ensure-emergencyfab.sh` no longer puts them back into `machine.enabledPlugins` (without the file it behaves as before). The script has to be copied to the Pi again (`~/ensure-emergencyfab.sh`).

## 2.21.40 -- 2026-10-31

- Camera relay: the operator may turn the flash on and off. `/control` was technician-only for every setting, so with users enabled an operator tapped the flash button and nothing happened; now the operator may send only `led_intensity`, any other setting of the camera stays technician.
- Service page on DWC 3.6: a plugin counts as active only by the machine list of the enabled plugins (the plugins page never clears the global list), so the plugin columns, chips and links of this page follow Stop and Start.

## 2.21.39 -- 2026-10-31

- Interrupted live jobs: the board boot mark sent to the bridge is a whole number of seconds. dsf-python writes floats with 6 significant digits, so an epoch like 1793456272.3 reached the bridge as 1793460000 and every record looked "rebooted" (the page said the board restarted and the origins were lost) when nothing had restarted.

## 2.21.38 -- 2026-10-31

- The list of enabled plugins comes from `machine.enabledPlugins` of `dwc-settings.json`; the interface list `main` is only the fallback when the machine list is missing. DWC empties the machine list when a plugin is stopped but leaves it in `main`, so a stopped Vision still counted as enabled and the protection guard raised "fire and smoke watch (Vision) is down" with Vision stopped on purpose.

## 2.21.37 -- 2026-10-31

- Merged work: laser correction mirror, focus.g mirror, camera permissions, review fixes, one way to write the machine configuration.

## 2.21.36 -- 2026-10-30

- Machine: the work offsets G54..G59.3 are the work zones of the Workbench (`0:/sys/workshop/zones/p<N>.g`), one source of truth: the plan kind `config.workplaces` is gone (`0:/sys/workshop-offsets.g` is no longer written, config.g is not touched for it) and `machine.history.restore` refuses an `offsets.snapshot` with reason `work_offsets_in_workbench` (a snapshot is for comparing). `machine.offsets.get` and `machine.offsets.snapshot` stay; `config.g10` (tool offsets) stays.
- Camera relay: optional `bind` in `camera_relay` (default all interfaces, `"127.0.0.1"` keeps it on the Pi). Vision: `WORKSHOP_VISION_BIND`.
- `bridge/install.sh uninstall` removes the unit, the polkit rule and `/opt/workshop-bridge`.
- `security.md`: every permission is explained, plus a table of changes made outside DSF and how to undo them, and the open-access warning while no user exists.

## 2.21.35 -- 2026-10-30

- `health.history` takes `since` and `until` (epoch seconds) for any stretch of the Pi health history, not only `1h`, `6h`, `24h`, `7d`; the answer also carries `until`.
- API and keys: the request, the curl and the macro line of an operation have a copy button.
- `bridge/install.sh` never leaves an empty unit file (a missing template had left it at 0 bytes and systemd reported the bridge as masked).

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
