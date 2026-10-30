"""Read-only scan of the configuration text of the machine (Machine v2, phase 0).

The object model does not tell everything Machine needs: for example how many leadscrew positions M671 declares, or where the
G31 line of the probe lives. This module looks for those lines in `config.g` and in the macros it calls with M98 (one file
following the other, a few levels deep), so it works with a plain `config.g` and assumes no file of the workshop.

Pure part: `scan_text(text, path)` and `scan(read, root)`; `read(path)` is injected (it returns the text of a file of the SD
or None), so tests need no disk. The I/O side is in capabilities_io.py.

It NEVER writes: the patchers that edit these lines are a later phase (machine.config.plan / apply).
"""
import re

ROOT = "0:/sys/config.g"
BED = "0:/sys/bed.g"
MAX_FILES = 8
MAX_DEPTH = 2
MAX_BYTES = 400000

_WORD = r"(?:^|\s)%s(?![0-9A-Za-z.])"
_M98 = re.compile(r'\bM98\s+P"([^"]{1,120})"', re.I)
_ARG = re.compile(r"(?<![A-Za-z0-9])([XYZUVWABC])\s*(-?[0-9.]+(?::-?[0-9.]+)*)", re.I)


def strip_comment(line):
    """The line without its `;` comment (a `;` inside quotes is kept)."""
    out, quoted = [], False
    for ch in str(line):
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            break
        out.append(ch)
    return "".join(out).strip()


def resolve(name):
    """Path of a macro named in an M98 as `0:/sys/...`: absolute names keep their path, plain names are in 0:/sys."""
    n = str(name).strip()
    if len(n) > 1 and n[1] == ":":
        return n
    if n.startswith("/"):
        return "0:" + n
    return "0:/sys/" + n


def _has(code, line):
    return re.search(_WORD % code, line, re.I) is not None


def _values(line):
    out = {}
    for m in _ARG.finditer(line):
        out[m.group(1).upper()] = [float(x) for x in m.group(2).split(":") if x not in ("", "-", ".")]
    return out


def scan_text(text, path):
    """What one file declares: {"m671": [..], "g31": [..], "m208": [..], "m557": [..], "m558": [..], "calls": [paths]}.
    Each finding is {"file", "line", "text"} plus "entries" (M671) or "values"."""
    found = {"m671": [], "g31": [], "m208": [], "m557": [], "m558": [], "calls": []}
    for n, raw in enumerate(str(text or "").splitlines(), 1):
        line = strip_comment(raw)
        if not line:
            continue
        item = {"file": path, "line": n, "text": line[:160]}
        if _has("M671", line):
            vals = _values(line)
            entries = max((len(v) for k, v in vals.items() if k in ("X", "Y")), default=0)
            found["m671"].append(dict(item, entries=entries))
        elif _has("G31", line):
            found["g31"].append(dict(item, values=_values(line)))
        elif _has("M208", line):
            found["m208"].append(item)
        elif _has("M557", line):
            found["m557"].append(item)
        elif _has("M558", line):
            found["m558"].append(item)
        for m in _M98.finditer(line):
            found["calls"].append(resolve(m.group(1)))
    return found


def scan(read, root=ROOT, bed=BED):
    """Follows `root` and the macros it calls. Returns
    {"read": bool (root found), "files": [paths read], "m671": [...], "g31": [...], "m208": [...], "m557": [...], "m558": [...],
     "bed_g": bool}. Never raises: a file that cannot be read is skipped."""
    out = {"read": False, "files": [], "m671": [], "g31": [], "m208": [], "m557": [], "m558": [], "bed_g": False}
    queue, seen = [(root, 0)], set()
    while queue and len(out["files"]) < MAX_FILES:
        path, depth = queue.pop(0)
        if path.lower() in seen:
            continue
        seen.add(path.lower())
        try:
            text = read(path)
        except Exception:  # noqa: BLE001 - tolerant by design
            text = None
        if text is None:
            continue
        text = str(text)[:MAX_BYTES]
        if path == root:
            out["read"] = True
        out["files"].append(path)
        got = scan_text(text, path)
        for key in ("m671", "g31", "m208", "m557", "m558"):
            out[key].extend(got[key])
        if depth < MAX_DEPTH:
            queue.extend((c, depth + 1) for c in got["calls"])
    try:
        out["bed_g"] = read(bed) is not None
    except Exception:  # noqa: BLE001
        out["bed_g"] = False
    return out


def m671_entries(scanned):
    """Number of leadscrew positions the configuration declares (the last M671 wins, like in the firmware); 0 = none."""
    items = (scanned or {}).get("m671") or []
    return items[-1]["entries"] if items else 0
