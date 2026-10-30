"""
Internal implementation of the API operation(s) notifications.get, notifications.active, notifications.destination, notifications.new_topic, notifications.type, notifications.option, notifications.quiet_hours, notifications.video, notifications.mute, notifications.test (api_ops.py maps their named
arguments to the one-letter parameters below).

Configures the phone notifications (ntfy) of the activity events.
Used by the Activity page (WorkshopActivity plugin).

Usage: <params>                             -> query (JSON)
     <params> C"activo" V1|0                -> turns all on/off
     <params> C"destino" S"https://ntfy.sh" T"my-topic"
     <params> C"new_topic"                -> new random topic (you have to subscribe again on the phone)
     <params> C"tipo" T"job_end" V1|0   -> one event type
     <params> C"probar"                     -> sends a test one
     <params> C"silenciar" D60              -> do not send for 60 min (D, NOT M: "M1" would run as another command)
     <params> C"silenciar" D0               -> reactivate now
     <params> C"opcion" T"job_end" [A"nada"|"foto"|"video"] [R"min"|"low"|"default"|"high"|"urgent"|"auto"] [H1|0] [K"<camera id>"|"auto"]
                                                           -> per type: attachment, ntfy priority (auto = the factory one),
                                                              whether it respects the scheduled silence and which camera sends the photo
     <params> C"horario" [V1|0] [F"22:00"] [U"07:00"] [Q"callar"|"suave"]
                                                           -> scheduled silence (callar: does not send; suave: without sound)
     <params> C"video" D5                   -> seconds of the short video (2 to 10)
Always returns the updated JSON ({config, catalogo, ultimo}).

"""
import json
import re
import time

import activity
import messages
import notifier
from messages import M, J, B


def _dumps(obj):
    """JSON of the answer with every message in the language of the request (the kind names are made at import time)."""
    return json.dumps(messages.localize(obj, messages.current_language()))


def run(params, bridge, config):
    action = str(params.get("C", "query")).strip().lower()
    cfg = notifier.get_cfg(config)
    change = None

    if action == "active":
        cfg["active"] = float(params.get("V", 1)) != 0
        change = M("notif_enabled") if cfg["active"] else M("notif_disabled")
    elif action == "destination":
        server = str(params.get("S", cfg["server"])).strip() or notifier.SERVER_DEFAULT
        topic = str(params.get("T", cfg["topic"])).strip()
        if not re.match(r"^https?://", server):
            return json.dumps({"error": M("notifications_server_must_start_with_http")})
        if topic and not re.match(r"^[A-Za-z0-9_-]{1,64}$", topic):
            return json.dumps({"error": M("notifications_topic_can_only_have_letters_numbers")})
        cfg["server"], cfg["topic"] = server, topic
        change = M("notif_destination", server=server)
    elif action == "new_topic":
        cfg["topic"] = notifier.topic_new()
        change = M("notif_new_topic")
    elif action == "kind":
        type_name = str(params.get("T", "")).strip()
        if type_name not in cfg["kinds"]:
            return json.dumps({"error": M("notifications_unknown_type", type=type_name)})
        cfg["kinds"][type_name] = float(params.get("V", 1)) != 0
        change = None  # changes per type: no event (there would be many)
    elif action == "option":
        type_name = str(params.get("T", "")).strip()
        if type_name not in cfg["options"]:
            return json.dumps({"error": M("notifications_unknown_type", type=type_name)})
        o = dict(cfg["options"][type_name])
        if params.get("A") not in (None, ""):
            a = notifier.attachment_valid(params.get("A"))
            if not a:
                return json.dumps({"error": M("notifications_attachment_none_photo_video")})
            o["attachment"] = a
        if params.get("R") not in (None, ""):
            r = str(params.get("R")).strip().lower()
            if r == "auto":
                r = notifier.options_default(type_name)["priority"]
            if r not in notifier.PRIORITIES:
                return json.dumps({"error": M("notifications_priority_values")})
            o["priority"] = r
        if params.get("H") not in (None, ""):
            o["schedule"] = float(params.get("H")) != 0
        if params.get("K") is not None:
            # camera of this type ("" or "auto" = the notifications default)
            k = str(params.get("K")).strip()
            o["camera"] = "" if k.lower() == "auto" else re.sub(r"[^A-Za-z0-9_-]", "", k)[:40]
        cfg["options"][type_name] = o
        change = None  # like "tipo": no event
    elif action == "schedule":
        h = dict(cfg["schedule"])
        if params.get("V") not in (None, ""):
            h["active"] = float(params.get("V")) != 0
        for letter, field in (("F", "since"), ("U", "until")):
            if params.get(letter) not in (None, ""):
                v = notifier.hour_valid(params.get(letter))
                if not v:
                    return json.dumps({"error": M("notifications_time_must_be_hh_mm")})
                h[field] = v
        if params.get("Q") not in (None, ""):
            q = notifier.mode_valid(params.get("Q"))
            if not q:
                return json.dumps({"error": M("notifications_schedule_mode_values")})
            h["mode"] = q
        cfg["schedule"] = h
        change = M("notif_schedule_on", since=h["since"], until=h["until"]) if h["active"] else M("notif_schedule_off")
    elif action == "video":
        cfg["video_s"] = int(max(notifier.VIDEO_S_MIN, min(notifier.VIDEO_S_MAX, float(params.get("D", notifier.VIDEO_S_DEFAULT)))))
        change = None
    elif action == "silenciar":
        minutes = max(0.0, min(float(params.get("D", 60)), 24 * 60))
        cfg["silence_until"] = int(time.time() + minutes * 60) if minutes > 0 else 0
        change = M("notif_silenced", minutes=minutes) if minutes > 0 else M("notif_reactivated")
    elif action == "test":
        type_name = str(params.get("T", "")).strip()
        out = notifier.status(config)
        if type_name:
            if type_name not in cfg["kinds"]:
                return json.dumps({"error": M("notifications_unknown_type", type=type_name)})
            out["test"] = dict(notifier.probe_kind(config, type_name), kind=type_name)
            return _dumps(out)
        ok, err = notifier.send_test(config)
        out["test"] = {"ok": ok, "error": err}
        return _dumps(out)

    if action in ("active", "destination", "new_topic", "kind", "silenciar", "option", "schedule", "video"):
        notifier.set_cfg(config, cfg)
        bridge.save_config()
        notifier.publish()
        if change:
            activity.log_event(bridge, "config", change)

    return _dumps(notifier.status(config))
