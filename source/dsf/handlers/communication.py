"""
Internal implementation of the API operation(s) comms.get, comms.set (api_ops.py maps their named
arguments to the one-letter parameters below).

Through where the Pi sends its G-codes to the Duet (see dsf/communication.py).

Usage: <params>                       (only reads and publishes)
     <params> C"auto"|"Aux2"|"Aux"|"SBC"   plugin codes
     <params> J"auto"|"SBC"|"Aux2"|"Aux"   jog G1s (auto: Aux2 if free, otherwise SBC)

Changing a channel by hand is BLOCKED (2026-10-12): it is only accepted in
advanced mode, with the two parameters A1 and K"entiendo" besides C/J, for example
     <params> J"SBC" A1 K"entiendo"
Without them it answers the warning (communication.BLOCKED_NOTICE, also in
data.comunicacion.advertencia; data.comunicacion.bloqueado = true) and
changes nothing. Reading/publishing does not need it.
It only accepts channels that can be chosen now (see communication.ALL: the
ones reserved by the Duet or DWC and those taken by a PanelDue are rejected).
It is saved in config.json["comunicacion"] and takes effect instantly (the
no-limits jog block, from the next time it is activated).

2026-10-12 (finding 9 of docs-internal/AUDITORIA-MOTION.md): it cannot be
changed with a file or live job, with recent bridge activity,
with a jog gesture in progress or with the no-limits jog active. When the
jog channel is changed, G90 is sent through the one being left.

"""
import activity
import communication
import jog_move
from messages import M, J, B


def _choose(value, options):
    v = str(value or "").strip()
    for o in options:
        if o.lower() == v.lower():
            return o
    return None


def _not_eligible(cid):
    """Reason if the channel cannot be chosen now (reserved by the Duet or
    DWC, taken by a PanelDue, does not exist); "" if it can."""
    if cid == "auto":
        return ""
    c = next((x for x in communication._channels(communication._inputs(), communication._ports_serial()) if x["id"] == cid), None)
    if c is None or c["eligible"]:
        return ""
    return c["reason"] or M("communication_cannot_be_chosen")


def _advanced(params):
    """Modo avanzado: A1 y K"entiendo" explicitos."""
    a = str(params.get("A", "0")).strip() in ("1", "1.0", "true")
    k = str(params.get("K", "")).strip().lower() == "entiendo"
    return a and k


def run(params, bridge, config):
    c = config.setdefault("communication", {})
    change = []
    if params.get("C") is not None or params.get("J") is not None:
        if not _advanced(params):
            return M("communication_changing_channel_blocked", notice=communication.BLOCKED_NOTICE)
        reason = jog_move.reason_cannot_change_channel(bridge)
        if reason:
            return M("communication_cannot_change_channel_now", reason=reason)
    jog_before = jog_move._name_channel(communication.channel_jog())
    if params.get("C") is not None:
        chan = _choose(params.get("C"), communication.CHANNELS)
        if not chan:
            return M("communication_communication_use_c_auto_c_aux2")
        reason = _not_eligible(chan)
        if reason:
            return M("communication_communication_cannot_used", chan=chan, reason=reason)
        c["channel"] = chan
        change.append(M("comm_plugin_codes", channel=chan))
    if params.get("J") is not None:
        jog = _choose(params.get("J"), communication.CHANNELS_JOG)
        if not jog:
            return M("communication_communication_use_j_sbc_j_aux2")
        reason = _not_eligible(jog)
        if reason:
            return M("communication_communication_cannot_used_jog", jog=jog, reason=reason)
        c["channel_jog"] = jog
        change.append(M("comm_jog", channel=jog))
    if change:
        bridge.save_config()
    i = communication.emit(bridge, config, force=True)
    if i["channel_jog"] != jog_before:
        jog_move.close_channel(jog_before)
    if change:
        activity.log_event(bridge, "config", M("comm_changed", parts=J(change)))
    raw_text = M("communication_plugin_codes_over_jog_over", channel=i['channel'], channel_jog=i['channel_jog'])
    parts = [raw_text]
    if i["notices"]:
        parts.append(M("communication_watch_out", notes=J(i["notices"], sep=" ")))
    if i.get("suggestion"):
        parts.append(M("communication_suggestion", text=i["suggestion"]))
    return J(parts, sep=". ") if len(parts) > 1 else raw_text
