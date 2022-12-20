import platform
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from fprime_gds.executables import run_deployment


class TestRunDeployment(unittest.TestCase):

    def test_as_in_installation_instructions(self):
        # Same as the "Testing F´ GDS Installation Via Running HTML GUI" from
        # https://nasa.github.io/fprime/INSTALL.html
        # fprime-gds -g html -r <path to fprime checkout>/Ref/build-artifacts
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.create_fake_deployment_structure(temporary_directory)
            with mock.patch("sys.argv", ["main", "-g", "html", "-r", temporary_directory]):
                run_deployment.parse_args()

    def create_fake_deployment_structure(self, temporary_directory):
        system_dir = Path(temporary_directory) / platform.system()

        bin_dir = system_dir / "bin"
        bin_dir.mkdir(parents=True)
        bin_file = bin_dir / "Test"
        with bin_file.open(mode="wb") as fake_app:
            fake_app.write("fake app".encode("utf-8"))

        dictionary_dir = system_dir / "dict"
        dictionary_dir.mkdir(parents=True)
        dictionary_file = dictionary_dir / "TestTopologyAppDictionary.xml"
        with dictionary_file.open(mode="w") as fake_dictionary:
            fake_dictionary.write("<test></test>")
