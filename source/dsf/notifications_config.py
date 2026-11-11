"""Settings of the phone notifications (ntfy) of the activity events, behind the operations notifications.get, .active, .destination,
.new_topic, .type, .option, .quiet_hours, .video, .mute and .test (notifications_ops.py registers them; phase 5 of the redesign, it
replaces handlers/notifications.py). Used by the Activity page (WorkshopActivity plugin).

Every function takes the bridge and the configuration plus named, already validated arguments, changes the settings through notifier
(get_cfg / set_cfg), saves config.json, publishes the new state and notes the change in Activity where it matters, and returns the
updated {config, catalog, last, muted, in_schedule}. A refused change is {"error": <message>} (an answer, not an ApiError) and saves
nothing.
"""
import re
import time

import activity
import notifier
from messages import M


def _commit(bridge, config, cfg, change=None):
    """Saves the settings, publishes them, notes `change` in Activity (when there is one) and answers the new state."""
    notifier.set_cfg(config, cfg)
    bridge.save_config()
    notifier.publish()
    if change:
        activity.log_event(bridge, "config", change)
    return notifier.status(config)


def status(config):
    return notifier.status(config)


def set_active(bridge, config, *, on, acknowledge_outbound=False):
    """All notifications on or off. Turning them on sends data to a third-party server, so it needs the explicit acknowledgement (like the
    confirmation dialog of the page: an API caller cannot turn it on silently) and creates the topic of a new installation."""
    cfg = notifier.get_cfg(config)
    cfg["active"] = bool(on)
    if cfg["active"]:
        if not acknowledge_outbound:
            return {"error": M("notifications_confirm_outbound_required")}
        if not cfg["topic"]:
            cfg["topic"] = notifier.topic_new()  # a new installation has no topic until it asks for the notifications
    return _commit(bridge, config, cfg, M("notif_enabled") if cfg["active"] else M("notif_disabled"))


def set_destination(bridge, config, *, server=None, topic=None):
    """Server (empty: the default one) and topic; an argument that is not given keeps what is saved."""
    cfg = notifier.get_cfg(config)
    server = str(cfg["server"] if server is None else server).strip() or notifier.SERVER_DEFAULT
    topic = str(cfg["topic"] if topic is None else topic).strip()
    if not re.match(r"^https?://", server):
        return {"error": M("notifications_server_must_start_with_http")}
    if topic and not re.match(r"^[A-Za-z0-9_-]{1,64}$", topic):
        return {"error": M("notifications_topic_can_only_have_letters_numbers")}
    cfg["server"], cfg["topic"] = server, topic
    return _commit(bridge, config, cfg, M("notif_destination", server=server))


def new_topic(bridge, config):
    cfg = notifier.get_cfg(config)
    cfg["topic"] = notifier.topic_new()
    return _commit(bridge, config, cfg, M("notif_new_topic"))


def set_kind(bridge, config, *, type, on):
    """One event type on or off (no Activity event: there would be many)."""
    cfg = notifier.get_cfg(config)
    type_name = str(type).strip()
    if type_name not in cfg["kinds"]:
        return {"error": M("notifications_unknown_type", type=type_name)}
    cfg["kinds"][type_name] = bool(on)
    return _commit(bridge, config, cfg)


def set_option(bridge, config, *, type=None, attachment=None, priority=None, quiet_hours=None, camera=None, default_camera=None):
    """Options of one event type (only what is given changes); without a type, only default_camera ("auto" = the main camera)."""
    cfg = notifier.get_cfg(config)
    type_name = str(type if type is not None else "").strip()
    if not type_name and default_camera is not None:
        z = str(default_camera).strip()
        cfg["default_camera"] = "" if z.lower() == "auto" else notifier.camera_id_clean(z)
        return _commit(bridge, config, cfg)
    if type_name not in cfg["options"]:
        return {"error": M("notifications_unknown_type", type=type_name)}
    o = dict(cfg["options"][type_name])
    if attachment not in (None, ""):
        a = notifier.attachment_valid(attachment)
        if not a:
            return {"error": M("notifications_attachment_none_photo_video")}
        o["attachment"] = a
    if priority not in (None, ""):
        r = str(priority).strip().lower()
        if r == "auto":
            r = notifier.options_default(type_name)["priority"]
        if r not in notifier.PRIORITIES:
            return {"error": M("notifications_priority_values")}
        o["priority"] = r
    if quiet_hours not in (None, ""):
        o["schedule"] = bool(quiet_hours)
    if camera is not None:
        # camera of this type ("" or "auto" = the notifications default)
        k = str(camera).strip()
        o["camera"] = "" if k.lower() == "auto" else re.sub(r"[^A-Za-z0-9_-]", "", k)[:40]
    cfg["options"][type_name] = o
    return _commit(bridge, config, cfg)


def set_quiet_hours(bridge, config, *, on=None, since=None, until=None, mode=None):
    """The scheduled silence (mute: nothing is sent; soft: without sound); only what is given changes."""
    cfg = notifier.get_cfg(config)
    h = dict(cfg["schedule"])
    if on not in (None, ""):
        h["active"] = bool(on)
    for value, field in ((since, "since"), (until, "until")):
        if value not in (None, ""):
            v = notifier.hour_valid(value)
            if not v:
                return {"error": M("notifications_time_must_be_hh_mm")}
            h[field] = v
    if mode not in (None, ""):
        q = notifier.mode_valid(mode)
        if not q:
            return {"error": M("notifications_schedule_mode_values")}
        h["mode"] = q
    cfg["schedule"] = h
    return _commit(bridge, config, cfg,
                   M("notif_schedule_on", since=h["since"], until=h["until"]) if h["active"] else M("notif_schedule_off"))


def set_video(bridge, config, *, seconds):
    """Length of the short video, kept between notifier.VIDEO_S_MIN and VIDEO_S_MAX."""
    cfg = notifier.get_cfg(config)
    cfg["video_s"] = int(max(notifier.VIDEO_S_MIN, min(notifier.VIDEO_S_MAX, float(seconds))))
    return _commit(bridge, config, cfg)


def mute(bridge, config, *, minutes):
    """Nothing is sent for `minutes` (at most a day); 0 reactivates now. Events are still recorded."""
    cfg = notifier.get_cfg(config)
    minutes = max(0.0, min(float(minutes), 24 * 60))
    cfg["silence_until"] = int(time.time() + minutes * 60) if minutes > 0 else 0
    return _commit(bridge, config, cfg, M("notif_silenced", minutes=minutes) if minutes > 0 else M("notif_reactivated"))


def test(config, *, type=""):
    """A test notification (of one event type when given, with its own attachment, priority and camera); changes no setting."""
    cfg = notifier.get_cfg(config)
    type_name = str(type).strip()
    out = notifier.status(config)
    if type_name:
        if type_name not in cfg["kinds"]:
            return {"error": M("notifications_unknown_type", type=type_name)}
        out["test"] = dict(notifier.probe_kind(config, type_name), kind=type_name)
        return out
    ok, err = notifier.send_test(config)
    out["test"] = {"ok": ok, "error": err}
    return out
