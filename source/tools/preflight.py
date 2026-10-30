#!/usr/bin/env python3
"""Pre-installation check for WorkshopService on a Duet 3 + Raspberry Pi (run it ON the Pi).

    python3 tools/preflight.py [--lang es|en] [--json] [--features camera,vision]
                               [--manifest plugin.json] [--shutdown relay|software|tuya|none] [--meter tuya|none]

Each check prints OK, WARNING or ERROR with the solution in words. Exit code 0 when there
is no ERROR, 1 otherwise. WORKSHOP_DSF_ROOT replaces /opt/dsf. It uses only the standard library
and the dsf/ folder next to this script (or the one installed in the plugin); the logic is in dsf/preflight_cli.py.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "dsf"), os.path.join(HERE, "dsf"), HERE):
    if os.path.isfile(os.path.join(cand, "preflight_cli.py")):
        sys.path.insert(0, os.path.abspath(cand))
        break

import preflight_cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(preflight_cli.main())
