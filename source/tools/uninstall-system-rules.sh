#!/bin/sh
# Removes the system rules that WorkshopService needed OUTSIDE its zip, and tells you what it removed.
#
#   sudo tools/uninstall-system-rules.sh [--dry-run] [--bridge]
#
#   (no option)  removes the sudoers rule /etc/sudoers.d/dsf-power (the shutdown / restart buttons then log an error and
#                the system keeps running), then checks the sudoers syntax with "visudo -c"
#   --bridge     also runs bridge/install.sh uninstall: the unit workshop-gcode-bridge.service, the polkit rule
#                49-workshop-gcode-bridge.rules and /opt/workshop-bridge
#   --dry-run    lists what would be removed and changes nothing (it does not need root)
#
# What it NEVER touches: your data (0:/sys/workshop, /opt/dsf/conf/workshop-*.json), the plugin itself (uninstall it
# from DWC), the AppArmor profile (DSF removes it when the plugin is uninstalled) and the kiosk scripts in your home
# folder (they are yours: docs/INSTALL.md and security.md list them with the line to delete from the autostart).
# WORKSHOP_SUDOERS_FILE overrides the rule's path (used by the tests).
set -eu

SUDOERS="${WORKSHOP_SUDOERS_FILE:-/etc/sudoers.d/dsf-power}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_INSTALL="$HERE/../bridge/install.sh"
DRY=0
BRIDGE=0

for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --bridge) BRIDGE=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "usage: sudo $0 [--dry-run] [--bridge]" >&2; exit 2 ;;
  esac
done

if [ "$DRY" -eq 0 ] && [ -z "${WORKSHOP_SUDOERS_FILE:-}" ] && [ "$(id -u)" -ne 0 ]; then
  echo "This needs root: run it with sudo (or add --dry-run to only list)." >&2
  exit 1
fi

removed=0
if [ -e "$SUDOERS" ]; then
  if [ "$DRY" -eq 1 ]; then
    echo "would remove: $SUDOERS"
  else
    rm -f "$SUDOERS"
    echo "removed: $SUDOERS"
  fi
  removed=1
else
  echo "not present: $SUDOERS"
fi

if [ "$BRIDGE" -eq 1 ]; then
  if [ ! -f "$BRIDGE_INSTALL" ]; then
    echo "bridge/install.sh not found next to this script: run it from the bridge folder (sudo ./install.sh uninstall)" >&2
    exit 1
  fi
  if [ "$DRY" -eq 1 ]; then
    echo "would run: $BRIDGE_INSTALL uninstall (unit workshop-gcode-bridge.service, polkit rule 49-workshop-gcode-bridge.rules, /opt/workshop-bridge)"
  else
    sh "$BRIDGE_INSTALL" uninstall
  fi
fi

if [ "$DRY" -eq 0 ] && [ "$removed" -eq 1 ] && [ -z "${WORKSHOP_SUDOERS_FILE:-}" ] && command -v visudo >/dev/null 2>&1; then
  visudo -c >/dev/null && echo "visudo -c: the remaining sudoers files parse OK"
fi

echo "Your data stays: 0:/sys/workshop, /opt/dsf/conf/workshop-*.json. Uninstall the plugin from DWC to remove its folder."
