import unittest
from pathlib import Path
from unittest import mock

from fprime_gds.executables import utils


class TestFormatString(unittest.TestCase):

    def test_find_app_with_no_bin_dir_exits(self):
        path_with_no_bin = Path("")
        with self.assertRaises(SystemExit):
            utils.find_app(path_with_no_bin)

    def test_find_dict_with_no_dict_dir_exits(self):
        path_with_no_dict = Path("")
        with self.assertRaises(SystemExit):
            utils.find_app(path_with_no_dict)

    def test_run_wrapped_application_uses_supplied_cwd(self):
        cwd = Path("deployment") / "bin"
        child = mock.Mock(returncode=None)

        with mock.patch.object(utils.subprocess, "Popen", return_value=child) as popen:
            result = utils.run_wrapped_application(["app"], cwd=cwd)

        self.assertIs(result, child)
        popen.assert_called_once_with(
            ["app"], stdout=None, stderr=utils.subprocess.STDOUT, env=None, cwd=cwd
        )
