"""
Internal implementation of the API operation(s) password.status, password.set, password.clear (api_ops.py maps their named
arguments to the one-letter parameters below).

DWC password (2026-10-10: "where is the password configured and changed?").
In SBC mode DWC's password is the board's: M551 P"..." in sys/config.g.
With a password, DWC asks for it on connecting and the pages' HTTP endpoint
rejects requests without a session (http_api.py).

Usage: <params>                  says whether there is a password (never shows it)
     <params> S"set" V"<new>"    sets or changes it: config.g + instantly
     <params> S"clear"           removes it (the factory one "reprap" = no password comes back)
config.g is backed up before every change (sys/config.g.bak-password-<date>).
The value is never saved in the command history (main._mask).

"""
import paths
import re
import shutil
import time

import activity
from messages import M, J, B

CONFIG_G = paths.CONFIG_G
# active M551 (not commented out), with or without spaces before it
_RE_M551 = re.compile(r'^(\s*)M551\b.*$', re.M | re.I)
_MARK = "; DWC password (System service page > Password)"


def _read():
    with open(CONFIG_G, encoding="utf-8", errors="replace") as f:
        return f.read()


def _has(raw_text):
    for m in _RE_M551.finditer(raw_text):
        if not re.search(r'P"reprap"', m.group(0), re.I):
            return True
    return False


def _back_up():
    """Copy of config.g before a change. The copy does NOT keep the password (the line M551 is commented out): the backups would
    otherwise pile up every old password in plain text, readable by anyone who can read the SD card. Restoring a copy therefore
    leaves DWC without a password (set it again)."""
    destination = f"{CONFIG_G}.bak-password-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CONFIG_G, destination)
    with open(destination, "r", encoding="utf-8", errors="replace", newline="") as f:
        raw_text = f.read()
    hidden = _RE_M551.sub(lambda m: m.group(1) + "; M551 (the password is not kept in this copy)", raw_text)
    if hidden != raw_text:
        with open(destination, "w", encoding="utf-8", newline="") as f:
            f.write(hidden)
    return destination


def _write(raw_text):
    with open(CONFIG_G, "w", encoding="utf-8") as f:
        f.write(raw_text)


def _valid(key):
    if not 4 <= len(key) <= 60:
        return M("password_must_have_4_to_60_characters")
    if any(c in key for c in '";\r\n') or any(ord(c) < 32 for c in key):
        return M("password_cannot_contain_quotes_semicolons_line_breaks")
    if key.lower() == "reprap":
        return M("password_reprap_factory_one_no_password_use")
    return ""


def run(params, bridge, config):
    action = str(params.get("S", "status")).strip().lower()
    if action in ("status", "state"):
        try:
            return M("password_dwc_password_is_set") if _has(_read()) else M("password_dwc_password_none")
        except OSError as e:
            return M("password_dwc_password_could_not_read_config", e=e)

    if action in ("set", "put"):
        key = str(params.get("V") or "")
        reason = _valid(key)
        if reason:
            return M("password_password", reason=reason)
        try:
            raw_text = _read()
            backup = _back_up()
            line = f'M551 P"{key}" {_MARK}'
            if _RE_M551.search(raw_text):
                # replaces the first active one and comments out the others
                first = [True]

                def _rep(m):
                    if first[0]:
                        first[0] = False
                        return m.group(1) + line
                    return m.group(1) + "; M551 (disabled: there is another one above)"

                raw_text = _RE_M551.sub(_rep, raw_text)
            else:
                raw_text = raw_text.rstrip("\n") + "\n\n" + line + "\n"
            _write(raw_text)
        except OSError as e:
            return M("password_password_could_not_write_config_g", e=e)
        r = str(bridge.send(f'M551 P"{key}"') or "")
        activity.log_event(bridge, "config", M("dwc_password_changed"))
        notice = M("password_note_board_answered", strip=r.strip()) if "rror" in r else ""
        return M("password_dwc_password_set_config_g_backup", rsplit=backup.rsplit('/', 1)[-1], notice=notice)

    if action in ("clear", "remove"):
        try:
            raw_text = _read()
            if not _RE_M551.search(raw_text):
                return M("password_dwc_password_there_was_no_password")
            backup = _back_up()
            raw_text = _RE_M551.sub(lambda m: m.group(1) + "; M551 (password removed from the page)", raw_text)
            _write(raw_text)
        except OSError as e:
            return M("password_password_could_not_write_config_g", e=e)
        bridge.send('M551 P"reprap"')
        activity.log_event(bridge, "config", M("dwc_password_removed"))
        return M("password_dwc_password_removed_config_g_backup", rsplit=backup.rsplit('/', 1)[-1])

    return M("password_password_use_s_status_s_set")
