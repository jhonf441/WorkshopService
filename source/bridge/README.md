# Workshop G-code bridge

A Telnet-style server on the Pi that lets an external program (cutting software,
a terminal, a script, an ESP32) send G-code to the Duet through DSF. Each line gets
the machine's reply followed by `ok`. It is a separate systemd service, not part of the
WorkshopService plugin package; the Services page of the plugin shows and controls it.

Source: `gcode_bridge.py` (version 3.0.0). Python 3, standard
library plus `dsf-python` (`dsf.connections`), which is already on the Pi.

## Install (once, on the Pi, needs sudo)

From the `bridge` folder of this repository:

```
sudo ./install.sh
```

It copies the code to `/opt/workshop-bridge`, makes sure `0:/sys/workshop/config` and
`0:/sys/workshop/data` are writable by the dsf group, writes the unit
`workshop-gcode-bridge.service`, enables it and starts it, and writes the polkit rule that lets
the Services page start and stop only that unit. Update later by running the same command again.

Equivalent manual steps (what the script does):

```
sudo install -d -m 755 /opt/workshop-bridge
sudo install -m 644 gcode_bridge.py live_resume.py live_stop.py /opt/workshop-bridge/
sed -e "s#__USER__#$USER#" -e "s#__DIR__#/opt/workshop-bridge#" -e "s#__SD__#/opt/dsf/sd#" workshop-gcode-bridge.service | sudo tee /etc/systemd/system/workshop-gcode-bridge.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now workshop-gcode-bridge
```

Do it with no live job running: restarting the bridge cuts its connections.

## Files

| File (on the SD, `0:/sys/workshop/...`) | Purpose |
|---|---|
| `config/bridge.json` | Settings, reloaded when the file changes (port change reopens the socket without cutting clients). |
| `data/bridge-state.json` | State, health and activity, written every 2 s (1 s while debug is on). |
| `data/bridge-action.json` | Actions from the page: `{"seq": n, "action": "...", ...}`. |
| `data/bridge-viewer.json` | Heartbeat of the page's Debug view; only its modification time matters. |

The action file is created if missing; the state is regenerated.

### Settings (`bridge.json`)

`port` (23), `exclusive` (true), `queries` (M114, M115, M105, M119, M122, M408, M503, M27, M20, M36),
`names` ({ip: name}), `extended_greeting`, `debug`, `debug_timeout_min` (30),
`allowed` ([] = local network only), `trusted`, `password_hash`/`password_salt`
(`scrypt$<hex>` with the salt in `password_salt`; the older plain sha256(salt + password) is still accepted until the password is set again), `max_connections` (8), `password_attempts` (5),
`block_seconds` (300), `blocked`, and the line-handling knobs:
`order_timeout_s` (15), `query_timeout_s` (3), `query_cache_ms` ({code: ms}; defaults
M114 500, M408 500, M105 1000, M119 1000, M27 1000, M36 2000, M20 5000, M122 5000, M503 30000,
M115 60000; 0 disables the cache for a code), `query_soft_ms` (500), `query_stale_s` (5),
`overtake_ms` (500), `query_workers` (2).

## How lines are handled

* Each received line becomes a slot in a per-client queue. Replies are written in arrival
  order. A query or a local answer may overtake an order that has waited longer than
  `overtake_ms`, so a console keeps answering while a long move blocks the machine; an order
  never overtakes an order.
* Orders run in a per-client worker with its own DSF connection and `order_timeout_s`.
  Queries use a small shared pool of DSF connections with `query_timeout_s`; nothing queued
  behind a long move can block them.
* Identical queries from all clients are coalesced into one Duet request and answered from a
  short cache (the cache key is the line with only the code upper-cased). If the machine is
  slow, after `query_soft_ms` a cached answer younger than `query_stale_s` is served; with no
  usable cache the client gets `Error: ...` and `ok` after the query timeout. Counters per
  client: `cache_hits`, `coalesced`, `stale_served`, `overtaken`.
  A cached M114 can be up to 500 ms old: set `"query_cache_ms": {"M114": 0}` if a script needs
  the position right after its own move.
* `G0`/`G1` with no parameters are answered `ok` locally (automatic pings).

## A failed macro or probe stops the job (3.7.0)

If a `M98` (macro call), `G30`, `M280`, `M401` or `M402` is answered with `Error: ...` (the Z probe did not trigger, the BLTouch gave an alarm, a macro called `abort`, ...), the rest of the job is refused for 120 s: every order except the stops (`M5`, `M0`, `M25`, `M112`, `M999`) gets `Error: an earlier order of this job failed (...)`. The program keeps streaming, but nothing runs without the focus, origin or probe that order had to set up. The live job of that client is closed as cancelled. `BRIDGE JOB START` or `BRIDGE RESUME` clear it earlier. Other orders with an error (a `G1` out of limits) do not stop the job.

