#!/usr/bin/env python3
"""Estimates the CSS weight of the page without a build: the bytes of CSS source of dwc36 (styles/*.css and the <style> blocks of the .vue files), whitespace squeezed.

    python tools/dev/css_size.py [rev]        rev = a git revision to measure instead of the working tree (e.g. master)

The compiled bundle is about the same as this number; compare two revisions and apply the difference to the last measured bundle (105 135 B at 2.52.5, budget 106 062 B).
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def squeeze(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    return re.sub(r"\s*([{};:,>])\s*", r"\1", css)


def sources(rev):
    if rev:
        names = subprocess.run(["git", "-C", ROOT, "ls-tree", "-r", "--name-only", rev, "dwc36"], capture_output=True, text=True).stdout.split()
        get = lambda n: subprocess.run(["git", "-C", ROOT, "show", rev + ":" + n], capture_output=True).stdout.decode("utf-8", "replace")
    else:
        names = []
        for d, _, fs in os.walk(os.path.join(ROOT, "dwc36")):
            for f in fs:
                names.append(os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/"))
        get = lambda n: open(os.path.join(ROOT, n), encoding="utf-8", errors="replace").read()
    for n in names:
        if "/i18n/" in n or n.endswith("family.css") and False:
            continue
        if n.endswith(".css"):
            yield n, get(n)
        elif n.endswith(".vue"):
            for m in re.finditer(r"<style[^>]*>(.*?)</style>", get(n), re.S):
                yield n, m.group(1)


def main(argv):
    total = 0
    for _, css in sources(argv[0] if argv else None):
        total += len(squeeze(css))
    print(total)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
