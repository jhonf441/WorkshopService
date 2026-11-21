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
"""
import re

MIN_LEN = 10
MAX_LEN = 60
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
