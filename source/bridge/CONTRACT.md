# Bridge contract: WorkshopService <-> G-code bridge

Contract version: 1 (state file schema 2). Written 2026-11-06 from the code as it is today (bridge 3.8.0, service 2.29.4): it
documents what both sides already do, adds no behavior, and gives each promise a name, a number and a test. Decision record and
migration: `ARCHITECTURE.md`.

The bridge (`gcode_bridge.py`, `live_stop.py`, `live_resume.py`) is its own program and its own systemd unit. WorkshopService is a DSF
plugin. They share a Pi and some files, not a process, not a language runtime, not a release train. This text is everything one
side may rely on about the other. Anything not written here is not promised.

Words: MUST / MUST NOT bind both sides. "Reader" is the side that reads a file, "writer" the side that writes it.

## 1. The channels

| # | Channel | Writer -> reader | Where | Promise |
|---|---|---|---|---|
| C1 | State | bridge -> service, jog, page | `0:/sys/workshop/data/bridge-state.json` | section 3 |
| C2 | Actions | page, service -> bridge | `0:/sys/workshop/data/bridge-action.json`, answer in C1 key `action` | section 4 |
| C3 | Settings | page, `install.sh` -> bridge; service reads the port | `0:/sys/workshop/config/bridge.json` | section 5 |
| C4 | Power | service -> unit | polkit rule + `systemctl start/stop workshop-gcode-bridge.service` + flag file `0:/sys/workshop/data/bridge-disabled` | section 6 |
| C5 | Calls to the service | bridge -> service | `POST http://127.0.0.1/machine/WorkshopService/api`, header `X-Workshop-Token` | section 7 |
| C6 | Live-stop records | bridge -> service, page | `0:/sys/workshop/data/live-interrupted.json` (+ `.bak`), `live-interrupted-hidden.json` (service) | section 8 |
| C7 | Debug heartbeat | page -> bridge | `0:/sys/workshop/data/bridge-viewer.json` (only its modification time) | section 5 |
| C8 | Clients | programs -> bridge | TCP port of C3 (default 23), plain lines + Telnet | section 9, frozen |

The bridge and the service MUST write their files atomically (temporary file in the same folder, then rename). The page writes C2, C3 and C7 with a plain PUT through DWC's file API, which is not under its control, so every reader of those files MUST tolerate a half-written or invalid file (the bridge does: a garbage action file is ignored and a bad `bridge.json` keeps the old settings, both tested). `0:/` is `/opt/dsf/sd` on the Pi.

## 2. Versions and compatibility

* `schema` (state file, integer): the MAJOR version of C1. It changes only when a promised key changes meaning or disappears.
  Today: schema 2. A reader supports a list of schemas (service: `bridge_contract.SCHEMAS`); a schema it does not know is
  incompatible and NOTHING is read from that file.
* `contract` (state file, integer, added in bridge 3.8.x; absent = 1): the version of THIS text the bridge was written for.
  Inside one schema the bridge only ADDS keys. A reader MUST ignore keys it does not know and MUST treat a missing optional key as
  "unknown", never as "false" or "zero". A `contract` higher than the reader's is read normally and shown as "newer".
* `version` (string): the bridge program version, for people and logs; nobody MUST branch on it.
* Compatibility matrix (what must still work):

| Service | Bridge | Result |
|---|---|---|
| any | no state file / dead / garbage / older than 15 s | "down": the jog does not block, the live stop says the bridge is down, the page says so |
| newer | older (no `contract`, or no `live_stop`) | reads what is there; features that need a missing key answer "this bridge is old, run install.sh again" (exists today for the safe stop) |
| older | newer, same schema | extra keys ignored; actions the older service writes are the ones the newer bridge still has |
| older or newer | schema it does not know | "incompatible": reads nothing, jog falls back to its own signals (M3/M4/M5 seen on the SBC channel), page shows a warning; the bridge itself keeps serving its clients |

