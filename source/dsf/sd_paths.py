"""Paths of the files of the DSF SD as the Pi sees them."""
import paths
import os

SD = paths.SD


def sd(rel):
    """Path on the Pi of a file on the SD: "sys/workshop/data/x.json" or
    "0:/sys/workshop/data/x.json" -> /opt/dsf/sd/sys/workshop/data/x.json."""
    r = str(rel)
    if len(r) > 1 and r[1] == ":":
        r = r[2:]
    return os.path.join(SD, *r.strip("/").split("/"))
