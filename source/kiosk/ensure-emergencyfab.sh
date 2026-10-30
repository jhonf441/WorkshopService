#!/bin/sh
# ensure-emergencyfab.sh -- kiosk safety net for machine.enabledPlugins
# of DWC (0:/sys/dwc-settings.json). Copy in the repo: WorkshopService/kiosk/.
#
# Version 2026-10-12 (request 29d of the 2026-10-11 diagnosis): before, it forced the
# list ALWAYS, before launching Chromium, fighting with DWC (DWC keeps its
# own copy of dwc-settings.json and uploads it again). Now:
#  - It ONLY acts if no screen has DWC open: neither the kiosk's Chromium
#    (launch-dwc: "chromium --app=http://localhost") nor another browser
#    connected to the Pi over the network (TCP connection established to port 80 from
#    another machine). If there is one, it touches nothing and notes it.
#  - It only adds the plugins that are MISSING and INSTALLED
#    (/opt/dsf/plugins/<Id>.json). It never removes anything nor touches other keys
#    (nor main.webcam: the Camera no longer uses DWC's camera).
#  - It notes in the log which plugin it had to reactivate (if DWC took it out it is
#    because it could not load it: the reason is in DWC's console, "Failed to
#    load DWC plugin X").
#  - It writes through DSF's file API (the file belongs to the dsf user),
#    like _reactivate in TallerPlugins/build.py.
#
# Log: ~/ensure-emergencyfab.log (trimmed by itself) and the journal
#      (journalctl -t ensure-emergencyfab).
#
# Usage:
#   ~/ensure-emergencyfab.sh                 checks and, if there are no screens, reactivates
#   ~/ensure-emergencyfab.sh --force         reactivates even with screens open
#   ~/ensure-emergencyfab.sh --test          only says what it would do (writes nothing)
#   ~/ensure-emergencyfab.sh -- <command>    after checking, runs <command>
#                                            (in case the autostart used it to
#                                            launch the kiosk: ... -- launch-dwc)
#
# Install (on the Pi, once):
#   cp ~/ensure-emergencyfab.sh ~/ensure-emergencyfab.sh.old
#   (copy this file to ~/ensure-emergencyfab.sh, e.g. with scp from the PC)
#   chmod +x ~/ensure-emergencyfab.sh
#   grep -rn ensure-emergencyfab ~/.config/labwc/autostart ~/.config/autostart 2>/dev/null
#     -> if the old script also launched Chromium (check with
#        grep -n 'chromium\|launch-dwc' ~/ensure-emergencyfab.sh.old), leave
#        that line in the autostart after this one, or use "-- launch-dwc".
#   ~/ensure-emergencyfab.sh --test          (with the kiosk open: it must say
#                                            "screen open, nothing is touched")
# Go back:
#   cp ~/ensure-emergencyfab.sh.old ~/ensure-emergencyfab.sh
#
# NEW plugin: add it to PLUGINS (and the first time to enabledPlugins with
# Plugins > Start, or with build.py --install).

PLUGINS="GlobalsManager ReleaseMgr WorkshopService WorkshopControlBar WorkshopJog
WorkshopWorkbench WorkshopCamera WorkshopVision WorkshopActivity WorkshopPower
WorkshopMotors WorkshopLights WorkshopPiHealth WorkshopPrinting WorkshopRS485
WorkshopConfig"

API="http://localhost/machine/file/0:/sys/dwc-settings.json"
LOG="$HOME/ensure-emergencyfab.log"
DSF_WAIT=90 # maximum seconds waiting for DSF to answer when the Pi boots

force=0
test_only=0
while [ $# -gt 0 ]; do
    case "$1" in
        --force) force=1 ;;
        --test) test_only=1 ;;
        --) shift; break ;;
        *) echo "unknown option: $1" >&2 ;;
    esac
    shift
done

