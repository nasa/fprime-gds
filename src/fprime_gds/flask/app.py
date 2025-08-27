####
# app.py:
#
# This file sets up the flask app, and registers the endpoints for the individual APIs supplied by
# this framework.
#
####
import logging
import os
import sys
import uuid

import flask

# Try to import Compress, but disable compression if not installed
try:
    from flask_compress import Compress
except ImportError:
    Compress = None

import fprime_gds.flask.channels

# Import the Flask API implementations
import fprime_gds.flask.commands
import fprime_gds.flask.errors
import fprime_gds.flask.events
import fprime_gds.flask.json
import fprime_gds.flask.logs
import fprime_gds.flask.sequence
import fprime_gds.flask.stats
import fprime_gds.flask.updown
from fprime_gds.executables.cli import ParserBase, StandardPipelineParser, ConfigDrivenParser

from . import components

# Update logging to avoid redundant messages
logger = logging.getLogger("werkzeug")
logger.setLevel(logging.WARN)
logger = logging.getLogger("downlink")
logger.setLevel(logging.INFO)


def construct_app():
    """
    Constructs the Flask app by taking the following steps:

    1. Setup and configure the app
    2. Setup JSON encoding for Flask and flask_restful to handle F prime types natively
    3. Setup standard pipeline used throughout the system
    4. Create Restful API for registering flask items
    5. Register all restful endpoints

    :return: setup app
    """
    app = flask.Flask(__name__, static_url_path="")
    # Enable compression if it is installed
    if Compress is not None:
        compress = Compress()
        compress.init_app(app)

    app.config.from_object("fprime_gds.flask.default_settings")

    # Override defaults from python files specified in 'FP_FLASK_SETTINGS'
    if "FP_FLASK_SETTINGS" in os.environ:
        app.config.from_envvar("FP_FLASK_SETTINGS")

    # JSON encoding settings
    app.json.default = fprime_gds.flask.json.default
    app.config["RESTFUL_JSON"] = {"default": app.json.default}
    # Standard pipeline creation
    input_arguments = app.config["STANDARD_PIPELINE_ARGUMENTS"]
    args_ns, _ = ParserBase.parse_args(
        [StandardPipelineParser, ConfigDrivenParser], "n/a", input_arguments, client=True
    )
    # Load app configuration from file
    for key, value in args_ns.config_values.get("flask", {}).items():
        app.config[key] = value

    pipeline = components.setup_pipelined_components(app.debug, args_ns)


    # Restful API registration
    api = fprime_gds.flask.errors.setup_error_handling(app)

    # Application routes
    api.add_resource(
        fprime_gds.flask.commands.CommandDictionary,
        "/dictionary/commands",
        resource_class_args=[
            pipeline.dictionaries.command_name,
            pipeline.dictionaries.project_version,
            pipeline.dictionaries.framework_version,
            pipeline.dictionaries.metadata,
        ],
    )
    api.add_resource(
        fprime_gds.flask.commands.CommandHistory,
        "/commands",
        resource_class_args=[pipeline.histories.commands],
    )
    api.add_resource(
        fprime_gds.flask.commands.Command,
        "/commands/<command>",
        resource_class_args=[pipeline],
    )
    api.add_resource(
        fprime_gds.flask.events.EventDictionary,
        "/dictionary/events",
        resource_class_args=[
            pipeline.dictionaries.event_id,
            pipeline.dictionaries.project_version,
            pipeline.dictionaries.framework_version,
            pipeline.dictionaries.metadata,
        ],
    )
    api.add_resource(
        fprime_gds.flask.events.EventHistory,
        "/events",
        resource_class_args=[pipeline.histories.events],
    )
    api.add_resource(
        fprime_gds.flask.channels.ChannelDictionary,
        "/dictionary/channels",
        resource_class_args=[
            pipeline.dictionaries.channel_id,
            pipeline.dictionaries.project_version,
            pipeline.dictionaries.framework_version,
            pipeline.dictionaries.metadata,
        ],
    )
    api.add_resource(
        fprime_gds.flask.channels.ChannelHistory,
        "/channels",
        resource_class_args=[pipeline.histories.channels],
    )
    api.add_resource(
        fprime_gds.flask.updown.Destination,
        "/upload/destination",
        resource_class_args=[pipeline.files.uplinker],
    )
    api.add_resource(
        fprime_gds.flask.updown.FileUploads,
        "/upload/files",
        resource_class_args=[pipeline.files.uplinker, pipeline.up_store],
    )
    api.add_resource(
        fprime_gds.flask.updown.FileDownload,
        "/download/files",
        "/download/files/<string:source>",
        resource_class_args=[pipeline.files.downlinker],
    )
    api.add_resource(
        fprime_gds.flask.sequence.SequenceCompiler,
        "/sequence",
        resource_class_args=[
            args_ns.dictionary,
            pipeline.up_store,
            pipeline.files.uplinker,
            args_ns.remote_sequence_directory,
        ],
    )
    api.add_resource(
        fprime_gds.flask.stats.StatsBlob,
        "/stats",
        resource_class_args=[
            {
                "events": pipeline.histories.events,
                "channels": pipeline.histories.channels,
                "commands": pipeline.histories.commands,
            }
        ],
    )

    # Optionally serve log files
    if app.config["SERVE_LOGS"]:
        api.add_resource(
            fprime_gds.flask.logs.LogList,
            "/logdata",
            resource_class_args=[args_ns.logs],
        )
        api.add_resource(
            fprime_gds.flask.logs.LogFile,
            "/logdata/<name>",
            resource_class_args=[args_ns.logs],
        )
    return app, api


try:
    app, _ = construct_app()
except Exception as exc:
    print(f"[ERROR] {exc}", file=sys.stderr)
    sys.exit(1)


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    status_code = 500
    response = {"errors": [fprime_gds.flask.errors.build_error_object(error)]}
    return flask.jsonify(response), status_code


@app.route("/js/config.js")
def config_serve():
    """
    Serve the config.js file

    :param path: path to the file (in terms of web browser)
    """
    return flask.send_file(app.config["JS_CONFIGURATION_FILE"])

@app.route("/js/<path:path>")
def files_serve(path):
    """
    A function used to serve the JS files needed for the GUI layers.

    :param path: path to the file (in terms of web browser)
    """
    return flask.send_from_directory("static/js", path)


@app.route("/")
def index():
    """
    A function used to serve the JS files needed for the GUI layers.
    """
    return flask.send_from_directory("static", "index.html")


@app.route("/logs")
def log():
    """
    A function used to serve the JS files needed for the GUI layers.
    """
    return flask.send_from_directory("static", "logs.html")


@app.route("/session")
def session():
    return flask.jsonify({"session": uuid.uuid4()}), 200


@app.after_request
def set_no_cache(response):
    """Set the no-cache header"""
    response.headers["Cache-Control"] = "no-cache"
    return response


# When running from the command line, this will allow the flask development server to launch
if __name__ == "__main__":
    app.run()
