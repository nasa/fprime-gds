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

import fprime_gds.common.utils.config_manager

# Select uploads directory and create it
uplink_dir = os.environ.get("UP_FILES_DIR", "/tmp/fprime-uplink/")
DOWNLINK_DIR = os.environ.get("DOWN_FILES_DIR", "/tmp/fprime-downlink/")

# Configuration is mostly driven from environment variables
DICTIONARY = os.environ.get("DICTIONARY", None)
ZMQ_TRANSPORT = os.environ.get("ZMQ_TRANSPORT", None)
ZMQ_TRANSPORT = None if ZMQ_TRANSPORT is None else ZMQ_TRANSPORT.split("|")
PORT = int(os.environ.get("TTS_PORT", "50050"), 0)
ADDRESS = os.environ.get("TTS_ADDR", "127.0.0.1")

LOG_DIR = os.environ.get("LOG_DIR", "/tmp/fprime-gds-logs")
SERVE_LOGS = os.environ.get("SERVE_LOGS", "YES") == "YES"
UPLOADED_UPLINK_DEST = uplink_dir
UPLOADS_DEFAULT_DEST = uplink_dir
REMOTE_SEQ_DIRECTORY = "/seq"
MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # Max length of request is 32MiB

# Gds config setup
GDS_CONFIG = fprime_gds.common.utils.config_manager.ConfigManager()

for directory in [LOG_DIR, UPLOADED_UPLINK_DEST, UPLOADS_DEFAULT_DEST, DOWNLINK_DIR]:
    os.makedirs(directory, exist_ok=True)

# TODO: load real config
