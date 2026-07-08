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

_standard_pipeline = os.environ.get("STANDARD_PIPELINE_ARGUMENTS", "")
STANDARD_PIPELINE_ARGUMENTS = _standard_pipeline.split("|") if _standard_pipeline else []

SERVE_LOGS = os.environ.get("SERVE_LOGS", "YES") == "YES"

# Optional subpath for reverse-proxy deployments (nasa/fprime#3854).
APPLICATION_ROOT = os.environ.get("FP_GDS_APPLICATION_ROOT", "")

MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # Max length of request is 32MiB

JS_CONFIGURATION_FILE = os.path.join(os.path.dirname(__file__), "static", "js", "config.js")

# TODO: load real config
