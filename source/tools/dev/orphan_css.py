#!/usr/bin/env python3
"""Lists the CSS rules of the service page (dwc36: styles/*.css and the <style> blocks of the .vue files) whose classes are never written anywhere in the code.

    python tools/dev/orphan_css.py [--bytes]       the orphan selectors, biggest first

A class counts as used when its name appears in a .vue / .js file of dwc36 (a template, a computed class, a string built from it). A rule is orphan when EVERY class of EVERY selector of
its list is unused. It is a lead, not a verdict: a class built from pieces ('sv-' + kind) is not seen, so read before deleting.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "dwc36")


def files(ext):
    for d, _, names in os.walk(SRC):
        if os.sep + "i18n" in d:
            continue
        for n in names:
            if n.endswith(ext):
                yield os.path.join(d, n)


def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def main(argv):
    code = "\n".join(read(p) for p in list(files(".vue")) + list(files(".js")))
    blocks = []
    for p in files(".css"):
        blocks.append((os.path.relpath(p, SRC), read(p)))
    for p in files(".vue"):
        t = read(p)
        for m in re.finditer(r"<style[^>]*>(.*?)</style>", t, re.S):
            blocks.append((os.path.relpath(p, SRC), m.group(1)))
    out = []
    for name, css in blocks:
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
            sel, body = m.group(1).strip(), m.group(2)
            classes = re.findall(r"\.(-?[a-zA-Z_][\w-]*)", sel)
            if not classes:
                continue
            # a rule is orphan when every selector of its list names at least one unused class
            lists = [s for s in sel.split(",") if s.strip()]
            dead = 0
            for s in lists:
                cs = re.findall(r"\.(-?[a-zA-Z_][\w-]*)", s)
                if cs and any(c not in code for c in cs if not re.match(r"^(v-|mdi|theme--|sv-vh$)", c)):
                    dead += 1
            if dead == len(lists):
                out.append((len(sel) + len(body) + 2, name, " ".join(sel.split())[:110]))
    out.sort(reverse=True)
    total = sum(o[0] for o in out)
    for size, name, sel in out[:200]:
        print("%5d  %-34s %s" % (size, name, sel))
    print("-- %d orphan rules, about %d bytes of source" % (len(out), total))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
