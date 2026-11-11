"""The service settings (service.json + keys) with ONE way to change them safely (plan phase 2c, review A6).

`config` is still the plain dict the whole service shares (same reference, same format on the card). What this adds is
`update(mutator)`: under the lock of config_store, it takes a copy, lets the mutator change the live dict, validates it, and saves
it atomically; if the mutator, the validation or the save fails, the live dict goes back to what it was, so memory and card never
disagree. Sites that still mutate `config` by hand keep working: their save() takes the same lock and a snapshot.
"""
import copy

import config_store


class SettingsInvalid(Exception):
    """The validator refused the changed settings: nothing was saved and the live dict is as it was."""


class ServiceSettings:
    def __init__(self, live, save_fn=None, lock=None):
        """live: the shared config dict. save_fn(cfg): how it is written (default config_store.save; the service passes its
        save_config, which also refuses to save over an unreadable file). lock: default config_store.LOCK."""
        self.live = live
        self._save = save_fn or config_store.save
        self._lock = lock or config_store.LOCK

    def update(self, mutator, validate=None):
        """mutator(live) changes the dict in place (its return value is returned). validate(live), if given, returns False or raises
        to refuse. Atomic: read, apply, validate, save under one lock, with rollback of the live dict on any failure."""
        with self._lock:
            before = copy.deepcopy(self.live)
            try:
                result = mutator(self.live)
                if validate is not None and validate(self.live) is False:
                    raise SettingsInvalid("the changed settings were refused")
                self._save(self.live)
            except BaseException:
                self.live.clear()
                self.live.update(before)  # same reference, previous content
                raise
            return result

    def flush(self):
        """Saves the live dict as it is, under the same lock (what bridge.save_config() does for the hand-mutating sites)."""
        with self._lock:
            self._save(self.live)

    def get(self, key, default=None):
        with self._lock:
            return copy.deepcopy(self.live.get(key, default))
