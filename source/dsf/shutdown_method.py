"""
How the equipment is turned off (2026-10-10: "some may not have a meter or
a switch at the start of the whole system; I want to shut down, schedule or
time using the PS_ON, but it must be clear").

config.json["apagado"]:
    "metodo":    "auto" (default) | "medidor" | "pson"
    "power_off_pi": true (default) -> with PS_ON the Raspberry Pi is also turned off

  meter:   the Tuya meter / switch cuts ALL the power (Pi + Duet +
           supply). It is what was always done.
  relay:   a relay on a Duet output (M950 P<n>) that cuts ALL the
           power: M42 P<n> S<0|1> ("rele": {salida, power_off_with}).
  pson:    M81 turns off the supply controlled by the Duet's PS_ON pin (M80
           C"pson" in config.g): motors, laser, heaters. The Pi and the
           board stay on ONLY if they have their own power.
  auto:    meter if one is configured; otherwise the relay if it is chosen and
           configured; otherwise PS_ON if the board has it; otherwise only the Pi.

"Shut down now", "Shut down when finished" and the timer all go through
handlers/shutdown_all.py, which uses this. The text (desc) is published in
plugins.WorkshopService.data.shutdownMethod and in global.shutdownDesc (used by the
confirmation of macros/power/shutdown-all.g), so all the screens say
the same thing about what is going to happen.

"""
from messages import M

METHODS = ("auto", "meter", "relay", "pson")


def _state():
    """state of the object model (None if it could not be read)."""
    try:
        import machine_state  # single subscription to DSF (no HTTP)

        return machine_state.get_status(timeout=5).get("state") or {}
    except Exception:
        return None


def _has_meter():
    try:
        import tuya_meter

        return tuya_meter.meter_current() is not None
    except Exception:
        return False


def relay_cfg(config):
    """{output: n | None, power_off_with: 0|1}: relay on a Duet output
    (M950 P<n>) that cuts ALL the power (2026-10-10)."""
    r = (config.get("shutdown") or {}).get("relay") or {}
    try:
        output = int(r.get("output"))
        if not 0 <= output <= 63:
            output = None
    except (TypeError, ValueError):
        output = None
    return {"output": output, "power_off_with": 1 if r.get("power_off_with") == 1 else 0}


def info(config, status=None):
    ap = config.get("shutdown") or {}
    method = ap.get("method") if ap.get("method") in METHODS else "auto"
    power_off_pi = bool(ap.get("power_off_pi", True))
    meter = _has_meter()
    st = _state() if status is None else status
    pson = None if st is None else st.get("atxPower") is not None
    rc = relay_cfg(config)
    gp = (st or {}).get("gpOut") or []
    outputs = [i for i, g in enumerate(gp) if g]  # salidas M950 P configuradas
    relay = rc["output"] is not None and (st is None or rc["output"] in outputs)
    if method in ("meter", "relay", "pson"):
        effective = method
    else:
        effective = "meter" if meter else "relay" if relay else "pson" if pson else "pi"
    # desc / notice are messages: published as {"key", "params"}, every page shows them in its own language;
    # macros/power/shutdown-all.g reads the two rendered texts of global.shutdownDesc / shutdownDescEn (emit()).
    notice = ""
    if effective == "meter":
        desc = M("shutdown_method_shuts_system_down_safely_cuts_all")
        if not meter:
            notice = M("shutdown_method_no_meter_configured_consumption_meter_only")
    elif effective == "relay":
        n = rc["output"]
        desc = M("shutdown_method_shuts_down_cuts_all_power_relay_output", n=str(n) if n is not None else "?")
        if n is None:
            notice = M("shutdown_method_relay_output_has_not_been_chosen")
        elif not relay:
            notice = M("shutdown_method_output_not_configured_on_duet", n=str(n))
    elif effective == "pson":
        if power_off_pi:
            desc = M("shutdown_method_shuts_system_down_safely_turns_supply")
        else:
            desc = M("shutdown_method_turns_supply_off_ps_m81_motors")
        if pson is False:
            notice = M("shutdown_method_board_has_no_ps_configured_m80")
    else:
        desc = M("shutdown_method_shuts_only_system_down_safely_there")
    return {
        "method": method,
        "effective": effective,
        "power_off_pi": power_off_pi,
        "has_meter": meter,
        "has_pson": pson,
        "relay": rc,
        "has_relay": relay,
        "outputs": outputs,
        "desc": desc,
        "notice": notice,
    }


_published = [None]


def emit(bridge, config, force=False):
    """Publishes the method (if it changed) in plugin data and in global.shutdownDesc /
    global.shutdownDescEn (English, for macros/power/shutdown-all.g)."""
    i = info(config)
    if not force and i == _published[0]:
        return i
    _published[0] = i
    try:
        bridge.set_status("shutdownMethod", i)
    except Exception:
        pass
    # only desc (short: a long text in M291 may not fit); the notice goes in the bar
    for label, lang in (("shutdownDesc", "es"), ("shutdownDescEn", "en")):
        raw_text = i["desc"].text(lang).replace('"', '""')
        # set fails (returns "Error: ... unknown variable") if the global does not exist
        try:
            r = bridge.send(f'set global.{label} = "{raw_text}"')
            missing = bool(r and "rror" in str(r))
        except Exception:
            missing = True  # depending on the version, the error arrives as an exception
        if missing:
            try:
                bridge.send(f'global {label} = "{raw_text}"')
            except Exception:
                pass
    return i
