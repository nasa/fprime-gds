####
# channels.py:
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


class ChannelDictionary(DictionaryResource):
    """Channel dictionary shares implementation"""


class ChannelHistory(HistoryResourceBase):
    """
    Resource supplying the history of channels in the system. Includes `get_display_text` postprocessing to add in the
    getter for the display text.
    """
