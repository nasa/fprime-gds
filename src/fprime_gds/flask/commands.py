####
# commands.py:
#
# This file provides the API for the commands Gds interface for use with the Gds Flask server. This
# API should provide the following HTML API behaviors:
#
#  GET /commands: list all commandsi history available to the GUI. Note: this also provides a full
#                 command listing.
#  PUT /commands/<command>: issue a command through the GDS
#      Data: {
#                "key": "0xfeedcafe", # A key preventing accidental issuing of a command
#                "args": {
#                            <arg-key>:<arg-value>,
#                             ...
#                             ...
#                        }
#             }
#
#
# Note: for commands, these are not true "REST" objects, and thus this is a bit of a stretch to use
#       a restful interface here. It is done this way to be in-tandem with the events and telemetry
#       APIs for maintainability.
####
import flask_restful
import flask_restful.reqparse
import fprime_gds.common.models.serialize.type_exceptions
import werkzeug.exceptions

import fprime_gds.common.data_types.cmd_data
from fprime_gds.flask.resource import DictionaryResource, HistoryResourceBase


class CommandDictionary(DictionaryResource):
    """Channel dictionary shares implementation"""


class CommandHistory(HistoryResourceBase):
    """Command history requires no deviation from the base history implementation"""


class MissingArgumentException(werkzeug.exceptions.BadRequest):
    """Did not supply an argument"""

    def __init__(self):
        super().__init__("Did not supply all required arguments.")


class CommandArgumentsInvalidException(werkzeug.exceptions.BadRequest):
    """Command arguments failed to validate properly"""

    def __init__(self, errors):
        super().__init__(f"Failed to validate all arguments: {', '.join(errors)}")
        self.args = errors


class InvalidCommandException(werkzeug.exceptions.BadRequest):
    """Requested invalid command"""

    def __init__(self, key):
        super().__init__(f"{ key } is not a valid command")


class Command(flask_restful.Resource):
    """
    Command object used to send commands into the GDS.
    """

    def __init__(self, sender):
        """
        Constructor: setup the parser for incoming command runs
        """
        self.parser = flask_restful.reqparse.RequestParser()
        self.parser.add_argument(
            "key", required=True, help="Protection key. Must be: 0xfeedcafe."
        )
        self.parser.add_argument(
            "arguments", action="append", help="Argument list to pass to command."
        )
        self.sender = sender

    def put(self, command):
        """
        Receive a command run request.
        @param command: command identification
        """
        args = self.parser.parse_args()
        key = args.get("key", None)
        arg_list = args.get("arguments", [])
        # Error checking
        if key is None or int(key, 0) != 0xFEEDCAFE:
            flask_restful.abort(
                403,
                message=f"{key} is invalid command key. Supply 0xfeedcafe to run command.",
            )
        if arg_list is None:
            arg_list = []
        try:
            self.sender.send_command(command, arg_list)
        except fprime_gds.common.models.serialize.type_exceptions.NotInitializedException:
            raise MissingArgumentException()
        except fprime_gds.common.data_types.cmd_data.CommandArgumentsException as exc:
            raise CommandArgumentsInvalidException(exc.errors)
        except KeyError as key_error:
            raise InvalidCommandException(key_error)
        return {"message": "success"}
