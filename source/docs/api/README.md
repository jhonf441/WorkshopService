# WorkshopService API

WorkshopService (and WorkshopRS485) expose their functions as named operations over an HTTP
endpoint served by the Duet web server (DWS) of DSF.

| Endpoint | Use |
|---|---|
| `POST http://<machine>/machine/WorkshopService/api` | call an operation |
| `GET  http://<machine>/machine/WorkshopService/api` | list every operation with its arguments |
| `POST/GET http://<machine>/machine/WorkshopRS485/api` | the same for the RS485 devices (`rs485.*`) |

## Calling an operation

```
POST /machine/WorkshopService/api
Content-Type: application/json
X-Session-Key: <session key, only when DWC has a password>

{"op": "lights.zone", "args": {"index": 2, "on": true}, "confirm": false, "origin": "my-script"}
```

- `op`: name of the operation (`group.action`).
- `args`: named arguments. Unknown arguments, missing required ones or wrong types are refused
  (`invalid_args`, with `error.field`).
- `confirm`: set it to `true` only after a person accepted the risk of that operation
  (see Confirmations).
- `origin`: who calls (free text, kept in the history of the service).

Answer:

```
200 {"ok": true, "op": "lights.zone", "result": {...} | null, "message": "<text>" | null}
4xx/5xx {"ok": false, "op": "...", "error": {"code": "...", "message": "...", ...}}
```

| HTTP | `error.code` | Meaning |
|---|---|---|
| 400 | `bad_request` | the body is not JSON or `op` is missing |
| 401 | `auth_required` | DWC has a password: log in first |
| 401 | `login_required` | the service has people and the call came without a valid token: `auth.login` (see People, PIN and roles) |
| 403 | `forbidden` | this way of calling cannot use that operation |
| 404 | `unknown_op` | no such operation |
| 428 | `confirm_required` | repeat with `"confirm": true` after asking the person (`error.confirm` has the level and the texts in Spanish and English) |
| 409 | `conflict` | `settings.set` was based on an old revision; `error.current` has the current `{value, rev}` |
| 423 | `interlock_open` | a declared laser interlock is not ok (`error.interlock`) |
| 423 | `motion_denied` | the owner of the movement does not allow it now (`error.motion.reason`) |
| 424 | `failed` | the operation ran and failed (`error.message`) |
| 422 | `invalid_args` | wrong arguments |
| 500 | `internal` | unexpected error (details in the log of the service) |
| 503 | `busy` | another long operation is running; try again |

A 502/503 without a JSON body comes from DWS itself: the service is stopped or restarting.

**Contract: branch on `error.code` first, the HTTP status second.** Since 2026-10-26 each answer that clients treat differently has its own status (428 `confirm_required`, 423 `motion_denied` and `interlock_open`, 409 `conflict`, 424 `failed`); before, all of them were 409. `error.code` did not change, so a client that reads it works with both an old and a new service (the pages and the system programs do; none tested `status === 409`).

## Authentication

- DWC without a password (factory `reprap`): no session is needed (the same as `/machine/code`).
- DWC with a password (M551): open a session like DWC does and send its key:

```
curl -s "http://duet3.local/machine/connect?password=MYPASSWORD"
# -> {"sessionKey": 12345678, ...}
curl -s -X POST http://duet3.local/machine/WorkshopService/api \
     -H "X-Session-Key: 12345678" -H "Content-Type: application/json" \
     -d '{"op": "job.get"}'
curl -s http://duet3.local/machine/disconnect -H "X-Session-Key: 12345678"
```

- Programs running on the same computer as DSF (the G-code bridge, the Vision service) may
  send the header `X-Workshop-Token` with the content of `/opt/dsf/conf/workshop-api-token` (older installs: `0:/sys/workshop/data/.api-token`)
  instead of a session (not for the `admin` operations: password and channels).

- An external service (an app, a phone, another computer) should have its own **key** instead of the
  DWC password: create it in the page of the service (Access keys), choose what it may call (operation
  classes read / write / motion / stop / power, plus operation patterns such as `light.*`, minus refused
  patterns), an optional expiry, and switch it off or delete it whenever you want. The key looks like
  `wk_` + 48 hex characters, is shown once (only its SHA-256 is stored in
  `0:/sys/workshop/data/api-keys.json`) and goes in the header `X-Workshop-Key`:

```
curl -s -X POST http://duet3.local/machine/WorkshopService/api      -H "X-Workshop-Key: wk_..." -H "Content-Type: application/json" -d '{"op": "light.set", "args": {"on": true}}'
```

  A key never reaches the `admin` operations (keys, password, restoring configurations); a key that is
  sent but is invalid, expired, disabled or revoked answers 401 and never falls back to the open mode;
  an operation outside its permissions answers 403 `forbidden` with the reason. The calls made with a
  key are in the history of received commands with the name of the key. Managing keys:
  `keys.list`, `keys.create`, `keys.update`, `keys.revoke` (a DWC session only).

## People, PIN and roles (identity)

The service has its own people: a name and a PIN (4 to 12 digits, kept only as a salted hash in
`/opt/dsf/conf/workshop-users.json`, mode 600, outside the SD that DWC serves). Created in the page of the service
(Users). **Until the first person is created nobody is asked for anything: everybody who reaches the
API through DWC is an administrator** (the page shows a warning). From the first administrator on, a call that comes
with a DWC session or in the open mode needs a person:

```
curl -s -X POST .../machine/WorkshopService/api -H "Content-Type: application/json"      -d '{"op": "auth.login", "args": {"name": "Ana", "pin": "2468"}}'
# -> {"ok": true, "result": {"token": "...", "user": {"name": "Ana", "role": "operator", ...}}}
curl -s -X POST .../machine/WorkshopService/api -H "X-Workshop-Token: <token>" -H "X-Workshop-Device: <id of the browser>" ...
```