## Telnet compatibility (3.6.0)

The port speaks plain lines (`G-code` + CR/LF, reply + `ok`), and a real Telnet client works too (RFC 854/855/1143):

* The bridge never starts a negotiation, so cutting software, scripts and ESP32 boards see exactly what they saw before.
* If the client negotiates (PuTTY, `telnet`, `nc -t`), every option is refused once (`DO x` -> `IAC WONT x`, `WILL x` -> `IAC DONT x`), option bytes and `IAC SB ... IAC SE` never reach the G-code, `IAC IAC` is a literal byte 255 and NUL bytes (the NVT sends `CR NUL` for a bare Enter) are dropped. Before 3.6.0 those bytes landed in the first line, in front of the first G-code.
* A character split between two reads is no longer lost (incremental UTF-8 decoder).
* The Spanish command words (`PUENTE`, `AYUDA`, `CLAVE`, `TRABAJO`...) are not commands any more: the bridge only understands `BRIDGE HELP`, `BRIDGE KEY`, `BRIDGE JOB` and the other English ones.

## Debug mode

Turn it on from the Services page (Debug panel) or with `{"action": "debug", "on": true}`.
While on, the last 300 lines (received lines, replies, Duet timings, cache/coalescing
decisions, events; passwords masked) are kept in memory and published in `bridge-state.json`
under `debug`. They are **not** written to the journal, which only gets warnings and errors.
It turns itself off after `debug_timeout_min` minutes. While the page has the Debug panel open
it rewrites `bridge-viewer.json` every 10 s; the bridge sees the new modification time and
pushes the deadline forward by `debug_timeout_min`. When it switches off it also saves
`debug: false` in the settings.

## State file schema (version 2)

Top level: `schema` (2), `version`, `seq` (changes every write), `time` (epoch), `clock`,
`uptime_s`, `port`, `error`, `exclusive`, `owner`, `owner_id`, `owner_since_s`, `clients[]`,
`totals{}`, `history[60][orders, queries, rejects, connections]`, `duet_ms_avg`, `duet_ms_max`,
`order_ms_avg`, `query_ms_avg`, `events[]` (`time`, `type`, `code`, `args`, `text` in English),
`security{password, allowed, local_only, trusted, max_connections, password_attempts,
blocked[], rejected[]}`, `action` (`{seq, ok, code, text, time}` of the last page action),
`debug{active, timeout_min, remaining_s, viewer_seen_s, last_id, lines[]}`, `activity{}`.

`clients[]`: `id` (`ip:port`), `name`, `ip`, `port`, `connected_s`, `idle_s`, `lines`, `orders`,
`queries`, `rejects`, `cache_hits`, `coalesced`, `stale_served`, `overtaken`, `bytes_rx`,
`bytes_tx`, `last` / `last_age_s` (last line of any kind), `last_order` / `last_order_at` /
`last_order_age_s` (last non-query line), `last_motion_at`, `pending_orders`, `control`,
`role` (`control`, `listener`, `no_password`), `trusted`, `name_saved`.

### `activity` (what the movement safety logic reads)

```
"activity": {
  "generated_at": 1791860562.77,   // epoch when this file was written
  "clients_connected": 1,
  "pending_orders": 0,             // non-query lines sent to the machine and not finished
  "last_order_at": 1791860560.25,  // epoch of the last non-query line (received OR finished), null if none
  "last_motion_at": 1791860560.24, // same, only for G0-G3, G5, G28-G32, G38, M3, M4, M5, M24, M32, M98
  "live_job": {"active": false, "name": null, "since": null, "client": null,
               "last_event_at": null, "ended_at": null, "end_reason": null}
}
```

Times are absolute, so a reader does not depend on the file's modification time. Queries,
`BRIDGE ...` commands, empty `G0`/`G1` pings and rejected orders are not activity.
`live_job` follows the bridge commands `BRIDGE JOB START [name]` (start) and
`BRIDGE JOB END`, `BRIDGE JOB CANCEL`, `BRIDGE JOB CLOSE` (end; `end_reason` `end`, `cancel` or
`close`). They are
answered by the bridge and never reach the board. It also ends with
`end_reason: "disconnect"` when the client that started it was the last one connected.
Each start / end is also sent to WorkshopService through its API (`job.start`, `job.end`,
`job.cancel`, `job.close`; a disconnect closes the job at its last activity), in the
background with retries, using the local key `/opt/dsf/conf/workshop-api-token` (older installs: `0:/sys/workshop/data/.api-token`, read as a fallback)
Put the two
lines in the start / end G-code of the sending program.
`dsf/jog_move.py` (`bridge_state_age_s`) uses `pending_orders` (only if the file is less than
10 s old, so a dead bridge cannot block the jog) and `last_order_at`; `dsf/origin_track.py` matches
clients by `last` and `last_order`.

