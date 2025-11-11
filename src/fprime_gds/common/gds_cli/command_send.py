"""
Handles executing the "command-send" CLI command for the GDS
"""

import difflib
from typing import Iterable, List

from fprime_gds.common.models.serialize.type_exceptions import NotInitializedException

import fprime_gds.common.gds_cli.test_api_utils as test_api_utils
from fprime_gds.common.gds_cli.base_commands import BaseCommand
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI


class CommandSendCommand(BaseCommand):
    """
    The implementation for sending a command via the GDS to the spacecraft
    """

    ####################################################################
    #   Utility functions
    ####################################################################
    @staticmethod
    def _get_closest_commands(
        project_dictionary: Dictionaries, command_name: str, num: int = 3
    ) -> List[str]:
        """
        Searches for the closest matching known command(s) to the given command
        name.

        :param project_dictionary: The dictionary object for this project
            containing the item type definitions
        :param command_name: The full string name of the command to search for
        :param num: The maximum number of near-matches to return
        :return: A list of the closest matching commands (potentially empty)
        """
        known_commands = project_dictionary.command_name.keys()
        closest_matches = difflib.get_close_matches(command_name, known_commands, n=num)
        return closest_matches

    @staticmethod
    def _get_command_template(
        project_dictionary: Dictionaries, command_name: str
    ) -> CmdTemplate:
        """
        Retrieves the command template for the given command name

        :param project_dictionary: The dictionary object for this project
            containing the item type definitions
        :param command_name: The full string name of the command to return a
            template for
        :return: The CmdTemplate object for the given command
        """
        return project_dictionary.command_name[command_name]

    @staticmethod
    def _get_command_help_message(
        project_dictionary: Dictionaries, command_name: str
    ) -> str:
        """
        Returns a string showing a help message for the given GDS command.

        :param project_dictionary: The dictionary object for this project
            containing the item type definitions
        :param command_name: The full string name of the command to return a
            help message for
        :return: A help string for the command
        """
        command_template = CommandSendCommand._get_command_template(
            project_dictionary, command_name
        )
        return CommandSendCommand._get_item_string(command_template)

    ####################################################################
    #   Abstract method implementations
    ####################################################################
    @classmethod
    def _get_item_list(
        cls,
        project_dictionary: Dictionaries,
        filter_predicate: predicates.predicate,
    ) -> Iterable[CmdTemplate]:
        """
        Gets a list of available commands in the system and return them in an
        ID-sorted list.

        :param project_dictionary: The dictionary object for the project
            containing the command definitions
        :param filter_predicate: Test API predicate used to filter shown
            channels
        """

        # NOTE: Trying to create a blank CmdData causes errors, so currently
        # just using templates (i.e. this function does nothing)
        def create_empty_command(cmd_template):
            return cmd_template

        command_list = test_api_utils.get_item_list(
            item_dictionary=project_dictionary.command_id,
            search_filter=filter_predicate,
            template_to_data=create_empty_command,
        )
        return command_list

    @classmethod
    def _get_item_string(
        cls,
        item: CmdTemplate,
        json: bool = False,
    ) -> str:
        """
        Converts the given command template into a human-readable string.

        :param item: The CmdTemplate to convert to a string
        :param json: Whether or not to return a JSON representation of "temp"
        :return: A readable string version of "item"
        """
        if not item:
            return ""
        if json:
            # This is questionable whether it should be supported
            from fprime_gds.flask.json import getter_based_json

            return str(getter_based_json(item))

        cmd_string = "%s (%d) | Takes %d arguments.\n" % (
            item.get_full_name(),
            item.get_id(),
            len(item.get_args()),
        )

        cmd_description = item.get_description()
        if cmd_description:
            cmd_string += f"Description: {(cmd_description)}\n"

        for arg in item.get_args():
            arg_name, arg_description, arg_type = arg
            if not arg_description:
                arg_description = "--no description--"
            # Can't compare against actual module, since EnumType is a serializable
            # type from the dictionary
            if type(arg_type).__name__ == "EnumType":
                arg_description = f"{str(arg_type.keys())} | {arg_description} "

            cmd_string += f"\t{arg_name} ({arg_type.__name__}): {arg_description}\n"

        return cmd_string

    @classmethod
    def _execute_command(cls, args, api: IntegrationTestAPI):
        """
        Logic for sending a command
        """
        command = args.command_name
        arguments = [] if args.arguments is None else args.arguments
        try:
            api.send_command(command, arguments)
        except KeyError:
            cls._log(f"{command} is not a known command")
            close_matches = cls._get_closest_commands(
                api.pipeline.dictionaries, command
            )
            if close_matches:
                cls._log(f"Similar known commands: {close_matches}")
        except NotInitializedException:
            temp = cls._get_command_template(api.pipeline.dictionaries, command)
            cls._log(
                "'%s' requires %d arguments (%d given)"
                % (command, len(temp.get_args()), len(arguments))
            )
            cls._log(cls._get_command_help_message(api.pipeline.dictionaries, command))
