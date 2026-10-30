"""Single place for the DSF locations on the Raspberry Pi.

Every other module of the service takes its paths from here (a test fails if a
literal /opt/dsf shows up elsewhere). The root can be replaced with the
environment variable WORKSHOP_DSF_ROOT, for tests on another PC or for a
machine whose DSF lives in another folder.
"""
import os

ROOT = (os.environ.get("WORKSHOP_DSF_ROOT") or "/opt/dsf").rstrip("/") or "/opt/dsf"
SD = ROOT + "/sd"                       # virtual SD card (0:/)
SYS = SD + "/sys"                       # 0:/sys
WORKSHOP = SYS + "/workshop"            # 0:/sys/workshop (everything the plugins own)
CONFIG_DIR = WORKSHOP + "/config"       # settings *.json
DATA_DIR = WORKSHOP + "/data"           # database, jobs, trace, flags
ZONES_DIR = WORKSHOP + "/zones"         # work zones p<N>.g
CAMERA_DIR = SD + "/workshop/camera"    # captures and videos (outside sys/ on purpose)
CONF = ROOT + "/conf"                   # DSF configuration and workshop secrets
PLUGINS = ROOT + "/plugins"             # installed plugins
CONFIG_G = SYS + "/config.g"
DWC_SETTINGS = SYS + "/dwc-settings.json"
DSF_CONFIG = CONF + "/config.json"
SECRETS_FILE = CONF + "/workshop-secrets.json"


def sd_file(rel):
    """Path on the Pi of a file given relative to the SD ("sys/config.g")."""
    return SD + "/" + str(rel).lstrip("/")
