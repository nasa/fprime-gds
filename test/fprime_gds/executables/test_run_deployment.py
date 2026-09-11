import platform
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fprime_gds.executables import run_deployment


class TestRunDeployment(unittest.TestCase):

    def test_as_in_installation_instructions(self):
        # Same as the "Testing F´ GDS Installation Via Running HTML GUI" from
        # https://nasa.github.io/fprime/INSTALL.html
        # fprime-gds -g html -d <path to fprime checkout>/Ref/build-artifacts/<platform>/Test
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.create_fake_deployment_structure(temporary_directory)
            with mock.patch("sys.argv", ["main", "-g", "html", "-d", str(Path(temporary_directory) / platform.system() / "Test")]):
                run_deployment.parse_args()

    def test_launch_app_runs_from_app_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path = Path(temporary_directory) / "bin" / "TestApp"
            app_path.parent.mkdir()
            logs_path = Path(temporary_directory) / "logs"
            logs_path.mkdir()
            parsed_args = SimpleNamespace(
                app=app_path,
                logs=str(logs_path),
                port=50000,
                address="127.0.0.1",
                application_arguments=None,
            )

            with mock.patch.object(run_deployment, "launch_process") as launch_process:
                run_deployment.launch_app(parsed_args)

            launch_process.assert_called_once_with(
                [
                    app_path.absolute(),
                    "-p",
                    str(parsed_args.port),
                    "-a",
                    parsed_args.address,
                ],
                name=f"{app_path.name} Application",
                logfile=str(logs_path / f"{app_path.name}.log"),
                launch_time=1,
                cwd=app_path.parent,
            )

    def test_app_connection_ip(self):
        parsed_args = SimpleNamespace(communication_selection="ip", address="0.0.0.0", port=50000)
        self.assertEqual(run_deployment.app_connection(parsed_args), ("0.0.0.0", 50000))

    def test_app_connection_tcp_fast_server_defaults_to_loopback(self):
        parsed_args = SimpleNamespace(
            communication_selection="tcp-fast-server", tcp_fast_address=None, tcp_fast_port=50123
        )
        self.assertEqual(run_deployment.app_connection(parsed_args), ("127.0.0.1", 50123))

    def test_app_connection_tcp_fast_server_explicit_wildcard_uses_loopback(self):
        for wildcard in ("0.0.0.0", ""):
            parsed_args = SimpleNamespace(
                communication_selection="tcp-fast-server", tcp_fast_address=wildcard, tcp_fast_port=50000
            )
            self.assertEqual(run_deployment.app_connection(parsed_args), ("127.0.0.1", 50000))

    def test_app_connection_tcp_fast_server_explicit_address(self):
        parsed_args = SimpleNamespace(
            communication_selection="tcp-fast-server", tcp_fast_address="192.168.1.5", tcp_fast_port=50000
        )
        self.assertEqual(run_deployment.app_connection(parsed_args), ("192.168.1.5", 50000))

    def test_app_connection_other_adapters_do_not_launch(self):
        for selection in ("udp", "uart", "tcp-fast-client", "none"):
            parsed_args = SimpleNamespace(communication_selection=selection)
            self.assertIsNone(run_deployment.app_connection(parsed_args), selection)

    def test_launch_app_uses_explicit_connection(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path = Path(temporary_directory) / "bin" / "TestApp"
            app_path.parent.mkdir()
            parsed_args = SimpleNamespace(app=app_path, logs=temporary_directory, application_arguments=None)
            with mock.patch.object(run_deployment, "launch_process") as launch_process:
                run_deployment.launch_app(parsed_args, connection=("127.0.0.1", 50123))
            self.assertEqual(
                launch_process.call_args.args[0],
                [app_path.absolute(), "-p", "50123", "-a", "127.0.0.1"],
            )

    def create_fake_deployment_structure(self, temporary_directory):
        system_dir = Path(temporary_directory) / platform.system() / "Test"

        bin_dir = system_dir / "bin"
        bin_dir.mkdir(parents=True)
        bin_file = bin_dir / "Test"
        with bin_file.open(mode="wb") as fake_app:
            fake_app.write("fake app".encode("utf-8"))

        unit_test_dictionary = Path(__file__).parent.parent / "common" / "testing_fw" / "UnitTestDictionary.xml"
        dictionary_dir = system_dir / "dict"
        dictionary_dir.mkdir(parents=True)
        dictionary_file = dictionary_dir / "TestTopologyAppDictionary.xml"
        with dictionary_file.open(mode="w") as fake_dictionary:
            with open(unit_test_dictionary, "r") as file_handle:
                fake_dictionary.write(file_handle.read())
