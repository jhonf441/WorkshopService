"""Scenarios of the development backend (tools/dev/api_server.py): the people, roles, keys and rows a test starts from.

Everything that has an operation is created THROUGH the operation (so it went through the real validation): people, roles, keys,
settings. Bulk rows (activity, received commands, audit) are written with the functions of dsf/db.py, the same ones the service uses.

    open        nobody was created: everybody is an administrator (open mode)
    users       one person per role with a known PIN, a custom role with a denial and a person who has it; a session is required
    anonymous   the same, and a caller with no session reads as a viewer
    damaged     the people file is unreadable: the service fails closed

The PINs are test values of a throwaway folder on this PC; they are never used on a real machine.
"""
import json
import os
import time

SCENARIOS = ("open", "users", "anonymous", "damaged")

# name, PIN, role, extra arguments of users.add
PEOPLE = [
    ("Ana Admin", "482913", "admin", {}),
    ("Tomas Tecnico", "735128", "technician", {}),
    ("Olga Operadora", "614937", "operator", {"modes": ["laser", "cnc"]}),
    ("Victor Visitante", "825039", "viewer", {"camera_for_viewer": True}),
    ("Nadia Nocturna", "936257", "Turno noche", {"modes": ["laser"]}),
    ("Jose Maria Fernandez-Ruiz Jr.", "648291", "operator", {}),     # a long name with a hyphen and a dot (the longest the service accepts: 32)
]
CUSTOM_ROLE = {"name": "Turno noche", "base": "operator", "description": "Night shift: runs jobs, may not touch the lights nor the power",
               "grant": [], "deny": ["lights.*", "power.after_job"]}
KEYS = [
    {"name": "Vision camera", "preset": "read"},
    {"name": "Old dashboard", "preset": "read", "days": 1, "_age_days": 5},          # expired 4 days ago
    {"name": "Lights panel", "preset": "lights_air", "_enabled": False},              # switched off
]
# texts a page must print as text, never run or break on
NASTY = ['<img src=x onerror=alert(1)>', "O'Brien \"quoted\" & co", "Corte de MDF 3 mm: capa nº 2 — año 2026", "x" * 300, "", "línea\ncon salto", "{braces} | pipe @ at"]
ACTIVITY_TYPES = ["job", "service", "system", "laser", "camera", "power", "security_alarm"]
OPS_FOR_ROWS = ["lights.set", "power.after_job", "users.set", "settings.set", "service.restart", "air.set", "movement.lock", "keys.create"]


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def wipe(root):
    """Everything the service wrote under the data root, the database rows included (the file stays: other threads may hold it)."""
    import db
    import db_conn
    for folder in ("conf", "sd/sys/workshop/config", "sd/sys/workshop/data"):
        base = os.path.join(root, folder)
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                try:
                    os.remove(os.path.join(dirpath, name))
                except OSError:
                    pass
    with db_conn.write(db.DB_FILE) as conn:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            conn.execute('DROP TRIGGER IF EXISTS "%s"' % name)
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
            conn.execute('DROP TABLE IF EXISTS "%s"' % name)
        conn.execute("PRAGMA user_version = 0")
    db.init_db()


def people(backend, anonymous=False):
    backend.internal("users.add", {"name": PEOPLE[0][0], "pin": PEOPLE[0][1], "role": PEOPLE[0][2]})   # the first one must be an administrator
    backend.internal("roles.set", CUSTOM_ROLE)
    for name, pin, role, extra in PEOPLE[1:]:
        backend.internal("users.add", dict({"name": name, "pin": pin, "role": role}, **extra))
    if anonymous:
        backend.internal("users.settings", {"anonymous_viewer": True})


def keys(backend):
    import api_ops
    store = api_ops._ctx.get("keys")
    made = []
    for spec in KEYS:
        args = {k: v for k, v in spec.items() if not k.startswith("_")}
        real = store.clock
        if spec.get("_age_days"):
            store.clock = lambda real=real, d=spec["_age_days"]: real() - d * 86400
        try:
            out = backend.internal("keys.create", args)
        finally:
            store.clock = real
        made.append(out)
        if spec.get("_enabled") is False:
            listed = backend.internal("keys.list")
            rec = next(k for k in listed["keys"] if k["name"] == spec["name"])
            backend.internal("keys.update", {"id": rec["id"], "enabled": False})
    return made


