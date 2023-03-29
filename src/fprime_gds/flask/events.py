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
from fprime_gds.flask.resource import DictionaryResource, HistoryResourceBase


class EventDictionary(DictionaryResource):
    """Channel dictionary shares implementation"""


class EventHistory(HistoryResourceBase):
    """
    Resource supplying the history of events in the system. Includes postprocessing to add in the
    for the display_text attribute which Flask will use.
    """
