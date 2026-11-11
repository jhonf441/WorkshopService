"""
Status strip, the frame: everything the three outputs (strip, screen, board LEDs) show right now, put together from the decisions. Pure: no painting, no network. Also the "test this state" request of the Lights page.
"""
import time
import lights_config as lc
import lights_runtime as lr
import lights_decide
from messages import M
from lights_board import apply_leds_board
from lights_decide import LED_COUNT_DEFAULT, TEXT_OF, config_state, effects_frozen, hex_color


# Test of a state ("Test this state" button of the page): shows the state on
# the chosen outputs for a few seconds, then everything goes back by itself.
TEST = {"id": None, "until": 0.0, "outputs": (), "color": None, "effect": None}


TEST_SECONDS = 6


def probe_state(ident, seconds=TEST_SECONDS, outputs=None, current_time=None, color=None, effect=None):
    """Starts the test of a state. Returns the test dict, or None if the state
    does not exist. salidas: subset of strip/screen/board (all by default).
    color / effect: what the page has on screen (not saved yet); by default the
    saved ones are used."""
    if ident not in lc.STATE_IDS:
        return None
    current_time = time.time() if current_time is None else current_time
    sal = tuple(o for o in lc.OUTPUTS if o in (outputs or lc.OUTPUTS))
    TEST.update(id=ident, until=current_time + max(2, min(20, float(seconds))), outputs=sal,
                  color=color, effect=effect if effect in lc.EFFECTS else None)
    return dict(TEST)


def test_active(current_time=None):
    current_time = time.time() if current_time is None else current_time
    if TEST["id"] and current_time < TEST["until"]:
        return TEST
    return None


def state_test(slc, trial):
    """The state under test: saved config, with the colour / effect the page
    has on screen if it sent them."""
    f = dict(lc.state_full(slc, trial["id"]))
    if trial.get("color"):
        f["color"] = lc.clean_color(trial["color"], f["color"])
    if trial.get("effect") and lc.STATE_KIND[trial["id"]] != "emergency":
        f["effect"] = trial["effect"]
    return f


def arm_frame(config, mode, disabled, illum, status, file_pos, file_size, extras, ep=None, current_time=None, trial=None):
    """Everything the three outputs show right now, from the machine data.

    Returns {present, segs, text, ui_color, info, screen: {detalle, text,
    segs}, secs_board, toma, disabled}. segs / text / info are for the strip
    (or, on a machine without strip, for the screen); screen is the on-screen
    indicator. Pure: no painting, no network."""
    slc = config.get("status_light", {}) or {}
    present = lc.has_strip(slc)
    if not present:
        disabled = False  # nothing else uses the strip: the automatic status is always on
    t = time.monotonic() if current_time is None else current_time
    cfg_e = config if disabled else config_state(config)
    output_main = "strip" if present else "screen"

    # a state with the "Board" checkbox takes over the positions of the board LEDs
    take = None
    if trial and "board" in trial["outputs"]:
        f = state_test(slc, trial)
        take = (f["color"], f["effect"])
    elif present and not disabled:
        info_b = {}
        lights_decide.compute(cfg_e, mode, disabled, illum, status, file_pos, file_size, extras, info_b, output="board", current_time=t)
        det = info_b.get("detail") or []
        if det:
            take = (det[0]["color"], det[0]["effect"])
    # leds_board.with_lighting: "mantener" (default) = the board LEDs keep showing the board while
    # the lighting takes the rest of the status zone; "as_zone" = they do what the zone does (they
    # light up or go off together with the lighting)
    follows_zone = disabled and (slc.get("leds_board") or {}).get("with_lighting") == "as_zone"
    if present and not follows_zone:
        # the STATUS LED of the board blinks: during a job it stays lit (no repaint per phase)
        cfg_s, secs_board = apply_leds_board(cfg_e, ep, 0.0 if effects_frozen(slc, status, extras) else t, take)
    else:
        cfg_s, secs_board = cfg_e, []

    info = {}
    secs, text, ui_color = lights_decide.compute(cfg_s, mode, disabled, illum, status, file_pos, file_size, extras, info, output=output_main, current_time=t)
    secs = list(secs) + list(secs_board)
    # the on-screen indicator: same machine data, the states marked "Screen"
    info_p = {}
    if present:
        secs_p, text_p, _ = lights_decide.compute(cfg_e, mode, disabled, illum, status, file_pos, file_size, extras, info_p, output="screen", current_time=t)
    else:
        secs_p, text_p, info_p = secs, text, info

    if trial:
        f = state_test(slc, trial)
        col = f["color"]
        level, enc = lr.effect_level(f["effect"], t)
        label = lc.STATE_TEXT[trial["id"]]
        if "strip" in trial["outputs"] and present:
            n_s = cfg_s.get("status_light", {}).get("led_count", LED_COUNT_DEFAULT)
            secs = [(col["r"], col["u"], col["b"], col.get("w", 0), level, n_s) if enc else (0, 0, 0, 0, 0, n_s)] + secs_board
            text = M("status_light_testing", state=label)
            info = {"activeList": [(trial["id"], col)], "detail": [dict(f, id=trial["id"], color=col)]}
        if "screen" in trial["outputs"]:
            text_p = M("status_light_testing", state=label)
            info_p = {"activeList": [(trial["id"], col)], "detail": [dict(f, id=trial["id"], color=col)]}
        if not present:
            secs, text, info = secs_p, text_p, info_p
    return {"present": present, "secs": secs, "text": text, "ui_color": ui_color, "info": info,
            "screen": {"detail": info_p.get("detail") or [], "text": text_p, "secs": list(secs_p)},
            "secs_board": secs_board, "take": take, "disabled": disabled, "cfg_s": cfg_s, "cfg_e": cfg_e}


def detail_ui(detail):
    """[{id, color, effect}] -> [{id, nombre, hex, effect}] for the screens."""
    out = []
    for d in detail or []:
        c = d.get("color") or {}
        out.append({"id": d["id"], "name": TEXT_OF.get(d["id"], d["id"]), "effect": d.get("effect", "steady"),
                    "hex": hex_color(c.get("r", 0), c.get("u", 0), c.get("b", 0), c.get("w", 0))})
    return out
