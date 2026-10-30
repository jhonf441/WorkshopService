"""
Phone notifications (ntfy) of the activity history events.

Every event goes through activity.log_event(): it is saved in the DB and, if
its TYPE is enabled here, it is also sent as a push notification. The config
lives in config.json -> "notificaciones" and is edited from the Activity
page (WorkshopActivity plugin) via handlers/notifications.py.

It replaces duet-notify (a separate systemd service that only saw file jobs
and pauses/emergencies, with the topic written in the .service): now there
is ONE event flow and one configuration.

Sending runs in a separate thread: whoever records the event (e.g.
shutdown_all.py, about to cut the power) never waits for the network.

"""
import threading
import time
import urllib.request
from messages import M

# (type, UI label, enabled by default, ntfy priority, ntfy tag/emoji)
KINDS = [
    ("job_start", M("notice_kind_job_start"), False, "default", "arrow_forward"),
    ("job_end", M("notice_kind_job_end"), True, "default", "white_check_mark"),
    ("job_pause", M("notice_kind_job_pause"), True, "default", "pause_button"),
    ("emergency", M("notice_kind_emergency"), True, "urgent", "rotating_light"),
    ("error", M("notice_kind_error"), True, "high", "warning"),
    ("notice", M("notice_kind_notice"), False, "low", "information_source"),
    ("power", M("notice_kind_power"), True, "high", "electric_plug"),
    ("system", M("notice_kind_system"), True, "low", "computer"),
    ("service", M("notice_kind_service"), False, "min", "arrows_counterclockwise"),
    ("mode", M("notice_kind_mode"), False, "low", "gear"),
    ("zone", M("notice_kind_zone"), False, "min", "triangular_ruler"),
    ("config", M("notice_kind_config"), False, "low", "wrench"),
    # 2026-10-10: riesgo activo (nivel 4, risk_rules.py) y calibraciones (the API (log))
    ("risk", M("notice_kind_risk"), True, "high", "warning"),
    ("calibration", M("notice_kind_calibration"), False, "low", "straight_ruler"),
    # Machine v2 phase 4: a maintenance item became due (machine_maintenance.py; the owner's opt-in is in the maintenance plan)
    ("maintenance", M("notice_kind_maintenance"), True, "default", "wrench"),
    ("fire", M("notice_kind_fire"), True, "urgent", "fire"),
    # Pi health (health_poller.py / "Pi health" page), 2026-10-09
    ("health_temp", M("notice_kind_health_temp"), True, "high", "thermometer"),
    ("health_voltage", M("notice_kind_health_voltage"), True, "high", "zap"),
    ("health_wifi", M("notice_kind_health_wifi"), True, "default", "signal_strength"),
    ("health_service", M("notice_kind_health_service"), True, "high", "warning"),
    ("health_restart", M("notice_kind_health_restart"), True, "high", "rotating_light"),
    # 2026-10-12: black_box.py, unclean shutdown with the report of the last lines
    ("box_black", M("notice_kind_box_black"), True, "high", "page_facing_up"),
    # 2026-10-10: little space on the Pi's card, or the database too big
    ("health_disk", M("notice_kind_health_disk"), True, "high", "floppy_disk"),
    # 2026-10-10: camera_relay.py warns if a camera stops responding and when it comes back
    ("camera", M("notice_kind_camera"), True, "default", "camera"),
    # 2026-10-10: the relay limits or cuts screens because of the Pi's load
    ("camera_load", M("notice_kind_camera_load"), False, "low", "camera"),
    # 2026-10-10: before deleting only videos or photos because of the caps (they can be kept)
    ("camera_deleted", M("notice_kind_camera_deleted"), True, "default", "wastebasket"),
    # 2026-10-11: old backups or meter readings that are going to be deleted or summarized (they can be kept)
    ("base_deleted", M("notice_kind_base_deleted"), True, "default", "wastebasket"),
    # 2026-10-11: the automatic database backup failed
    ("base_backup", M("notice_kind_base_backup"), True, "high", "floppy_disk"),
    # 2026-10-10: a meter that watches a heater consumes with the heater off
    ("meter_alarm", M("notice_kind_meter_alarm"), True, "urgent", "rotating_light"),
    # F1-C: a safety process died / a protection is unwatched (protection_guard.py); the alarm is with a job running
    ("guard", M("notice_kind_guard"), True, "high", "warning"),
    ("guard_alarm", M("notice_kind_guard_alarm"), True, "urgent", "rotating_light"),
]
# Types that until 2026-10-12 went with a photo (fixed list): now it is the
# default value of the "adjunto" option of each type (item 21).
_KINDS_WITH_PHOTO = ("job_end", "job_pause", "error", "emergency")
_KIND = {t[0]: t for t in KINDS}

