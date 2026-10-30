"""
Internal implementation of the API operation(s) power.off (api_ops.py maps their named
arguments to the one-letter parameters below).

Cuts the complete power (Pi + Duet + motors) through the Tuya
meter/breaker "Impresora" on the local network (dlq / WIFI intelligent
leakage switch), and along the way leaves the Pi shutting down safely.

Usage: <params>

⚠️ HISTORY OF FAILURES IN PRODUCTION (2026-10-06) -- read before touching:

1) v1: "sudo shutdown -h now" failed silently for lack of sudo permission
   for the real user that runs the plugin ("dsf", not the login user) --
   fixed with a NOPASSWD rule in /etc/sudoers.d/dsf-power, and checking
   the real returncode.

2) v2: the cut was launched with subprocess.Popen(start_new_session=True)
   AFTER the shutdown, hoping that would make it independent from this
   process. FALSE: start_new_session() separates the SESSION/process group,
   but does not take the child out of the systemd cgroup -- this plugin
   runs inside the cgroup of duetcontrolserver.service, and systemd kills
   that WHOLE cgroup when stopping the service (KillMode=control-group by
   default). The cut died before its first attempt.

3) v3: it was changed to schedule the cut via `at` (atd), a separate service
   that does survive the cgroup -- confirmed live that an `at` job runs in
   the middle of a real "sudo reboot". BUT it kept failing: `at` only
   schedules with a granularity of 1 MINUTE at minimum, and by the time the
   job ran (60-120 s later), the Pi's network was already down (a normal part
   of its own shutdown sequence, which stops network services well before
   reaching the final halt) -- atd survived, but there was nothing left to
   send anything to the meter with.

4) v4 (this one): instead of fighting the order in which systemd shuts
   things down, the sequence is completely inverted. sync() (flushing the
   write cache to disk) is ALMOST INSTANTANEOUS and is the part that really
   protects against corruption -- there is no need to wait for the complete
   service shutdown for the data to be safe. So now: (1) sync() right away,
   (2) best-effort remount-ro (cosmetic, avoids the "dirty shutdown" flag),
   (3) Tuya cut RIGHT NOW, while the network is still 100% guaranteed up
   (nothing has been touched yet), and only at the end (4) "shutdown -h now"
   is fired as cleanup -- by then the power is already cut or about to be, so
   it does not matter whether the normal shutdown manages to finish or not.

The local key (DEVICE_KEY) is assigned again by Tuya every time the device
is re-paired from the app (for example, when moving it to another WiFi
network) -- if it stops working in the future, the tinytuya wizard has to
be run again to get the updated key.

"""
import os
import subprocess
import time

import tinytuya

import activity
from messages import M, J, B

# 2026-10-09 (publication on GitHub): the Tuya meter credentials no longer
# live in the code -- they come from config.json["medidor"] (loaded from
# the Consumption > Meter page) via tuya_meter.meter_current(). Without a
# configured meter the Pi still shuts down but the power is not cut.
CUT_ATTEMPTS = 4
CUT_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "apagartodo_corte.log")  # plugin folder (new or old Id)


def _log(msg):
    with open(CUT_LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}\n")


def _has_heat():
    """Some heater above 50 C (nozzle / bed in FFF)."""
    try:
        import machine_state  # single subscription to DSF (no HTTP)

        heat = machine_state.read_in("heat.heaters", [], timeout=5) or []
        return any(h and (h.get("current") or 0) > 50 for h in heat)
    except Exception:
        return False


def _power_off_pson(bridge, met):
    """PS_ON: sync, M81 (or M81 S1 if something is hot: the board waits for the
    thermostatic fans to turn off, so as not to cook the nozzle) and, if
    chosen, shut down the Pi. If the Pi is powered from that same supply, the
    sync already left the data safe."""
    activity.log_event(bridge, "power", M("shutdown_pson_system") if met["power_off_pi"] else M("shutdown_pson"))
    os.sync()
    _log("sync() done")
    heat = _has_heat()
    cod = "M81 S1" if heat else "M81"
    try:
        r = bridge.send(cod)
        _log(f"{cod} sent: {r}")
    except Exception as e:
        _log(f"{cod} exception: {e}")
        raise RuntimeError(M("shutdown_all_could_not_send_to_board", cod=cod, e=e))
    if r and "rror" in str(r):
        raise RuntimeError(M("shutdown_all_board_rejected_check_pson", cod=cod, r=r))
    waiting = M("shutdown_all_something_hot_waits_fans") if heat else ""
    if met["power_off_pi"]:
        subprocess.Popen(["sudo", "-n", "shutdown", "-h", "now"])
        _log("shutdown -h now fired")
        return M("shutdown_all_psu_off_pson_system_shutting_down", waiting=waiting)
    return M("shutdown_all_psu_off_pson_system_still_on", waiting=waiting)


