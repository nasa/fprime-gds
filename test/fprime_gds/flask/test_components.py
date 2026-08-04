import unittest

from fprime_gds.executables.cli import HistoryParser, ParserBase
from fprime_gds.flask.components import FlaskEndpointRamHistory, NonClearingHistory


class TestHistoryParser(unittest.TestCase):
    """--gds-non-clearing-history defaults to off and round-trips through the parser"""

    def test_default_is_clearing(self):
        args_ns, _parser = ParserBase.parse_args([HistoryParser], "test", [])
        self.assertFalse(args_ns.non_clearing_history)

    def test_flag_enables_non_clearing(self):
        args_ns, _parser = ParserBase.parse_args(
            [HistoryParser], "test", ["--gds-non-clearing-history"]
        )
        self.assertTrue(args_ns.non_clearing_history)


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
