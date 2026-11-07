#!/bin/sh
# Installs the workshop G-code bridge as a systemd service.
#
#   sudo ./install.sh            install / update (same as "install")
#   sudo ./install.sh control    (re)write only the rule that lets the Services page start / stop the bridge
#   sudo ./install.sh no-control remove that rule
#   sudo ./install.sh uninstall  remove the unit, the polkit rule and /opt/workshop-bridge (the SD data stays)
#   sudo ./install.sh guard      set who may send orders (see below) without reinstalling
#   sudo ./install.sh rollback   go back to the code and the unit of the previous install (kept in /opt/workshop-bridge.prev)
#   ./install.sh status          what is installed (version, unit state, previous version); needs no root
#   add --force to install / rollback / uninstall while the bridge is IN USE (see below)
#
# IN USE: install, rollback and uninstall restart or remove the bridge, which cuts every connected program. They REFUSE (exit 3) while the
# state file the bridge writes (fresh, under 15 s old) says a live job is open, orders are pending, or an order arrived in the last 30 s,
# unless --force (or BRIDGE_FORCE=1) is given. A state that is missing, unreadable or old counts as "not in use" (a bridge that stopped
# writing is not running a job). If the check itself cannot run (no python3) it refuses too.
# BACKUP: before copying, the installed code and the unit go to /opt/workshop-bridge.prev (one generation; installing the same code again
# keeps the older backup). bridge.json and the data files are never touched by install or rollback.
#
# WHO MAY SEND ORDERS (Duet3D review): a bridge with no password, no allowed list and no trusted address refuses every order
# from the network (queries and the Pi itself still work). "install" and "guard" therefore ask for one of them when none is
# set, in this order of preference:
#   BRIDGE_PASSWORD=<text>     a password (min 4 characters): clients type "BRIDGE KEY <text>" before their orders
#   BRIDGE_ALLOW=ip,ip,net     an allow-list (for example the PC: BRIDGE_ALLOW=192.0.2.16): only those addresses connect and order
#   BRIDGE_TRUST=ip,ip         trusted addresses: they order without a password
# With none of them and a terminal, it asks; without a terminal it only says so and installs (the bridge then answers queries only).
#
# What "install" does, in order (nothing is deleted):
#   1. copies gcode_bridge.py, live_resume.py and live_stop.py to /opt/workshop-bridge (root-owned);
#   2. makes sure 0:/sys/workshop/config and /data exist and the bridge user can write there;
#   3. writes /etc/systemd/system/workshop-gcode-bridge.service, enables it and starts it;
#   4. writes /etc/polkit-1/rules.d/49-workshop-gcode-bridge.rules: the user dsf (the Workshop Service) may start and
#      stop ONLY the unit workshop-gcode-bridge.service, so the Services page can start / stop the bridge. Nothing
#      else (no sudo: DSF starts its plugins without the right to change user). "sudo ./install.sh no-control" removes it.
set -eu

UNIT=workshop-gcode-bridge
# BRIDGE_DEST / BRIDGE_SD / BRIDGE_UNIT_DIR / BRIDGE_POLKIT exist only for the tests on a scratch root (bridge/tests/test_install_sh.py);
# sudo does not pass the environment on, so a normal run always uses the real places.
DEST="${BRIDGE_DEST:-/opt/workshop-bridge}"
SD="${BRIDGE_SD:-/opt/dsf/sd}"
UNIT_DIR="${BRIDGE_UNIT_DIR:-/etc/systemd/system}"
POLKIT="${BRIDGE_POLKIT:-/etc/polkit-1/rules.d/49-workshop-gcode-bridge.rules}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PREV="$DEST.prev"
CODE_FILES="gcode_bridge.py live_resume.py live_stop.py"

FORCE="${BRIDGE_FORCE:-0}"
CMD=install
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    *) CMD="$a" ;;
  esac
done

if [ "${BRIDGE_SCRATCH:-}" = 1 ]; then
  if [ -z "${BRIDGE_DEST:-}" ]; then
    echo "BRIDGE_SCRATCH=1 needs BRIDGE_DEST (a scratch folder): refusing to run on the real system." >&2
    exit 1
  fi
elif [ "$CMD" != status ] && [ "$(id -u)" -ne 0 ]; then
  echo "This needs root: run it with sudo." >&2
  exit 1
fi

