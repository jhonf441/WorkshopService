# Machine v2 phase 3: contract for the plugin (service side)

Branch `m3-service`. Everything here is called through `POST /machine/WorkshopService/api` `{op, args}` (see `docs/api/README.md`).
Answers are `{ok, op, result}` or `{ok:false, error:{code, message, reason?, field?, ...}}`. Texts the service builds are Spanish/English by
the request language; everything else is codes and numbers (the plugin translates them). Same conventions as `docs/MACHINE-PHASE2-CONTRACT.md`.
Nothing here was run against a real board: see "Unverified" at the end. The accelerometer path is behind a capability and the owner
is NOT assumed to have one.

Roles: `viewer < operator < technician < admin`. Administrator kinds (Q1 of the design): `config.m208`, `config.m92`, `config.m906`,
`config.m913`, `config.m917`, `config.m569`, `config.m584` (plan/apply) and the `machine.try` kinds `M208`, `M92`, `M906`, `M913`, `M917`.
Everything else of this phase is the technician's. The rule is fail closed: `machine.config.apply` and `machine.try` called WITHOUT `kind`
/ `gcode_kind` also need admin (a technician gets 403 `needed_role: "admin"`). `permissions.table_for_client()` publishes it (`escalate_in`, with `when_missing`).

## Operations

| op | role | kind | args | result |
|---|---|---|---|---|
| `machine.calc` | technician | write (audited; `save` stores a record) | `calc` ("steps" "skew" "backlash" "ringing"), `values` (below), `save?` bool, `note?` | below |
| `machine.motion.get` | operator | read | none | `{axes: [Row], extruders: [Row], idle, backlash_factor, skew, limits, config_read}` |
| `machine.shaping.get` | operator | read | none | `{available, current, types, min_frequency_hz, accelerometer, definitions, warnings}` |
| `machine.shaping.test` | technician | read (text only, NEVER sent to the board) | `axes?` ("X" "Y" "XY", default "XY"), `origin_x?`, `origin_y?`, `size?` mm 10-200 (50), `feed?` mm/min 600-30000 (6000), `accels?` [mm/s2] 1-6 values 50-20000 (500,1000,2000), `repeats?` 1-5 (2) | `{gcode, lines, params, notes: [code]}` |
| `machine.try` | technician (admin by `gcode_kind`) | motion (geometry), level 3 confirm | `gcode_kind`, `action?`, `values`, `seconds?` 5-600 (60), `try_id?` | below |
| `machine.config.plan` / `apply` | technician (admin by `kind`) | see phase 1 | new kinds below | phase 1 Plan |
| `machine.run` | technician | | new kind `shaping.tune` | `{run_id, kind, state}` |

### `machine.calc` (pure arithmetic; nothing is sent to the board)

All results carry `calc`, `warnings: [code]`, `plan: {kind, values}` (feed it to `machine.config.plan` unchanged) and `record_id` (null unless `save: true`).
Errors: `invalid_args` + `reason: "bad_value"` + `field`; `refused` + `reason` in `out_of_range` (the ratio of the correction is outside 0.5-2),
`implausible` (a skew above 3 degrees or a diagonal that cannot belong to the square), `no_value`.

- `calc: "steps"`, `values: {axis: "X".."C" | "E", commanded: mm 1-5000, measured: mm > 0, old?: steps/mm}` (`old` defaults to `move.axes[].stepsPerMm`, extruder `E` = `move.extruders[0]`).
  Result `{axis, old, commanded, measured, ratio, new, change_pct, line: "M92 X80.4", plan: {kind: "config.m92", values: {axes: {"X": new}}}}`.
  `new = old * commanded / measured` rounded to 3 places (the firmware keeps what the G-code writes). Warnings: `large_correction` (ratio outside 0.9-1.1), `microstepping_note` (always: M92 is microsteps/mm of the current M350).