- The token goes in the header `X-Workshop-Token` (the same header carries the local key of the system programs: the
  local key is compared first). `X-Workshop-Device` is a random id of the browser for the audit. The address of the
  request (`X-Forwarded-For`) is only written in the audit, it is never used to decide anything.
- Sessions live in the memory of the service (a restart logs everybody out), expire after `idle_minutes` without
  activity (`auth.keepalive` or any change) and after `max_hours` in any case. 5 wrong PINs lock the person for a minute
  (twice as long each time, up to 15 minutes); a client and the whole service have their own limits.
- Without a valid token: `401 login_required` (the pages open a PIN dialog and repeat the call). With a token but not
  enough role: `403 forbidden` with `error.reason` (`role`, `mode`, `mode_unknown`, `camera`), `error.role` and
  `error.needed_role`. A `confirm: true` never replaces the role. Stopping (`jog.stop_*`, `frame.stop`, `pid.cancel`)
  is never blocked.
- Roles, from the lowest: `viewer` (reads the state; the camera only with `camera_for_viewer`), `operator` (moves,
  runs jobs in the modes it is allowed, work lights, camera, captures; by default only `laser`), `technician` (calibrates,
  edits settings of the plugins, Motors, RS485, offsets), `admin` (people, keys, shutdown / restart, M950, deleting
  history, passwords). The table is `dsf/permissions.py` (`OP_ROLES`); `auth.whoami` sends it to the pages. An operation
  that is not in the table needs `admin`, and a test fails if the registry has one that is not classified.
- Operations: `auth.login`, `auth.logout`, `auth.whoami`, `auth.keepalive`, `auth.change_pin`; for administrators
  `users.list`, `users.add`, `users.set`, `users.remove`, `users.reset_pin`, `users.settings`, `users.enable`, `audit.list`.
  Nobody lowers their own role or removes themselves, and the last administrator stays.
  `auth.resolve` is for the local programs that receive the browser's calls directly (the Vision server on port 8095): with the local key
  it answers the role of a session token the browser sent them; a DWC session needs `admin` for it.
  The answer is `{configured, compat, role, user}`; `user` is `{name, role, modes, camera}` (or `null` for nobody) and `camera` is the
  effective flag: the user's `camera_for_viewer` or the global setting. The Vision server uses it for the GET of a viewer (a viewer
  without `camera`, or an answer that lacks it, sees no camera data); operator and above never need it.
- The **audit** (`audit.list`, read only) records user, role, device, address, operation, arguments without PINs or
  secrets, result and time of every change, every refusal and every login. The API has no way to delete it; the
  maintenance purges rows older than 90 days.
- External keys (`X-Workshop-Key`), local programs and macros keep their own model and do not go through the roles.

### Camera relay (port 8090)

The pages talk to the relay directly, so it applies the roles itself (`dsf/camera_access.py`, in process: it asks the user
store, no HTTP). The browser sends `X-Workshop-Token` / `X-Workshop-Device` (the relay answers them in the CORS preflight).
Without users nothing changes. A request from the Pi itself (loopback, no `Origin`, no token: macros, Vision, the service)
passes. Users exist and the store cannot answer: `503 service_unreachable`. No session: `401 login_required`; not enough
role (or a viewer without `camera_for_viewer`): `403 forbidden`. Body: `{"ok": false, "code": "...", "error": "..."}`.
A route that is not in the table needs `admin`; a test fails if the relay has a route that is not classified.

| Role | Routes |
|------|--------|
| viewer with the camera (`camera_for_viewer`) | `GET /state`, `/stream`, `/snapshot`, `/c/<id>[/snapshot]`, `/status`, `/captures`, `/captures/<file>`, `/timelapses`, `/timelapses/<file>`, `/timelapse/last`, `/per_delete` |
| operator | `POST /capture`, `POST /rename`, `POST /timelapse?action=begin` and `action=stop` |
| technician | `POST /remove`, `/keep`, `/edit`, `POST /timelapse?action=schedule` and `unschedule`, `GET /control` (camera settings), `GET /detect` (camera search) |
| admin | anything not listed |

A viewer without the camera gets nothing from the relay (not even `/state`). `<img>`, `<video>` and downloads cannot carry
headers: a GET of a read route WITHOUT `X-Workshop-Token` is also accepted with the day key the relay already had (`?t=` or
the cookie `workshop_camera`, obtained with `camera.token`, which needs operator or a viewer with the camera). A request that
sends the session token is decided by that session alone. The day key lives two days and opens read routes only.

## Examples

```
# list the operations
curl -s http://duet3.local/machine/WorkshopService/api

# a live job from an external program 
curl -s -X POST .../api -d '{"op": "job.start", "args": {"name": "sign 40x20"}, "origin": "external:cutter"}'
curl -s -X POST .../api -d '{"op": "job.end", "origin": "external:cutter"}'

# may I move the machine now?
curl -s -X POST .../api -d '{"op": "motion.ask", "args": {"origin": "external:cam", "action": "move"}}'
# -> {"ok": true, "result": {"decision": "allow" | "confirm" | "deny", "code": "...", "reason": "..."}}  (reason in the language asked with "lang")

# keep the machine for a sequence (others are denied until it ends)
curl -s -X POST .../api -d '{"op": "motion.reserve", "args": {"origin": "external:cam", "text": "photos", "seconds": 120}}'
curl -s -X POST .../api -d '{"op": "motion.release", "args": {"token": "<token>"}}'

# power off after confirming with the person
curl -s -X POST .../api -d '{"op": "power.off", "confirm": true, "origin": "external:panel"}'
```

