import tempfile
import unittest
from pathlib import Path

from fprime_gds.executables.cli import CommExtraParser, ConfigDrivenParser, ParserBase


class TestCommCli(unittest.TestCase):

    def test_downlink_queue_maxsize_argument_is_parsed(self):
        args, _ = ParserBase.parse_args(
            [CommExtraParser],
            arguments=["--downlink-queue-maxsize", "128"],
        )

        self.assertEqual(args.downlink_queue_maxsize, 128)

    def test_downlink_queue_maxsize_rejects_non_positive_values(self):
        with self.assertRaises(ValueError):
            CommExtraParser().handle_values(
                {"output_unframed_data": None, "downlink_queue_maxsize": 0}
            )

    def test_downlink_queue_maxsize_can_come_from_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "fprime-gds.yml"
            config_path.write_text(
                "command-line-options:\n"
                "  downlink-queue-maxsize: 256\n",
                encoding="utf-8",
            )

            args, _ = ConfigDrivenParser.parse_args(
                [CommExtraParser],
                arguments=["--config", str(config_path)],
            )

        self.assertEqual(args.downlink_queue_maxsize, 256)
