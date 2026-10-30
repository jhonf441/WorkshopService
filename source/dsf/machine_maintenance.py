"""The maintenance plan of Machine v2 (phase 4, design 2.10): items with an interval, due markers, "done", notifications.

The plan lives in the machine profile (`machine.maintenance`, validated by machine_profile). The counters live in the store
`machine-maintenance` (machine_odometer.py / machine_maint_poller.py). While the owner has not edited the plan and the profile list is
empty, the generic DEFAULT_ITEMS are the plan; `machine.maintenance.plan.set` writes the owner's list into the profile (an explicitly empty
list is allowed: then the plan is really empty) and remembers it in the store (`plan_custom`).

    interval    every_hours (power-on hours, or moving hours with hours_basis "moving"), every_km (ESTIMATED distance) or every_days
    source      the counters of the item's axis, or of the whole board when the axis is null (its distance is the sum over the axes)
    used        what the source counted since the last "done" (the counters at that moment are stored as `base`); days count from the last
                done, or from the first start of the counters when it was never done
    status      ok < due_soon (ratio from 0.9) < due (1.0) < overdue (1.25): guesses, tune with use

Operations: machine.maintenance.get (operator), machine.maintenance.done (technician), machine.maintenance.plan.set (technician: it only
changes reminders; nothing here moves the machine or writes a file of the board).
"""
import copy
import threading
import time

import machine_profile
import machine_store
from messages import M
from workshop_api import ApiError, Arg, READ, WRITE, Op

DUE_SOON, DUE, OVERDUE = 0.9, 1.0, 1.25
STATUSES = ("ok", "due_soon", "due", "overdue")
RANK = {s: i for i, s in enumerate(STATUSES)}
UNITS = {"every_hours": "hours", "every_km": "km", "every_days": "days"}
DEFAULT_ITEMS = (
    {"id": "z_screws", "label": "", "axis": "Z", "every_hours": 100},
    {"id": "belts", "label": "", "axis": None, "every_hours": 200, "hours_basis": "moving"},
    {"id": "lens", "label": "", "axis": None, "every_days": 30},
    {"id": "z_couplers", "label": "", "axis": "Z", "every_days": 180},
)
DEFAULT_IDS = tuple(i["id"] for i in DEFAULT_ITEMS)
_plan_lock = threading.Lock()
_hooks = {"now": None, "notify": None}


def now():
    return _hooks["now"]() if _hooks["now"] else time.time()


# ---- the plan and the counters (pure) ----

def effective_plan(machine_block, custom):
    """The list of items: the profile's, or the defaults while the profile list is empty and the owner never edited the plan."""
    items = list((machine_block or {}).get("maintenance") or [])
    if items or custom:
        return items
    return copy.deepcopy(list(DEFAULT_ITEMS))


def interval_of(item):
    key = next(k for k in UNITS if k in item)
    basis = (item.get("hours_basis") or "power_on") if key == "every_hours" else None
    return {"unit": UNITS[key], "value": item[key], "basis": basis}


def source_of(item, counters):
    """{power_on_s, moving_s, distance_mm} of the axis (zeros when nothing was counted yet) or of the whole board."""
    src = (counters.get("board") or {}) if item.get("axis") is None else ((counters.get("axes") or {}).get(item["axis"]) or {})
    return {k: float(src.get(k) or 0.0) for k in ("power_on_s", "moving_s", "distance_mm")}


def used_of(item, counters, done, at):
    """What the item has used since its last done, in the unit of its interval."""
    iv = interval_of(item)
    if iv["unit"] == "days":
        start = next((v for v in ((done or {}).get("ts"), counters.get("since")) if v is not None), at)
        return max(0.0, (at - start) / 86400.0)
    now_v, base = source_of(item, counters), (done or {}).get("base") or {}
    if iv["unit"] == "hours":
        key = "moving_s" if iv["basis"] == "moving" else "power_on_s"
        return max(0.0, (now_v[key] - float(base.get(key) or 0.0)) / 3600.0)
    return max(0.0, (now_v["distance_mm"] - float(base.get("distance_mm") or 0.0)) / 1e6)


def status_of(ratio):
    if ratio >= OVERDUE:
        return "overdue"
    if ratio >= DUE:
        return "due"
    return "due_soon" if ratio >= DUE_SOON else "ok"


