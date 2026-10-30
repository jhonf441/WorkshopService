# Machine v2 phase 4: contract for the plugin (service side)

Branch `m4-service`. Everything here is called through `POST /machine/WorkshopService/api` `{op, args}` (see `docs/api/README.md`).
Answers are `{ok, op, result}` or `{ok:false, error:{code, message, reason?, field?, ...}}`. Texts the service builds (phone notices, error
messages) follow the request language, or DWC's language outside a request (`messages.machine_language()`); everything else is codes and
numbers (the plugin translates them). Same conventions as `docs/MACHINE-PHASE3-CONTRACT.md`.
Nothing here was run against a real board or a real Vision: see "Unverified" at the end.

Roles: `viewer < operator < technician < admin`.

| op | role | kind | args | result |
|---|---|---|---|---|
| `machine.maintenance.get` | operator | read | none | Maintenance (below) |
| `machine.maintenance.done` | technician | write (audited) | `id`, `note?` | `{id, done, item}` |
| `machine.maintenance.plan.set` | technician | write (audited) | `items?`, `notify?`, `defaults?` | `{items, notify, plan_empty}` |
| `machine.run` kind `offsets.verify` | technician | motion (sequence), level 3 confirm | see "Camera verification" | run, see `machine.runs` |

`machine.state` gains `vision: {measure: bool, checked_at}` (see "Camera verification"). `machine.overview` gains `maintenance` (the light).

## Maintenance counters

The board keeps no odometer. The service integrates, with ONE subscription (`machine_state`, no polling of `/machine/status`), per axis
letter and for the machine as a whole:

- `power_on_h`: hours the machine was powered (`state.status` not off / disconnected / starting / updating) and, for an axis, the axis was
  not released (`motor_poller.released()`, known while the Motors plugin runs; otherwise every powered hour counts).
- `moving_h`: hours the axis `machinePosition` changed (above 0.002 mm between two samples); the board entry counts any axis moving.
- `distance_m`: ESTIMATED distance, the integral of the sampled `machinePosition` (per axis letter, not per motor: on CoreXY the motors move
  differently). Always an underestimate when the head reverses faster than the sampling; the answer carries `estimated: true`.

Rules: a gap between two samples above 10 s (service down, subscription lost) counts NOTHING and creates no jump (`gaps` goes up); a
sample pair where `homed` changed (homing or unhoming rewrites the position) is not counted; an implied speed above 2000 mm/s is ignored
(`jumps`). Values are written to the store `machine-maintenance` every 5 minutes (atomic write; a power cut loses at most that) and when the module rests; the module rests when the plugin
WorkshopMachine is stopped (like the other modules). `crosscheck` compares the XY path length the service integrated during the last
file job with the path length that `gcode_plan` computes from the file (`ratio` = estimated / planned; a ratio far below 1 is the
sampling underestimate, far above 1 is noise or a wrong file).

## `machine.maintenance.get` (operator)

```
{schema: 1, generated_at: epoch s,
 counters: {running: bool, estimated: true, since: epoch|null, updated: epoch|null, gaps: n, jumps: n,
            board: {power_on_h, moving_h, distance_m},
            axes: {"X": {power_on_h, moving_h, distance_m}, ...},
            crosscheck: {job, estimated_mm, planned_mm, ratio, ts} | null},
 items: [Item], custom: bool,
 notify: {enabled: bool},
 summary: {worst: "ok"|"due_soon"|"due"|"overdue", due_soon: n, due: n, overdue: n}}

Item = {id, label, label_key: key|null, axis: letter|null,
        interval: {unit: "hours"|"km"|"days", value, basis: "power_on"|"moving"|null},
        used, remaining, ratio, status: "ok"|"due_soon"|"due"|"overdue",
        last_done: {ts, user, role}|null}
```

