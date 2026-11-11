"""The state main.py used to keep as globals and inside class Bridge, in one object (plan phase 3a, ARQUITECTO 2.2).

A ServiceContext holds what is passed around the whole service today: the live config dict and its ServiceSettings, the plugin id,
the log functions, the lock + connection of the general CommandConnection, the payload readers see at once, and the publisher
thread's queue. main.Bridge is a thin facade over it (same public methods and attributes), so the 200 modules that receive `bridge`
do not change.

Nothing here connects by itself: the factory that opens the CommandConnection comes from the caller (main passes
dsf.connections.CommandConnection; tests pass a double), so the context can be built and used without DSF.
"""
import importlib
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import communication
import ipc_stats
import messages
import publisher
from messages import M

RETRY_S = 5  # wait between attempts to open the general connection


def mask_secrets(raw_text):
    """Hides secrets of a G-code before logging it (DWC password of M551)."""
    return re.sub(r'\bM551(\s+)P"[^"]*"', r'M551\1P"***"', raw_text, flags=re.I)


@dataclass
class ServiceContext:
    plugin_id: str
    base_dir: str
    config: dict                      # the dict the whole service shares (same reference as ever)
    settings: Any                     # service_settings.ServiceSettings over `config`
    log: Callable[[Any], None]        # actionable: reaches DWC as a pop-up (main.log)
    log_file: Callable[[str], None]   # routine: only the local file (main.log_file)
    connect: Callable[[], Any]        # opens the general CommandConnection (a factory with .connect())
    db: Any = None                    # the db module (the one SQLite file of the service)
    sleep: Callable[[float], None] = time.sleep
    lock: Any = field(default_factory=threading.Lock)
    conn: Optional[Any] = None
    payload: dict = field(default_factory=dict)
    publisher: Any = None

    def __post_init__(self):
        if self.publisher is None:
            self.publisher = publisher.Publisher(publisher.instrument(self.send_datum), log=self.log_file)

    @property
    def machine_state(self):
        """The single subscription to DSF (loaded when first asked: it needs DSF's package)."""
        return importlib.import_module("machine_state")

    def ensure_connected(self):
        while self.conn is None:
            try:
                conn = self.connect()
                conn.connect()
                self.conn = conn
                self.log_file("auxiliary CommandConnection connected")
            except Exception as e:
                self.log_file(f"Could not connect CommandConnection ({e}), retrying in {RETRY_S}s")
                self.sleep(RETRY_S)

    def send(self, gcode, who="?"):
        """who = module of the caller, for the IPC counter (ipc_stats.py)."""
        with self.lock:
            self.ensure_connected()
            try:
                return ipc_stats.call("code", who, self.conn.perform_simple_code, gcode, channel=communication.channel_plugin())
            except Exception as e:
                self.log(M("main_error_sending_code_reconnecting", code=mask_secrets(gcode), e=e))
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                raise

    def set_status(self, key, value, **options):
        """Publish plugin data. The value is visible to the readers inside the service at once (self.payload); the IPC call is
        made by the publisher thread only when it changed and at most at the rate of its key (publisher.py)."""
        self.payload[key] = value
        # every message goes out as {"key", "params"}: each page shows it in the language of its own DWC
        self.publisher.set(key, messages.data(value), **options)

    def send_datum(self, key, value):
        with self.lock:
            self.ensure_connected()
            try:
                self.conn.set_plugin_data(self.plugin_id, key, value)
            except Exception as e:
                self.log_file(f"Error updating state '{key}' ({e})")
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                raise

    def save_config(self):
        """Saves the live config under the settings lock (what bridge.save_config() always did)."""
        self.settings.flush()
