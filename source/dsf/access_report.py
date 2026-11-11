"""
access_report -- what access.review and access.report show (phase 6 of informes/control-acceso/PLAN-ACCESO.md, section 4.5). Read-only.

  snapshot(env, keys, now)     the input of access_review.review, read from the stores (access file, users, keys): the only function here that
                               touches a store; it only reads
  people_and_keys(...)         the report of people and keys, from plain data (pure): users, locked PINs, last sign-in, age of the PIN,
                               what each person last used (access_usage) and each key with its last use

`env` is access_admin.Env (access store, users store); `keys` is api_keys.KeyStore or None (no keys file). Nothing is written and nothing is
decided here; the severity "high" findings are exposed by access.review (there is no scheduler that would turn them into notices: the notice
system of the service writes rows of the activity history from the code that sees an event, and a review is a read on demand).
"""
import access_review

DAY_S = 86400


def snapshot(env, keys=None):
    """The data of access_review.review, read now."""
    damaged = bool(env.access.damaged)
    view = None if damaged else env.access.view()
    profiles = []
    if view is not None:
        for doc in env.access.list():
            profiles.append({"name": doc["name"], "doc": doc, "holders": view.holders(doc["name"])})
    people = []
    for rec in (env.users.list() if env.users is not None else []):
        att = view.person(rec["name"]) if view is not None else {"groups": [], "profiles": []}
        people.append({"name": rec["name"], "role": rec["role"], "groups": att["groups"], "profiles": att["profiles"],
                       "last_seen": rec.get("last_seen"), "created": rec.get("created"), "pin_changed": rec.get("pin_changed"),
                       "sessions": rec.get("sessions", 0)})
    return {"damaged": damaged, "profiles": profiles, "people": people, "keys": keys.list() if keys is not None else []}


def _age_days(iso, now):
    seen = access_review.iso_epoch(iso)
    return None if seen is None else max(0, int((now - seen) // DAY_S))


def people_and_keys(data, lockouts, used, now):
    """The report. `lockouts` is {name: seconds left} (users.UserStore.lockouts), `used` is {person casefolded: {capability: epoch}}
    (access_usage.UsageStore.used)."""
    people = []
    for p in data.get("people") or ():
        mine = used.get(p["name"].casefold(), {})
        people.append({
            "name": p["name"], "role": p["role"], "groups": list(p.get("groups") or ()), "profiles": list(p.get("profiles") or ()),
            "governed": bool(p.get("groups") or p.get("profiles")) and not data.get("damaged"),
            "last_login": p.get("last_seen"), "sessions": p.get("sessions", 0),
            "pin_changed": p.get("pin_changed"), "pin_age_days": _age_days(p.get("pin_changed") or p.get("created"), now),
            "locked_for_s": int(lockouts.get(p["name"], 0)),
            "last_used": dict(sorted(mine.items())), "last_use": max(mine.values()) if mine else None})
    keys = []
    for k in data.get("keys") or ():
        last = k.get("last_used")
        keys.append({"id": k.get("id"), "name": k.get("name"), "enabled": bool(k.get("enabled", True)), "created": k.get("created"),
                     "last_used": last, "uses": k.get("uses", 0), "expires": k.get("expires"), "breadth": access_review.key_breadth(k),
                     "idle_days": None if not last else max(0, int((now - last) // DAY_S))})
    return {"generated": int(now), "damaged": bool(data.get("damaged")), "people": people, "keys": keys,
            "locked": sorted(n for n, s in lockouts.items() if s > 0)}