## Owner of the movement

`motion.ask` / `motion.reserve` answer from the same rules the pages use: a file job running,
a live job with activity or orders of the G-code bridge in the last 20 s deny moves; a live job
open but idle asks for a confirmation; a paused file job allows moves (RepRapFirmware restores
the position on resume) but not geometry changes. The current state is also published in the
object model, `plugins.WorkshopService.data.motion`, without any request.

Who holds the control (F1-D): a reservation belongs to (origin, device, person), taken from `X-Workshop-Device` and the
session. Another device cannot take, renew or release it: the answer names the person (or "another device" when there are
no users) and since when. `motion.take_over` (technician or administrator) takes it from the holder, stops that holder's
jog, leaves a notice in `data.motion.notice` and a row in the audit; during a file job, a live job or bridge activity only
an administrator may. The jog keeps one lease per device: a second device is refused without touching the first;
`jog.stop_*` with `release: true` only lets go of the caller's own control, without it they stop everything (no login).
`data.motion.owner` carries `name`, `device` (8 characters) and `since` (epoch seconds).

Nothing stops a program from sending G-code to `/machine/code` directly: asking first is what
keeps two pages, the jog and a program from moving at the same time.

## Shared settings with a revision

`settings.get {name}` returns `{value, rev}` of a shared settings file (`jog`, `laser`, `cameras`, `vision`... a fixed list under
`sys/workshop/config`, never a path); a file that does not exist yet is `{value: null, rev: "0"}`. `settings.set {name, value, base_rev}`
writes the whole file only if `base_rev` is still the current rev; otherwise it answers `409` with `error.code = "conflict"` and
`error.current = {value, rev}`: merge your change into `current.value` and send it again. `settings.merge {name, patch}` replaces only
the top-level keys of `patch`, without a revision check. The rev is a hash of the file, so a program that still writes the file through
DWC's file API is not broken: it just has no protection and makes the next `settings.set` based on the old rev conflict.

## Machine profile, capabilities and pre-install check

- `capabilities.get {refresh?}` (viewer): what this machine has, discovered from the live board and the SD (board and firmware, axes,
  driver chips, tools, heaters, probe with its speeds and tolerance, modes, laser, spindle, LED strip, cameras, meter, and for Machine the
  kinematics (`supported` / `unsupported` for delta, SCARA...), `axis_drivers`, `z_motors`, `endstops`, `accelerometers`, `input_shaping`,
  `compensation`, `workplaces`, `tool_offsets` and `levelling`). Every capability is
  `{present, source}` with `source` = `discovered` | `declared` | `default`; the answer is cached for 30 seconds (`refresh: true` reads again).
  The pages use it to hide what the machine does not have, with the reason.
- `profile.get` (viewer) returns the declared profile plus the macro paths that really exist and the axis indexes found on the board;
  `profile.set {changes, replace?}` (administrator) validates and saves it atomically in `0:/sys/workshop/config/machine.json`
  (schema 3; a file of another schema is ignored and the defaults are used; the last healthy copy stays as `machine.json.bak`). Invalid fields answer `invalid_args`
  with one message per field. The fields are listed in `docs/INSTALL.md`.
- `preflight.run {features?}` (technician) runs the same checks as `tools/preflight.py`: one item per check with `ok`, `warn` or
  `error` and the fix in words.
- `api.ping` (no login) answers `{pong, time}`; `api.describe` and `GET .../api` list the operations.

## Machine (calibration procedures)

Machine v2 runs its calibration procedures IN THE SERVICE, not in the page: `machine.run` takes the reservation of the movement
(class `sequence`), sends only G-code from a closed list (`dsf/machine_gcode.py`; never `M569.2`, `M569.1`, `M918`, `M950` or `M112`),
publishes the progress in the plugin data key `machine` and stores the result in the calibration history. Closing the page changes
nothing: `machine.runs` returns the run in progress to a page that was reloaded. One procedure at a time. Design:
`TallerPlugins/docs-internal/MACHINE-V2-DESIGN.md`.

| Operation | Role | What |
|---|---|---|
| `machine.overview` | viewer | per kind of calibration its traffic light (`never`, `ok`, `old`) and age in days, what the machine is ready for (homed, probe, mesh active, kinematics, levelling mode) and whether a procedure runs. No values of offsets or limits. |
| `machine.state` | operator | the overview plus the modules available (or hidden with the reason), the runs, the newest records with their values, the maintenance state and the `machine` block of the profile. |
| `machine.runs {run_id?}` | operator | the run in progress (`current`) and the last finished ones, newest first, with `state`, `step`/`total`/`phase`, `result` and `error.code`. |
| `machine.run {kind, params?}` | technician | starts a procedure; answers `{run_id, kind, state}`. Kinds: `probe.read` (phase 0, moves nothing), `probe.repeat`, `level.g32`, `level.g30`, `level.measure`, `mesh.probe` (phase 1, below). The other kinds of the design answer `not_implemented`. Refusals: `error.reason` = `no_probe`, `not_homed`, `unsupported_kinematics`, `heater_fault`, `no_model`, `busy_run`, and the ones of the procedure (`no_probe_index`, `no_levelling`, `no_m671`, `no_bed_g`, `bed_g_points`, `no_points`, `too_many_points`, `too_few_points`, `out_of_reach`, `duplicate_point`, `no_limits`, `descent_limit`, `bad_region`); `motion_denied` when the movement is not free. |
| `machine.stop` | viewer, never blocked | ends the procedure at its next step, retracts the probe if it was deployed, releases the movement. It does NOT send `M112`. Listed in `STOP_OPS`. |

