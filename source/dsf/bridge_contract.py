"""Service side of the bridge contract (bridge/CONTRACT.md): ONE place that knows how to read what the G-code bridge publishes.

The bridge is another program (a systemd unit, bridge/gcode_bridge.py). It tells the service what it is doing only through the state
file `0:/sys/workshop/data/bridge-state.json` (written every 2 s, 1 s with debug on) and answers the actions of the action file
`bridge-action.json` in the key `action` of that state. This module reads the state and applies the rules of the contract:

  * It NEVER raises and never waits. A missing, unreadable, garbage, old or incompatible file is a plain answer ("down" / "unknown"),
    so a dead, slow or newer bridge cannot block the jog or any other module of the service.
  * A reader that cannot tell what the bridge is doing answers `None` ("unknown"). What each caller does with unknown stays its own
    decision and is the same as before this module existed: the jog does not block, the live stop says "bridge down".
  * Compatibility: `schema` is the major version of the file. Inside schema 2 the bridge only adds keys, so a reader ignores keys it
    does not know and treats a missing key as unknown. A schema this module does not know (a future bridge) is "incompatible":
    nothing is read from it. `contract` (added by bridge 3.8.x, absent in older ones = contract 1) is the version of the CONTRACT.md
    text the bridge was written for; a number higher than CONTRACT is still read (additive) and reported as `newer`.

Nothing in the service calls this module yet: jog_move.py, live_job_stop.py and health_poller.py keep their own readers (the old
layout stays the default). test_bridge_contract.py proves that this module answers exactly what those readers answer for the same
file, so they can be moved onto it one at a time (bridge/ARCHITECTURE.md, step 3).
"""
import json
import os
import time

import paths

STATE_FILE = paths.DATA_DIR + "/bridge-state.json"
ACTION_FILE = paths.DATA_DIR + "/bridge-action.json"

CONTRACT = 1             # the version of bridge/CONTRACT.md this module implements
SCHEMAS = (2,)           # the schema numbers of bridge-state.json this module reads
FRESH_S = 10             # "pending_orders" proves something only if the file is younger than this (jog_move.BRIDGE_STATE_FRESH_S)
ALIVE_S = 15             # a state older than this: the bridge is not running (live_job_stop.STATE_MAX_AGE_S)
DEFAULT_PORT = 23

OK = "ok"
MISSING = "missing"          # no file, or not readable
GARBAGE = "garbage"          # not JSON, or not an object
INCOMPATIBLE = "incompatible"  # a schema this module does not know


class StateRead:
    """The result of reading the state file. `state` is a dict only when `status` is OK."""

    __slots__ = ("status", "state", "age_s", "schema", "version", "contract", "legacy", "newer")

    def __init__(self, status, state=None, age_s=None, schema=None, version=None, contract=None, legacy=False, newer=False):
        self.status = status
        self.state = state if status == OK else {}
        self.age_s = age_s
        self.schema = schema
        self.version = version
        self.contract = contract
        self.legacy = legacy      # no `contract` key: a bridge written before the contract (3.8.0 and older)
        self.newer = newer        # `contract` higher than CONTRACT

    def __repr__(self):
        return "StateRead(%s, age=%s, schema=%s, version=%s, contract=%s)" % (self.status, self.age_s, self.schema, self.version, self.contract)

    @property
    def readable(self):
        return self.status == OK

    def alive(self, max_age_s=ALIVE_S):
        """The file is readable, compatible and was written within `max_age_s`: the bridge is running."""
        return self.status == OK and self.age_s is not None and self.age_s <= max_age_s


def parse(raw, age_s=None):
    """A StateRead from the text (or already parsed object) of a state file."""
    try:
        state = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    except (ValueError, TypeError):
        return StateRead(GARBAGE, age_s=age_s)
    if not isinstance(state, dict):
        return StateRead(GARBAGE, age_s=age_s)
    schema = state.get("schema")
    if schema is None:
        schema_ok = True                      # the readers of the service never required it: keep reading what is there
    else:
        schema_ok = isinstance(schema, int) and not isinstance(schema, bool) and schema in SCHEMAS
    contract = state.get("contract")
    legacy = contract is None
    if legacy:
        contract = 1
    elif isinstance(contract, bool) or not isinstance(contract, int) or contract < 1:
        contract, legacy = 1, True            # a nonsense value (not an integer, or below 1) is read as "not declared"
    version = state.get("version") if isinstance(state.get("version"), str) else None
    if not schema_ok:
        return StateRead(INCOMPATIBLE, age_s=age_s, schema=schema, version=version, contract=contract, legacy=legacy)
    return StateRead(OK, state, age_s=age_s, schema=schema, version=version, contract=contract, legacy=legacy, newer=contract > CONTRACT)


