#!/bin/sh
# Restart the bridge (not while a live job runs: its connections are cut).
sudo systemctl restart workshop-gcode-bridge
systemctl --no-pager --lines=5 status workshop-gcode-bridge
