"""
Status strip, the loop: one tick = one decision from the shared model (Painter), the RS485 reader and the event-driven loop that rests with its plugin (service_modules).
"""
import os
import time
import types
import heartbeats
import lights_config as lc
import lights_profile
import lights_view
import lights_runtime as lr
import lights_output
import pi_leds
import viewers
from messages import M
from lights_board import LEDS_BOARD_IDS, led_board, next_change_board, state_board, strip_state, thresholds_board
from lights_decide import LED_COUNT_DEFAULT, MAX_BETWEEN_PAINTED_SLOW_S, MIN_BETWEEN_PAINTED_JOB_S, TEXT_OF, color_for, effects_frozen, hex_color, is_live, layout, modes_ui, motors_released, pi_hot, pi_paints, read_input, rs_values, sanitize, secs_ui, strips_extra_segments, unclean_shutdown, zone_state
from lights_frame import arm_frame, detail_ui, test_active
from lights_output import CountedBridge, POWER, WithoutM150, configure_outputs, e_declared, effect_end_job, log_file, paint_segment_list, paint_segments, power_off_state, publish_strip_state


POLL_INTERVAL_S = 0.4


# lights_probe paints the strip by hand for a few seconds to count LEDs: while
# time.time() < PAUSE_UNTIL this loop does not paint, and when it ends it repaints everything.
PAUSE_UNTIL = 0.0


def pause_until(moment):
    """The loop does not paint until this time (time.time()); 0.0 gives the strip back to it at once."""
    global PAUSE_UNTIL
    PAUSE_UNTIL = moment


def pause_for(seconds):
    """The loop does not paint for the next `seconds` (a test paints the strip by hand)."""
    pause_until(time.time() + seconds)


# What the loop asks of other features (the jog, the protection guard). status_light.py, the composition point, fills these in;
# the defaults mean "nothing to report", so this module imports no other feature.
PROBES = {
    "jog_free_active": lambda: False,
    "jog_free_color": lambda: None,
    "jog_alert_limits": lambda: False,
    "guard_degraded": lambda: False,
}


# The "laser firing" state
LASER_HOLD_S = 4.0   # the "laser firing" state stays this long after the last PWM > 0


class ReaderRs485:
    """Reads the RS485 plugin data (faults / warnings) rarely and in its own
    thread, never in the paint loop. plugins.* is not in the shared
    subscription (it would echo our own plugin data back as patches), so this
    is a spot read: every RS485_CADA_S if the plugin is installed, every
    RS485_SIN_PLUGIN_S if it is not."""
    RS485_EACH_S = 5
    RS485_WITHOUT_PLUGIN_S = 60

    def __init__(self, read_in=None):
        self.faults = 0
        self.notices = 0
        self._read = read_in

    def _read_one_shot(self):
        """The spot read of plugins.*: status_light.py supplies it (it talks to machine_state)."""
        raise NotImplementedError("status_light.ReaderRs485 reads the plugins")

    def run_once(self):
        """One spot read. Returns the seconds to wait before the next one."""
        try:
            v = rs_values((self._read or self._read_one_shot)())
            if v is None:
                self.faults = self.notices = 0
                return self.RS485_WITHOUT_PLUGIN_S
            self.faults, self.notices = v
            return self.RS485_EACH_S
        except Exception as e:
            self.faults = self.notices = 0
            log_file(f"RS485 read failed: {e}")
            return 30


def run_reader_rs485(reader):
    while True:
        time.sleep(max(1, reader.run_once()))


