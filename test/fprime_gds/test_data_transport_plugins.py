"""Tests for the data_transport plugin category: built-in transports, selection, aliases and pipeline wiring"""

import functools
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from _pytest.config.argparsing import Parser

from fprime_gds.common.testing_fw import pytest_integration
from fprime_gds.common.testing_fw.pytest_integration import pytest_addoption
from fprime_gds.common.transport import (
    ThreadedTCPSocketClient,
    ThreadedTransportClient,
    TransportClient,
)
from fprime_gds.common.zmq_transport import ZmqClient
from fprime_gds.executables import run_deployment
from fprime_gds.executables.cli import (
    CompositeParser,
    ConfigDrivenParser,
    MiddleWareParser,
    PluginArgumentParser,
    StandardPipelineParser,
)
from fprime_gds.plugin.definitions import PluginType, gds_plugin_implementation
from fprime_gds.plugin.system import Plugins

UNIT_TEST_DICTIONARY = str(
    Path(__file__).parent / "common" / "testing_fw" / "UnitTestDictionary.xml"
)


class FakeGroundSystemClient(TransportClient):
    """Stand-in for an externally installed transport plugin (e.g. the fprime-yamcs plugin)"""

    def __init__(self, fake_url="http://fake"):
        super().__init__()
        self.fake_url = fake_url

    @classmethod
    def get_name(cls):
        return "fake-ground"

    @classmethod
    def get_arguments(cls):
        return {
            ("--fake-url",): {
                "dest": "fake_url",
                "type": str,
                "default": "http://fake",
                "help": "Fake ground system URL",
            }
        }

    @classmethod
    def get_connection_uri(cls, client=True, fake_url="http://fake"):
        return f"fake://{fake_url}"

    @classmethod
    @gds_plugin_implementation
    def register_data_transport_plugin(cls):
        return cls

    def connect(self, connection_uri=None, incoming_routing=None, outgoing_routing=None):
        pass

    def disconnect(self):
        pass

    def send(self, data):
        pass

    def recv(self, timeout=None):
        return b""


def parse_middleware_again(arguments, client=True):
    """Parse again in the same process without resetting the once-per-process deprecation warning"""
    parser = MiddleWareParser()
    parser._plugin_parser = PluginArgumentParser(Plugins(["data_transport"]))
    composite = CompositeParser([parser])
    return composite.handle_arguments(composite.get_parser().parse_args(arguments), client=client)


def parse_middleware(arguments, client=True, extra_plugins=(), parser=None):
    """Parse the middleware arguments only, returning the namespace"""
    plugins = Plugins(["data_transport"])
    for plugin in extra_plugins:
        plugins.register_plugin(plugin)
    parser = MiddleWareParser() if parser is None else parser
    MiddleWareParser.deprecation_warned = False
    parser._plugin_parser = PluginArgumentParser(plugins)
    composite = CompositeParser([parser])
    return composite.handle_arguments(
        composite.get_parser().parse_args(arguments), client=client
    )


def implementor(bound_class):
    """Unwrap the class bound by the plugin system"""
    return bound_class.func if isinstance(bound_class, functools.partial) else bound_class


