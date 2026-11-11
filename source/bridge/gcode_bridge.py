#!/usr/bin/env python3
"""
G-code bridge for the workshop (formerly "puente.py" / "duet-bridge").

Listens for TCP connections (Telnet style, configurable port, 23 by default)
and sends every received line to the Duet as G-code through DSF. The reply is
followed by "ok", which is what external cutting programs, terminals, scripts
and ESP32 boards expect. Several connections at once; with "exclusive" on, only
one of them (the owner) may send orders. Queries (M114, M105...) always pass.
Own commands: BRIDGE HELP. Telnet: a real Telnet client works (options are refused politely, NUL and IAC bytes never reach the G-code).
Live jobs (2026-10-13): the start / end G-code of the sending program carries
BRIDGE JOB START <name> / BRIDGE JOB END (or CANCEL); the bridge answers them
itself (they never reach the board) and tells WorkshopService through its API
(job.start / job.end, POST /machine/WorkshopService/api with the local key of
/opt/dsf/conf/workshop-api-token).

Line handling (3.0):
  - Every line becomes a "slot" in a per-client queue. Replies are written in
    the order the lines arrived, except that a query or a local answer may
    overtake an order that has been waiting for more than `overtake_ms`
    (so a console keeps answering while a long move blocks the machine).
  - Orders go to a per-client worker with its own DSF connection (timeout
    `order_timeout_s`); they never share a queue with queries.
  - Queries go to a small shared pool of DSF connections (timeout
    `query_timeout_s`). Identical queries from all clients are coalesced into one
    Duet request and answered from a short cache (`query_cache_ms`); when the
    machine is slow a recent cached answer is served instead of waiting.
  - Activity of the clients (last order time, pending orders, live job) is
    published in bridge-state.json ("activity") for the movement safety logic
    of the service.

Security. Telnet encrypts nothing and some programs cannot send a user or
password, so protection comes in layers:
  - Allowed IPs only: by default just the local network (10.x, 172.16-31.x,
    192.168.x, 127.x).
  - Optional password for ORDERS: without "BRIDGE KEY <password>" a connection
    can only query. "Trusted" IPs do not need it.
  - Wrong passwords block the IP for a while; maximum connections and line
    length; kick / block / hand over control from the Services page.

Files (0:/sys/workshop/..., /opt/dsf/sd/sys/workshop/... on the Pi):
  config/bridge.json        settings, reloaded when the file changes
  data/bridge-state.json    state/health, written when it changes and at least every 5 s (Services page, jog)
  data/bridge-action.json   actions from the page ({seq, action, ...})
  data/bridge-viewer.json   heartbeat of the page's Debug view (its mtime counts)

Debug mode keeps the last lines in memory (ring buffer) and publishes them in
the state file while it is on. It is NOT written to the journal and it turns
itself off after `debug_timeout_min` minutes unless the page keeps viewing it.
"""

# The program is bridge_pkg/ (one module per concern, see ARCHITECTURE.md); this file is the entry point of the systemd unit and
# re-exports every name of the old single-file bridge, because the tests and the tools import them from `gcode_bridge`.
import logging
import os  # noqa: F401  (the tests patch gcode_bridge.os.replace)
import sys

from bridge_pkg.identity import CONTRACT, SCHEMA, VERSION  # noqa: F401
from bridge_pkg.log import LOG  # noqa: F401
from bridge_pkg.clock import Clock, Timing  # noqa: F401
from bridge_pkg.fsutil import Paths, SD_DIR, _remove_quiet, _sync_dir, ensure_action_file, read_json, write_json_atomic  # noqa: F401
from bridge_pkg.textutil import first_token, format_response, mask, query_key, str_list  # noqa: F401
from bridge_pkg.lines import (  # noqa: F401
    FAIL_REFUSE_S, FAIL_WATCH, GATED_CODES, M118_JOB_RE, MATERIAL_MACRO_RE, MAX_LINE, MOTION_CODES, NEEDS_HOMING_OK, NOOP_WITHOUT_PARAMS,
    QUERIES_DEFAULT, QUERY_GRAMMAR, QUERY_GRAMMAR_RE, STOPS_PASS, STOP_ENDS_JOB, TAINT_S, _PATH, is_query_line, m118_job_line,
    parse_job_command)
from bridge_pkg.settings import CACHE_MS_DEFAULT, CONFIG_DEFAULT, Settings, _warned_queries, clean_config  # noqa: F401
from bridge_pkg.telnet import TelnetFilter  # noqa: F401
from bridge_pkg.duet import DuetLink, real_link_factory  # noqa: F401
from bridge_pkg.queries import QueryService, _Job, _Waiter  # noqa: F401
from bridge_pkg.orders import OrderWorker  # noqa: F401
from bridge_pkg.service_link import JOB_END_OPS, ServiceNotifier  # noqa: F401
from bridge_pkg.gate import MachineGate, UNFIT_STATES  # noqa: F401
from bridge_pkg.debug import DEBUG_RING_LINES, DEBUG_TEXT_MAX, DebugMixin, DebugRing  # noqa: F401
from bridge_pkg.security import SecurityMixin  # noqa: F401
from bridge_pkg.jobs import LiveJobMixin  # noqa: F401
from bridge_pkg.commands import CommandsMixin, HELP_TEXT, SUBCOMMANDS  # noqa: F401
from bridge_pkg.actions import ActionsMixin  # noqa: F401
from bridge_pkg.state import STATE_CHECK_S, STATE_HEARTBEAT_S, STATE_PERIOD_DEBUG_S, STATE_PERIOD_S, StateMixin, VIEWER_GRACE_S  # noqa: F401
from bridge_pkg.client import Client, Slot  # noqa: F401
from bridge_pkg.server import HOST, ServerMixin  # noqa: F401
from bridge_pkg.bridge import Bridge, live_stop  # noqa: F401


def make_readable():
    # Binding port 23 without root (CAP_NET_BIND_SERVICE in the unit) makes the
    # process "non dumpable": /proc/<pid> becomes root's and DSF cannot identify
    # it ("Failed to find plugin permissions"), cutting the connection.
    # PR_SET_DUMPABLE=1 puts it back to normal.
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(4, 1, 0, 0, 0)  # PR_SET_DUMPABLE
    except Exception as e:
        LOG.warning("could not mark the process as readable: %s", e)


def main():
    # The journal gets warnings and errors only; the detailed view is the
    # in-memory Debug view of the Services page.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(levelname)s %(message)s")
    make_readable()
    print(f"Workshop G-code bridge {VERSION} (journal at warning level; debug is in the Services page)", flush=True)
    Bridge().serve()


if __name__ == "__main__":
    main()
