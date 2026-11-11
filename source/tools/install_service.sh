#!/bin/bash
# Installs / updates WorkshopService <version> on a Duet 3 + Raspberry Pi from the RELEASE ZIP, and only from it (plan F1, D-36).
#
#   tools/install_service.sh --host HOST --user USER --version X.Y.Z --zip FILE [--dry-run] [--force-busy] [--reinstall]
#   tools/install_service.sh --local --version X.Y.Z --zip FILE [--dsf-root DIR] [--dry-run] ...   (run on the Pi itself, or on a scratch root)
#
# Without --local it copies this script and the zip to the Pi and runs itself there with --local, so there is one code path.
# What it does, in order (nothing is deleted):
#   1. verifies the zip: dsf/RELEASE.json (version, sha256 and size of every file) against the bytes, and nothing else in the zip;
#   2. refuses while the machine is busy (status other than idle, off or halted, or a live job / orders on the G-code bridge); --force-busy overrides;
#   3. refuses to reinstall the version that is installed (the backup of what was there would hold the NEW code); --reinstall or FORCE=1 overrides;
#   4. prints the plan: files to copy, files that will be MOVED away (leftovers: test_*.py, anything the release does not list), bundles;
#      --dry-run stops here (the plan it prints is the one a real run executes);
#   5. stops Vision, RS485 and the service; backs up what it will touch to ~/sd-backup/WorkshopService-pre-<version>/ (cp -n: an existing
#      backup of the same version is never overwritten); moves leftovers to <backup>/leftovers/ (never deletes them);
#   6. copies ONLY the files of the release (atomic: temp file + rename), the js / css to <plugin>/dwc/ and <dsf>/dwc/, then writes the manifest
#      (version, data, dsfFiles from the zip, dwcFiles ONLY the files of the new build), reloads and starts the service, RS485 and Vision,
#      removes served bundles that are not in the manifest;
#   7. checks: manifest version, every installed file against RELEASE.json, api.ping. If anything fails it RESTORES the state it found
#      (exit 5). If everything passes it restores nothing.
#
# Exit codes: 2 bad zip / bad arguments, 3 machine busy, 4 same version already installed, 5 install failed and was rolled back,
# 6 not installed yet (first install: tools/install.sh), 7 install failed and the rollback failed too (the undo folder is kept).
#
# Environment (tests use these on a scratch root; a real run needs none):
#   WORKSHOP_DSF_ROOT (/opt/dsf)  WORKSHOP_HOME (backup base, default $HOME)  PYTHON  WORKSHOP_SSH_OPTS
#   WORKSHOP_STATUS_CMD  prints the DSF machine status JSON (default: curl http://localhost/machine/status)
#   WORKSHOP_PING_CMD    prints the answer of POST api.ping (default: curl on /machine/WorkshopService/api); WORKSHOP_PING_TRIES / _WAIT
#   WORKSHOP_STOP        plugins to stop before and start after, in stop order (default "WorkshopVision WorkshopRS485")
set -eu

HOST="${WORKSHOP_HOST:-}"; USER_="${WORKSHOP_USER:-}"; VER="${WORKSHOP_VERSION:-}"; ZIP="${WORKSHOP_ZIP:-}"
ROOT="${WORKSHOP_DSF_ROOT:-/opt/dsf}"; SSH_OPTS="${WORKSHOP_SSH_OPTS:-}"
STOP="${WORKSHOP_STOP-WorkshopVision WorkshopRS485}"
LOCAL=0; DRY=0; FORCE_BUSY=0; REINSTALL=0; [ "${FORCE:-0}" = 1 ] && REINSTALL=1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "ERROR: $*" >&2; exit "${2:-2}"; }
say() { echo "[install-service] $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --user) USER_="$2"; shift 2;;
    --version) VER="$2"; shift 2;;
    --zip) ZIP="$2"; shift 2;;
    --dsf-root) ROOT="$2"; shift 2;;
    --stop) STOP="$2"; shift 2;;
    --local) LOCAL=1; shift;;
    --dry-run) DRY=1; shift;;
    --force-busy) FORCE_BUSY=1; shift;;
    --reinstall) REINSTALL=1; shift;;
    -h|--help) sed -n '2,/^set -eu/p' "${BASH_SOURCE[0]}" | sed '$d'; exit 0;;
    *) die "unknown option: $1 (use --help)";;
  esac
