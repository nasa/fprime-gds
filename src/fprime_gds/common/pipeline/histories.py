"""
histories.py:

Module used to handle the wrangling of histories for the standard pipeline. This allows the standard pipeline, and other
to compose in this code.

@author mstarch
"""

from typing import Type

from fprime_gds.common.history.history import History
from fprime_gds.common.history.ram import RamHistory


class Histories:
    """
    Class to handle the individual histories. This handles the following histories:

    1. Channel history
    2. Event history
    3. Command history (short-circuited feedback from encoder)
    """

    def __init__(self):
        """Constructor of histories composer"""
        self.coders = None
        self._command_hist = None
        self._event_hist = None
        self._channel_hist = None
        self._implementation_type = RamHistory

    def setup_histories(self, coders):
        """
        Setup a set of history objects in order to store the events of the decoders. This registers itself with the
        supplied coders object.

        :param coders: coders object to register histories with
        """
        self.coders = coders
        # Allow implementation type to disable histories
        if self._implementation_type is None:
            return
        # Create histories, RAM histories for now
        self.commands = self._implementation_type()
        self.events = self._implementation_type()
        self.channels = self._implementation_type()

    @property
    def implementation(self):
        """Get implementation type"""
        return self._implementation_type

    @implementation.setter
    def implementation(self, implementation_type: Type[History]):
        """Set the implementation type"""
        assert (
            self._command_hist is None
            and self._event_hist is None
            and self._channel_hist is None
        ), "Cannot setup implementation types after setup"
        self._implementation_type = implementation_type

    @property
    def events(self):
        """
        Events history property
        """
        return self._event_hist

    @events.setter
    def events(self, history: History):
        """
        Set the events history
        """
        assert (
            self.coders is not None
        ), "Cannot override history before calling 'setup_histories'"
        if self._event_hist is None:
            self.coders.remove_event_consumer(self._event_hist)
        self._event_hist = history
        self.coders.register_event_consumer(self._event_hist)

    @property
    def channels(self):
        """
        Channels history property
        """
        return self._channel_hist

    @channels.setter
    def channels(self, history: History):
        """
        Set the channels history
        """
        assert (
            self.coders is not None
        ), "Cannot override history before calling 'setup_histories'"
        if self._channel_hist is None:
            self.coders.remove_channel_consumer(self._channel_hist)
        self._channel_hist = history
        self.coders.register_channel_consumer(self._channel_hist)

    @property
    def commands(self):
        """
        Commands history property
        """
        return self._command_hist

    @commands.setter
    def commands(self, history: History):
        """
        Set the channels history
        """
        assert (
            self.coders is not None
        ), "Cannot override history before calling 'setup_histories'"
        if self._command_hist is None:
            self.coders.remove_command_consumer(self._command_hist)
        self._command_hist = history
        self.coders.register_command_consumer(self._command_hist)