def read_state(path=None, now=None):
    """Reads the state file. Never raises, never waits. `age_s` is the age of the FILE (its modification time), the only clock both
    sides trust: the absolute times inside it are for people (a browser may read them rounded)."""
    path = path or STATE_FILE
    now = time.time() if now is None else now
    try:
        age = max(0.0, now - os.path.getmtime(path))
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return StateRead(MISSING)
    return parse(raw, age)


# ---------------------------------------------------------------------------
# What the callers need, one function each. All of them answer None / a default when the state cannot be trusted.
# ---------------------------------------------------------------------------

def orders_age_s(read, now=None):
    """Seconds since the last non-query line of any client, or None if unknown. 0.0 while an order is pending in a FRESH file
    (so a dead bridge cannot block anything). The same answer as jog_move.bridge_state_age_s for the same file."""
    if not isinstance(read, StateRead) or read.status != OK:
        return None
    state, file_age = read.state, read.age_s or 0.0
    now = time.time() if now is None else now
    # relative ages first: the absolute epochs reach a browser rounded (2026-10-15), the relative ones are reliable
    cls = state.get("clients")
    if isinstance(cls, list) and any(isinstance(c, dict) and "last_order_age_s" in c for c in cls):
        val = None
        for c in cls:
            if not isinstance(c, dict):
                continue
            if _num(c.get("pending_orders")) > 0 and file_age <= FRESH_S:
                return 0.0
            ag = c.get("last_order_age_s")
            if isinstance(ag, (int, float)) and not isinstance(ag, bool):
                h = float(ag) + file_age
                val = h if val is None else min(val, h)
        return val
    act = state.get("activity")
    if isinstance(act, dict):
        gen = act.get("generated_at")
        fresh = isinstance(gen, (int, float)) and (now - gen) <= FRESH_S
        if fresh and _num(act.get("pending_orders")) > 0:
            return 0.0
        last = act.get("last_order_at")
        return max(0.0, now - float(last)) if isinstance(last, (int, float)) and not isinstance(last, bool) else None
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def port(read, default=DEFAULT_PORT):
    """The port the bridge listens on (health_poller.port_bridge)."""
    if isinstance(read, StateRead) and read.status == OK:
        try:
            return int(read.state.get("port") or default)
        except (TypeError, ValueError):
            pass
    return default


def clients(read):
    """The connected clients as a list of dicts (health_poller.programs_bridge); [] if unknown."""
    if isinstance(read, StateRead) and read.status == OK and isinstance(read.state.get("clients"), list):
        return [c for c in read.state["clients"] if isinstance(c, dict)]
    return []


def live_stop_enabled(read):
    """True when this bridge has the safe stop (live_stop.py installed); False = an old or incomplete install; None = unknown."""
    if not isinstance(read, StateRead) or read.status != OK:
        return None
    ls = read.state.get("live_stop")
    return bool(ls.get("enabled")) if isinstance(ls, dict) else False


def action_result(read, seq):
    """The answer of the bridge to the action `seq`, or None while it has not answered it."""
    if isinstance(read, StateRead) and read.status == OK:
        res = read.state.get("action")
        if isinstance(res, dict) and res.get("seq") == seq:
            return res
    return None


def health(read):
    """One word for the page: 'down' (no readable state or too old), 'incompatible', 'newer' (works, but ahead of this service) or 'ok'."""
    if not isinstance(read, StateRead) or read.status in (MISSING, GARBAGE):
        return "down"
    if read.status == INCOMPATIBLE:
        return "incompatible"
    if not read.alive():
        return "down"
    return "newer" if read.newer else "ok"
