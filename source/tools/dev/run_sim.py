#!/usr/bin/env python3
"""One command for the development environment of the service page (E2): the real API on this PC and, in front of it, a real DWC 3.6.

    python tools/dev/run_sim.py [--scenario open|users|anonymous|damaged] [--rows N] [--lang es|en] [--dark]
                                [--api-port 18765] [--port 18766] [--build NAME] [--api-only] [--open]

It starts tools/dev/api_server.py and tools/dev/dwc_sim.js, prints the address to open and stops both with Ctrl+C.
`--api-only` leaves the DWC out (tests in node and contract checks need only the API). `--open` opens the browser.
`--build NAME` chooses the compiled DWC of dist/sim/<NAME> (default: dwc). `python tools/dev/sim_build.py [NAME]` makes one (a build of the
page in a free DWC clone; its default name is `work`). A build that is being validated keeps its own name and is not written again.
Two people can run it at the same time on different ports.
Nothing here reaches the machine: both servers listen on 127.0.0.1 and the API process cannot connect anywhere else.
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def wait_for(url, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as f:
                if f.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="users", choices=["open", "users", "anonymous", "damaged"])
    ap.add_argument("--rows", type=int, default=120)
    ap.add_argument("--lang", default="es", choices=["es", "en"])
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--api-port", type=int, default=18765)
    ap.add_argument("--port", type=int, default=18766)
    ap.add_argument("--build", default="dwc", help="the compiled DWC to serve: dist/sim/<name>")
    ap.add_argument("--api-only", action="store_true")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args(argv)

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    api = "http://127.0.0.1:%d" % args.api_port
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "api_server.py"), "--port", str(args.api_port), "--scenario", args.scenario, "--rows", str(args.rows)], env=env)]
    try:
        if not wait_for(api + "/__dev/state"):
            print("run_sim: the API server did not start on " + api, file=sys.stderr)
            return 1
        print("run_sim: API  %s/machine/WorkshopService/api   control %s/__dev/state" % (api, api), flush=True)
        if not args.api_only:
            cmd = ["node", os.path.join(HERE, "dwc_sim.js"), "--api", api, "--port", str(args.port), "--lang", args.lang, "--dwc", "dist/sim/" + args.build] + (["--dark"] if args.dark else [])
            procs.append(subprocess.Popen(cmd, env=env))
            page = "http://127.0.0.1:%d/Plugins/WorkshopService" % args.port
            if not wait_for("http://127.0.0.1:%d/__sim/state" % args.port):
                print("run_sim: the DWC simulator did not start (is dist/sim/%s there? python tools/dev/sim_build.py %s)" % (args.build, args.build), file=sys.stderr)
                return 1
            print("run_sim: page " + page, flush=True)
            if args.open:
                webbrowser.open(page)
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
