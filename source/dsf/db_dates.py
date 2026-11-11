"""
db_dates -- the tolerated dates of the database (split from db.py, phase 2e): dates are stored as ISO text, and reading and writing
normalise what turned up different (null bytes, epoch numbers, rounded epochs). db re-exports these names.
"""
import re
import time

# ---- tolerated dates (2026-10-12, item 20: "1 row with a damaged date") ----
# Dates are stored as ISO text. What turned up different: leading null bytes
# (a consumption row, 2026-10-10), and the risk of an epoch time (number) or
# its text ("1791690000.5", or "1.79169e+09" when it went through dsf's JSON,
# which keeps 6 digits). Reading normalizes; writing too; and the old rows
# used to be repaired (that repair is gone, see init_db) with a backup before,
# without deleting.
FMT_TS = "%Y-%m-%dT%H:%M:%S"
_EPOCH_MIN, _EPOCH_MAX = 946684800, 4102444800  # 2000-01-01 .. 2100-01-01
_RX_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)")
_RX_NUM = re.compile(r"^[+]?(\d+)(?:\.(\d*))?(?:[eE][+]?(\d+))?$")


def ts_of(v):
    """(iso, margin_s) of a stored date, or (None, 0) if it is not understood.
    margin_s > 0: it was a rounded epoch (e.g. 1.79169e+09: +-5000 s)."""
    if v is None:
        return None, 0
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        num, approx = float(v), 0
    else:
        t = str(v).replace("\x00", "").strip()
        m = _RX_ISO.match(t)
        if m:
            hour = m.group(2) if len(m.group(2)) == 8 else m.group(2) + ":00"
            iso = m.group(1) + "T" + hour
            try:
                time.strptime(iso, FMT_TS)
            except ValueError:
                return None, 0
            return iso, 0
        m = _RX_NUM.match(t)
        if not m:
            return None, 0
        try:
            num = float(t)
        except ValueError:
            return None, 0
        # with an exponent, the time may come rounded: 1.79169e+09 -> +-5000 s
        approx = 0
        if m.group(3):
            step = 10 ** (int(m.group(3)) - len(m.group(2) or ""))
            approx = step / 2 if step > 1 else 0
    if num != num or num > _EPOCH_MAX * 1000:
        return None, 0
    if num > _EPOCH_MAX:
        num /= 1000.0  # milisegundos
    if not (_EPOCH_MIN <= num <= _EPOCH_MAX):
        return None, 0
    return time.strftime(FMT_TS, time.localtime(int(num))), approx


def ts_iso(v, default=None):
    """ISO date of whatever is stored; if it is not understood, `default` (or the
    text as is, without nulls: the row is still visible and nothing blows up)."""
    iso, _ = ts_of(v)
    if iso:
        return iso
    if default is not None:
        return default
    return "" if v is None else str(v).replace("\x00", "")


def ts_for_save(v):
    iso, _ = ts_of(v)
    return iso or time.strftime(FMT_TS)