# 0 = the bridge is in use (the reason is printed), 1 = it is not, 2 = the check could not run
bridge_in_use() {
  f="$SD/sys/workshop/data/bridge-state.json"
  [ -f "$f" ] || return 1
  command -v python3 >/dev/null 2>&1 || return 2
  BSTATE="$f" python3 - <<'PY' || return $?
import json, os, sys, time
f = os.environ["BSTATE"]
try:
    age = time.time() - os.path.getmtime(f)
    with open(f, encoding="utf-8") as fh:
        d = json.load(fh)
except Exception:
    sys.exit(1)          # unreadable: nothing we can tell is running
if age > 15 or not isinstance(d, dict):
    sys.exit(1)          # a bridge that stopped writing is not running a job
act = d.get("activity") if isinstance(d.get("activity"), dict) else {}
job = act.get("live_job") if isinstance(act.get("live_job"), dict) else {}
def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
if job.get("active"):
    print("a live job is open through the bridge")
    sys.exit(0)
if num(act.get("pending_orders")) > 0:
    print("orders are being sent to the machine right now")
    sys.exit(0)
ages = [num(c.get("last_order_age_s")) + age for c in (d.get("clients") or []) if isinstance(c, dict) and isinstance(c.get("last_order_age_s"), (int, float)) and not isinstance(c.get("last_order_age_s"), bool)]
if ages and min(ages) < 30:
    print("an order arrived in the last 30 seconds")
    sys.exit(0)
sys.exit(1)
PY
}

refuse_if_in_use() {
  [ "$FORCE" = 1 ] && return 0
  rc=0
  reason="$(bridge_in_use)" || rc=$?
  if [ "$rc" = 0 ]; then
    echo "REFUSED: the bridge is in use ($reason). Restarting it would cut the program that is sending." >&2
    echo "Wait until the job ends, or run the same command with --force if you are sure." >&2
    exit 3
  fi
  if [ "$rc" = 2 ]; then
    echo "REFUSED: could not check whether the bridge is in use (python3 is missing). Use --force if you are sure." >&2
    exit 3
  fi
}

installed_version() {
  # $1 = a folder with gcode_bridge.py
  [ -f "$1/gcode_bridge.py" ] && sed -n 's/^VERSION = "\(.*\)"/\1/p' "$1/gcode_bridge.py" | head -n 1
}

# the code and the unit that are installed go to $PREV, unless the new code is the same as what is installed
# (then the older backup stays: backing the same code up over itself would lose the way back)
backup_installed() {
  [ -d "$DEST" ] || return 0
  same=1
  for f in $CODE_FILES; do
    cmp -s "$HERE/$f" "$DEST/$f" 2>/dev/null || same=0
  done
  if [ "$same" = 1 ] && [ -d "$PREV" ]; then
    echo "  same code as installed: the previous backup in $PREV is kept"
    return 0
  fi
  rm -rf "$PREV"
  mkdir -p "$PREV"
  for f in $CODE_FILES; do
    [ -f "$DEST/$f" ] && cp -p "$DEST/$f" "$PREV/$f"
  done
  [ -f "$UNIT_DIR/$UNIT.service" ] && cp -p "$UNIT_DIR/$UNIT.service" "$PREV/$UNIT.service"
  echo "  previous code backed up to $PREV ($(installed_version "$PREV" || true))"
}

run_user() {
  # the user the bridge runs as: the one who called sudo, else the owner of this folder
  u="${SUDO_USER:-$(stat -c %U "$HERE")}"
  if [ "$u" = root ]; then
    echo "Run this with sudo from your normal user (the bridge must not run as root)." >&2
    exit 1
  fi
  echo "$u"
}

ensure_sd_dir() {
  d="$1"; user="$2"
  if [ ! -d "$d" ]; then
    mkdir -p "$(dirname "$d")"
    if id dsf >/dev/null 2>&1; then install -d -o dsf -g dsf -m 2775 "$d"; else mkdir -p "$d"; fi
  fi
  if ! sudo -u "$user" test -w "$d"; then
    if getent group dsf >/dev/null 2>&1 && id -nG "$user" | tr ' ' '\n' | grep -qx dsf; then
      chgrp dsf "$d"
      chmod g+ws "$d"
      echo "  $d: group dsf can write now"
    else
      echo "  WARNING: $user cannot write to $d (is $user in the dsf group?)" >&2
    fi
  fi
}

