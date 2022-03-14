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
import copy
import types
import time
from fprime.common.models.serialize.serializable_type import SerializableType
from fprime.common.models.serialize.array_type import ArrayType
from fprime_gds.flask.resource import DictionaryResource, HistoryResourceBase


class ChannelDictionary(DictionaryResource):
    """Channel dictionary shares implementation"""


class ChannelHistory(HistoryResourceBase):
    """
    Resource supplying the history of channels in the system. Includes `get_display_text` postprocessing to add in the
    getter for the display text.
    """

    def process(self, chan):
        """Process the channel to add get_display_text"""
        chan = copy.copy(chan)
        # Setup display_text and when needed
        if isinstance(chan.val_obj, (SerializableType, ArrayType)):
            setattr(chan, "display_text", chan.val_obj.formatted_val)
        elif chan.template.get_format_str() is not None:
            setattr(
                chan,
                "display_text",
                chan.template.get_format_str() % (chan.val_obj.val),
            )
        # If we added display_text, then add a getter and test it
        if hasattr(chan, "display_text"):

            def func(this):
                return this.display_text

            setattr(chan, "get_display_text", types.MethodType(func, chan))
            # Pre-trigger any errors in the display text getter
            _ = chan.get_display_text()
        return chan
