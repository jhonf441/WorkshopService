"""The state file (bridge-state.json): what is built, when it is written and the heartbeat."""


import json
import time

from bridge_pkg.fsutil import write_json_atomic
from bridge_pkg.identity import CONTRACT, SCHEMA, VERSION
from bridge_pkg.log import LOG


# The period the CONTRACT text still promises ("every 2 s, 1 s with debug"). Nothing in the bridge waits on them any more: the state is written
# on change and at least every STATE_HEARTBEAT_S. They stay only until the contract text is updated (test_contract compares the two).
STATE_PERIOD_S = 2.0
STATE_PERIOD_DEBUG_S = 1.0
STATE_CHECK_S = 0.5       # how often the state is built and compared with what was last written
STATE_HEARTBEAT_S = 5.0   # an unchanged state is rewritten at least this often (readers call it dead at 15 s, pending orders stale at 10 s)
VIEWER_GRACE_S = 120      # debug lines stay in the state this long after the last viewer heartbeat


class StateMixin:
    """State file of the bridge (mixed into Bridge)."""

    # -- state for the Services page and the movement logic --
    def build_state(self):
        wall = self.clock.wall()
        mono = self.clock.mono()
        s = self.settings
        minute = int(wall // 60)
        with self.lock:
            self.seq = (self.seq + 1) % 100000
            hist = [list(self.history.get(m) or [0, 0, 0, 0]) for m in range(minute - 59, minute + 1)]
            clients = [c.info(wall) for c in sorted(self.clients.values(), key=lambda c: c.since)]
            job = dict(self.live_job)
            debug = self._debug_state(wall, mono)
            state = {
                "schema": SCHEMA,
                "version": VERSION,
                "contract": CONTRACT,
                "seq": self.seq,
                "time": wall,
                "clock": time.strftime("%H:%M:%S", time.localtime(wall)),
                "uptime_s": round(wall - self.started_wall),
                "port": self.listening["port"],
                "error": self.listening["error"],
                "exclusive": s.get("exclusive"),
                "owner": self.owner.name if self.owner else None,
                "owner_id": self.owner.id if self.owner else None,
                "owner_since_s": round(wall - self.owner_since) if self.owner_since else None,
                "clients": clients,
                "totals": dict(self.totals),
                "history": hist,
                "duet_ms_avg": round(self.timing["all"].avg_ms, 1) if self.timing["all"].avg_ms is not None else None,
                "duet_ms_max": round(self.timing["all"].max_ms, 1),
                "order_ms_avg": round(self.timing["order"].avg_ms, 1) if self.timing["order"].avg_ms is not None else None,
                "query_ms_avg": round(self.timing["query"].avg_ms, 1) if self.timing["query"].avg_ms is not None else None,
                "events": list(self.events)[:40],
                "security": {
                    "password": self.needs_password(),
                    "allowed": s.get("allowed"),
                    "local_only": not s.get("allowed"),
                    "exposed": self.exposed(),
                    "trusted": s.get("trusted"),
                    "max_connections": s.get("max_connections"),
                    "password_attempts": s.get("password_attempts"),
                    "blocked": [{"ip": ip, "remaining_s": None, "fixed": True, "name": s.get("names").get(ip)} for ip in s.get("blocked")]
                    + [{"ip": ip, "remaining_s": int(until - wall)} for ip, until in self.temp_blocks.items()
                       if until > wall and ip not in s.get("blocked")],
                    "rejected": list(self.rejected)[:10],
                },
                "focus_lock": ({**self.focus_lock, "since_s": round(wall - self.focus_lock["since"])} if self.focus_lock else None),
                "action": self.action_seen["result"],
                "live_stop": self.live.public_state() if self.live is not None else {"enabled": False},
                "debug": debug,
                "activity": {
                    "generated_at": wall,
                    "clients_connected": len(self.clients),
                    "pending_orders": self.pending_orders,
                    "last_order_at": self.last_order_wall,
                    "last_motion_at": self.last_motion_wall,
                    "live_job": job,
                },
            }
        return state

    def _debug_state(self, wall, mono):
        active = self.debug_ring.active
        viewing = self.viewer_seen_at is not None and wall - self.viewer_seen_at <= VIEWER_GRACE_S
        return {
            "active": active,
            "timeout_min": self.settings.get("debug_timeout_min"),
            "renew": bool(self.settings.get("debug_renew")),
            "remaining_s": max(0, int(self.debug_until - mono)) if (active and self.debug_until is not None) else None,
            "viewer_seen_s": round(wall - self.viewer_seen_at) if self.viewer_seen_at is not None else None,
            "last_id": self.debug_ring.last_id,
            "lines": self.debug_ring.snapshot() if (active or viewing) else [],
        }

    # Keys that move every second without anything having happened: they do not make a state "changed" (the heartbeat refreshes them).
    _VOLATILE_KEYS = frozenset(("seq", "time", "clock", "generated_at"))

    @classmethod
    def _significant(cls, node):
        """The state without the clock-driven parts: the time stamps and every "*_s" age or uptime."""
        if isinstance(node, dict):
            return {k: cls._significant(v) for k, v in node.items() if k not in cls._VOLATILE_KEYS and not k.endswith("_s")}
        if isinstance(node, list):
            return [cls._significant(v) for v in node]
        return node

    def write_state(self, state=None, mono=None):
        """Writes the state file now. The readers judge it by the age of the FILE and by activity.generated_at, so every write is a full
        rewrite (an os.utime alone would leave generated_at old and the service would call the pending orders stale after 10 s)."""
        if state is None:
            state = self.build_state()
        path = self.paths.state
        self._state_sig = json.dumps(self._significant(state), sort_keys=True, default=str)
        self._last_state_write = self.clock.mono() if mono is None else mono
        try:
            write_json_atomic(path, state, durable=False)
            self.state_writes += 1
            self._state_warned = False
            return True
        except OSError as e:
            if not self._state_warned:
                self._state_warned = True
                LOG.warning("could not write the state file %s: %s", path, e)
        return False
