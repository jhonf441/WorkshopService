"""
api_docs -- the texts of the API reference (what each operation does and what each argument is) in the language of the person who asks.

The code keeps the English text of every operation and argument (Op.desc, Arg.desc: it is the contract). The Spanish ones live in i18n/api_docs.es.json
(keys `op.<operation>` and `op.<operation>.arg.<argument>`); i18n/api_docs.en.json is the English twin that the coverage test keeps equal to the code.
api.describe asked in a language answers the texts of that language and falls back to the English of the code for a key that is missing; asked with no
language it answers as it always did. No imports of the service: it is a leaf.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_cache = {}


def catalog(lang):
    """{key: text} of a language ({} when there is no catalog for it or it cannot be read: the English of the code is then used)."""
    if lang not in _cache:
        try:
            with open(os.path.join(HERE, "i18n", "api_docs.%s.json" % lang), encoding="utf-8") as f:
                _cache[lang] = json.load(f)
        except (OSError, ValueError):
            _cache[lang] = {}
    return _cache[lang]


def describe_in(registry, lang, reads=None):
    """registry.describe() with the texts of `lang` (the registry is passed in: this module imports nothing of the service). With `reads` (a function of
    an Op), every operation says `reads`: true when it only reads, so the screen does not guess it from the class (an ADMIN operation can only read)."""
    d = registry.describe()
    d["ops"] = [localize(o, lang) for o in d["ops"]]
    if reads is not None:
        for o in d["ops"]:
            o["reads"] = bool(reads(registry.ops.get(o["op"])))
    return d


def make_op(registry, Op, Arg, READ, reads=None):
    """The service's api.describe: it answers in the language of the request (the Op class and the READ kind are passed in: this module is a leaf)."""
    # the language is an ARGUMENT, not the "lang" of the request (every page sends that one): who asks for no language gets the English of the code, as always
    return Op("api.describe", lambda a, c: describe_in(registry, a.get("lang"), reads), READ, {"lang": Arg("str", desc="Language of the texts (es or en); without it the English of the code.")}, desc="All operations with their arguments", log=False)


def localize(op, lang):
    """The description of one operation (Op.describe()) with the texts of `lang`; a key without text keeps its English. Returns a new dict."""
    cat = catalog(lang) if lang and lang != "en" else {}
    if not cat:
        return op
    name = op["op"]
    out = dict(op)
    out["desc"] = cat.get("op." + name) or op.get("desc", "")
    args = {}
    for k, a in (op.get("args") or {}).items():
        a = dict(a)
        text = cat.get("op.%s.arg.%s" % (name, k))
        if text:
            a["desc"] = text
        args[k] = a
    out["args"] = args
    return out
