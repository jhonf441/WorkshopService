"""
Status strip, the Duet board's own LEDs and the virtual status strip of the object model (pure): what each board LED says, which ones are lit, and the list of LEDs the Lights page shows.
"""
import time
import lights_runtime as lr
from messages import M, J
from lights_decide import LED_COUNT_DEFAULT, hex_color


# ---------------------------------------------------------------------------
# Board LEDs (2026-10-11, Lights page > "Board LEDs at the end")
# ---------------------------------------------------------------------------
# Copy of the LEDs the Duet 3 6HC has soldered on the board, with the same colour and the same
# behaviour. Colours: bill of materials of Duet3D's schematics
# (github.com/Duet3D/Duet3-Mainboard-6HC v1.02, Power.kicad_sch and Processor.kicad_sch): V_FUSED
# blue (150060BS75000), 12V+ amber (150060AS75000), 5V+ red (150060RS75000), 3.3V green
# (150060VS75000), STATUS red, ACT green. The EXP3HC / EXP1XD / TOOL1LC expansions use the same
# colours (VIN blue, 12V amber, 5V red, 3.3V green, STATUS red, ACT green). The 6HC does NOT have a
# 4 V LED: the "4V" asked for is the VIN input (V_FUSED, after the fuse).
#
# STATUS (the CAN communication LED), from RRF's code (src/CAN/CanInterface.cpp UpdateStatusLed and
# Duet3Expansion Platform.cpp):
# - main board: it blinks with the step clock, bit 19 of 750 kHz = 0.70 s on / 0.70 s off (~0.7 Hz);
# - expansion synchronised by CAN: the SAME blink, at the same time as the main one;
# - expansion not synchronised (no CAN messages): bit 17 = 0.175 s / 0.175 s (4 times faster);
# - firmware not running: off (or steady).
# Here: slow if all the CAN boards are "running", fast if some CAN board is not "running" or stopped
# appearing in boards[] (it disappears when it stops sending messages), off if there is no data from
# the board (the Pi does not read it). The phase is NOT the board's (its clock cannot be read): the
# Pi's clock is used with the same period.
STATUS_MIDDLE_SYNC_S = (1 << 19) / 750000.0   # 0,699 s


STATUS_MIDDLE_WITHOUT_SYNC_S = (1 << 17) / 750000.0  # 0,175 s


# On the strip (physical or virtual) the loop does not repaint faster than ~0.2 s: the fast blink is
# painted with 0.2 s instead of 0.175 s (2.5 Hz instead of 2.9 Hz). The board's status strip
# (screens) uses the real value.
MIDDLE_MIN_STRIP_S = 0.2


VIN_MIN_V = 4.5   # less than this: without VIN (the board lives on USB / external 5 V)


V12_MIN_V = 6.0


COLOR_NETWORK = {"r": 255, "u": 0, "b": 0, "w": 0}


COLOR_GREEN = {"r": 0, "u": 255, "b": 0, "w": 0}


COLOR_BLUE = {"r": 0, "u": 0, "b": 255, "w": 0}


COLOR_AMBER = {"r": 255, "u": 150, "b": 0, "w": 0}


LEDS_BOARD_DEF = [
    # id, name (as the board says), colour
    ("can", M("status_light_status_can_communication"), COLOR_NETWORK),
    ("vin", "VIN (V_FUSED)", COLOR_BLUE),
    ("v12", "12 V", COLOR_AMBER),
    ("v5", "5 V", COLOR_NETWORK),
    ("v3_3", "3,3 V", COLOR_GREEN),
]


LEDS_BOARD_IDS = [x[0] for x in LEDS_BOARD_DEF]


