"""
Through where the Pi talks to the Duet (2026-10-10: "I want it to be explicit
and configurable through where the Pi sends G-codes ... there are users who
may use a PanelDue; if it has no channel to send through it cannot use the
plugin or should be sent to a page explaining that").

Everything goes through DSF (the Duet in SBC mode, joined to the Pi by SPI).
Without SBC mode there is no DSF and this plugin cannot run (plugin.json:
sbcRequired); the Taller* plugins warn about it and link to docs/communication.md.

Inside DSF each G-code goes through an RRF "channel" (a queue of its own). Two uses:

  canal      the plugin's OWN codes (LEDs, driver reads, set
             global, light/air macros, heartbeat). Default "auto".
  channel_jog  the jog's G1s. Default "auto" (2026-10-12, user's
             decision): Aux2 if free, otherwise SBC. The no-limits jog block
             lets ONLY this channel through (see jog_move._block_loop).

config.json["comunicacion"] = {"canal": "auto"|"Aux2"|"Aux"|"SBC",
                               "channel_jog": "auto"|"SBC"|"Aux2"|"Aux"}
An installation that already has a channel_jog chosen (SBC, Aux2 or Aux) keeps
it; without a value it is "auto".

Changing the channels by hand is BLOCKED (BLOCKED_NOTICE): the handler only
accepts it in advanced mode (see handlers/communication.py) and the published
information carries "bloqueado" and "advertencia" so that the page shows it.

  SBC   the Pi's common channel: other programs also use it through DSF
        (the G-code bridge of the live jobs over the network). It always exists,
        but a long macro sent through it makes everything else wait.
        Free or shared according to the REAL use (2026-10-10): shared while
        there are connections to the G-code bridge (a program sending live
        jobs); free if there are none.
  Aux   the channel of the PanelDue serial port (M575 P1). Free if there is no
        PanelDue or terminal on that port.
  Aux2  the second serial port (M575 P2). Free if nothing sends G-code through it.
  auto  Aux2 if it is free and is not the jog's, otherwise Aux, otherwise SBC
        (shared). With the jog on Aux2, the jog has its own channel.

A serial port with M575 ... S7 (device mode, e.g. Modbus/RS485) does not
send G-code: the channel stays free.

Full list (2026-10-10, request: "list them all, but whatever could endanger the
communication or the internal processes of the official Duet and DWC should
not be selectable"): RRF has 14 channels and all are shown with their use, but
only Aux2, Aux and SBC can be chosen, and Aux/Aux2 only if they are free. The
others belong to DWC (HTTP), to the jobs (File, File2), to the internal
motion queues (Queue, Queue2), to the M581 triggers (Trigger), to
daemon.g (Daemon) or to the power-failure pause (Autopause): an own code
there gets into another Duet process's queue. USB, LCD and Telnet were
never used from this service: they stay unselectable until tested.
History that justifies it: with everything through SBC, the G-code bridge made
the service's codes wait (timeouts with mdf3mm.g) -> Aux2 (0bc5f6d);
a hung API call jammed DWC's HTTP channel (449f25c).
If config.json has a channel that can no longer be chosen (a PanelDue was
connected, or an old version saved it), the automatic one is used (or SBC for
the jog) and a notice is given; it does not fail.

"""
import paths
import os
import re
import threading
from messages import M

CHANNELS = ("auto", "Aux2", "Aux", "SBC")
CHANNELS_JOG = ("auto", "SBC", "Aux2", "Aux")
_PORT = {"Aux": 1, "Aux2": 2}  # M575 P<n>
# The 14 RRF channels in the order of inputs[] of the object model:
# (id, what it is for, can be chosen, reason if it cannot)
ALL = (
    ("HTTP", M("communication_dwc_this_interface_web_requests"), False, M("communication_dwc_s_code_our_own_there")),
    ("Telnet", M("communication_telnet_connections_to_board"), False, M("communication_untested_from_this_service")),
    ("File", M("communication_job_printing_cutting"), False, M("communication_belongs_to_running_job")),
    ("USB", M("communication_computer_over_board_usb"), False, M("communication_untested_pc_over_usb_would_share")),
    ("Aux", M("communication_paneldue_serial_port"), True, ""),
    ("Trigger", M("communication_trigger_macros"), False, M("communication_belongs_to_duet_triggers")),
    ("Queue", M("communication_internal_motion_queue"), False, M("communication_internal_to_duet")),
    ("LCD", M("communication_12864_screen_on_board"), False, M("communication_untested_from_this_service")),
    ("SBC", M("communication_system_programs_connected_to_dsf"), True, ""),
    ("Daemon", M("communication_daemon_g_runs_in_loop"), False, M("communication_daemon_g_s_would_slow_down")),
    ("Aux2", M("communication_second_serial_port"), True, ""),
    ("Autopause", M("communication_power_failure_pause"), False, M("communication_internal_to_duet")),
    ("File2", M("communication_second_job_file"), False, M("communication_belongs_to_running_job")),
    ("Queue2", M("communication_second_internal_motion_queue"), False, M("communication_internal_to_duet")),
)
_INDEX = {t[0]: i for i, t in enumerate(ALL)}
# Changing the channels by hand (2026-10-12): blocked except in advanced mode
BLOCKED_NOTICE = (
    M("communication_changing_channel_by_hand_can_leave")
)
CONFIG_G = paths.CONFIG_G
DOC = "https://github.com/jhonf441/WorkshopService/blob/main/docs/communication.md"

_lock = threading.Lock()
_state = {"channel": "SBC", "channel_jog": "SBC", "info": None}


def _cfg(config):
    c = config.get("communication") or {}
    chan = c.get("channel") if c.get("channel") in CHANNELS else "auto"
    jog = c.get("channel_jog") if c.get("channel_jog") in CHANNELS_JOG else "auto"
    return chan, jog


