"""Small pure text helpers shared by the other modules."""


def str_list(v):
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def mask(line):
    """The line as it may be shown or logged (passwords hidden, shortened)."""
    parts = line.split(None, 2)
    # the old Spanish spelling is not a command any more, but a password typed with it must still never be shown or logged
    if len(parts) >= 2 and parts[0].upper() in ("BRIDGE", "PUENTE") and parts[1].upper() in ("KEY", "CLAVE"):
        return f"{parts[0]} {parts[1]} ***"
    return line[:80]


def first_token(line):
    parts = line.split()
    return parts[0].upper() if parts else ""


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