# ---------------------------------------------------------------------------
# The painter: one tick = one decision from the model (no IPC while idle)
# ---------------------------------------------------------------------------
class Painter:
    """Everything the old polling loop did, as a function of the model: tick(om)
    reads nothing, asks nothing, and only sends to the board / publishes when
    the frame or the payload really changed. run_loop() calls it when the
    shared model changes and on a timer only while an animation needs frames."""

    def __init__(self, bridge_real, config, rs=None, announce=None):
        self.config = config
        self.bridge_real = CountedBridge(bridge_real)
        self.rs = rs
        self.announce = announce if announce is not None else self._announce_real
        self.conn = None
        self.last_key = None
        self.last_key_strip = None
        self.keys_extra = {}
        self.announced = False
        self.reconnected = False
        self.prev_status = None
        self.prev_in_live = False
        self.animating_since = None
        self.auto_published = None
        self.te_pub = None
        self.te_last = 0.0
        self.history = lr.StateHistory(50)
        self.light_auto = lr.WorkLightAuto()
        self.still_since = None
        self.pub = {"indicator": None, "info": None}
        self.last_painted = None  # monotonic time of the last paint of the strip
        self.paint_s = 0.0      # how long the last paint took (the Duet answering slowly = paint less)

    def _announce_real(self):
        """One-off, counted: tells daemon.g that the Pi paints (strip only). status_light.py supplies it (it sends the macro)."""
        raise NotImplementedError("status_light.Painter announces to daemon.g")

    def forget(self):
        """The subscription (re)connected: paint everything again."""
        self.last_key = None
        self.keys_extra.clear()
        self.announced = False
        self.pub["indicator"] = self.pub["info"] = self.pub["light"] = self.pub["view_src"] = None

    def _light_of_job(self, turn_on):
        """The work light switches on / off by itself with a job: same as lights_macros.work_light. status_light.py supplies it (it starts the thread)."""
        raise NotImplementedError("status_light.Painter switches the work light")

    def power_off(self, om):
        """The module was stopped: switch the status zone off once."""
        cfg = self.config
        illum = read_input(om)[2]
        real = self.bridge_real
        pi_leds.power_off_all()
        self.pub["view_src"] = None  # power_off_state empties lightsView: publish it again when the module runs again
        power_off_state(WithoutM150(real) if not lc.has_strip(cfg.get("status_light") or {}) else real, illum, cfg)

    def tick(self, om, mono=None, wall=None, minutes=None):
        """One decision from the model `om`. Returns the seconds to wait for
        the next tick if nothing changes (short while an animation runs).
        `c` carries what the steps below read and decide, in this order."""
        c = self._start(om, mono, wall, minutes)
        if self._holds_off(c):
            return POLL_INTERVAL_S
        self._announce_once(c)
        self._publish_auto(c)
        self._end_of_job(c)
        self._read_extras(c)
        self._arm(c)
        self._legend(c)
        self._keys(c)
        self._paint_strip(c)
        self._paint_extra_strips(c)
        # --- on-screen indicator (statusIndicator) and extra info (lightsInfo) ---
        try:
            light_on = self._publish_indicator(c)
            self._publish_info(c, light_on)
        except Exception as e:
            log_file(f"on-screen indicator: {e}")
        heartbeats.ok("status_light")
        return self._wait(c)

    def _start(self, om, mono, wall, minutes):
        """The clocks, the configuration, which bridge to use and what the model says."""
        mono = time.monotonic() if mono is None else mono
        wall = time.time() if wall is None else wall
        if minutes is None:
            lt = time.localtime(wall)
            minutes = lt.tm_hour * 60 + lt.tm_min
        config = self.config
        if isinstance(config.get("status_light"), dict):
            sanitize(config["status_light"])
        slc_p = config.get("status_light", {}) or {}
        present = lc.has_strip(slc_p)
        bridge = self.bridge_real if present else WithoutM150(self.bridge_real)

        # board LEDs / board status strip need the model (already in memory)
        lp_c = slc_p.get("leds_board") or {}
        te_c = slc_p.get("strip_state") or {}
        om_p = om if (lp_c.get("active") or te_c.get("active")) else None
        ep_p = state_board(om_p) if om_p is not None else None
        try:
            self._tick_strip_state(bridge, slc_p, om_p, ep_p)
        except Exception as e:
            log_file(f"board status strip: {e}")
        if not present:
            heartbeats.detail("status_light", M("status_light_no_led_strip_status_on_screens"))

        mode, disabled, illum, status, file_pos, file_size, laser_pwm, homed, animating = read_input(om)
        return types.SimpleNamespace(
            mono=mono, wall=wall, minutes=minutes, config=config, slc=slc_p, present=present, bridge=bridge, lp_c=lp_c, ep=ep_p,
            mode=mode, disabled=disabled, illum=illum, status=status, file_pos=file_pos, file_size=file_size,
            laser_pwm=laser_pwm, homed=homed, animating=animating)

    def _holds_off(self, c):
        """Start-up animation / page preview in progress, or the page paused the loop: do not paint; after it
        everything is painted again. A stuck flag is ignored after 30 s."""
        animating = c.animating
        if animating:
            if self.animating_since is None:
                self.animating_since = c.mono
            elif c.mono - self.animating_since > 30:
                animating = False
        else:
            self.animating_since = None
        if (animating or c.wall < PAUSE_UNTIL) and c.present:
            self.last_key = None
            self.keys_extra.clear()
            heartbeats.ok("status_light")
            return True
        return False

    def _announce_once(self, c):
        if not self.announced:
            if c.present:
                try:
                    self.announce()
                except Exception as e:
                    # a machine without the workshop's macros: the strip is still painted
                    log_file(f"enable_pi_status.g not available ({e}): carrying on without telling daemon.g")
            c.bridge.set_status("statusLightPiActive", True)
            self.announced = True
            self.last_key = None
            self.keys_extra.clear()

    def _publish_auto(self, c):
        if not c.present:
            c.disabled = False
        # statusLightAuto comes from the REAL state (global.statusLedDisabled)
        if self.auto_published is not (not c.disabled):
            self.auto_published = not c.disabled
            try:
                c.bridge.set_status("statusLightAuto", self.auto_published)
            except Exception:
                pass

    def _end_of_job(self, c):
        """The end-of-job flashes, when a file job or a live job just finished."""
        datos0 = getattr(c.bridge, "payload", {}) or {}
        c.in_live_now = is_live(datos0.get("liveJob"))
        ended_file = self.prev_status in ("processing", "simulating") and c.status == "idle"
        # live job: the machine stays "busy", not "processing", so the end is
        # detected when liveJob turns off
        ended_in_live = self.prev_in_live and not c.in_live_now and c.status != "halted"
        if (ended_file or ended_in_live) and not c.disabled:
            try:
                effect_end_job(c.bridge, c.config, c.illum)
                self.keys_extra.clear()
            except Exception as e:
                log_file(f"end-of-job effect: {e}")
            self.last_key = None
        self.prev_status = c.status
        self.prev_in_live = c.in_live_now

    def _read_extras(self, c):
        """What the states need besides the object model (all of it already published by other parts of the service)."""
        payload = getattr(c.bridge, "payload", {}) or {}
        new = lc.normalize_new(c.slc)
        if c.in_live_now and c.status == "idle":
            if self.still_since is None:
                self.still_since = c.mono
        else:
            self.still_since = None
        in_live_still = self.still_since is not None and c.mono - self.still_since >= new["live_quiet_s"]
        rs_f, rs_a = (self.rs.faults, self.rs.notices) if self.rs is not None else (0, 0)
        # The laser PWM goes to 0 between cuts and in every rapid move: the state "laser firing" would switch on and off
        # every second and, in "dividir", every change would re-split the whole strip (reported 2026-10-16 with a live
        # job). It is held for LASER_SOSTENER_S after the last shot, so the strip only changes when the laser really stops.
        laser_pwm = c.laser_pwm
        if laser_pwm:
            self.laser_seen = c.mono
        elif getattr(self, "laser_seen", None) is not None and c.mono - self.laser_seen < LASER_HOLD_S:
            laser_pwm = 1
        c.payload = payload
        c.new = new
        c.extras = {"laser_pwm": laser_pwm, "homed": c.homed, "air": payload.get("airAssist"),
                    "in_live": c.in_live_now, "rs485_faults": rs_f,
                    "jog_free": PROBES["jog_free_active"](), "crash": PROBES["jog_alert_limits"](),
                    # free jog has its own state and colour: it does not count as "risk"
                    # a safety process down (protection_guard.py) must never leave the strip on "ready"
                    "risk": any((r or {}).get("id") != "jog_free" for r in (payload.get("riskActive") or [])) or PROBES["guard_degraded"](),
                    "jog_free_color": PROBES["jog_free_color"](),
                    "rs485_notices": rs_a,
                    "pi_hot": pi_hot(payload, new["pi_hot_c"]),
                    "motors_loose": motors_released(payload),
                    "in_live_still": in_live_still,
                    "shutdown_dirty": unclean_shutdown(payload)}

    def _arm(self, c):
        """The frames for the strip and for the pages, and what the pages copy of them."""
        c.trial = test_active(c.wall)
        frame = arm_frame(c.config, c.mode, c.disabled, c.illum, c.status, c.file_pos, c.file_size, c.extras, c.ep, current_time=c.mono, trial=c.trial)
        c.frame = frame
        c.secs, c.text, c.ui_color, c.info = frame["secs"], frame["text"], frame["ui_color"], frame["info"]
        c.secs_board = frame["secs_board"]
        # What the pages mirror is the frozen frame (every effect lit): the strip repaints with the phase of a
        # blink, the pages animate it themselves (statusIndicator) and must not get a new value per phase
        frame_ui = arm_frame(c.config, c.mode, c.disabled, c.illum, c.status, c.file_pos, c.file_size, c.extras, c.ep,
                             current_time=lr.UI_FRAME_T, trial=c.trial)
        c.secs_mirror = frame_ui["secs"]
        c.ui_color = frame_ui["ui_color"]
        c.modes = modes_ui(frame["cfg_s"], c.mode, c.disabled, c.illum, c.status, c.file_pos, c.file_size, c.extras,
                           output="strip" if c.present else "screen", current_time=lr.UI_FRAME_T)
        if c.secs_board:
            c.modes = {m: v + secs_ui(frame_ui["secs_board"]) for m, v in c.modes.items()}
        mc = c.slc.get("mode_colors", {}) or {}
        c.mode_colors = {m: hex_color(x.get("r", 0), x.get("u", 0), x.get("b", 0), x.get("w", 0)) for m, x in mc.items() if isinstance(x, dict)}

    def _legend(self, c):
        """The list of active states the pages show, with the mode last."""
        info = c.info
        c.active_ui = detail_ui(info.get("detail")) if info.get("detail") else [
            {"id": i, "name": TEXT_OF.get(i, i), "hex": hex_color(col.get("r", 0), col.get("u", 0), col.get("b", 0), col.get("w", 0))} for i, col in info.get("activeList", [])]
        c.jog_above = c.disabled and bool(info.get("activeList")) and info["activeList"][0][0] in ("crash", "risk", "jog_free")
        mcol = color_for(c.slc, c.mode)
        c.mode_hex = hex_color(mcol.get("r", 0), mcol.get("u", 0), mcol.get("b", 0), mcol.get("w", 0))
        if c.disabled and not c.jog_above:
            # automatic status lights off: the work light takes these LEDs
            on = any(c.illum[:4])
            c.active_ui = [{"id": "lighting", "name": M("status_light_lighting_automatic_off" if on else "status_light_lighting_off_automatic_off"),
                            "hex": hex_color(*c.illum[:4]) if on else "#333333"}]
        elif not (c.active_ui and c.active_ui[0]["id"] in ("stop", "crash", "risk", "jog_free")):
            # emergency / crash / free jog take the WHOLE zone: the mode is not
            # shown in the legend (2026-10-10)
            c.active_ui.append({"id": "base", "name": M("status_light_mode_progress_bar" if c.status in ("processing", "simulating") else "status_light_mode", mode=c.mode),
                                "hex": c.mode_hex})

    def _keys(self, c):
        """Where the strip is, night dimming and the two keys: what the STRIP shows, and what the pages show on top of it."""
        slc0 = c.slc
        configure_outputs(slc0)
        self.pi_fast = pi_paints(slc0)
        c.led_count = slc0.get("led_count", LED_COUNT_DEFAULT)
        # night dimming: only the physical strip
        c.factor = lr.night_factor(c.new["night"], c.minutes) if c.present else 1.0
        c.dim = (c.factor, c.new["night"]["include_work_light"]) if c.factor < 0.999 else None
        POWER["ma_channel"] = c.new["power"]["ma_per_channel"]
        c.where = ("main",) if c.disabled else zone_state(slc0)
        # the strip is repainted only when what the STRIP shows changes; the previews of the page (activos_ui,
        # modos, colours of the modes) change with their own effects and must not cost M150 (2026-10-13: ~180
        # M150 per minute with nothing changing on the strip)
        c.key_strip = f"{c.secs},{c.led_count},{slc0.get('led_start', 10)},{slc0.get('led_strip', 0)},{slc0.get('order')},{c.illum},{layout(slc0)},{c.where},{c.dim}"
        c.key = f"{c.key_strip},{c.active_ui},{c.modes},{c.mode_colors}"

    def _paint_strip(self, c):
        """Paint the main strip when its frame changed (paced during a job), and publish what the pages copy."""
        slc0, bridge, mono = c.slc, c.bridge, c.mono
        # job running: at most 2 paints per second, and fewer when the Duet takes long to answer
        # (the paints are queued behind the job's own traffic on the same link)
        in_job = c.status in ("processing", "simulating") or c.in_live_now
        gap = MIN_BETWEEN_PAINTED_JOB_S if in_job else 0.0
        if self.paint_s > 0.3:
            gap = max(gap, min(MAX_BETWEEN_PAINTED_SLOW_S, 4 * self.paint_s))
        if pi_paints(slc0):
            gap = 0.0  # a paint from the Pi costs no call to the board: no pacing
        defer = bool(c.key != self.last_key and self.last_painted is not None and gap > 0 and mono - self.last_painted < gap and not c.trial)
        c.gap, c.defer = gap, defer
        if c.key == self.last_key or defer:
            return
        repaint = self.last_key is None or c.key_strip != self.last_key_strip
        if repaint and os.path.exists("/tmp/workshop-debug-lights"):
            log_file("DEBUG repaint: %s || before: %s" % (c.key_strip[:400], str(self.last_key_strip)[:400]))
        self.last_key = c.key
        self.last_key_strip = c.key_strip
        t_paint = time.monotonic()
        try:
            if not repaint:
                pass  # only a preview of the page changed: publish below, no M150
            elif not c.present:
                # no strip: only what the screens copy (statusLightSecs, ledStrip)
                paint_segment_list(bridge, c.illum, c.secs, slc0.get("led_start", 10), slc0.get("led_strip", 0), slc0.get("order"), layout(slc0), secs_mirror=c.secs_mirror)
            elif c.disabled:
                paint_segment_list(bridge, c.illum, c.secs, slc0.get("led_start", 10), slc0.get("led_strip", 0), slc0.get("order"), layout(slc0), dim=c.dim, secs_mirror=c.secs_mirror)
            else:
                lights_output.paint_state(bridge, c.illum, c.secs, slc0, with_extra=False, dim=c.dim, secs_mirror=c.secs_mirror)
        except Exception as e:
            log_file(f"error painting: {e}")
        self.paint_s = time.monotonic() - t_paint
        self.last_painted = mono
        col = next((h for h, level, _ in secs_ui(c.secs_mirror) if level > 0), "#000000")
        bridge.set_status("statusLightColor", c.ui_color or col)
        self._publish_detail(c)
        bridge.set_status("statusLightText", c.text)
        bridge.set_status("statusLightActive", c.active_ui)
        bridge.set_status("statusLightModes", c.modes)
        bridge.set_status("statusLightModeColors", c.mode_colors)

    def _publish_detail(self, c):
        """The line of the process list: where the status is painted."""
        slc0, where, text = c.slc, c.where, c.text
        ini0 = slc0.get('led_start', 10)
        if not c.present:
            heartbeats.detail("status_light", M("status_light_no_led_strip_screens_only", text=text))
        elif where[0] == "main":
            heartbeats.detail("status_light", M("status_light_leds_of_strip", first=ini0, last=ini0 + c.led_count - 1, n=c.led_count, strip=slc0.get('led_strip', 0), text=text))
        elif where[0] == "led_strip":
            heartbeats.detail("status_light", M("status_light_status_in_zone_of_strip", strip=where[1], n=where[4], text=text))
        else:
            heartbeats.detail("status_light", M("status_light_no_status_zone_screens_only", text=text))

    def _paint_extra_strips(self, c):
        """Additional strips (Lights page): fixed colours per zone, painted only when they change and only if their E is declared in config.g."""
        for e_, segments_ in (strips_extra_segments(c.slc, None if c.disabled else c.secs) if c.present else []):
            k_ = repr(segments_)
            if self.keys_extra.get(e_) != k_:
                self.keys_extra[e_] = k_
                if e_declared(e_):
                    try:
                        paint_segments(c.bridge, e_, segments_)
                    except Exception as ex:
                        log_file(f"error painting strip E{e_}: {ex}")
                else:
                    log_file(f"strip E{e_} has no M950 in config.g: not painted")

    def _publish_indicator(self, c):
        """The on-screen indicator (statusIndicator), the history and lightOn. Returns whether the light is on."""
        bridge, status, illum = c.bridge, c.status, c.illum
        screen = c.frame["screen"]
        det_p = detail_ui(screen["detail"])
        if c.disabled and not c.jog_above:
            det_p = [d for d in c.active_ui if d["id"] == "lighting"]
        prog = None
        if status in ("processing", "simulating") and c.file_size:
            prog = int(((c.file_pos or 0) / c.file_size) * 20) / 20.0
        comb_p = c.slc.get("combine") or {}
        mode_c = comb_p.get("mode", "priority")
        if mode_c == "split" and (c.info.get("capacidad") or {}).get("rotating"):
            mode_c = "turns"  # more states than LEDs: they take turns
        ind = lr.build_indicator(det_p, c.mode, c.mode_hex, status, screen["text"], prog,
                                 test=(c.trial["id"] if c.trial else None),
                                 extra={"combine": mode_c, "turn_s": max(0.5, float(comb_p.get("turn_s", 1.5)))})
        k_ind = repr(ind)
        if k_ind != self.pub["indicator"]:
            self.pub["indicator"] = k_ind
            bridge.set_status("statusIndicator", ind)
        if not c.trial:
            self.history.observe(int(c.wall), [d["id"] for d in det_p if d["id"] != "lighting"], c.mode, status)
        light_on = any(illum[:4]) and illum[4] > 0
        # lightOn (the Light on / Light off buttons) follows the real zone colour, so a light switched
        # on or off by any other path (Lights page, macro, daemon) never leaves the buttons stale
        if self.pub.get("light") != bool(light_on):
            self.pub["light"] = bool(light_on)
            bridge.set_status("lightOn", bool(light_on))
        return light_on

    def _publish_info(self, c, light_on):
        """The work light by itself (it switches on / off with a job) and lightsInfo for the Lights page."""
        wall, lp_c, new, present = c.wall, c.lp_c, c.new, c.present
        working = c.status not in ("idle", "off") or c.in_live_now
        action = self.light_auto.update(wall, light_on, working, new["work_light"]) if present and not c.disabled else None
        if action == "off":
            log_file("work light: switched off by itself after the quiet time")
            self._light_of_job(False)
        elif action == "on":
            log_file("work light: switched on by itself, a job started")
            self._light_of_job(True)
        board_ui = None
        if lp_c.get("active") and c.ep is not None:
            board_ui = lr.board_leds_ui(lp_c.get("leds") or LEDS_BOARD_IDS, c.ep, led_board, thresholds_board(lp_c))
        subtracts = self.light_auto.seconds_left(wall, light_on, working, new["work_light"]) if present else None
        info_pub = {
            "strip": present,
            "history": self.history.as_list(),
            "power": {"ma": int(round(POWER["ma"] / 10.0)) * 10 if present else 0, "limit": new["power"]["limit_ma"],
                      "over": bool(present and new["power"]["limit_ma"] and POWER["ma"] > new["power"]["limit_ma"])},
            "night": {"on": c.factor < 0.999, "level": int(round(c.factor * 100))},
            "auto_off_min": None if subtracts is None else int((subtracts + 59) // 60),
            "board": board_ui,
            # how many LEDs the status zone has, how many states fit at once and what did not fit
            "capacity": dict(c.info.get("capacidad") or {}, board_leds=len(c.frame["secs_board"]),
                             board_wanted=len((lp_c.get("leds") if lp_c.get("leds") is not None else LEDS_BOARD_IDS)) if lp_c.get("active") else 0),
        }
        k_inf = repr(info_pub)
        if k_inf != self.pub["info"]:
            self.pub["info"] = k_inf
            c.bridge.set_status("lightsInfo", info_pub)
        self._publish_view(c)

    def _publish_view(self, c):
        """lightsView: the public read-only view of the configuration (lights_view.py, note 8), built again only when the saved settings change."""
        k_src = repr(c.slc)
        if c.trial or k_src == self.pub.get("view_src"):  # a simulation of unsaved settings is not the saved view
            return
        self.pub["view_src"] = k_src
        c.bridge.set_status("lightsView", lights_view.view(lights_profile.clean({"status_light": c.slc})))

    def _wait(self, c):
        """Seconds to the next tick. Animations are the only reason to wake up on a timer (no IPC):
        the board STATUS LED blinking (0.7 s slow; fast = MEDIO_MIN_TIRA_S),
        blinking / pulsing states, turns between several states."""
        slc0, info, trial, mono = c.slc, c.info, c.trial, c.mono
        waiting = IDLE_WAIT_S
        frozen = effects_frozen(slc0, c.status, c.extras)
        prox = next_change_board(slc0, c.ep) if c.lp_c.get("active") and not frozen else None
        if prox is not None:
            waiting = min(waiting, max(0.05, prox + 0.01))
        effects = [d.get("effect") for d in (info.get("detail") or [])]
        if trial or any(e != "steady" for e in effects):
            if pi_paints(slc0) and not trial:
                waiting = min(waiting, lr.next_change([e for e in effects if e], mono) + 0.005)
            else:
                waiting = min(waiting, 0.2 if lr.needs_fast_tick(effects) or trial else POLL_INTERVAL_S)
        if (slc0.get("combine") or {}).get("mode") in ("turns",) and len(info.get("activeList") or []) > 1 and not frozen:
            waiting = min(waiting, POLL_INTERVAL_S)
        if (slc0.get("combine") or {}).get("mode") == "split" and effects and any(e != "steady" for e in effects):
            waiting = min(waiting, 0.2)
        if c.defer:  # a change is waiting for its turn: come back when the gap is over
            waiting = min(waiting, max(0.1, c.gap - (mono - self.last_painted) + 0.02))
        return waiting

    def _tick_strip_state(self, bridge, slc, om, ep):
        te = slc.get("strip_state") or {}
        # only the Lights page (Advanced tab) reads this copy: nobody there, nothing is worked out or published
        if not te.get("active") or not viewers.active("lights_board"):
            if self.te_pub is not None:
                self.te_pub = None
                publish_strip_state(bridge, None)
            return
        val = {"secs": strip_state(om, te.get("groups"), ep), "ok": om is not None}
        k = repr(val)
        # The virtual strip copies live outputs (the laser LED follows every on/off of the beam): during a cut
        # that is a change several times per second, and each one is a call to the board's server. A copy that
        # is two seconds old is as good for the screens, so a changed copy waits for the next tick after that.
        mono = time.monotonic()
        if k != self.te_pub and (self.te_pub is None or mono - self.te_last >= STRIP_STATE_MIN_S):
            self.te_pub = k
            self.te_last = mono
            publish_strip_state(bridge, val)


# the idle wait: nothing animates, so the loop only wakes on a model change
# (state.upTime changes every second) or after this
IDLE_WAIT_S = 1.0


STRIP_STATE_MIN_S = 2.0  # at most one copy of the board's virtual strip every 2 s


MIN_BETWEEN_TURNS_S = 0.2


class LightsLoop:
    """The event driven loop, one step at a time: a step reads the model, rests with the plugin, throttles and ticks the painter.
    The model reader, the plugin gate and the sleep are injected so a step can be tried with a fake model and clock."""

    def __init__(self, painter, event, get_status, is_active, sleep=None, clock=None):
        self.painter = painter
        self.event = event
        self.get_status = get_status
        self.is_active = is_active
        self.sleep = sleep or (lambda s: time.sleep(s))
        self.clock = clock or (lambda: time.monotonic())
        self.in_idle = False
        self.last = 0.0

    def step(self):
        painter, event = self.painter, self.event
        # The event is cleared BEFORE the model is read: a patch that arrives after the read (while this step throttles
        # or paints) sets it again and is painted in the next cycle. Cleared after the read it was wiped and the right
        # state waited for the next patch (backlog item 17).
        event.clear()
        try:
            om = self.get_status(timeout=3)
        except Exception as e:
            heartbeats.detail("status_light", M("status_light_waiting_machine_state_dsf_subscription"))
            log_file(f"no model yet ({e})")
            self.sleep(2)
            return
        # "Lights and status" (WorkshopLights) stopped or disabled: this module
        # does not run (service_modules.py). The status zone is switched off once and
        # the loop waits; when it is enabled again everything is painted.
        if not self.is_active():
            if not self.in_idle:
                try:
                    painter.power_off(om)
                    self.in_idle = True
                    painter.forget()
                    log_file("Lights and status stopped: status zone off, the service does not paint")
                except Exception as e:
                    log_file(f"rest: could not switch the status zone off ({e}), retrying")
                    self.sleep(5)
                    return
            heartbeats.detail("status_light", M("status_light_at_rest_lights_states_plugin_stopped"))
            heartbeats.ok("status_light")
            self.sleep(3)
            return
        if self.in_idle:
            self.in_idle = False
            painter.forget()
            log_file("Lights and status active again: the service paints again")
        if painter.reconnected:
            painter.reconnected = False
            painter.forget()
        # at most ~5 decisions per second, however many patches arrive (25 when the Pi paints: no call to the board)
        missing = (0.04 if getattr(painter, "pi_fast", False) else MIN_BETWEEN_TURNS_S) - (self.clock() - self.last)
        if missing > 0:
            self.sleep(missing)
        try:
            waiting = painter.tick(om)
        except Exception as e:
            log_file(f"tick failed: {type(e).__name__}: {e}")
            heartbeats.error("status_light", e)
            waiting = 2.0
        self.last = self.clock()
        event.wait(waiting)
