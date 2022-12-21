####
# default_settings.py:
#
# Contains default setup for the F prime flask application. Specifically, it is used to pass configuration
# down to the GDS config layers, and is used to specify a dictionary and packet spec for specifying
# the event, channels, and commands setup.
#
# Note: flask configuration is all done via Python files
#
####
import os

# Select uploads directory and create it
uplink_dir = os.environ.get("UP_FILES_DIR", "/tmp/fprime-uplink/")
DOWNLINK_DIR = os.environ.get("DOWN_FILES_DIR", "/tmp/fprime-downlink/")

STANDARD_PIPELINE_ARGUMENTS = os.environ.get("STANDARD_PIPELINE_ARGUMENTS").split("|")

SERVE_LOGS = os.environ.get("SERVE_LOGS", "YES") == "YES"
UPLOADED_UPLINK_DEST = uplink_dir
UPLOADS_DEFAULT_DEST = uplink_dir
REMOTE_SEQ_DIRECTORY = "/seq"
MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # Max length of request is 32MiB


for directory in [UPLOADED_UPLINK_DEST, UPLOADS_DEFAULT_DEST, DOWNLINK_DIR]:
    os.makedirs(directory, exist_ok=True)

# TODO: load real config