- `calc: "skew"`, `values: {pair: "XY"|"YZ"|"ZX", side: mm 10-1000 (nominal side of the square), diag_sum: mm, diag_diff: mm}`.
  `diag_sum` = diagonal from the origin corner to the opposite corner (the X+Y direction), `diag_diff` = the other diagonal. With equal sides `sin(d) = (diag_diff^2 - diag_sum^2) / (4 side^2)`; positive = obtuse (the firmware convention). The deviation is `side * tan(d)`.
  Result `{pair, side, diag_sum, diag_diff, angle_deg, tan, deviation, letter: "X"|"Y"|"Z", line: "M556 S100 X0.35", plan: {kind: "config.m556", values: {s, x|y|z}}}`. XY -> `X`, YZ -> `Y`, ZX -> `Z`.
- `calc: "backlash"`, `values: {axis: "X".."C", samples: [lost motion in mm] 1-20 (each 0-2), multiplier?: 1-100}`.
  Result `{axis, n, mean, stdev, min, max, proposal (mean, 3 places), multiplier, line: "M425 X0.12 S10", plan: {kind: "config.m425", values: {axes: {"X": proposal}, multiplier?}}}`.
  Warnings (always `fixed_backlash_only`: M425 is for FIXED backlash, not belt stretch or flex): `inconsistent` (stdev above 35 % of the mean, or range above half of it), `big_backlash` (above 0.5 mm), `per_motor` (CoreXY or other: M425 is per MOTOR), `zero` (proposal 0), `not_in_g32` (always: M425 is not applied to levelling moves).
- `calc: "ringing"`, `values: {feed: mm/min, ripples: 2-200, distance: mm}` (ripples counted over `distance` on the test part).
  Result `{frequency_hz, wavelength_mm, speed_mm_s, plan: {kind: "config.m593", values: {frequency: hz}}}` (the shaper `type` is not guessed: the plugin chooses it). Warnings: `below_minimum` (under 4 Hz), `very_high` (over 200 Hz).

### `machine.motion.get`

`Row = {kind: "axis"|"extruder", index, letter ("E" for the extruder 0, "E1"...), drivers: ["0.0"], steps_per_mm, microstepping, interpolated, current_ma,
current_percent (M913), standstill_percent (M917), speed (mm/min), acceleration (mm/s2), jerk (mm/min, M566), printing_jerk (mm/s, M205), backlash (mm, axes only),
driver_mode: "spreadcycle"|"stealthchop"|"other"|null, driver_mode_source: "config"|"default"|null, direction: 0|1|null, unavailable: [field]}`.
A field the board did not report is `null` and listed in `unavailable`; nothing is invented. `driver_mode` is not in the object model: it comes from the
`M569 P.. D..` lines of config.g and the macros it calls (`"default"` = no `D` there, so the 3.4+ firmware default spreadCycle).
`idle = {percent (M906 I, move.idle.factor*100), timeout_s (M906 T)}`, `skew = {tan_xy, tan_yz, tan_xz}`, `limits = {max_current_ma: profile cap, ceiling_ma: 6300}`.

### `machine.shaping.get`

`available` (the firmware reports `move.shaping`), `current = {type, frequency, damping, amplitudes, delays, min_acceleration}` (keys the board did not give are null),
`types` = `["none","zvd","zvdd","zvddd","mzv","ei2","ei3"]` (settable; `custom` is shown but not edited), `min_frequency_hz` 4,
`accelerometer = {present, source: "discovered"|"declared"|"default", count, items: [{index, orientation, points, runs, sampling_rate, resolution}]}`,
`definitions = [{file, line, text}]` (M593 lines of the configuration), `warnings` (`retune_pressure_advance` when a shaper is active, `custom_shaper` when `type` is `custom`).

### `machine.try` generalised

`gcode_kind` is one of `M208 M92 M906 M913 M917 M593 M425 M556 M203 M201 M205 M566`; `M376` still answers `not_implemented`.
`values` per kind (the same shape as the `values` of the plan of the same kind, except M208 which keeps `{axes:{"X":{min,max}}}`):

