# Machine v2 phase 2: contract for the plugin (service side)

Branch `m2-service`. Everything here is called through `POST /machine/WorkshopService/api` `{op, args}` (see `docs/api/README.md`).
Answers are `{ok, op, result}` or `{ok:false, error:{code, message, ...}}`. Texts that the service builds are Spanish/English by the request
language; everything else is codes and numbers (the plugin translates them). Nothing here was run against a real board: the replies of the
firmware are the ones of `docs-internal/MACHINE-V2-GCODE-REFERENCE.md` (see "Unverified" at the end).

Roles: `viewer < operator < technician < admin`. The administrator kinds are `config.m208`, `config.m92` (phase 2) and `config.m906`,
`config.m913`, `config.m917`, `config.m569`, `config.m584` (later). `permissions.table_for_client()` publishes the same table (`escalate_in`).

## Operations

| op | role | kind | args | result |
|---|---|---|---|---|
| `machine.history.list` | technician | read | `kind?`, `user?`, `state?`, `since?`, `until?` (epoch s), `limit?` 1-200 (50), `offset?` | `{records: [Brief], total, limit, offset}` |
| `machine.history.get` | technician | read | `id` | `{record: Record, restore: {restorable, reason, which: ["before","after"], role_needed, files: [FileState]}}` |
| `machine.history.compare` | technician | read | `a`, `b` (record ids, same kind) | `{kind, a: Brief, b: Brief, results: Diff, inputs: Diff, mesh: MeshDiff or null}` |
| `machine.history.restore` | technician (admin by the record's kind) | write | `id`, `which?` ("before" default; a snapshot only "after"), `kind?` (kind of the record; the registry escalates from it), `accept_current?` | a Plan (below) with `restore: {of, which, dirty, accepted_current, three_way: [{key, before, after, now}], files}`; NOTHING is written: send `plan_id` to `machine.config.apply` with the plan's `kind` |
| `machine.report` | technician | read | `id` (one calibration) or `full: true` | Report (below) |
| `machine.offsets.get` | operator | read | - | `{tools, work, current, axes: ["X","Y","Z"], last_snapshot: {id, ts, user} or null}` |
| `machine.offsets.snapshot` | technician | write | `note?` | `{tools, work, current, record_id, previous: {id, ts, user} or null, changed: n or null, diff: [DiffRow] or null}` |
| `machine.limits.get` | operator | read | - | `{axes: [{index, letter, min, max, min_probed, max_probed, homed, visible, position}], endstops: [{index, axis, type, high_end, triggered, probe}], definitions: [{file, line, text}], warnings: [{code: "bad_limits" or "no_endstop", axis}], config_read}` |
| `machine.try` | technician (admin for M208) | motion (geometry), level 3 confirm | `gcode_kind` ("M208" implemented; M92, M906, M913, M917, M593, M425, M556, M376 answer `not_implemented`), `action?` ("start" default, "keep", "revert"), `values` = `{axes: {"X": {min, max}}}`, `seconds?` 5-600 (60), `try_id?` | start: `{try_id, gcode_kind, previous: {X: {min, max}}, applied: {...}, ts, seconds, expires_at, user, action: "start"}`; keep: `{try_id, action: "keep", kept: true, applied}`; revert: `{try_id, action: "revert", reverted: true, previous}`. Errors `reason`: `try_pending`, `busy_run`, `no_previous`, `board_error`, `not_found`, `revert_failed` |
| `machine.mark_cross` | technician | motion (sequence); the mark asks for `confirm` (level 3) | `action?` ("mark" default, "capture", "clear"), `power?` 1-10 (3), `save?` (capture) | mark: `{action, head: {x, y}, power_pct, s, size_mm: 4, marked_at}`; capture: `{action, mark: {x, y, ts}, head: {x, y}, correction: {x, y}, previous: {x, y, date} or null, saved, record_id}`; clear: `{action, cleared}`. Refusal `reason`: `bad_power`, `no_model`, `not_laser_mode`, `no_laser`, `not_homed`, `interlock_open`, `busy_run`, `busy_mark`, `no_mark`, `no_position` |
| `machine.config.plan` / `machine.config.apply` | technician (admin for the admin kinds, from `kind`) | see phase 1 | new kinds below | the Plan gets `before` and `after` |
| `machine.run` | technician | | new kinds `safety.check`, `homing.verify` (below) | `{run_id, kind, state}`; follow with `machine.runs` |

Operations that write or move are audited by the registry (`audit` table: user, role, device, op, arguments). Pure reads are not (as everywhere in the
API), except `machine.report`, which writes an `audit.event` row `machine.report`. Plus rows `machine.run.end`, `machine.record`,
`machine.mark_cross.saved`.

### Shapes

- **Brief** `{id, kind, ts, user, role, device, state, run_id, notes, outcome, light, applied: bool, restorable: bool}`
- **Record** (calibration store, schema 1) `{id, kind, ts, user, role, device, origin, run_id, machine, inputs, results, applied, notes, state}`;
  `applied` = `{files: [{path, sha_before, sha_after, snapshot_id}]}` for configuration records.
  Record kinds added in this phase: `safety.check`, `offsets.snapshot`, `laser.pointer` (plus the configuration kinds below).
  A configuration record has `results.before` and `results.after` in the same shape the planner takes as `values` (null when the line did not exist).
- **FileState** `{path, sha_now, sha_before, sha_after, state: "clean" | "changed" | "missing"}`
- **Diff** `{rows: [DiffRow], changed: n, cut: bool}`; **DiffRow** `{key: "stats.stdev", a, b, delta: number or null, changed: bool}` (changed rows first)
- **MeshDiff** `{ok: true, axes, grid, rows: [[number or null]], stats, ids: [a_mesh_id, b_mesh_id]}` (rows = b - a, null where either was not probed) or
  `{ok: false, reason: "grid_differs" | "mesh_missing" | "unreadable"}` (a different grid is NOT resampled)
- **Plan** (phase 1 shape) `{plan_id, kind, files: [{path, exists, sha_before, sha_after, changed, diff, diff_cut}], warnings, action, line, role_needed,
  expires, can_apply_now, before, after, restore?}`
- **Tables** (`machine.offsets.*`, the record of `offsets.snapshot`)
  `tools = {"<number>": {name, offsets: {"X": v}, probed: ["X"]}}`, `work = {"<1..9>": {code: "G54".."G59.3", offsets: {"X": v}}}`, `current = 1..9 or null`.

### Restore rules (design 5.3)

`restore.three_way` is always present in the plan: one row `{key, before, after, now}` per value of the record that is not equal on the three sides (`now` = what
the file has now; for a clean restore `now == after`, so the page can show it as "the value that will be replaced").

`machine.history.restore` is refused with `error.code = "conflict"`, `error.reason = "file_changed"` and `error.three_way`, `error.files` when a file the
record wrote is neither as the record left it (`sha_after`) nor as it found it (`sha_before`). Show the three-way table (and `machine.history.compare`),
and ask again with `accept_current: true`: the plan is made over the CURRENT file replacing only the values of the record. Other `reason`s:
`not_restorable`, `not_applied`, `no_value` (the line did not exist before: there is no `before`), `kind_mismatch`, `role` (403 with `needed_role`).
Restorable: `config.m671`, `config.g31`, `config.m208`, `config.m92`, `config.g10`, `config.workplaces` and `offsets.snapshot` (becomes a
`config.workplaces` plan). Not restorable: `config.bed` (use the configuration history snapshot), runs.

## Plan kinds added to `machine.config.plan` (values)

| kind | values | role | effect without `apply_now` | with `apply_now` (volatile lines sent after the file is written) |
|---|---|---|---|---|
| `config.g31` | `{k?: 0-15 (0), p?: 0-1023, x?, y?, z?}` at least one of p x y z | technician | edits the `G31 K..` line (or adds it after the `M558` of that probe; warning `new_line_resets_defaults`) | `G31 K P X Y Z` only when the resulting line has all four |
| `config.m208` | `{axes: {"X": {min, max}}}` | ADMIN | edits `M208` per axis (the last line that has the axis) | `M208 X<min>:<max>` per axis |
| `config.m92` | `{axes: {"X": steps_per_mm}}` (letters X Y Z U V W A B C and E for the extruder) | ADMIN | edits `M92` per axis; warning `big_change` when the ratio is outside 0.5-2 | `M92 X..` per axis |
| `config.g10` | `{tool: 0-49, offsets: {"X": v, "Y": v, "Z": v}}` | technician | edits `G10 L1 P<tool>` (adds it after the `M563` of the tool) | `G10 L1 P<tool> X..` per axis |
| `config.workplaces` | `{systems: {"1": {"X": v}}, target?: "macro" (default) or "config"}` | technician | `macro`: writes the G10 L2 lines into `0:/sys/workshop-offsets.g` and makes sure config.g calls it (`M98 P"workshop-offsets.g"`, before an `M501` line if there is one); `config` edits the file that already has the lines. `M500` is NOT used | `G10 L2 P<n> X..` per axis |

Warnings (codes) in `plan.warnings`: `several_definitions`, `defined_in_several_files`, `nothing_changes`, `no_anchor`, `no_m558`, `no_m558_for_probe`,
`multi_driver_value`, `also_in_config`, `config_calls_macro`, `big_change`, `new_line_resets_defaults`. Plan errors (`error.reason`):
`bad_value` (+`field`), `no_config`, `not_utf8`, `patch_expression` (the token is an expression `X{...}`: not replaced), `patch_unsupported_form`
(M208 with `S`), `patch_bad_axis`. `apply` answers `restart_needed: true` for all of them (the file is read at the next start; `apply_now` makes it valid at once).

## Run kinds added to `machine.run`

### `safety.check` (read only; no reservation, no connection, works during a job; params: none)
Result and record: 
```
{generated_at, verdict: "ok" | "warn" | "bad",
 counts: {ok, info, warn, bad, unavailable},
 items: [{id, severity: "ok"|"info"|"warn"|"bad"|"unavailable", action: key | null, values: {...}}]}
```
Item ids (in order): `kinematics`, `homed`, `z_motors`, `probe`, `probe_offsets`, `reach`, `endstops`, `heaters`, `sensors`, `status`, `reset_reason`, `supply`,
`job`, `interlocks`, `config_guard`. `reset_reason` is always `unavailable` (`values.reason = "no_verified_key"`: the object model has no key).
Action keys: `home_axes`, `open_levelling`, `check_probe`, `check_probe_offsets`, `check_limits`, `check_endstops`, `see_heaters`, `see_sensors`, `reset_board`,
`fix_startup_error`, `check_supply`, `close_interlocks`, `declare_interlocks`, `check_config_guard`, `kinematics_unsupported`. `values` per item is small numbers/codes
(for example `homed.axes`, `heaters.fault`, `supply.vin/min/max`, `probe.value/trigger_height`, `z_motors.z_motors/m671_entries/mode`).
The record stores `{outcome: verdict, counts, attention: [ids with warn or bad]}`.

### `homing.verify` (HOMES the axes: class sequence, `confirm` required, reservation, stop honoured between axes)
Params `{axes?: ["X","Y","Z"] (default: visible X, Y, Z with an endstop), tolerance?: 0.001-2 (0.05)}`. Refusals `reason`: `no_endstops`, `bad_axis`, plus the generic ones
(`unsupported_kinematics`, `heater_fault`, `busy_run`...; it does not need a probe nor homed axes). Result (and record, shortened):
```
{outcome: "ok" | "warn" | "failed", tolerance, axes: [{axis, index, endstop: {type, high_end, probe}, home_at: "min"|"max", declared: mm,
  before: {triggered, position, homed}, after: {triggered, position, homed}, delta: mm or null,
  checks: {endstop_present, not_pressed_before, position_matches, triggered_after}  (true/false/null), ok}]}
```
A homing macro that backs off after touching the endstop leaves `delta` != 0 (reported as warn, not hidden). Homing repeatability and the real travel check are NOT here (phase 3).
Errors in `run.error.code`: `homing_failed` (+detail), `stop`, `machine_halted`, `reservation_lost`.

## Report data (`machine.report`)
```
{schema: 1, kind: "calibration" | "machine", generated_at, generated_by, machine: {name, board, firmware, kinematics, axes_fingerprint}}
calibration: + record: {id, kind, ts, user, role, state, run_id, notes}, tables: [{id: "inputs"|"results", rows: [{key, value}]}],
   applied: [{path, sha_before, sha_after, snapshot_id}] or null, mesh: MeshFigure or null, level: LevelFigure or null, signature: {person, date}
machine: + records: [{record, tables, mesh, level}] (newest good record of every kind except snapshots and safety checks), limits (= machine.limits.get),
   offsets (= tools/work/current), compensation: {type, file, fade_height}, safety (= safety.check result, fresh), signature: {person, date}
MeshFigure {id, axes, grid, rows: [[z or null]], stats, scale: {min, max, symmetric}}      rows[j][i]: axis1 index j, axis0 index i
LevelFigure {tolerance, passes: [{n, before, after}], residual: mm or null, light: "ok"|"warn"|null}
```
The service draws no SVG: the plugin draws the mesh colour map and the level residual from these numbers.

## Other changes a client may notice
- `capabilities.get`: `tool_offsets.items[].probed` is now the list of axis indexes of the `offsetsProbed` BITMAP (before, a real board value crashed the discovery);
  `workplaces.current` falls back to `move.motionSystems[0].workplaceNumber` (0-based) when the obsolete `move.workplaceNumber` is missing.
- `machine.run` kinds `safety.check` / `homing.verify` appear in `machine.runs`, `machine.state.procedures` and the published `machine` data like the others.
- `main.py` starts `machine_try.recover_pending` once (a thread) so a pending volatile M208 trial is put back after a restart.

## Unverified (no real capture exists)
- Replies of `G28 <axis>`, `M409 K"sensors.endstops"`, `M208`, `M92`, `G31`, `G10` to the new lines: assumed from the reference; errors are detected by the tolerant `find_errors`.
- `M208 X..:..` sent alone as a volatile trial: its reply and whether the firmware refuses limits narrower than the current position are not documented.
- The laser S scale (`power% * 2.55`, `M452 R255` of the workshop machine) and the 4 mm cross feed (300 mm/min) come from the old `lasermark.g`.
- The supply voltage window (11-29 V) and "endstop triggered more than 1 mm from its end" of the safety check are guesses.
- No fixture of a real machine was added; tests build their models from the existing invented fixtures.
