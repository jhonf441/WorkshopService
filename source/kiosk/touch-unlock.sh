#!/bin/bash
# touch-unlock.sh -- safety net: a touch on the black lock layer must always take it away.
# Launched from ~/.config/labwc/autostart (it needs the Wayland session).
#
# Why (2026-10-19): after the touch controller re-enumerated on USB, the screen stayed black and ignored
# touches. swayidle's "resume" is the normal way out; this script does not depend on it: it reads the touch
# device itself and, if a touch arrives while swaylock is up and the lock is still there 1.5 s later,
# unlocks it with SIGUSR1 (never kill: labwc would stay locked and draw only black).
# The device is looked up again every time libinput exits, so it survives a USB re-enumeration.
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
OFF="$HOME/screensaver-off.sh"

touch_dev() {
  local n
  n=$(grep -l "SiS" /sys/class/input/event*/device/name 2>/dev/null | head -1 | sed 's#.*/\(event[0-9]*\)/.*#\1#')
  [ -n "$n" ] && echo "/dev/input/$n"
}

while sleep 2; do
  dev=$(touch_dev)
  [ -n "$dev" ] || continue
  libinput debug-events --device "$dev" 2>/dev/null | while read -r _ ev _; do
    [ "$ev" = "TOUCH_DOWN" ] || continue
    pgrep -x swaylock >/dev/null || continue
    sleep 1.5
    if pgrep -x swaylock >/dev/null; then
      "$OFF"
      logger -t touch-unlock "touch on the lock layer did not unlock it: forced unlock"
    fi
  done
done