def item_view(item, counters, done, at):
    iv = interval_of(item)
    used = used_of(item, counters, done, at)
    ratio = used / iv["value"]
    custom = (item.get("label") or "").strip()
    return {"id": item["id"], "label": custom, "label_key": None if custom or item["id"] not in DEFAULT_IDS else "machine_maint_item_" + item["id"],
            "axis": item.get("axis"), "interval": iv, "used": round(used, 3), "remaining": round(iv["value"] - used, 3), "ratio": round(ratio, 4),
            "status": status_of(ratio),
            "last_done": {k: done.get(k) for k in ("ts", "user", "role")} if done else None}


def counters_view(counters, running):
    c = counters or {}
    board = c.get("board") or {}

    def row(src):
        return {"power_on_h": round(float(src.get("power_on_s") or 0) / 3600.0, 3), "moving_h": round(float(src.get("moving_s") or 0) / 3600.0, 3),
                "distance_m": round(float(src.get("distance_mm") or 0) / 1000.0, 3)}

    return {"running": bool(running), "estimated": True, "since": c.get("since"), "updated": c.get("updated"), "gaps": int(c.get("gaps") or 0),
            "jumps": int(c.get("jumps") or 0), "board": row(board), "axes": {k: row(v) for k, v in sorted((c.get("axes") or {}).items())},
            "crosscheck": c.get("crosscheck")}


def evaluate(machine_block, store, at):
    """The whole answer of machine.maintenance.get from a profile block and the store value (pure)."""
    counters, done = store.get("counters") or {}, store.get("done") or {}
    items = [item_view(i, counters, done.get(i["id"]), at) for i in effective_plan(machine_block, store.get("plan_custom"))]
    count = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    worst = max((i["status"] for i in items), key=RANK.get, default="ok")
    custom = bool(store.get("plan_custom")) or bool((machine_block or {}).get("maintenance"))
    return {"schema": 1, "generated_at": int(at), "items": items, "custom": custom,
            "notify": {"enabled": bool((store.get("notify") or {}).get("enabled"))},
            "summary": {"worst": worst, "due_soon": count["due_soon"], "due": count["due"], "overdue": count["overdue"]}}


# ---- reading ----

def _block():
    try:
        return machine_profile.load().get("machine") or machine_profile.default_machine()
    except Exception:  # noqa: BLE001
        return machine_profile.default_machine()


def _running():
    try:
        import machine_maint_poller
        return machine_maint_poller.running()
    except Exception:  # noqa: BLE001
        return False


def current():
    """The answer of machine.maintenance.get."""
    store = machine_store.maintenance()
    out = evaluate(_block(), store, now())
    out["counters"] = counters_view(store.get("counters"), _running())
    return out


def light():
    """The traffic light of the overview: {"worst", "due_soon", "due", "overdue"} (no counters, no names)."""
    try:
        return evaluate(_block(), machine_store.maintenance(), now())["summary"]
    except machine_store.StoreError:
        return None


# ---- notifications ----

def _label_text(view):
    return view["label"] if view["label"] else M(view["label_key"] or "machine_maint_item_unknown")


def notice_for(view):
    """The message of an item that is due or overdue (an M: the phone and the history render it in their language)."""
    key = "machine_maint_overdue" if view["status"] == "overdue" else "machine_maint_due"
    iv = view["interval"]
    return M(key, label=_label_text(view), used=view["used"], every=iv["value"], unit=M("machine_maint_unit_" + iv["unit"]))


def pending_notices(evaluated, store):
    """[(item view, level)] to notify now: due / overdue and above the level already notified in this cycle (pure)."""
    done, seen = store.get("done") or {}, store.get("notified") or {}
    out = []
    for v in evaluated["items"]:
        if v["status"] not in ("due", "overdue"):
            continue
        epoch = (done.get(v["id"]) or {}).get("ts") or 0
        last = seen.get(v["id"]) or {}
        if last.get("epoch") == epoch and RANK.get(last.get("level"), 0) >= RANK[v["status"]]:
            continue
        out.append((v, v["status"]))
    return out