# ---- options per type (2026-10-12, item 21) ----
# config.json "notificaciones":
# "opciones": {type: {"adjunto": "none"|"photo"|"video", "prioridad": <ntfy>, "horario": bool, "camara": "" | <id>}}
# only what differs from the default is saved (so a change of default in a
# new version reaches the types nobody touched)
# "horario": {"activo", "desde": "HH:MM", "hasta": "HH:MM", "modo": "mute"|"soft"}
# scheduled silence (it crosses midnight if desde > hasta). It affects the
# types with "horario": true; "mute" does not send, "soft" sends without sound (min)
# "video_s": seconds of the short video (camera_relay.video_for_notice)
# By default everything stays as before: photo attachment in _KINDS_WITH_PHOTO, priority
# the one in KINDS, schedule off (the urgent ones do not respect it even if it is turned on).
ATTACHMENTS = ("none", "photo", "video")
ATTACHMENT_ALIAS = {"nothing": "none", "none": "none", "photo": "photo", "clip": "video", "no": "none"}
PRIORITIES = ("min", "low", "default", "high", "urgent")
MODES_SCHEDULE = ("mute", "soft")
MODE_ALIAS = {"callar": "mute", "silencio": "mute", "soft": "soft", "without_sound": "soft"}
SCHEDULE_DEFAULT = {"active": False, "since": "22:00", "until": "07:00", "mode": "mute"}
VIDEO_S_DEFAULT = 5
VIDEO_S_MIN, VIDEO_S_MAX = 2, 10


def options_default(type_name):
    t = _KIND.get(type_name, (type_name, type_name, False, "default", None))
    return {"attachment": "photo" if type_name in _KINDS_WITH_PHOTO else "none", "priority": t[3], "schedule": t[3] != "urgent", "camera": ""}


def attachment_valid(v):
    v = str(v or "").strip().lower()
    v = ATTACHMENT_ALIAS.get(v, v)
    return v if v in ATTACHMENTS else None


def mode_valid(v):
    v = str(v or "").strip().lower()
    v = MODE_ALIAS.get(v, v)
    return v if v in MODES_SCHEDULE else None


