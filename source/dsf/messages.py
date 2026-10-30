"""Messages of the backend that people read: a key plus its parameters, never a finished sentence.

    import messages
    M = messages.M
    activity.log_event(bridge, "job_start", M("job_started", label="Logo", zone=" (G55)"))

`M(key, **params)` is a `str` (its text in the current language: the request's, or DWC's outside a request, see
machine_language()) that also carries `key` and `params`,
so it can go anywhere a text goes (black box, phone notification, logs, a function that only passes it on) and whoever stores
or shows it can ask for it in another language: `m.text("en")`. The texts live in `i18n/es.json` and `i18n/en.json`, one flat
dictionary per language, in the way DWC's own translations work: the key never changes, the sentence does. A parameter may be
another `M` (it is rendered in the same language) and keeps its number format: `"{power_w:.0f} W"`.

The activity history stores `key` and `params` (columns `message_key`, `message_params`) next to the Spanish text; the page and the
phone ask for the language they need. Plugin data carries data(value): every message as {"key", "params"}, which each page
translates with its own copy of the templates (published_texts.py). A text that is not ours (an error of the firmware, a line typed by a user) is a plain `str`
and is shown as it is.
"""
import contextvars
import json
import os
import re
import unicodedata

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n")
_cat = {}
# language of the request being served ("es" or "en"): a message created while it runs is already in that language.
# The API layer sets it (workshop_api.py). A background thread has none and uses the machine's language (below).
_lang = contextvars.ContextVar("workshop_language", default=None)

# Language of the machine outside a request: DWC's language, which the pages write into global.workshopLanguage (macro
# language.g); without that global, the language of the last API request; without either, Spanish.
_machine = {"global": None, "request": None}


def _norm(lang):
    return "en" if str(lang or "").lower().startswith("en") else "es"


def machine_language():
    """The language for texts made without a request (pop-ups, console messages, photos, phone notices)."""
    return _machine["global"] or _machine["request"] or "es"


def note_machine_global(value):
    """global.workshopLanguage changed (None = deleted)."""
    _machine["global"] = _norm(value) if value else None


def note_request_language(lang):
    """An API request asked for this language (used only while the global does not exist)."""
    _machine["request"] = _norm(lang)


def _on_model_patch(patch, full=False):
    if not isinstance(patch, dict):
        return
    g = patch.get("global")
    if isinstance(g, dict) and "workshopLanguage" in g:
        note_machine_global(g.get("workshopLanguage"))
    elif full or ("global" in patch and g is None):
        note_machine_global(None)


def follow_machine_language():
    """Keep machine_language() up to date from the object model subscription (main.py, once at start)."""
    import machine_state
    try:
        s = machine_state.last_state()
        if s:
            _on_model_patch(s, True)
    except Exception:
        pass
    machine_state.on_change(_on_model_patch)


def current_language():
    """The request's language inside a request (it always wins), else the machine's."""
    return _lang.get() or machine_language()


def set_language(lang):
    """Returns the token for reset_language(). Anything but "en" is Spanish."""
    return _lang.set("en" if str(lang).lower().startswith("en") else "es")


def reset_language(token):
    _lang.reset(token)


def catalog(lang):
    """Flat dictionary key -> template of one language ("es" or "en")."""
    if lang not in _cat:
        try:
            with open(os.path.join(_DIR, lang + ".json"), encoding="utf-8") as f:
                _cat[lang] = json.load(f)
        except (OSError, ValueError):
            _cat[lang] = {}
    return _cat[lang]


def reload():
    _cat.clear()


def render(lang, key, params=None):
    """The text of `key` in `lang`. Without a template in that language it falls back to Spanish, and without that to the key."""
    if key == "_raw":  # B(): a text the caller wrote in both languages
        return params.get(lang) or params.get("es") or ""
    if key == "_join":  # J(): several messages in a row
        sep = params.get("sep")
        return (", " if sep is None else sep).join(x.text(lang) if isinstance(x, Msg) else str(x) for x in params.get("items") or [])
    t = catalog(lang).get(key)
    if t is None:
        t = catalog("es").get(key)
    if t is None:
        return key
    p = {}
    for k, v in (params or {}).items():
        p[k] = v.text(lang) if isinstance(v, Msg) else v
    try:
        return t.format(**p)
    except (KeyError, IndexError, ValueError):
        return t


class Msg(str):
    """Spanish text + key + params. See the module docstring."""

    def __new__(cls, key, params=None):
        obj = str.__new__(cls, render(current_language(), key, params))
        obj.key = key
        obj.params = dict(params or {})
        return obj

    def text(self, lang="es"):
        return render(lang, self.key, self.params)

    def as_dict(self):
        """JSON-able: {"key", "params"} (nested messages keep their own key and params)."""
        return {"key": self.key, "params": {k: _plain(v) for k, v in self.params.items()}}


