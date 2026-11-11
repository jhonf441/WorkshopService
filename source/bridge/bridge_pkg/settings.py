"""The settings file: defaults, validation (clean_config) and the reloading Settings object."""


import os
import threading

from bridge_pkg.fsutil import read_json, write_json_atomic
from bridge_pkg.lines import QUERIES_DEFAULT, QUERY_GRAMMAR
from bridge_pkg.log import LOG
from bridge_pkg.textutil import str_list


_warned_queries = set()


# How long (ms) a Duet answer to each query stays valid for every client.
CACHE_MS_DEFAULT = {
    "M114": 500, "M408": 500, "M105": 1000, "M119": 1000, "M27": 1000,
    "M36": 2000, "M20": 5000, "M122": 5000, "M503": 30000, "M115": 60000,
}
CONFIG_DEFAULT = {
    "port": int(os.environ.get("BRIDGE_PORT", "23")),
    "exclusive": os.environ.get("BRIDGE_EXCLUSIVE", "1") == "1",
    "queries": QUERIES_DEFAULT,
    "names": {},                  # {"<ip>": "Cutter-PC"}
    "extended_greeting": False,   # True: after "Connected!" explain the name and the help
    "debug": os.environ.get("BRIDGE_DEBUG", "0") == "1",
    "debug_timeout_min": 30,      # debug turns itself off after this long without a viewer
    "debug_renew": True,          # True: while the page shows the debug panel the countdown starts again; False: fixed from turning it on (Extend adds time)
    # --- security ---
    "allowed": [],                # IPs or networks ("192.168.77.0/24"); empty = local network only
    "trusted": [],                # IPs that send orders without a password
    "password_hash": "",          # "scrypt$<hex>"; empty = no password. Any other format counts as no password (logged once)
    "password_salt": "",
    "max_connections": 8,
    "password_attempts": 5,       # wrong passwords before the IP is blocked
    "block_seconds": 300,
    "blocked": [],                # IPs blocked from the page until unblocked
    # --- line handling (3.0) ---
    "order_timeout_s": 120,       # max wait for the Duet on an order: a slow cut keeps the board queue full and a line can wait for a long time (15 s gave false errors)
    "query_timeout_s": 3,         # max wait for the Duet on a query
    "skip_material_macro": False, # True: the M98 that calls a material macro (macros/laser, laserfocus.g, livemark.g) is answered ok and NOT run (the program's start G-code carries it)
    "block_when_unfit": True,     # refuse movement / laser orders while the machine is paused, halted by an error, cancelling...
    "queries_in_job": True,       # False: while a live job runs the queries are answered from the last known answer, the board is not asked
    "query_channel": "Telnet",    # code channel of the queries: not the one of the orders, so a query never waits behind a slow cut ("" = same channel)
    "query_cache_ms": dict(CACHE_MS_DEFAULT),
    "query_soft_ms": 500,         # after this wait a recent cached answer is served instead
    "query_stale_s": 5,           # oldest cached answer that may be served when the Duet is slow
    "overtake_ms": 500,           # a query may overtake an order waiting longer than this
    "query_workers": 2,           # DSF connections reserved for queries
}


def clean_config(raw):
    """Merge a (possibly partial) settings dict over the defaults and
    validate every value; invalid values fall back to the default."""
    base = dict(CONFIG_DEFAULT)
    base.update({k: v for k, v in raw.items() if k in CONFIG_DEFAULT})
    try:
        base["port"] = max(1, min(65535, int(base["port"])))
    except (TypeError, ValueError):
        base["port"] = CONFIG_DEFAULT["port"]
    base["exclusive"] = bool(base["exclusive"])
    base["extended_greeting"] = bool(base["extended_greeting"])
    base["debug"] = bool(base["debug"])
    base["debug_renew"] = bool(base.get("debug_renew", True))
    base["queries_in_job"] = bool(base.get("queries_in_job", True))
    base["block_when_unfit"] = bool(base.get("block_when_unfit", True))
    base["skip_material_macro"] = bool(base.get("skip_material_macro", False))
    wanted = [str(c).upper() for c in (base.get("queries") or QUERIES_DEFAULT)]
    base["queries"] = [c for c in wanted if c in QUERY_GRAMMAR]
    for c in wanted:
        if c not in QUERY_GRAMMAR and c not in _warned_queries:
            _warned_queries.add(c)
            LOG.warning("queries: %s has no query grammar, so it is ignored (it is handled as an order)", c)
    base["names"] = {str(k): str(v) for k, v in (base.get("names") or {}).items()}
    for k in ("allowed", "trusted", "blocked"):
        base[k] = str_list(base.get(k))
    base["password_hash"] = str(base.get("password_hash") or "")
    base["password_salt"] = str(base.get("password_salt") or "")
    for k in ("max_connections", "password_attempts", "block_seconds", "query_workers", "debug_timeout_min"):
        try:
            base[k] = max(1, int(base[k]))
        except (TypeError, ValueError):
            base[k] = CONFIG_DEFAULT[k]
    base["query_workers"] = min(base["query_workers"], 8)
    for k, lo, hi in (("order_timeout_s", 1.0, 300.0), ("query_timeout_s", 0.5, 30.0), ("query_stale_s", 0.0, 120.0)):
        try:
            base[k] = max(lo, min(hi, float(base[k])))
        except (TypeError, ValueError):
            base[k] = CONFIG_DEFAULT[k]
    base["query_channel"] = "".join(ch for ch in str(base.get("query_channel") or "") if ch.isalnum())[:16]
    for k in ("query_soft_ms", "overtake_ms"):
        try:
            base[k] = max(0, int(base[k]))
        except (TypeError, ValueError):
            base[k] = CONFIG_DEFAULT[k]
    cache = dict(CACHE_MS_DEFAULT)
    given = base.get("query_cache_ms")
    if isinstance(given, dict):
        for code, ms in given.items():
            try:
                cache[str(code).upper()] = max(0, int(ms))
            except (TypeError, ValueError):
                pass
    base["query_cache_ms"] = cache
    return base


class Settings:
    def __init__(self, paths, log=print):
        self.paths = paths
        self.log = log
        self.lock = threading.Lock()
        self.values = clean_config({})
        self.mtime = None

    def get(self, key):
        with self.lock:
            return self.values.get(key)

    def snapshot(self):
        with self.lock:
            return dict(self.values)

    def load(self):
        """Reload when the file changed. Returns True if new values were applied."""
        path = self.paths.config
        try:
            m = os.path.getmtime(path)
        except OSError:
            return False
        if m == self.mtime:
            return False
        try:
            raw = read_json(path)
        except (OSError, ValueError) as e:
            self.log(f"Invalid settings in {path} ({e}): keeping the previous values")
            self.mtime = m
            return False
        with self.lock:
            self.values = clean_config(raw)
        self.mtime = m
        return True

    def modify(self, fn):
        """Read the settings file, apply fn(dict) and save it (atomic). Used by
        the page actions (rename, trust, password) and debug auto-off."""
        try:
            d = read_json(self.paths.config)
        except (OSError, ValueError):
            d = {}
        fn(d)
        write_json_atomic(self.paths.config, d, indent=2)
        self.mtime = None
        self.load()