## Security (tested in `tests/test_security.py`)

Allowed IPs (default: private and loopback only), trusted IPs, optional password for orders
(`BRIDGE KEY <password>`; queries always pass), IP blocked after `password_attempts` wrong
passwords for `block_seconds`, blocking from the page (persisted, cuts all connections of the
IP), maximum connections, maximum line length (1024), exclusive control with
`BRIDGE USE` / `BRIDGE RELEASE`. Passwords are stored as a salted scrypt hash and never appear in
events, the state file or the debug buffer. Commands are `BRIDGE HELP|STATUS|LIST|NAME|USE|RELEASE|KEY`;
only the English words exist. Replies sent to
the external program are in English.

## Tests

```
cd bridge/tests
PYTHONDONTWRITEBYTECODE=1 python -m unittest
```

They use a fake clock, a fake Duet and fake sockets (nothing touches the SD or the network):
ordering and overtaking, coalescing and cache, debug ring and auto-off, path migration,
activity reporting, security and page actions.

## Helper scripts

`scripts/status.sh`, `scripts/restart.sh`, `scripts/logs.sh` (journal of the unit).

## What to paste in the cutting program (live jobs)

In the device profile of the program that sends the job, paste these lines in the start G-code and in the end G-code:

```
Start G-code:   M118 P0 S"BRIDGE JOB START Trabajo en vivo"
End G-code:     M118 P0 S"BRIDGE JOB END"
If it is cut:   M118 P0 S"BRIDGE JOB CANCEL"
```

`M118` is a real G-code (it prints a message), so the same file can also be uploaded to the Duet without errors. The bridge recognises the text, marks the live job and does not send the line to the board. The short form `BRIDGE JOB START Trabajo en vivo` also works through the bridge, but a file that contains it cannot be uploaded to the Duet. The same lines are shown, with a copy button, in the service page (G-code bridge > Commands).

## Safe stop and resume of a live job (3.8.0, 2026-10-22)

Needs `live_resume.py` and `live_stop.py` next to `gcode_bridge.py` (`install.sh` copies them; without them the bridge works as before and answers
"no safe stop"). Design and operations: `TallerPlugins/docs-internal/LIVE-JOB-STOP-RESUME.md`.

- While a live job runs the bridge keeps a journal of the lines that reached the board: a count, a SHA-256 of the normalized lines (comments out,
  upper case), a checkpoint of the hash every 50 lines, the modal state (G90/G91, G20/G21, WCS, F, S, M3/M4/M5, M7/M8/M9), the path done and the
  bounding box of the cut. The lines of the stops (M5 M0 M25 M112 M999), queries, `BRIDGE` commands and the skipped material macros are not counted.
- Page action `stop_safe` (written in `data/bridge-action.json` by the service): the lines that come after are refused, what the board already
  accepted finishes, `M5` goes on a private connection, `M114` reads the head, the record is saved in `data/live-interrupted.json` (+ `.bak`, the
  last 5) and the live job is closed in the service as "stopped". It is NOT the emergency stop: `M112` works as before, nothing is cancelled and the
  power is not cut. If the laser-off order fails the stop is NOT done (the job keeps running) and the page says why.
- The rest of the stopped job stays refused (except the stops) until a new `BRIDGE JOB START`.
- `resume_arm {id, overlap_lines}` arms ONE record for 30 minutes; `resume_disarm`; `interrupted_discard {id}`. When the program sends the same job
  again (`BRIDGE JOB START`), the lines up to the stop are answered `ok` without reaching the board while they are verified against the hash; a
  line that differs cancels it: nothing runs and the rest is refused (the record is kept). At the first line past the stop the bridge plays the
  approach with the laser off (M5, G90, units, WCS, travel to where the program left the head, Z, feed, spindle, G91 if it was relative) on the
  program's own connection and the job goes on for real. `overlap_lines` goes back that many lines and cuts them again.
- Only laser jobs can be resumed. The state of the pages is in `bridge-state.json` key `live_stop`.
