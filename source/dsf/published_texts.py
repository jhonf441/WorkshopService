"""The messages the service publishes on its own (plugin data, process details, camera relay answers), which the pages
translate themselves.

The service publishes a message as {"key", "params"} (messages.data()); every page shows it in the language of its
own DWC, so two viewers with different languages each read their own. For that the pages need the templates of those
keys: they keep a copy in the area "svc" of their catalogs:

    WorkshopService/dwc-src/i18n/{es,en}.json                     the service page (written by this module)
    TallerPlugins/src/_shared/i18n/{es,en}.json, vue/_shared/...  the other plugins (TallerPlugins tools/sync_service_texts.py
                                                                  copies the area from the service page)

The keys are every catalog key written as a string in the modules below (the modules that publish data or feed the
process details). The templates lose their format specs ("{power_w:.0f}" -> "{power_w}"): data() applies them before
publishing.

    python published_texts.py          rewrite the area "svc" of dwc-src/i18n (after adding or changing a published key)
    python published_texts.py --check  exit 1 if it is out of date (test_published_texts.py does the same)
"""
import json
import os
import re
import sys

import messages

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_I18N = os.path.join(os.path.dirname(HERE), "dwc-src", "i18n")
AREA = "svc"

# modules whose messages reach plugin data or the process details (servicesInternal), or that the pages render
# from an answer of the camera relay
MODULES = [
    "black_box.py", "camera_load.py", "camera_relay.py", "communication.py", "config_guard.py", "consumption_poller.py", "event_watcher.py",
    "health_poller.py", "heartbeats.py", "job_poller.py", "job_trace.py", "jog_move.py", "lights_config.py",
    "lights_runtime.py", "live_job.py", "machine_state.py", "main.py", "motion_owner.py", "motor_poller.py",
    "motor_status.py", "notifier.py", "protection_guard.py", "risk_rules.py", "shutdown_method.py", "shutdown_timer.py", "status_light.py",
    "handlers/lights.py", "handlers/pid_zones.py",
]
_LITERAL = re.compile(r"""["']([a-z0-9_]+)["']""")


def keys():
    """Sorted list of the published keys."""
    cat = messages.catalog("es")
    out = set()
    for m in MODULES:
        with open(os.path.join(HERE, m), encoding="utf-8") as f:
            out |= {k for k in _LITERAL.findall(f.read()) if k in cat}
    return sorted(out)


def page_area(lang):
    """{key: template} of the area "svc" for the pages, in `lang`."""
    cat = messages.catalog(lang)
    return {k: messages.page_template(cat[k]) for k in keys()}


def _path(lang):
    return os.path.join(PAGE_I18N, lang + ".json")


def current(lang):
    with open(_path(lang), encoding="utf-8") as f:
        return json.load(f).get(AREA)


def write():
    for lang in ("es", "en"):
        p = _path(lang)
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        data[AREA] = page_area(lang)
        with open(p, "rb") as f:
            crlf = b"\r\n" in f.read()
        with open(p, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:  # keeps the line endings of the file
            json.dump(data, f, ensure_ascii=False, indent="\t")
            f.write("\n")


if __name__ == "__main__":
    if "--check" in sys.argv:
        bad = [lang for lang in ("es", "en") if current(lang) != page_area(lang)]
        print("out of date: " + ", ".join(bad) if bad else "up to date")
        sys.exit(1 if bad else 0)
    write()
    print("%d keys written to %s" % (len(keys()), PAGE_I18N))
