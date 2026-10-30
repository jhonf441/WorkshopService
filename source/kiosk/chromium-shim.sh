#!/bin/sh
# the kiosk page must be able to play sound (DWC beep, M300) without a touch first
exec /usr/bin/chromium --autoplay-policy=no-user-gesture-required "$@"