Run states: `queued`, `running`, `stopping`, `done`, `error`, `aborted` (stopped, machine halted or reservation lost; the reason is in
`error.code`: `stop`, `machine_halted`, `reservation_lost`). The reservation is always released; each run ends with an audit row
`machine.run.end` (with `run_id` and `kind`) and, for procedures that record, a row `machine.record`.

### Phase 1: probe, levelling and mesh (all server side)

Replies of the board are read tolerantly (`dsf/machine_parsers.py`): the raw text is kept, a field the reply does not have is simply missing, and
nothing crashes on an unknown wording. Only part of the wording is verified against the firmware source (see `MACHINE-V2-GCODE-REFERENCE.md`);
the rest needs captures of the real machine. Every run honours the safety limits of the profile (`machine.safety.max_probe_descent_mm`,
`max_points_per_run`), a stop request between steps, and ends with the probe retracted and the reservation released.

| Kind | Parameters | What |
|---|---|---|
| `probe.repeat` | `probe`, `samples` 2-100 (10), `x`+`y` (where the probe touches; without them: the current XY), `deploy_each` | N measure-only touches (`G30 K.. S-1`, or `G30 P0 X Y Z-99999 K.. S-1` at a point); mean, sample deviation, min/max/range, drift between halves, traffic light by `machine.thresholds` (`probe_sigma_warn` / `probe_sigma_bad`). |
| `level.g32` | `probe`, `passes`, `tolerance`, `points`, `verify` (true), `rehome_z` (false) | G32 passes (bed.g); convergence below the tolerance, error `diverging` when the deviation grows, `limit` (record `partial`) at the pass limit, `manual` when the firmware only says how to turn the screws, error `corrections_exceed`; then a measure-only pass (the "after" of the firmware is only expected). `rehome_needed` tells that Z=0 shifted. |
| `level.g30` | same | the same loop with the points of the run (parameters, profile `levelling.probe_points`, numeric G30 lines of bed.g, or one near each leadscrew), `S` = leadscrews. |
| `level.measure` | `probe`, `tolerance`, `points` | measure only, nothing is calibrated and no motor moves; heights per point, mean, deviation, range. |
| `mesh.probe` | `probe`, `nx`, `ny`, `region {x0,x1,y0,y1}`, `margin`, `run_g32` (auto), `name`, `save` (true) | `G32` first when the machine levels with leadscrews (it clears the map), `M557`, `G29 S0 K..` (never a bare `G29`: `mesh.g` is not run), reads the map, statistics, quality gate (a partial map is kept in the library and left not active), library entry. |

