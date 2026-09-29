"""Tests for configuration-file handling in fprime_gds.executables.cli"""

import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            ConfigDrivenParser.flatten_options(
                {"gui": "none", "port": 50000, "noapp": None}
            ),
            ["--gui", "none", "--port", "50000", "--noapp"],
        )

    def test_list_for_store_option_is_unchanged(self):
        self.assertEqual(
            ConfigDrivenParser.flatten_options(
                {"zmq-transport": ["ipc:///a", "ipc:///b"]}
            ),
            ["--zmq-transport", "ipc:///a", "ipc:///b"],
        )

    def test_list_for_extend_option_uses_equals_form(self):
        self.assertEqual(
            ConfigDrivenParser.flatten_options(
                {
                    "application-arguments": [
                        "-p",
                        50000,
                        "-a",
                        "0.0.0.0",
                        "-k",
                        "sdls.key",
                    ]
                },
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
            ConfigDrivenParser.flatten_options(
                {"application-arguments": "-k"}, {"--application-arguments"}
            ),
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
            [BinaryDeployment, GdsParser, MiddleWareParser],
            arguments=["--config", str(config_path), "--no-app", *cli],
        )
        return namespace, remaining

    def test_config_list_with_dash_values(self):
        expected = ["-p", "50000", "-a", "0.0.0.0", "-k", "sdls.key"]
        namespace, remaining = self.parse({"application-arguments": expected})
        self.assertEqual(namespace.application_arguments, expected)
        self.assertEqual(remaining, [])

    def test_config_list_with_dash_values_does_not_disturb_other_options(self):
        namespace, _ = self.parse(
            {"application-arguments": ["-p", "50000"], "gui-port": 6000, "gui": "none"}
        )
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
            {},
            "--application-arguments=-p",
            "--application-arguments=50000",
            "--gui",
            "none",
        )
        self.assertEqual(namespace.application_arguments, ["-p", "50000"])
        self.assertEqual(remaining, [])

    def test_cli_extends_config(self):
        namespace, _ = self.parse(
            {"application-arguments": ["-p", "50000"]}, "--application-arguments=-k"
        )
        self.assertEqual(namespace.application_arguments, ["-p", "50000", "-k"])


class TestConfigDrivenParserDefaultConfiguration(unittest.TestCase):
    """Tests for ConfigDrivenParser's (global) default configuration resolution

    Covers get_default_configuration()/set_default_configuration() precedence (-c/--config >
    FPRIME_GDS_CONFIG_PATH > built-in default), and that set_default_configuration() does not
    mutate os.environ (so child processes still see the original variable).
    """

    def setUp(self):
        # Snapshot/restore ConfigDrivenParser's class-level state so tests don't leak into each other.
        self._orig_default_path = ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH
        self._orig_explicit = ConfigDrivenParser._DEFAULT_CONFIGURATION_EXPLICIT

    def tearDown(self):
        ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH = self._orig_default_path
        ConfigDrivenParser._DEFAULT_CONFIGURATION_EXPLICIT = self._orig_explicit

    def test_default_configuration_without_env_var(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV, None)
            self.assertEqual(
                ConfigDrivenParser.get_default_configuration(),
                Path("fprime-gds.yml"),
            )

    def test_env_var_overrides_built_in_default(self):
        with mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: "/tmp/custom.yml"},
        ):
            self.assertEqual(
                ConfigDrivenParser.get_default_configuration(), Path("/tmp/custom.yml")
            )

    def test_empty_env_var_is_treated_as_unset(self):
        # Must not resolve to Path(""), i.e. the current working directory.
        with mock.patch.dict(
            os.environ, {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: ""}
        ):
            self.assertEqual(
                ConfigDrivenParser.get_default_configuration(),
                ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH,
            )

    def test_set_default_configuration_wins_over_env_var(self):
        with mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: "/tmp/from-env.yml"},
        ):
            ConfigDrivenParser.set_default_configuration(Path("/tmp/explicit.yml"))
            self.assertEqual(
                ConfigDrivenParser.get_default_configuration(),
                Path("/tmp/explicit.yml"),
            )
            # Must not mutate the environment (child processes still see the original variable).
            self.assertEqual(
                os.environ[ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV],
                "/tmp/from-env.yml",
            )

    def test_set_default_configuration_none_ignores_env_var(self):
        with mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: "/tmp/from-env.yml"},
        ):
            ConfigDrivenParser.set_default_configuration(None)
            self.assertIsNone(ConfigDrivenParser.get_default_configuration())


