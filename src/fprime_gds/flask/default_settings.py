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

# WebSocket telemetry stream (see fprime_gds.flask.streams). When True the
# /api/stream WebSocket route is registered (provided ``flask-sock`` is
# installed) and the front-end may use it instead of polling /channels and
# /events. When False the route is omitted and the front-end falls back to
# REST polling regardless of its own configuration.
STREAM_ENABLED = os.environ.get("FP_STREAM_ENABLED", "YES") == "YES"

# Per-client outbox depth used by the stream hub. When a client's outbox
# fills, the oldest message is dropped (and a counter is incremented) so
# the F Prime decoder threads are never blocked by a slow consumer.
STREAM_QUEUE_DEPTH = int(os.environ.get("FP_STREAM_QUEUE_DEPTH", "1024"))

# Batch window the stream sender thread waits, after the first envelope
# wakes it up, for more envelopes to accumulate before draining. Smaller
# values give faster updates but more ws.send / browser JSON.parse calls.
# Default (28 ms) is sized for one F Prime frame at 35 Hz; raise this to
# 0.2 (200 ms) to match the legacy ``/channels`` REST poll cadence on
# resource-constrained dashboards.
STREAM_BATCH_WINDOW_S = float(os.environ.get("FP_STREAM_BATCH_WINDOW_S", "0.028"))

# Default transport advertised to the front-end via /api/stream/status.
# Accepts "stream" or "poll". The browser picks this up on first load only;
# the Advanced settings tab toggle then persists a per-browser choice that
# wins on subsequent loads. Set to "poll" to ship a deployment where the
# default first impression is the legacy REST poll (the WS route still
# exists and can be opted into through the UI toggle); set to "stream"
# (default) for the push transport.
STREAM_DEFAULT_TRANSPORT = os.environ.get("FP_STREAM_DEFAULT_TRANSPORT", "stream").lower()

# TODO: load real config
