####
# events.py:
#
# This file captures the HTML endpoint for the events list. This file contains one endpoint which allows for listing
# events after a certain time-stamp.
#
#  GET /events: list events
#      Input Data: {
#                      "start-time": "YYYY-MM-DDTHH:MM:SS.sss" #Start time for event listing
#                  }
####
import copy
import types

from fprime_gds.flask.resource import DictionaryResource, HistoryResourceBase
from fprime_gds.common.utils.string_util import format_string_template


class EventDictionary(DictionaryResource):
    """Channel dictionary shares implementation"""


class EventHistory(HistoryResourceBase):
    """
    Resource supplying the history of events in the system. Includes `get_display_text` postprocessing to add in the
    getter for the display text.
    """

    def process(self, event):
        """Process item and return one with get_display_text"""
        event = copy.copy(event)
        setattr(
            event,
            "display_text",
            format_string_template(
                event.template.format_str, tuple([arg.val for arg in event.args])
            ),
        )

        def func(this):
            return this.display_text

        setattr(event, "get_display_text", types.MethodType(func, event))

        # Pre-trigger errors before JSON serialization
        _ = event.get_display_text()
        return event