def _power_off_relay(bridge, met):
    """Relay on a Duet output that cuts ALL the power: same order as the
    meter (sync NOW, cut while everything works, shutdown at the end as cleanup)."""
    n, v = met["relay"]["output"], met["relay"]["power_off_with"]
    activity.log_event(bridge, "power", M("shutdown_relay", output=n))
    os.sync()
    _log("sync() done")
    cod = f"M42 P{n} S{v}"
    try:
        r = bridge.send(cod)
        _log(f"{cod} sent: {r}")
    except Exception as e:
        r = None
        _log(f"{cod} exception (it may be the power cut itself): {e}")
    subprocess.Popen(["sudo", "-n", "shutdown", "-h", "now"])
    _log("shutdown -h now fired")
    if r and "rror" in str(r):
        raise RuntimeError(M("shutdown_all_board_rejected_system_shutting_down_anyway", cod=cod, r=r))
    return M("shutdown_all_relay_output_p_operated_power_cut", n=n)


def _cut_extras():
    """2026-10-10 (several meters): before turning off the rest, the meters that do
    NOT power the Pi and have "corta" (e.g. the bed on another line) are cut, in
    their order. The one that powers the Pi always goes last (further down, or
    it is left for PS_ON / relay). Returns [(name, ok)]."""
    import meters
    import tuya_meter
    done_items = []
    for m in meters.order_of_cut(meters.entries()):
        if m["feeds_pi"]:
            continue
        ok = tuya_meter.cut(meters.as_dev(m), attempts=3, log=_log)
        _log(f"extra meter {m['slot']} ({m['name']}): {'cut' if ok else 'could NOT cut'}")
        done_items.append((m["name"], ok))
    return done_items


def run(params, bridge, config):
    with open(CUT_LOG, "w") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] apagartodo started\n")

    # First the extra meters (bed, etc.), in any method: while the network
    # and the Pi are still surely up.
    try:
        extras = _cut_extras()
    except Exception as e:
        _log(f"cutting the extras: exception (going on): {e}")
        extras = []
    if extras:
        try:
            activity.log_event(bridge, "power", M("before_shutdown", parts=J([M("extra_cut" if ok else "extra_cut_failed", name=n) for n, ok in extras])))
        except Exception:
            pass

    # 2026-10-10: the method is chosen on the bar (Shutdown > How it turns off):
    # Tuya meter (as always) or the Duet's PS_ON (M81). See shutdown_method.py.
    import shutdown_method

    met = shutdown_method.info(config)
    _log(f"method {met['method']} -> {met['effective']} (power_off_pi={met['power_off_pi']})")
    if met["effective"] == "pson":
        return _power_off_pson(bridge, met)
    if met["effective"] == "relay" and met["has_relay"]:
        return _power_off_relay(bridge, met)

    # It is recorded BEFORE touching anything -- in a few moments the Pi's own
    # power is cut, so there is no second chance to leave this written afterwards.
    activity.log_event(bridge, "power", M("shutdown_meter") if met["effective"] == "meter" else M("shutdown_system"))

    # 1) Filesystem safe NOW -- this is what really matters, and it is
    # almost instantaneous. There is no need to wait for systemd's complete
    # shutdown for the data to be protected.
    os.sync()
    _log("sync() done")

    # Cosmetic/best-effort: avoids the "dirty shutdown" flag on the next
    # startup. If it fails (filesystem busy, no permission, etc.) it does not
    # matter -- sync() already did the part that really protects data.
    # 2026-10-09: there used to be a "sudo mount -o remount,ro /" here that the
    # sudo rule never allowed (it always failed, silently). It is removed:
    # less sudo, and the sync() above is what protects the data.
    try:
        os.sync()
    except Exception as e:
        _log(f"remount-ro exception (ignored): {e}")

    # 2) Cut the Tuya meter NOW, while the network is still 100%
    # up -- nothing has been touched yet that could bring it down.
    cut_ok = False
    import tuya_meter
    dev = tuya_meter.meter_current()
    if dev is None:
        _log("no meter configured (config.json['medidor']): the power is not cut")
    for attempt in range(1, (CUT_ATTEMPTS if dev else 0) + 1):
        try:
            d = tinytuya.Device(dev["id"], dev["ip"], dev["key"])
            d.set_version(float(dev["version"]))
            r = d.set_value(16, False)
            _log(f"attempt {attempt}: {r}")
            if not (isinstance(r, dict) and r.get("Error")):
                cut_ok = True
                _log("cut OK")
                break
        except Exception as e:
            _log(f"attempt {attempt} exception: {e}")
        if attempt < CUT_ATTEMPTS:
            time.sleep(1)

    # 3) Normal shutdown as cleanup -- by this point the power has already
    # been cut or is about to be, so it does not matter whether this command
    # actually finishes or not.
    subprocess.Popen(["sudo", "-n", "shutdown", "-h", "now"])
    _log("shutdown -h now fired")

    if dev is None:
        raise RuntimeError(M("shutdown_all_no_meter_configured_consumption_meter_page"))
    if not cut_ok:
        raise RuntimeError(
            M("shutdown_all_power_cut_could_not_confirmed_after", CUT_ATTEMPTS=CUT_ATTEMPTS, CUT_LOG=CUT_LOG)
        )

    return M("shutdown_all_filesystem_synced_power_cut_tuya_meter")
