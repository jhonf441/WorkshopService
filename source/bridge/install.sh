#!/bin/sh
# Installs the workshop G-code bridge as a systemd service.
#
#   sudo ./install.sh            install / update (same as "install")
#   sudo ./install.sh control    (re)write only the rule that lets the Services page start / stop the bridge
#   sudo ./install.sh no-control remove that rule
#   sudo ./install.sh uninstall  remove the unit, the polkit rule and /opt/workshop-bridge (the SD data stays)
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
DEST=/opt/workshop-bridge
SD=/opt/dsf/sd
UNIT_DIR=/etc/systemd/system
POLKIT=/etc/polkit-1/rules.d/49-workshop-gcode-bridge.rules
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "This needs root: run it with sudo." >&2
  exit 1
fi

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
  user="$(run_user)"
  if ! sudo -u "$user" python3 -c "import dsf.connections" >/dev/null 2>&1; then
    echo "WARNING: python3 of $user cannot import dsf.connections (dsf-python). The bridge needs it." >&2
  fi

  echo "1. Code to $DEST"
  install -d -m 755 "$DEST"
  install -m 644 "$HERE/gcode_bridge.py" "$DEST/gcode_bridge.py"
  # safe stop / resume of live jobs (2026-10-22): the bridge starts without these two, but then it has no safe stop
  install -m 644 "$HERE/live_resume.py" "$DEST/live_resume.py"
  install -m 644 "$HERE/live_stop.py" "$DEST/live_stop.py"

  echo "2. SD folders"
  ensure_sd_dir "$SD/sys/workshop/config" "$user"
  ensure_sd_dir "$SD/sys/workshop/data" "$user"

  echo "3. Unit"
  sed -e "s#__USER__#$user#" -e "s#__DIR__#$DEST#" -e "s#__SD__#$SD#" "$HERE/$UNIT.service" > "$UNIT_DIR/$UNIT.service"
  systemctl daemon-reload
  systemctl enable "$UNIT"
  systemctl restart "$UNIT"
  sleep 2
  systemctl --no-pager --lines=8 status "$UNIT" || true
  echo "4. Control from the Services page (polkit, only this unit)"
  do_control
  echo
  echo "Installed."
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
  systemctl disable --now "$UNIT" 2>/dev/null || true
  rm -f "$UNIT_DIR/$UNIT.service" "$POLKIT"
  systemctl daemon-reload
  rm -rf "$DEST"
  echo "Bridge removed (unit, polkit rule and $DEST). $SD/sys/workshop/{config,data} were not touched."
}

case "${1:-install}" in
  install) do_install ;;
  control) do_control ;;
  no-control) do_no_control ;;
  uninstall) do_uninstall ;;
  *) echo "usage: sudo $0 [install|control|no-control|uninstall]" >&2; exit 2 ;;
esac
