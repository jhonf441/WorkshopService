"""Minimum policy of the DWC password (2026-11-20). Pure: no files, no DSF, no logging (a password never goes through a log from here).

The server applies it ALWAYS (handlers/password.py, operation password.set); the page shows the same rules while the person types
(dwc36/password-policy.js, kept equal by tests/password-policy.test.js, which also compares COMMON with the list there).

check(password, repeat=None, names=()) -> "" when it is acceptable, else the reason (a key: the message is `password_policy_<reason>` in
dsf/i18n/es.json and en.json). The first reason that applies is returned, in this order:
  characters  a double quote, a single quote, a semicolon, braces, a backslash or a control character: they break the line `M551 P"..."` of
              config.g (RRF reads ' as an escape and { } as an expression; ; starts a comment); also spaces at the ends
  length      shorter than MIN_LEN (10) or longer than MAX_LEN (60; the limit of M551 itself could not be confirmed here, the 60 of the earlier code stays)
  factory     "reprap": the factory one means no password
  mismatch    the second entry (when it is given) differs from the first
  common      it is in COMMON, or it is one of them plus a tail of 1, 12, 123, ... or !, or a year
  names       it is the name of a person, the hostname or the IP of the machine (names=...)
  one_class   only letters or only digits (symbols and spaces count as a third kind)
  pattern     one repeated character, a block repeated (12341234), or mostly a sequence (abcd1234, 98765432, qwertyuiop)

The PIN of a person has its own check in this same module (check_pin, 2026-11-21), applied by the API (api_users.py) ONLY to a NEW or CHANGED PIN:
the PINs already saved keep working (nothing here is looked at when somebody signs in). The first reason that applies:
  digits      anything that is not a digit
  length      fewer than PIN_MIN_LEN (6) or more than PIN_MAX_LEN (12) digits
  mismatch    the second entry (when it is given) differs from the first
  common      it is in PIN_COMMON (000000, 123123, 112233, 696969, ...)
  repeated    one or two digits only (111111, 121212 ...) or a block repeated (123123, 12341234)
  sequence    ascending or descending run of consecutive digits that covers the PIN (123456, 654321, 345678, 7890123): 9 -> 0 counts as consecutive
  date        a probable date between 1930 and 2030: DDMMAAAA, AAAAMMDD or DDMMAA
The message of a reason is `users_err_pin_<reason>` in dsf/i18n/es.json and en.json. Nothing here logs: a PIN never goes through a log from this module.
"""
import datetime
import re

MIN_LEN = 10
MAX_LEN = 60
PIN_MIN_LEN = 6
PIN_MAX_LEN = 12
BAD_CHARS = set("\"';{}\\")

# lower case, no tail: a small list of what people choose first (and of what is typed in a workshop with a Duet)
COMMON = frozenset("""
password passw0rd p4ssword pass word passwort contrasena contrasenia clave claves secreto secret admin administrator administrador root
user usuario guest invitado login welcome bienvenido letmein master dragon monkey shadow sunshine princess football futbol baseball
iloveyou loveyou trustno1 abc123 qwerty qwertyui qwertyuiop asdfgh asdfghjk asdfghjkl zxcvbn zxcvbnm azerty qazwsx qazwsxedc
1qaz2wsx 1q2w3e4r 1q2w3e4r5t 1qazxsw2 zaq12wsx
duet duet3 duet3d duet2 duetweb duetwifi reprap reprap3d rrf repraprap printer impresora 3dprinter 3dprint prusa ender creality marlin klipper
taller workshop workshopservice laser cnc fresadora router maquina machine machine1 milling plotter cutter cortadora
raspberry raspberrypi raspberrypi4 pi pi4 dsf dwc duet36hc duet3mb6hc mb6hc 6hc
123456 1234567 12345678 123456789 1234567890 0123456789 987654321 9876543210 111111 11111111 1111111111 000000 00000000 0000000000
123123 123123123 112233 11223344 121212 12121212 654321 666666 696969 7777777 77777777 88888888 99999999 123321 12341234 1234abcd abcd1234
abcdefgh abcdefghij abcdefghijkl aaaaaaaa aaaaaaaaaa
michael jennifer jordan superman batman spiderman pokemon starwars naruto minecraft fortnite ferrari mercedes mustang chevrolet
buster hunter harley charlie thomas robert daniel andrea carlos pedro jose maria juan luis miguel javier david alejandro sebastian
colombia mexico argentina venezuela chile peru ecuador bogota medellin cali barranquilla madrid barcelona
america sistemas hola holamundo holahola mundo mipassword micontrasena micasa miclave tucontrasena test test123 testing prueba pruebas
temp temporal changeme change cambiame default demo example ejemplo access acceso network internet wifi router1 linksys netgear
google facebook youtube amazon apple samsung windows linux ubuntu debian hello hellohello helloworld
football1 baseball1 soccer hockey rangers yankees liverpool arsenal chelsea realmadrid
""".split())

_TAIL = re.compile(r"[0-9!@#$%^&*._\-+=?]+$")
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890", "qazwsxedcrfvtgbyhnujmikolp", "abcdefghijklmnopqrstuvwxyz", "azertyuiop", "qsdfghjklm")


def kinds(p):
    """How many kinds of character: letters, digits, others (the page draws the same count)."""
    return sum(1 for ok in (any(c.isalpha() for c in p), any(c.isdigit() for c in p), any(not c.isalnum() for c in p)) if ok)


def _normal(p):
    return p.lower().replace(" ", "").replace("-", "") if p else ""


def is_common(p):
    low = p.lower().strip()
    squeezed = _normal(p)
    for cand in (low, squeezed, _TAIL.sub("", low), _TAIL.sub("", squeezed)):
        if cand and (cand in COMMON or cand.rstrip("0123456789") in COMMON or cand.lstrip("0123456789") in COMMON):
            return True
    return False