BOARDS_VIEWS = set()  # CAN addresses seen since the service started


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def state_board(om):
    """What the board's LEDs say, from the complete object model (/machine/status). Returns {ok, vin, v12, can, boards, missing}: can = "sync" (slow) | "no_sync" (fast) | "off"; boards = the expansion ones [{addr, name, state, vin, v12, can}]. 5 V and 3.3 V have no measurement in the object model: if the board answers, they are present."""
    boards = (om or {}).get("boards") or []
    if not boards or not isinstance(boards[0], dict):
        return {"ok": False, "vin": None, "v12": None, "can": "shutdown", "boards": [], "missing": []}
    b0 = boards[0]
    board_list = []
    for b in boards[1:]:
        if not isinstance(b, dict) or b.get("canAddress") in (None, 0):
            continue
        addr = int(b.get("canAddress"))
        BOARDS_VIEWS.add(addr)
        st = b.get("state")
        board_list.append({
            "addr": addr, "name": b.get("shortName") or b.get("name") or "",
            "state": st,
            "vin": num((b.get("vIn") or {}).get("current")),
            "v12": num((b.get("v12") or {}).get("current")),
            # without "state" (old firmware) it is taken as synchronised
            "can": "sync" if st in (None, "running") else "without_sync",
        })
    present = {p["addr"] for p in board_list}
    missing = sorted(BOARDS_VIEWS - present)
    can = "sync" if all(p["can"] == "sync" for p in board_list) and not missing else "without_sync"
    return {
        "ok": True,
        "vin": num((b0.get("vIn") or {}).get("current")),
        "v12": num((b0.get("v12") or {}).get("current")),
        "can": can, "boards": board_list, "missing": missing,
    }


def thresholds_board(lp):
    """Thresholds of the VIN and 12 V board LEDs (Lights page > Outputs >
    Board LEDs): below vin_min / v12_min the LED goes off, like the real one.
    Unset, the usual values apply (VIN_MIN_V, V12_MIN_V)."""
    lp = lp if isinstance(lp, dict) else {}
    out = {}
    for k, d in (("vin_min", VIN_MIN_V), ("v12_min", V12_MIN_V)):
        try:
            out[k] = float(lp.get(k, d))
        except (TypeError, ValueError):
            out[k] = d
    out["can_always"] = lp.get("can_blink") == "always"
    return out


def led_board(ident, ep, thresholds=None):
    """(colour, half blink period in s or 0 = steady, lit?, text) of a main board LED according to board_state()."""
    um = thresholds or {}
    vin_min = um.get("vin_min", VIN_MIN_V)
    v12_min = um.get("v12_min", V12_MIN_V)
    col = next(c for i, _, c in LEDS_BOARD_DEF if i == ident)
    if not ep.get("ok"):
        return col, 0, False, M("status_light_no_board_data")
    if ident == "can":
        if ep["can"] == "sync":
            # 2026-10-13: the slow blink of the board STATUS LED costs ~2 M150 per half period (measured 182
            # commands per minute): by default it stays lit while the CAN is fine and blinks only on a problem
            if not um.get("can_always"):
                return col, 0, True, M("status_light_steady_can_communication_fine") if ep["boards"] else M("status_light_steady_firmware_running")
            return col, STATUS_MIDDLE_SYNC_S, True, M("status_light_slow_blink_can_communication_fine") if ep["boards"] else M("status_light_slow_blink_firmware_running")
        bad = [str(p["addr"]) for p in ep["boards"] if p["can"] != "sync"] + [str(a) for a in ep["missing"]]
        return col, STATUS_MIDDLE_WITHOUT_SYNC_S, True, M("status_light_fast_blink_no_can_communication_board", boards=", ".join(bad))
    if ident == "vin":
        v = ep.get("vin")
        on = v is not None and v >= vin_min
        return col, 0, on, ("%.1f V" % v) if v is not None else M("status_light_no_measurement")
    if ident == "v12":
        v = ep.get("v12")
        on = v is not None and v >= v12_min
        return col, 0, on, ("%.1f V" % v) if v is not None else M("status_light_no_measurement")
    # 5 V and 3.3 V: no measurement in the object model; the board answers = present
    return col, 0, True, M("status_light_present_board_answers_no_measurement")


def is_on(middle, on, t):
    if not on:
        return False
    if not middle or t < 0:
        return True
    return int(t / middle) % 2 == 0


