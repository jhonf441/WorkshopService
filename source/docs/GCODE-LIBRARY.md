# G-code library (service side)

A library of the G-code files on the machine for the printing plugin: list with relevant data, a thumbnail and a layer preview (like a
slicer viewer). Every file is parsed ONCE, streaming, by one low-priority background worker; the answers come from a cache on the SD.
Nothing is parsed inside an API request.

Modules (`dsf/`): `gcodelib_parse.py` (pure streaming parser), `gcodelib_kind.py` (kind of file, 2D toolpath of laser / cnc / travel files), `gcodelib_thumb.py` (synthetic thumbnail: sampler + rasterizer + PNG encoder), `gcodelib_geo.py` (polyline simplification and the layer blob format),
`gcodelib_cache.py` (the cache), `gcodelib_files.py` (path safety, folder scan), `gcodelib_indexer.py` (the worker), `gcodelib_ops.py` (the API).

## How it works

- The worker (process `gcodelib`, shown on the services page, rests when the Printing plugin is stopped, see `service_modules.PROCESSES`)
  takes one file at a time, newest first. A file that a page asks for (`info`, `thumbnail`, `layers`, `refresh`) jumps the queue.
  It sleeps between chunks of 4000 lines and asks the OS for a nice value of 10.
- It scans `0:/gcodes` (and every folder a `gcodelib.list` looked at) every 30 s: new or changed files are queued, entries of deleted files
  are dropped. `gcodelib.list` also queues what it finds without an entry. Both only when the setting `auto_index` is true.
- A cache entry is valid while the parser version, the size and the modification time of the file are the same. Otherwise the file is
  `pending` again. A file the parser could not read is `error` and is not retried until it changes (or `refresh`).
- Cache folder: `0:/sys/workshop/data/gcodelib/` (`index.json`, and per file `<sha1 of the path>.json`, `.geo`, `.<n>.png` embedded thumbnails, `.thumb.png` synthetic thumbnail). Writes are
  atomic. Over `cache_mb` the least recently USED entries lose their geometry, thumbnails and detail but keep their summary (so the list
  still shows them and nothing is parsed in a loop); asking for the geometry or thumbnail of such a file reads it again (`pending`).
- Settings area `gcodelib` (`settings.get` / `settings.set`, technician): `{"enabled": true, "cache_mb": 200, "auto_index": true}`
  (`cache_mb` 10..4000). With `enabled` false the worker rests; lists still work and show `pending`.

## Operations

Paths: `0:/gcodes/a.gcode` (also `/gcodes/a.gcode` or `gcodes/a.gcode`; all relative to the SD). Only `.g .gcode .gco .nc .gc .ngc .tap` (any case) inside the SD;
`..`, absolute paths outside the SD and symbolic links that leave it answer `invalid_args` (field `file` / `dir`). Layers are numbered from 0.
Texts in answers (`error`) are in the language of the request.

Roles: `gcodelib.list`, `.info`, `.thumbnail`, `.layers` viewer; `.refresh` operator; `.forget` admin.
Capabilities (both in category `system`, delegable): `jobs.library` (the four reads), `jobs.library_manage` (refresh, forget).

