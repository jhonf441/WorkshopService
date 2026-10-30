#!/bin/sh
# wifi-watchdog.sh -- keeps the Raspberry Pi on the "DUET" Wi-Fi (profile with a fixed IP).
# It is launched from ~/.config/labwc/autostart: it runs INSIDE the
# kiosk session, the only one with permission to manage the network without a
# password (over SSH NetworkManager asks for authentication).
#
# Why (2026-10-10, recurring problem): the kiosk's Wi-Fi menu
#  - shows the network as "fhmesh_..." even if the Pi is on "DUET": the same
#    mesh node broadcasts both networks with the same BSSID;
#  - when "DUET" is tapped it does NOT use the saved profile (with key and fixed IP): it creates a
#    new empty "DUET 1", and that is why it asks for the key. If it is typed, the Pi
#    ends up with another IP (DHCP) and the bridge / the screens cannot find it;
#  - after "Disconnect" (or turning the Wi-Fi off and on) NetworkManager does not
#    reconnect by itself until someone asks.
# Every 20 s: if the Wi-Fi is off it turns it on; it deletes the duplicate
# "DUET <n>"; and if wlan0 is not on the "DUET" profile two rounds in a row,
# it activates it.

PROFILE="DUET"
away=0
while true; do
    if [ "$(nmcli radio wifi 2>/dev/null)" = "disabled" ]; then
        nmcli radio wifi on >/dev/null 2>&1
    fi
    nmcli -t -f NAME connection show 2>/dev/null | grep -E "^${PROFILE} [0-9]+$" | while IFS= read -r dup; do
        nmcli connection delete "$dup" >/dev/null 2>&1
    done
    active=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | grep ':wlan0$' | cut -d: -f1)
    if [ "$active" = "$PROFILE" ]; then
        away=0
    else
        away=$((away + 1))
        if [ "$away" -ge 2 ]; then
            nmcli connection up "$PROFILE" >/dev/null 2>&1
            away=0
        fi
    fi
    sleep 20
done