`custom` is true when the plan is the owner's (the profile list is not empty, or the owner saved the plan: an empty plan saved on purpose stays
empty); false while the generic defaults are the plan. `label` is the owner's text; when it is empty and the id is one of the defaults, `label_key` is a catalog key
(`machine_maint_item_<id>`) that the plugin translates. `used` and `remaining` are in the unit of the interval (`remaining` is negative
when over). `ratio = used / value`. Status: `due_soon` from 0.9, `due` from 1.0, `overdue` from 1.25 (guesses, constants of
`machine_maintenance.py`). An item with `axis: null` counts the whole machine (board counters; its distance is the sum over the axes).
`days` count from the last `done` (or from `counters.since` when it was never done). `hours` use `basis` `power_on` unless the item says
`hours_basis: "moving"`. The defaults (generic, the owner edits them): `z_screws` (Z, every 100 power-on hours), `belts` (machine, every 200
moving hours), `lens` (every 30 days), `z_couplers` (Z, every 180 days).

## `machine.maintenance.done` (technician)

Args `{id: str, note?: str up to 200}`. Records who and when (audit row `machine.maintenance.done` with the user, role and device) and resets
the item: the counters at that moment become the new base. Result `{id, done: {ts, user, role}, item: Item}`.
Errors: `invalid_args` (HTTP 422) with `field: "id"` when the item is not in the plan.

## `machine.maintenance.plan.set` (technician)

Role justification: the plan only drives reminders; it moves nothing and writes no configuration of the board (`profile.set`, which stays admin,
is the door for everything that does). The change is audited with the previous and new item ids. Args (all optional, at least one):

- `items`: the WHOLE plan, `[{id, label, axis, every_hours | every_km | every_days, hours_basis?}]` (ids `[a-z][a-z0-9_.-]{0,39}`, up to 40
  items, exactly one interval each, `axis` null or a letter). It goes through the profile validator (`machine.maintenance` of `machine.json`).
- `defaults: true`: empties the profile list and goes back to the generic defaults (`custom: false`); not together with `items`.
- `notify: bool`: opt-in phone notice when an item becomes `due` (and once more when it becomes `overdue`).

Result `{items: [Item], notify: {enabled}, custom, summary}`. Errors: `invalid_args` (HTTP 422) with `field` (`machine.maintenance[3]`) and the validator's message, `errors: [{field, message}]` for all problems found; also `invalid_args` for a call with none of the three arguments.

Notifications: when an item reaches `due` or `overdue` (checked at each save of the counters, every 5 minutes, and after `plan.set`) one notice goes through the
notifier (type `maintenance`, the destination and quiet hours of the Activity page apply) and one activity row, in
`messages.machine_language()`. The same level is never repeated for an item until it is done again.

## Camera verification (Vision capability `vision.measure`)

Vision does NOT expose a measure operation today and this phase does not change it. The service asks for the capability and uses it
when present.

### What Vision must provide (contract, version 1)

1. **Announce it.** `GET /state` returns `"capabilities": ["measure"]` (any other entries are ignored). The service reads it through the
   existing call path (`vision.get` `/state`) with a 2 s timeout, caches the answer for 30 s, and treats an old Vision (no `capabilities`)
   or a Vision that is off as "absent": `vision.measure` is false and every use is refused with reason `no_vision_measure`.
2. **Measure.** `POST /measure` (the service adds the path to its allowed Vision paths; by role it is an operator's path like `/detect`
   because it only LOOKS: it takes a photo and analyses it, it never moves the machine and never fires the laser).

Request:
```
{"schema": 1, "what": "crosshair" | "mark",
 "near": {"x": mm, "y": mm},      // where the mark should be, bed (machine) coordinates; the search is limited to radius_mm around it
 "radius_mm": 15,                 // 2-60
 "fresh": true,                   // take a new photo (do not reuse the last one)
 "camera": "main"}                // optional
```
`what: "crosshair"` = the pointer / crosshair / tool tip of the head; `what: "mark"` = a mark on the bed (laser burn, pen).