def _repeated_block(p):
    n = len(p)
    for size in range(1, n // 2 + 1):
        if n % size == 0 and p[:size] * (n // size) == p:
            return True
    return False


def _sequence_share(p):
    """Share of the characters that sit in a run of 4 or more consecutive characters (abcd, 4321) or in a keyboard row."""
    low = p.lower()
    n = len(low)
    covered = [False] * n
    i = 0
    while i < n - 1:
        step = ord(low[i + 1]) - ord(low[i])
        if step in (1, -1):
            j = i + 1
            while j + 1 < n and ord(low[j + 1]) - ord(low[j]) == step:
                j += 1
            if j - i + 1 >= 4:
                for k in range(i, j + 1):
                    covered[k] = True
            i = j
        else:
            i += 1
    for row in _ROWS:
        for r in (row, row[::-1]):
            for size in range(min(n, len(r)), 3, -1):
                for start in range(0, len(r) - size + 1):
                    piece = r[start:start + size]
                    pos = low.find(piece)
                    while pos >= 0:
                        for k in range(pos, pos + size):
                            covered[k] = True
                        pos = low.find(piece, pos + 1)
    return sum(covered) / n if n else 0


def has_pattern(p):
    if len(set(p.lower())) < 4:
        return True
    if _repeated_block(p.lower()):
        return True
    return _sequence_share(p) >= 0.6


def check(password, repeat=None, names=()):
    p = password if isinstance(password, str) else ""
    if any(c in BAD_CHARS for c in p) or any(ord(c) < 32 or ord(c) == 127 for c in p) or p != p.strip():
        return "characters"
    if not MIN_LEN <= len(p) <= MAX_LEN:
        return "length"
    if p.lower() == "reprap":
        return "factory"
    if repeat is not None and repeat != p:
        return "mismatch"
    if is_common(p):
        return "common"
    low = p.lower()
    for name in names or ():
        n = str(name or "").strip().lower()
        if len(n) >= 3 and (low == n or _TAIL.sub("", low) == n or low.rstrip("0123456789") == n):
            return "names"
    if kinds(p) < 2:
        return "one_class"
    if has_pattern(p):
        return "pattern"
    return ""


def strength(password):
    """0 very weak, 1 weak, 2 acceptable, 3 strong (what the meter says). Below the minimum policy it is never above 1."""
    p = password or ""
    if check(p) != "":
        return 0 if len(p) < MIN_LEN or has_pattern(p) or is_common(p) else 1
    score = 2
    if len(p) >= 14 and kinds(p) >= 2 or (len(p) >= 20):
        score = 3
    elif len(p) >= 12 and kinds(p) >= 3:
        score = 3
    return score


# ---- the PIN of a person (new or changed PINs only) ----

# what is tried first on a keypad; dwc36/password-policy.js has the same list (tests keep them equal)
PIN_COMMON = frozenset("""
000000 0000000 00000000 000111 001122 002200 007007 010101 010203 012345 0123456 01234567 012345678 0123456789 100200 101010 102030 111000 111111 111222
112211 112233 121212 121314 123000 123123 123321 123456 1234567 12345678 123456789 1234567890 123654 123789 123123123 131313 142536 147258 147258369
159159 159357 159753 192837 200000 202020 223344 232323 246810 252525 292929 321321 333333 369369 445566 456123 456456 456789 520520 555555 654123
654321 666666 696969 741852 753159 777777 778899 789456 789789 888888 898989 987456 987654 987654321 9876543210 999999
""".split())


def _pin_valid_date(day, month, year):
    if not 1930 <= year <= 2030:
        return False
    try:
        datetime.date(year, month, day)
    except ValueError:
        return False
    return True


def pin_is_date(p):
    """DDMMAAAA, AAAAMMDD (8 digits) or DDMMAA (6 digits, year 30-99 is 19xx and 00-30 is 20xx) that is a real date between 1930 and 2030."""
    n = len(p)
    if n == 8:
        return _pin_valid_date(int(p[0:2]), int(p[2:4]), int(p[4:8])) or _pin_valid_date(int(p[6:8]), int(p[4:6]), int(p[0:4]))
    if n == 6:
        yy = int(p[4:6])
        return _pin_valid_date(int(p[0:2]), int(p[2:4]), 1900 + yy if yy >= 30 else 2000 + yy)
    return False


def pin_longest_run(p):
    """The longest run of consecutive digits, ascending (1234, 7890) or descending (4321, 3210), as a number of digits."""
    best = 1
    for want in (1, 9):  # +1 and -1 modulo 10
        run = 1
        for a, b in zip(p, p[1:]):
            run = run + 1 if (int(b) - int(a)) % 10 == want else 1
            best = max(best, run)
    return best


def pin_is_sequence(p):
    return pin_longest_run(p) >= max(5, len(p) - 1)


def pin_is_repeated(p):
    return len(set(p)) <= 2 or _repeated_block(p)


def check_pin(pin, repeat=None):
    """"" when the PIN may be set, else the reason (see the top of this file). Only for a new or changed PIN."""
    p = pin if isinstance(pin, str) else ""
    if not p.isascii() or not p.isdigit():
        return "digits"
    if not PIN_MIN_LEN <= len(p) <= PIN_MAX_LEN:
        return "length"
    if repeat is not None and repeat != p:
        return "mismatch"
    if p in PIN_COMMON:
        return "common"
    if pin_is_repeated(p):
        return "repeated"
    if pin_is_sequence(p):
        return "sequence"
    if pin_is_date(p):
        return "date"
    return ""