done
[ -n "$VER" ] || die "missing --version"
case "$VER" in *[!0-9A-Za-z._-]*|"") die "bad version: $VER";; esac
[ -n "$ZIP" ] || die "missing --zip"
[ -f "$ZIP" ] || die "zip not found: $ZIP"

# ---------------------------------------------------------------- remote mode: copy self + zip, run --local there
if [ "$LOCAL" = 0 ]; then
  [ -n "$HOST" ] || die "missing --host (or --local)"
  [ -n "$USER_" ] || die "missing --user (or --local)"
  # shellcheck disable=SC2206
  SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 $SSH_OPTS)
  # shellcheck disable=SC2206
  SCP=(scp -q -o BatchMode=yes -o ConnectTimeout=10 $SSH_OPTS)
  T="$USER_@$HOST"; R="/tmp/workshop-install-service-$VER"
  "${SSH[@]}" "$T" "rm -rf '$R' && mkdir -p '$R'"
  "${SCP[@]}" "${BASH_SOURCE[0]}" "$ZIP" "$T:$R/"
  flags=""; [ "$DRY" = 1 ] && flags="$flags --dry-run"; [ "$FORCE_BUSY" = 1 ] && flags="$flags --force-busy"; [ "$REINSTALL" = 1 ] && flags="$flags --reinstall"
  rc=0
  "${SSH[@]}" "$T" "bash '$R/$(basename "${BASH_SOURCE[0]}")' --local --version '$VER' --zip '$R/$(basename "$ZIP")' --dsf-root '$ROOT' --stop '$STOP'$flags" || rc=$?
  "${SSH[@]}" "$T" "rm -rf '$R'" || true
  exit "$rc"
fi

# ---------------------------------------------------------------- local mode (on the Pi or on a scratch root)
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    if $c -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || die "Python 3 not found (tried python3, python)"
HOME_DIR="${WORKSHOP_HOME:-$HOME}"
PL="$ROOT/plugins"; PM="$ROOT/bin/PluginManager"; PLUG="$PL/WorkshopService"; MANIFEST="$PL/WorkshopService.json"
BK="$HOME_DIR/sd-backup/WorkshopService-pre-$VER"
WORK="$(mktemp -d)"; X="$WORK/x"; UNDO="$WORK/undo"; PLAN="$WORK/plan.txt"
KEEP_WORK=0
cleanup() { [ "$KEEP_WORK" = 1 ] || rm -rf "$WORK"; return 0; }
trap cleanup EXIT

