"""Small pure text helpers shared by the other modules."""

import re


def str_list(v):
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def mask(line):
    """The line as it may be shown or logged (passwords hidden, shortened)."""
    parts = line.split(None, 2)
    # the old Spanish spelling is not a command any more, but a password typed with it must still never be shown or logged
    if len(parts) >= 2 and parts[0].upper() in ("BRIDGE", "PUENTE") and parts[1].upper() in ("KEY", "CLAVE"):
        return f"{parts[0]} {parts[1]} ***"
    return line[:80]


_CODE = re.compile(r"[A-Za-z][0-9]+(?:\.[0-9]+)?")


def first_token(line):
    """The code of a line, upper case: `M98 P"x"`, `M98P"x"` and `m98p"x"` are all M98, `G1X10` is G1 (the Duet reads them the same way; a policy that looked at the text
    up to the first space missed every glued line). A word that is not a code (BRIDGE, KEY...) is returned as it is."""
    parts = line.split()
    if not parts:
        return ""
    word = parts[0].upper()
    m = _CODE.match(word)
    return m.group(0) if m else word


def query_key(line):
    """Cache key: whitespace collapsed, only the code upper-cased (parameters
    such as file paths are case sensitive)."""
    parts = line.split()
    if not parts:
        return ""
    return " ".join([parts[0].upper()] + parts[1:])


def format_response(text):
    text = (text or "").strip()
    body = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n") if text else ""
    return body + "ok\r\n"
