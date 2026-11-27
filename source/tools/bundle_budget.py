#!/usr/bin/env python3
"""Weight budget of the compiled service page (dwc/css/*.css and dwc/js/*.js of the release zip, .gz / .map not counted).

    python tools/bundle_budget.py <zip> [<zip> ...]      measure and compare with tools/bundle-budget.json; exit 1 over budget

The numbers live ONLY in tools/bundle-budget.json. tools/build_release.py runs this check on every release zip it checks, and
tests/bundle-budget.test.js runs it on the newest compiled zip of the current version (it skips when there is none).
Raising a number is a project decision (docs/BUNDLE-BUDGET.md), never a way to make a build pass.
"""
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUDGET = os.path.join(HERE, "bundle-budget.json")


def load_budget():
    with open(BUDGET, encoding="utf-8") as f:
        return json.load(f)


def measure(path):
    """(css_bytes, js_bytes) of the page files of one zip."""
    css = js = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            n = info.filename
            if n.endswith((".gz", ".map")):
                continue
            if n.startswith("dwc/css/") and n.endswith(".css"):
                css += info.file_size
            elif n.startswith("dwc/js/") and n.endswith(".js"):
                js += info.file_size
    return css, js


def problems(path):
    """Messages for a zip over budget (empty list = within budget)."""
    b = load_budget()
    css, js = measure(path)
    out = []
    if css > b["css_bytes"]:
        out.append("page CSS is %d B, the budget is %d B (+%d)" % (css, b["css_bytes"], css - b["css_bytes"]))
    if js > b["js_bytes"]:
        out.append("page JS is %d B, the budget is %d B (+%d)" % (js, b["js_bytes"], js - b["js_bytes"]))
    if out:
        out.append("remove weight instead of raising tools/bundle-budget.json (raising it is a project decision: docs/BUNDLE-BUDGET.md)")
    return out


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    bad = 0
    b = load_budget()
    for p in argv:
        css, js = measure(p)
        found = problems(p)
        print("%s  css %d / %d B, js %d / %d B  %s" % (os.path.basename(p), css, b["css_bytes"], js, b["js_bytes"], "ok" if not found else "OVER BUDGET"))
        for m in found:
            print("  " + m)
        bad += bool(found)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
