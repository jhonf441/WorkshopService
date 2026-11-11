# What the service does today when it does not know

Phase 0 of the redesign plan (architect's report, section 1.5 / D-17 / 2.5). This is a description of the code as it is, read
line by line; nothing here was changed. The target is one table in code (`unknown_policy`, L3) that these rows move into; until
then the decisions live scattered in comments, so this page is the only place that lists them together. Line numbers are of the
commit this page was written on: if a row looks wrong, trust the code and fix the page.

"Unknown" means one of: no object model yet (`machine_state` has nothing), the model has no `state.machineMode`, the status is
missing, the bridge never sent anything (`None`), or the service does not answer (bridge side).

Two ways of reading the mode exist and they disagree on purpose or by accident:

- `real_mode.pick` (`dsf/real_mode.py:12-18`): `state.machineMode` if it is FFF / Laser / CNC, else `global.selectedMode` if it is
  one of them, else whatever either holds, else `None`. Used by `api_ops.current_mode()` (`dsf/api_ops.py:1131-1139`, lower case,
  `None` on any exception), by the activity history, the trace, the status LEDs and the Machine pages.
- `state.machineMode` alone, with no fallback: the laser guard (`dsf/main.py:437`), `guard_probes.job_context` (`dsf/guard_probes.py:86-94`),
  `jog_move` (`dsf/jog_move.py:419,1876`), `machine_cross` (`dsf/machine_cross.py:58`), `camera_image` (`dsf/camera_image.py:124`).

## The table

"Opens" = the protected thing is allowed when the input is unknown (fail open). "Closes" = refused (fail closed).

| Decision | Unknown input | Today | Where |
|---|---|---|---|
| Laser interlocks (lid, extraction, key) refuse `job.start`, `frame.start` (laser mode), live job resume | mode unknown or not laser | Opens: no refusal | `dsf/interlocks.py:105-110` (`current_mode() != "laser"` returns `None`) |
| same | an exception while reading the profile or the model | Opens: "reading problems must not close the machine for the pages; the firmware is the real protection" | `dsf/interlocks.py:111-114` |
| same | a DECLARED interlock whose input is not in the model (`sensors.gpIn[pin]` missing or no value) | Closes: state `unknown` counts as not ok, laser mode refuses with `interlock_open` | `dsf/interlocks.py:41-50,62-67,70-76` |
| same | no interlock declared in the profile | Opens: `declared false, ok true` | `dsf/interlocks.py:93-96,137-139` |
| Laser guard (turns off a power left set, sends `M5`) | `state.machineMode` is not exactly `"Laser"` (unknown mode, model missing, `selectedMode` ignored) | The guard does nothing: it only beats its heartbeat | `dsf/main.py:435-438` |
| same | the bridge never sent an order (`bridge_quiet_s` is `None`) | Counts as quiet: the guard may send `M5` after `HOLD_S` idle seconds | `dsf/laser_guard.py:47` |
| same | `state.status` or `laserPwm` unknown | `status != "idle"` holds the guard (no `M5`); an unknown `laserPwm` does not arm it | `dsf/laser_guard.py:48-50`, `dsf/main.py:441-442` |
| same | an exception in the loop | Logs, sleeps 4 s, keeps looping; a failed `M5` re-arms for the next pass | `dsf/main.py:451-457` |
| Protection guard (alarm when a safety process dies) | mode not Laser / CNC, or no model | `active` false: a dead process is not treated as critical, the laser interlock alarm is not raised | `dsf/guard_probes.py:94`, `dsf/protection_guard.py:152,241-242` |
| Jog, S0 on every G1 | mode unknown (cache has no `machineMode`) | Opens the other way: NO `S0` is sent. S0 is added only when the mode is exactly `"Laser"` (finding D-26) | `dsf/jog_move.py:1876-1877` |
| Jog, start of the no-limits mode | status unknown | Closes: `None not in SAFE_STATUSES` refuses to enter | `dsf/jog_move.py:1040-1042` |
| Jog, leaving the no-limits mode on a job | status unknown | Opens: it stays in the mode (`status is not None and ...`) | `dsf/jog_move.py:1544-1545` |
| Owner of the movement (`motion_owner`) | status unknown (`None`) | Opens: not in `STOPPED`, not in the file-job states, so state `free` and every class allowed | `dsf/motion_owner.py:105-119,210-216,289,316` |
| same | bridge activity unknown (`None`) | Opens: not "bridge_active" | `dsf/motion_owner.py:138-143,229` |
| same | the import or the read of the jog cache / `jog_move` raises | Opens: status `None`, bridge age `None`, clients 0 | `dsf/motion_owner.py:105-119,122-153` |
| Operator limited to some modes: `jog.*`, `frame.start`, `motion.reserve`, `job.start` | machine mode unknown | Closes for that operator: `mode_unknown`. Only when the operator is restricted to fewer than the three modes; technician and admin are never gated | `dsf/permissions.py:246-253` (custom roles `:308-314`) |
| Role of an operation that nobody classified | operation not in `OP_ROLES` | Closes: needs admin | `dsf/permissions.py:201-204` |
| Permission decision on arguments | the argument is missing (`machine.config.apply`, `machine.try`) | Closes: needs the higher role (`when_missing`) | `dsf/permissions.py:65-69` |
| Bridge machine gate (`block_when_unfit`) | service does not answer, status `None`, or the last answer is older than 10 s | Opens: "the gate never blocks by guessing" | `bridge/gcode_bridge.py:357-361,390-398`; the loop sets `status = None` on any exception at `:377-378` |
| same | `needs_homing` when the service does not answer | Opens: `False` | `bridge/gcode_bridge.py:384-385` |
| Preview of a file (`jobs.preview`) | mode unknown and none given | Assumes Laser | `dsf/jobs_preview.py:128-130` |
| Status LEDs (mode colour) | mode unknown | Assumes FFF | `dsf/lights_decide.py:584` |
| Laser section of the LEDs | mode not Laser and no `laserPwm` | Not shown | `dsf/lights_board.py:353` |
| Heaters with a disconnected sensor (about -273 C) | mode unknown | Shown as a fault (only hidden in Laser / CNC) | `dsf/lights_board.py:335-336` |
| `machine.mark_cross` (laser point) | model missing / mode not Laser | Closes: `no_model` / `not_laser_mode` | `dsf/machine_cross.py:54-59` |
| Height calibration, work area | mode not FFF / Laser / CNC | `None` (no mode-specific proposal) | `dsf/machine_height.py:235-236`, `dsf/machine_workarea.py:165-166` |
| Camera exposure for laser cutting | no model yet | `False`: "the machine is not doing anything we know of" | `dsf/camera_image.py:117-124` |

## Things this table shows

These are findings, not changes; each is a decision for the owner when the machine is present (the plan puts them in phases 4 and 6):

1. The same question "is it laser mode?" has three answers: `real_mode.pick` (falls back to `selectedMode`), the exact
   `machineMode == "Laser"` of the guard and the jog, and `api_ops.current_mode()` (lower case, `None` on error). With the model
   missing or `machineMode` empty and `selectedMode` saying Laser, the interlocks refuse, the guard sleeps and the jog sends no `S0`.
2. The laser guard and the S0 of the jog fail open on an unknown mode (D-26 of the report: "S0 unless the mode is known and not laser").
3. `None` for the bridge counts as "quiet" in the guard and as "free" in the owner of the movement.
4. The two fail-open cases the report lists (D-17) are the bridge gate (`bridge/gcode_bridge.py:394-395`) and `laser_guard.py:47`.
5. The only deliberate fail-closed choices are: an interlock input that is not readable, an unclassified operation, a missing
   argument that escalates, a restricted operator in an unknown mode, and the jog entering the no-limits mode.