do_install() {
  refuse_if_in_use
  user="$(run_user)"
  if ! sudo -u "$user" python3 -c "import dsf.connections" >/dev/null 2>&1; then
    echo "WARNING: python3 of $user cannot import dsf.connections (dsf-python). The bridge needs it." >&2
  fi

  echo "1. Code to $DEST"
  backup_installed
  install -d -m 755 "$DEST"
  install -m 644 "$HERE/gcode_bridge.py" "$DEST/gcode_bridge.py"
  # safe stop / resume of live jobs (2026-10-22): the bridge starts without these two, but then it has no safe stop
  install -m 644 "$HERE/live_resume.py" "$DEST/live_resume.py"
  install -m 644 "$HERE/live_stop.py" "$DEST/live_stop.py"

  echo "2. SD folders"
  ensure_sd_dir "$SD/sys/workshop/config" "$user"
  ensure_sd_dir "$SD/sys/workshop/data" "$user"

  echo "3. Unit"
  # the unit is written to a temporary file first: a missing template or a failed sed must never leave an EMPTY unit file, which systemd
  # reports as "masked" (it happened once: the folder had no $UNIT.service and the redirection truncated the real unit)
  if [ ! -s "$HERE/$UNIT.service" ]; then
    echo "The template $HERE/$UNIT.service is missing or empty: nothing was changed." >&2
    exit 1
  fi
  tmp="$UNIT_DIR/.$UNIT.service.new"
  sed -e "s#__USER__#$user#" -e "s#__DIR__#$DEST#" -e "s#__SD__#$SD#" "$HERE/$UNIT.service" > "$tmp"
  if [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo "Could not write the unit: nothing was changed." >&2
    exit 1
  fi
  mv "$tmp" "$UNIT_DIR/$UNIT.service"
  systemctl daemon-reload
  systemctl enable "$UNIT"
  systemctl restart "$UNIT"
  sleep 2
  systemctl --no-pager --lines=8 status "$UNIT" || true
  echo "4. Control from the Services page (polkit, only this unit)"
  do_control
  echo "5. Who may send orders"
  do_guard "$user"
  echo
  echo "Installed."
}

do_guard() {
  user="${1:-$(run_user)}"
  conf="$SD/sys/workshop/config/bridge.json"
  ensure_sd_dir "$SD/sys/workshop/config" "$user"
  # the answers go in the environment, not in the command line, so a password never shows in the process list
  if [ -z "${BRIDGE_PASSWORD:-}" ] && [ -z "${BRIDGE_ALLOW:-}" ] && [ -z "${BRIDGE_TRUST:-}" ] && [ -t 0 ]; then
    if sudo -u "$user" env CONF="$conf" python3 -c 'import json,os,sys
try: c=json.load(open(os.environ["CONF"]))
except Exception: c={}
sys.exit(0 if (c.get("password_hash") or c.get("allowed") or c.get("trusted")) else 1)'; then
      echo "  a password, an allowed list or a trusted address is already set: nothing to ask"
    else
      echo "  Nobody is allowed to send orders yet. Type a password for the programs that send G-code (empty = skip)."
      printf "  Password (min 4 characters): "
      stty -echo 2>/dev/null || true
      read -r BRIDGE_PASSWORD || BRIDGE_PASSWORD=""
      stty echo 2>/dev/null || true
      echo
      export BRIDGE_PASSWORD
    fi
  fi
  sudo -u "$user" env CONF="$conf" DEST="$DEST" BRIDGE_PASSWORD="${BRIDGE_PASSWORD:-}" BRIDGE_ALLOW="${BRIDGE_ALLOW:-}" BRIDGE_TRUST="${BRIDGE_TRUST:-}" python3 - <<'PY'
import json, os, secrets, sys
sys.path.insert(0, os.environ["DEST"])
conf = os.environ["CONF"]
try:
    c = json.load(open(conf))
except Exception:
    c = {}
if not isinstance(c, dict):
    c = {}
pw = os.environ.get("BRIDGE_PASSWORD", "")
allow = [x.strip() for x in os.environ.get("BRIDGE_ALLOW", "").split(",") if x.strip()]
trust = [x.strip() for x in os.environ.get("BRIDGE_TRUST", "").split(",") if x.strip()]
changed = False
if pw:
    if len(pw) < 4:
        print("  the password must have at least 4 characters: not set")
    else:
        import gcode_bridge as gb
        salt = secrets.token_hex(8)
        c["password_hash"] = gb.Bridge.hash_password(pw, salt)
        c["password_salt"] = salt
        changed = True
        print("  password set (only its hash is stored)")
if allow:
    c["allowed"] = allow
    changed = True
    print("  allowed list: " + ", ".join(allow))
if trust:
    c["trusted"] = trust
    changed = True
    print("  trusted addresses: " + ", ".join(trust))
if changed:
    tmp = conf + ".new"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=2)
    os.replace(tmp, conf)
if not (c.get("password_hash") or c.get("allowed") or c.get("trusted")):
    print("  WARNING: no password, no allowed list and no trusted address: the bridge answers queries from the network but refuses every order.")
    print("           Set one with: sudo BRIDGE_PASSWORD=... ./install.sh guard   (or BRIDGE_ALLOW=<pc address>, or from Services > G-code bridge)")
PY
}