* Unknown schema (OPEN OWNER DECISION). A state of a schema the reader does not know is "incompatible". What the readers do with it:
  the health poller, the origin tracker, the bridge probe and the page read nothing from it (the page shows a warning and does not guess its
  fields); the safe stop refuses it like an old bridge ("the bridge is too old to have this"; `M112` never depends on it); the port is still
  read from it (the client count of the jog depends on the right port). For the JOG there is one named policy,
  `bridge_contract.UNKNOWN_SCHEMA_JOG`, with three values: `"legacy"` (the default and today's behavior: read it with the rules of schema 2,
  best effort), `"free"` (read nothing: the jog is free, as with a dead bridge; the M3/M4/M5 mark seen on the SBC channel still protects)
  and `"block"` (an order is pending right now while the file is fresh: the jog is refused; an old file never blocks, so a dead bridge
  cannot hold the jog). The default changes nothing until the owner decides; flipping it is one line and `test_bridge_safety_readers_parity`
  tests the three values. Recommendation: `"block"` with a clear message (the jog's refusal text today says an order arrived, which is not
  exact for this case; the message is part of the decision).
* `contract` stays 1 in this revision on purpose: every change since the first text (the vectors, the page reader, the manifest, the
  installer, the policy, the rule that a `contract` below 1 or not an integer is read as "not declared") adds no key to the files and does
  not change the meaning of a promised key or the answer of a rule for a bridge that follows the text. The number rises when a promised key
  or a rule changes, and then `vectors.json` changes first.
* A breaking change of C1 MUST raise `schema`, and MUST either keep the old file written in the old schema for at least two bridge
  releases or ship the service adapter first (the strangler order of `ARCHITECTURE.md`). A new promised key needs a new `contract`
  number and a line in this file.

## 3. C1, the state file

Writer: the bridge, every 2 s (1 s with debug on), atomically, mode 0664. Machine-checked shape: `contract/state.schema.json`
(`tests/test_contract.py` validates the real output; `dsf/test_bridge_contract.py` validates the service reading).
Keys promised: `schema`, `version`, `port`, `clients[]` (`id`, `ip`, `name`, `pending_orders`, `last_order_age_s`), `activity`
(`generated_at`, `clients_connected`, `pending_orders`, `last_order_at`, `last_motion_at`, `live_job{...}`), `events[]`
(`time` HH:MM:SS local, `type`, `code`, `text`), `action`, `live_stop.enabled`. Everything else in the file (`security`, `debug`,
`history`, `totals`, timings, `live_stop` details) belongs to the page and may change inside the schema.

Units: times in the schema are epoch seconds (float) or whole seconds relative to the moment of writing (`*_age_s`, `*_s`). Counts
are integers. Ports are integers.

Staleness (the rule that keeps a dead bridge from blocking anything):

* The age of the state is the age of the FILE (modification time). The absolute epochs inside are for people: a browser reads them
  rounded to about 3 hours (found 2026-10-15), so a reader MUST NOT compute an age from them when `*_age_s` exists.
* `pending_orders` proves "something is moving now" only if the file is younger than 10 s (`FRESH_S`). An older file says
  nothing about now.
* The bridge is running only if the file is younger than 15 s (`ALIVE_S`, 7 writes missed).
* Missing, unreadable, not JSON, not an object, unknown schema: the reader answers "unknown" (`None`). It MUST NOT raise, wait,
  retry in a loop or block a motion command. Each caller decides what unknown means and today all of them fail open for motion
  (jog free) and closed for the live stop ("bridge down").

The rules above are written ONCE, as data, in `contract/vectors.json` (65 inputs with the answers: healthy, absent, garbage, the 10 s and
15 s edges, unknown schema, newer or missing `contract`, missing keys, hostile types). `dsf/bridge_contract.py` (service) and
`dwc36/bridge-contract.js` (page) are both tested against that file (`dsf/test_bridge_contract.py`, `tests/bridge-contract.test.js`): a rule
changes in the vectors first and both readers must follow, so they cannot drift. Every reader of the service reads the file through the
adapter; the jog keeps its own arithmetic (`jog_move.bridge_state_age_s`, parity-tested against the adapter) and applies the policy above.

## 4. C2, the action file

Writer: the page (browser, through the DSF file API) or the service (`live_job_stop._send`). Shape: `contract/action.schema.json`:
`{"seq": <integer>, "action": "<name>", ...arguments}`.

* The bridge looks at the file about once a second (by modification time) and runs an action whose `seq` it has not run. The same
  `seq` MUST NOT be run twice. `seq` is unique and increasing per sender (the service uses epoch milliseconds).
* The answer is C1 key `action`: `{seq, ok, code, text, time}` with the same `seq`. A sender finds its answer by `seq` and waits at
  most 10 s (the safe stop up to 150 s: the answer comes when the board finishes).
