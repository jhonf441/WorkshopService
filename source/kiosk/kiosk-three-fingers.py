#!/usr/bin/env python3
# Closes the DWC kiosk when the touch screen is tapped with THREE fingers at once.
#
# Why fingers at the same time and not a count of taps: normal use of DWC is always one finger at a
# time, so a series of taps (however quick or repeated) can never be mistaken for the gesture.
# Every finger of the session must be a real tap (short, no drag); the session is judged when all
# fingers are up, with the largest number of fingers that were down together.
#
# Cost: none while nobody touches the screen. The script sleeps in select() on the touch device and
# only wakes up for touch events. The USB touch controller can show up late after boot or be
# re-enumerated: the script retries instead of dying (it runs loose in the labwc autostart).
import select
import subprocess
import time

import evdev
from evdev import ecodes

DEVICE_NAME = 'SiS HID Touch Controller'
DEVICE_FALLBACK = '/dev/input/event4'

TAP_MAX_DURATION = 0.4     # a finger that stays down longer is not a tap
MAX_TAP_MOVEMENT_MM = 5.0  # a finger that moves more than this is a drag, not a tap
RETRY_WAIT = 3             # seconds between attempts to open the device
EXIT_KIOSK_FINGERS = 3


def close_kiosk():
    subprocess.run(['pkill', '-f', 'app=http://localhost'])


def find_touch_device():
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        if DEVICE_NAME.lower() in dev.name.lower():
            return dev
    return None


def open_device():
    while True:
        dev = find_touch_device()
        if dev is None:
            try:
                dev = evdev.InputDevice(DEVICE_FALLBACK)
            except OSError:
                dev = None
        if dev is not None:
            return dev
        time.sleep(RETRY_WAIT)


def axis_resolution(dev, code, fallback):
    try:
        info = dict(dev.capabilities().get(ecodes.EV_ABS, []))
        return info[code].resolution or fallback
    except (KeyError, AttributeError):
        return fallback


def run_loop(dev):
    """Raises OSError when the device goes away (USB re-enumeration) so main() reopens it."""
    fd = dev.fileno()
    res_x = axis_resolution(dev, ecodes.ABS_MT_POSITION_X, 35)
    res_y = axis_resolution(dev, ecodes.ABS_MT_POSITION_Y, 48)

    slots = {}              # slot -> {down_time, down_x, down_y, last_x, last_y, max_move_mm}
    cur_slot = 0            # type B protocol: the active slot until the next ABS_MT_SLOT
    peak_fingers = 0        # most fingers down together in this session
    all_taps_valid = True   # no finger of the session dragged or stayed down

    while True:
        r, _, _ = select.select([fd], [], [])
        if not r:
            continue
        for event in dev.read():
            if event.type != ecodes.EV_ABS:
                continue
            if event.code == ecodes.ABS_MT_SLOT:
                cur_slot = event.value
            elif event.code == ecodes.ABS_MT_TRACKING_ID:
                if event.value != -1:
                    slots[cur_slot] = {'down_time': time.monotonic(), 'down_x': None, 'down_y': None,
                                       'last_x': None, 'last_y': None, 'max_move_mm': 0.0}
                    peak_fingers = max(peak_fingers, len(slots))
                else:
                    s = slots.pop(cur_slot, None)
                    if s is not None:
                        duration = time.monotonic() - s['down_time']
                        if duration >= TAP_MAX_DURATION or s['max_move_mm'] > MAX_TAP_MOVEMENT_MM:
                            all_taps_valid = False
                    if not slots:
                        if all_taps_valid and peak_fingers >= EXIT_KIOSK_FINGERS:
                            close_kiosk()
                        peak_fingers = 0
                        all_taps_valid = True
            elif event.code in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y):
                s = slots.get(cur_slot)
                if s is None:
                    continue
                if event.code == ecodes.ABS_MT_POSITION_X:
                    s['last_x'] = event.value
                    if s['down_x'] is None:
                        s['down_x'] = event.value
                else:
                    s['last_y'] = event.value
                    if s['down_y'] is None:
                        s['down_y'] = event.value
                if s['down_x'] is not None and s['down_y'] is not None and s['last_x'] is not None and s['last_y'] is not None:
                    dx_mm = (s['last_x'] - s['down_x']) / res_x
                    dy_mm = (s['last_y'] - s['down_y']) / res_y
                    dist_mm = (dx_mm ** 2 + dy_mm ** 2) ** 0.5
                    if dist_mm > s['max_move_mm']:
                        s['max_move_mm'] = dist_mm


def main():
    while True:
        dev = open_device()
        try:
            run_loop(dev)
        except OSError:
            pass
        finally:
            try:
                dev.close()
            except Exception:
                pass


if __name__ == '__main__':
    main()