do_control() {
  if ! id dsf >/dev/null 2>&1; then
    echo "  there is no user dsf here: nothing to allow"
    return 0
  fi
  if [ ! -d "$(dirname "$POLKIT")" ]; then
    echo "  WARNING: there is no polkit here ($(dirname "$POLKIT")): the page will not be able to start / stop the bridge" >&2
    return 0
  fi
  cat > "$POLKIT" <<RULE
// The Workshop Service (user dsf) may start and stop ONLY the G-code bridge unit.
polkit.addRule(function (action, subject) {
  if (action.id == "org.freedesktop.systemd1.manage-units" &&
      subject.user == "dsf" &&
      action.lookup("unit") == "$UNIT.service" &&
      (action.lookup("verb") == "start" || action.lookup("verb") == "stop")) {
    return polkit.Result.YES;
  }
});
RULE
  chmod 644 "$POLKIT"
  echo "  $POLKIT written"
}

do_no_control() {
  rm -f "$POLKIT"
  echo "$POLKIT removed: the Services page can only read the state of the bridge now."
}

do_uninstall() {
  refuse_if_in_use
  systemctl disable --now "$UNIT" 2>/dev/null || true
  rm -f "$UNIT_DIR/$UNIT.service" "$POLKIT"
  systemctl daemon-reload
  rm -rf "$DEST"
  echo "Bridge removed (unit, polkit rule and $DEST). $SD/sys/workshop/{config,data} were not touched."
}

do_rollback() {
  if [ ! -d "$PREV" ] || [ ! -f "$PREV/gcode_bridge.py" ]; then
    echo "Nothing to go back to: $PREV does not exist (the first install has no previous version). Nothing was changed." >&2
    exit 1
  fi
  refuse_if_in_use
  echo "Rolling back $(installed_version "$DEST" || echo '?') -> $(installed_version "$PREV" || echo '?')"
  for f in $CODE_FILES; do
    if [ -f "$PREV/$f" ]; then
      install -m 644 "$PREV/$f" "$DEST/$f"
    fi
  done
  if [ -f "$PREV/$UNIT.service" ]; then
    cp -p "$PREV/$UNIT.service" "$UNIT_DIR/$UNIT.service"
  fi
  systemctl daemon-reload
  systemctl restart "$UNIT"
  sleep 2
  systemctl --no-pager --lines=8 status "$UNIT" || true
  echo "Rolled back. The settings (bridge.json) and the data files were not touched."
}

do_status() {
  v="$(installed_version "$DEST" || true)"
  if [ -z "$v" ]; then
    echo "Not installed ($DEST has no gcode_bridge.py)."
    return 0
  fi
  echo "Installed: bridge $v in $DEST"
  pv="$(installed_version "$PREV" || true)"
  if [ -n "$pv" ]; then echo "Previous:  bridge $pv in $PREV (sudo ./install.sh rollback goes back to it)"; else echo "Previous:  none"; fi
  echo "Unit:      $(systemctl is-active "$UNIT" 2>/dev/null || true) / $(systemctl is-enabled "$UNIT" 2>/dev/null || true)"
  if [ -f "$POLKIT" ]; then echo "Page control (polkit): on"; else echo "Page control (polkit): off"; fi
}

case "$CMD" in
  install) do_install ;;
  control) do_control ;;
  no-control) do_no_control ;;
  guard) do_guard ;;
  uninstall) do_uninstall ;;
  rollback) do_rollback ;;
  status) do_status ;;
  *) echo "usage: sudo $0 [install|rollback|status|control|no-control|guard|uninstall] [--force]" >&2; exit 2 ;;
esac
