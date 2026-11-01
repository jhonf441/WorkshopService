"""The two TCP ports the workshop opens besides DSF's own, in ONE place (the camera relay runs inside the service, Vision runs inside its
plugin). They are not settings: the pages, Vision, the kiosk and the macros know them, so changing one in a file would break them all.
A test (test_ports.py) fails when another module of the service writes one of these numbers.
"""

CAMERA_RELAY = 8090   # camera_relay.py: stream, photos, captures and videos for the screens, Vision and the kiosk
VISION = 8095         # the Vision plugin (OpenCV): detection, calibration, fire watch