| Operation | Role | What |
|---|---|---|
| `machine.mesh.list` / `machine.mesh.get {id}` | operator | the library (`m-...`) with who/when/probe/statistics and its validity (`trigger_height_changed`, `config_changed`, `probe_changed`, `partial`; age is only `old`), the active compensation, one map with its grid and statistics. |
| `machine.mesh.load {id, accept_stale?}` | technician | puts the map in `sys/heightmap.csv` (the previous one is kept) and sends `G29 S1`; refused when the map no longer matches the machine unless `accept_stale`. |
| `machine.mesh.clear` / `machine.mesh.taper {height}` | technician | `G29 S2` / `M376 H..`. All three: class `geometry` (denied with a job) and refused while a procedure runs. |
| `machine.mesh.save {name?}` / `machine.mesh.delete {id}` | technician | copies the active map into the library (done by the service; `G29 S3` is not used) / deletes an entry. |
| `machine.config.plan {kind, values}` | technician | builds the change WITHOUT writing: file, diff, warnings, `plan_id` (15 minutes). Kinds: `config.m671` (`x`, `y`, `s`, `p`, `f`; the line is replaced where it is, config.g or a macro it calls, or added after M584) and `config.bed` (`points`, `k`, `s`, `passes`, `tol`, `rehome_z`; the user's own bed.g is kept, only the points, tolerance, passes and the final `G28 Z` change). Other kinds: `not_implemented`. |
| `machine.config.apply {plan_id, kind, apply_now?}` | technician (admin for the hardware-risk kinds) | writes the plan through `config.commit` (snapshot of the set first, sha check, atomic swap), notes it in the history with the plan id as `run_id`, and with `apply_now` sends the new M671. `kind` is an argument on purpose: the registry raises the role from it and the handler refuses a plan of another kind. Needs a confirmation; class `geometry`. |

### Phase 2: history, restore, report, safety check, offsets, limits (server side)

The exact shapes the plugin builds against are in `docs/MACHINE-PHASE2-CONTRACT.md`. Summary:

| Operation | Role | What |
|---|---|---|
| `machine.history.list {kind?, user?, state?, since?, until?, limit?, offset?}` | technician | the calibration records newest first (who, when, how they ended, restorable). |
| `machine.history.get {id}` | technician | one record complete, and what a restore would need (values `before` / `after`, role needed, state of the files the record wrote). |
| `machine.history.compare {a, b}` | technician | two records of the SAME kind: the table of values that differ (`results`, `inputs`, with `delta = b - a`) and, for `mesh.probe`, the difference grid and its statistics (same grid required, no resampling). |
| `machine.history.restore {id, which?, kind?, accept_current?}` | technician (admin for the hardware-risk kinds) | builds a PLAN (writes nothing) that puts the `before` (undo) or `after` values of a configuration record back; `machine.config.apply` writes it (fresh snapshot, sha check). Refused with `conflict` / `file_changed` and a three-way table when a file is neither as the record left it nor as it found it, unless `accept_current`. An `offsets.snapshot` becomes a `config.workplaces` plan. |
| `machine.report {id}` / `{full: true}` | technician | the DATA of a printable report (the page draws it): one calibration (values, who, when, mesh grid or level residual) or the status of the whole machine (newest record of every kind, limits, offsets, active mesh, a fresh safety check). No SVG on the server. |
| `machine.offsets.get` | operator | tool offsets (per tool and axis, probed axes) and the nine work offsets G54..G59.3 from the object model, the work system selected now, the last snapshot. |
| `machine.offsets.snapshot {note?}` | technician | stores both tables as a record `offsets.snapshot` and returns the differences with the previous snapshot. |
| `machine.limits.get` | operator | the M208 limits of every axis, the endstops and where the configuration defines M208. |
| `machine.layout {mode, probe?, x0 x1 y0 y1?, nx?, ny?, points?, margin?}` | operator | READ, no motion, nothing sent to the board: data for the bed view of Mesh and Level (axis limits, probe and offsets, reach of the probe, M671 leadscrews, which mesh / level points are taken or excluded and why, last mesh and level measurements). Exact keys: `docs/MACHINE-LAYOUT-CONTRACT.md`. |
| `machine.try {gcode_kind, action?, values, seconds?, try_id?}` | technician (admin for M208, M92, M906, M913, M917) | VOLATILE trial with automatic revert. Phase 2: `M208` (`values {axes: {X: {min, max}}}`); phase 3 adds M92, M906, M913, M917, M203, M201, M205, M566, M425, M556, M593 (below); `M376` answers `not_implemented`. `action` start / keep / revert. The previous limits are written to `sys/workshop/data/machine/try-pending.json` first and put back after `seconds` (5-600, default 60) even if the page closed; `recover_pending` (started by main.py) puts them back after a restart. Class `geometry`, level 3 confirmation, one trial at a time. |
| `machine.mark_cross {action?, power?, save?}` | technician | laser <-> pointer assistant on the server: `mark` fires a 4 mm cross (Laser mode, X and Y homed, 1-10 %, interlocks closed, movement reserved, level 3 confirmation; the laser guard is armed and M5 always follows), `capture` computes the correction once the pointer is over the cross (`save` writes it to the settings store `laser` key `correction` and to the history), `clear` forgets the mark. |
| `machine.height.get` | operator | READ: the height calibration of the tool (it was a card of the Workbench): per mode `{general: {method, setting}, k0, szp}`, the paper thickness, the `rev` to save against, the hooks of the mode files, whether `zcal.g` exists, the probes of the object model (trigger height, offsets), the macros present and what is homed. |
| `machine.height.save {base_rev, changes}` | technician | `changes {paper?, modes: {Laser|CNC|FFF: {method?, setting?, k0?, szp?}}}` (fine adjustment -3..3 mm; `k0 {p, x, y, z, date}`; `szp` only FFF; `null` removes). Revisioned like `settings.set` (409 `conflict` returns the current value). Rewrites `sys/workshop/macros/zcal.g` and applies it now unless a job runs (`applied`, `apply_reason`). Audited. |
| `machine.height.hook` | technician | adds `M98 P"0:/sys/workshop/macros/zcal.g"` to `modelaser.g`, `modecnc.g`, `modefff.g` when missing (a `.bak-<stamp>` copy of each first). Audited. |
| `machine.height.step {action, x?, y?, dz?, paper?, h?, a?}` | technician | motion, reserved like `machine.mark_cross` (refused during a job): `goto` (macro zcal-goto, X Y), `jog` (one relative Z step of -5 -1 -0.1 -0.05 0.05 0.1 1 5, always `S0`), `mark` (zcal-mark: Z0 with the paper `paper` and rise to `h`), `measure` (zcal-probe at X Y: returns `measured`), `szp` (FFF: zcal-szp, `a` 1 or 2: returns `output`). |
| `machine.workarea.get` | operator | READ: the work area of each mode (`cutarea.g`: `areas {Laser|CNC|FFF: {xmin,xmax,ymin,ymax} \| null}`), `mode`, `reach` (M208 travel of X and Y), `macros`, `homed {X,Y}`, `edit_modes`, `min_mm` (machine_workarea.py; it was a card of the Workbench) |
| `machine.workarea.positions` | operator | READ: the positions saved by the jog (`positions.json`): `positions [{name, x, y, z}]` in machine coordinates (where the tool was); two of them can be the corners of a work area |
| `machine.workarea.save {mode, rect?, remove?}` | technician | WRITE: one mode (Laser, CNC or FFF): `rect {xmin,xmax,ymin,ymax}` (at least 10 mm each way, inside the travel; error `reason` `not_numbers` / `too_small` / `outside_travel`) or `remove: true`; keeps the other modes and a `.bak` of the file, reloads it when no job runs -> `{mode, areas, applied, apply_reason}` |
| `machine.workarea.release` | technician | MOTION, level 4 confirmation: X and Y off (`handfree.g`) to take the pointer to a corner by hand |
| `machine.workarea.step {action, x?, y?}` | technician | MOTION, reserved like `machine.height.step`: `capture` (`handcorner.g`, answers `{x, y}`), `goto` (`gotobed.g` X Y), `frame` (`framecutarea.g`, walks the saved area of the mode in use with the pointer, laser off) |

New `machine.config.plan` kinds (all show the diff first, the plan also carries `before` and `after`): `config.g31` (`k`, `p`, `x`, `y`, `z`), `config.m208`
(admin; `axes {X: {min, max}}`), `config.m92` (admin; `axes {X: steps}`), `config.g10` (tool offsets, `tool`, `offsets`), `config.workplaces` (`systems
{"1": {X, Y, Z}}`, `target` macro | config: the G10 L2 block goes to `0:/sys/workshop-offsets.g`, which config.g calls; `M500` is not used). The patchers
(`dsf/machine_patch.py`) keep the user's spacing, comments and line endings, edit the last definition of a value, add a missing line after a sensible
anchor, never replace an expression (`X{...}`) and never rewrite `M208 S..` lines; golden files in `dsf/golden/patch/`.

New `machine.run` kinds: `safety.check` (read only: no reservation, no connection, works during a job; items with severity and action key, the
reset reason is `unavailable` because the object model has no key for it) and `homing.verify` (homes the axes one by one, level 3 confirmation:
endstop present, not pressed before, position equals the declared home within the tolerance, endstop triggered after). Homing repeatability and the
travel check are phase 3 and are not implemented.

Audit: `machine.history.restore`, `machine.offsets.snapshot`, `machine.try`, `machine.mark_cross` and `machine.config.apply` are audited by the
registry like every non-read operation; `machine.report` writes an `audit.event` row; plus `machine.run.end`, `machine.record`,
`machine.mark_cross.saved`.

`PLANNED_OP_ROLES` in `dsf/permissions.py` (classified, not registered yet) is empty since phase 4. The hardware-risk writes (M208, M92, M906/M913/M917, M569,
M584) need an **administrator** whichever operation carries them: the rule `ESCALATE_IN` (published to the pages as `escalate_in` in
`auth.whoami`) raises `machine.config.apply`, `machine.history.restore` (argument `kind`: `config.m208`, `config.m92`, `config.m906`,
`config.m913`, `config.m917`, `config.m569`, `config.m584`) and `machine.try` (argument `gcode_kind`: M208, M92, M906, M913, M917); `machine.config.apply` and `machine.try` called without that argument need admin too (fail closed).

The calibration history (`machine-calibrations`, last 500 records) and the maintenance state (`machine-maintenance`) are settings files with
a revision that only the service writes: `settings.set` and `settings.merge` refuse them, `settings.get` (operator) reads them.

The store `machine-pointsets` (named point sets of the bed view, `docs/MACHINE-POINTSETS-CONTRACT.md`) is the opposite: an ordinary store, `settings.get` for the operator and `settings.set` / `settings.merge` for the technician; the page owns its shape.

### Phase 3: steps, squareness, backlash, motion parameters, input shaping (server side)

The exact shapes the plugin builds against are in `docs/MACHINE-PHASE3-CONTRACT.md`. Summary:

| Operation | Role | What |
|---|---|---|
| `machine.calc {calc, values, save?, note?}` | technician | arithmetic of the assistants, nothing is sent to the board: `steps` (`new = old * commanded / measured`, refused outside 0.5-2), `skew` (from the two diagonals of a square -> `M556 S.. X..`), `backlash` (samples of lost motion -> `M425`, always with the fixed-backlash warning), `ringing` (frequency from the ripples). Returns the value, the G-code `line`, `warnings` and the `plan` {kind, values} for `machine.config.plan`; `save` stores a record `calc.<calc>`. |
| `machine.motion.get` | operator | per axis and extruder: current (M906), idle factor and timeout, percent current (M913), standstill (M917), microstepping, interpolation, speed, acceleration, jerk, backlash, driver mode and direction (from the `M569` lines of the configuration). What the board did not report is `null` and listed in `unavailable`. |
| `machine.shaping.get` | operator | the shaper of the board (`move.shaping`), the types that can be set, the M593 lines of the configuration and the accelerometer capability. |
| `machine.shaping.test {axes?, origin_x?, origin_y?, size?, feed?, accels?, repeats?}` | technician | the G-code of a ringing test as TEXT (never sent to the board). |
| `machine.try` | technician (admin by `gcode_kind`; without it, admin) | now also `M92`, `M906` (and idle), `M913`, `M917`, `M203`, `M201`, `M205`, `M566`, `M425`, `M556`, `M593`. M906 stays within `machine.safety.max_current_ma` of the profile (default 2800 mA, never above 6300). Refused with a job (`job_running`). A revert the board refuses is retried every 10 s. `keep` answers `persist {kind, values}` for `machine.config.plan`. |

New `machine.config.plan` kinds: `config.m556`, `config.m425`, `config.m593`, `config.m203`, `config.m201`, `config.m205`, `config.m566` (technician) and
`config.m906`, `config.m913`, `config.m917`, `config.m569` (ADMIN). `config.m569` edits only `S` (direction) and `D` (spreadCycle / stealthChop) of an
existing line: it never adds a line, never touches the other tokens, never rewrites closed loop and never sends anything to the board. The patchers are in
`dsf/machine_patch_motion.py` (golden files `dsf/golden/patch/motion.*`, `bare.m*`).

New `machine.run` kind `shaping.tune` (level 3 confirmation): collects accelerometer data with `M956 .. A0` while the axis moves; refused with
`reason: "no_accelerometer"` unless `capabilities.accelerometers.present` AND the object model lists that accelerometer. The service does not analyse the file.

Policy (design 5.4): the closed list has no template for `M569`, `M955` only as a bare report and `M956` only with `A0`; the second wall refuses every
`M569.<n>`, `M918`, `M950`, `M112`.

### Phase 4: maintenance and camera verification (server side)

The exact shapes the plugin builds against are in `docs/MACHINE-PHASE4-CONTRACT.md`. Summary:

| Operation | Role | What |
|---|---|---|
| `machine.maintenance.get` | operator | the counters (power-on hours, moving hours and ESTIMATED distance per axis letter and for the machine, gaps, cross-check with the planned path of the last file job) and the items of the plan with `used`, `remaining`, `ratio` and `status` (`ok`, `due_soon`, `due`, `overdue`), `last_done`, the opt-in of the notices and a summary. |
| `machine.maintenance.done {id, note?}` | technician | records who and when (audit `machine.maintenance.done`) and resets the item (the counters at that moment are its new zero). |
| `machine.maintenance.plan.set {items?, defaults?, notify?}` | technician | edits the plan (saved in `machine.maintenance` of the profile, validated by the profile) and the opt-in of the phone notice when an item becomes due. A technician may do it because it only changes reminders; the profile itself stays admin. |
| `machine.run {kind: "offsets.verify", params}` | technician | moves to the offsets of a work system (`G53`) or the active tool (`G1 X0 Y0`), asks Vision where the crosshair or mark is and reports the error in mm with its uncertainty. Needs the Vision capability `vision.measure`; otherwise refused with `reason: "no_vision_measure"`. Level 3 confirmation. |

`machine.overview` has `maintenance` (counts of items `due_soon`, `due`, `overdue` and the worst status; no values) and `machine.state` has `vision: {measure, checked_at}`.
The counters process (`maintenance` on the Services page) listens to the single subscription of `machine_state` (nothing polls `/machine/status`), writes
the store `machine-maintenance` every 5 minutes and when it rests, and rests when the plugin WorkshopMachine is stopped.
`vision.post` accepts the path `/measure` (an operator's path like `/detect`: it only looks).
Notices: a new activity type `maintenance` (phone notice, language of DWC outside a request).


## Protection guard

`guard.status` (viewer) says which safety processes are expected, which are watched and which are down (the same list is in the plugin
data key `guardStatus`); `guard.set` (administrator) changes `enabled`, `action` (`notify` | `pause`: also pause a file job when the fire
or servo protection is down) and the tolerances. A fallen protection raises a `guard` event in Activity and makes the status lights stop
showing "ready".

## Work state of the operator

`workstate.get` (viewer) returns `{state, rev}`; `workstate.set {state}` (operator) records part of it. It exists because
`settings.set` needs a technician and this is what an operator does all day. Same shape as the Workbench keeps under the key
`work_state` of the `focus` file, so moving it is trivial:

```
{"v": 1,
 "zones": {"<zone number>": {"prepare": {"measure": ts, "border": ts}, "applied": {"z": number|null, "ts": ts}}},
 "focus_h": {"h": number, "base": number, "ts": ts}}
```

`ts` is epoch milliseconds; a negative `prepare` mark means "cleared at that time". The document is stored as the shared
settings file `work_state` (so it has a rev and a backup). `workstate.set` merges what it receives mark by mark and the newest
`ts` wins (a tie goes to the new value): what you did not send, or sent older, is not overwritten. It answers
`{state, rev, changed}` with the merged state. Any unknown key, boolean, text or out of range number refuses the whole call with
`invalid_args` and `error.field`. At most 32 zones. The write goes to the audit like any other. `settings.set` of `focus`
stays a technician's.

## Laser interlocks (optional)

The machine profile (`profile.set`, schema 2) may declare `interlocks: {lid, extraction, key}`, each
`{gpin: <N of sensors.gpIn[N]> | null, active_when: "high" | "low", label}`; `active_when` is the level of the input at which the
interlock is satisfied (closed / on). `capabilities.get` then reports `lid_interlock`, `extraction_interlock` and `key_interlock`
as present (`source: "declared"`) when declared and the input exists in the object model. `safety.status` (viewer) returns
`{declared, ok, interlocks: [{name, capability, label, gpin, active_when, state}]}`, `state` being `ok`, `open` or `unknown`
(no input, no value or no board: counts as not ok). In Laser mode, with a declared interlock that is not ok, `job.start` and
`frame.start` with `mode: "laser"` fail with `interlock_open` (423 refusal, `error.interlock` names it); stops and
moves without the laser are never affected, and without declared interlocks nothing changes. The protection guard also raises
an urgent `guard_alarm` if one opens during a laser job. This does not replace the firmware: see `docs/INTERLOCKS.md`.

`activity.log` also accepts `safety_check` (the operator confirmed the manual checklist: `zone`, `points` = ids of the confirmed
points; the user is the caller) and `job_start` (`text` = job name, `zone`).

## Activity by person and Pi health history (F3-H)

`activity.list` and `activity.summary` take `user` (a user name: only the events whose `user` column is that name) and `mine`
(true: only the events of the person of the session; the server knows who it is from the token). In open mode (no users created)
`mine` filters nothing; `user` and `mine` together: `user` wins. Events written by the service or by programs have no user and
are only returned without the filter. A client that gets `unknown_arg`/`unknown_op` from an old service falls back to filtering
the loaded page.

`health.history` (viewer) returns the history of the Pi health kept in the database (table `health_samples`, schema 6):
`range` = `1h` (default) | `6h` | `24h` | `7d`, `limit` = most points per series (10 to 1000, default 300). The answer is
`{range, since, step_s, retention_days, series: {cpu, temp, ram, disk, wifi}}`, each series a list of `{t: epoch milliseconds,
y: value}` averaged in buckets of `step_s` seconds (cpu, ram, disk, wifi in %, temp in degrees C; wifi is 0 when the link is down).
The poller records a sample every cycle (at most one per 5 s); the last 2 hours are kept complete, older ones are thinned to one
per 30 s, and rows older than `health.history_days` of `config.json` (default 7) are deleted by the database maintenance.

## Confirmations

Operations with a risk declare a level (3: can damage, 4: leaves the machine without a
protection while it lasts). Without `"confirm": true` they answer `428 confirm_required` with
`error.confirm = {level, key, texts: {es: {title, text}, en: {...}}, reason?}`. Show the text to a
person and only then repeat the call with `"confirm": true`.

## Macros of the SD

A macro cannot make HTTP requests. It calls the service with the helper macro that WorkshopService
writes at start:

```
M98 P"0:/sys/workshop/macros/service-call.g" S"power.after_job" A"armed=toggle"
M98 P"0:/sys/workshop/macros/service-call.g" S"activity.log" A"type=warning,text=Door open" W5
```

`S` = operation (only the ones marked `macro` in the list), `A` = arguments `key=value,...`
(numbers and true/false are converted), `W` = seconds to wait for the answer (default 5, `W0` =
do not wait), `Q1` = do not echo the answer. The answer is in `global.wsReply`
(`"<n>|ok|<text>"` or `"<n>|error|<text>"`). The request travels in RepRapFirmware global
variables (`global.wsRequest`) that the service reads in its object model subscription.

## G-code bridge (live jobs)

Put these lines in the start / end G-code of the program that sends the live job through the
G-code bridge; the bridge answers them itself and tells the service:

```
BRIDGE JOB START <name>
BRIDGE JOB END
```

`BRIDGE JOB CANCEL` marks a cut job. Run `BRIDGE HELP` in a terminal connected to the bridge for
the rest of its commands.

## Safe stop and resume of the live job (`livejob.*`, 2026-10-22)

A live job is a program streaming G-code through the bridge (`BRIDGE JOB START ... END`). These operations stop it without cutting anything and let
it go on from where it stopped. The bridge does the work (it sees the lines); the service checks the machine and talks to it. It is **not** the
emergency stop: `M112` / `machine.stop` keep working as before. Design: `TallerPlugins/docs-internal/LIVE-JOB-STOP-RESUME.md`.

| Operation | Role | What it does |
|---|---|---|
| `livejob.stop_safe` | anybody (it is a stop) | Refuses the lines that come after, lets what the board already accepted finish, turns the laser off (`M5`), reads the head (`M114`) and saves an interrupted record. Returns `{stopped, id, lines, resumable, why_not, message}`. Conflict when there is no live job; fails (and the job keeps running) if the laser-off order fails or the board does not finish in time. |
| `livejob.interrupted.list` | operator | `{available, live_job, stopping, resume, records}`: each record is light (`id, name, started, stopped, lines, bbox, cut_mm, program_pos, position, mode, resumable, why_not, armed`) plus `blockers` and `can_resume`. `blockers`: `not_laser`, `rebooted`, `machine_unknown`, `job_running`, `machine_busy`, `not_homed`, `not_resumable`. |
| `livejob.interrupted.get {id}` | operator | The record with `path` (`[[x, y, cut]]`, program coordinates) and `bbox`, `modal`, `program_pos`. |
| `livejob.resume.arm {id, overlap_lines}` | operator, **confirm level 3** | Arms ONE record for 30 minutes. The next `BRIDGE JOB START` verifies and skips the lines already done (an `ok` each, nothing reaches the board), goes back to the point with the laser off and continues. `overlap_lines` (0..39) cuts the last lines again. Refused with `conflict` + `error.blockers` when a blocker applies. |
| `livejob.resume.disarm` | operator | Cancels the armed resume. |
| `livejob.interrupted.discard {id}` | operator | Deletes a record. |

How the resume is verified: the bridge hashes the normalized lines (comments out, upper case, one space) that reached the board and keeps a
checkpoint every 50 lines. The relaunched job must produce the same hashes; the first difference cancels the resume, nothing runs and the rest of that
job is refused (the record is kept). Only laser jobs are resumable; a board restart after the stop blocks it (origins and offsets are gone).


## Job trace, only what is new (`trace.since`, 2026-10-24)

The trace of a job (what the head did: `[t, x, y, z, pwm, v, air, e, layer, rpm, fpos]` per sample, `meta.fields`) is recorded by
`dsf/job_trace.py` for file jobs and live jobs (network or USB bridge) alike. `trace.since` returns only the samples added since a cursor,
so a page never reads nor rebuilds the whole trace again. The job being recorded and the last one closed are served from memory (a slice of
the list); older jobs from their history file `0:/sys/workshop/data/jobs/<id>.json`, parsed once and cached while it does not change.

| Operation | Role | What it does |
|---|---|---|
| `trace.since {job, cursor, limit}` | operator | `job`: a history id (`YYYYMMDD-HHMMSS`) or `"current"` (default: the job being recorded, else the last one recorded). `cursor`: the one of the previous answer, empty = from the first sample. `limit`: 1..10000 samples per answer (default 2000). Returns `{job, active, samples, cursor, done, more, reset, meta}`. Read, not noted in the history of commands. |

- `cursor` is opaque (`"<job>.<reduction>.<count>"`): send back exactly what came. A cursor of another job, of a trace whose samples were
  halved (long jobs, `meta.reduction`) or past the end answers from the first sample with `reset: true`: drop what you had and use these.
- `more: true`: there are more samples right now (call again without waiting). `done: true`: the job ended and every sample was sent; stop
  asking. `active`: the job is still being recorded. `meta`: `name, origin (file/live), mode, zone, start, end, end_approximate, duration_s,
  result, state, laserOffsetOn, plan, fields, reduction` (whatever the trace has).
- With `"current"` and nothing recorded yet: `{job: null, samples: [], cursor: "", done: true, ...}`. An id that does not exist: `not_found`;
  a malformed `job` or `cursor`: `invalid_args`.
- Asking for `"current"` or for the job being recorded also keeps the recorder awake (the same as `view.heartbeat {topic: "trace"}`).
- Deleting the trace (the Delete button of the job card removes `0:/sys/workshop/data/trace.json` with a plain DSF file delete,
  `DELETE /machine/file/...`; any other way of removing that file counts the same) also forgets the last closed job the service keeps in
  memory: from then on `"current"` answers nothing recorded (`{job: null, samples: [], cursor: "", done: true, more: false, reset: false,
  meta: null}`) until another job starts. The history copy `data/jobs/<id>.json` is not touched and `trace.since {job: "<id>"}` still
  reads it. A job being recorded is never forgotten (the recorder writes the file again).