| gcode_kind | values | sent (volatile) | previous read from |
|---|---|---|---|
| M92 | `{axes:{"X": steps/mm}}` (X Y Z U V W A B C, E) | `M92 X..` | `move.axes[].stepsPerMm`, `move.extruders[0]` |
| M906 | `{axes?:{"X": mA}, idle_percent?: 0-100, idle_timeout?: 1-3600}` | `M906 X..`, `M906 I..`, `M906 T..` | `current`, `move.idle.factor/timeout` |
| M913 / M917 | `{axes:{"X": 0-100}}` | `M400` then `M913 X..` / `M917 X..` | `percentCurrent` / `percentStstCurrent` |
| M203 / M201 / M205 / M566 | `{axes:{"X": v}}` | `M203 X..` (mm/min), `M201` (mm/s2), `M205` (jerk mm/s, job), `M566` (jerk mm/min) | `speed`, `acceleration`, `printingJerk`, `jerk` |
| M425 | `{axes:{"X": mm 0-2}, multiplier?}` | `M425 X..`, `M425 S..` | `backlash`, `move.backlashFactor` |
| M556 | `{s: 1-1000, x?, y?, z?}` (deviation in mm; `|dev| <= 0.1*s`) | `M556 S1 X<tan> Y<tan> Z<tan>` (factors, always the three) | `move.compensation.skew.tanXY/tanYZ/tanXZ` |
| M593 | `{type, frequency?, damping?}` | `M593 P"zvd" F43.5 S0.1` / `M593 P"none"` | `move.shaping` (a `custom` shaper cannot be put back: `no_previous`) |

Result of `start` / `keep` / `revert` as in phase 2 (`try_id, gcode_kind, previous, applied, ts, seconds, expires_at, user, action`), and `keep` adds
`persist: {kind: "config.m906", values}` (what `machine.config.plan` takes to make the trial permanent). Reasons: `try_pending`, `busy_run`, `no_previous`,
`board_error`, `not_found`, `revert_failed`, `bad_value` (+`field`), `current_over_limit` (+`axis`, `limit_ma`, `ceiling_ma`), `job_running`.
`start` fails with HTTP 400 `refused` for every reason above except `bad_value` (422 `invalid_args`) and `board_error` / `revert_failed` (424 `failed`). The service reverts when the time is over even if the page was closed; the trial is written to `try-pending.json` BEFORE it is sent; after a restart of the
service `recover_pending` puts everything back as its first act, and a revert the board did not accept is retried every 10 s (6 times) and then kept pending.
M906 current: every axis value must be `<= machine.safety.max_current_ma` of the profile (default 2800 mA; `profile.set` is admin) and never above the hard ceiling 6300 mA.
It also applies to the `config.m906` plan.

## Plan kinds added to `machine.config.plan` (values)

| kind | values | role | line edited | now (with `apply_now`) |
|---|---|---|---|---|
| `config.m556` | `{s?, x?, y?, z?}` | technician | `M556 S.. X.. Y.. Z..`; `s` is required when the line does not exist | `M556 S1 X Y Z` (factors) |
| `config.m425` | `{axes:{"X": mm}, multiplier?}` | technician | `M425 X.. S..` | `M425 X..` |
| `config.m593` | `{type, frequency?, damping?}` (`frequency` required unless `type` is `none`) | technician | `M593 P".." F.. S..` | `M593 ...` |
| `config.m906` | `{axes?:{"X": mA}, idle_percent?, idle_timeout?}` | ADMIN | `M906 X.. I.. T..` | `M906 ...` |
| `config.m913` / `config.m917` | `{axes:{"X": 0-100}}` | ADMIN | `M913 X..` / `M917 X..` | `M400` + the line |
| `config.m203` / `config.m201` / `config.m205` / `config.m566` | `{axes:{"X": v}}` | technician | `M203 X..` etc. (a `M203` with `S` is not rewritten: `patch_unsupported_form`) | the line |
| `config.m569` | `{drivers:{"0.0": {direction?: 0\|1, mode?: "spreadcycle"\|"stealthchop"}}}` | ADMIN | `M569 P0.0 S.. D..` (ONLY `S` and `D`; the line must exist: `patch_missing_line`; closed-loop `D4/D5` lines are not rewritten) | none (`restart_needed`) |