def rows(count, break_chain=False):
    """`count` rows in each of activity, received commands and audit, spread over the last 60 days (plus one old and one in the future)."""
    import db
    import db_conn
    now = time.time()
    names = [p[0] for p in PEOPLE]
    span = 60 * 86400
    for i in range(count):
        t = now - (span * (count - i) / max(count, 1))
        who = names[i % len(names)]
        role = PEOPLE[i % len(PEOPLE)][2]
        text = NASTY[i % len(NASTY)] if i % 9 == 0 else "Row %d of the seed" % (i + 1)
        db.insert_activity(_iso(t), ACTIVITY_TYPES[i % len(ACTIVITY_TYPES)], text, kind="info" if i % 5 else "warning", duration_s=i % 600,
                           detail={"data": {"n": i, "note": NASTY[(i + 3) % len(NASTY)]}}, user=who, role=role)
        op = OPS_FOR_ROWS[i % len(OPS_FOR_ROWS)]
        ok = i % 7 != 0
        db.command_insert(_iso(t), op, json.dumps({"n": i, "text": text[:80]}, ensure_ascii=False), ok, 3 + i % 40, "ok" if ok else "refused: " + text[:60],
                          via="session", reading=False, origin={"channel": "HTTP", "kind": "page", "plugin": "WorkshopService", "result": "ok" if ok else "error"}, user=who, role=role)
        db.audit_insert(_iso(t), who, role, "dev-%d" % (i % 4), "127.0.0.1", "session", op, "n=%d %s" % (i, text[:60]), ok, "" if ok else "forbidden", "" if ok else "not allowed",
                        {"reason": "role"} if not ok else None)
    runs(max(0, min(60, count // 5)), names)
    if count:
        db.insert_activity(_iso(now - 400 * 86400), "system", "A very old row (400 days)", user=names[0], role="admin")
        db.insert_activity(_iso(now + 2 * 86400), "system", "A row dated in the future (clock moved)", user=names[0], role="admin")
    if break_chain and count >= 3:
        with db_conn.write(db.DB_FILE) as conn:
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit'").fetchall():
                conn.execute('DROP TRIGGER IF EXISTS "%s"' % name)   # the table refuses changes: the seed breaks it on purpose, as a tampered file would be
            row = conn.execute("SELECT id FROM audit ORDER BY id LIMIT 1 OFFSET ?", (count // 2,)).fetchone()
            conn.execute("UPDATE audit SET args = 'tampered by the seed' WHERE id = ?", (row[0],))
    return count


def runs(count, names):
    """`count` runs of the start-up (what startup.runs.list pages), each with a few file actions, written with the service's own install_log."""
    import install_log
    triggers = sorted(install_log.TRIGGERS)
    actions = sorted(install_log.ACTIONS)
    for i in range(count):
        run = install_log.Run(triggers[i % len(triggers)], actor=names[i % len(names)], role="admin", device="dev-1", via="session", dry_run=i % 4 == 0)
        run.run_id = "%s-%04d" % (run.run_id[:15], i)                  # unique and in order (they are created within the same second)
        for j in range(1 + i % 4):
            run.add("Workshop" + ("Lights", "Power", "Jog", "Camera")[j % 4], "0:/sys/workshop/macros/dev/file-%d-%d.g" % (i, j), actions[(i + j) % len(actions)],
                    kind="macro", reason="seed", size_before=120 + j, size_after=140 + j)
        run.finish()


def damage_people(root):
    with open(os.path.join(root, "conf", "workshop-users.json"), "w", encoding="utf-8") as f:
        f.write('{"users": [ this is not JSON')


def apply(backend, scenario="open", row_count=0, break_chain=False):
    """Back to an empty service, then the scenario. Returns a summary (the people and PINs a tester needs)."""
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario %r (one of %s)" % (scenario, ", ".join(SCENARIOS)))
    wipe(backend.root)
    if scenario == "damaged":
        damage_people(backend.root)
    backend.start()
    made = []
    if scenario in ("users", "anonymous"):
        people(backend, anonymous=scenario == "anonymous")
        made = keys(backend)
    rows(int(row_count or 0), break_chain=bool(break_chain))
    return {
        "scenario": scenario, "rows": int(row_count or 0), "broken_chain": bool(break_chain and int(row_count or 0) >= 3),
        "people": [{"name": n, "pin": p, "role": r} for n, p, r, _ in PEOPLE] if scenario in ("users", "anonymous") else [],
        "keys": [{"name": k.get("name"), "key": k.get("key")} for k in made if isinstance(k, dict)],
    }
