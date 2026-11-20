"""
sd_pending -- the short memory of "what the wizard proposes to change now" (the plan), shared by whoever reads it and whoever writes the SD.

Looking at several files in a row must not compute the whole plan again for each one: the answer is kept PENDING_TTL_S seconds per key.
Whatever writes the SD (apply, restore, the import of a package) calls forget(). Any doubt recomputes: an answer that could not be computed
(None) is never kept, a clock that went back is not trusted. No imports of the service: it is a leaf.
"""
import time

PENDING_TTL_S = 5.0
_cache = {"key": None, "at": 0.0, "value": None}


def forget():
    _cache.update(key=None, at=0.0, value=None)


def get(key, compute, now=None):
    """The kept answer for `key` if it is younger than PENDING_TTL_S, else compute() (a set, or None when it cannot be computed)."""
    clock = time.monotonic() if now is None else now
    if _cache["key"] == key and _cache["value"] is not None and 0 <= clock - _cache["at"] < PENDING_TTL_S:
        return set(_cache["value"])
    value = compute()
    if value is None:
        forget()
        return None
    _cache.update(key=key, at=clock, value=set(value))
    return set(value)
