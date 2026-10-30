#!/bin/bash
# Generic installer / updater of WorkshopService on a Duet 3 + Raspberry Pi (SBC), over SSH.
# FIRST install (the plugin is not on the Pi yet): it runs DSF's own "PluginManager install" with the zip, which gives the
# files the owner and permissions DSF needs, starts the service and adds it to DWC's enabled plugins.
# UPDATE (already installed): it copies only the files that changed (it never runs PluginManager install over an installed
# plugin: that uninstalls it and deletes its folder first). Install with the machine IDLE: the service is stopped for a few seconds.
# It needs only the zip: the files are taken from inside it. --repo (a clone of the repository) is optional.
#
#   tools/install.sh --host HOST --user USER --version X.Y.Z --zip FILE [options]
#   tools/install.sh --host HOST --user USER --rollback X.Y.Z [options]
#
# Every value can also come from the environment:
#   WORKSHOP_HOST  WORKSHOP_USER  WORKSHOP_VERSION  WORKSHOP_ZIP  WORKSHOP_DSF_ROOT (default /opt/dsf)
#   WORKSHOP_SSH_OPTS (extra ssh/scp options, e.g. "-i ~/.ssh/key -p 2222")  WORKSHOP_LANG (es|en, default en)
#   WORKSHOP_WORK (local scratch folder, default a temporary one)  WORKSHOP_REMOTE_TMP (scratch folder on the Pi, default /tmp/workshop-install-<version>)
#
# Options:
#   --host H           address or name of the Raspberry Pi
#   --user U           login user on the Pi (it must be able to write /opt/dsf/plugins, or use --sudo)
#   --version V        version being installed (must match the version inside the zip)
#   --zip F            build of the service page: WorkshopService-<version>.zip (contains plugin.json and dwc/)
#   --repo DIR         WorkshopService repository to take the files from (default: the one this script is in, if it is one;
#                      without it the files inside the zip are used)
#   --dsf-root DIR     DSF folder on the Pi (default /opt/dsf)
#   --ssh-opts "..."   extra options for ssh and scp
#   --stop "A B"       plugins to stop before and start after (default: those that depend on WorkshopService and have a backend)
#   --sudo             run the remote part with sudo (files are given back to dsf:dsf)
#   --skip-preflight   do not run the pre-install check
#   --dry-run          show what would be copied and stop (does not change the Pi)
#   --rollback V       put back the files saved before installing V (see docs/INSTALL.md)
#   --lang L           language of the preflight texts: es or en
set -euo pipefail

HOST="${WORKSHOP_HOST:-}"; USER_="${WORKSHOP_USER:-}"; VER="${WORKSHOP_VERSION:-}"; ZIP="${WORKSHOP_ZIP:-}"
ROOT="${WORKSHOP_DSF_ROOT:-/opt/dsf}"; SSH_OPTS="${WORKSHOP_SSH_OPTS:-}"; LANG_="${WORKSHOP_LANG:-en}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; REPO="$(cd "$HERE/.." && pwd)"
# Local Python 3: "python3" (Linux, macOS) or "python" / "py -3" (Windows, where python3 is only a Microsoft Store shortcut)
PYL=""
for c in python3 python "py -3"; do
  # shellcheck disable=SC2086
  if $c -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then PYL="$c"; break; fi
done
STOP=""; SUDO=0; SKIP_PRE=0; DRY=0; ROLLBACK=""; WORK="${WORKSHOP_WORK:-}"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "[install] $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --user) USER_="$2"; shift 2;;
    --version) VER="$2"; shift 2;;
    --zip) ZIP="$2"; shift 2;;
    --repo) REPO="$2"; shift 2;;
    --dsf-root) ROOT="$2"; shift 2;;
    --ssh-opts) SSH_OPTS="$2"; shift 2;;
    --stop) STOP="$2"; shift 2;;
    --sudo) SUDO=1; shift;;
    --skip-preflight) SKIP_PRE=1; shift;;
    --dry-run) DRY=1; shift;;
    --rollback) ROLLBACK="$2"; shift 2;;
    --lang) LANG_="$2"; shift 2;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d'; exit 0;;
    *) die "unknown option: $1 (use --help)";;
  esac
