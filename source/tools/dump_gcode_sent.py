"""Writes dsf/golden/gcode_sent.json: the G/M/T codes that the plugin pages put in front of DWC (a lower bound, found by string literals).
Run: PYTHONDONTWRITEBYTECODE=1 python -I tools/dump_gcode_sent.py <path of TallerPlugins> [--out dsf/golden/gcode_sent.json]
Same method as Projects/informes/control-acceso/tools/gcode_sent.py: in every .js/.vue file of a plugin that mentions sendCode / postCode /
postJogCommand / machine/code, each string literal that STARTS with a G, M or T code counts (M569.2 keeps its sub-number), except the SVG paths of icons (is_svg_path). Read only
on TallerPlugins; it only writes the golden file."""
import json
import os
import re
import sys

PLUGINS = {
    "Workbench": ["src/WorkshopWorkbench", "src/_camera_client", "src/_workbench_base", "src/_workbench_cut", "src/_zones"],
    "Camera": ["src/WorkshopCamera", "src/_camera_client"],
    "ControlBar": ["src/WorkshopControlBar"],
    "Jog": ["src/WorkshopJog", "src/_workbench_base"],
    "Vision": ["src/WorkshopVision", "src/_camera_client"],
    "Translations": ["src/WorkshopTranslations"],
    "Machine": ["vue/WorkshopMachine/dwc36"], "Motors": ["vue/WorkshopMotors/dwc36"], "Activity": ["vue/WorkshopActivity/dwc36"],
    "Printing": ["vue/WorkshopPrinting/dwc36"], "Power": ["vue/WorkshopPower/dwc36"], "PiHealth": ["vue/WorkshopPiHealth/dwc36"],
    "Model": ["vue/WorkshopModel/dwc36"], "Lights": ["vue/WorkshopLights/dwc36"],
    "RS485": ["vue/WorkshopRS485/dwc36", "vue/WorkshopRS485/dsf"],
    "ModelAgent": ["vue/WorkshopModelAgent/dwc36"], "Config": ["vue/WorkshopConfig/dwc-src"],
}
EXCL = {"node_modules", "dist", "test", "tests", "__pycache__", "i18n", "releases"}
SEND = re.compile(r"\b(sendCode|postCode|postJogCommand|machine/code)\b")
LIT = re.compile(r"""(['"`])\s*((?:[GMT]\d+(?:\.\d+)?)(?:[^'"`\n]*))\1""")
CODE = re.compile(r"^([GMT])(\d+(?:\.\d+)?)")
# An SVG path of an icon ("M12 22c1.1 0 2-.9 2-2h-4...") also starts with M and a number. Its shape: no quote, no "/" and no "{" (a G-code
# literal with a macro path or an expression has them) and lowercase path commands glued to a number (c1.1, h-4, l4.59) or number,number pairs.
SVG_COMMAND = re.compile(r"[chlvastqz]-?\.?\d")
SVG_PAIR = re.compile(r"\d,-?\.?\d")


def is_svg_path(lit):
    if any(ch in lit for ch in '"/{'):
        return False
    return bool(SVG_COMMAND.search(lit) or SVG_PAIR.search(lit))


def _files(base, roots):
    for r in roots:
        for d, ds, fs in os.walk(os.path.join(base, r)):
            ds[:] = [x for x in ds if x not in EXCL]
            for f in fs:
                if f.endswith((".js", ".vue")):
                    yield os.path.join(d, f)


def scan(base):
    res = {}
    for pid, roots in PLUGINS.items():
        codes = set()
        for f in _files(base, roots):
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if not SEND.search(text):
                continue
            for line in text.splitlines():
                if line.strip().startswith(("//", "*", "<!--")):
                    continue
                for m in LIT.finditer(line):
                    c = CODE.match(m.group(2))
                    if c and not is_svg_path(m.group(2)):
                        codes.add(c.group(1) + c.group(2))
        res[pid] = sorted(codes, key=lambda k: (k[0], float(k[1:])))
    return res


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dsf", "golden", "gcode_sent.json")
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    res = {k: v for k, v in scan(argv[0]).items() if v}
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps({"codes": res}, indent=1, sort_keys=True) + "\n")
    print("%d plugins, %d distinct codes -> %s" % (len(res), len({c for v in res.values() for c in v}), out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