def hour_valid(v):
    """"7:5" / "07:05" -> "07:05"; None if it is not a time."""
    import re
    m = re.match(r"^\s*(\d{1,2})[:.h](\d{1,2})\s*$", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def _option_clean(type_name, saved):
    """Full options of a type: default + whatever is saved that is valid."""
    o = options_default(type_name)
    g = saved if isinstance(saved, dict) else {}
    a = attachment_valid(g.get("attachment"))
    if a:
        o["attachment"] = a
    p = str(g.get("priority") or "").strip().lower()
    if p in PRIORITIES:
        o["priority"] = p
    if "schedule" in g:
        o["schedule"] = bool(g["schedule"])
    # camera of the photo / video of this type ("" = the notifications default)
    import re
    o["camera"] = re.sub(r"[^A-Za-z0-9_-]", "", str(g.get("camera") or ""))[:40]
    return o


def _schedule_clean(h):
    h = h if isinstance(h, dict) else {}
    return {
        "active": bool(h.get("active", SCHEDULE_DEFAULT["active"])),
        "since": hour_valid(h.get("since")) or SCHEDULE_DEFAULT["since"],
        "until": hour_valid(h.get("until")) or SCHEDULE_DEFAULT["until"],
        "mode": mode_valid(h.get("mode")) or SCHEDULE_DEFAULT["mode"],
    }


def in_schedule(cfg, current_time=None):
    """True if now falls within the scheduled silence (and it is active)."""
    h = cfg.get("schedule") or {}
    if not h.get("active"):
        return False
    t = time.localtime(current_time if current_time is not None else time.time())
    m = t.tm_hour * 60 + t.tm_min
    d = int(h["since"][:2]) * 60 + int(h["since"][3:])
    a = int(h["until"][:2]) * 60 + int(h["until"][3:])
    if d == a:
        return False  # same schedule: no silence (not "all day" by mistake)
    return d <= m < a if d < a else (m >= d or m < a)


def plan_sending(cfg, type_name, current_time=None):
    """What to do with an event: None (not sent) or {priority, attachment, schedule}.
    It looks at neither the network nor the camera: it can be tested without the machine."""
    if not cfg["active"] or not cfg["topic"] or not cfg["kinds"].get(type_name) or muted(cfg, current_time):
        return None
    o = cfg["options"].get(type_name) or options_default(type_name)
    plan = {"priority": o["priority"], "attachment": o["attachment"], "schedule": False, "camera": o.get("camera") or ""}
    if o["schedule"] and in_schedule(cfg, current_time):
        if cfg["schedule"]["mode"] == "mute":
            return None
        plan["priority"] = "min"  # ntfy "min": arrives without sound or vibration
        plan["schedule"] = True
    return plan


SERVER_DEFAULT = "https://ntfy.sh"

_state = {"bridge": None, "config": None, "last": None}
_lock = threading.Lock()


def topic_new():
    """Random topic for this installation. On ntfy.sh the topic IS the key:
    anyone who knows it reads and sends notifications, so each machine must
    have its own and it must not be guessable: 160 random bits, no host name
    (a short topic with the host name can be found by trying). Only new
    installations get it; an existing topic is never replaced."""
    import secrets
    return "workshop-" + secrets.token_hex(20)


def init(bridge, config):
    _state["bridge"] = bridge
    _state["config"] = config
    cfg = get_cfg(config)
    if not cfg["topic"]:
        cfg["topic"] = topic_new()
        set_cfg(config, cfg)
        try:
            bridge.save_config()
        except Exception:
            pass
    publish()


def get_cfg(config):
    n = config.get("notifications") or {}
    kinds = {t[0]: t[2] for t in KINDS}
    kinds.update({k: bool(v) for k, v in (n.get("kinds") or {}).items()})
    return {
        "active": bool(n.get("active", True)),
        "server": str(n.get("server") or SERVER_DEFAULT),
        # Before, the topic was in config["ntfy_topic"] (handlers/ntfy.py) and
        # in the duet-notify .service -- it is inherited from there the first time.
        "topic": str(n.get("topic") if n.get("topic") is not None else config.get("ntfy_topic", "")),
        "kinds": kinds,
        # Epoch (s) until which nothing is sent (0 = not muted). Used by
        # "Mute 1 h" of the sidebar: when standing next to the machine the phone
        # does not need to sound. Events are still recorded
        # the same; it reactivates by itself when it expires.
        "silence_until": int(n.get("silence_until") or 0),
        "options": {t[0]: _option_clean(t[0], (n.get("options") or {}).get(t[0])) for t in KINDS},
        "schedule": _schedule_clean(n.get("schedule")),
        "video_s": max(VIDEO_S_MIN, min(VIDEO_S_MAX, int(n.get("video_s") or VIDEO_S_DEFAULT))),
    }


def _only_changes(options):
    """What differs from the default, per type (it is what gets saved)."""
    out = {}
    for type_name, o in (options or {}).items():
        d = options_default(type_name)
        dif = {k: v for k, v in o.items() if k in d and v != d[k]}
        if dif:
            out[type_name] = dif
    return out


def set_cfg(config, cfg):
    config["notifications"] = {
        "active": cfg["active"],
        "server": cfg["server"],
        "topic": cfg["topic"],
        "kinds": cfg["kinds"],
        "silence_until": int(cfg.get("silence_until") or 0),
        "options": _only_changes(cfg.get("options")),
        "schedule": _schedule_clean(cfg.get("schedule")),
        "video_s": int(cfg.get("video_s") or VIDEO_S_DEFAULT),
    }
    # handlers/ntfy.py still reads ntfy_topic: it is kept in sync.
    config["ntfy_topic"] = cfg["topic"]


def catalog():
    # label is a message: published as {"key", "params"} (every page shows it in its language), localized in an API answer
    return [{"kind": t[0], "label": t[1], "priority": t[3],
             "defaultValue": options_default(t[0])} for t in KINDS]


def muted(cfg, current_time=None):
    return cfg.get("silence_until", 0) > (current_time if current_time is not None else time.time())


def status(config):
    cfg = get_cfg(config)
    return {"config": cfg, "catalog": catalog(), "last": _state["last"], "muted": muted(cfg),
            "in_schedule": in_schedule(cfg)}


def publish():
    b, c = _state["bridge"], _state["config"]
    if b is None or c is None:
        return
    try:
        b.set_status("notifications", status(c))
    except Exception:
        pass


def send(cfg, title, message, priority="default", tags=None):
    """Envio sincronico. Devuelve (ok, error_o_None)."""
    if not cfg["topic"]:
        return False, M("notifier_no_topic_configured")
    url = cfg["server"].rstrip("/") + "/" + cfg["topic"]
    headers = {"Title": title.encode("utf-8"), "Priority": priority}
    if tags:
        headers["Tags"] = tags
    try:
        req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _rfc2047(raw_text):
    # ntfy accepts encoded headers: that is how accents get through in Title/Message
    import base64
    return "=?UTF-8?B?" + base64.b64encode(raw_text.encode("utf-8")).decode("ascii") + "?="


def send_photo(cfg, title, message, jpeg, priority="default", tags=None):
    """Like send(), with the camera photo attached (2026-10-10). The text
    goes in the Message header because the body is the image."""
    return send_file(cfg, title, message, jpeg, time.strftime("camara-%Y%m%d-%H%M%S.jpg"), priority, tags)


def send_file(cfg, title, message, payload, label, priority="default", tags=None, timeout=20):
    """Send with an attached file (photo or video). Returns (ok, error_or_None)."""
    if not cfg["topic"]:
        return False, M("notifier_no_topic_configured")
    url = cfg["server"].rstrip("/") + "/" + cfg["topic"]
    headers = {"Title": _rfc2047(title), "Message": _rfc2047(message), "Priority": priority, "Filename": label}
    if tags:
        headers["Tags"] = tags
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="PUT")
        urllib.request.urlopen(req, timeout=timeout)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _register_sending(type_name, title, ok, err):
    with _lock:
        _state["last"] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": type_name,
            "title": title,
            "ok": ok,
            "error": err,
        }
    publish()


