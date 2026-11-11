"""What a board answer says, as a typed state (pure, standard library only: layer L0).

Item 11 of the backlog, finding M4: the service used to decide "failed" by looking for the word "error" anywhere in a text
(`"rror" in reply`, `.lower().startswith("error")`). A real M122 answer contains the line "Error status: 0x00" and is not a
failure; a message of ours that begins "Error de lectura corregido" is a sentence, not a board error. The rule that RepRapFirmware
(through DSF) uses is a PREFIX of a line, so that is the only thing read here.

classify(reply) -> OK, WARNING or ERROR. Nothing else decides "failed" from a text: test_board_reply.py keeps the list of the places
that still do (they are in the safety path or belong to other work) and forbids new ones.

Table of prefixes (PREFIXES). `source` says where each one comes from and `verified` how sure it is:
  seen   the exact text appears in a capture or in a log of the real machine kept in this repository
  rrf    the convention of RRF/DSF for a reply (a message type becomes a prefix), NOT captured from this machine
  no     not verified: nobody has seen it here (it is kept out of the decision until a capture confirms it)
dsf/fixtures/real holds only read-only answers (M115, M122 idle): no real error answer has been captured yet, so no prefix here is
`verified="seen"` as a bridge reply. The G30/G32/G29/M671 error texts used by the tests of the machine module are still invented.
"""

OK = "ok"
WARNING = "warning"
ERROR = "error"

# (state, prefix, verified, source)
PREFIXES = (
    (ERROR, "Error:", "rrf",
     "RRF/DSF prefix of an error reply. The same text opens the lines of the real event log seen 2026-10-08 (event_watcher.py). "
     "No bridge reply with it in dsf/fixtures/real."),
    (WARNING, "Warning:", "rrf",
     "RRF/DSF prefix of a warning reply; handled by event_watcher.py for the event log. No capture of a bridge reply with it."),
)

# Real text that holds the word but is not a board error: dsf/fixtures/real/m122-rrf3.6.3-mb6hc-idle.txt, line "Error status: 0x00".
# The prefix is "Error:" (with the colon), never the bare word.
NOT_AN_ERROR_EXAMPLE = "Error status: 0x00"


def _text(reply):
    if reply is None:
        return ""
    if isinstance(reply, (bytes, bytearray)):
        return bytes(reply).decode("utf-8", "replace")
    return str(reply)


def _state_of(line):
    line = line.lstrip()
    for state, prefix, verified, _source in PREFIXES:
        if verified == "no":
            continue
        if line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)] in " \t"):
            return state
    return OK


def classify(reply, first_line_only=False):
    """ERROR when a line of the reply begins with "Error:", else WARNING when one begins with "Warning:", else OK.
    first_line_only: look at the first non-empty line only (a message of ours that is a report, not a board answer)."""
    found = OK
    for line in _text(reply).splitlines():
        if not line.strip():
            continue
        state = _state_of(line)
        if state == ERROR:
            return ERROR
        if state == WARNING:
            found = WARNING
        if first_line_only:
            break
    return found


def is_error(reply, first_line_only=False):
    return classify(reply, first_line_only) == ERROR
