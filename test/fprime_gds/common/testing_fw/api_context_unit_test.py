"""Unit tests for IntegrationTestAPIContext (using the integration test API without pytest)

The pipeline connection is replaced with a mock so these tests exercise argument parsing, API construction, and
teardown without a running GDS.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fprime_gds.common.testing_fw import api as api_module
from fprime_gds.common.testing_fw.api import (
    IntegrationTestAPI,
    IntegrationTestAPIContext,
)
from fprime_gds.executables.cli import ConfigDrivenParser

UNIT_TEST_DICTIONARY = str(Path(__file__).parent / "UnitTestDictionary.xml")


class TestIntegrationTestAPIContext(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.base_args = [
            "--dictionary",
            UNIT_TEST_DICTIONARY,
            "--logs",
            str(Path(self.tmp_dir.name) / "logs"),
        ]
        self.pipeline = mock.MagicMock()
        self.pipeline.dictionaries.dictionary_path = UNIT_TEST_DICTIONARY
        factory = mock.patch.object(
            api_module.StandardPipelineParser,
            "pipeline_factory",
            return_value=self.pipeline,
        )
        self.pipeline_factory = factory.start()
        self.addCleanup(factory.stop)
        # Point the configuration file at an empty one so a user's fprime-gds.yml cannot leak into the tests
        self.config_path = Path(self.tmp_dir.name) / "fprime-gds.yml"
        self.config_path.write_text("")
        environment = mock.patch.dict(
            os.environ,
            {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: str(self.config_path)},
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_yields_api_and_tears_down(self):
        """The context yields a set-up API, then tears down the API and disconnects the pipeline on exit"""
        context = IntegrationTestAPIContext(self.base_args)
        with mock.patch.object(
            IntegrationTestAPI,
            "teardown",
            autospec=True,
            side_effect=IntegrationTestAPI.teardown,
        ) as teardown:
            with context as api:
                self.assertIsInstance(api, IntegrationTestAPI)
                self.assertIs(api.pipeline, self.pipeline)
                self.pipeline.coders.register_event_consumer.assert_any_call(api)
                teardown.assert_not_called()
                self.pipeline.disconnect.assert_not_called()
        teardown.assert_called_once_with(api)
        self.pipeline.disconnect.assert_called_once()
        self.assertIsNone(context.api)
        self.assertIsNone(context.pipeline)

    def test_parses_pipeline_arguments(self):
        """Standard pipeline arguments are parsed and handed to the pipeline factory; unknown ones are ignored"""
        args = self.base_args + ["--tts-port", "60000", "--my-script-option", "x"]
        with IntegrationTestAPIContext(args):
            pass
        arg_ns = self.pipeline_factory.call_args.args[0]
        self.assertEqual(arg_ns.tts_port, 60000)

    def test_reads_configuration_file(self):
        """Options not given on the command line are read from the fprime-gds configuration file"""
        self.config_path.write_text("command-line-options:\n  tts-port: 60001\n")
        with IntegrationTestAPIContext(self.base_args):
            pass
        arg_ns = self.pipeline_factory.call_args.args[0]
        self.assertEqual(arg_ns.tts_port, 60001)

    def test_deployment_config(self):
        """--deployment-config is read from the arguments, and the keyword argument takes precedence"""
        args = self.base_args + ["--deployment-config", "from_cli.json"]
        with IntegrationTestAPIContext(args) as api:
            self.assertEqual(api.get_config_file_path(), Path("from_cli.json"))
        with IntegrationTestAPIContext(args, deployment_config="from_kwarg.json") as api:
            self.assertEqual(api.get_config_file_path(), "from_kwarg.json")
        with IntegrationTestAPIContext(self.base_args) as api:
            self.assertIsNone(api.get_config_file_path())

    def test_exception_in_body_tears_down_and_propagates(self):
        """An exception (e.g. a failed assert) inside the with block still cleans up and is not swallowed"""
        with self.assertRaises(AssertionError):
            with IntegrationTestAPIContext(self.base_args):
                assert False, "failed check"
        self.pipeline.disconnect.assert_called_once()

    def test_setup_failure_disconnects_pipeline(self):
        """If building the API fails after the pipeline connected, the pipeline is still disconnected"""
        with mock.patch.object(
            IntegrationTestAPI, "setup", side_effect=RuntimeError("setup failed")
        ):
            with self.assertRaises(RuntimeError):
                with IntegrationTestAPIContext(self.base_args):
                    self.fail("body must not run when setup fails")
        self.pipeline.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
