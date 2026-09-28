"""Unit tests for pytest_integration.py's config-file/pytest-CLI precedence handling

These exercise the same path fprime_test_api_session() uses to reconcile pytest command-line
options with an fprime-gds configuration file (via FPRIME_GDS_CONFIG_PATH): pytest_addoption() to
build the pytest-style namespace, then reproduce_cli_args() + ConfigDrivenParser.parse_known_args()
to fold in the configuration file. They assert that:
  * an option left at its default on the pytest command line is filled in from the configuration
    file (including options like --tts-port whose argparse default is not None), and
  * an option explicitly given on the pytest command line still takes precedence over the file.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _pytest.config.argparsing import Parser

from fprime_gds.common.testing_fw.pytest_integration import pytest_addoption
from fprime_gds.executables.cli import ConfigDrivenParser, StandardPipelineParser

UNIT_TEST_DICTIONARY = str(Path(__file__).parent / "UnitTestDictionary.xml")


def _parse_pytest_args(args):
    """Build a pytest-style namespace the same way pytest would parse its command line"""
    parser = Parser(_ispytest=True)
    pytest_addoption(parser)
    # Supply a dictionary explicitly so DictionaryParser does not try to auto-detect a deployment
    # (irrelevant to what is under test here).
    return parser.parse(["--dictionary", UNIT_TEST_DICTIONARY] + args)


class TestPytestIntegrationConfigPrecedence(unittest.TestCase):
    def test_defaulted_option_is_filled_in_from_config_file(self):
        """A pytest option left at its default should be overridden by the configuration file"""
        namespace = _parse_pytest_args(["--logs", "/tmp/logs"])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "fprime-gds.yml"
            config_path.write_text("command-line-options:\n  tts-port: 60000\n")

            with mock.patch.dict(
                os.environ,
                {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: str(config_path)},
            ):
                reproduced_args = StandardPipelineParser().reproduce_cli_args(namespace)
                arg_ns, _, _ = ConfigDrivenParser.parse_known_args(
                    [StandardPipelineParser], arguments=reproduced_args, client=True
                )

        self.assertEqual(arg_ns.tts_port, 60000)

    def test_explicit_pytest_flag_wins_over_config_file(self):
        """An option given explicitly on the pytest command line must not be overridden by the file"""
        namespace = _parse_pytest_args(
            ["--logs", "/tmp/logs", "--tts-addr", "10.0.0.5"]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "fprime-gds.yml"
            config_path.write_text(
                "command-line-options:\n  tts-port: 60000\n  tts-addr: 10.0.0.9\n"
            )

            with mock.patch.dict(
                os.environ,
                {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: str(config_path)},
            ):
                reproduced_args = StandardPipelineParser().reproduce_cli_args(namespace)
                arg_ns, _, _ = ConfigDrivenParser.parse_known_args(
                    [StandardPipelineParser], arguments=reproduced_args, client=True
                )

        self.assertEqual(arg_ns.tts_addr, "10.0.0.5")
        self.assertEqual(arg_ns.tts_port, 60000)

    def test_help_text_reports_real_default_despite_suppression(self):
        """Suppressing the pytest-side default must not leak "None" into `pytest --help`"""
        real_default = next(
            specifiers["default"]
            for flags, specifiers in StandardPipelineParser().get_arguments().items()
            if "--tts-port" in flags
        )

        parser = Parser(_ispytest=True)
        pytest_addoption(parser)
        option = next(
            option
            for option in parser._anonymous.options
            if "--tts-port" in option.names()
        )

        self.assertIsNone(option.attrs().get("default"))
        self.assertNotIn("%(default)s", option.attrs()["help"])
        self.assertIn(str(real_default), option.attrs()["help"])


if __name__ == "__main__":
    unittest.main()