class TestDataTransportCategory(unittest.TestCase):
    def test_category_registered_as_selection_of_transport_clients(self):
        plugins = Plugins(["data_transport"])
        self.assertIs(plugins.get_category_specification_class("data_transport"), TransportClient)
        self.assertEqual(plugins.get_category_plugin_type("data_transport"), PluginType.SELECTION)
        names = {plugin.get_name() for plugin in plugins.get_plugins("data_transport")}
        self.assertTrue({"zmq", "tcp"}.issubset(names), names)
        self.assertIn("data_transport", Plugins().get_all_categories())

    def test_built_in_plugins_implement_the_contract(self):
        for plugin in Plugins(["data_transport"]).get_plugins("data_transport"):
            transport = plugin.get_implementor()
            self.assertTrue(issubclass(transport, TransportClient))
            arguments = {
                keywords["dest"]: keywords["default"]
                for keywords in transport.get_arguments().values()
            }
            transport.check_arguments(**arguments)
            self.assertIsNotNone(transport.get_connection_uri(client=True, **arguments))
            self.assertIsNotNone(transport.get_connection_uri(client=False, **arguments))

    def test_pipeline_parser_lists_the_built_in_transports(self):
        names = [plugin.get_name() for plugin in StandardPipelineParser.get_data_transport_plugins()]
        self.assertIn("zmq", names)
        self.assertIn("tcp", names)

    def test_composed_gds_parser_binds_the_transport_once(self):
        """The fprime-gds parser composition (pipeline parser + singleton plugin parser) selects tcp end to end"""
        dictionary = Path(__file__).parent / "common" / "loaders" / "resources" / "RefTopologyDictionary.json"
        with mock.patch("fprime_gds.executables.cli.check_port") as check_port:
            args, _, _ = ConfigDrivenParser.parse_known_args(
                [StandardPipelineParser, PluginArgumentParser],
                arguments=[
                    "--dictionary", str(dictionary), "--packet-set-name", "PacketSet1",
                    "--data-transport-selection", "tcp", "--tts-port", "50127",
                ],
                client=False,
            )
        check_port.assert_called_once_with("0.0.0.0", 50127)
        self.assertEqual(args.connection_uri, "tcp://0.0.0.0:50127")
        self.assertIs(implementor(args.connection_transport), ThreadedTCPSocketClient)
        self.assertFalse(args.zmq)
        self.assertNotIn("data_transport", PluginArgumentParser()._plugin_map)

    def test_external_plugin_is_selectable(self):
        args = parse_middleware(
            ["--data-transport-selection", "fake-ground", "--fake-url", "http://gs:1"],
            extra_plugins=[FakeGroundSystemClient],
        )
        self.assertIs(implementor(args.connection_transport), FakeGroundSystemClient)
        self.assertEqual(args.connection_uri, "fake://http://gs:1")
        self.assertEqual(args.connection_transport().fake_url, "http://gs:1")


class TestBuiltInTransports(unittest.TestCase):
    def test_zmq_connection_uri_is_the_url_pair(self):
        self.assertEqual(
            ZmqClient.get_connection_uri(zmq_transport=("ipc:///a", "ipc:///b")),
            ["ipc:///a", "ipc:///b"],
        )
        self.assertEqual(ZmqClient.get_connection_uri(), ZmqClient.get_default_transport())
        self.assertEqual(ZmqClient(["ipc:///a", "ipc:///b"]).default_uri, ["ipc:///a", "ipc:///b"])

    def test_tcp_connection_uri_rewrites_wildcard_for_clients(self):
        self.assertEqual(
            ThreadedTCPSocketClient.get_connection_uri(client=True, tts_addr="0.0.0.0", tts_port=50123),
            "tcp://127.0.0.1:50123",
        )
        self.assertEqual(
            ThreadedTCPSocketClient.get_connection_uri(client=False, tts_addr="0.0.0.0", tts_port=50123),
            "tcp://0.0.0.0:50123",
        )
        self.assertEqual(
            ThreadedTCPSocketClient.get_connection_uri(client=True, tts_addr="10.0.0.0", tts_port=50123),
            "tcp://10.0.0.0:50123",
        )
        self.assertEqual(
            ThreadedTCPSocketClient.get_connection_uri(client=True, tts_addr="10.0.0.1", tts_port=50123),
            "tcp://10.0.0.1:50123",
        )
        with self.assertRaises(ValueError):
            ThreadedTCPSocketClient.check_arguments(tts_addr="0.0.0.0", tts_port=70000)

    def test_tcp_connect_without_uri_uses_constructor_arguments(self):
        client = ThreadedTCPSocketClient(tts_addr="10.0.0.1", tts_port=50126)
        client.sock = mock.MagicMock()
        with mock.patch.object(ThreadedTransportClient, "connect"):
            client.connect()
        client.sock.connect.assert_called_once_with(("10.0.0.1", 50126))

    def test_zmq_connect_without_uri_uses_constructor_arguments(self):
        client = ZmqClient(zmq_transport=["ipc:///a", "ipc:///b"])
        client.zmq = mock.MagicMock()
        with mock.patch.object(ThreadedTransportClient, "connect"):
            client.connect()
        client.zmq.configure.assert_called_once_with(["ipc:///a", "ipc:///b"], mock.ANY, mock.ANY)

    def test_tcp_client_keeps_constructor_defaults(self):
        client = ThreadedTCPSocketClient(sock=mock.MagicMock(), tts_addr="0.0.0.0", tts_port=50123)
        self.assertEqual(client.default_uri, "tcp://127.0.0.1:50123")