* Unknown action: answered `ok: false` (the sender can see it did not happen). Unknown extra keys in an action are ignored. A
  file that is not JSON, or has no `seq`, or is the `{"seq": null}` the bridge creates, is ignored without an answer.
* A password action (`set_password`, `clear_password`) is scrubbed from the file as soon as it is read.
* Actions, by owner. The service only sends the first four; the page sends all of them:
  `stop_safe`, `resume_arm`, `resume_disarm`, `interrupted_discard` (live stop and resume, `live_stop.py`);
  `debug`, `debug_extend`, `restart` (refused while a live job runs or an order arrived in the last 30 s),
  `kick`, `rename`, `give_control`, `release`, `trust`, `block`, `unblock`, `set_password`, `clear_password`.
  The old Spanish action names of an old page still work (pinned by `test_old_spanish_actions_from_an_old_page_still_work`).
* `stop_safe`: if the laser-off order fails the stop is NOT done and the job keeps running (answer `ok: false` with the reason).

## 5. C3 and C7, settings and the debug heartbeat

* `bridge.json` belongs to the bridge. The page and `install.sh` edit it; the bridge reloads it within about 1 s when the file's
  modification time changes; a file that does not parse, or a value out of range, keeps the previous (or default) value, never stops
  the bridge. The service only reads `port`, and it prefers the `port` of C1. Defaults and limits are in `gcode_bridge.CONFIG_DEFAULT`
  and pinned in `tests/test_characterization.py` (order timeout 120 s, clamp 1..300; query timeout 3 s, clamp 0.5..30).
* A port change reopens the listening socket and MUST NOT cut connected clients (pinned with real sockets).
* `bridge-viewer.json`: while the page's Debug view is open it rewrites the file every 10 s; the bridge only looks at the
  modification time to renew its debug countdown.

## 6. C4, power (start, stop, status)

* The unit is `workshop-gcode-bridge.service`, always enabled. "Off" is the flag file `bridge-disabled`: the unit has
  `ExecCondition=test ! -e <flag>`, so a stopped bridge does not come back at boot. "On" removes the flag and starts it.
* The service (user `dsf`) starts and stops only that unit through polkit (`/etc/polkit-1/rules.d/49-workshop-gcode-bridge.rules`,
  written by `install.sh`), never with `sudo` (a DSF plugin cannot change user). Reading the state needs no permission.
  `can_control` is probed by really trying `systemctl start` on a running unit.
* The service MUST refuse to turn the bridge off while a live job is active (`bridge_service` handler) and MUST NOT restart or stop
  it for its own reasons. The bridge MUST NOT depend on the service being up to run.
* Status for the page: `systemctl cat / is-active / is-enabled` plus the age of C1. `ss` counts established connections on the C1 port.

## 7. C5 and identity, the calls the bridge makes to the service

