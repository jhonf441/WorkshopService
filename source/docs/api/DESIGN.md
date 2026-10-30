# Design of the central API

Usage for external programs in README.md.

Underlying rule: use what DSF and DWC already bring. No servers, ports or registries of
our own: plugin HTTP endpoints (DWS), the object model and the plugin data (state),
dsf-python (orders to the board), DSF's permissions and DWC's sessions.

## 1. Transport

DSF plugin HTTP endpoints (permission `registerHttpEndpoints`, which
WorkshopService and WorkshopRS485 already have). DWS serves them at `/machine/<namespace>/<path>`:

| Method and route | What for |
|---|---|
| `POST /machine/WorkshopService/api` | call an operation (JSON body) |
| `GET  /machine/WorkshopService/api` | description: all the operations with their schema (the same as `api.describe`) |
| `POST /machine/WorkshopRS485/api` / `GET` | the same for RS485 (`rs485.*` operations) |

Why plugin HTTP and not another socket: it does not go through the queue of any RRF channel,
DWS already publishes it on the same port and with the same session as DWC, and DSF cleans it up by itself
when the plugin stops (a request to a stopped plugin gives 502/503, never a jammed
channel). One single path per plugin: the name of the operation goes in the body (DSF has
no wildcards in the routes and each endpoint is a separate socket in the service).

