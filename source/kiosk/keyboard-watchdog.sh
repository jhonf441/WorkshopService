#!/bin/sh
# keyboard-watchdog.sh -- keeps the kiosk's on-screen keyboard (squeekboard)
# alive. It is launched from ~/.config/labwc/autostart.
#
# Why (2026-10-09): the system launcher (/usr/bin/sbtest, via
# /etc/xdg/autostart/squeekboard.desktop) checks ONLY once at session start
# whether there is a touch screen. If the touch USB enumerates late
# (it happened: it showed up ~1 min after boot) squeekboard never starts and
# no keyboard appears when touching a text field. This watchdog checks every
# 5 s: if there is a touch screen and squeekboard is not running, it starts it (also if it dies).

while true; do
    if ! pgrep -x squeekboard >/dev/null 2>&1; then
        if libinput list-devices 2>/dev/null | grep Capabilities | grep -qw touch; then
            if [ -e /usr/share/squeekboard/output ]; then
                . /usr/share/squeekboard/output
            fi
            /usr/bin/squeekboard >/dev/null 2>&1 &
        fi
    fi
    sleep 5
done
