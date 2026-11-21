# Development environment of the service page (E2)

The page with sessions, roles, writes and errors, WITHOUT the machine and without creating accounts on it. Nothing here is packed in the plugin zip
(`tools/build_36.py` ships `dwc36/` and the `dsfFiles` only) and nothing here can reach the machine.

## One command

    python tools/dev/run_sim.py --scenario users --rows 120 [--lang en] [--dark] [--open]

prints two addresses:

- the API: `http://127.0.0.1:18765/machine/WorkshopService/api` (control surface: `/__dev/state`)
- the page inside a real DWC 3.6: `http://127.0.0.1:18766/Plugins/WorkshopService`

`--api-only` starts only the API (tests in node, contract checks). Stop with Ctrl+C. The control surface is also reachable through the page's address
(`http://127.0.0.1:18766/__dev/...`), so a browser test needs one origin only.

Which page is served: `--build NAME` takes the compiled DWC of `dist/sim/<NAME>` (default `dwc`). One folder per build somebody is looking at:

| Folder | What it holds | Who writes it |
|---|---|---|
| `dist/sim/v0` | the page as it was before the redesign (2.51.5), for comparisons | built once |
| `dist/sim/dwc` | the build handed over for the validation point that is open (today: the same as `v0`) | the developer, only when handing a point over |
| `dist/sim/work` | the developer's work in progress (`python tools/dev/sim_build.py`) | the developer, at any time |

Two people can run the environment at once on different ports (`--api-port`, `--port`); each run has its own throwaway data folder.

## The pieces

| File | What it is |
|---|---|
| `api_server.py` | HTTP on 127.0.0.1: the API entry, same body and answers as on the machine, plus the control surface `/__dev/` (its docstring lists every path). |
| `dev_backend.py` | The REAL registry of `dsf/` (roles, sessions, validation, confirmations, conflicts, audit, database, texts) over stand-ins: a bridge that sends nothing and records every code, an invented object model, heartbeats beaten by hand. It also closes the ways out (see Safety). |
| `dev_seed.py` | The scenarios: `open` (nobody created, everybody is an administrator), `users` (one person per role, a custom role with a denial, three keys), `anonymous` (the same, a caller with no session reads as a viewer), `damaged` (people file unreadable: fails closed). People and PINs are in `GET /__dev/state`. `rows` = rows seeded in activity, received commands and audit; `broken_chain` tampers one audit row. |
| `dev_fixtures.py` | Example values of the published data only a process of the Pi writes (guard, Pi health, black box, configuration guard, risks, live job), built BY HAND with the documented shapes, and the notices a test can switch on one at a time. |
| `dwc_sim.js` | A real DWC 3.6 against a pretend DSF: serves `dist/sim/dwc`, speaks the SBC protocol DWC needs (connect, object model over WebSocket with patches, files of the SD card, codes recorded) and passes the API on to `api_server.py`. Proof of concept: see Limits. |
| `sim_build.py` | Fast build of the page in a FREE clone of the DWC pool (`TALLER_DWC_SRC_36`) and copy of the compiled DWC to `dist/sim/<name>` (default `work`; `python tools/dev/sim_build.py v1` for a validation point); puts the clone back as git has it. Run it after changing `dwc36/` to see the change in the simulator (`run_sim.py --build work`). |
| `test_dev_env.py` | The environment's own tests: `python tools/run_tests.py --cwd tools/dev -- python -m unittest test_dev_env`. |

## What a test can do through `/__dev/`