The body is read whole (dsf-python's read cuts at 32 KB): requests of
up to 1 MB are accepted. The biggest thing (the configurator's file list) can still go as a
file on the SD (`file: "0:/..."`).

## 2. Format

Request:

```
POST /machine/WorkshopService/api
Content-Type: application/json
X-Session-Key: <DWC session, if there is a password>

{"op": "lights.zone", "args": {"index": 2, "on": true}, "confirm": false, "origin": "WorkshopLights"}
```

- `op` (required): `<group>.<action>`, in English, lowercase.
- `args` (object, optional): named arguments; types validated with the operation's
  schema (int, number, bool, string, enum, object, array). An argument that is not in
  the schema is an error (`invalid_args`), unless the operation says `extra: true`.
- `confirm` (bool): the person already accepted that operation's notice (section 6).
- `origin` (short text): who is calling (plugin or page Id, `macro`, `bridge`,
  `vision`, `external:<name>`). Only for the "Received commands" history and the
  Activity; it gives no permissions.

Correct response (HTTP 200):

```
{"ok": true, "op": "lights.zone", "result": {...} | [...] | null, "message": "<text>"}
```

`result` is the JSON the operation returns; `message` the text to show (when the operation returns text).

Error:

```
{"ok": false, "op": "...", "error": {"code": "<code>", "message": "<text>", ...extra}}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | body that is not JSON, `op` missing |
| 404 | `unknown_op` | operation that does not exist (the client says "update WorkshopService" if the whole endpoint does not exist: a DWS 404 without a JSON body) |
| 422 | `invalid_args` | missing, extra or other-typed argument (`error.field`) |
| 401 | `auth_required` | DWC has a password and the request carries neither a session nor the local key |
| 403 | `forbidden` | the route cannot use that operation (macro or local key with an administrator operation) |
| 428 | `confirm_required` | `confirm: true` missing (`error.confirm` = {level, key, title, text}) |
| 423 | `motion_denied` | the motion owner does not allow it (`error.motion` = {decision, code, reason}) |
| 424 | `failed` | the operation ran and failed with a reason (e.g. "the board rejected M18") |
| 500 | `internal` | unexpected exception (detail in the service log) |
| 503 | `busy` | another exclusive operation takes more than 20 s (the request was not executed) |

A DWS 502/503 without JSON = service stopped or restarting: the client retries 6 times
every 2.5 s and then gives an error.

## 3. Who can call (permissions)

DSF gives the permissions to the PLUGIN (plugin.json `sbcPermissions`); inside the API it is decided
by the ROUTE of the request:

| Route | How it is recognized | What it can do |
|---|---|---|
| DWC page / external program with a session | DWS passes a `sessionId` >= 0 (the session given by `GET /machine/connect?password=...`) | everything |
| Without a session, DWC WITHOUT a password | `sessionId` < 0 and the board has no password (factory M551) | everything (like `/machine/code` today: anyone on the network can already send G-code) |
| Without a session, DWC WITH a password | same with a password | nothing: 401 `auth_required` |
| Local program of the system (Vision, G-code bridge) | header `X-Workshop-Token` = the contents of `/opt/dsf/conf/workshop-api-token` (outside the SD) (created by the service on startup, permissions 640, group dsf) | everything except `admin` |
| SD macro | mailbox by global variables (section 7) | only the operations marked `macro` |

Each operation has a class: `read`, `write`, `motion`, `stop`, `power`, `admin`.
`admin` = DWC's password (`password.*`) and channels (`comms.set`). `stop` is never
blocked nor asks for confirmation. The "existing password/key" for external programs is
DWC's (M551): the program opens a session the way DWC does and sends it in
`X-Session-Key`. The G-code bridge keeps its own key for its Telnet clients.

## 4. Operations (summary; the full schema is given by `GET .../api`)

Each row is an entry of the `dsf/api_ops.py` table (name, internal handler, action,
arguments with name and type, class, confirmation level, exclusive, macro). The
files in `handlers/` remain as an internal implementation (`run(params, bridge, config)`);
the table translates the named arguments to their parameters. There are no Spanish aliases any more.

| Group | Operations | Class |
|---|---|---|
| api | `api.describe`, `api.ping` | read |
| state | `state.get` {keys?}: published data of the service (memory, without asking DSF for anything) | read |
| machine | `capabilities.get` {refresh?}: what the machine has, discovered from the board (viewer); `profile.get` (viewer); `profile.set` {changes, replace?} (admin session; suggested level technician/admin); `preflight.run` {features?}: pre-install check (viewer) | read/admin |
| activity | `list` {from,to,type,exclude,limit,offset}, `delete` {id}, `clear` {from,to,type,exclude}, `log` {type,text} (macro) | read/write |
| air | `set` {on} (macro), `auto` {on}, `delay` {seconds} | write |
| power | `after_job` {armed: true/false/"toggle"} (macro), `timer` {minutes}, `timer_cancel`, `method` {method, power_off_system, relay_output, relay_value}, `off` (macro, conf. 3), `full_reset` (macro, conf. 3) | write/power |
| db | `status`, `backup`, `repair_dates`, `places`, `folder` {path}, `delete_previous` (conf. 2), `keep` {file, keep}, `settings` {...} | read/write |
| sound | `beep` {pattern} (macro) | write |
| blackbox | `status`, `lines` {n}, `note` {text} (macro), `hide` | read/write |
| camera | `status`, `start`, `stop`, `url` {url}, `service` {changes?}, `capture` {camera}, `timelapse` {action,name}, `token` | read/write |
| history | `list` {from,to,name,errors,query,...}, `delete` {from,to} | read/write |
| comms | `get`, `set` {plugin_channel?, jog_channel?} (conf. 4) | read/admin |
| config | `snapshot`, `list`, `get`, `commit`, `lock`, `unlock`, `arm`, `confirm`, `rollback`, `restore`, `guard` (args as today, named) | read/write |
| energy | `history` {from,to,limit,offset,meter}, `period` {period,date,meter}, `rate_get`, `rate_set` {currency,value} | read/write |
| meter | `get` {meter}, `search`, `test` {...}, `save` {...}, `forget` {meter} (conf. 2), `settings` {meter,changes} | read/write |
| jog | `xy` {x,y,speed}, `z` {z,speed}, `axis` {axis,value,speed}, `stop_xy`, `stop_z`, `stop_axis`, `free` {on} | motion/stop |
| light / statuslight | `light.set` {on} (macro), `statuslight.set` {on} (macro) | write |
| lights | `get`, `save` {config}, `test`, `identify`, `animation`, `preview`, `apply_m950` (conf. 3), `zone`, `test_state`, `scene`, `schedule`, `import` | read/write |
| motors | `enable` {axes}, `disable` {axes} (conf. 4), `reread` | write |
| notifications | `get`, `active`, `destination`, `new_topic`, `type`, `option`, `quiet_hours`, `video`, `mute`, `test`, `send` {title,message} (macro) | read/write |
| password | `status`, `set` {password} (conf. 3), `clear` (conf. 3) | read/admin |
| pid | `status`, `start` {tool, zones}, `cancel` | read/write/stop |
| bigpart | `read`, `counts`, `marks`, `part`, `fit` (`data` object) | write |
| bridge | `test` {line} | read |
| risk | `list`, `start` {id,text,seconds}, `end` {id} | read/write |
| job | `get`, `start` {name}, `end`, `cancel`, `close` (conf. 2), `timeout` {minutes} | read/write |
| view | `heartbeat` {topic: health/power/motors/trace} | read (not noted) |
| trace | `since` {job, cursor, limit} | read (not noted) |
| motion | `state`, `ask`, `reserve`, `renew`, `release` (section 5) | read/motion |

Concurrency: the `write`/`power`/`admin` operations are exclusive (one lock, like today's
`_handlers_lock`; if it is held more than 20 s: 503 `busy`). `read`, `stop`, `jog.*`,
`view.*` and `motion.*` do not wait for that lock: a long Lights save no longer holds up the
jog or a STOP.

Long operations: the API answers when it finishes (the longest, `meter.search`, ~8 s;
`lights.preview` lasts as long as requested). What lasts minutes already runs in the background and shows in
the plugin data: PID (`pid.status`), configuration rollback (`configGuard`),
timelapse, live job (`trabajoEnVivo`). No task system is added.

## 5. Motion owner (`dsf/motion_owner.py`)

A single module decides whether it is possible to move or change the geometry NOW and says why not.
It gathers what used to be spread around (jog_move.block_state, the pages' JEN/JMF/ZMF,
Vision's tvBusy, the configurator's CFG). Inputs, all in memory (without asking DSF for anything):
the single subscription (`state.status`, `job.file`, homing, `global.motoresSueltos`,
`global.jogLibre`), `live_job` (open, last activity), the bridge's activity
(bridge-state.json + M3/M4/M5 over SBC), the jog (active gesture, no limits), active risks
and the reservations.

States (code): `stopped` (halted/off/updating...), `file_job` (processing, pausing,
resuming, simulating, cancelling), `file_paused` (paused), `live_active` (live job
with activity < 20 s ago), `live_idle` (open, still > 20 s), `bridge_active` (the
bridge sent orders < 20 s ago without a live job), `reserved` (someone else holds a reservation),
`free`.

Action classes and decision (`allow` / `confirm` / `deny`), with the user's decisions
of 2026-10-12 (a file pause CAN be moved; a still live job asks for
confirmation; with activity it is blocked):

| Class | free | reserved (other) | file_job | file_paused | live_active | live_idle | bridge_active | stopped |
|---|---|---|---|---|---|---|---|---|
| `stop` | allow | allow | allow | allow | allow | allow | allow | allow |
| `move` (jog, go to, home, probe, visionpose, frame with macro) | allow | deny | deny | allow | deny | confirm | deny | deny |
| `job` (M32 of an own job) | allow | deny | deny | deny | deny | deny | deny | deny |
| `sequence` (Vision photos/crosses/registration, Z assistant, guided test, Motors tests, Level, crash calibration) | allow | deny | deny | deny | deny | deny | deny | deny |
| `geometry` (active zone, G10, laser offset, mode, mesh, microstep, M564, M18, reload mode) | allow | deny | deny | deny | deny | deny | confirm | deny (M999 apart) |
| `power` (shut down now, restart everything) | confirm | confirm | confirm | confirm | confirm | confirm | confirm | allow |
| `channel` (change channels) | allow | deny | deny | deny | deny | deny | deny | allow |

Reservations: `motion.reserve` {origin, action, text, seconds (30, cap 900), confirm} gives a
`token`; while it lasts, the others get `deny` with "<origin> is using it: <text>".
`motion.renew` {token, seconds} extends it (heartbeat of a long sequence);
`motion.release` {token} releases it; it expires by itself. The jog takes an implicit reservation while
each gesture lasts. The confirmations of the still live job are valid for 60 s from the last
use, only for that job, and are lost if it has activity again (today's jog behaviour).

API: `motion.ask` {origin, action, text?, confirm?} -> `{decision, code, reason, state}`;
`motion.state` -> the same data that is published. Published (only on change, < 1 KB):
`plugins.WorkshopService.data.motion` = `{state, code, reason, owner: {origin, action,
text, until}, job: {kind, name, idle_s}, bridge: {clients, last_order_s}, v}`. The
pages read that data from DWC's store (without polling) to disable buttons with the
reason, and before moving they make ONE `motion.ask` (what is drawn is not trusted).

Who uses it in this migration:
- Jog (backend): each gesture asks the owner (it replaces block_state; `data.jogBloqueo`
  keeps being published with the same format for the page).
- JS pages (Jog, Workbench / Zones, Camera, Vision, Bar): `postCode` classifies the
  G-code that moves (G0-G3, G28-G32, G38, G29, M32, M98 to the macros that move) and asks
  before sending it; the guards that draw buttons (jogMachineFree, machineFree, tvBusy)
  add the published decision.
- Vue pages: `machineFree()` (vue/_shared/machine-free.js, the same table as
  `tallerMaquinaLibre` of the JS pages) adds the published data: a reservation by someone else
  (code `reservada`) or the bridge sending orders (code `puente`) block, with the reason
  from the service (Motors: crash, pulse ceiling, axis test; Printing: head change,
  extruder, mode). The Configurator's guided test also does `askMotion()`
  right before moving.
- Vision (Python): calibration with crosses and registration ask for a reservation, renew it between steps
  and release it; if they lose it, they stop.
- Out of scope (open question 3): enforcing it on the board by intercepting G-code from
  HTTP/Telnet/USB (stage 2.6 of the audit): DWC, the console and the external program can still
  move on their own.

## 6. Confirmations (the central notices keep working)

Each operation can declare `confirm: {level: 2|3|4, key}`. Without `confirm: true` in the
request, the service does NOT execute and answers 428 `confirm_required` with the level and the texts
(es/en, keys `plugins.WorkshopService.api.confirm.<key>.*` registered with
`registerPluginLocalization` by the service page). The common client shows the notice
of the level (3: `tallerConfirmarRiesgo`, 4: `tallerConfirmarNivel4`; in Vue the same dialog)
and repeats with `confirm: true`. This way the risk is defined by the server and also holds for external
programs (they have to send `confirm: true` on purpose). The pages that already
show their own notice (Enable motors, Channels) send `confirm: true` directly.
Level 2 (double tap) remains page-only. The TALLER_RIESGOS table (G-code and
macros) stays the same in 00-core.js.

## 7. SD macros (without own codes)

A macro cannot do HTTP. Two ways, in this order:

1. **Look instead of notify.** What the service can deduce from the object model no longer
   needs anyone to tell it: light, air and status LEDs are read from the globals/outputs;
   the no-limits jog crash arrives through global variables written by `sys/driver-stall.g`
   (`global.jogLibreStallN` which goes up and `global.jogLibreStallDrv`), which the service sees through its
   subscription (`global.**`).
2. **Mailbox by global variables** for what really is an order (shut down, restart,
   arm the shutdown at the end, notices):

```
M98 P"0:/sys/workshop/macros/service-call.g" S"power.after_job" A"armed=toggle" W5
```

`service-call.g` (written by the service on startup, with a mark; if someone edits it and
removes the mark it is not touched) declares `global.wsRequest`, `global.wsReply`, `global.wsSeq`,
waits for the mailbox to be free, writes `"<n>|<op>|<args>"` in `global.wsRequest` and
waits up to `W` seconds (default 5; `W0` = do not wait). The service sees it in its
subscription, executes the operation with `origin: "macro"` (only those marked `macro`),
writes `global.wsReply = "<n>|ok|<text>"` or `"<n>|error|<text>"` and empties
`global.wsRequest`. Arguments `A"key=value,key=value"` (numbers and true/false are
converted). Without the service running, the macro warns with `echo` after W seconds and continues.

Affected macros: `macros/power/shutdown-all.g`, `full-reset.g`, `shutdown-after-job.g`
(repo, WorkshopControlBar) move to the mailbox; `sys/daemon.g` does not change (it calls
shutdown-all.g); `sys/driver-stall.g` is rewritten by the service; the heartbeat macros
(`enable_pi_status.g`, `disable_pi_status.g`) are called by the service: they do not change.

## 8. G-code bridge and external programs

- The bridge (`bridge/gcode_bridge.py`) understands `BRIDGE JOB START [name]`,
  `BRIDGE JOB END` and `BRIDGE JOB CANCEL` as its own orders (they do not go to the board), notes
  them in `bridge-state.json` (`activity.live_job`, as today) and calls `job.start` /
  `job.end` / `job.cancel` of the API with the local key, in the background and with retries.
  The live job program puts those lines in its Start/End G-code.
- External programs (another PC, scripts): `POST /machine/WorkshopService/api` with DWC's
  session. Examples in README.md.

## 9. History ("Received commands")

Each call is kept in the same table (`db.command_insert`) with: operation name,
masked arguments (passwords, meter key, big JSONs summarized), route and
origin, result, ms. Heartbeats (`view.heartbeat`, repeated `jog.xy/z/axis`,
`motion.renew`) are not noted. RS485 keeps noting in its file (extra_commands.py) with the
operation name.
