#!/bin/bash
# Triggered by swayidle at the idle timeout (2026-10-13: the screen is switched OFF instead of
# animating a bouncing logo in a second Chromium: that animation kept ~1 CPU core busy all night).
# The old version is screensaver-on.sh.bak-20261013.
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
# 2026-10-14: a black lock layer instead of switching the HDMI output off: the signal stays, so the
# screen wakes at once (the DPMS off made the monitor re-sync for seconds). Backup: screensaver-on.sh.bak-20261014
pgrep -x swaylock >/dev/null || swaylock -f -c 000000 -s solid_color -u
