"""
audit_alarms -- the alarms of the activity record (phase 4, PLAN-ACCESO.md 4.4; decision I-8 of DECISIONS-TOMADAS.md).

Four alarms, each one switchable in the settings (audit_settings.py, key "audit" -> "alarms"):

  access_damaged    the file of access profiles is damaged: nobody has profiles attached, the base roles decide (I-8). While it stays damaged there is
                    ONE visible notice per period (alarm_quiet_s, debounced and remembered in the table audit_alarm_state, so a restart loop does not
                    repeat it), and a note when the file is healthy again.
  denial_burst      one person is refused `burst_threshold` times inside `burst_window_s`. One alarm per person and period.
  sensitive_change  a profile that grants risk 4 or an administrator profile is created or changed, a key is created, or the group of an administrator
                    changes. One alarm per change (a change is rare and always worth a line).
  chain_broken      audit.verify found a broken chain. One alarm per period.

HOW A NOTICE IS RAISED: the service already has one mechanism, the Activity record + the phone (activity.log_event with a type of notifier.KINDS, the
way db_backup shows a database set aside). This module does not touch it: `sink(key, params)` is set by audit_ops.make_ops to a function that logs the
activity event of type "security_alarm" with the text M(key, **params) (keys audit_alarm_* in es.json and en.json). Tests put their own sink.
Nothing here raises: an alarm must never break the call that caused it.
"""
import collections
import fnmatch

import audit_settings
import clock
import permission_caps as caps

sink = None  # fn(key, params) -> None; None = nothing is raised (no bridge yet)
users_of = lambda: None  # () -> users.UserStore or None, to know who is an administrator  # noqa: E731
EVENT_TYPE = "security_alarm"
_hits = collections.defaultdict(collections.deque)  # person -> monotonic times of its recent refusals
_last = {}  # (alarm, subject) -> monotonic time of the last notice
state_store = None  # (read(name) -> (state, ts) or None, write(name, state, ts)): the table audit_alarm_state, set by audit_ops (this module imports no store)
_file = {"state": None, "ts": 0}  # access file: "damaged" | "ok" | None (not read from the database yet) and when the last notice was


def _raise(text_key, **params):
    try:
        if sink is not None:
            sink(text_key, params)
    except Exception:  # noqa: BLE001
        pass


def _quiet(name, subject, quiet):
    """True when the alarm of this subject was raised less than `quiet` seconds ago; otherwise remembers now."""
    now = clock.mono()
    k = (name, subject)
    if k in _last and now - _last[k] < quiet:
        return True
    if len(_last) > 500:
        _last.clear()
    _last[k] = now
    return False


# ---- a burst of refusals ----

def denied(person):
    """A refusal of `person` (a name, or something that tells an anonymous caller apart). Raises the burst alarm when the threshold is reached."""
    try:
        if not audit_settings.alarm_on("denial_burst"):
            return
        s = audit_settings.get()
        now = clock.mono()
        q = _hits[person]
        q.append(now)
        while q and now - q[0] > s["burst_window_s"]:
            q.popleft()
        if len(_hits) > 200:
            for k in [k for k, v in _hits.items() if not v]:
                del _hits[k]
        if len(q) >= s["burst_threshold"] and not _quiet("denial_burst", person, s["alarm_quiet_s"]):
            _raise("audit_alarm_denial_burst", person=person, count=len(q), seconds=s["burst_window_s"])
            q.clear()
    except Exception:  # noqa: BLE001
        pass


# ---- sensitive changes ----

