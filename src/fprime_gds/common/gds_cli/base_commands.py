"""
A collection of base classes used for the backend implementations of the GDS
CLI commands
"""

import abc
import json
import sys
from typing import Iterable

import fprime_gds.common.gds_cli.filtering_utils as filtering_utils
import fprime_gds.common.gds_cli.test_api_utils as test_api_utils
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI
from fprime_gds.executables.cli import StandardPipelineParser


class BaseCommand(abc.ABC):
    """
    The base class for implementing a GDS CLI channel/event/command-send functionality
    Subclasses must implement the _get_item_list and handle_command methods
    """

    ####################################################################
    #   Abstract Methods
    ####################################################################

    @classmethod
    @abc.abstractmethod
    def _execute_command(cls, args, api: IntegrationTestAPI):
        """
        Command logic of sending/receiving channels/commands/events
        """

    @classmethod
    @abc.abstractmethod
    def _get_item_list(
        cls,
        project_dictionary: Dictionaries,
        filter_predicate: predicates.predicate,
    ) -> Iterable:
        """
        Gets a sorted list of items from the dictionary, filtered by the given
        predicate, and return it.

        :param project_dictionary: The dictionary object for the project
            containing the item type definitions
        :param filter_predicate: Test API predicate used to filter shown items
        :return: An iterable collection of items that passed the filter
        """

    @classmethod
    @abc.abstractmethod
    def _get_item_string(
        cls,
        item,
        json: bool = False,
    ) -> str:
        """
        Takes an F' item and returns a human-readable string of its data.

        :param item: The F' item to convert to a string
        :param json: Whether to print out each item in JSON format or not
        :return: A string representation of "item"
        """

    ####################################################################
    #   Shared Methods
    ####################################################################
    @classmethod
    def _get_item_list_string(
        cls,
        items: Iterable,
        json: bool = False,
    ) -> str:
        """
        Takes a list of items from the dictionary and returns a human-readable
        string containing their details.

        :param items: An iterable collection of F' data objects
        :param json: Whether to print out each item in JSON format or not
        :return: A string containing the details of each item
        """
        return "\n".join(cls._get_item_string(item, json) for item in items)

    @classmethod
    def _get_search_filter(
        cls,
        ids: Iterable[int],
        components: Iterable[str],
        search: str,
        json: bool = False,
    ) -> predicates.predicate:
        """
        Returns a predicate that can be used to filter any received messages.
        This is done to link printing code to filtering, so that filtering ALWAYS
        filters the same strings as are printed.

        NOTE: Currently assumes that item list strings will contain the
        individual strings of each items to work with both, which there's no
        guarantee of if _get_item_list_string is overridden

        :param search: The F' item to convert to a string
        :param json: Whether to convert each item to a JSON representation
            before filtering them
        :return: A string representation of "item"
        """

        def item_to_string(x):
            return cls._get_item_string(x, json)

        return filtering_utils.get_full_filter_predicate(
            ids, components, search, to_str=item_to_string
        )

    @classmethod
    def _list_all_possible_items(
        cls, dictionary_path: str, search_filter: predicates.predicate, json: bool
    ) -> str:
        """
        Returns a string of the information for all relevant possible items
        for this command, filtered using the given predicate.

        :param dictionary_path: The string path to the dictionary file we should
            look for possible items in
        :param search_filter: The predicate to filter the items with
        :param json: Whether to print out each item in JSON format or not
        :return: A string describing each item relevant to this command that
            passes the given filter
        """
        project_dictionary = Dictionaries()
        project_dictionary.load_dictionaries(dictionary_path, packet_spec=None, packet_set_name=None)
        items = cls._get_item_list(project_dictionary, search_filter)
        return cls._get_item_list_string(items, json)

    @classmethod
    def handle_arguments(cls, args, **kwargs):
        """
        Entrypoint for the command. Handles parsing the arguments and creating the
        StandardPipeline and Integration API, then calls the execution of the command logic.
        Finally, tears down the pipeline and API.
        """
        pipeline = None
        api = None
        try:
            # Parsing the arguments
            pipeline_parser = StandardPipelineParser()
            pipeline_parser.handle_arguments(args, **kwargs, client=True)

            # If the user is just listing all possible items, do that and exit
            if args.is_printing_list:
                search_filter = cls._get_search_filter(
                    args.ids, args.components, args.search, args.json
                )
                cls._log(
                    cls._list_all_possible_items(
                        args.dictionary, search_filter, args.json
                    )
                )
                return

            # Set up StandardPipeline and Integration API
            pipeline = pipeline_parser.pipeline_factory(args)
            api = IntegrationTestAPI(pipeline)
            api.setup()

            # Execute the command logic
            cls._execute_command(args, api)

        # Tear down resources
        finally:
            try:
                if api is not None:
                    api.teardown()
            except Exception as exc:
                print(f"[WARNING] Exception in API teardown: {exc}", file=sys.stderr)
            try:
                if pipeline is not None:
                    pipeline.disconnect()
            except Exception as exc:
                print(
                    f"[WARNING] Exception in pipeline teardown: {exc}", file=sys.stderr
                )

    @classmethod
    def _log(cls, log_text: str):
        """
        Takes the given string and logs it (by default, logs all output to the
        console). Will ignore empty strings.

        :param log_text: The string to print out
        """
        if log_text:
            print(log_text)
            sys.stdout.flush()


class QueryHistoryCommand(BaseCommand):
    """
    The base class for a set of related GDS CLI commands that need to query and
    display received data from telemetry channels and F' events.
    """

    @classmethod
    @abc.abstractmethod
    def _get_upcoming_item(
        cls,
        api: IntegrationTestAPI,
        filter_predicate: predicates.predicate,
        min_start_time="NOW",
        timeout: float = 5.0,
    ):
        """
        Retrieves an F' item that has occurred since the given time and returns
        its data.
        """
    

    @classmethod
    def _get_item_string(
        cls,
        item: "SysData",
        as_json: bool = False,
    ) -> str:
        """
        Takes an F' item and returns a human-readable string of its data.

        :param item: EventData or ChData
        :param as_json: Whether to print out each item in JSON format or not
        :return: A string representation of "item"
        """
        if not item:
            return ""
        return json.dumps(item.get_dict()) if as_json else item.get_str(verbose=True)

    @classmethod
    def _execute_command(cls, args, api: IntegrationTestAPI):
        """
        Logic for receiving events/channels given the parsed arguments.
        This differentiates between the events and channels because their
        implementation of _get_upcoming_item is different.
        """
        search_filter = cls._get_search_filter(
            args.ids, args.components, args.search, args.json
        )
        # Timeout <= 0 means we should keep going until interrupted
        if args.timeout > 0:
            item = cls._get_upcoming_item(api, search_filter, "NOW", args.timeout)
            cls._log(cls._get_item_string(item, args.json))
        else:

            def print_upcoming_item(min_start_time="NOW"):
                item_ = cls._get_upcoming_item(api, search_filter, min_start_time)
                cls._log(cls._get_item_string(item_, args.json))
                # Update time so we catch the next item since the last one
                if item_:
                    min_start_time = predicates.greater_than(item_.get_time())
                    min_start_time = filtering_utils.time_to_data_predicate(
                        min_start_time
                    )
                return (min_start_time,)

            test_api_utils.repeat_until_interrupt(print_upcoming_item, "NOW")
