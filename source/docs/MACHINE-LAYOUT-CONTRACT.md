# Machine v2 bed view (service): contract of `machine.layout`

Branch `m6-service`. One read-only operation, called through `POST /machine/WorkshopService/api` `{op, args}` (see `docs/api/README.md`).
Answers are `{ok, op, result}` or `{ok:false, error:{code, message, reason?, field?}}`. Same conventions as `docs/MACHINE-PHASE4-CONTRACT.md`:
the service sends codes and numbers, the plugin translates them (reason keys below are the vocabulary; there are no texts in the answer).
Nothing here was run against the real machine: see "Unverified" at the end.

| op | role | kind | args | result |
|---|---|---|---|---|
| `machine.layout` | operator | read (no motion, no G-code, no reservation, not logged) | `mode`, optional `probe`, `x0 x1 y0 y1 nx ny`, `points`, `margin` | Layout (below) |

It reads the object model, `sys/config.g` (and the macros it calls) for M671, `sys/bed.g`, the machine profile, the mesh library and the calibration
history. It never sends anything to the board.

## Arguments

| arg | type | meaning |
|---|---|---|
| `mode` | `"mesh"` or `"level"`, required | which block of the answer is filled (`mesh` or `level`; the other is `null`) |
| `probe` | int 0..15, optional | probe index. Default: `machine.mesh.default_probe_index` (mesh) or `machine.probe.index` (both) of the profile, else the first real probe of the model |
| `x0 x1 y0 y1` | num, optional (all four or none) | mesh: the region the owner wants to probe, PROBE coordinates (where the probe touches). None: the whole reach minus the margin |
| `nx ny` | int 2..31, optional | mesh: grid size. Default: `machine.mesh.default_points` of the profile, else 5 x 5 |
| `points` | list of `{x, y}`, optional (1..32) | level: explicit probe points. Default: the profile's `levelling.probe_points`, else the numeric `G30` lines of bed.g, else one near each leadscrew (`suggested`) |
| `margin` | num 0..50, optional | distance kept from the edge of the reach. Default 5 mm for `mesh` (the same margin `mesh.probe` uses), 0 for `level` (the same rule `level.*` uses) |

Bad arguments answer `invalid_args` (`reason: "bad_value"`) with `field` (`region`, `nx`, `ny`, `points`).

## Coordinates and conventions

Machine coordinates in mm. A probe point `(x, y)` is where the PROBE touches; the head goes to `(x - offset_x, y - offset_y)` and has to stay inside the
axis limits (M208). A datum the machine does not tell is `null` and the block carries a `*_reason` key; nothing is invented. Geometry is the Cartesian
reasoning of `machine_geometry.py` (valid for the supported kinematics `cartesian`, `corexy`, `corexyu`, `corexyuv`, `corexz`: the XY head position is the
Cartesian one in the model); for other kinematics `kinematics.supported` is false and `reach`, `mesh.points` and `level.points` are `null`
(reason `unsupported_kinematics`).

## Layout

```
{
  "v": 1,
  "mode": "mesh" | "level",
  "generated_at": <epoch seconds, int>,
  "kinematics": {"name": str | null, "supported": bool | null},   // null = the model gives no kinematics name (geometry is still computed)
  "bed": {"x_min", "x_max", "y_min", "y_max"} | null,        "bed_reason": null | "no_limits",
  "probe": {"index": int, "type": int | null, "offset_x": num, "offset_y": num, "offset_z": null, "trigger_height": num | null} | null,
                                                              "probe_reason": null | "no_probe",
  "reach": {"x_min", "x_max", "y_min", "y_max"} | null,      "reach_reason": null | "no_limits" | "no_probe" | "empty_reach" | "unsupported_kinematics",
  "leadscrews": [{"index": int, "x": num, "y": num, "motor": str | int | null}],
                                                              "leadscrews_reason": null | "no_m671" | "m671_unreadable",
  "leadscrews_source": "model" | "config" | null,
  "mesh": Mesh | null,
  "level": Level | null,
  "last": {"mesh": LastMesh | null, "mesh_reason": null | "no_mesh",
           "level": LastLevel | null, "level_reason": null | "no_level"}
}
```

