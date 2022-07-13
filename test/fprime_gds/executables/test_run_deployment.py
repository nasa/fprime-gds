import unittest
from unittest import mock
from unittest.mock import patch

from fprime_gds.executables import run_deployment


class TestRunDeployment(unittest.TestCase):

    def test_as_in_installation_instructions(self):
        # Same as the "Testing F´ GDS Installation Via Running HTML GUI" from
        # https://nasa.github.io/fprime/INSTALL.html
        # fprime-gds -g html -r <path to fprime checkout>/Ref/build-artifacts
        with mock.patch("sys.argv", ["main", "-g", "html", "-r", "./build-artifacts"]):
            with mock.patch("os.path.isdir", return_value=True):
                run_deployment.get_settings()
