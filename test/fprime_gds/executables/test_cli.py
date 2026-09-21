"""Tests for configuration-file handling in fprime_gds.executables.cli"""

import tempfile
import unittest
from pathlib import Path

import yaml

from fprime_gds.executables.cli import (
    BinaryDeployment,
    ConfigDrivenParser,
    GdsParser,
    MiddleWareParser,
)


class TestFlattenOptions(unittest.TestCase):
    """flatten_options turns configured options into command line tokens"""

    def test_none_and_scalars(self):
        self.assertEqual(ConfigDrivenParser.flatten_options(None), [])
        self.assertEqual(
            ConfigDrivenParser.flatten_options({"gui": "none", "port": 50000, "noapp": None}),
            ["--gui", "none", "--port", "50000", "--noapp"],
        )

    def test_list_for_store_option_is_unchanged(self):
        self.assertEqual(
            ConfigDrivenParser.flatten_options({"zmq-transport": ["ipc:///a", "ipc:///b"]}),
            ["--zmq-transport", "ipc:///a", "ipc:///b"],
        )

    def test_list_for_extend_option_uses_equals_form(self):
        self.assertEqual(
            ConfigDrivenParser.flatten_options(
                {"application-arguments": ["-p", 50000, "-a", "0.0.0.0", "-k", "sdls.key"]},
                {"--application-arguments"},
            ),
            [
                "--application-arguments=-p",
                "--application-arguments=50000",
                "--application-arguments=-a",
                "--application-arguments=0.0.0.0",
                "--application-arguments=-k",
                "--application-arguments=sdls.key",
            ],
        )

    def test_scalar_for_extend_option_uses_equals_form(self):
        self.assertEqual(
            ConfigDrivenParser.flatten_options({"application-arguments": "-k"}, {"--application-arguments"}),
            ["--application-arguments=-k"],
        )


class TestApplicationArguments(unittest.TestCase):
    """--application-arguments accepts dash-prefixed values from the configuration file"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def parse(self, config, *cli):
        config_path = Path(self.tempdir.name) / "fprime-gds.yml"
        config_path.write_text(yaml.safe_dump({"command-line-options": config}))
        namespace, _, remaining = ConfigDrivenParser.parse_known_args(
            [BinaryDeployment, GdsParser, MiddleWareParser], arguments=["--config", str(config_path), "--no-app", *cli]
        )
        return namespace, remaining

    def test_config_list_with_dash_values(self):
        expected = ["-p", "50000", "-a", "0.0.0.0", "-k", "sdls.key"]
        namespace, remaining = self.parse({"application-arguments": expected})
        self.assertEqual(namespace.application_arguments, expected)
        self.assertEqual(remaining, [])

    def test_config_list_with_dash_values_does_not_disturb_other_options(self):
        namespace, _ = self.parse({"application-arguments": ["-p", "50000"], "gui-port": 6000, "gui": "none"})
        self.assertEqual(namespace.application_arguments, ["-p", "50000"])
        self.assertEqual(namespace.gui_port, "6000")
        self.assertEqual(namespace.gui, "none")

    def test_unset_defaults_to_none(self):
        namespace, _ = self.parse({"gui": "none"})
        self.assertIsNone(namespace.application_arguments)

    def test_cli_plain_values(self):
        namespace, remaining = self.parse({}, "--application-arguments", "foo", "bar")
        self.assertEqual(namespace.application_arguments, ["foo", "bar"])
        self.assertEqual(remaining, [])

    def test_cli_equals_form_with_dash_values(self):
        namespace, remaining = self.parse(
            {}, "--application-arguments=-p", "--application-arguments=50000", "--gui", "none"
        )
        self.assertEqual(namespace.application_arguments, ["-p", "50000"])
        self.assertEqual(remaining, [])

    def test_cli_extends_config(self):
        namespace, _ = self.parse({"application-arguments": ["-p", "50000"]}, "--application-arguments=-k")
        self.assertEqual(namespace.application_arguments, ["-p", "50000", "-k"])


if __name__ == "__main__":
    unittest.main()
