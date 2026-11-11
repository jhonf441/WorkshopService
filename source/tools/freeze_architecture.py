"""Writes dsf/golden/architecture_frozen.json from the code (see dsf/test_architecture.py).

    python tools/freeze_architecture.py            lowers the frozen lists to what the code has now; refuses if anything is new or higher
    python tools/freeze_architecture.py --init     writes whatever the code has (first freeze only: it is how the debt gets fixed)
    python tools/freeze_architecture.py --check    prints the numbers and writes nothing
"""
import json
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dsf"))

import test_architecture as ta  # noqa: E402


def main(argv):
    now = ta.measure()
    if "--check" in argv:
        for rule in ta.RULES:
            print("%-16s %4d entries, total %d" % (rule, len(now[rule]), sum(now[rule].values())))
        return 0
    if "--init" not in argv:
        frozen = ta.load_frozen()
        bad = []
        for rule in ta.RULES:
            grown, _ = ta.compare(rule, now[rule], frozen[rule])
            bad += ["%s: %s" % (rule, g) for g in grown]
        if bad:
            print("refusing to freeze new debt:\n  " + "\n  ".join(bad[:30]))
            return 1
    data = {rule: dict(sorted(now[rule].items())) for rule in ta.RULES}
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    with open(ta.FROZEN_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for rule in ta.RULES:
        print("%-16s %4d entries, total %d" % (rule, len(now[rule]), sum(now[rule].values())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
