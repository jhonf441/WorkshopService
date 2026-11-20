"""
access_rev -- one number that goes up every time something that auth.whoami answers to someone changes.

The three files of access (the people and their switch, the custom roles, the profiles / groups / ceilings) each call `bump()` after they save. The service
publishes the number as the plugin data `accessRev` (bootstrap.announce wires `listen`): a page that sees it change asks auth.whoami again instead of waiting for
its next poll. Only the integer is published, never what changed. It starts at 0 with every run of the service and only goes up inside one run.
No imports of the service: it is a leaf.
"""
import threading

_lock = threading.Lock()
_rev = 0
_listener = None


def get():
    """The current number."""
    with _lock:
        return _rev


def bump():
    """Something that changes what auth.whoami answers was saved: the number goes up by one and the listener (if any) hears it."""
    global _rev
    with _lock:
        _rev += 1
        n, fn = _rev, _listener
    if fn is not None:
        try:
            fn(n)
        except Exception:  # publishing must never break the save that already happened
            pass
    return n


def listen(fn):
    """`fn(number)` is called after every change (None to stop); it is called once now with the current number."""
    global _listener
    with _lock:
        _listener = fn
        n = _rev
    if fn is not None:
        try:
            fn(n)
        except Exception:
            pass