### gcodelib.list `{dir?, query?, kind?, sort?, desc?, limit?, offset?}`
`dir` default `0:/gcodes`; `query` substring of the name OR of a tag (case-insensitive); `kind` one kind or a list (or a comma separated
string) of `fff | laser | cnc | travel | unknown` (only ready files can match; an unknown name is `invalid_args`, field `kind`); `sort` `name` (default) | `modified` | `size` | `time`
(`time` uses the slicer's estimate, else our own, files without one last); `limit` 1..200 (default 50); `offset`.
Answer:
```
{dir, dirs: [sub-folder names], total, pending, cache_bytes, counts: {fff, laser, cnc, travel, unknown},
 rows: [{name, path, size, modified (epoch s), state: "ready"|"pending"|"working"|"error", error?, summary?}]}
```
`counts` is over ALL the ready files of the folder (not the query, not the `kind` filter; a pending file is not counted yet): the UI draws its
kind chips with it. `total` is the number of rows after the filters. `summary` exists when `state` is `ready` (see below). `pending` counts files still queued or being read: poll the list while it is above 0.

### Summary (every field optional)
`slicer`, `slicer_version`, `layers` (count), `layer_height`, `first_layer_height`, `time_s` (the slicer's estimate), `time_calc_s` (our
rough distance/feed estimate, no acceleration), `filament_mm`, `filament_cm3`, `filament_g`, `filament_cost`, `nozzle_mm`,
`nozzle_c`, `bed_c`, `chamber_c` (first temperature above 0 the file asks for), `bbox: {min: [x,y,z], max: [x,y,z]}` (extruding moves),
`features: [type names]`, `has_thumbnail` (true only for a thumbnail EMBEDDED in the file), `has_preview_thumb` (true when `gcodelib.thumbnail` has
something to give: the embedded one or the synthetic one; the UI asks only when it is true), `object`, `size`, `modified`.
Always present on a ready file: `kind` (`fff` | `laser` | `cnc` | `travel` | `unknown`), `plane` (`3d` for fff, `2d` otherwise) and `tags`
(short strings for chips: the slicer or program in lower case (`prusaslicer`, `simplify3d`, `lightburn`), `laser-macros` (M98 of
`/macros/laser/`), `macro-calls` (any M98), `live-job-markers` (M118 `BRIDGE JOB START` / `END`), `user-script` (`;USER START SCRIPT`),
`spindle` (cnc with M3/M4), `has-thumbnail`, `preview-truncated`).
Only for `laser`, `cnc`, `travel`: `cut_mm`, `travel_mm`, `power_max` (largest S seen while cutting), `feed_mm_min` (F of the first cut move),
`time_calc_s` from lengths and feeds (a G0 without F counts at 3000 mm/min), `bbox` (the `;Bounds: X.. Y.. to X.. Y..` header when present,
else measured over the cut moves; z is the cut depth range for cnc, 0 otherwise), `layers` = number of 2D layers, `features` = `cut`,
`travel`, `plunge`. `slicer` / `slicer_version` hold the program of the header (`LightBurn`, `2.1.04`).

### Kinds
Decided from the content (never from the folder name), in this order: `fff` = extruding moves (positive E with XY motion, 3 or more);
`laser` = a LightBurn / LaserGRBL / Inkscape header or an M98 of `/macros/laser/` (unless it is clearly cnc), else G1 moves that carry S power
(`G1 X.. S255`, or modal S after `M4`) with no E; `cnc` = spindle `M3/M4` or a `.nc/.ngc/.tap` file, plus G1 moves that change Z;
`travel` = only G0/G1 without extrusion, power or spindle (test and utility files); `unknown` = nothing moves. Several commands on one line
(`G90 M5 G0 X1 Y2`) are read one by one.
### gcodelib.info `{file}`
Ready: `{state: "ready", file, plane: "3d" | "2d", summary, header: {key: value}, temps: [gcode_temps commands: {line, text, kind, tool, bed, temps, code}],
layers_table: [{layer, z, height, est_time_s, features: [..]}] (2D layers: `z` null or the cut depth, no `height`, plus `name`; at most 1500, `layers_table_truncated`), types: [..]}`.
`header` holds the slicer's `; key = value` / `;KEY:value` comments (header and footer config, at most 400, values cut at 200 chars).
Not ready: `{state: "pending"|"working"}` (the file was queued first in line) or `{state: "error", error}`.

### gcodelib.thumbnail `{file, width?}`
`{width, height, png_base64, synthetic?}`: the embedded thumbnail (the smallest one that is at least `width` wide, else the biggest) or, when the
file has none, the synthetic one (`synthetic: true`, always 192x144, `width` is not used to scale it); `{none: true}` when the file has no
geometry to draw; or the same `{state: ...}` answers as `info`. Embedded: PNG thumbnails only (PrusaSlicer, OrcaSlicer, Cura `; thumbnail begin WxH len`); an embedded thumbnail always wins.

#### Synthetic thumbnail
Made once at index time, inside the same streaming pass, for files that have geometry and no embedded thumbnail (Simplify3D, LightBurn, Cura
without plugin, cnc). `gcodelib_thumb.Sampler` receives every layer the parser closes and keeps at most 30000 segments spread evenly over the
file (when full it keeps every second one and doubles its stride, so memory is fixed whatever the file size); at the end it draws a 192x144
8-bit palette PNG (about 2 to 4 KB, background `#1b1b1f`, bed outline) with no PIL. fff: orthographic view, yaw 35 / pitch 35 degrees, all
layers, lower layers darker, one colour per feature type when the file has several. Laser / cnc / travel: top view, travel dim under the cut (plunge
in amber), over the bbox rectangle. The same input gives the same bytes. Stored as `<sha1>.thumb.png`: counted in `cache_bytes` and the cap,
evicted and forgotten with the rest of the file (after an eviction the thumbnail is `pending` until the worker reads the file again). A list or a card
needs this one small PNG and no geometry. Cost measured on a PC: sampling adds about 15 percent to the parse; drawing takes 10 to 350 ms per file.

### gcodelib.layers `{file, from, to, detail?}`
`detail` `normal` (default; 0.05 mm, with travel moves) or `low` (0.3 mm, no travel). Answer:
```
{state: "ready", from, to, total, types: [..], plane: "3d" | "2d", detail, truncated,
 layers: [{layer, z, name? (2d), segments: {<type>: [[x0, y0, x1, y1, ...], ...]}, travel?: [x0, y0, x1, y1, ...]}]}
```
`plane` `3d` is everything described so far (fff, `z` = layer height, types = feature names, `travel` list). `plane` `2d` (laser, cnc, travel files):
`z` is null (cnc: the cut depth of the layer), `name` is the layer name (laser: the `;Layer C02` comment, e.g. `C02`, one layer per comment; cnc:
`z=-0.4`, one layer per cut depth, a depth cut again goes back to its layer; otherwise `all`), `types` are `cut` (tool on), `travel` (G0 or tool
off, drawn as polylines too, there is no separate `travel` list) and `plunge` (cnc, Z going down). A zero-length polyline is a plunge point.
The same window and 400 KB rules apply; at most 500 layers and about 4 million coordinates are kept per file (`preview-truncated` tag).
One entry of a type is one polyline (flat x,y pairs, 2 decimals). `travel` is flat 4-number moves (2 mm and longer, at most 1500 per layer).
An answer holds about 400 KB: when the window is bigger it stops early, `to` is the last layer sent and `truncated` is true: ask the next
window from `to + 1`. `from` beyond the last layer gives an empty `layers`. Not ready: `{state: ...}` like `info`.

### gcodelib.refresh `{file?}`
With `file`: drops its entry and queues it first in line. Without: scans the watched folders now (queues new/changed, drops deleted). `{queued}`.

### gcodelib.forget `{file?}`
Deletes one entry, or the whole cache. `{removed}`. With `auto_index` on the worker reads the files again; to stop that, turn `auto_index` off.

## What the parser understands
PrusaSlicer / OrcaSlicer / SuperSlicer / Cura / Simplify3D-style comments: slicer name and version (`generated by ...`, `Generated with ...`),
estimated time (`estimated printing time (normal mode) = 1d 2h 3m 4s`, `total estimated time:`, `;TIME:`), filament (`filament used [mm|cm3|g]`,
`total filament cost`, Cura `;Filament used: 1.2m`), `;TYPE:` / `; FEATURE:` types, layers from `;LAYER_CHANGE` + `;Z:` + `;HEIGHT:`,
`; CHANGE_LAYER` + `; Z_HEIGHT:` + `; LAYER_HEIGHT:` or `;LAYER:n`; without markers the layer changes with the Z of the extruding moves.
Files that are not prints (laser, cnc, travel) get a 2D toolpath, see Kinds and gcodelib.layers. Moves: G0/G1, G2/G3 arcs (I/J or R), G90/G91, M82/M83, G92. Extruding = positive E with XY motion (retractions are not drawn). Whatever comes
before the first layer marker (purge line) is not a layer. Macros (M98) and tool changes are not followed.

## Needs on install
Service version bump (new modules, settings name, process, texts); the page texts of the service page are regenerated (`dwc-src/i18n`).
No new AppArmor permission (the cache lives under `0:/sys/workshop/data/`, the files are read where DWC already reads them).