def leds_board_segments(lp, ep, t=None, take=None):
    """Stretches (r,g,b,w,p,1) of the board LEDs chosen in Lights, in the order of BOARD_LEDS_DEF. taken = (colour, effect): a state with its "Board" checkbox on is active and takes the positions of the board LEDs while it lasts (for instance the emergency stop filling the whole zone)."""
    t = time.time() if t is None else t
    chosen = set(lp.get("leds") or LEDS_BOARD_IDS)
    p = max(1, min(255, int(lp.get("brightness", 120) or 120)))
    um = thresholds_board(lp)
    out = []
    for ident in LEDS_BOARD_IDS:
        if ident not in chosen:
            continue
        if take:
            c, effect = take
            level, enc = lr.effect_level(effect, t)
            out.append((c["r"], c["u"], c["b"], c.get("w", 0), level, 1) if enc else (0, 0, 0, 0, 0, 1))
            continue
        col, middle, on, _ = led_board(ident, ep, um)
        if is_on(middle and max(middle, MIDDLE_MIN_STRIP_S), on, t):
            out.append((col["r"], col["u"], col["b"], col["w"], p, 1))
        else:
            out.append((0, 0, 0, 0, 0, 1))
    return out


def apply_leds_board(config, ep, t=None, take=None):
    """With status_light.leds_board.activo, the last LEDs of the status zone are the board's: the zone does NOT grow (the physical strip has the LEDs it has and growing would shift the lighting and the extra zones), they are subtracted from the end. At least 1 LED always remains for the state: with a very small zone fewer board LEDs fit (the first ones in the list). Returns (config with a reduced led_count, board stretches)."""
    slc = config.get("status_light") or {}
    lp = slc.get("leds_board") or {}
    if not lp.get("active") or ep is None:
        return config, []
    segments = leds_board_segments(lp, ep, t, take)
    n = int(slc.get("led_count", LED_COUNT_DEFAULT))
    segments = segments[:max(0, n - 1)]
    if not segments:
        return config, []
    c2 = dict(config)
    c2["status_light"] = dict(slc, led_count=n - len(segments))
    return c2, segments


def next_change_board(slc, ep, t=None):
    """Seconds until the next change of the STATUS LED's blink (so the loop repaints in time), or None if nothing blinks."""
    lp = slc.get("leds_board") or {}
    te = slc.get("strip_state") or {}
    uses = (lp.get("active") and "can" in (lp.get("leds") or LEDS_BOARD_IDS)) or te.get("active")
    if not uses or not ep or not ep.get("ok"):
        return None
    # the CAN LED stays lit while the communication is fine (unless the user wants the slow blink): nothing to repaint
    if ep.get("can") == "sync" and lp.get("can_blink") != "always" and not te.get("active"):
        return None
    t = time.time() if t is None else t
    middle = max(MIDDLE_MIN_STRIP_S, STATUS_MIDDLE_SYNC_S if ep["can"] == "sync" else STATUS_MIDDLE_WITHOUT_SYNC_S)
    return middle - (t % middle)


# ---------------------------------------------------------------------------
# Board status strip (2026-10-11): ONLY virtual, never M150
# ---------------------------------------------------------------------------
# A second strip the service builds by itself, one LED per thing of the object model, for the
# screens (ledStrip.stripState). Groups chosen in Lights.
GROUPS_STRIP_STATE = ("board", "final", "probes", "fans", "heaters", "laser", "outputs")


HEX_SHUTDOWN = "#000000"


def sec_entry(ident, group, label, hexc, level, blink=0.0, fault=False):
    """fault = a real problem (a heater in fault, a CAN board that stopped answering): the screens count it, not the colour (the board LEDs are red by design)."""
    return {"id": ident, "group": group, "label": label, "hex": hexc,
            "level": round(max(0.0, min(1.0, float(level))), 2), "blink": round(float(blink or 0), 3), "fault": bool(fault)}


def hex_of_color(c):
    return hex_color(c["r"], c["u"], c["b"], c.get("w", 0))


