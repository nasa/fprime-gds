"""
A file containing utilities for interacting with the Integration Test API
"""

import types
from typing import Any, Callable, Dict, List

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.data_types.sys_data import SysData
from fprime_gds.common.templates.data_template import DataTemplate
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI


def get_upcoming_event(
    test_api: IntegrationTestAPI,
    search_filter: predicates.predicate,
    start_time="NOW",
    timeout: float = 5,
) -> EventData:
    """
    Returns the next event matching the given search filter that occurs after
    this is called. Times out after the given amount if no matching new events
    are found.

    :param test_api: An API instance that will be called to find the next event
    :param search_filter: A predicate each found event is tested against; if
        the event doesn't test "True" against this, we ignore it and keep
        searching
    :param start_time: An optional index or predicate to specify the earliest
        event time to search for
    :param timeout: The maximum time (in seconds) to wait for an event

    :return: The first "EventData" found that passes the filter, or "None" if no
        such event is found within time
    """
    event_filter = predicates.satisfies_all(
        [search_filter, predicates.event_predicate()]
    )
    # Test API only takes integer timeouts
    return test_api.find_history_item(
        event_filter, test_api.get_event_test_history(), start_time, int(timeout)
    )


def get_upcoming_channel(
    test_api: IntegrationTestAPI,
    search_filter: predicates.predicate,
    start_time="NOW",
    timeout: float = 5,
) -> ChData:
    """
    Returns the next telemetry update matching the given search filter that
    occurs after this is called. Times out after the given amount if no
    matching new updates are found.

    :param test_api: An API instance that will be called to find the next update
    :param search_filter: A predicate each found update is tested against; if
        the item doesn't test "True" against this, we ignore it and keep
        searching
    :param start_time: An optional index or predicate to specify the earliest
        update time to search for
    :param timeout: The maximum time (in seconds) to wait for an update

    :return: The first "ChData" found that passes the filter, or "None" if no
        such update is found within time
    """
    channel_filter = predicates.satisfies_all(
        [search_filter, predicates.telemetry_predicate()]
    )
    # Test API only takes integer timeouts
    return test_api.find_history_item(
        channel_filter, test_api.get_telemetry_test_history(), start_time, int(timeout)
    )


def get_item_list(
    item_dictionary: Dict[Any, DataTemplate],
    search_filter: predicates.predicate,
    template_to_data: types.FunctionType,
) -> List[SysData]:
    """
    Returns an ID-sorted list containing all the possible item types that could
    occur on the running F' instance, and information about each one.

    :param item_dictionary: A dictionary full of DataTemplate objects containing
        the events you want to list
    :param search_filter: A Test API predicate used to filter out which items
        to include in the returned list
    :param template_to_data: A callback function accepting a single DataTemplate
        object and returning a SysData object

    :return: An ID sorted list with all the items from the given dictionary
        AFTER being filtered
    """
    # Dictionary has DataTemplates by default, so convert them to SysData so
    # filtering will work properly (several predicates assume SysData types)
    event_data_list = list(
        map(lambda x: template_to_data(x[1]), item_dictionary.items())
    )

    # Filter by using the given predicate on the event values
    event_data_list = list(filter(search_filter, event_data_list))
    event_data_list.sort(key=lambda x: x.get_id())
    return event_data_list


def repeat_until_interrupt(func: Callable, *args):
    """
    Continues to call the input function with the given arguments until the
    user interrupts it.

    :param func: The function you want to call repeatedly. If the function
        returns anything, it MUST return a new, updated tuple of the arguments
        passed into it in the same order, which will be used as the new
        arguments in the next iteration. This is done to allow for persistent
        state between iterations; if needed, create a wrapper for your original
        function to do this. If the function does NOT return anything, the
        original input arguments will continue to be used
    :param args: All keyword arguments you want to pass into "func"
    """
    try:
        while True:
            new_args = func(*args)  # lgtm [py/call/wrong-arguments]
            if new_args:
                args = new_args
    except KeyboardInterrupt:
        pass