def _inputs():
    """List inputs[] of the model (None in an entry = the board does not have that
    channel); None if it could not be read. inputs is not in the common
    subscription (it changes with every G-code line): a one-shot read through
    DSF's socket, only that field (2026-10-12; before, the full
    /machine/status every 10 s)."""
    try:
        import machine_state

        return machine_state.read_one_shot(["inputs"]).get("inputs")
    except Exception:
        return None


def _ports_serial():
    """{1: mode, 2: mode} of the active M575 lines of config.g (not
    commented out). Mode = the S number (S1 PanelDue, S2 terminal, S7 device)."""
    out = {}
    try:
        with open(CONFIG_G, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.split(";", 1)[0]
                m = re.match(r"\s*M575\b(.*)", line, re.I)
                if not m:
                    continue
                p = re.search(r"\bP(\d+)", m.group(1), re.I)
                s = re.search(r"\bS(\d+)", m.group(1), re.I)
                if p:
                    out[int(p.group(1))] = int(s.group(1)) if s else 1
    except OSError:
        pass
    return out


def _connections_bridge():
    """Open connections to the G-code bridge (live jobs over the network), which
    sends through SBC. 0 if it cannot be known."""
    try:
        import health_poller
        return int(health_poller.clients_bridge() or 0)
    except Exception:
        return 0


def _channels(inputs, ports):
    """The 14 channels with their state. choosable = can be chosen NOW."""
    entries = []
    for idx, (cid, use, allowed, by_that) in enumerate(ALL):
        present = True
        if inputs is not None:
            present = idx < len(inputs) and inputs[idx] is not None
        state_txt = "free"
        reason = ""
        if not present:
            state_txt, reason = "no_exists", M("communication_board_has_no_such_channel")
        elif not allowed:
            state_txt, reason = "reserved", by_that
        elif cid in _PORT:
            kind = ports.get(_PORT[cid])
            if kind is not None and kind != 7:
                who = M("communication_a_paneldue") if kind == 1 else M("communication_a_serial_terminal")
                state_txt = "busy"
                reason = M("communication_used_by_m575", who=who, port=_PORT[cid], kind=kind)
        elif cid == "SBC":
            n = _connections_bridge()
            if n:
                state_txt = "shared"
                reason = M("communication_shared_connection_s_g_code_bridge", n=n)
            else:
                reason = M("communication_free_now_no_connection_g_code")
        entries.append({
            "id": cid,
            "usage": use,
            "exists": present,
            "state": state_txt,
            "busy": state_txt == "busy",
            "eligible": present and allowed and state_txt != "busy",
            "reason": reason,
        })
    return entries


def info(config):
    channel_cfg, jog_cfg = _cfg(config)
    chans = _channels(_inputs(), _ports_serial())
    by_id = {c["id"]: c for c in chans}
    notices = []
    if jog_cfg == "auto":
        jog = "Aux2" if by_id["Aux2"]["eligible"] else "SBC"
    elif by_id[jog_cfg]["eligible"]:
        jog = jog_cfg
    else:
        jog = "SBC"
        notices.append(M("communication_jog_channel_not_eligible_sbc_used", channel_cfg=jog_cfg, reason=by_id[jog_cfg]['reason']))
    # 2026-10-12 (AUDITORIA-MOVIMIENTO 3.3.2): "auto" does not take the jog's channel,
    # so a jog moved to Aux2 has a channel of its own (its G91 is seen by nobody
    # else and the no-limits jog block covers SBC, the bridge's)
    auto = next((c for c in ("Aux2", "Aux") if by_id[c]["eligible"] and c != jog), "SBC")
    if channel_cfg == "auto":
        chan = auto
        if chan == "SBC":
            notices.append(M("communication_aux2_aux_not_free_service_codes"))
    elif by_id[channel_cfg]["eligible"]:
        chan = channel_cfg
    else:
        chan = auto
        notices.append(M("communication_service_codes_used_automatic", channel_cfg=channel_cfg, reason=by_id[channel_cfg]['reason'], chan=chan))
    if chan == jog:
        notices.append(M("communication_jog_service_codes_go_through_same", chan=chan))
    # Proposal (does not change the default): with Aux2 free, the jog on its own
    # channel. On SBC it shares the G90/G91 state with the G-code bridge.
    hint = ""
    if jog == "SBC" and by_id["Aux2"]["eligible"]:
        hint = M("communication_aux2_free_if_you_move_jog")
    return {
        "suggestion": hint,
        "mode": "SBC",
        "channel_cfg": channel_cfg,
        "channel": chan,
        "channel_jog_cfg": jog_cfg,
        "blocked": True,
        "warning": BLOCKED_NOTICE,
        "channel_jog": jog,
        "channels": chans,
        "notices": notices,
        "doc": DOC,
    }


def update(config):
    """Recalculates the channels (at startup and when the configuration changes)."""
    i = info(config)
    with _lock:
        _state["channel"] = i["channel"]
        _state["channel_jog"] = i["channel_jog"]
        _state["info"] = i
    return i


def _code_channel(label):
    from dsf.commands.code_channel import CodeChannel

    return getattr(CodeChannel, label, CodeChannel.SBC)


def channel_plugin():
    """CodeChannel for the plugin's own codes."""
    with _lock:
        return _code_channel(_state["channel"])


def channel_jog():
    """CodeChannel for the jog's G1s."""
    with _lock:
        return _code_channel(_state["channel_jog"])


_published = [None]


def emit(bridge, config, force=False):
    i = update(config)
    if force or i != _published[0]:
        _published[0] = i
        try:
            bridge.set_status("communication", i)
        except Exception:
            pass
    return i