def _photo(camera=None):
    try:
        import camera_relay
        return camera_relay.photo_for_notice(camera or None)
    except Exception:
        return None


def _video(seconds, camera=None):
    try:
        import camera_relay
        return camera_relay.video_for_notice(seconds, camera or None)
    except Exception:
        return None


def _send_first(cfg, type_name, title, description, plan, tags):
    """The text (with the photo when the type asks for it): (ok, error, with_photo). It also logs the send."""
    photo = _photo(plan.get("camera")) if plan["attachment"] in ("photo", "video") else None
    ok, err = (False, None)
    if photo:
        ok, err = send_photo(cfg, title, description, photo, priority=plan["priority"], tags=tags)
    if not ok:  # no camera (or the send with photo failed): the notice goes out anyway
        ok, err = send(cfg, title, description, priority=plan["priority"], tags=tags)
    _register_sending(type_name, title, ok, err)
    return ok, err, bool(photo)


def _send_video(cfg, type_name, title, plan):
    clip = _video(cfg.get("video_s", VIDEO_S_DEFAULT), plan.get("camera"))
    if not clip:
        return
    import messages
    lang = messages.language(_state["config"] or {})
    ok2, err2 = send_file(cfg, title + " (video)", M("notice_video_caption").text(lang), clip,
                             time.strftime("camara-%Y%m%d-%H%M%S.mp4"), priority="min", tags="movie_camera", timeout=60)
    if not ok2:
        _register_sending(type_name, title + " (video)", ok2, err2)


