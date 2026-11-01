"""The key of the day for the remote screens (when DWC has a password): `token` gives it, `token_valid` checks one, `has_password` asks DSF."""
import hashlib
import hmac
import os
import time

import paths
import camera_context


# The relay's key does NOT go on the card (DWC's file API would serve it): it goes in DSF's
# configuration folder, which the web does not serve and which uninstalling a plugin does not delete
# (2026-10-11, "how passwords are managed").
KEY_FILE = paths.CONF + "/workshop-camera.key"
# ---- key for the remote screens (with a password in DWC) ----
_key = {"has": False, "ts": 0.0, "secret": None}


def has_password():
    if time.time() - _key["ts"] < 30:
        return _key["has"]
    _key["ts"] = time.time()
    try:
        import ipc_stats
        from dsf.connections import CommandConnection
        c = CommandConnection()
        c.connect()
        try:
            # same as http_api.py: without a password DSF accepts any key
            r = ipc_stats.call("other", "camera_relay", c.check_password, "workshop-without-key-9f3k")
            _key["has"] = not bool(getattr(r, "result", r))
        finally:
            c.close()
    except Exception:
        _key["has"] = True  # if it cannot be known, a key is asked for
    return _key["has"]


def _secret():
    if _key["secret"] is None:
        route = KEY_FILE
        try:
            with open(route, "rb") as fh:
                sec = fh.read()
            if len(sec) < 16:
                raise OSError
        except OSError:
            sec = os.urandom(32)
            os.makedirs(camera_context.DATA_DIR, exist_ok=True)
            with open(route, "wb") as fh:
                fh.write(sec)
            os.chmod(route, 0o600)
        _key["secret"] = sec
    return _key["secret"]


def _token(day):
    return hmac.new(_secret(), day.encode(), hashlib.sha256).hexdigest()[:32]


def token():
    """Key of the day (valid today and tomorrow). The page asks for it with the API (camera_relay) S"token", which already requires the DWC session."""
    return _token(time.strftime("%Y%m%d"))


def token_valid(t):
    if not t:
        return False
    today = time.time()
    for day in (time.strftime("%Y%m%d", time.localtime(today)), time.strftime("%Y%m%d", time.localtime(today - 86400))):
        if hmac.compare_digest(t, _token(day)):
            return True
    return False