Answer (always JSON, HTTP 200 also for "not found"):
```
{"ok": true, "schema": 1, "found": true,
 "x": mm, "y": mm,                // centre of what was found, MACHINE coordinates (the frame of machinePosition X / Y, no work offset)
 "sigma_mm": 0.08,                // one standard deviation of the position (calibration residual + detection), required
 "confidence": 0.0-1.0,
 "frame_ts": epoch s,             // when the photo was taken
 "calibration": {"id": str, "age_days": n, "rms_mm": mm}}
{"ok": true, "schema": 1, "found": false, "reason": "no_mark" | "ambiguous" | "out_of_view" | "not_calibrated" | "blurry"}
{"ok": false, "error": "..."}     // Vision's usual error
```
The service refuses an answer without `sigma_mm`, with a position outside the bed, or with a `frame_ts` older than 30 s, as `vision_bad_answer`.

### Run kind `offsets.verify` (`machine.run`)

Needs XY homed, the movement reservation and the level 3 confirmation. It moves the head to a point, asks Vision where the head or the
mark is, and compares. Params:

| param | values | default |
|---|---|---|
| `target` | `"system"` or `"tool"` | `"system"` |
| `system` | 1-9 (G54 = 1): `target: "system"`; the head reference goes to the offsets of that system with `G53` | the system selected now |
| `tool` | number of the ACTIVE tool, `target: "tool"`; the run never changes tool (`tool_not_current`) | the active tool |
| `method` | `"crosshair"` (no laser), `"laser"` (a 4 mm cross, <= 10 %, Laser mode, interlocks, like `machine.mark_cross`), `"pen"` (the pen is on the head; the person marked it; no laser) | `"crosshair"` |
| `power` | 1-10 (%), `method: "laser"` | 3 |
| `samples` | 1-5 measurements | 3 |
| `tolerance` | 0.05-5 mm | 0.5 |
| `feed` | 600-12000 mm/min | 3000 |
| `settle_s` | 0-5 s wait after the move before the photo | 1 |

- `target: "system"`: the expected point is the work origin of the system (`machine.offsets.get` `work[n].offsets` X and Y); the head
  reference goes there with `G53 G1 X.. Y..`. It checks that the stored offset points to the place the camera sees.
- `target: "tool"`: the head goes to `G1 X0 Y0` in the current system with the active tool; the firmware applies the tool offset, so the TIP lands at the work
  origin of the current system when the tool offset is right. The expected point is that work origin.

Refusal reasons (`error.reason` of `machine.run`): `no_vision_measure`, `not_homed`, `bad_target`, `tool_not_current`, `out_of_reach`
(the point is outside the M208 limits of X / Y) and, for the laser, those of `machine.mark_cross` (`bad_power`, `not_laser_mode`,
`no_laser`, `interlock_open`), plus the generic ones (`busy_run`, `no_model`, `unsupported_kinematics`, `heater_fault`).
Run errors (`error.code` of the run): `vision_unavailable`, `vision_not_found` (Vision answered `found: false`; the Vision reason is in the result), `vision_bad_answer`.

Result of the run (and the history record, kind `offsets.verify`):
```
{outcome: "ok" | "out" | "inconclusive",
 target: {kind: "system", system: n} | {kind: "tool", tool: n}, method,
 expected: {x, y}, reached: {x, y},        // reached = machinePosition read back after the move
 measured: {x, y, sigma_mm, n, spread_mm}, // mean of the samples; sigma_mm combines Vision's sigma and the spread
 error: {dx, dy, dist},                    // measured - expected, mm
 tolerance, uncertainty_mm,                // uncertainty = 2 * sigma
 samples: [{x, y, sigma_mm, confidence}],
 vision: {calibration: {...}|null}}
```
`outcome`: `ok` when `dist + uncertainty <= tolerance`, `out` when `dist - uncertainty > tolerance`, `inconclusive` otherwise (the camera is not
precise enough to decide: improve the calibration or raise the tolerance). The run ends `done` in all three cases; `error` only when the
procedure could not measure.

## Unverified

- Vision's real `/state` and `/measure` do not exist: everything above is the contract the service needs, tested with a mocked Vision.
- `G53 G1 X.. Y..` in the firmware (the modifier form of G53) and that `G53` ignores the tool offset.
- The sampling rate of the model patches while moving (decides how much the estimated distance underestimates).
- The sign and size of `crosscheck.ratio` on a real job.