- `bed` = the axis limits of the object model (`move.axes[].min/max` of X and Y). It is the travel, not a measured bed: `bed_reason` says when X or Y limits are unknown.
- `probe.offset_x/offset_y` = `sensors.probes[k].offsets` (G31 X Y); a missing value counts as 0 like every other module. `offset_z` is always `null`:
  RRF has no Z offset of the probe other than the trigger height (`trigger_height`, G31 Z, `null` when the model does not give it). `probe` is
  `null` with `probe_reason: "no_probe"` when no real probe (type 0 is a manual probe and does not count) is there.
- `reach` = where the PROBE can be so that the head stays inside the limits AND the probe point is inside the travel:
  `x_min = max(xmin + offset_x, xmin)`, `x_max = min(xmax + offset_x, xmax)` (same for Y). Exactly `machine_geometry.reach` with margin 0.
  `null` when empty (`empty_reach`), or when the limits or the probe are unknown.
- `leadscrews`: from the M671 the model reports (`move.kinematics.tiltCorrection.screwX/screwY`, `leadscrews_source: "model"`), else from the last
  `M671` line of `config.g` and the macros it calls (`"config"`). `index` is the position in the M671 (0 based), which is the order of the Z drivers
  of M584. `motor` = the Z driver of that position (`"1.2"` style as the board names it) when the number of Z drivers equals the number of
  leadscrews, else `null`. Empty list with `leadscrews_reason`: `no_m671` (no M671 anywhere), `m671_unreadable` (the configuration could not be read, or
  the line gives X and Y lists of different length).

## Mesh (mode `mesh`)

```
{
  "region_source": "asked" | "default",
  "requested_region": {"x0","x1","y0","y1"} | null,          // the asked one, else reach minus margin (probe coordinates); null if unknown
  "margin": num,
  "grid": {"nx": int, "ny": int, "total": int, "source": "asked" | "profile" | "default"},
  "spacing": {"x": num, "y": num} | null,
  "points": [{"i": int, "j": int, "x": num, "y": num,
              "status": "in" | "out_of_reach" | "clipped" | null, "reason": str (absent when status is "in")}],
  "counts": {"in": n, "out_of_reach": n, "clipped": n, "unknown": n},
  "clipped_region": {"x0","x1","y0","y1"} | null,
  "clipped_reason": null | "out_of_reach" | "no_limits" | "no_probe" | "bad_region" | "unsupported_kinematics",
  "too_many_points": bool,                                   // grid larger than the profile's max_points_per_run or the firmware's 961
  "estimated_seconds": null, "estimate_reason": "no_estimate"
}
```

`points` are listed row by row (`j` along Y outer, `i` along X inner; index = `j * nx + i`), x from `x0` to `x1` in `nx` steps, y from `y0` to `y1` in `ny` steps.
Status and reason (first rule that applies):

| status | reason | meaning |
|---|---|---|
| `out_of_reach` | `outside_bed` | the probe point itself is outside the X/Y travel |
| `out_of_reach` | `head_outside_x`, `head_outside_y`, `head_outside_xy` | the point is on the bed but the head (point minus the probe offset) would leave the limits on that axis: the probe offset makes it unreachable |
| `clipped` | `inside_margin` | reachable, but closer than `margin` to the edge of the reach (the safety band `mesh.probe` keeps; a run over the requested region would be refused as `out_of_reach`) |
| `in` | (none) | would be probed |
| `null` | `no_limits`, `no_probe` or `unsupported_kinematics` | cannot be judged |

There is no data about clamps or fixtures in the machine (the profile has none), so no point is excluded for a clamp: `too_close_to_clamp` is NOT produced.
`clipped_region` = the requested region intersected with (reach minus margin), i.e. what `mesh.probe` would accept; `null` when the intersection is empty or
cannot be computed (`clipped_reason`). When the requested region is fully accepted, `clipped_region` equals it. `clipped_reason: "out_of_reach"` is set
only when `clipped_region` is `null` because nothing of the region is reachable; a partly reachable region gives the rectangle and `clipped_reason: null`.
`bad_region` = `x0 >= x1` or `y0 >= y1`. `estimated_seconds` is `null`: the service has no per point time estimate (Machine 0.3.0 `lastRun` is kept as is
by the import and is not a measured rate).

