import unittest

from fprime_gds.executables.cli import HistoryParser, ParserBase
from fprime_gds.flask.components import (
    FlaskEndpointRamHistory,
    NonClearingHistory,
    select_history_implementation,
)


class TestHistoryParser(unittest.TestCase):
    """--no-clear-history defaults to off and round-trips through the parser"""

    def test_default_is_clearing(self):
        args_ns, _parser = ParserBase.parse_args([HistoryParser], "test", [])
        self.assertFalse(args_ns.no_clear_history)

    def test_flag_enables_non_clearing(self):
        args_ns, _parser = ParserBase.parse_args(
            [HistoryParser], "test", ["--no-clear-history"]
        )
        self.assertTrue(args_ns.no_clear_history)


class TestSelectHistoryImplementation(unittest.TestCase):
    """The parsed --no-clear-history argument actually selects the right history class

    This exercises the real path from CLI argument string to the class that
    setup_pipelined_components would assign to pipeline.histories.implementation -
    catching the case where the flag parses correctly but the selection logic doesn't
    act on it (or vice versa).
    """

    def test_flag_off_selects_clearing_history(self):
        args_ns, _parser = ParserBase.parse_args([HistoryParser], "test", [])
        self.assertIs(select_history_implementation(args_ns), FlaskEndpointRamHistory)

    def test_flag_on_selects_non_clearing_history(self):
        args_ns, _parser = ParserBase.parse_args(
            [HistoryParser], "test", ["--no-clear-history"]
        )
        self.assertIs(select_history_implementation(args_ns), NonClearingHistory)

    def test_missing_attribute_defaults_to_clearing_history(self):
        # Guards the getattr(..., False) default: an arguments object that doesn't even
        # have the attribute (e.g. a caller that predates this flag) should still get the
        # original, unchanged default behavior.
        class NoHistoryAttr:
            pass

        self.assertIs(
            select_history_implementation(NoHistoryAttr()), FlaskEndpointRamHistory
        )


class TestNonClearingHistory(unittest.TestCase):
    """A new session sees everything already in history, and clear() is a no-op"""

    def setUp(self):
        self.history = NonClearingHistory()
        for item in range(5):
            self.history.data_callback(item)

    def test_new_session_sees_full_history(self):
        # A client connecting after 5 items already arrived should still see all 5,
        # unlike the base FlaskEndpointRamHistory, whose new sessions start at the end.
        items = self.history.retrieve(start="session-a")
        self.assertEqual(items, [0, 1, 2, 3, 4])

    def test_clear_is_a_no_op(self):
        self.history.retrieve(start="session-a")
        self.history.clear()
        # A second session, connecting after clear(), should still see everything -
        # nothing was evicted.
        items = self.history.retrieve(start="session-b")
        self.assertEqual(items, [0, 1, 2, 3, 4])

    def test_existing_session_only_sees_new_items(self):
        self.history.retrieve(start="session-a")
        self.history.data_callback(5)
        # A session that already caught up should only see the new item, not a
        # replay of everything - this only changes behavior for *new* sessions.
        items = self.history.retrieve(start="session-a")
        self.assertEqual(items, [5])


class TestFlaskEndpointRamHistoryUnaffected(unittest.TestCase):
    """The default (clearing) history is untouched by this change"""

    def test_new_session_sees_only_new_items(self):
        history = FlaskEndpointRamHistory()
        for item in range(5):
            history.data_callback(item)
        # Existing behavior: a brand new session starts at the current end of
        # history and sees nothing that arrived before it connected.
        items = history.retrieve(start="session-a")
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