note() {
    line="$(date '+%Y-%m-%d %H:%M:%S') $*"
    echo "$line"
    if [ "$test_only" -eq 0 ]; then
        echo "$line" >>"$LOG" 2>/dev/null
        logger -t ensure-emergencyfab -- "$*" 2>/dev/null
    fi
}

trim_log() {
    if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 200000 ]; then
        tail -n 1000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
}

# Screens with DWC open. Prints a short description (empty = none).
open_screens() {
    if pgrep -f -- '--app=http://localhost' >/dev/null 2>&1; then
        echo "kiosk (the Pi's Chromium)"
    fi
    # browsers of other machines: connections established to port 80
    # (DWC stays connected while the page is open). The Pi's own (127.x / ::1:
    # plugins, bridge) do not count.
    ss -Htn state established '( sport = :80 or sport = :443 )' 2>/dev/null |
        awk '{print $NF}' |
        sed -E -e 's/^\[(.*)\]:[0-9]+$/\1/' -e 't v6' -e 's/:[0-9]+$//' -e ':v6' -e 's/^::ffff://' |
        grep -v -e '^127\.' -e '^::1$' -e '^$' |
        sort -u | sed 's/^/browser on /'
}

run_rest() {
    if [ $# -gt 0 ]; then
        exec "$@"
    fi
    exit 0
}

trim_log

# 1) Open screens -> do not touch (DWC owns the file while it runs).
open="$(open_screens | paste -sd ',' - | sed 's/,/, /g')"
if [ -n "$open" ] && [ "$force" -eq 0 ]; then
    [ "$test_only" -eq 1 ] && note "screen open ($open), nothing is touched"
    run_rest "$@"
fi

# 2) Wait for DSF (when the Pi boots it takes a while to answer).
tmp="$(mktemp)"
deadline=$(($(date +%s) + DSF_WAIT))
while :; do
    code="$(curl -s -o "$tmp" -w '%{http_code}' "$API" 2>/dev/null)"
    [ "$code" = "200" ] && break
    if [ "$(date +%s)" -ge "$deadline" ]; then
        note "ERROR: DSF did not answer in ${DSF_WAIT} s (HTTP $code); nothing was checked"
        rm -f "$tmp"
        run_rest "$@"
    fi
    sleep 3
done

# 3) Add the missing ones (only if they are installed).
installed=""
for p in $PLUGINS; do
    [ -f "/opt/dsf/plugins/$p.json" ] && installed="$installed $p"
done

missing="$(python3 - "$tmp" $installed <<'EOF'
import json, sys
f, wanted = sys.argv[1], sys.argv[2:]
try:
    d = json.load(open(f, encoding="utf-8"))
    enabled = d["machine"]["enabledPlugins"]
except Exception as e:
    print("ERROR " + type(e).__name__)
    sys.exit(0)
missing = [p for p in wanted if p not in enabled]
if missing:
    enabled.extend(missing)
    with open(f + ".new", "w", encoding="utf-8") as o:
        json.dump(d, o)
print(" ".join(missing))
EOF
)"

case "$missing" in
    ERROR*)
        note "ERROR: dwc-settings.json could not be read ($missing); nothing was touched"
        ;;
    "")
        [ "$test_only" -eq 1 ] && note "all good: no plugin is missing"
        ;;
    *)
        if [ "$test_only" -eq 1 ]; then
            note "would reactivate: $missing"
        else
            code="$(curl -s -o /dev/null -w '%{http_code}' -X PUT \
                -H 'Content-Type: application/octet-stream' \
                --data-binary @"$tmp.new" "$API" 2>/dev/null)"
            if [ "$code" = "201" ] || [ "$code" = "200" ] || [ "$code" = "204" ]; then
                note "reactivated (DWC had taken them out of enabledPlugins): $missing${open:+ [forced with screens open: $open]}"
            else
                note "ERROR: dwc-settings.json could not be saved (HTTP $code); missing: $missing"
            fi
        fi
        ;;
esac
rm -f "$tmp" "$tmp.new"
run_rest "$@"