* Request: `POST http://127.0.0.1/machine/WorkshopService/api`, JSON `{"op": ..., "args": {...}, "origin": "bridge"}`, header
  `X-Workshop-Token: <local key>`; timeout 5 s. The local key is the file `/opt/dsf/conf/workshop-api-token` (mode 640, owner `dsf`,
  group `dsf`; the bridge's user is in group `dsf`). Nothing else is read for it. The bridge never writes it and never logs it.
* Operations used (all must exist in `dsf/api_ops.py`, pinned by `tests/test_contract.py`): `job.start` (BRIDGE JOB START),
  `job.end`, `job.cancel`, `job.close` (job ends, disconnects, failed orders, safe stop), `motion.state` (machine gate, every 2 s
  while someone is connected).
* Error model of the answer: `{"ok": true, ...}` or `{"ok": false, "error": {"code", "message"}}`; HTTP errors are turned into
  `code: "http"`.
* Failure behavior, both ways:
  - service dead, slow, restarting or answering garbage: the job notices go to a queue of 50 served by one background thread
    (4 tries, 2, 5, 8 and 11 s apart); a full queue drops the notice; a failure is only logged; NO line of the job ever waits for it.
    The service closes an idle live job by itself. The machine gate treats "no answer" as "unknown state" and lets orders through (it
    never blocks by guessing).
  - bridge dead: the service sees an old state file and does nothing (section 3).
* The `origin` string is for the audit trail only; authorization is the key.

## 8. C6, live-stop records

The bridge writes `live-interrupted.json` (`{"v": 1, "records": [...]}`, plus `.bak`, the last 5 records). The service reads it
(`live_job_stop`) to list interrupted jobs and writes only `live-interrupted-hidden.json` (ids hidden from the work table).
Records are never edited by the service; discard goes through the action `interrupted_discard`. A record file that cannot be read is
an empty list.

## 9. C8, the client protocol (frozen)

Plain lines over TCP (CR/LF or LF), each answered with the machine's reply followed by `ok`; Telnet RFC 854/855/1143 tolerated (the
bridge never starts a negotiation, refuses every option once, drops option bytes, `IAC IAC` is byte 255, NUL after CR dropped);
greeting `Connected!`; commands `BRIDGE HELP|STATUS|LIST|NAME|USE|RELEASE|KEY|JOB`; line limit 1024; ordering, overtaking and
coalescing rules of `README.md`. Also part of the public wire contract (pinned in `tests/test_public_wire.py` and `tests/test_coalescing.py`): reply framing is the
Duet text with CRLF line ends followed by exactly `ok
` for EVERY line, errors included (`Error: ...` then `ok`); the bridge never
sends unsolicited output and never starts a Telnet negotiation; there is no GRBL emulation (no `<Idle|...>` status line; a bare `?` is
an order forwarded to the Duet, an empty line from the wire is dropped without an answer, `BRIDGE` / `BRIDGE ?` / `BRIDGE HELP`
answer the help text); the per-command query cache TTLs (M114/M408 500 ms, M105/M119/M27 1000, M36 2000, M20/M122 5000, M503 30000,
M115 60000), coalescing of identical queries across clients, the stale-answer path and the `Error: ...` + `ok` after
`query_timeout_s`; per-client reply order. LightBurn, cutting software, scripts and an ESP32 are real clients (the page tells the owner to
change the port in LightBurn too), so all of this is frozen.

Real clients (cutting software, scripts, an ESP32) exist, so this surface is frozen: it changes
only by an owner decision, with a deprecation period, and every change needs a new characterization test first. This contract does
not touch it.

## 9b. Dialect neutrality

C1, C2 and C3 do not mention any client text format: `clients[]` and `activity` count connections and the orders the bridge sent to the
board. The service MUST NOT parse client lines or replies and MUST NOT depend on the RepRap framing except `bridge.test`, which speaks to
the port as a RepRap client. Nothing more is promised or planned (see `ARCHITECTURE.md` 6b).

## 9c. The page is a reader too

`BridgeCard.vue` (the browser) reads C1 through `dwc36/bridge-contract.js`: same rules, same vectors, no texts. The age it passes is the
seconds since `seq` last moved (the browser has no file mtime). It shows a small chip with the contract the bridge declares (`ok`,
`newer`, `old` = declares nothing) and a warning for an unknown schema. It writes C2, C3 and C7 itself through DWC's file API, so those
files MUST be read tolerantly (see section 1): the page writes them with a plain PUT, not a temporary file and a rename.

## 10. What each side MUST NOT do

* The service MUST NOT write C1, MUST NOT edit `bridge.json` behind the page's back (the page and `install.sh` own it), MUST NOT
  send a line to the bridge's TCP port except `bridge.test` (queries only), MUST NOT block a motion command on an unknown bridge state.
* The bridge MUST NOT import anything of the service, MUST NOT need the service to start, MUST NOT run as root, MUST NOT change the
  order of the lines it received, MUST NOT run an order after a failed laser-off during a safe stop.
* Neither side reads or writes the other's secrets: the service never sees the bridge password (only its scrypt hash lives in
  `bridge.json`, and only the page or `install.sh` write it); the bridge only reads the local key (C5).

## 11. Changing the contract

1. Write the change here first and raise `Contract version` (and the schema number only if a promised key breaks).
2. Update `contract/*.schema.json`, `dsf/bridge_contract.py` and the tests; the tests that quote this file fail otherwise.
3. Release order: the reader side that learns the new thing goes first, the writer second, so every mixed pair in the matrix of
   section 2 keeps working at every step.

## 12. Values both sides know

The bridge is installed apart and cannot import anything of the service, so a value both need is COPIED. A copy cannot be removed without
changing how the bridge is installed, but it is guarded: if one side changes and the other does not, a test fails
(`dsf/test_bridge_shared_values.py`, which reads the bridge as text, never imports it):

