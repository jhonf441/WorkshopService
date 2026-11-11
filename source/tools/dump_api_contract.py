"""Snapshot of the API contract of the service: dsf/golden/api_contract.json (compared by dsf/test_api_contract.py).

What it records: every operation of the registry (arguments, class, confirmation, motion class, macro flag, role, capability),
the operations a macro may call, the HTTP status table of the error codes plus every code the code raises, and the keys of
`plugin data` that plugin.json declares (with their defaults).

    python tools/dump_api_contract.py            writes dsf/golden/api_contract.json
    python tools/dump_api_contract.py --stdout   prints it instead

A difference in the test is a change of the contract the 14 plugins depend on: regenerate this file only when the change is
intended (and tell the plugin owners). The registry is built with no files, no connection and no secrets (api_ops.init with every
path off); dsf-python is replaced by an empty stub only inside this script when it is not installed.
"""
import ast
import enum
import json
import os
import sys
import tempfile
import types

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSF = os.path.join(ROOT, "dsf")
OUT = os.path.join(DSF, "golden", "api_contract.json")


def _stub_dsf_python():
    """dsf-python (module `dsf`) is not on a development PC: the registry only needs the names to import."""
    try:
        import dsf.connections  # noqa: F401
        return
    except ImportError:
        pass

    class _Chan(enum.Enum):
        HTTP = "HTTP"
        SBC = "SBC"
        Aux = "Aux"
        Aux2 = "Aux2"

    pkg = types.ModuleType("dsf")
    pkg.__path__ = []
    conns = types.ModuleType("dsf.connections")
    conns.CommandConnection = object
    cmds = types.ModuleType("dsf.commands")
    cc = types.ModuleType("dsf.commands.code_channel")
    cc.CodeChannel = _Chan
    sys.modules.update({"dsf": pkg, "dsf.connections": conns, "dsf.commands": cmds, "dsf.commands.code_channel": cc})
    sys.modules.setdefault("tinytuya", types.ModuleType("tinytuya"))


def _raised_codes():
    """Every literal code of an ApiError(...) in the production code of dsf/ and dsf/handlers/."""
    found = set()
    for folder in (DSF, os.path.join(DSF, "handlers")):
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    f = n.func
                    if (isinstance(f, ast.Name) and f.id == "ApiError") or (isinstance(f, ast.Attribute) and f.attr == "ApiError"):
                        found.add(n.args[0].value)
    return sorted(found)


def build_contract():
    _stub_dsf_python()
    tmp = tempfile.mkdtemp(prefix="api-contract-")
    os.environ["WORKSHOP_DB"] = os.path.join(tmp, "duet.db")
    sys.path.insert(0, DSF)
    import api_ops
    import permission_caps
    import permissions
    import workshop_api as wa

    bridge = types.SimpleNamespace(set_status=lambda *a, **k: None)
    reg = api_ops.init(bridge, {}, "WorkshopService", token_file=None, keys_file=None, users_file=None)
    ops = {}
    for name in sorted(reg.ops):
        op = reg.ops[name]
        d = op.describe()
        d.pop("op", None)
        d["exclusive"] = bool(op.exclusive)
        d["log"] = bool(op.log)
        d["role"] = permissions.required_role(name)
        d["capability"] = permission_caps.capability_of(name)
        ops[name] = d
    raised = _raised_codes()
    with open(os.path.join(ROOT, "plugin.json"), encoding="utf-8") as f:
        data = json.load(f)["data"]
    return {
        "api_version": wa.API_VERSION,
        "ops": ops,
        "macro_ops": sorted(n for n, o in reg.ops.items() if o.macro),
        "confirm_texts": sorted(api_ops.CONFIRM_TEXTS),
        "error_codes": {
            "status": dict(sorted(wa.ApiError.STATUS.items())),
            "raised": raised,
            "raised_without_status": [c for c in raised if c not in wa.ApiError.STATUS],
        },
        "plugin_data": dict(sorted(data.items())),
    }


def to_text(contract):
    return json.dumps(contract, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv):
    text = to_text(build_contract())
    if "--stdout" in argv:
        sys.stdout.write(text)
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote %s (%d bytes)" % (OUT, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
