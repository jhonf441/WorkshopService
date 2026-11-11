"""API operations of the phone notifications: notifications.get / active / destination / new_topic / type / option / quiet_hours / video /
mute / test (notifications_config.py). notifications.send stays in api_ops. api_ops.init registers them through build(ctx), like
settings_ops. The class, arguments, role (permissions.py) and flags are the ones they had when they were handlers/notifications.py.
"""
import notifications_config as nc
from workshop_api import READ, WRITE, Arg, Op


def build(ctx):
    """The operations; ctx is api_ops._ctx (bridge, config)."""
    S, I, N, B = "str", "int", "num", "bool"
    a = Arg

    def get(args, c):
        return nc.status(ctx["config"])

    def active(args, c):
        return nc.set_active(ctx["bridge"], ctx["config"], on=args["on"], acknowledge_outbound=args.get("acknowledge_outbound", False))

    def destination(args, c):
        return nc.set_destination(ctx["bridge"], ctx["config"], server=args.get("server"), topic=args.get("topic"))

    def new_topic(args, c):
        return nc.new_topic(ctx["bridge"], ctx["config"])

    def kind(args, c):
        return nc.set_kind(ctx["bridge"], ctx["config"], type=args["type"], on=args["on"])

    def option(args, c):
        return nc.set_option(ctx["bridge"], ctx["config"], type=args.get("type"), attachment=args.get("attachment"), priority=args.get("priority"),
                             quiet_hours=args.get("quiet_hours"), camera=args.get("camera"), default_camera=args.get("default_camera"))

    def quiet_hours(args, c):
        return nc.set_quiet_hours(ctx["bridge"], ctx["config"], on=args.get("on"), since=args.get("from"), until=args.get("to"), mode=args.get("mode"))

    def video(args, c):
        return nc.set_video(ctx["bridge"], ctx["config"], seconds=args["seconds"])

    def mute(args, c):
        return nc.mute(ctx["bridge"], ctx["config"], minutes=args["minutes"])

    def test(args, c):
        return nc.test(ctx["config"], type=args.get("type", ""))

    return [
        Op("notifications.get", get, READ, {},
           "Returns the phone notification settings (ntfy destination, event types and options, quiet hours, mute) and the catalogue of event types."),
        Op("notifications.active", active, WRITE,
           {"on": a(B, True, desc="true sends notifications, false sends none (events are still logged)."),
            "acknowledge_outbound": a(B, desc="Required true to turn them on: the events (and photos or videos if chosen) are sent to a third-party server, ntfy.sh unless another one is set.")},
           "Turns every phone notification on or off. They are OFF by default because turning them on sends data out of the machine to a third-party server; "
           "turning them on is refused unless acknowledge_outbound is true. Saved and logged in Activity."),
        Op("notifications.destination", destination, WRITE,
           {"server": a(S, desc="ntfy server starting with http:// or https:// (empty: https://ntfy.sh)."),
            "topic": a(S, desc="ntfy topic: letters, numbers, - and _, up to 64 characters.")},
           "Changes the ntfy server and topic the notifications go to. Saved and logged in Activity."),
        Op("notifications.new_topic", new_topic, WRITE, {},
           "Replaces the ntfy topic with a new random one; the phone has to subscribe again. Saved and logged in Activity."),
        Op("notifications.type", kind, WRITE,
           {"type": a(S, True, desc="Event type id, for example job_end, error, power, fuego (catalogue in notifications.get)."),
            "on": a(B, True, desc="true sends this type to the phone, false does not.")},
           "Turns the phone notifications of one event type on or off. Saved."),
        Op("notifications.option", option, WRITE,
           {"type": a(S, desc="Event type id (catalogue in notifications.get). Without it only default_camera is changed."),
            "attachment": a(S, choices=("none", "photo", "video"), desc="What is attached to the notification: none, a photo or a short video."),
            "priority": a(S, choices=("min", "low", "default", "high", "urgent", "auto"), desc="ntfy priority; auto goes back to the default of the type."),
            "quiet_hours": a(B, desc="Whether the quiet hours apply to this type."),
            "camera": a(S, desc="Camera of the photo or video of this type: a camera id, or \"auto\" / \"\" for the default camera of the notices."),
            "default_camera": a(S, desc="Without type: the camera of the photo or video of every type that does not choose its own: a camera id, or \"auto\" for the main one.")},
           "Changes the options of one event type (attachment, priority, quiet hours, camera); only the arguments given change. Without type, default_camera sets the camera "
           "the notices use unless their type chooses another. Whether a notice carries a photo or a video is decided here (the attachment of each type), not by the camera service. Saved."),
        Op("notifications.quiet_hours", quiet_hours, WRITE,
           {"on": a(B, desc="Quiet hours on or off."), "from": a(S, desc="Start time HH:MM, for example 22:00."),
            "to": a(S, desc="End time HH:MM, for example 07:00."),
            "mode": a(S, choices=("mute", "soft"), desc="mute: nothing is sent; soft: sent without sound.")},
           "Sets the daily quiet hours of the notifications; only the arguments given change. Saved and logged in Activity."),
        Op("notifications.video", video, WRITE,
           {"seconds": a(I, True, min=2, max=10, desc="Video length, 2 to 10 seconds.")},
           "Sets the length of the short video attached to the notifications that use video. Saved."),
        Op("notifications.mute", mute, WRITE,
           {"minutes": a(N, True, min=0, max=1440, desc="Minutes to mute, up to 1440; 0 unmutes now.")},
           "Mutes the phone notifications for N minutes (events are still logged), or unmutes them with 0. Logged in Activity."),
        Op("notifications.test", test, WRITE,
           {"type": a(S, desc="Event type id (catalogue in notifications.get): tests that type with its own attachment, priority and camera, skipping its switch, the quiet hours and the mute. Without it, a plain test.")},
           "Sends a test notification to the configured destination and returns whether it was accepted, with the settings. With a type it sends what a real event of that type would send, marked as a test."),
    ]
