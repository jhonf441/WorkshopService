"""API operations of the service itself: modules.list / modules.set (module_modes.py) and db.status / backup /
places / folder / delete_previous / keep / settings (db_admin.py). api_ops.init registers them through build(ctx),
like settings_ops. The class, arguments, role (permissions.py) and flags are the ones they had when they were handlers/service_modules and handlers/base.py.
"""
import db_admin
import module_modes
from workshop_api import READ, WRITE, Arg, Op


def build(ctx):
    """The operations; ctx is api_ops._ctx (bridge, config)."""
    S, N, B = "str", "num", "bool"
    a = Arg

    def modules_list(args, c):
        return module_modes.listing()

    def modules_set(args, c):
        return module_modes.set_mode(ctx["bridge"], ctx["config"], process=args["process"], mode=args["mode"])

    def db_status(args, c):
        r = db_admin.state()
        return "null" if r is None else r  # a database that does not exist yet was always the text "null", not a result

    def db_backup_now(args, c):
        return db_admin.back_up_now()

    def db_places(args, c):
        return db_admin.places()

    def db_folder(args, c):
        return db_admin.change_folder(path=args["path"])

    def db_delete_previous(args, c):
        return db_admin.delete_previous()

    def db_keep(args, c):
        return db_admin.keep(file=args["file"], keep=args.get("keep", True))

    def db_settings(args, c):
        return db_admin.settings(auto=args.get("auto"), daily=args.get("daily"), weekly=args.get("weekly"), summarize=args.get("summarize"),
                                 extra_copy=args.get("extra_copy"))

    return [
        Op("db.status", db_status, READ, {}, "Returns the state of the service database, its backups and its maintenance."),
        Op("db.backup", db_backup_now, WRITE, {},
           "Makes a backup now: the database and the workshop folders (0:/sys/workshop config, data, zones) in one .tar.gz in the backup folder "
           "(and in the extra copy if set)."),
        Op("db.places", db_places, READ, {},
           "Lists where backups can be kept: the system card and every mounted USB stick, with their free space."),
        Op("db.folder", db_folder, WRITE,
           {"path": a(S, True, desc="Absolute folder on the system card (inside the DSF SD folder) or on a USB stick (/media/..., /mnt/...), "
                                    "for example one of db.places.")},
           "Changes the backup folder: the existing backups are copied (not moved) and checked; the old folder stays until db.delete_previous."),
        Op("db.delete_previous", db_delete_previous, WRITE, {},
           "Deletes the backups of the previous backup folder that already have a copy in the current one; the others are left alone."),
        Op("db.keep", db_keep, WRITE,
           {"file": a(S, True, desc="File name of the backup in the backup folder (as listed by db.status)."),
            "keep": a(B, default=True, desc="true (default) protects it from the automatic deletion; false lets the rotation delete it again.")},
           "Marks a backup so the rotation never deletes it automatically, or releases that mark."),
        Op("db.settings", db_settings, WRITE,
           {"auto": a(B, desc="Automatic daily backups on or off."),
            "daily": a(N, min=0, desc="How many daily backups are kept (the service keeps it between 1 and 60)."),
            "weekly": a(N, min=0, desc="How many weekly backups are kept among the older ones (0 to 52)."),
            "summarize": a(B, desc="Summarize meter readings older than 90 days to one per hour (after a warning and a backup); false never summarizes."),
            "extra_copy": a(S, desc="Extra copy of each backup: \"auto\" (the first USB stick, or the card when the main folder is a stick), "
                                    "\"no\", or a folder on the card or on a stick.")},
           "Changes the backup settings; only the arguments given change. Returns the resulting settings."),
        Op("modules.list", modules_list, READ, {},
           "Lists the internal processes of the service with the way each one runs (auto / on / off), whether it runs now and why (a plugin that needs it is enabled, or forced).", log=False),
        Op("modules.set", modules_set, WRITE,
           {"process": a(S, True, desc="Id of the internal process (as listed by modules.list)."),
            "mode": a(S, True, choices=("auto", "on", "off"), desc="auto: runs only while a plugin that needs it is enabled; on: always; off: never (applies at the next start of the service).")},
           "Chooses how an internal process of the service runs. Saved in the configuration."),
    ]
