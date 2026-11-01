"""Version of the camera relay contract (port 8090).

The relay used to have no version, so a plugin page and the service could silently disagree. Now `/state` carries `proto`
and the page (WorkshopCamera 09-camera-roles.js) compares it with the one it was written for:

  proto 1   the relay before this field existed (the page sees "no proto" and treats it as 1)
  proto 2   `proto` in /state and one set of English routes (the old Spanish names are gone)
  proto 3   the writes (capture, burst, remove, keep, rename, edit, rerender, timelapse, schedule) are operations of the API: the port only
            serves media, and the one POST left is the upload of a look file (/luts, /luts/remove)

Change PROTO when a route or an answer changes in a way an older page would not understand, and change the same number
in the page (CAMERA_RELAY_PROTO).
"""

PROTO = 3


def describe():
    """What /state publishes about the contract."""
    return {"proto": PROTO}