## Level (mode `level`)

```
{
  "source": "params" | "profile" | "bed_g" | "suggested" | null,
  "suggested": bool,                                          // true when source is "suggested" (one point near each leadscrew)
  "margin": num,
  "points": [{"index": int, "x": num, "y": num,
              "status": "in" | "out_of_reach" | "clipped" | "duplicate" | null, "reason": str (absent when "in"),
              "near_leadscrew": {"index": int, "distance": num} | null}],
  "errors": [{"code": "no_probe" | "no_points" | "too_many_points" | "too_few_points" | "no_limits" | "out_of_reach" | "duplicate_point", "point": int | null}],
  "leadscrew_count": int,
  "descent": {"bound": num | null, "limit": num | null, "ok": bool | null}
}
```

- `points` come from the same resolution as `level.g32/g30/measure` (`machine_level.resolve_points`). `index` is the order of the points = the `P` of `G30`.
- status/reason as for the mesh, plus `duplicate` / `duplicate_point` for a point closer than 1 mm to an earlier one in both axes (the first of them stays `in`).
  Without the margin (default 0) there is no `clipped`.
- `near_leadscrew` = the closest leadscrew (distance in mm in the XY plane, probe coordinates against leadscrew coordinates) for each point; `null`
  when there are no leadscrews. A good levelling has about one point per leadscrew.
- `errors` = `machine_geometry.validate_points` (what the run would refuse as `error.reason`; `too_few_points` is the `level.g30` rule, fewer points than leadscrews) or `no_probe` when there is no probe; `leadscrew_count` = number of leadscrews.
- `descent` = `machine_geometry.descent_bound` against `safety.max_probe_descent_mm`; `ok` is `null` when one of the two is unknown.
- When the mode is `level`, the profile's M671 does not need to be present: with no leadscrews the points still come back (bed.g / profile / params).
  Without anywhere to take points from, `points: []`, `source: null`, `errors: [{code: "no_points"}]`.

## Last measurements

`last.mesh` (the newest map of the library, never a `legacy:` file; `machine_heightmap.listing`):

```
{"id", "name", "ts": <created, epoch s>, "user", "probe_index": int | null,
 "grid": {"nx","ny","min_x","max_x","min_y","max_y"}, "stats": {"probed","unprobed","min","max","range","mean","rms","stdev","light"},
 "points": [{"i","j","x","y","z": num | null}]}        // z null = not probed (skipped)
```

`last.level` (the newest level run: the record of the history for who/when/outcome, and the points of the run in memory when it still holds them):

```
{"ts": <finished / record time, epoch s>, "user", "kind": "level.g32" | "level.g30" | "level.measure", "outcome": str | null, "record_id": str | null,
 "deviation": num | null, "mean": num | null,
 "points": [{"index","x","y","z","deviation"}] | null, "points_reason": null | "not_stored"}
```

`deviation` of the block = the RMS deviation of the last measurement (the verification when there is one, else the `before` of the last pass).
Per point, `deviation = z - mean(z)` of the measured heights. The history record only stores the statistics, so after a restart of the service the
points are `null` with `points_reason: "not_stored"`. Both blocks are `null` with `mesh_reason: "no_mesh"` / `level_reason: "no_level"` when there is
nothing.

## Roles, registration

Operator, READ (same as `machine.limits.get`, `machine.mesh.list`). No role change. Registered in `permissions.OP_ROLES`, `machine_ops.phase2_ops`,
`docs/api/README.md`, `CHANGELOG.md`, `plugin.json` `dsfFiles`, `test_machine_permissions`.

## Unverified

Never run against the real machine: no capture of a real M671 `tiltCorrection` in the object model exists in `dsf/fixtures/real` (the M671 answers
are invented, like the rest of the levelling ones); the order of M671 positions against Z drivers is the firmware's documented one, not checked here.
The tool offset (G10) is not added to the probe reach (the geometry modules do not either).