def _send(cfg, type_name, title, description, plan, tags):
    """What runs in the thread: text (with a photo if applicable) and then the video.
    The notice goes out right away with the photo; the video (a few seconds AFTER
    the event, plus assembly) arrives as a second message with "min" priority
    (no sound): so an urgent notice is never delayed nor sounds twice."""
    ok, _err, _photo_ok = _send_first(cfg, type_name, title, description, plan, tags)
    if plan["attachment"] != "video" or not ok:
        return
    _send_video(cfg, type_name, title, plan)


def probe_kind(config, type_name):
    """Test of ONE event type: sends what a real event of that type would send (its attachment, priority
    and camera) with a text that says it is a test. It skips the type switch, the quiet hours and the mute, so
    it can be tried at any time. Returns {ok, error, adjunto, with_photo, video}."""
    t = _KIND.get(type_name)
    if t is None:
        return {"ok": False, "error": "unknown type: %s" % type_name}
    cfg = get_cfg(config)
    if not cfg.get("topic"):
        return {"ok": False, "error": "no topic: set the destination first"}
    o = cfg["options"].get(type_name) or options_default(type_name)
    plan = {"priority": o["priority"], "attachment": o["attachment"], "schedule": False, "camera": o.get("camera") or ""}
    import messages
    lang = messages.language(config)
    title = t[1].text(lang) + " " + M("notice_test_suffix").text(lang)
    description = M("notice_kind_test_body").text(lang)
    ok, err, with_photo = _send_first(cfg, type_name, title, description, plan, t[4])
    video = plan["attachment"] == "video" and ok
    if video:
        threading.Thread(target=_send_video, args=(cfg, type_name, title, plan), daemon=True).start()
    return {"ok": ok, "error": err, "attachment": plan["attachment"], "with_photo": with_photo, "video": video}


def notify_event(type_name, description):
    """Called by activity.log_event() with each event. It does not block."""
    config = _state["config"]
    if config is None:
        return
    cfg = get_cfg(config)
    plan = plan_sending(cfg, type_name)
    if plan is None:
        return
    t = _KIND.get(type_name, (type_name, type_name, False, "default", None))
    # phone language = DWC's (messages.language); the history keeps the Spanish text and the key
    import messages
    lang = messages.language(config)
    title = t[1].text(lang) if isinstance(t[1], messages.Msg) else str(t[1])
    description = description.text(lang) if isinstance(description, messages.Msg) else description
    threading.Thread(target=_send, args=(cfg, type_name, title, description, plan, t[4]), daemon=True).start()


def send_test(config):
    cfg = get_cfg(config)
    import messages
    lang = messages.language(config)
    title = M("notice_test_title").text(lang)
    ok, err = send(cfg, title, M("notice_test_body").text(lang), tags="white_check_mark")
    _register_sending("test", title, ok, err)
    return ok, err