PYHELPER=$(cat <<'PYEOF'
import hashlib, json, os, sys, time, zipfile

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def release(x):
    return load(os.path.join(x, "dsf", "RELEASE.json"))

def same(a, b):
    return os.path.isfile(a) and os.path.isfile(b) and os.path.getsize(a) == os.path.getsize(b) and sha(a) == sha(b)

def walk(base):
    out = []
    for r, d, fs in os.walk(base):
        d[:] = [n for n in d if n != "__pycache__"]
        for f in fs:
            if not f.endswith(".pyc"):
                out.append(os.path.relpath(os.path.join(r, f), base).replace(os.sep, "/"))
    return sorted(out)

def cmd_verify(zpath, x, version):
    bad = []
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for n in names:
            if n.startswith("/") or ".." in n.split("/") or ":" in n:
                bad.append("unsafe entry name " + n)
        if bad:
            return bad
        z.extractall(x)
    if "plugin.json" not in names or "dsf/RELEASE.json" not in names:
        return ["the zip has no plugin.json or no dsf/RELEASE.json (it is not a release built by tools/build_release.py of 2.36 or later)"]
    rel, man = release(x), load(os.path.join(x, "plugin.json"))
    if rel.get("version") != version or man.get("version") != version:
        bad.append("version mismatch: asked %s, RELEASE.json %s, plugin.json %s" % (version, rel.get("version"), man.get("version")))
    listed = {e["path"]: e for e in rel.get("files", [])}
    for p, e in sorted(listed.items()):
        fp = os.path.join(x, p)
        if not os.path.isfile(fp):
            bad.append("listed but missing: " + p)
        elif os.path.getsize(fp) != e["size"] or sha(fp) != e["sha256"]:
            bad.append("hash or size differs from RELEASE.json: " + p)
    for n in names:
        if n not in listed and n not in ("plugin.json", "dsf/RELEASE.json"):
            bad.append("in the zip but not in RELEASE.json: " + n)
    dsf = sorted("dsf/" + n for n in man.get("dsfFiles", []))
    if dsf != sorted(n for n in names if n.startswith("dsf/")):
        bad.append("plugin.json dsfFiles does not match the dsf/ entries of the zip")
    if not bad:
        print("zip verified: %d files, version %s, commit %s" % (len(listed), version, rel.get("commit")))
    return bad

def cmd_plan(x, plug, root, out):
    """Lines: COPY|NEW dsf/<rel>, LEFT <rel under plugin dsf>, BUNDLE dwc/<js|css>/<name>, KEEP <count>."""
    rel = release(x)
    lines, keep, listed_dsf = [], 0, set()
    # RELEASE.json cannot hold its own hash: it is installed with the files (the check compares it with the zip)
    for e in rel["files"] + [{"path": "dsf/RELEASE.json"}]:
        p = e["path"]
        if p.startswith("dsf/"):
            listed_dsf.add(p[4:])
            tgt = os.path.join(plug, p)
            if not os.path.exists(tgt):
                lines.append("NEW\t" + p)
            elif not same(os.path.join(x, p), tgt):
                lines.append("COPY\t" + p)
            else:
                keep += 1
        elif p.startswith("dwc/"):
            if not (same(os.path.join(x, p), os.path.join(plug, p)) and same(os.path.join(x, p), os.path.join(root, p))):
                lines.append("BUNDLE\t" + p)
    # leftovers: config.json / secrets.json are machine settings (never touched); RELEASE.json is in the list
    base = os.path.join(plug, "dsf")
    for f in (walk(base) if os.path.isdir(base) else []):
        if f not in listed_dsf and os.path.basename(f) not in ("config.json", "secrets.json"):
            lines.append("LEFT\t" + f)
    lines.append("KEEP\t%d" % keep)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

def cmd_manifest(x, mpath, version, plug):
    d = load(mpath) if os.path.exists(mpath) else {}
    new = load(os.path.join(x, "plugin.json"))
    d["version"] = version
    d["name"] = "Workshop - Service"
    d["dwcVersion"] = new["dwcVersion"]          # strict line values (3.6), not the old "3"
    d["sbcDsfVersion"] = new["sbcDsfVersion"]
    d["data"] = new.get("data", d.get("data"))   # data keys declared by the plugin
    d["dsfFiles"] = new.get("dsfFiles", d.get("dsfFiles"))  # DSF removes only what the manifest lists on uninstall
    d["dwcFiles"] = sorted("%s/%s" % (k, f) for k in ("css", "js") if os.path.isdir(os.path.join(x, "dwc", k)) for f in os.listdir(os.path.join(x, "dwc", k)))
    with open(mpath, "w", encoding="utf-8", newline="") as f:
        json.dump(d, f, separators=(",", ":"), ensure_ascii=False)
    print(d["version"], d["dwcFiles"])
    print("EXE\t" + (new.get("sbcExecutable") or ""))

def cmd_stale(mpath, plug, root):
    d = load(mpath)
    ref = {os.path.basename(f) for f in d["dwcFiles"]}
    for sub in (root + "/dwc/js", root + "/dwc/css", plug + "/dwc/js", plug + "/dwc/css"):
        if os.path.isdir(sub):
            for f in sorted(os.listdir(sub)):
                if f.startswith("WorkshopService.") and f not in ref:
                    print(sub + "/" + f)

def cmd_check(x, plug, root, mpath, version):
    bad = []
    try:
        if load(mpath).get("version") != version:
            bad.append("installed manifest is not " + version)
    except Exception as e:  # noqa: BLE001
        bad.append("installed manifest unreadable: %s" % e)
    listed_dsf = set()
    for e in release(x)["files"] + [{"path": "dsf/RELEASE.json"}]:
        p = e["path"]
        places = [os.path.join(plug, p)] + ([os.path.join(root, p)] if p.startswith("dwc/") else [])
        if p.startswith("dsf/"):
            listed_dsf.add(p[4:])
        for t in places:
            if not os.path.isfile(t):
                bad.append("missing: " + t)
            elif "size" not in e:
                if not same(os.path.join(x, p), t):
                    bad.append("differs from the zip: " + t)
            elif os.path.getsize(t) != e["size"] or sha(t) != e["sha256"]:
                bad.append("differs from RELEASE.json: " + t)
    base = os.path.join(plug, "dsf")
    for f in walk(base):
        if f not in listed_dsf and os.path.basename(f) not in ("config.json", "secrets.json"):
            bad.append("not in RELEASE.json: " + f)
    return bad

def cmd_busy(bridge_state):
    """exit 0 busy (reason printed), 1 free, 2 cannot tell. The status JSON comes on stdin."""
    raw = sys.stdin.read()
    try:
        d = json.loads(raw)
        d = d.get("result", d) if isinstance(d, dict) else {}
        status = (d.get("state") or {}).get("status")
    except Exception:  # noqa: BLE001
        status = None
    if not isinstance(status, str):
        print("the machine status could not be read")
        return 2
    # nothing is running in idle, off (powered down: the usual state when the service is installed) and halted (emergency stop);
    # anything else (processing, paused, busy, changingTool, disconnected, starting...) is "busy" or unknown, so it refuses
    if status not in ("idle", "off", "halted"):
        print("machine status is %r (only idle, off or halted allow an install)" % status)
        return 0
    if os.path.isfile(bridge_state):
        try:
            age = time.time() - os.path.getmtime(bridge_state)
            b = load(bridge_state)
        except Exception:  # noqa: BLE001
            return 1
        if age <= 15 and isinstance(b, dict):
            act = b.get("activity") if isinstance(b.get("activity"), dict) else {}
            job = act.get("live_job") if isinstance(act.get("live_job"), dict) else {}
            num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0  # noqa: E731
            if job.get("active"):
                print("a live job is open through the bridge")
                return 0
            if num(act.get("pending_orders")) > 0:
                print("orders are being sent to the machine right now")
                return 0
            ages = [num(c.get("last_order_age_s")) + age for c in (b.get("clients") or []) if isinstance(c, dict) and isinstance(c.get("last_order_age_s"), (int, float))]
            if ages and min(ages) < 30:
                print("an order arrived in the last 30 seconds")
                return 0
    return 1

def main():
    sys.stdout.reconfigure(newline="\n")  # Windows pythons would print CRLF and break the shell reads
    c, a = sys.argv[1], sys.argv[2:]
    if c == "busy":
        sys.exit(cmd_busy(*a))
    if c in ("verify", "check"):
        bad = cmd_verify(*a) if c == "verify" else cmd_check(*a)
        for b in bad:
            print("  PROBLEM: " + b)
        sys.exit(1 if bad else 0)
    {"plan": cmd_plan, "manifest": cmd_manifest, "stale": cmd_stale}[c](*a)

main()
PYEOF
)
pyh() { PYTHONDONTWRITEBYTECODE=1 "$PY" -c "$PYHELPER" "$@"; }

