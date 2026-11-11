"""Paths of the files of the DSF SD as the Pi sees them.

sd() maps a path written by the service itself (constants) and does not validate. resolve() is the one door for a path
that comes from a user or from an argument: it returns a real path inside the SD or raises SdPathError.
"""
import paths
import os
import re
from urllib.parse import unquote

SD = paths.SD

_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_SEPARATORS = re.compile(r"[\\/]")
_DRIVE = re.compile(r"^([A-Za-z0-9]):(.*)$", re.DOTALL)


class SdPathError(ValueError):
    """A path that is not allowed. `reason` is a short code: empty, null_byte, parent, other_drive, drive_not_allowed,
    outside, reserved_name, not_under."""

    def __init__(self, reason, path=""):
        ValueError.__init__(self, "%s: %r" % (reason, str(path)[:120]))
        self.reason = reason


def sd(rel):
    """Path on the Pi of a file on the SD: "sys/workshop/data/x.json" or
    "0:/sys/workshop/data/x.json" -> /opt/dsf/sd/sys/workshop/data/x.json."""
    r = str(rel)
    if len(r) > 1 and r[1] == ":":
        r = r[2:]
    return os.path.join(SD, *r.strip("/").split("/"))


def _inside(real, root):
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def _decoded(text):
    """The text and its percent-decoded forms (an encoded .. must not pass), up to three layers."""
    forms = [text]
    for _ in range(3):
        more = unquote(forms[-1])
        if more == forms[-1]:
            break
        forms.append(more)
    return forms


def _own_root(text, root):
    """The rest of `text` when it is a real Pi path that starts with the SD root (as written or with its links resolved), else None."""
    base = (root or SD).rstrip("/\\")
    low = os.path.normcase(text).replace("\\", "/")
    for cand in {base.replace("\\", "/"), os.path.realpath(base).replace("\\", "/")}:
        c = os.path.normcase(cand).replace("\\", "/").rstrip("/")
        if c and (low == c or low.startswith(c + "/")):
            return text[len(c):]
    return None


def clean_rel(user_path, *, allow_absolute_sd=True, root=None):
    """The path of the user as "a/b/c" relative to the SD root ("" is the root). Accepts "0:/a/b", "/a/b", "a/b" with slashes
    or backslashes. A real path of the Pi that starts with the SD root counts as absolute (only with allow_absolute_sd).
    No file system access."""
    text = str(user_path if user_path is not None else "")
    if not text.strip():
        raise SdPathError("empty", text)
    text = text.strip()
    for form in _decoded(text):
        if "\x00" in form:
            raise SdPathError("null_byte", text)
        if ".." in _SEPARATORS.split(form):
            raise SdPathError("parent", text)
    text = text.replace("\\", "/")
    own = _own_root(text, root) if allow_absolute_sd else None
    drive = None if own is not None else _DRIVE.match(text)
    if own is not None:
        text = own
    elif drive:
        if drive.group(1) != "0":
            raise SdPathError("other_drive", text)          # "D:\x", "d:/x", "1:/x"
        if not allow_absolute_sd:
            raise SdPathError("drive_not_allowed", text)
        text = drive.group(2)
    parts = [p for p in text.split("/") if p and p != "."]
    if os.name == "nt":
        for part in parts:
            if ":" in part:
                raise SdPathError("other_drive", text)
            if _WINDOWS_RESERVED.match(part.split(".")[0]):
                raise SdPathError("reserved_name", text)
    return "/".join(parts)


def resolve(user_path, *, must_be_under=None, allow_absolute_sd=True, root=None):
    """Real path (symbolic links resolved) of a path that comes from a user or an argument, always inside the SD.
    must_be_under: folder of the SD ("gcodes", "0:/sys/workshop/config") the result must be in (or be).
    allow_absolute_sd: accept the "0:/" prefix and a real Pi path that starts with the SD root.
    root: another SD root (tests, a copy of the card). Raises SdPathError."""
    base = os.path.realpath(root or SD)
    rel = clean_rel(user_path, allow_absolute_sd=allow_absolute_sd, root=root)
    real = os.path.realpath(os.path.join(base, *rel.split("/"))) if rel else base
    if not _inside(real, base):
        raise SdPathError("outside", user_path)             # a link that leaves the SD
    if must_be_under is not None:
        under_rel = clean_rel(must_be_under)
        under = os.path.realpath(os.path.join(base, *under_rel.split("/"))) if under_rel else base
        if not _inside(real, under):
            raise SdPathError("not_under", user_path)
    return real
