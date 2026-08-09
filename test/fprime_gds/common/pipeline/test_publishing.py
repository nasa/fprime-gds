import unittest

from fprime_gds.common.handlers import DataHandler
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.pipeline.publishing import PublishingPipeline


class _FakeTransport(DataHandler):
    """Minimal stand-in transport - a real DataHandler, but no actual socket"""

    def data_callback(self, data, sender=None):
        pass


class TestPublishingPipelineDictionaries(unittest.TestCase):
    """dictionaries is reachable without reaching into the private _dictionaries field

    fixes nasa/fprime#5066 - GDS data plugins built against PublishingPipeline had no
    supported way to get at the dictionaries object (e.g. for dictionary_path or
    channel_name lookups) other than accessing the private field directly.
    """

    def test_default_dictionaries_is_accessible(self):
        pipeline = PublishingPipeline()
        self.assertIsInstance(pipeline.dictionaries, Dictionaries)

    def test_dictionaries_reflects_setup_argument(self):
        # transport_implementation must be set before setup() regardless of this
        # change (unrelated to #5066); _FakeTransport stands in for the real
        # transport so setup() doesn't try to open a socket.
        pipeline = PublishingPipeline()
        pipeline.transport_implementation = _FakeTransport
        supplied = Dictionaries()
        pipeline.setup(supplied)
        self.assertIs(pipeline.dictionaries, supplied)


if __name__ == "__main__":
    unittest.main()