# ---- 1. the zip
mkdir -p "$X" "$UNDO"
say "checking the zip"
pyh verify "$ZIP" "$X" "$VER" || die "the zip does not match its RELEASE.json: nothing was touched" 2

[ -f "$MANIFEST" ] || die "WorkshopService is not installed in $ROOT yet: do the first install with tools/install.sh" 6
INSTALLED="$(PYTHONDONTWRITEBYTECODE=1 "$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST" 2>/dev/null || echo unknown)"

# ---- 2. is the machine busy?
STATUS_CMD="${WORKSHOP_STATUS_CMD:-curl -s --max-time 5 http://localhost/machine/status}"
busy_rc=0
busy_why="$(bash -c "$STATUS_CMD" 2>/dev/null | pyh busy "$ROOT/sd/sys/workshop/data/bridge-state.json")" || busy_rc=$?
BUSY_MSG=""
if [ "$busy_rc" != 1 ]; then BUSY_MSG="$busy_why"; fi
if [ -n "$BUSY_MSG" ] && [ "$FORCE_BUSY" != 1 ] && [ "$DRY" != 1 ]; then
  echo "REFUSED: the machine is busy ($BUSY_MSG). Installing stops the service, Vision and RS485." >&2
  echo "Wait until it is idle, or run again with --force-busy if you are sure." >&2
  exit 3
fi
# ---- 3. same version
if [ "$INSTALLED" = "$VER" ] && [ "$REINSTALL" != 1 ] && [ "$DRY" != 1 ]; then
  echo "STOP: WorkshopService $VER is already installed (a second install would overwrite the rollback backup). Use --reinstall (or FORCE=1) to override." >&2
  exit 4
fi