def _plain(v):
    if isinstance(v, Msg):
        return v.as_dict()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _back(v):
    if isinstance(v, dict):
        return from_dict(v) or v
    if isinstance(v, list):
        return [_back(x) for x in v]
    return v


def M(key, **params):
    return Msg(key, params)


def B(es, en=None):
    """A text that comes already written in Spanish and English (a risk text, for example)."""
    return Msg("_raw", {"es": str(es), "en": str(en if en is not None else es)})


def J(items, sep=", "):
    """Several messages (or texts) joined with `sep`; it is a message too, so it can go inside another."""
    return Msg("_join", {"items": list(items), "sep": sep})


def from_dict(d):
    """Back from `as_dict()` (or from the stored JSON): a Msg, or None if it is not one."""
    if not isinstance(d, dict) or not d.get("key"):
        return None
    return Msg(d["key"], {k: _back(v) for k, v in (d.get("params") or {}).items()})


def dumps_params(m):
    """Parameters of a Msg as the JSON text that the database stores."""
    return json.dumps(m.as_dict()["params"], ensure_ascii=False, separators=(",", ":"), default=str)


def of_row(key, params_json):
    """Msg from the two columns of the database, or None."""
    if not key:
        return None
    try:
        p = json.loads(params_json) if params_json else {}
    except (TypeError, ValueError):
        p = {}
    return from_dict({"key": key, "params": p})


def text_of(key, params_json, lang):
    m = of_row(key, params_json)
    return m.text(lang) if m is not None else None


def localize(obj, lang):
    """The same structure with every message replaced by its text in `lang` (also the ones made at import time, in a table)."""
    if isinstance(obj, Msg):
        return obj.text(lang)
    if isinstance(obj, dict):
        return {k: localize(v, lang) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [localize(v, lang) for v in obj]
    return obj


# ---- published data: the pages translate ----

_SPEC = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:![rsa])?:([^}]+)\}")
_specs_cache = {}


def specs(key):
    """{param: format spec} of the template of `key` ("{power_w:.0f}" -> {"power_w": ".0f"}), from the Spanish catalog."""
    if key not in _specs_cache:
        _specs_cache[key] = {n: s for n, s in _SPEC.findall(catalog("es").get(key) or "")}
    return _specs_cache[key]


def page_template(t):
    """A catalog template as the pages have it: the format specs are applied by the service (data()), so "{x:.0f}" is "{x}"."""
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:![rsa])?(?::[^}]+)?\}", r"{\1}", t)


def _data_msg(m):
    if m.key == "_raw":
        return {"key": "_raw", "params": {"es": str(m.params.get("es") or ""), "en": str(m.params.get("en") or m.params.get("es") or "")}}
    if m.key == "_join":
        sep = m.params.get("sep")
        return {"key": "_join", "params": {"items": [data(x) for x in m.params.get("items") or []], "sep": ", " if sep is None else sep}}
    sp = specs(m.key)
    out = {}
    for k, v in m.params.items():
        if k in sp and isinstance(v, (int, float)) and not isinstance(v, bool):
            try:
                v = format(v, sp[k])
            except (ValueError, TypeError):
                pass
        elif not isinstance(v, (str, int, float, bool, dict, list, tuple)) and v is not None:
            v = str(v)  # an exception, a path...: its text (plugin data must be JSON)
        out[k] = data(v)
    return {"key": m.key, "params": out}


def data(obj):
    """The same structure with every message as {"key", "params"} (nested messages too, numbers already in their format):
    what the service publishes as plugin data, so every page shows it in its own language (the pages keep a copy of the
    published keys, area "svc" of their catalogs). Plain strings stay as they are."""
    if isinstance(obj, Msg):
        return _data_msg(obj)
    if isinstance(obj, dict):
        return {k: data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [data(v) for v in obj]
    return obj


def stored(obj):
    """For a state file: every message as {"key", "params"} with its raw parameters (restored() brings them back)."""
    if isinstance(obj, Msg):
        return obj.as_dict()
    if isinstance(obj, dict):
        return {k: stored(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [stored(v) for v in obj]
    return obj


def restored(obj):
    """Back from stored(): every {"key", "params"} dict (exactly those two fields) is a message again."""
    if isinstance(obj, dict):
        if set(obj) == {"key", "params"} and isinstance(obj.get("key"), str) and isinstance(obj.get("params"), dict):
            m = from_dict(obj)
            if m is not None:
                return m
        return {k: restored(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [restored(v) for v in obj]
    return obj


def in_language(description, key, params_json, lang):
    """The text of a stored row in `lang`: from its key and parameters, else the sentence as it was written."""
    t = text_of(key, params_json, lang)
    return t if t is not None else description


# ---- language of the phone notices ----

def language(config):
    """"en" or "es": the one forced in config["notifications"]["language"], else the machine's (machine_language())."""
    n = (config or {}).get("notifications") or {}
    forced = str(n.get("language") or "").lower()
    if forced in ("en", "es"):
        return forced
    return machine_language()