| Value | Where each side has it | Guard |
|---|---|---|
| Material macro names (`macros/laser/`, `laserfocus.g`, `livemark.g`) | bridge `MATERIAL_MACRO_RE`; service `laser_correction.FILE` and the documented SD macros | `Macros` |
| Default port 23 | bridge `CONFIG_DEFAULT`; service `bridge_contract.DEFAULT_PORT` and `health_poller.port_bridge` | `Defaults` |
| SD root `/opt/dsf/sd` | bridge `SD_DIR`; service `paths.py` | `Defaults` |
| The two ages (10 s pending, 15 s alive) | adapter, `jog_move.BRIDGE_STATE_FRESH_S`, `live_job_stop.STATE_MAX_AGE_S`, the page reader, this text | `Thresholds`, the vectors |
| State keys the readers use, action names, service operations the bridge calls | schemas, bridge source, `api_ops.py` | `tests/test_contract.py`, `contract/*.schema.json` |
| Version and contract numbers of the bridge | `gcode_bridge.py`, `VERSION`, `bridge-manifest.json` | `tests/test_bridge_manifest.py` |
| The files the installer copies | `install.sh`, `bridge_manifest.py` | `tests/test_bridge_manifest.py` |

## 13. What is enforced and what is only written

Kept honest on 2026-11-06 (bridge 3.8.0, service 2.30.4 plus branch `bridge-contract-2`). "Branch" = in `bridge-contract-2`, not merged, and
the readers marked there are NOT to be merged or installed before a test with the owner and the machine present.

| Promise | Status |
|---|---|
| Shape and keys of the state file | ENFORCED: the real bridge's output is validated against `state.schema.json` (`tests/test_contract.py`) and read by both readers through the vectors |
| Staleness 10 s / 15 s, unknown or garbage means "unknown" | ENFORCED in the adapter and the page reader (vectors). The service's own readers use it only in the branch |
| Every service reader goes through the adapter | Master: none. Branch: health poller, origin tracker, safe stop, bridge probe, jog, client count. Not yet: `jog_move`'s arithmetic (kept, parity-tested) |
| `contract` published by the bridge | Written in the code, NOT running: the bridge on the Pi (3.8.0, checked read-only on 2026-11-06) does not publish it until `install.sh` is run again |
| Page shows contract and unknown schema | Branch only (needs a service build, not done here) |
| Unknown schema for the jog | NOT DECIDED: the policy exists, default = today's behavior |
| Action file protocol (seq, answer, dedupe, unknown action) | ENFORCED by bridge tests; the service sender (`live_job_stop._send`) is tested; the page sender is not tested |
| Client wire (framing, `ok`, no unsolicited output, cache TTLs, ordering, port change without cutting clients) | ENFORCED (`test_public_wire`, `test_characterization`, `test_telnet`, `test_ordering`, `test_coalescing`) on loopback and fake sockets; not on a real client |
| Service never blocks the jog for an unknown or dead bridge | ENFORCED by parity tests of the readers (the rules of the jog itself are the old code) |
| Calls to the service (ops, header, queue, never delays a line) | ENFORCED (`test_characterization.ServiceCallTests`, `test_contract`); the local key's permissions are only read, not tested |
| Bridge version as an artifact (VERSION, manifest, hashes) | Branch: ENFORCED by `test_bridge_manifest` (a changed file without the manifest fails) |
| Installer: backup, rollback, refusal while in use | Branch: tested on a scratch root with fake `systemctl`, `sudo` and `python3`. NEVER run for real by me. The unit file and the polkit rule content are not tested |
| Start/stop through polkit, flag file, "refuse to turn off during a live job" | The handler refusal and the service side are tested (`test_bridge_service`); polkit and the flag as the unit sees them are not |
| Section 10 "MUST NOT" rules (the service never writes C1, never edits `bridge.json`, the bridge imports nothing of the service) | ONLY WRITTEN. The bridge importing nothing of the service is true today by reading; no test |
| Section 7 token permissions (640 `dsf:dsf`), user and group of the files on the SD | Verified once by read-only inspection of the Pi; no test |
| Real machine, real Duet, systemd, polkit, AppArmor | Nothing automated; only the real machine |