done

[ -n "$HOST" ] || die "missing --host (or WORKSHOP_HOST)"
[ -n "$USER_" ] || die "missing --user (or WORKSHOP_USER)"
[ -n "$ROLLBACK" ] && VER="$ROLLBACK"
[ -n "$VER" ] || die "missing --version (or WORKSHOP_VERSION)"
case "$VER" in *[!0-9A-Za-z._-]*|"") die "bad version: $VER";; esac
case "$ROOT" in /*|[A-Za-z]:/*) ;; *) die "--dsf-root must be an absolute path";; esac
case "$LANG_" in es|en) ;; *) die "--lang must be es or en";; esac

# shellcheck disable=SC2206
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 $SSH_OPTS)
# shellcheck disable=SC2206
SCP=(scp -q -o BatchMode=yes -o ConnectTimeout=10 $SSH_OPTS)
TARGET="$USER_@$HOST"
TMP_REMOTE="${WORKSHOP_REMOTE_TMP:-/tmp/workshop-install-$VER}"

cleanup() { [ -n "${OWN_WORK:-}" ] && rm -rf "$OWN_WORK"; return 0; }
trap cleanup EXIT
if [ -z "$WORK" ]; then OWN_WORK="$(mktemp -d)"; WORK="$OWN_WORK"; else mkdir -p "$WORK"; fi

# Runs the script on stdin on the Pi with the given NAME=value variables (through sudo when --sudo is used).
remote_run() {
  local envs="" a
  for a in "$@"; do envs="$envs $(printf '%q' "$a")"; done
  if [ "$SUDO" = 1 ]; then "${SSH[@]}" "$TARGET" "sudo -n env$envs bash -s"; else "${SSH[@]}" "$TARGET" "env$envs bash -s"; fi
}

# ---------------------------------------------------------------- rollback
rollback() {
  say "rolling back to the state saved before $VER on $HOST"
  [ "$DRY" = 1 ] && { say "dry run: nothing changed"; return 0; }
  remote_run "VER=$VER" "ROOT=$ROOT" "DO_SUDO=$SUDO" <<'REMOTE'
set -e
PL="$ROOT/plugins"; BK="$HOME/sd-backup/WorkshopService-pre-$VER"
[ "$DO_SUDO" = 1 ] && BK="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/sd-backup/WorkshopService-pre-$VER"
[ -d "$BK" ] || { echo "no backup at $BK"; exit 3; }
PM="$ROOT/bin/PluginManager"
for id in $(cat "$BK/stopped.txt" 2>/dev/null); do "$PM" stop "$id" || true; done
"$PM" stop WorkshopService || true
sleep 2
(cd "$BK/dsf" && find . -type f) | while read -r f; do mkdir -p "$PL/WorkshopService/dsf/$(dirname "$f")"; cat "$BK/dsf/$f" > "$PL/WorkshopService/dsf/$f"; done
for f in $(cat "$BK/new-files.txt" 2>/dev/null); do rm -f "$PL/WorkshopService/dsf/$f"; done
cp "$BK/WorkshopService.json" "$PL/WorkshopService.json"
if [ -d "$BK/dwc" ]; then
  for d in js css; do for f in "$BK/dwc/$d"/*; do [ -f "$f" ] || continue; b=$(basename "$f"); cp "$f" "$PL/WorkshopService/dwc/$d/$b"; cp "$f" "$ROOT/dwc/$d/$b"; done; done
fi
python3 - <<PY
import glob, json, os
d = json.load(open('$PL/WorkshopService.json')); ref = {os.path.basename(f) for f in d['dwcFiles']}
for sub in ('$ROOT/dwc/js', '$ROOT/dwc/css', '$PL/WorkshopService/dwc/js', '$PL/WorkshopService/dwc/css'):
    for f in glob.glob(sub + '/WorkshopService.*'):
        if os.path.basename(f) not in ref: os.remove(f); print('removed', f)
PY
[ "$DO_SUDO" = 1 ] && chown -R dsf:dsf "$PL/WorkshopService" "$PL/WorkshopService.json" || true
"$PM" reload WorkshopService
"$PM" start WorkshopService
sleep 3
for id in $(cat "$BK/stopped.txt" 2>/dev/null); do "$PM" start "$id" || true; done
grep -o '"version":"[^"]*"' "$PL/WorkshopService.json" | head -1
REMOTE
  say "rollback done. Check the plugin list in DWC and reload every DWC tab."
}

# ---------------------------------------------------------------- local checks
local_checks() {
  [ -n "$PYL" ] || die "Python 3 not found on this computer (tried python3, python, py -3): install it to run this script"
  [ -n "$ZIP" ] || die "missing --zip (or WORKSHOP_ZIP): the build of the service page"
  [ -f "$ZIP" ] || die "zip not found: $ZIP"
  mkdir -p "$WORK/build"; rm -rf "$WORK/build"; mkdir -p "$WORK/build"
  (cd "$WORK/build" && unzip -q "$ZIP") || die "cannot unzip $ZIP"
  [ -f "$WORK/build/plugin.json" ] || die "the zip has no plugin.json"
  [ -d "$WORK/build/dwc/js" ] || die "the zip has no dwc/js"
  local zv; zv="$($PYL - "$WORK/build/plugin.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["version"])
PY
)"
  zv="$(printf '%s' "$zv" | tr -d '')"
  [ "$zv" = "$VER" ] || die "the zip is version $zv, not $VER"
  say "zip OK (version $zv)"
  # where the files come from: the repository (if there is one) or the zip itself
  if [ -d "$REPO/dsf" ] && [ -f "$REPO/plugin.json" ]; then
    SRC_DSF="$REPO/dsf"; SRC_MANIFEST="$REPO/plugin.json"; say "files from the repository: $REPO"
  else
    SRC_DSF="$WORK/build/dsf"; SRC_MANIFEST="$WORK/build/plugin.json"; say "no repository: files taken from inside the zip"
  fi
  [ -d "$SRC_DSF" ] || die "the zip has no dsf/ folder (it is not a build of WorkshopService)"
}

# Is WorkshopService already on the Pi? (a first install and an update are different operations)
installed_on_pi() {
  "${SSH[@]}" "$TARGET" "[ -f '$ROOT/plugins/WorkshopService.json' ]"
}

# ---------------------------------------------------------------- preflight
run_preflight() {
  if [ "$SKIP_PRE" = 1 ]; then say "preflight skipped"; return 0; fi
  say "preflight on $HOST"
  if [ ! -f "$SRC_DSF/preflight_cli.py" ]; then say "preflight skipped: this build has no dsf/preflight_cli.py (older than 2.19.1)"; return 0; fi
  "${SSH[@]}" "$TARGET" "rm -rf '$TMP_REMOTE/pre' && mkdir -p '$TMP_REMOTE/pre/dsf/i18n'"
  "${SCP[@]}" "$SRC_DSF/preflight_cli.py" "$SRC_DSF/preflight.py" "$SRC_DSF/messages.py" "$SRC_DSF/paths.py" "$TARGET:$TMP_REMOTE/pre/dsf/"
  "${SCP[@]}" "$SRC_DSF/i18n/es.json" "$SRC_DSF/i18n/en.json" "$TARGET:$TMP_REMOTE/pre/dsf/i18n/"
  "${SCP[@]}" "$WORK/build/plugin.json" "$TARGET:$TMP_REMOTE/pre/plugin.json"
  local rc=0
  "${SSH[@]}" "$TARGET" "WORKSHOP_DSF_ROOT='$ROOT' PYTHONDONTWRITEBYTECODE=1 python3 '$TMP_REMOTE/pre/dsf/preflight_cli.py' --lang $LANG_ --manifest '$TMP_REMOTE/pre/plugin.json'" || rc=$?
  if [ "$rc" != 0 ]; then die "the pre-install check found errors: fix them (or use --skip-preflight at your own risk)"; fi
}

# ---------------------------------------------------------------- install
stage_files() {
  S="$WORK/stage"; rm -rf "$S"; mkdir -p "$S/dsf" "$S/dwc"
  (cd "$SRC_DSF" && find . -maxdepth 2 \( -name "*.py" -o -name "*.json" \) ! -name config.json ! -path "./fixtures/*" ! -path "*/__pycache__/*" -type f | sort \
    | while read -r f; do echo "$(md5sum "$f" | cut -d' ' -f1)  $f"; done) > "$WORK/local.md5"
  remote_run "ROOT=$ROOT" > "$WORK/remote.md5" <<'REMOTE'
cd "$ROOT/plugins/WorkshopService/dsf" 2>/dev/null || exit 0
find . -maxdepth 2 \( -name "*.py" -o -name "*.json" \) ! -name config.json -type f | sort | while read -r f; do echo "$(md5sum "$f" | cut -d' ' -f1)  $f"; done
REMOTE
  CHANGED="$(diff "$WORK/local.md5" "$WORK/remote.md5" | grep '^<' | sed 's/^< *[0-9a-f]*  //' || true)"
  say "files that differ from the Pi:"; echo "${CHANGED:-  (none)}"
  for f in $CHANGED; do mkdir -p "$S/dsf/$(dirname "$f")"; cp "$SRC_DSF/$f" "$S/dsf/$f"; done
  # files that exist on the Pi but not in this version are kept (rollback removes only the new ones)
  echo "$CHANGED" > "$WORK/changed.txt"
  cp -r "$WORK/build/dwc/js" "$WORK/build/dwc/css" "$S/dwc/"
}

push() {
  "${SSH[@]}" "$TARGET" "rm -rf '$TMP_REMOTE/in' && mkdir -p '$TMP_REMOTE/in'"
  "${SCP[@]}" -r "$S/dsf" "$S/dwc" "$TARGET:$TMP_REMOTE/in/"
  "${SCP[@]}" "$WORK/build/plugin.json" "$TARGET:$TMP_REMOTE/in/plugin.json"
  "${SCP[@]}" "$SRC_MANIFEST" "$TARGET:$TMP_REMOTE/in/plugin-repo.json"
}

apply() {
  remote_run "VER=$VER" "ROOT=$ROOT" "IN=$TMP_REMOTE/in" "STOP=$STOP" "DO_SUDO=$SUDO" <<'REMOTE'
set -e
PL="$ROOT/plugins"; PM="$ROOT/bin/PluginManager"
HOME_DIR="$HOME"; [ "$DO_SUDO" = 1 ] && HOME_DIR="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"
BK="$HOME_DIR/sd-backup/WorkshopService-pre-$VER"
mkdir -p "$BK/dsf" "$BK/dwc/js" "$BK/dwc/css"
# 1. plugins that depend on the service and have a backend: stop them first, start them again at the end
if [ -z "$STOP" ]; then
  STOP="$(python3 - <<PY
import glob, json, os
out = []
for p in sorted(glob.glob('$PL/*.json')):
    try: d = json.load(open(p))
    except Exception: continue
    if d.get('id') in (None, 'WorkshopService'): continue
    deps = list(d.get('sbcPluginDependencies') or []) + list(d.get('dwcDependencies') or [])
    if 'WorkshopService' in deps and d.get('sbcExecutable') and os.path.isdir('$PL/' + d['id']): out.append(d['id'])
print(' '.join(out))
PY
)"
fi
echo "$STOP" > "$BK/stopped.txt"
# 2. backup (-n: a second run never overwrites the first backup)
cp -n "$PL/WorkshopService.json" "$BK/" 2>/dev/null || true
(cd "$IN/dsf" 2>/dev/null && find . -type f) | while read -r f; do
  mkdir -p "$BK/dsf/$(dirname "$f")"
  if [ -f "$PL/WorkshopService/dsf/$f" ]; then cp -n "$PL/WorkshopService/dsf/$f" "$BK/dsf/$f" 2>/dev/null || true; else echo "$f" >> "$BK/new-files.txt"; fi
done
for d in js css; do for f in "$PL/WorkshopService/dwc/$d"/WorkshopService.*; do [ -f "$f" ] && cp -n "$f" "$BK/dwc/$d/" 2>/dev/null || true; done; done
# 3. stop, copy, manifest
for id in $STOP; do "$PM" stop "$id" || true; done
"$PM" stop WorkshopService || true
sleep 2
mkdir -p "$PL/WorkshopService/dsf" "$PL/WorkshopService/dwc/js" "$PL/WorkshopService/dwc/css"
(cd "$IN/dsf" 2>/dev/null && find . -type f) | while read -r f; do mkdir -p "$PL/WorkshopService/dsf/$(dirname "$f")"; cat "$IN/dsf/$f" > "$PL/WorkshopService/dsf/$f"; done
for d in js css; do for f in "$IN/dwc/$d"/*; do b=$(basename "$f"); cp "$f" "$PL/WorkshopService/dwc/$d/$b"; cp "$f" "$ROOT/dwc/$d/$b"; done; done
python3 - <<PY
import json, os
p = '$PL/WorkshopService.json'
d = json.load(open(p)) if os.path.exists(p) else {}
build = json.load(open('$IN/plugin.json'))      # built manifest (dwcFiles with the new hashes)
repo = json.load(open('$IN/plugin-repo.json'))  # repository manifest (dsfFiles, data)
for k, v in build.items():
    if k not in ('dwcFiles', 'dsfFiles', 'data') and k not in d: d[k] = v
d['version'] = '$VER'
d['dsfFiles'] = repo.get('dsfFiles', d.get('dsfFiles', []))
d['data'] = repo.get('data', d.get('data'))
d['sbcPythonDependencies'] = repo.get('sbcPythonDependencies', d.get('sbcPythonDependencies', []))
d['dwcFiles'] = sorted('%s/%s' % (k, f) for k in ('css', 'js') for f in os.listdir('$IN/dwc/' + k))  # ONLY the files of the new build
json.dump(d, open(p, 'w'), separators=(',', ':'), ensure_ascii=False)
print('manifest', d['version'])
PY
if [ "$DO_SUDO" = 1 ]; then
  chown -R dsf:dsf "$PL/WorkshopService" "$PL/WorkshopService.json" || true
else
  # What this login user created (new files, folders) must be usable by DSF, which runs as "dsf": group dsf, group-writable.
  # Without it DSF cannot update or uninstall the plugin later ("Access to the path ... is denied").
  chgrp -R dsf "$PL/WorkshopService" "$PL/WorkshopService.json" 2>/dev/null || true
  chmod -R g+rwX "$PL/WorkshopService" 2>/dev/null || true
  chmod g+rw "$PL/WorkshopService.json" 2>/dev/null || true
fi
# the executable declared in the manifest must have the execute bit (a copied file does not keep it)
EXE="$(python3 -c "import json; print(json.load(open('$PL/WorkshopService.json')).get('sbcExecutable') or '')")"
[ -n "$EXE" ] && chmod +x "$PL/WorkshopService/dsf/$EXE" 2>/dev/null || true
if find "$PL/WorkshopService" ! -group dsf 2>/dev/null | grep -q .; then
  echo "WARNING: some files are not in the group dsf (this user is not in it): DSF will not be able to update or uninstall them. Run again with --sudo."
fi
# 4. reload and start
"$PM" reload WorkshopService
"$PM" start WorkshopService
sleep 3
for id in $STOP; do "$PM" start "$id" || true; done
# 5. remove old bundles that are not in the manifest
python3 - <<PY
import glob, json, os
d = json.load(open('$PL/WorkshopService.json')); ref = {os.path.basename(f) for f in d['dwcFiles']}
for sub in ('$ROOT/dwc/js', '$ROOT/dwc/css', '$PL/WorkshopService/dwc/js', '$PL/WorkshopService/dwc/css'):
    for f in glob.glob(sub + '/WorkshopService.*'):
        if os.path.basename(f) not in ref: os.remove(f); print('removed', f)
PY
echo "backup kept in $BK"
REMOTE
}

# FIRST install: DSF's own installer does what a copy cannot (owner dsf, permissions, executable bit, pip packages).
first_install() {
  say "WorkshopService is not on $HOST yet: first install with PluginManager"
  if [ "$DRY" = 1 ]; then say "dry run: PluginManager install of $(basename "$ZIP"), start, and enabling in DWC"; return 0; fi
  "${SSH[@]}" "$TARGET" "mkdir -p '$TMP_REMOTE'"
  "${SCP[@]}" "$ZIP" "$TARGET:$TMP_REMOTE/WorkshopService-$VER.zip"
  remote_run "VER=$VER" "ROOT=$ROOT" "ZIPR=$TMP_REMOTE/WorkshopService-$VER.zip" <<'REMOTE'
set -e
PM="$ROOT/bin/PluginManager"
out="$("$PM" install "$ZIPR" 2>&1)" || true
echo "$out"
echo "$out" | grep -q "Plugin installed" || { echo "PluginManager did not install the plugin"; exit 3; }
"$PM" start WorkshopService
sleep 3
# DWC cannot load the page of a plugin whose process is already running: list it as enabled in DWC's settings
# (the same file DWC writes; sent through DWC's own file API so the owner stays dsf)
python3 - <<PY
import json, os, subprocess, sys, tempfile
p = '$ROOT/sd/sys/dwc-settings.json'
try:
    d = json.load(open(p))
except Exception as e:
    print('dwc-settings.json not readable (%s): enable WorkshopService in DWC > Settings > Plugins' % e); sys.exit(0)
en = d.setdefault('machine', {}).setdefault('enabledPlugins', [])
if 'WorkshopService' in en:
    print('WorkshopService already enabled in DWC'); sys.exit(0)
en.insert(0, 'WorkshopService')  # first: DWC loads plugins in this order and every other plugin depends on the service
tmp = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
json.dump(d, tmp, separators=(',', ':')); tmp.close()
r = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '-X', 'PUT', '-H', 'Content-Type: application/octet-stream',
                    '--data-binary', '@' + tmp.name, 'http://localhost/machine/file/sys/dwc-settings.json'], capture_output=True, text=True)
os.unlink(tmp.name)
print('WorkshopService added to the enabled plugins of DWC (HTTP %s)' % r.stdout.strip() if r.stdout.strip() in ('200', '201') else 'could not write dwc-settings.json (HTTP %s): enable WorkshopService in DWC > Settings > Plugins' % r.stdout.strip())
PY
REMOTE
}

verify() {
  say "verifying"
  local out
  out="$(remote_run "VER=$VER" "ROOT=$ROOT" <<'REMOTE'
python3 - <<PY
import json, os, subprocess, sys, time
ok = True
d = json.load(open('$ROOT/plugins/WorkshopService.json'))
print('manifest version:', d.get('version'))
if d.get('version') != '$VER': ok = False; print('FAIL: the manifest is not $VER')
alive = False
for _ in range(15):
    r = subprocess.run(['pgrep', '-f', 'WorkshopService/dsf/main.py'], capture_output=True, text=True)
    if r.stdout.strip(): alive = True; break
    time.sleep(1)
print('service process:', 'running' if alive else 'NOT running')
ok = ok and alive
try:
    en = json.load(open('$ROOT/sd/sys/dwc-settings.json')).get('machine', {}).get('enabledPlugins', [])
    print('enabledPlugins:', len(en), 'WorkshopService' in en and 'with WorkshopService' or 'WITHOUT WorkshopService')
    if 'WorkshopService' not in en: ok = False
except Exception as e:
    print('enabledPlugins: could not read (%s)' % e)
sys.exit(0 if ok else 2)
PY
REMOTE
)" || { echo "$out"; die "verification failed: see docs/INSTALL.md (Rollback)"; }
  echo "$out"
}

main() {
  if [ -n "$ROLLBACK" ]; then rollback; return 0; fi
  local_checks
  run_preflight
  if installed_on_pi; then
    stage_files
    if [ "$DRY" = 1 ]; then say "dry run: nothing changed on $HOST"; return 0; fi
    push
    apply
  else
    first_install
    [ "$DRY" = 1 ] && { say "dry run: nothing changed on $HOST"; return 0; }
  fi
  verify
  say "done: WorkshopService $VER on $HOST. Reload every DWC tab (and the kiosk) and check machine.enabledPlugins."
}
main
