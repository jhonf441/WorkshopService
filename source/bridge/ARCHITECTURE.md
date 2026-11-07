# Bridge as its own component: decision record

Status: proposed, 2026-11-06, branch `bridge-component`. Nothing in this record is installed or released. The bridge's behavior is
unchanged by everything in this branch except one additive key in its state file (section 9). The interface itself is in
`CONTRACT.md` (+ `contract/*.schema.json`); this file says why, what was checked, and how to get there without risk.

## 1. Context

The G-code bridge sits in the motion path of a real CNC / laser machine: external programs (cutting software, scripts, an ESP32) send
G-code to it over TCP port 23 and it feeds the Duet through DSF. It is already its own OS process and its own systemd unit
(`workshop-gcode-bridge.service`, `/opt/workshop-bridge`, user = the login user, not root, not `dsf`). It travels inside the
WorkshopService zip, and the service page controls it. The owner wants it to become a separate, independently installable and
versionable component, with a written contract with the service, WITHOUT changing what it does.

Two questions: (1) what exactly couples the two sides, (2) which run model is right: keep the systemd unit, or make the bridge a DSF
plugin like WorkshopVision and WorkshopRS485.

## 2. Evidence: why the bridge is a systemd unit

No document says "systemd, not plugin" in so many words: there is no earlier decision record. What exists:

* History. The bridge predates the service's control of it: `gcode_bridge.py` header says "formerly puente.py / duet-bridge"; it was
  imported as 3.0 on 2026-10-12 (`1724566`) and given its unit and `install.sh` the same day (`e106aed`, "systemd unit (alias
  taller-puente)"). The service learned to start/stop it on 2026-10-15 (`2949fe4` with sudoers, then `a5a59a8`: "polkit (sudo does not
  work from a DSF plugin)"). `docs-internal/PUBLICACION-DUET3D.md` B4 lists "sudoers, polkit y systemd fuera del zip" as a known review
  point, so the owner knows the cost of the current model.
* The code and the unit carry the technical reasons, each of which I checked on the Pi (read-only, machine idle, 2026-11-06):
  1. Port 23 (below 1024). The unit gives `AmbientCapabilities=CAP_NET_BIND_SERVICE` (the bridge process has `CapEff 0x400`, `NoNewPrivs 1`).
     A plugin process of the service has `CapEff 0`, `CapAmb 0`, runs as user `dsf` under `DuetPluginService`, and
     `net.ipv4.ip_unprivileged_port_start` is 1024. In addition the AppArmor profile DSF writes for every plugin
     (`/etc/apparmor.d/dsf.WorkshopService`, `.WorkshopVision`, `.WorkshopRS485`) lists only `capability dac_override, dac_read_search,
     sys_nice`: a plugin cannot be given `net_bind_service` even if systemd were willing. The only plugin permission that changes
     user is `superUser` (`DuetPiManagementPlugin` has `['superUser']` and runs under the root `DuetPluginService`): that is root, which
     the owner rules out (CLAUDE.md, unit comments, `HARDENING.md`).
  2. Real clients on port 23 exist (the PC `.16`, an ESP32, scripts: CLAUDE.md "Network", README). Changing the port is a change of the public protocol surface.
  3. The unit comment: "No Group=dsf on purpose: DSF treats every process whose primary group is dsf as a PLUGIN ('Failed to find
     plugin permissions') and cuts it", and `make_readable()` in the bridge (PR_SET_DUMPABLE, because binding a low port makes the
     process non-dumpable and DSF cannot identify it). The bridge lives as a non-plugin DSF client on purpose.
  4. Independent lifetime. A plugin install or reinstall restarts that plugin's process and deletes its folder (`PERMISSIONS.md`). The
     service ships often (2.29.x); a service update must never cut a live job: `CHANGELOG.md` line "a plugin install does not touch
     it", README "Do it with no live job running: restarting the bridge cuts its connections".
  5. Control without root: the service (user `dsf`, started by DSF without the right to change user) cannot `sudo`, so the install
     writes a polkit rule that allows exactly `start` / `stop` of this one unit.

## 3. Coupling inventory

Failure column = what happens today if the other side is dead, slow or sends garbage. "Pinned" = a test that fails if it changes.

