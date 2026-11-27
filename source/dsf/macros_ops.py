"""The `macros.catalog` operation (lote 6): registers macros_catalog.catalog in the API. Read-only; the rules are in macros_catalog.py."""
import macros_catalog
from workshop_api import READ, Op


def ops():
    def _catalog(args, ctx):
        user = (ctx or {}).get("user")
        role = user.get("role") if isinstance(user, dict) else ""
        lang = "en" if str((ctx or {}).get("lang") or "").lower().startswith("en") else "es"
        return macros_catalog.catalog(role, lang)

    return [
        Op("macros.catalog", _catalog, READ, {},
           "Lists the macros a person may pick for a button, in two groups. mine: the paths (relative to 0:/macros) of every .g the person has there. "
           "plugins: the macros the workshop plugins ship for the person to call, [{action: 'plugin:<path>', plugin, file, title, description}], only the ones their manifest "
           "(sys/workshop/macros/macros.<PluginId>.json) declares audience user; the helpers only the plugins call are never listed. Only technicians and administrators "
           "receive the plugins group (plugins_hidden: true for the rest). Read-only.",
           log=False),
    ]
