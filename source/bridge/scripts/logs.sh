#!/bin/sh
# Journal of the bridge: warnings and errors only (debug is in the Services page).
journalctl -u workshop-gcode-bridge -f -n 50