class TestConfigDrivenParserHandleArguments(unittest.TestCase):
    """Tests for ConfigDrivenParser.handle_arguments()'s explicit-configuration detection

    Must use the `arguments` passed to the parser, not sys.argv (callers like the pytest fixture
    in pytest_integration.py parse an argument list that differs from pytest's own sys.argv), and
    must agree with get_default_configuration() on whether set_default_configuration() has
    overridden the environment variable.
    """

    def setUp(self):
        self._orig_default_path = ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH
        self._orig_explicit = ConfigDrivenParser._DEFAULT_CONFIGURATION_EXPLICIT

    def tearDown(self):
        ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH = self._orig_default_path
        ConfigDrivenParser._DEFAULT_CONFIGURATION_EXPLICIT = self._orig_explicit

    def _make_args(self, config_path):
        return argparse.Namespace(
            config=Path(config_path) if config_path is not None else None
        )

    def test_missing_config_not_explicit_is_ignored(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV, None)
            args = self._make_args("does-not-exist.yml")
            result = ConfigDrivenParser().handle_arguments(
                args, arguments=["--foo", "bar"]
            )
            self.assertEqual(result.config_values, {})

    def test_missing_config_explicit_via_arguments_raises(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV, None)
            args = self._make_args("does-not-exist.yml")
            with self.assertRaises(ValueError):
                ConfigDrivenParser().handle_arguments(
                    args, arguments=["--config", "does-not-exist.yml"]
                )

    def test_missing_config_explicit_via_env_var_raises(self):
        # Must fail loudly rather than silently falling back to built-in defaults.
        with mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: "does-not-exist.yml"},
        ):
            args = self._make_args("does-not-exist.yml")
            with self.assertRaises(ValueError):
                ConfigDrivenParser().handle_arguments(args, arguments=["--foo", "bar"])

    def test_env_var_ignored_after_set_default_configuration_none(self):
        # A stale env var must not be treated as explicit (args.config is None here, so
        # args.config.exists() would crash).
        with mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: "/nonexistent.yml"},
        ):
            ConfigDrivenParser.set_default_configuration(None)
            args = self._make_args(None)
            result = ConfigDrivenParser().handle_arguments(
                args, arguments=["--foo", "bar"]
            )
            self.assertEqual(result.config_values, {})

    def test_env_var_ignored_after_set_default_configuration_override(self):
        with mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: "/nonexistent-env.yml"},
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                override_path = Path(tmp_dir) / "override.yml"
                override_path.write_text("command-line-options:\n  logs: /tmp/logs\n")
                ConfigDrivenParser.set_default_configuration(override_path)
                args = self._make_args(override_path)
                result = ConfigDrivenParser().handle_arguments(
                    args, arguments=["--foo", "bar"]
                )
        self.assertEqual(
            result.config_values, {"command-line-options": {"logs": "/tmp/logs"}}
        )

    def test_sys_argv_is_not_consulted(self):
        # A driving tool's own sys.argv (e.g. pytest's `-c pytest.ini`) must not be mistaken
        # for an explicit --config to this parser.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV, None)
            args = self._make_args("does-not-exist.yml")
            with mock.patch("sys.argv", ["pytest", "-c", "pytest.ini"]):
                result = ConfigDrivenParser().handle_arguments(
                    args, arguments=["--foo", "bar"]
                )
            self.assertEqual(result.config_values, {})

    def test_existing_config_file_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yml"
            config_path.write_text("command-line-options:\n  logs: /tmp/logs\n")
            args = self._make_args(str(config_path))
            result = ConfigDrivenParser().handle_arguments(
                args, arguments=["--config", str(config_path)]
            )
            self.assertEqual(
                result.config_values, {"command-line-options": {"logs": "/tmp/logs"}}
            )


if __name__ == "__main__":
    unittest.main()