`before` / `after` have the same shape as `values` (null when the line did not exist), so `machine.history.restore` works for all of them (admin kinds need admin).
New plan errors (`error.reason`): `patch_missing_line`, `current_over_limit`, `bad_type`, `no_frequency`, plus the phase 2 ones. New warnings: `idle_zero_unhomes` (M906 I0), `custom_shaper_replaced`, `big_change` (ratio outside 0.5-2), `multi_driver_value`. A `config.m556` plan with no side `s` (neither given nor in the file), or a value above `0.1 * s` (also taken from the file), is `bad_value` with `field` `s` / `x` / `y` / `z`.
Record kinds written: `config.m556 config.m425 config.m593 config.m906 config.m913 config.m917 config.m203 config.m201 config.m205 config.m566 config.m569`,
`calc.steps calc.skew calc.backlash calc.ringing` (machine.calc with `save`), `shaping.tune`.

## Run kind `shaping.tune` (accelerometer; moves the axis; level 3 confirmation)

Params `{axis: "X"|"Y" (X), accelerometer: index (0), samples: 100-3000 (1000), travel: mm 10-150 (50), start?: mm (axis minimum + 20), feed: mm/min 600-30000 (6000), cycles: 1-10 (3)}`.
Refused with `reason: "no_accelerometer"` unless `capabilities.accelerometers.present` is true AND the object model lists that index (a profile that only DECLARES one
is not enough). Also `not_homed`, `out_of_reach` (start..start+travel outside M208 minus margin), plus the generic ones. Sends only: `M955 P<n>` (report, nothing configured),
`M956 P<n> S<samples> A0 <axis>`, `G90`, `G1 <axis>.. F.. S0` back and forth, `M400`. The service does NOT analyse the file.
Result `{outcome: "collected", axis, accelerometer, samples, folder: "0:/sys/accelerometer", moves, report: "<raw M955 reply>"}`.

## Capabilities

`capabilities.get`: `accelerometers` (already there) now gives `items[].sampling_rate` and `items[].resolution`; `input_shaping` unchanged.
With no `sensors.accelerometers` in the model `accelerometers.present` is false and no accelerometer operation does anything.

## Texts, audit, roles

All refusals/warnings are codes; the messages are in `dsf/i18n/{es,en}.json` (`machine_calc_*`, `machine_try_*`, `machine_shaping_*`, `machine_config_plan_*`, `machine_refuse_*`; `machine.motion.get` has no texts).
`machine.calc`, `machine.try`, `machine.config.apply`, `machine.run` write audit rows as the phase 2 ones; `machine.motion.get`, `machine.shaping.get` and `machine.shaping.test` are reads.

## Forbidden code (design 5.4, extended)

The closed list of `machine_gcode.py` has no template for `M569` at all (the plan edits the FILE), no `M955` other than the bare report, no `M956` without `A0`, and the second wall
(`FORBIDDEN`) refuses `M569.1`, `M569.2`, `M569.0`, `M918`, `M950`, `M112`, `M906.1`, `M915`... Tests walk every template of the list and a battery of bad lines.

## Unverified (no real capture exists)

- Replies of `M92`, `M906`, `M913`, `M917`, `M203`, `M201`, `M205`, `M566`, `M425`, `M556`, `M593` and `M955` to the lines above: assumed from the reference; errors are detected by the tolerant `find_errors`.
- Whether `M556 S1 X Y Z` replaces the three factors (and leaves `P` untouched), and whether `M593 P"none"` with no `F` is accepted: assumed.
- The skew formula uses the geometric definition of the angle error with the equal-sides approximation; the sign (positive = obtuse) follows the reference, the convention of which diagonal the vendor calls AC is not verified.
- `move.extruders[].percentCurrent / percentStstCurrent`, `move.shaping.minAcceleration / amplitudes / delays` and `sensors.accelerometers[].samplingRate / resolution` are read tolerantly; the exact key names for the extruders are not verified.
- Whether `M956 ... A0` blocks until the samples are taken or returns at once (the moves are sent after it; the order may need to change), and the format of the CSV (it is not read).
- The 6300 mA ceiling is the MB6HC rating from the documentation as remembered; the default 2800 mA cap of the profile is a guess.
- No fixture of a real machine was added; the tests use the invented fixtures marked `invented` in their `note`.

## Addendum: `machine.try.pending` (technician, read)
Answers `{pending: [{try_id, gcode_kind, previous, applied, ts, expires_at, user, seconds_left}]}`: the volatile trial waiting for its automatic revert, so a reloaded page (or another device) can keep or revert it.