def strip_board(out, ep):
    """The main board LEDs, the expansion boards and the ones that stopped answering."""
    for ident, label, _ in LEDS_BOARD_DEF:
        col, middle, on, txt = led_board(ident, ep, {"can_always": True})  # the screens blink by CSS: no cost
        out.append(sec_entry("board_" + ident, "board", M("status_light_main_board_led", label=label, text=txt),
                        hex_of_color(col), 1 if on else 0, middle if on else 0, fault=ident == "can" and ep.get("ok") and ep.get("can") != "sync"))
    for p in ep.get("boards") or []:
        nom = M("status_light_can_board", addr=p["addr"])
        if p["name"]:
            nom = J([nom, p["name"]], sep=" ")
        sync = p["can"] == "sync"
        out.append(sec_entry("can_%d" % p["addr"], "board",
                        M("status_light_board_status_led", board=nom, text=M("status_light_slow_blink_can_communication_fine") if sync else M("status_light_fast_blink_not_synced_state", state=str(p["state"]))),
                        hex_of_color(COLOR_NETWORK), 1, STATUS_MIDDLE_SYNC_S if sync else STATUS_MIDDLE_WITHOUT_SYNC_S, fault=not sync))
        if p["vin"] is not None:
            out.append(sec_entry("vin_%d" % p["addr"], "board", M("status_light_board_vin", board=nom, v=p["vin"]),
                            hex_of_color(COLOR_BLUE), 1 if p["vin"] >= VIN_MIN_V else 0))
    for a in ep.get("missing") or []:
        out.append(sec_entry("can_%d" % a, "board", M("status_light_can_board_not_answering", addr=a),
                        hex_of_color(COLOR_NETWORK), 1, STATUS_MIDDLE_WITHOUT_SYNC_S, fault=True))


def strip_final(out, om):
    """One LED per endstop."""
    sensors = om.get("sensors") or {}
    axes = (om.get("move") or {}).get("axes") or []
    for i, e in enumerate(sensors.get("endstops") or []):
        if not isinstance(e, dict):
            continue
        letter = (axes[i] or {}).get("letter") if i < len(axes) and isinstance(axes[i], dict) else None
        act = bool(e.get("triggered"))
        out.append(sec_entry("final_%d" % i, "final",
                        M("status_light_endstop", axis=letter or i, state=M("status_light_triggered_m" if act else "status_light_not_triggered")),
                        "#ffb300" if act else "#4caf50", 1 if act else 0.25))


def strip_probes(out, om):
    """One LED per probe (and the BLTouch pin)."""
    sensors = om.get("sensors") or {}
    glob = om.get("global") or {}
    for i, p in enumerate(sensors.get("probes") or []):
        if not isinstance(p, dict) or p.get("type") in (None, 0):
            continue
        val = p.get("value") or [0]
        try:
            v0 = float(val[0] if isinstance(val, list) else val)
        except (TypeError, ValueError, IndexError):
            v0 = 0.0
        threshold = num(p.get("threshold")) or 500
        act = v0 >= threshold
        out.append(sec_entry("probe_%d" % i, "probes",
                        M("status_light_probe", i=i, state=M("status_light_triggered_f" if act else "status_light_not_triggered"), value=v0, threshold=threshold),
                        "#ffb300" if act else "#4caf50", 1 if act else 0.25))
        if p.get("type") == 9:
            # BLTouch: the object model does not say whether the pin is out. global.probePinOut
            # is used (marked by deployprobe.g / retractprobe.g on this machine) and if it does
            # not exist, deployedByUser (only M401).
            if "probePinOut" in glob:
                outside, source = bool(glob.get("probePinOut")), "global.probePinOut"
            else:
                outside, source = bool(p.get("deployedByUser")), "M401 (deployedByUser)"
            out.append(sec_entry("bltouch_%d" % i, "probes",
                            M("status_light_bltouch_pin_according", i=int(i), p=M("status_light_pin_down_out") if outside else M("status_light_pin_up_stowed"), source=source),
                            "#e040fb" if outside else "#7e57c2", 1 if outside else 0.25))


def strip_fans(out, om):
    """One LED per fan."""
    for i, f in enumerate(om.get("fans") or []):
        if not isinstance(f, dict):
            continue
        v = num(f.get("currentValue")) or 0.0
        nom = f.get("name") or M("status_light_fan", i=i)
        out.append(sec_entry("fan_%d" % i, "fans", M("status_light_fan_pct", name=nom, pct=round(v * 100)),
                        "#29b6f6", v if v > 0 else 0))