| # | Direction | Mechanism (path, format) | Failure behavior today | Pinned by |
|---|---|---|---|---|
| 1 | bridge -> service, jog, page | `0:/sys/workshop/data/bridge-state.json`, JSON schema 2, every 2 s (1 s debug), atomic, mode 0664, owner login user group `dsf` | Reader errors are swallowed: unknown. `jog_move._bridge_file_does_s` -> `None` = jog free. `pending_orders` counts only if the file is under 10 s old, so a dead bridge cannot hold the jog. `live_job_stop.bridge_state` raises "bridge down" over 15 s old | `test_activity.test_state_file_schema`, `test_characterization.StateFileConsumerTests`, `test_contract`, `dsf/test_bridge_contract` (parity with `jog_move`), `test_jog_modal`, `test_bridge_job_end` |
| 2 | service/page -> bridge | `bridge-action.json` `{seq, action, ...}`; answer in state key `action` with the same `seq`; seq deduplicated; password actions scrubbed | Sender waits 10 s (stop_safe 150 s) then "no answer"; garbage / no seq / unknown action ignored or answered `ok:false` | `test_security.PageActionTests`, `test_characterization.ActionFileProtocolTests`, `test_contract.ConsumerOfTheActionFile`, `test_live_job_stop` |
| 3 | page/installer -> bridge; service reads port | `0:/sys/workshop/config/bridge.json`, reloaded when its mtime changes (~1 s); invalid values fall back | Bad file keeps previous settings. Service: `bridge_probe`, `health_poller.port_bridge` default 23 | `test_characterization.SettingsTests`, `test_paths`, `test_security` |
| 4 | service -> unit | `systemctl start/stop workshop-gcode-bridge.service` via polkit rule (`/etc/polkit-1/rules.d/49-...rules`, only user `dsf`, only that unit, only start/stop); flag `data/bridge-disabled` read by the unit's `ExecCondition`; `bridge_service.py` | No rule -> `can_control: false`, page read-only. No systemctl -> rc 127 handled. Turning off refused while a live job is open | `dsf/test_bridge_service` (6). `install.sh`, the unit and the polkit rule have NO test (gap) |
| 5 | service -> OS | `systemctl is-active / show ActiveEnterTimestamp(Monotonic)`, `ss` established connections on the bridge port; `bridge_watchdog` (why it started: boot / page / auto / stopped); state `events[].code == "restarting"` | `_sh` returns None on error; unit shown only if installed (`OPTIONAL`) | `dsf/test_bridge_watchdog` |
| 6 | service -> bridge TCP (client) | `bridge.test`: connects to the bridge port as a client, query commands only | Connect error -> API error to the page | none specific |
| 7 | bridge -> service | `POST http://127.0.0.1/machine/WorkshopService/api` `{op, args, origin:"bridge"}`, header `X-Workshop-Token`, 5 s; ops `job.start/end/cancel/close`, `motion.state`; queue of 50, 4 tries | Service dead: notices dropped/logged, no line waits; the service closes an idle live job itself. Machine gate fails OPEN on no answer | `test_characterization.ServiceCallTests`, `test_machine_gate`, `test_m118_job`, `test_contract` (ops exist) |
| 8 | service reads, bridge writes | Local key file `/opt/dsf/conf/workshop-api-token` (640 `dsf:dsf`); older `data/.api-token` no longer read (`test_security.LocalKeyTests`). I did not read its content | No file: no header, calls fail 401 -> notices lost, gate unknown | `test_security.LocalKeyTests` |
| 9 | bridge -> service, page | `data/live-interrupted.json` (+ `.bak`), service writes `live-interrupted-hidden.json` | Unreadable -> empty list | `test_safe_stop`, `test_live_job_stop` |
| 10 | implicit, DSF level | Orders the bridge sends through its own DSF `CommandConnection` (channel SBC, queries on `Telnet`) are seen by the service's interceptor: `jog_move.mark_bridge_si` (M3/M4/M5) and the bed-zone / laser guards | Service dead: DSF still runs the bridge's codes. Interceptor missing: the file signal (#1) remains | `test_jog_modal` |
| 11 | indirect consumers of #1 | `motion_owner` (jog, frame, bed-zone gating), `service_restart` ("do not restart while the bridge sends orders"), `origin_track`, and `laser_guard` (via `jog_move.bridge_activity_does_s`: **None counts as quiet**, so a dead or unreadable state lets the guard cut the laser power after 10 s quiet). Safety-relevant | see #1 | `test_motion_owners`, `test_laser_guard`, `test_origin_track`, `test_jog_modal` |
| 12 | page (browser) | `BridgeCard.vue` reads state and config and writes config, action and viewer files itself through DWC's `/machine/file/...`; units `workshop-gcode-bridge` / `workshop-bridge` in `health.services`; ops `bridge.test`, `bridge.service(.set)` (TECHNICIAN in `permissions.py`, `config.bridge` capability) | Page shows "down" from the file age | `test_identity`, `test_permissions_golden`; the page has no unit test |
| 13 | bridge knows service layout | `MATERIAL_MACRO_RE`: `M98` of `.../macros/laser/...`, `laserfocus.g`, `livemark.g` (changed once with the macro folders, `f61b28f`) | A renamed macro folder silently stops the "skip material macro" option | `test_skip_material_macro` (pins the regex, not the folder names in the service) |
| 14 | shared defaults, no shared constant | SD root: bridge `BRIDGE_SD_DIR` default `/opt/dsf/sd`, service `paths.py` `WORKSHOP_DSF_ROOT` default `/opt/dsf`; port default 23 in both | A machine with another DSF root needs both set | `test_paths`, `test_ports` |
| 15 | install / packaging | Zip ships `bridge/` (page card + copy of code); `bridge/install.sh` copies 3 files to `/opt/workshop-bridge`, makes SD dirs group-writable, writes unit + polkit, asks for a password / allow list; `tools/uninstall-system-rules.sh --bridge`; `docs/INSTALL.md` | Plugin install never touches an installed bridge (a stale bridge can run under a newer service) | none (shell) |
| 16 | permissions of the service | `launchProcesses` (systemctl, ss), `fileSystemAccess` (token, units); no `sbcPermissions` entry for the bridge | n/a | `docs/PERMISSIONS.md` (measured) |
| 17 | env vars | bridge: `BRIDGE_SD_DIR`, `BRIDGE_PORT`, `BRIDGE_EXCLUSIVE`, `BRIDGE_DEBUG`; installer: `BRIDGE_PASSWORD`, `BRIDGE_ALLOW`, `BRIDGE_TRUST`; service: `WORKSHOP_DSF_ROOT`. Imports: none either way (the bridge imports `live_stop`, `live_resume`, `dsf.connections`; the service never imports the bridge) | n/a | `test_paths` |

Documentation drift found while doing this (not fixed here: docs only, bridge README is shipped): the README says `order_timeout_s`
15 (the code default is 120 since `2f88127`), says "version 3.0.0" (code 3.8.0) and still mentions the `.api-token` fallback that
`96cffbd` removed. `test_characterization.SettingsTests` now pins the code values.

## 4. Feasibility of each run model

### (a) Systemd unit, kept, as its own versioned component

Feasible today: it is what runs. Every need is already met (table above). What it still lacks to be a real component: its own version
and release artifact, a manifest the service can check, an installer that is safe to re-run (backup + rollback, refuses while a live
job is active), tests for the installer and unit, and a contract (this branch).

### (b) DSF plugin (DWC page + SBC process in one zip)

| Need | Plugin model | Verdict |
|---|---|---|
| Listen on port 23 | Process has `CapEff 0` as user `dsf`; unprivileged port start is 1024; the plugin AppArmor profile allows only `dac_override`, `dac_read_search`, `sys_nice`. `superUser` is root. | BLOCKS. Works on a port >= 1024 (Vision 8095, camera 8090 are such ports) |
| User | Plugins run as `dsf` under `DuetPluginService`, profile per plugin; bridge today runs as the login user so as not to be a plugin process | Allowed, but it changes the identity of the process that talks to the motion hardware and widens `dsf` |
| Files (SD dir, token, config) | `fileSystemAccess` gives `/** rw` (measured, `PERMISSIONS.md`); `writeSystem` for `0:/sys` locks | Allowed |
| Network to DSF / clients | `networkAccess` gives `network` | Allowed |
| DSF connection with several code channels | `commandExecution`, `codeInterceptionReadWrite` as the other plugins; `dsf-python` would have to come from `sbcPythonDependencies`/venv (Vision, RS485 do) instead of the user's `~/.local` | Allowed |
| Install without sudo | Zip upload from DWC | Allowed (the real advantage: removes polkit rule, `install.sh`, `/opt/workshop-bridge`) |
| Start/stop from the page | DWC/DSF start and stop of plugins is native; the service already gates modules by `machine.enabledPlugins` | Allowed (not exercised by me; uncertain: whether DWC's plugin stop is safe with live clients) |
| Survive DSF restarts | Both models die with DSF (`Requires=duetcontrolserver.service` today; plugins are restarted by `DuetPluginService`) | Equal |
| `sbcAutoRestart` | Restarts the process after it exits; the bridge's `restart` action relies on `Restart=always` + `os._exit(0)`; whether `sbcAutoRestart` treats exit code 0 the same is UNCERTAIN (not verified) | Needs a test on the Pi |
| Independent lifetime from the service | Reinstalling the bridge plugin cuts clients and deletes its folder; a combined zip would cut live jobs at every service update | Acceptable only if the bridge is its OWN plugin zip, never inside WorkshopService |

## 5. Recommendation

Keep the systemd unit (model a) and make it a real, separately versioned component. Do not make it a DSF plugin now.

Reasons, in order of weight: (1) a plugin cannot bind port 23 and the only way around it (`superUser`) is root, which the owner
forbids; the alternative (move to a port >= 1024) changes the public client surface for the PC, the ESP32 and scripts, and the
byte-for-byte compatibility requirement rules it out for this task; (2) the bridge must outlive service updates and restart only
when the owner chooses, which a unit gives and a plugin zip does not; (3) it is the model already proven on this machine, and every
change of run model is a change in the motion path with no way to test it without the real machine; (4) the contract, the adapter
and the versioning achieve the decoupling the owner wants and do not need a change of run model.

What would make me change my mind: (i) the owner accepts a different port for clients (or a one-time NAT redirect 23 -> 2323, which
is root again and lives outside any zip), or DSF ships a permission for low ports; (ii) the project needs a public release that is
one sudo-less zip (`PUBLICACION-DUET3D.md` B4) badly enough to pay for (i); (iii) a Pi test shows `sbcAutoRestart`, plugin stop with
clients attached and a plugin reinstall behave at least as safely as `Restart=always`, polkit and a separate unit. Then the target
would be a separate `WorkshopBridge` plugin zip (never inside WorkshopService), installed beside it with the unit kept as a fallback
for one release.

No Taller plugin skeleton was prepared in TallerPlugins: the recommendation is not "package as a plugin". If the owner later wants
the bridge's page card moved out of the service zip into a page-only plugin, that is step 6 below and needs a decision.

## 6. The contract in short

Full text: `CONTRACT.md`. Eight channels (state file, action file, settings file, unit control, calls to the service, live-stop records,
debug heartbeat, client TCP). Versioned by `schema` (major, 2) and `contract` (1, new additive key, absent = 1). Inside a schema only
additions; readers ignore unknown keys and treat a missing key as unknown. Staleness is the age of the state FILE: under 10 s for
"pending orders", under 15 s for "bridge running"; anything unreadable, garbage, old or of an unknown schema is "unknown" and every
motion consumer fails open (jog free), the live stop fails closed. Service newer/older than bridge is a matrix in the contract; an
incompatible bridge keeps serving clients and the service falls back to its own signals. Client protocol frozen. Machine-checkable:
`contract/state.schema.json`, `contract/action.schema.json`, validated against the REAL bridge output in `tests/test_contract.py` and
`dsf/test_bridge_contract.py`.

## 6b. Non-goals and future

Speaking RepRap to its clients is the bridge's purpose (a TCP G-code port for a Duet), not a limitation. No dialect layer is planned,
and no configuration key, code or test for one exists. The only requirement is that the contract does not make one impossible: the
state and action files describe connections and the orders sent to the board, not any client text format, and the service never parses
client lines. If a second dialect is ever wanted, it must translate into the existing pipeline (never bypass the queue, owner and trust
rules, machine gate or live stop / resume), never report Idle while moving, never claim to cancel an accepted G1 (RRF cannot), treat a failed
laser-off as "the stop is NOT done", and map hold / resume conservatively; it would need its own design and tests then.

## 7. Behavior preservation

Every observable behavior that must not change, and the test that pins it. "New" = added in this branch, passing against the
unmodified bridge before the one-line additive change.

| Behavior | Pinned by |
|---|---|
| Client protocol: greeting `Connected!`, reply + `ok`, CR/LF or LF, line limit 1024 | New `test_characterization.WireTests` (real loopback sockets), `test_ordering.test_crlf_and_split_chunks`, `test_long_line_is_refused` |
| Telnet RFC 854/855/1143 handling, split UTF-8, NUL/IAC | `test_telnet` (all) |
| Ordering: arrival order, a query may overtake an order older than `overtake_ms`, an order never overtakes an order, a blocked client does not block another | `test_ordering` |
| Timeouts: `order_timeout_s` 120 (clamp 1..300), `query_timeout_s` 3 (0.5..30), queries on their own connection/channel, order link uses the order timeout | New `SettingsTests`; `test_query_channel`; `test_ordering.test_query_does_not_use_the_order_connection` |
| Queue behavior: per-client slots, coalescing and cache, stale answer, error after timeout | `test_coalescing` |
| A failed macro/probe order refuses the rest of the job, stops still pass | `test_failed_order` |
| Machine gate (paused/halted/not homed), fails open when the service does not answer | `test_machine_gate`; New `ServiceCallTests.test_the_machine_gate_does_not_block_by_guessing` |
| Status files the page and jog read | `test_activity.test_state_file_schema`; New `StateFileConsumerTests`, `test_contract`, `dsf/test_bridge_contract` |
| Call to the service (URL, body, header, ops, queue 50, never delays a line) | New `ServiceCallTests` |
| Action file protocol (seq, answer, dedupe, scrub, unknown) | `test_security.PageActionTests`; New `ActionFileProtocolTests`, `ConsumerOfTheActionFile` |
| Config path, reload on mtime, bad file keeps settings | New `SettingsTests`; `test_paths`; `test_security` |
| SD data dir layout and file names | `test_paths`; New contract tests (names in the schema/text) |
| Port change without cutting clients | New `WireTests.test_a_port_change_keeps_the_connected_clients` (real sockets) |
| Security: no order from the network without password / allow list / trusted address, scrypt, blocking | `test_security` |
| Live stop and resume: laser-off failure means the stop is NOT done; resume verified by hash; the rest of a stopped job refused | `test_safe_stop.test_the_laser_off_failing_means_the_stop_did_not_happen`, `Resume` tests, `test_live_resume` |
| Live job marks (`M118 P0 S"BRIDGE JOB ..."`), never reach the board | `test_m118_job`, `test_activity` |
| Jog never blocked by a dead bridge; laser guard / motion owner readings | `test_jog_modal`, `test_bridge_job_end`, `test_motion_owners`, `test_laser_guard`; parity in `dsf/test_bridge_contract` |
| Start/stop from the page, flag file, polkit rule, `install.sh` | `dsf/test_bridge_service` (service side only). NOT PINNED: `install.sh`, unit file, polkit rule (shell, root, systemd): step 3 adds a tested installer |
| Real DSF, real Duet, real clients, systemd, polkit, AppArmor | NOT PINNED by any automated test; only the real machine |

Baseline before any change (unmodified master `bab0705`, Windows dev PC): see section 11. The coordinator's note that `?` and an empty line answer as help was checked: not true today (see the row above); the tests pin what the code does.

## 8. Migration plan (strangler)

The installed Pi keeps working at every step: `/opt/workshop-bridge`, the unit name, the polkit rule, `bridge.json`, the data files
and the port do not move in steps 0 to 4. Each step ships alone and has its own rollback. Only step 6 (optional) changes a layout.

| Step | What | Touches the bridge in production? | Rollback |
|---|---|---|---|
| 0 | This branch: characterization tests, `CONTRACT.md`, schemas, `dsf/bridge_contract.py` (called by nothing), `"contract": 1` in the state file | The key appears only after the next `sudo ./install.sh`; until then nothing changes. A service zip with the new module is inert | Drop the commit. A bridge that already writes `contract` can run under an older service (it ignores unknown keys; pinned by the compatibility tests) |
| 1 | Move the readers onto the adapter, one per release, in this order: `health_poller` (port, clients, events), `live_job_stop`, `origin_track`, then LAST and only with the owner and the machine: `jog_move` (and through it `motion_owner`, `laser_guard`, `service_restart`). Each move needs a differential test on recorded real states (the Pi's own file can be copied read-only) | No | Revert that one release. Old readers stay until the last one moves |
| 2 | Version the bridge as an artifact: `bridge/VERSION`, `bridge-manifest.json` (version, contract, file list, sha256), a script that makes `workshop-bridge-<ver>.tar.gz`. The service zip keeps shipping `bridge/` as today | No | Nothing to roll back; the old path still installs |
| 3 | Installer safety, tested on a scratch root with a fake `systemctl`: back up `/opt/workshop-bridge` to `.prev` before copying; `install.sh rollback`; refuse (or ask) while the live state says a job is active or orders arrived in the last 30 s (today `install.sh` restarts the unit unconditionally and cuts clients); `status` subcommand printing installed version and contract; keep polkit/unit rewrite idempotent | Yes, on the next install: owner runs it with no live job, from a terminal | `install.sh rollback` (new), tested in step 3 itself before use |
| 4 | The service shows installed bridge version, contract and `health()` (`ok`, `newer`, `incompatible`, `down`) on the card; a version mismatch is a warning, never an action | No | Revert the service release |
| 5 | Optional: split `docs` and the page card so the bridge README, CONTRACT and installer live in a bridge-only folder that a release job publishes separately (a second git repo or tag) | No | none needed |
| 6 | Optional, owner decision: page-only Taller plugin `WorkshopBridge` for the card; or plugin model (b) if the section 5 conditions are met | Page-only plugin: no. Plugin model: yes, high risk, needs the real machine | Keep the unit installed; switch back by re-enabling it |

Upgrade of an existing install in practice (steps 2 to 3): owner stops cutting jobs, copies the new `bridge/` to the Pi, runs
`sudo ./install.sh` (backup, copy, daemon-reload, restart: clients reconnect in about 3 s because of `RestartSec=3`; the cutting
program reconnects and sends `BRIDGE JOB START` again), checks `status`, and the page card shows the new version. `bridge.json`
(password hash, allow list, names, port) and the `data/` files are never touched by `install` (README: "nothing is deleted";
`do_guard` only edits `bridge.json` when asked). Rollback: `install.sh rollback`, or by hand copy `/opt/workshop-bridge.prev/*.py`
back and `systemctl restart workshop-gcode-bridge`.

## 8b. Step 1 status (branch bridge-migrate-1) and the recipe for the safety readers

Moved onto `dsf/bridge_contract.py`, one commit each, parity tests first (`dsf/test_bridge_readers_parity.py`, passing before the move):

| Reader | Why it is not a safety path | What changed (healthy bridge: nothing) |
|---|---|---|
| `health_poller.programs_bridge`, `_events_bridge_recent` | Page display and the Activity record of why the bridge restarted | A stopped bridge (state older than 15 s) no longer lists the programs it had when it died; an unknown schema is not read; the restart event still reads an OLD file on purpose (the bridge leaves 1.5 s after writing it); a non-dict event is skipped instead of raising |
| `origin_track.bridge_clients` | Only names the program behind an API call | Unknown schema lists nothing; non-dict items are dropped |
| `live_job_stop.bridge_state` | The reader only decides whether the operation is offered; it fails closed (refuses) and `M112` never depends on it. The action file protocol of `_send` is untouched | Unknown schema, or a `live_stop` that is not an object, is refused as "bridge too old to have this" instead of being acted on or raising |
| `handlers/bridge_probe._port` | Diagnostic probe, queries only | Unknown schema: port 23 |

Classified as safety and NOT moved (code unchanged): `jog_move` (`bridge_state_age_s`, `_bridge_file_does_s`, `bridge_activity_does_s`,
`_clients_bridge`), `laser_guard` (through `main.py` -> `jog_move.bridge_activity_does_s`), `motion_owner` (`_bridge_age`, `_bridge_clients`),
`service_restart` (through `motion_owner`), and `health_poller.port_bridge` / `clients_bridge`, because the jog's no-limits check and
the motion owner use that connection count: a state of an unknown schema must keep giving its port, or the count would silently fall to
port 23. The page (`BridgeCard.vue`) reads the files in the browser through DWC and cannot use the Python adapter; its rules (age of the
file, relative ages) are in `CONTRACT.md` and a JS port is a separate task.

Recipe for the safety readers (owner and machine present; one reader per release; each release revertible alone):

1. Freeze the current answers: copy the real `bridge-state.json` of the Pi read-only at several moments (idle, client connected, live job
   running, order pending) and the file of a bridge stopped for more than 15 s; keep them as fixtures. Never copy secrets (the state has
   none).
2. Parity tests, before any edit, for each function: `bridge_state_age_s` (already in `test_bridge_contract.Parity`), `_bridge_file_does_s`
   (1 s cache, file age, missing / garbage -> None), `bridge_activity_does_s` (min of the SBC mark and the file, `_bridge["end"]` cut
   of 3 s after a job end), `_clients_bridge`, `motion_owner._bridge_age/_bridge_clients`, `laser_guard` decision table fed with each fixture
   (None = quiet, 10 s quiet threshold), `service_restart.default_motion`. Same inputs, same outputs, including dead / garbage / old /
   unknown schema. Cases that would change must be listed as `Changed*` tests with the reason, and for these readers the decision is the
   owner's.
3. Move `jog_move._bridge_file_does_s` first (read through `bridge_contract.read_state` + `orders_age_s`; keep the 1 s cache, keep `None`
   on any failure). Unknown schema: the adapter says `None`, i.e. "free", exactly as a dead bridge, and the SBC M3/M4/M5 mark still
   protects; the owner decides whether that is acceptable or whether unknown must instead block (not decided here).
4. Then `health_poller.port_bridge` with an explicit rule for unknown schema (read `port` anyway, i.e. extend the adapter with a lenient
   `port` that works on an incompatible file) so the client count cannot drop.
5. Then `motion_owner` (no logic of its own: it calls `jog_move`), `laser_guard` (no change in `laser_guard.py`: it receives a number or
   `None` from `main.py`; verify the call site only), `service_restart`.
6. On the machine, with the owner: laser job through the bridge, jog refused during it and free after 20 s, laser guard cuts power only
   when the bridge is quiet, bridge stopped mid-job (jog must not stay blocked, guard behavior as before), bridge restarted from the page.
7. Revert plan: each step is one commit in one service release; reverting restores the old reader byte for byte (kept in git).

## 8c. Steps 2 and 3 and the enforcement of the contract (branch bridge-contract-2)

* Step 2, the bridge as an artifact: `bridge/VERSION`, `bridge/bridge-manifest.json` (version, contract, schema, sha256 per file of what the
  installer puts on the Pi) and `bridge_manifest.py check|write|show`. `tests/test_bridge_manifest.py` fails when a file of the bridge
  changes without the manifest, so one release is one version, one contract and one list of hashes. What gets installed is unchanged.
* Step 3, installer safety: `install.sh` backs the installed code and unit up to `/opt/workshop-bridge.prev` before copying (one generation;
  the same code twice keeps the older backup), has `rollback` and `status`, and install / rollback / uninstall REFUSE (exit 3, `--force`
  overrides) while the fresh state says a live job is open, orders are pending or one arrived in the last 30 s. Tested on a scratch root with
  fake commands (`tests/test_install_sh.py`); never run on the Pi by me. The page already told the owner to run `install.sh rollback`:
  that command did not exist before this branch.
* Enforcement: `contract/vectors.json` is the single source of the reading rules, run by the Python adapter and the new page reader
  (`dwc36/bridge-contract.js`); every non-safety reader and the safety readers (jog, client count) go through the adapter in the branch;
  the unknown-schema policy for the jog is named (`UNKNOWN_SCHEMA_JOG`) and left at today's behavior. The honest table of what is enforced and
  what is only written is `CONTRACT.md` section 13; the values both sides copy and their guards are section 12.
* Open owner decisions: the unknown-schema policy for the jog (and its message); when to install the bridge that publishes `contract`
  (it needs an `install.sh` run with no job); whether the bridge README should state the contract number.
* Not merged and not to be installed before a test with the owner and the machine present: the jog and client-count readers
  (`jog_move`, `health_poller.port_bridge`), because they sit on the safety path.

## 9. What Phase B changed (this branch)

* `bridge/tests/test_characterization.py` (new, 21 tests, written and passing against the unmodified bridge first).
* `bridge/contract/state.schema.json`, `action.schema.json`, `bridge/tests/schema_check.py`, `bridge/tests/test_contract.py`.
* `dsf/bridge_contract.py` + `dsf/test_bridge_contract.py` (read-only adapter, nothing calls it), listed in `plugin.json` `dsfFiles`.
* `gcode_bridge.py`: two lines, `CONTRACT = 1` and `"contract": CONTRACT` in `build_state`. This is the only change to bridge code.
  It is not on the order path (the state writer runs in the tick thread, on a copy of already-built data); no reader uses the key;
  the file stays valid for every existing reader (they ignore unknown keys; `test_state_file_schema` and the parity tests pass). It
  is strictly additive and gives the service a way to tell which contract a bridge speaks. It takes effect only at the next install.

## 10. Risks

* A stale bridge under a new service is normal today (plugin installs do not update it). The contract and `health()` make it visible; it does not make it impossible.
* Moving `jog_move` / `laser_guard` onto the adapter (step 1) touches safety logic: `None` means "quiet" for the laser guard and "free" for the jog, and the adapter keeps that, but only parity tests protect it. Do it last, with the machine.
* The "rounded to 6 digits" note in `jog_move` / `live_job_stop` could not be reproduced from the file on the Pi (the file holds full-precision floats). It happens somewhere between the file and a consumer (probably the browser). UNCERTAIN where; the contract avoids absolute epochs on purpose.
* `install.sh`, the unit and the polkit rule have no automated test (step 3). Anything about systemd, polkit and AppArmor here is verified by reading and by read-only inspection of the Pi, never by running the installer.
* Plugin model: `sbcAutoRestart` semantics with exit code 0, and DWC plugin stop with attached clients, are UNCERTAIN.
* The `Connected!` greeting and byte-level reply format are pinned only for the plain path on loopback; Telnet negotiation is pinned by `test_telnet` on fake sockets, not on a real client.

## 11. Verification record

Verified: unit and characterization tests (baseline and after, below); code reading of both sides; read-only Pi inspection
(2026-11-06, machine `idle`, no job): `ps`, the unit text, `/proc/<pid>/status` capabilities of the bridge and a plugin process,
the AppArmor profiles of three plugins, the manifests' `sbcPermissions`, listening sockets, file owners and modes in
`/opt/dsf/sd/sys/workshop/{config,data}` and `/opt/dsf/conf` (names only; no token, secret or user file was read), the state file keys.
NOT verified: any behavior that needs the real machine, the real Duet, the cutting PC or ESP32, `sudo`, polkit decisions (the rule
file is root-only readable), a running `install.sh`, a plugin-model prototype, DWC plugin start/stop semantics.

Baseline and after (Windows PC, python 3.13):

Full per-file runs, `python -m unittest <module>` for each of the 136 dsf test files plus `bridge/tests`, same PC:

| | Before (master `bab0705`) | After (branch head) |
|---|---|---|
| `bridge/tests` | 182 tests, OK | 220 tests, OK (+38 new: characterization 21, contract 9, public wire 8) |
| `dsf/test_*.py` | 136 files, 0 failing files in the full tree (see note) | 137 files (+ `test_bridge_contract`, 23 tests), 0 failing files |
| Every pre-existing test | all pass | all pass; none weakened, none deleted, none changed |

Note on the baseline: my first baseline ran on a partial `git archive` (only `dsf`, `bridge`, `plugin.json`) and nine files failed there
only because the archive lacked `docs/`, `dwc36/`, `tools/`. On a full archive of `bab0705` (without `dwc-src`) six of those nine pass
and `test_catalog_accents`, `test_modules_process`, `test_published_texts` still fail because they need `dwc-src` (the paused DWC 3.7
copy, which I may not copy or touch); they pass in the branch worktree, which has it. So no test fails after that did not pass before,
and none was changed. `test_bridge_job_end` hangs when combined with other modules in one `unittest` call, on master too (it is a
script-style module); run alone it passes.

