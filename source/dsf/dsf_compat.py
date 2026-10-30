"""The only place that knows the differences between DSF 3.6 and DSF 3.7 (dsf-python 3.6 and 3.7).

Everything else in the service is written once for both. The differences that matter to this service:

  - The subscribe connection class of dsf-python 3.7 takes `verbose` and `obsolete` (they go into the SubscribeInitMessage of IPC
    protocol 13). DSF 3.7 leaves out of a subscription the fields flagged obsolete (for example move.workplaceNumber,
    which the service reads) and verbose ones unless they are asked for; DSF 3.6 always sent them and its dsf-python
    has no such parameters. subscribe_kwargs() asks for everything when the installed class supports it, so the model
    is the same on both.
  - dsf-python must match DSF (a 3.7 client is refused by a 3.6 server, and 3.7 needs Python 3.11 or newer).
    Nothing here pins it: the library is installed on the Pi by the owner, next to DSF.

Detection is by feature (the signature of the installed class), never by a version number, so a patched or
pre-release dsf-python is handled by what it can do.
"""
import importlib.metadata
import inspect
import time

_warned = False


def subscribe_kwargs(connection_class):
    """Keyword arguments to add when the subscribe connection class is built so that a subscription brings the whole model on any
    dsf-python: {"verbose": True, "obsolete": True} when the class has them, {} otherwise."""
    try:
        names = inspect.signature(connection_class).parameters
    except (TypeError, ValueError):
        names = ()
    found = {k: True for k in ("verbose", "obsolete") if k in names}
    if not found:
        _warn_once_if_37()
    return found


def _at_least_37(version):
    try:
        major, minor = (int(x) for x in version.split(".")[:2])
    except (AttributeError, ValueError):
        return False
    return (major, minor) >= (3, 7)


def _warn_once_if_37():
    """On dsf-python 3.7 or newer an empty answer means the parameter names changed: the model would silently lack the obsolete
    fields (move.workplaceNumber), so say so once in the service log."""
    global _warned
    version = dsf_python_version()
    if _warned or not _at_least_37(version):
        return
    _warned = True
    print("%s dsf_compat: dsf-python %s has no verbose/obsolete parameters on SubscribeConnection; subscriptions will lack "
          "obsolete fields such as move.workplaceNumber" % (time.strftime("%Y-%m-%dT%H:%M:%S"), version), flush=True)


def dsf_python_version():
    """Installed dsf-python version text, or None (not installed through pip, or metadata unavailable)."""
    try:
        return importlib.metadata.version("dsf-python")
    except importlib.metadata.PackageNotFoundError:
        return None
