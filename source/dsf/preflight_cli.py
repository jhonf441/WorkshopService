"""Command line of the pre-installation check (python3 -m / tools/preflight.py / tools/install.sh).

Lives in dsf/ so that it travels inside the plugin zip: tools/install.sh can run the check with only the zip.
Uses only the standard library and the files next to it (preflight.py, messages.py, paths.py, i18n/).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import messages  # noqa: E402
import preflight  # noqa: E402

LABEL = {"ok": "preflight_status_ok", "warn": "preflight_status_warn", "error": "preflight_status_error"}


def build_options(args):
    opts = preflight.options_from_machine()
    if args.manifest:
        with open(args.manifest, encoding="utf-8") as f:
            opts["python_dependencies"] = preflight.manifest_dependencies(f.read())
    if args.features is not None:
        opts["features"] = [x for x in args.features.split(",") if x]
    if args.shutdown:
        opts["shutdown_method"] = args.shutdown
    if args.meter:
        opts["meter_kind"] = args.meter
    return opts


def render(result, lang):
    fix_label = messages.render(lang, "preflight_fix_label")
    lines = []
    for it in result["items"]:
        lines.append("[%s] %s" % (messages.render(lang, LABEL[it["status"]]), it["message"]))
        if it["fix_key"]:
            lines.append("      %s: %s" % (fix_label, it["fix"]))
    s = result["summary"]
    key = "preflight_result_ok" if result["ok"] else "preflight_result_blocked"
    lines.append(messages.render(lang, key, s))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pre-installation check of WorkshopService")
    ap.add_argument("--lang", default="en", choices=("es", "en"))
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--features", help="comma list of optional features to check: camera, vision")
    ap.add_argument("--manifest", help="plugin.json whose sbcPythonDependencies are checked")
    ap.add_argument("--shutdown", choices=("none", "software", "relay", "tuya"))
    ap.add_argument("--meter")
    args = ap.parse_args(argv)
    messages.set_language(args.lang)
    result = preflight.run(options=build_options(args))
    if args.json:
        out = dict(result, items=[dict(i, message=str(i["message"]), fix=str(i["fix"]) if i["fix"] else None) for i in result["items"]])
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(render(result, args.lang))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
