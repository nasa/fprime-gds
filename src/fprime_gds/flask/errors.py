""" errors.py:

Contains the necessary definitions to handle errors across flask in a standard way. This will hopefully make the GDS
more stable and less likely to fail on errors that occur.

@author lestarch
"""

from flask import Flask, jsonify
from flask_restful import Api


def build_error_object(error, args=None):
    """Builds an error object from an error"""
    return {
        "type": str(type(error).__name__),
        "message": str(error),
        "args": args if args is not None else [],
    }


def handle_flask_error(error):
    """Handle an error within the flask usage

    Handling an error within flask should produce a standard error message and pass it back to the JavaScript
    application. The error response is expected to look like:

        {"errors": [{"type": "<error type>, "message": "<display message>"}, ...]}

    This will include setting the status code to 500. It is up to any specific resource to continue within the context
    of a recoverable error and the function build_error_object may be called to build an error message.

    Args:
        error: the error to be reported

    Returns:
        response JSON, status code
    """
    status_code = getattr(error, "code", 500)
    response = {"errors": [build_error_object(error, getattr(error, "args", []))]}
    return jsonify(response), status_code


class ErrorHandlingApi(Api):
    """Subclass of the flask_restful API only to change the error handle"""

    def handle_error(self, error):
        """Handle errors within flask_restful by overriding the handle_error method"""
        return handle_flask_error(error)


def setup_error_handling(app: Flask):
    """Setup the error handling for flask and get a flask_restful API with similar error handling

    Sets up a flask_restful API that will handle errors in the standard way and registers the same error handling to
    the flask app for non-restful errorrs

    Args:
        app: flask application to register errors

    Returns:
        flask restful api with standardized error handling
    """
    app.errorhandler(Exception)(handle_flask_error)
    return Api(app)
