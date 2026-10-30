#!/bin/bash
# display-watchdog.sh -- brings the kiosk screen back when it goes black and stops answering.
# Launched from ~/.config/labwc/autostart (it needs the Wayland session).
#
# Why (2026-10-18): the touch monitor sometimes drops its HDMI link and its USB touch controller at the
# same time (it goes to sleep or loses power for a moment). The kernel logs "USB disconnect" for the
# SiS HID Touch Controller and labwc disables the output; nothing re-enables it, and a leftover black lock
# layer (swaylock) hides DWC: the screen stays black and ignores touches until the Pi is rebooted.
# Every 2 s:
#  - if the touch controller came back (its input device changed), take the lock layer away and switch
#    the output on (screensaver-off.sh does both);
# It does NOT toggle outputs (wlr-randr / wlopm off-on): on this Pi a CRTC disable makes vc4 warn and the screen stay black.
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
OFF="$HOME/screensaver-off.sh"

touch_id() { grep -l "SiS" /sys/class/input/event*/device/name 2>/dev/null | sort | tr '\n' ' '; }

last=$(touch_id)
while sleep 2; do
  now=$(touch_id)
  if [ "$now" != "$last" ]; then
    # gone (empty) or back (maybe with another event number): wait for it to settle, then recover
    if [ -n "$now" ]; then
      sleep 2
      "$OFF"
      logger -t display-watchdog "touch controller re-enumerated ($last -> $now): lock layer removed, output switched on"
    fi
    last=$now
    continue
  fi
done
