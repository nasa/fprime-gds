import unittest
from pathlib import Path

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