def strip_heaters(out, om):
    """One LED per heater."""
    for i, h in enumerate((om.get("heat") or {}).get("heaters") or []):
        if not isinstance(h, dict):
            continue
        st = h.get("state") or "off"
        cur = num(h.get("current"))
        obj = num(h.get("active")) if st == "active" else num(h.get("standby")) if st == "standby" else None
        temp = ("%.0f" % cur) if cur is not None else "?"
        raw_text = {"off": M("status_light_heater_off"), "standby": M("status_light_heater_standby"), "active": M("status_light_heater_active"),
                    "fault": M("status_light_heater_fault"), "tuning": M("status_light_heater_tuning_pid"),
                    "offline": M("status_light_no_connection")}.get(st, st)
        # 2026-10-13: a heater whose sensor is not connected reads about -273 C (RRF calls it a fault, or
        # "off" with -273). In Laser / CNC mode nobody uses it: it is not listed at all (a thing that is not
        # configured for the mode in use is not shown). In FFF mode the same reading is a real fault.
        mode_machine = (om.get("state") or {}).get("machineMode")
        if cur is not None and cur < -250 and st in ("fault", "off") and mode_machine in ("Laser", "CNC"):
            continue
        et = M("status_light_heater_target", i=i, state=raw_text, temp=temp, target=obj) if obj is not None else M("status_light_heater", i=i, state=raw_text, temp=temp)
        if st == "fault":
            out.append(sec_entry("heater_%d" % i, "heaters", et, "#ff0000", 1, 0.25, fault=True))
        elif st in ("active", "tuning"):
            out.append(sec_entry("heater_%d" % i, "heaters", et, "#ff5722", 1, 0.5 if st == "tuning" else 0))
        elif st == "standby":
            out.append(sec_entry("heater_%d" % i, "heaters", et, "#ffb300", 0.5))
        else:
            out.append(sec_entry("heater_%d" % i, "heaters", et, HEX_SHUTDOWN, 0))


def strip_laser(out, om):
    """The laser and the spindles."""
    cm = (om.get("move") or {}).get("currentMove") or {}
    kind = (om.get("state") or {}).get("machineMode")
    if kind == "Laser" or cm.get("laserPwm") is not None:
        pwm = num(cm.get("laserPwm")) or 0.0
        out.append(sec_entry("laser", "laser", M("status_light_laser", round=round(pwm * 100)) if pwm > 0 else M("status_light_laser_off"),
                        "#ffeb3b", pwm if pwm > 0 else 0))
    for i, s in enumerate(om.get("spindles") or []):
        if not isinstance(s, dict) or s.get("state") in (None, "unconfigured"):
            continue
        st = s.get("state")
        rpm = num(s.get("current")) or 0
        raw_text = {"stopped": M("status_light_spindle_stopped"), "forward": M("status_light_spindle_turning"), "reverse": M("status_light_turning_reverse")}.get(st, st)
        out.append(sec_entry("spindle_%d" % i, "laser", M("status_light_spindle", i=i, state=raw_text, rpm=int(rpm)),
                        "#00e676", 1 if st in ("forward", "reverse") else 0))


def strip_outputs(out, om):
    """The general purpose outputs."""
    for i, g in enumerate((om.get("state") or {}).get("gpOut") or []):
        if not isinstance(g, dict):
            continue
        v = num(g.get("pwm")) or 0.0
        out.append(sec_entry("gpout_%d" % i, "outputs", M("status_light_output", i=i, state=("%d %%" % round(v * 100)) if 0 < v < 1 else M("status_light_output_on" if v > 0 else "status_light_output_off")),
                        "#ffffff", v if v > 0 else 0))


def strip_state(om, groups=None, ep=None):
    """List of LEDs [{id, group, label, hex, level 0..1, blink (half period in s, 0 = steady)}] from the complete object model. What is not in the object model does not appear (see the Lights page report)."""
    om = om or {}
    groups = set(GROUPS_STRIP_STATE if groups is None else groups)
    ep = ep if ep is not None else state_board(om)
    out = []
    if "board" in groups:
        strip_board(out, ep)
    if "final" in groups:
        strip_final(out, om)
    if "probes" in groups:
        strip_probes(out, om)
    if "fans" in groups:
        strip_fans(out, om)
    if "heaters" in groups:
        strip_heaters(out, om)
    if "laser" in groups:
        strip_laser(out, om)
    if "outputs" in groups:
        strip_outputs(out, om)
    return out