# ---- 4. the plan (a dry run stops after printing it)
pyh plan "$X" "$PLUG" "$ROOT" "$PLAN"
say "installed: $INSTALLED, installing: $VER, backup folder: $BK"
[ -n "$BUSY_MSG" ] && say "WOULD REFUSE: the machine is busy ($BUSY_MSG)"
[ "$INSTALLED" = "$VER" ] && say "note: this version is already installed (needs --reinstall)"
say "files to copy:";            awk -F'\t' '$1=="COPY"||$1=="NEW"{print "  " $1 " " $2}' "$PLAN"
say "bundles to copy:";          awk -F'\t' '$1=="BUNDLE"{print "  " $2}' "$PLAN"
say "leftovers that will be MOVED to $BK/leftovers (not deleted):"; awk -F'\t' '$1=="LEFT"{print "  " $2}' "$PLAN"
say "unchanged files: $(awk -F'\t' '$1=="KEEP"{print $2}' "$PLAN")"
if [ "$DRY" = 1 ]; then say "dry run: nothing changed"; exit 0; fi

# ---- 5/6/7. apply; on any failure restore what was found
step() { "$@" || { echo "step failed: $*" >&2; return 1; }; }
p_kind() { awk -F'\t' -v k="$1" '$1==k{print $2}' "$PLAN"; }
group_fix() {
  if getent group dsf >/dev/null 2>&1; then
    chgrp -R dsf "$PLUG" "$MANIFEST" 2>/dev/null || true
    chmod -R g+rwX "$PLUG" 2>/dev/null || true
    chmod g+rw "$MANIFEST" 2>/dev/null || true
    if find "$PLUG" ! -group dsf 2>/dev/null | grep -q .; then
      echo "WARNING: some files are not in the group dsf (this user is not in it): DSF may not be able to update or uninstall them."
    fi
  fi
  return 0
}
put() { # put <src> <dst>: write next to the target and rename (atomic)
  mkdir -p "$(dirname "$2")" && cp "$1" "$2.new.$$" && mv -f "$2.new.$$" "$2"
}
start_all() {
  "$PM" reload WorkshopService && "$PM" start WorkshopService || return 1
  sleep 3
  local id
  for id in $(echo "$STOP" | tr ' ' '\n' | tac); do "$PM" start "$id" || true; done   # old order: RS485 then Vision
  return 0
}
backup_and_undo() {
  mkdir -p "$BK/dsf" "$BK/dwc/js" "$BK/dwc/css" "$BK/leftovers" "$UNDO/dsf" "$UNDO/dwc-plug" "$UNDO/dwc-root"
  echo "$STOP" > "$BK/stopped.txt"
  cp -n "$MANIFEST" "$BK/" 2>/dev/null || true       # -n: the backup of the same version is never overwritten
  cp -p "$MANIFEST" "$UNDO/WorkshopService.json"
  : > "$UNDO/new.txt"; : > "$UNDO/moved.txt"; : > "$UNDO/stale.txt"
  local f p
  for f in $(p_kind COPY); do
    mkdir -p "$BK/$(dirname "$f")" "$UNDO/$(dirname "$f")"
    cp -n "$PLUG/$f" "$BK/$f" 2>/dev/null || true
    cp -p "$PLUG/$f" "$UNDO/$f"
  done
  for f in $(p_kind NEW); do echo "$PLUG/$f" >> "$UNDO/new.txt"; echo "${f#dsf/}" >> "$BK/new-files.txt"; done
  for f in $(p_kind BUNDLE); do   # f = dwc/js/name
    for p in "$PLUG/$f|dwc-plug" "$ROOT/$f|dwc-root"; do
      if [ -f "${p%%|*}" ]; then
        mkdir -p "$UNDO/${p##*|}/$(dirname "$f")"; cp -p "${p%%|*}" "$UNDO/${p##*|}/$f"
        [ "${p##*|}" = dwc-plug ] && { mkdir -p "$BK/$(dirname "$f")"; cp -n "${p%%|*}" "$BK/$f" 2>/dev/null || true; }
      else
        echo "${p%%|*}" >> "$UNDO/new.txt"
      fi
    done
  done
}
move_leftovers() {
  local f dst n
  for f in $(p_kind LEFT); do
    dst="$BK/leftovers/$f"; n=0
    while [ -e "$dst" ]; do n=$((n + 1)); dst="$BK/leftovers/$f.$n"; done   # never overwrite a file saved by an earlier run
    mkdir -p "$(dirname "$dst")" && mv "$PLUG/dsf/$f" "$dst" || return 1
    printf '%s\t%s\n' "$f" "$dst" >> "$UNDO/moved.txt"
  done
  return 0
}
copy_files() {
  local f
  for f in $(p_kind COPY) $(p_kind NEW); do put "$X/$f" "$PLUG/$f" || return 1; chmod 644 "$PLUG/$f" 2>/dev/null || true; done
  for f in $(p_kind BUNDLE); do put "$X/$f" "$PLUG/$f" && put "$X/$f" "$ROOT/$f" || return 1; done
  return 0
}
write_manifest() {
  local out exe
  out="$(pyh manifest "$X" "$MANIFEST" "$VER" "$PLUG")" || return 1
  echo "$out" | grep -v '^EXE'
  exe="$(echo "$out" | awk -F'\t' '$1=="EXE"{print $2}')"
  [ -n "$exe" ] && chmod +x "$PLUG/dsf/$exe" 2>/dev/null || true
  return 0
}
remove_stale() {
  local f i=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    i=$((i + 1)); mkdir -p "$UNDO/stale/$i" && mv "$f" "$UNDO/stale/$i/" || return 1
    printf '%s\t%s\n' "$i" "$f" >> "$UNDO/stale.txt"; echo "removed $f"
  done < <(pyh stale "$MANIFEST" "$PLUG" "$ROOT")
  return 0
}
wait_ping() {
  local cmd="${WORKSHOP_PING_CMD:-curl -s --max-time 5 -X POST -H 'Content-Type: application/json' -d '{\"op\":\"api.ping\"}' http://localhost/machine/WorkshopService/api}"
  local tries="${WORKSHOP_PING_TRIES:-15}" i=0 out
  while [ "$i" -lt "$tries" ]; do
    out="$(bash -c "$cmd" 2>/dev/null || true)"
    if echo "$out" | grep -Eq '"pong"[[:space:]]*:[[:space:]]*true'; then say "api.ping answers"; return 0; fi
    i=$((i + 1)); sleep "${WORKSHOP_PING_WAIT:-2}"
  done
  echo "api.ping did not answer" >&2; return 1
}
apply() {
  local id
  for id in $STOP; do "$PM" stop "$id" || true; done
  "$PM" stop WorkshopService || true
  sleep 2
  step backup_and_undo || return 1
  step move_leftovers || return 1
  step copy_files || return 1
  step write_manifest || return 1
  group_fix
  step start_all || return 1
  step remove_stale || return 1
  say "checking the installed files and the service"
  step pyh check "$X" "$PLUG" "$ROOT" "$MANIFEST" "$VER" || return 1
  step wait_ping || return 1
  return 0
}
restore() {
  local f i dst
  "$PM" stop WorkshopService || true
  sleep 2
  (cd "$UNDO" && find dsf -type f 2>/dev/null) | while read -r f; do put "$UNDO/$f" "$PLUG/$f"; done
  [ -d "$UNDO/dwc-plug/dwc" ] && (cd "$UNDO/dwc-plug" && find dwc -type f) | while read -r f; do put "$UNDO/dwc-plug/$f" "$PLUG/$f"; done
  [ -d "$UNDO/dwc-root/dwc" ] && (cd "$UNDO/dwc-root" && find dwc -type f) | while read -r f; do put "$UNDO/dwc-root/$f" "$ROOT/$f"; done
  while IFS= read -r f; do [ -n "$f" ] && rm -f "$f"; done < "$UNDO/new.txt"
  while IFS=$'\t' read -r f dst; do [ -n "$f" ] && { mkdir -p "$(dirname "$PLUG/dsf/$f")"; mv "$dst" "$PLUG/dsf/$f"; }; done < "$UNDO/moved.txt"
  while IFS=$'\t' read -r i f; do [ -n "$i" ] && { mkdir -p "$(dirname "$f")"; mv "$UNDO/stale/$i/$(basename "$f")" "$f"; }; done < "$UNDO/stale.txt"
  cp -p "$UNDO/WorkshopService.json" "$MANIFEST"
  group_fix
  start_all
}

arc=0
apply || arc=$?
if [ "$arc" = 0 ]; then
  "$PM" list 2>/dev/null | grep -i "Workshop - \(Pi Service\|RS485\|Vision\)" || true
  say "done: WorkshopService $VER installed. Backup kept in $BK. Reload every DWC tab (and the kiosk) and check machine.enabledPlugins."
  exit 0
fi
echo "INSTALL FAILED: restoring the state found before this run" >&2
if restore; then
  echo "restored: WorkshopService $INSTALLED is back (leftovers too). Nothing of $VER stays installed." >&2
  exit 5
fi
KEEP_WORK=1
echo "RESTORE FAILED too: the pre-install copy is in $UNDO, the durable backup in $BK" >&2
exit 7
