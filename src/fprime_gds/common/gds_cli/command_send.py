"""
The implementation code for the command-send GDS CLI commands
"""

import sys
import difflib
from typing import Iterable, List

import fprime_gds.common.gds_cli.misc_utils as misc_utils
import fprime_gds.common.gds_cli.test_api_utils as test_api_utils
from fprime.common.models.serialize.type_exceptions import NotInitializedException
from fprime_gds.common.data_types.cmd_data import CommandArgumentsException
from fprime_gds.common.gds_cli.base_commands import BaseCommand
from fprime_gds.common.pipeline.dictionaries import Dictionaries
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI
from fprime_gds.executables.cli import StandardPipelineParser


class CommandSendCommand(BaseCommand):
    """
    The implementation for sending a command via the GDS to the spacecraft
    """

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
        return misc_utils.get_cmd_template_string(command_template)

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
        return misc_utils.get_cmd_template_string(item, json)

    @classmethod
    def handle_arguments(cls, args, **kwargs):
        """
        Handle the given input arguments, then execute the command itself
        """

        pipeline_parser = StandardPipelineParser()
        pipeline = None
        api = None

        try:
            # Parse the command line arguments into a client connection
            args = pipeline_parser.handle_arguments(args, **kwargs, client=True)

            search_filter = cls._get_search_filter(
                args.ids, args.components, args.search, args.json
            )

            if args.is_printing_list:
                cls._log(cls._list_all_possible_items(args.dictionary, search_filter, args.json))
                return

            # Build a new pipeline with the parsed and processed arguments
            pipeline = pipeline_parser.pipeline_factory(args)

            # Build and set up the integration test api 
            api = IntegrationTestAPI(pipeline)
            api.setup()

            command = args.command_name
            arguments = [] if args.arguments is None else args.arguments
            try:
                api.send_command(command, arguments)
            except KeyError:
                cls._log(f"{command} is not a known command")
                close_matches = cls._get_closest_commands(
                    pipeline.dictionaries, command
                )
                if close_matches:
                    cls._log(f"Similar known commands: {close_matches}")
            except NotInitializedException:
                temp = cls._get_command_template(
                    pipeline.dictionaries, command
                )
                cls._log(
                    "'%s' requires %d arguments (%d given)"
                    % (command, len(temp.get_args()), len(arguments))
                )
                cls._log(cls._get_command_help_message(pipeline.dictionaries, command))

        # Teardown resources
        finally:
            # Attempt to teardown the API to ensure we are clean after the fixture is created
            try:
                if api is not None:
                    api.teardown()
            except Exception as exc:
                print(f"[WARNING] Exception in API teardown: {exc}", file=sys.stderr)
            # Attempt to shut down the pipeline connection
            try:
                if pipeline is not None:
                    pipeline.disconnect()
            except Exception as exc:
                print(
                    f"[WARNING] Exception in pipeline teardown: {exc}", file=sys.stderr
                )