class TestYamcsTransitionalPlugin(unittest.TestCase):
    def setUp(self):
        try:
            from fprime_gds.common.yamcs_transport import YamcsClient
        except Exception:
            self.skipTest("yamcs-client not installed")
        self.client = YamcsClient

    def test_connection_uri_schemes(self):
        self.assertEqual(self.client.get_connection_uri(yamcs_url="http://y:8090"), "yamcs://y:8090")
        self.assertEqual(self.client.get_connection_uri(yamcs_url="https://y:8443"), "yamcs+https://y:8443")
        self.assertEqual(self.client.get_connection_uri(yamcs_url="y:8090"), "yamcs://y:8090")

    def test_rejects_other_schemes(self):
        with self.assertRaises(ValueError):
            self.client.check_arguments(yamcs_url="ftp://y:8090")
        with self.assertRaises(ValueError):
            self.client.get_connection_uri(yamcs_url="ftp://y:8090")


class TestMiddleWareParser(unittest.TestCase):
    def test_default_is_zmq(self):
        args = parse_middleware([])
        self.assertEqual(args.data_transport_selection, "zmq")
        self.assertIs(implementor(args.connection_transport), ZmqClient)
        self.assertEqual(args.connection_uri, ZmqClient.get_default_transport())
        self.assertTrue(args.zmq)

    def test_zmq_transport_urls(self):
        args = parse_middleware(["--zmq-transport", "ipc:///a", "ipc:///b"])
        self.assertEqual(args.connection_uri, ["ipc:///a", "ipc:///b"])
        self.assertEqual(args.zmq_transport, ["ipc:///a", "ipc:///b"])

    def test_tcp_selection_client(self):
        args = parse_middleware(["--data-transport-selection", "tcp", "--tts-port", "50123"])
        self.assertIs(implementor(args.connection_transport), ThreadedTCPSocketClient)
        self.assertEqual(args.connection_uri, "tcp://127.0.0.1:50123")
        self.assertEqual(args.tts_port, 50123)

    def test_tcp_selection_server_checks_port(self):
        with mock.patch("fprime_gds.executables.cli.check_port") as check_port:
            args = parse_middleware(
                ["--data-transport-selection", "tcp", "--tts-addr", "10.0.0.1", "--tts-port", "50124"],
                client=False,
            )
        check_port.assert_called_once_with("10.0.0.1", 50124)
        self.assertEqual(args.connection_uri, "tcp://10.0.0.1:50124")

    def test_zmq_selection_does_not_check_port(self):
        with mock.patch("fprime_gds.executables.cli.check_port") as check_port:
            parse_middleware([], client=False)
        check_port.assert_not_called()

    def test_no_zmq_is_deprecated_alias_of_tcp(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            args = parse_middleware(["--no-zmq", "--tts-port", "50125"])
        self.assertEqual(args.data_transport_selection, "tcp")
        self.assertIs(implementor(args.connection_transport), ThreadedTCPSocketClient)
        self.assertEqual(args.connection_uri, "tcp://127.0.0.1:50125")
        self.assertIn("--no-zmq is deprecated", stderr.getvalue())
        self.assertIn("--data-transport-selection tcp", stderr.getvalue())

    def test_zmq_flag_tracks_the_selection(self):
        self.assertTrue(parse_middleware([]).zmq)
        self.assertFalse(parse_middleware(["--data-transport-selection", "tcp"]).zmq)
        self.assertFalse(
            parse_middleware(
                ["--data-transport-selection", "fake-ground"], extra_plugins=[FakeGroundSystemClient]
            ).zmq
        )

    def test_children_are_given_the_selection_not_the_deprecated_alias(self):
        parser = MiddleWareParser()
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            args = parse_middleware(["--no-zmq", "--tts-port", "50125"], parser=parser)
        reproduced = parser.reproduce_cli_args(args)
        self.assertNotIn("--no-zmq", reproduced)
        self.assertEqual(reproduced[reproduced.index("--data-transport-selection") + 1], "tcp")
        self.assertEqual(reproduced[reproduced.index("--tts-port") + 1], "50125")

    def test_pipeline_parser_reproduces_the_selection_for_children(self):
        dictionary = Path(__file__).parent / "common" / "loaders" / "resources" / "RefTopologyDictionary.json"
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            args, _, _ = ConfigDrivenParser.parse_known_args(
                [StandardPipelineParser],
                arguments=["--dictionary", str(dictionary), "--packet-set-name", "PacketSet1", "--no-zmq"],
                client=True,
            )
        reproduced = StandardPipelineParser().reproduce_cli_args(args)
        self.assertNotIn("--no-zmq", reproduced)
        self.assertEqual(reproduced[reproduced.index("--data-transport-selection") + 1], "tcp")
        self.assertIn("--dictionary", reproduced)

    def test_singleton_plugin_parser_leaves_data_transport_to_the_middleware_parser(self):
        plugins = Plugins(["data_transport", "framing"])
        with mock.patch.object(Plugins, "system", return_value=plugins):
            flags = [flag for flags in PluginArgumentParser().get_arguments() for flag in flags]
        self.assertNotIn("--data-transport-selection", flags)
        self.assertIn("--framing-selection", flags)
        flags = [flag for flags in PluginArgumentParser(plugins).get_arguments() for flag in flags]
        self.assertIn("--data-transport-selection", flags)

    def test_no_zmq_warns_once_per_process(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            parse_middleware(["--no-zmq"])
            parse_middleware_again(["--no-zmq"])
        self.assertEqual(stderr.getvalue().count("--no-zmq is deprecated"), 1)

    def test_tcp_selection_server_keeps_wildcard_address(self):
        with mock.patch("fprime_gds.executables.cli.check_port") as check_port:
            args = parse_middleware(["--data-transport-selection", "tcp", "--tts-port", "50124"], client=False)
        check_port.assert_called_once_with("0.0.0.0", 50124)
        self.assertEqual(args.connection_uri, "tcp://0.0.0.0:50124")

    def test_tcp_selection_client_skips_port_check(self):
        with mock.patch("fprime_gds.executables.cli.check_port") as check_port:
            parse_middleware(["--data-transport-selection", "tcp", "--tts-port", "50124"], client=True)
        check_port.assert_not_called()

    def test_no_zmq_conflicts_with_explicit_zmq_selection(self):
        with self.assertRaises(ValueError) as context:
            parse_middleware(["--no-zmq", "--data-transport-selection", "zmq"])
        self.assertIn("conflicts with --data-transport-selection zmq", str(context.exception))

    def test_reused_parser_rebinds_on_every_call(self):
        parser = MiddleWareParser()
        first = parse_middleware(["--data-transport-selection", "tcp", "--tts-port", "50131"], parser=parser)
        second = parse_middleware([], parser=parser)
        third = parse_middleware(["--data-transport-selection", "tcp", "--tts-port", "50132"], parser=parser)
        self.assertEqual(first.connection_uri, "tcp://127.0.0.1:50131")
        self.assertIs(implementor(second.connection_transport), ZmqClient)
        self.assertEqual(third.connection_uri, "tcp://127.0.0.1:50132")

    def test_no_zmq_with_explicit_tcp_is_accepted(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            args = parse_middleware(["--no-zmq", "--data-transport-selection", "tcp"])
        self.assertEqual(args.data_transport_selection, "tcp")

    def test_no_zmq_conflicts_with_other_selection(self):
        with self.assertRaises(ValueError) as context:
            parse_middleware(
                ["--no-zmq", "--data-transport-selection", "fake-ground"],
                extra_plugins=[FakeGroundSystemClient],
            )
        self.assertIn("conflicts with --data-transport-selection fake-ground", str(context.exception))

    def test_selection_from_config_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "fprime-gds.yml"
            config_path.write_text(
                "command-line-options:\n  data-transport-selection: tcp\n  tts-port: 60000\n"
            )
            with mock.patch.dict(
                os.environ, {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: str(config_path)}
            ):
                args, _, _ = ConfigDrivenParser.parse_known_args(
                    [MiddleWareParser], arguments=[], client=True
                )
        self.assertEqual(args.data_transport_selection, "tcp")
        self.assertEqual(args.connection_uri, "tcp://127.0.0.1:60000")

    def test_command_line_selection_wins_over_config_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "fprime-gds.yml"
            config_path.write_text("command-line-options:\n  data-transport-selection: tcp\n")
            with mock.patch.dict(
                os.environ, {ConfigDrivenParser.DEFAULT_CONFIGURATION_PATH_ENV: str(config_path)}
            ):
                args, _, _ = ConfigDrivenParser.parse_known_args(
                    [MiddleWareParser], arguments=["--data-transport-selection", "zmq"], client=True
                )
        self.assertEqual(args.data_transport_selection, "zmq")
        self.assertIs(implementor(args.connection_transport), ZmqClient)

    def test_arguments_group_under_the_plugin_system(self):
        help_text = CompositeParser([MiddleWareParser]).get_parser().format_help()
        self.assertIn("--data-transport-selection", help_text)
        self.assertIn("--no-zmq", help_text)
        self.assertIn("Data Transport Plugin 'zmq' Options", help_text)
        self.assertIn("Data Transport Plugin 'tcp' Options", help_text)


class TestPipelineFactory(unittest.TestCase):
    def test_pipeline_uses_selected_transport(self):
        bound = functools.partial(FakeGroundSystemClient, fake_url="http://gs:2")
        args_ns = SimpleNamespace(
            dictionaries=mock.MagicMock(),
            files_storage_directory="/tmp/files",
            logs="/tmp/logs",
            disable_data_logging=True,
            file_uplink_cooldown=1,
            file_uplink_chunk_size=2,
            connection_transport=bound,
            connection_uri="fake://http://gs:2",
        )
        pipeline = mock.MagicMock()
        result = StandardPipelineParser.pipeline_factory(args_ns, pipeline)
        self.assertIs(result, pipeline)
        self.assertIs(pipeline.transport_implementation, bound)
        pipeline.connect.assert_called_once_with("fake://http://gs:2")


class TestPytestIntegration(unittest.TestCase):
    """The pytest plugin exposes the transport selection and keeps --use-yamcs as a deprecated alias"""

    @staticmethod
    def parse_pytest(args):
        parser = Parser(_ispytest=True)
        pytest_addoption(parser)
        namespace = parser.parse(["--dictionary", UNIT_TEST_DICTIONARY] + args)
        reproduced = StandardPipelineParser().reproduce_cli_args(namespace)
        arg_ns, _, _ = ConfigDrivenParser.parse_known_args(
            [StandardPipelineParser], arguments=reproduced, client=True
        )
        return arg_ns

    def test_pytest_selects_tcp(self):
        arg_ns = self.parse_pytest(["--data-transport-selection", "tcp", "--tts-port", "50126"])
        self.assertEqual(arg_ns.data_transport_selection, "tcp")
        self.assertEqual(arg_ns.connection_uri, "tcp://127.0.0.1:50126")

    def test_pytest_defaults_to_zmq(self):
        arg_ns = self.parse_pytest([])
        self.assertEqual(arg_ns.data_transport_selection, "zmq")
        self.assertIs(implementor(arg_ns.connection_transport), ZmqClient)

    @staticmethod
    def config(use_yamcs):
        return SimpleNamespace(getoption=lambda name: use_yamcs if name == "--use-yamcs" else None)

    def test_use_yamcs_not_given_is_a_no_op(self):
        self.assertEqual(
            pytest_integration._apply_deprecated_transport_options(self.config(False), ["--a"]),
            ["--a"],
        )

    def test_use_yamcs_appends_selection_with_warning(self):
        yamcs_plugin = SimpleNamespace(get_name=lambda: "yamcs")
        with mock.patch.object(
            StandardPipelineParser, "get_data_transport_plugins", return_value=[yamcs_plugin]
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = pytest_integration._apply_deprecated_transport_options(
                self.config(True), ["--yamcs-url", "http://y:1"]
            )
        self.assertEqual(result, ["--yamcs-url", "http://y:1", "--data-transport-selection", "yamcs"])
        self.assertIn("--use-yamcs is deprecated", stderr.getvalue())

    def test_use_yamcs_with_explicit_yamcs_selection(self):
        yamcs_plugin = SimpleNamespace(get_name=lambda: "yamcs")
        with mock.patch.object(
            StandardPipelineParser, "get_data_transport_plugins", return_value=[yamcs_plugin]
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            result = pytest_integration._apply_deprecated_transport_options(
                self.config(True), ["--data-transport-selection", "yamcs"]
            )
        self.assertEqual(result, ["--data-transport-selection", "yamcs"])

    def test_use_yamcs_conflicts_with_other_selection(self):
        yamcs_plugin = SimpleNamespace(get_name=lambda: "yamcs")
        with mock.patch.object(
            StandardPipelineParser, "get_data_transport_plugins", return_value=[yamcs_plugin]
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(pytest.UsageError):
                pytest_integration._apply_deprecated_transport_options(
                    self.config(True), ["--data-transport-selection", "tcp"]
                )

    def test_use_yamcs_without_plugin_recommends_fprime_yamcs(self):
        with mock.patch.object(StandardPipelineParser, "get_data_transport_plugins", return_value=[]):
            with self.assertRaises(pytest.UsageError) as context:
                pytest_integration._apply_deprecated_transport_options(self.config(True), [])
        self.assertIn("fprime-gds[yamcs]", str(context.exception))


class TestRunDeploymentMiddleware(unittest.TestCase):
    def run_main(self, selection, communication_selection="none"):
        parsed_args = SimpleNamespace(
            data_transport_selection=selection,
            communication_selection=communication_selection,
            app=None,
            application_arguments=None,
            gui="none",
        )
        plugins = mock.MagicMock()
        plugins.get_feature_classes.return_value = []
        with mock.patch.object(run_deployment, "parse_args", return_value=parsed_args), mock.patch.object(
            run_deployment, "launch_tts"
        ) as launch_tts, mock.patch.object(run_deployment, "launch_comm") as launch_comm, mock.patch.object(
            run_deployment, "launch_html"
        ), mock.patch.object(run_deployment, "launch_app"), mock.patch.object(
            run_deployment.Plugins, "system", return_value=plugins
        ), mock.patch.object(run_deployment.sys, "stderr", new_callable=io.StringIO) as stderr:
            run_deployment.main()
        self.launch_comm = launch_comm
        self.stderr = stderr.getvalue()
        return launch_tts

    def test_tcp_launches_threaded_tcp_server(self):
        self.run_main("tcp").assert_called_once()

    def test_zmq_launches_no_middleware_process(self):
        self.run_main("zmq").assert_not_called()

    def test_external_transport_launches_no_middleware_process(self):
        self.run_main("fake-ground").assert_not_called()

    def test_comm_bridge_launched_for_bridged_transports(self):
        for selection in ("zmq", "tcp"):
            with self.subTest(selection=selection):
                self.run_main(selection, communication_selection="ip")
                self.launch_comm.assert_called_once()

    def test_comm_bridge_not_launched_for_external_transport(self):
        self.run_main("fake-ground", communication_selection="ip")
        self.launch_comm.assert_not_called()
        self.assertIn("Not launching the comm bridge", self.stderr)