def grants_risk4(doc):
    """True when an `allow` rule of the profile document grants an operation of risk 4 (a capability of risk 4 by "cap:", a tier, "*", or an operation
    name or pattern that overlaps the operations of a capability of risk 4). An operation that is in no capability is not known here."""
    risky = [p for c in caps.CAPABILITIES.values() if c["risk"] >= 4 for p in c["ops"]]
    for rule in (doc or {}).get("rules", ()):
        if rule.get("decision") != "allow":
            continue
        for e in rule.get("operations", ()):
            if e.startswith("tier:") or e == "*":
                return True
            if e.startswith("cap:"):
                if caps.CAPABILITIES.get(e[4:], {}).get("risk", 0) >= 4:
                    return True
                continue
            pat = e.replace(":", ".", 1) if ":" in e else e
            if any(fnmatch.fnmatchcase(p, pat) or fnmatch.fnmatchcase(pat, p) for p in risky):
                return True
    return False


def admin_like(doc):
    """An administrator profile: the managed one, or a document that allows everything or a tier."""
    if str((doc or {}).get("name", "")).startswith("base.administrator"):
        return True
    return any(r.get("decision") == "allow" and any(e == "*" or e.startswith("tier:") for e in r.get("operations", ())) for r in (doc or {}).get("rules", ()))


def _is_admin(name):
    st = users_of()
    rec = st.users.get(str(name).strip().casefold()) if st is not None else None
    return bool(rec) and rec.get("role") == "admin"


def sensitive(op_name, args, ctx, ok, who):
    """After a call: raises the alarm when it was one of the sensitive changes. `ctx` carries what access_ops left (the profile document that was
    saved, the people whose groups changed)."""
    try:
        if not ok or not audit_settings.alarm_on("sensitive_change"):
            return
        if op_name in ("access.profiles.set", "access.profile.rollback"):
            doc = ctx.get("access_changed_profile") or {}
            if admin_like(doc):
                _raise("audit_alarm_profile_admin", actor=who, profile=doc.get("name", "?"))
            elif grants_risk4(doc):
                _raise("audit_alarm_profile_risk4", actor=who, profile=doc.get("name", "?"))
        elif op_name == "keys.create":
            _raise("audit_alarm_key_created", actor=who, key=str((args or {}).get("name") or "?")[:40])
        for person in ctx.get("access_members_changed") or ():
            if _is_admin(person):
                _raise("audit_alarm_admin_group", actor=who, person=person)
    except Exception:  # noqa: BLE001
        pass


# ---- the access file ----

def _state(name):
    try:
        return state_store[0](name) or ("ok", 0)
    except Exception:  # noqa: BLE001
        return "ok", 0


def _remember(name, state, ts):
    try:
        state_store[1](name, state, ts)
    except Exception:  # noqa: BLE001
        pass


def access_file(damaged):
    """Called on every call that looks at the access file. Cheap when nothing changes."""
    try:
        if not damaged and _file["state"] == "ok":
            return
        if not audit_settings.alarm_on("access_damaged"):
            return
        if _file["state"] is None:
            _file["state"], _file["ts"] = _state("access_file")
        now = int(clock.wall())
        if damaged:
            if _file["state"] != "damaged" or now - _file["ts"] >= audit_settings.get()["alarm_quiet_s"]:
                _file.update(state="damaged", ts=now)
                _remember("access_file", "damaged", now)
                _raise("audit_alarm_access_damaged")
        elif _file["state"] == "damaged":
            _file.update(state="ok", ts=now)
            _remember("access_file", "ok", now)
            _raise("audit_alarm_access_healed")
        else:
            _file["state"] = "ok"
    except Exception:  # noqa: BLE001
        pass


# ---- the chain ----

def chain_broken(result):
    """After audit.verify: `result` is its answer. Raises the alarm when the chain is broken."""
    try:
        b = result.get("broken") if isinstance(result, dict) else None
        if b and audit_settings.alarm_on("chain_broken") and not _quiet("chain_broken", "chain", audit_settings.get()["alarm_quiet_s"]):
            _raise("audit_alarm_chain_broken", audit_id=b.get("audit_id"), reason=b.get("reason"))
    except Exception:  # noqa: BLE001
        pass


def reset():
    """Forgets everything held in memory (tests)."""
    _hits.clear()
    _last.clear()
    _file.update(state=None, ts=0)