def check_notifications(bridge=None):
    """Sends one notice for each item that became due (or overdue) since the last check, if the owner opted in. Returns the item ids."""
    store = machine_store.maintenance()
    if not (store.get("notify") or {}).get("enabled"):
        return []
    todo = pending_notices(evaluate(_block(), store, now()), store)
    sent = []
    for view, level in todo:
        epoch = ((store.get("done") or {}).get(view["id"]) or {}).get("ts") or 0
        _notify(bridge, notice_for(view))
        machine_store.update_maintenance(lambda v, i=view["id"], lv=level, ep=epoch: dict(
            v, notified=dict(v.get("notified") or {}, **{i: {"level": lv, "epoch": ep}})))
        sent.append(view["id"])
    return sent


def _notify(bridge, message):
    if _hooks["notify"]:
        return _hooks["notify"](message)
    import activity
    activity.log_event(bridge, "maintenance", message)


# ---- operations ----

def _bridge():
    import api_ops
    return api_ops._ctx["bridge"]


def _get(args, ctx):
    return current()


def _done(args, ctx):
    import identity
    store = machine_store.maintenance()
    item = next((i for i in effective_plan(_block(), store.get("plan_custom")) if i["id"] == args["id"]), None)
    if item is None:
        raise ApiError("invalid_args", M("machine_maint_unknown_item", id=args["id"]), field="id")
    at = now()
    base = source_of(item, store.get("counters") or {})
    entry = machine_store.maintenance_done(item["id"], identity.actor(ctx), now=at, base=base, note=str(args.get("note") or ""))
    after = machine_store.maintenance()
    view = item_view(item, after.get("counters") or {}, after["done"].get(item["id"]), at)
    return {"id": item["id"], "done": {k: entry.get(k) for k in ("ts", "user", "role")}, "item": view}


def _validated(items):
    profile = machine_profile.load()
    profile["machine"] = dict(profile.get("machine") or machine_profile.default_machine(), maintenance=items)
    try:
        return machine_profile.save(profile)
    except machine_profile.ProfileError as e:
        raise ApiError("invalid_args", str(e.errors[0]["message"]), field=e.errors[0]["field"],
                       errors=[{"field": x["field"], "message": str(x["message"])} for x in e.errors])


def _plan_set(args, ctx):
    items, notify, defaults = args.get("items"), args.get("notify"), bool(args.get("defaults"))
    if items is None and notify is None and not defaults:
        raise ApiError("invalid_args", M("machine_maint_plan_nothing"), field="items")
    if items is not None and defaults:
        raise ApiError("invalid_args", M("machine_maint_plan_both"), field="defaults")
    with _plan_lock:
        if defaults:
            _validated([])
            custom = False
        elif items is not None:
            _validated(items)
            custom = True
        else:
            custom = None

        def change(v):
            out = dict(v)
            if custom is not None:
                out["plan_custom"] = custom
            if notify is not None:
                out["notify"] = {"enabled": bool(notify)}
            return out

        machine_store.update_maintenance(change)
    import audit
    import identity
    out = current()
    audit.event("machine.maintenance.plan", {"items": [i["id"] for i in out["items"]], "defaults": defaults, "notify": notify}, identity.actor(ctx))
    check_notifications(_bridge_or_none())
    return {"items": out["items"], "notify": out["notify"], "custom": out["custom"], "summary": out["summary"]}


def _bridge_or_none():
    try:
        return _bridge()
    except Exception:  # noqa: BLE001
        return None


def ops():
    a = Arg
    return [
        Op("machine.maintenance.get", _get, READ, {},
           "The maintenance counters (power-on hours, moving hours and ESTIMATED distance per axis and for the machine), the items of the plan "
           "with what each has used since it was last done and its status (ok, due_soon, due, overdue), and whether phone notices are on.", log=False),
        Op("machine.maintenance.done", _done, WRITE,
           {"id": a("str", True, desc="Id of the item of the plan."), "note": a("str", desc="Free note up to 200 characters.")},
           "Records that a maintenance item was done (who and when, in the audit) and resets it: the counters at that moment are its new zero."),
        Op("machine.maintenance.plan.set", _plan_set, WRITE,
           {"items": a("obj", desc="The whole plan: [{id, label, axis, every_hours | every_km | every_days, hours_basis?}]."),
            "defaults": a("bool", desc="true puts the generic default items back."),
            "notify": a("bool", desc="true: phone notice when an item becomes due (opt-in).")},
           "Edits the maintenance plan (saved in the machine profile) and the opt-in of the due notices. It only changes reminders."),
    ]