| Need | Call |
|---|---|
| Start from a known state | `POST /__dev/seed {"scenario": "users", "rows": 51}` ; `POST /__dev/reset` repeats the last seed |
| An error on demand | `POST /__dev/fault {"op": "users.list", "kind": "error", "code": "busy", "times": 1}` ; kinds: `error` (any code of the service, with its real status), `http` (bare 502 / 503), `delay`, `garbage` (200 that is not JSON), `drop` (connection closed); `op: "*"` = every operation ; `DELETE /__dev/fault` |
| A session that expires | `POST /__dev/clock {"advance_s": 46800}` |
| ONE notice on a healthy machine | `POST /__dev/published {"_notice": "unclean_shutdown"}` ; names in `GET /__dev/state` (`notices`): process_error, process_late, process_stopped, safety_down, vision_down, database_damaged, backup_late, unclean_shutdown, unclean_shutdown_hidden, channel_warning, risk, live_job, config_rollback_armed, wifi_weak, disk_low ; `"none"` = healthy again |
| A process that fails, a published value that changes | `POST /__dev/published {"_process": {"jobs": "it crashed"}, "airAssist": true}` |
| A global of the board | `POST /__dev/published {"_global": {"powerOffOnFinish": false}}` (a `set global.x = ...` the service sends changes it too) |
| The machine busy | `POST /__dev/machine {"state": "job"}` (idle, job, live, off) ; `{"restart": "never"}` makes `service.restart` be accepted and not happen, `"gone"` makes the service not come back |
| What the board answers | `POST /__dev/replies {"M115": "FIRMWARE_NAME: ..."}` ; `GET /__dev/codes` = what the service would have sent |
| What the page really sent | `GET /__dev/requests?since=N` (operation, arguments, headers, status, the fault applied) |

## Safety

- Both servers listen on 127.0.0.1 only and refuse any other caller.
- The API process may only connect to this computer: any other address is refused before a packet leaves (`dev_backend.isolate`), so the machine,
  the power meter and the notification service cannot be reached even if a setting pointed at them. It launches no program and cannot end itself
  (`service.restart` is simulated). What was refused is listed in `GET /__dev/state` (`blocked`).
- Every file lives in a throwaway folder; the PINs and keys of the seed exist only there.

## Limits (say so when reporting a result obtained here)

- The processes of the service do not run, except two loops that need no board and that a page checks its writes against: the shutdown timer
  (`shutdownTimer`) and the owner of the movement (`motion`). The rest of the published data has three sources: the service's own code called once
  (`communication`, `notifications`, `machine`, `shutdownMethod`, and `servicesInternal` from heartbeats beaten by hand); values built by hand with
  the documented shapes (`dev_fixtures.py`: `guardStatus`, `healthPi`, `boxBlack`, `configGuard`, `riskActive`, `liveJob`, `jogFree`, `jogBlock`);
  and `null` for the keys other plugins' processes own (`bedZones`, `pelletLayers`, `motorReport`, `consumptionCurrent`, `ledStrip`, `lightsInfo`,
  `statusIndicator`). None of it is a capture of a real machine: a case that passes here on that data proves the page, not the service.
- `powerOffOnFinish` (published) stays `null` until `power.after_job` is called, as on the machine; the truth is the global of the board, which the
  pretend board updates when the service sends `set global.powerOffOnFinish = ...`.
- The request log keeps no secret: a PIN, password or key argument is `***` and a token is its first 6 characters.
- The object model of the machine is a small invented one (`dev_backend.default_model`), not a capture: operations that need the board answer what
  the script says (`/__dev/replies`) or fail.
- The G-code bridge, a real power cut or restart, the camera, Vision and the timings of the Pi: only on the machine.
- The simulator loads the page as a BUILT-IN plugin of the DWC it serves (same webpack build), not through the installer of plugins: installing,
  `enabledPlugins` and the cache of the service worker are not exercised. The other plugins of the family (the control bar, the shared PIN dialog of
  another plugin) are not there.
- The DWC session is not checked: a request that carries `X-Session-Key` counts as a DWC session, any other as an open call.

## Layout audit: which widths

`tools/dev/layout_audit.js` (see its header) is run in every place at 390, 1097x617, 1280 and 1920 px. Besides overlap, edges and contrast it checks the forms: `formgap` (sibling fields of one row more than 48 px apart) and `formbase` (the action of a row more than 4 px off the base of its input). A form row is made with `SvFormRow` (`dwc36/ui`), never with the 12-column grid.
