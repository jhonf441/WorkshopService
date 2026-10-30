"""Tool offsets and work offsets of Machine v2 (phase 2, design 2.7): `machine.offsets.get` and `machine.offsets.snapshot`.

machine.offsets.get        (operator, read only) the table from the object model: the tool offsets (tools[].offsets, in the order of move.axes) and
                           the nine work offsets G54..G59.3 (move.axes[].workplaceOffsets[]), the system selected now and the last snapshot.
machine.offsets.snapshot   (technician) stores both tables in the calibration history as a record of kind `offsets.snapshot`, compares them with the
                           previous snapshot and returns the differences. A snapshot can be put back with machine.history.restore (the work offsets:
                           it becomes a plan of kind `config.workplaces`).

Persisting is NOT done here: RRF keeps G10 L2 in RAM (the reference says M500 stores them in config-override.g; Machine does not rely on it).
The persistence helper is `machine.config.plan` kind `config.workplaces` (writes a G10 block into `0:/sys/workshop-offsets.g`, called from
config.g, or into the file that already holds the G10 L2 lines) and `config.g10` for tool offsets: both show the diff first and go through
config.commit with a snapshot of the files. Sign convention of the firmware (offsets are SUBTRACTED from the machine position) is kept as the
board reports it.

Table shape (the same in machine.offsets.get and in the record):
    tools    {"<number>": {"name", "offsets": {"X": v, ...}, "probed": ["X", ...]}}
    work     {"<1..9>": {"code": "G54".."G59.3", "offsets": {"X": v, ...}}}
    current  1..9 | null (the work system selected now, 1 = G54)
"""
import identity
import machine_diff
import machine_geometry as geo
import machine_store
from messages import M
from workshop_api import ApiError, Arg, READ, WRITE, Op

WORK_CODES = ("G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3")


def _letters(om):
    return [a.get("letter") if isinstance(a, dict) else None for a in ((om or {}).get("move") or {}).get("axes") or []]


def tool_table(om):
    """{"0": {"name", "offsets": {"X": v}, "probed": []}}: only the axes the model reports for the tool."""
    letters = _letters(om)
    out = {}
    for t in (om or {}).get("tools") or []:
        if not isinstance(t, dict) or not isinstance(t.get("number"), int):
            continue
        offs = t.get("offsets") if isinstance(t.get("offsets"), list) else []
        mask = t.get("offsetsProbed") if isinstance(t.get("offsetsProbed"), int) and not isinstance(t.get("offsetsProbed"), bool) else 0
        out[str(t["number"])] = {
            "name": t.get("name") or "",
            "offsets": {letters[i]: geo.num(v) for i, v in enumerate(offs) if i < len(letters) and letters[i] and geo.num(v) is not None},
            "probed": [letters[i] for i in range(len(letters)) if letters[i] and mask >> i & 1]}
    return out


def work_table(om):
    """{"1": {"code": "G54", "offsets": {"X": v}}, ...}: the nine systems of the visible axes."""
    axes = [a for a in ((om or {}).get("move") or {}).get("axes") or [] if isinstance(a, dict) and a.get("letter") and a.get("visible", True)]
    out = {}
    for n in range(1, 10):
        offs = {}
        for a in axes:
            wo = a.get("workplaceOffsets")
            v = geo.num(wo[n - 1]) if isinstance(wo, list) and len(wo) >= n else None
            if v is not None:
                offs[a["letter"]] = v
        if offs:
            out[str(n)] = {"code": WORK_CODES[n - 1], "offsets": offs}
    return out


def current_system(om, caps):
    wp = (((caps or {}).get("capabilities") or {}).get("workplaces") or {}).get("current")
    if isinstance(wp, int) and not isinstance(wp, bool) and 0 <= wp <= 8:
        return wp + 1
    ms = (((om or {}).get("move") or {}).get("motionSystems") or [None])[0]
    n = ms.get("workplaceNumber") if isinstance(ms, dict) else None
    return n + 1 if isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 8 else None


def snapshot_data(om, caps):
    return {"tools": tool_table(om), "work": work_table(om), "current": current_system(om, caps)}


def workplaces_values(work):
    """The `values` of a config.workplaces plan from a work table (the snapshot's, or the live one)."""
    return {"systems": {n: dict(row["offsets"] if "offsets" in row else row) for n, row in work.items()}, "target": "macro"}


def _last_snapshot():
    got, _ = machine_store.query(kind="offsets.snapshot", limit=1)
    return got[0] if got else None


def _mo():
    import machine_ops
    return machine_ops


def _get(args, ctx):
    mo = _mo()
    om, caps = mo.model(), mo._caps()
    prev = _last_snapshot()
    return dict(snapshot_data(om, caps), axes=[l for l in _letters(om) if l],
                last_snapshot={"id": prev["id"], "ts": prev["ts"], "user": prev["user"]} if prev else None)


def _snapshot(args, ctx):
    mo = _mo()
    om, caps = mo.model(), mo._caps()
    if not om:
        raise ApiError("refused", M("machine_offsets_no_model"), reason="no_model")
    data = snapshot_data(om, caps)
    if not data["tools"] and not data["work"]:
        raise ApiError("refused", M("machine_offsets_nothing"), reason="nothing_to_store")
    prev = _last_snapshot()
    who = identity.actor(ctx)
    try:
        rec = machine_store.make_record("offsets.snapshot", who, machine=machine_store.fingerprint_of(caps), inputs={}, results=data,
                                        notes=str(args.get("note") or ""), state="done")
        stored = machine_store.append(rec)
    except machine_store.StoreError as e:
        raise ApiError("failed", M("machine_offsets_store_failed", reason=e.code))
    diff = machine_diff.diff_rows(prev["results"], data) if prev else None
    return dict(data, record_id=stored["id"], previous={"id": prev["id"], "ts": prev["ts"], "user": prev["user"]} if prev else None,
                changed=diff["changed"] if diff else None, diff=[r for r in diff["rows"] if r["changed"]] if diff else None)


def ops():
    a = Arg
    return [
        Op("machine.offsets.get", _get, READ, {},
           "The tool offsets (per tool, per axis, and which were probed) and the nine work offsets G54..G59.3 from the object model, the work "
           "system selected now and the last snapshot stored.", log=False),
        Op("machine.offsets.snapshot", _snapshot, WRITE, {"note": a("str", desc="Free note up to 500 characters.")},
           "Stores the tool and work offset tables in the calibration history (kind offsets.snapshot) and returns the differences with the "
           "previous snapshot. Persisting offsets in a file is machine.config.plan kind config.workplaces / config.g10."),
    ]
