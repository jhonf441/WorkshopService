"""Service configuration (2026-10-11).

  - the SETTINGS on the card, next to the rest of the workshop:
    0:/sys/workshop/config/service.json (it goes into the backups);
  - the KEYS (the Tuya meter's local key, the phone notices topic...)
    separately, in /opt/dsf/conf/workshop-secrets.json with permission 600: it is
    DSF's configuration folder, which the web does not serve (DWC's file API
    reads any file on the card) and which uninstalling a plugin does not delete.

For the rest of the service it is still a single dict: load() joins the two and
save() separates them. Both are written in one step (tmp + fsync + rename) with
the previous version in .bak; if one cannot be read its .bak is used.
"""
import paths as dsf_paths
import json
import os
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.environ.get("WORKSHOP_CONFIG") or dsf_paths.CONFIG_DIR + "/service.json"
SECRETS_FILE = os.environ.get("WORKSHOP_SECRETS") or dsf_paths.SECRETS_FILE
SECRETS_BACKUP = os.path.join(BASE_DIR, "secrets.json")  # if /opt/dsf/conf cannot be written (tests on another PC)
# field names that are secrets, wherever they are (medidores[i].key, ntfy_topic, notificaciones.topic...)
KEYS = {"key", "local_key", "topic", "ntfy_topic", "password", "token", "api_key", "secret"}


def _split(o):
    """(without keys, only keys) of the same object; lists are separated by position."""
    if isinstance(o, dict):
        pub, sec = {}, {}
        for k, v in o.items():
            if k in KEYS and not isinstance(v, (dict, list)):
                sec[k] = v
                continue
            p, s = _split(v)
            pub[k] = p
            if s not in (None, {}, []) and not (isinstance(s, list) and not any(s)):
                sec[k] = s
        return pub, sec
    if isinstance(o, list):
        parts = [_split(x) for x in o]
        return [p for p, _ in parts], [s if s not in (None,) else {} for _, s in parts]
    return o, None


def _join(pub, sec):
    if isinstance(pub, dict) and isinstance(sec, dict):
        out = dict(pub)
        for k, v in sec.items():
            out[k] = _join(pub.get(k), v) if k in pub else v
        return out
    if isinstance(pub, list) and isinstance(sec, list):
        return [_join(p, sec[i]) if i < len(sec) else p for i, p in enumerate(pub)]
    return pub if sec in (None, {}, []) else sec


def _read(p):
    for f in (p, p + ".bak"):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return None


def _write(p, data, private):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())  # to the card before the rename (power cut)
    if private:
        os.chmod(tmp, 0o600)
    try:  # the previous version, if it was healthy, stays as .bak
        with open(p, encoding="utf-8") as f0:
            json.load(f0)
        shutil.copy2(p, p + ".bak")
        if private:
            os.chmod(p + ".bak", 0o600)
    except (OSError, ValueError):
        pass
    os.replace(tmp, p)


def _secrets_path():
    if os.path.isfile(SECRETS_FILE) or os.access(os.path.dirname(SECRETS_FILE), os.W_OK):
        return SECRETS_FILE
    return SECRETS_BACKUP


def mtime():
    """For the threads' caches: it changes if either of the two changes."""
    t = 0.0
    for p in (SETTINGS_FILE, _secrets_path()):
        try:
            t = max(t, os.path.getmtime(p))
        except OSError:
            pass
    return t or None


def _keep_keys(pub, sec, old):
    """Puts back into `sec` the keys that `old` (what is stored now) had and the new configuration does not mention.
    A saver that never saw the keys (a page, a partial read at start-up) must not erase them: a key is removed only by
    saving it explicitly empty, or by removing the object that owns it. Lists are matched by "id", never by position."""
    if not isinstance(pub, dict) or not isinstance(old, dict) or not isinstance(sec, dict):
        return
    for k, v in old.items():
        if k in KEYS and not isinstance(v, (dict, list)):
            if k not in sec and v not in (None, ""):
                sec[k] = v
        elif isinstance(v, dict) and isinstance(pub.get(k), dict):
            sub = sec.setdefault(k, {})
            _keep_keys(pub[k], sub, v)
            if not sub:
                del sec[k]
        elif isinstance(v, list) and isinstance(pub.get(k), list):
            lst = sec.get(k)
            if not isinstance(lst, list):
                lst = []
            lst = (lst + [{} for _ in pub[k]])[: len(pub[k])]
            by_id = {x.get("id"): x for x in v if isinstance(x, dict) and x.get("id")}
            for i, item in enumerate(pub[k]):
                before = by_id.get(item.get("id")) if isinstance(item, dict) else None
                if before is not None:
                    if not isinstance(lst[i], dict):
                        lst[i] = {}
                    _keep_keys(item, lst[i], before)
            if any(lst):
                sec[k] = lst
            else:
                sec.pop(k, None)


def save(cfg):
    pub, sec = _split(cfg)
    try:
        _keep_keys(pub, sec, load_data())
    except Exception:
        pass  # no stored configuration to compare with
    _write(_secrets_path(), sec or {}, True)  # keys first: they are never left only on the card
    _write(SETTINGS_FILE, pub, False)


def load_data():
    """The complete dict, or None if there is no configuration yet."""
    pub = _read(SETTINGS_FILE)
    if pub is None:
        return None
    return _join(pub, _read(_secrets_path()) or {})


def paths():
    return {"settings": SETTINGS_FILE, "keys": _secrets_path()}
