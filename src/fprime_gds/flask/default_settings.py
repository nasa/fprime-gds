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

STANDARD_PIPELINE_ARGUMENTS = os.environ.get("STANDARD_PIPELINE_ARGUMENTS").split("|")

SERVE_LOGS = os.environ.get("SERVE_LOGS", "YES") == "YES"

MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # Max length of request is 32MiB

JS_CONFIGURATION_FILE = os.path.join(os.path.dirname(__file__), "static", "js", "config.js")

# TODO: load real config
