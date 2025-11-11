"""
Tests Command Data

Created on Jan 11, 2025
@author: AlesKus
"""

import unittest
from fprime_gds.common.models.serialize.bool_type import BoolType
import fprime_gds.common.models.serialize.numerical_types as numerical_types
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.data_types.cmd_data import CmdData


class CmdDataTest(unittest.TestCase):
    def test_str_bool_command_arg(self):
        """
        Tests CmdData::get_str() for a command with one bool argument
        """
        opcode = 42
        mnemonic = "TEST_CMD_BOOL"
        component = "PythonTests"
        arguments = [("status", None, BoolType)]
        command_template = CmdTemplate(opcode, mnemonic, component, arguments)
        cmd_data = CmdData((True,), command_template)

        data_str = cmd_data.get_str()

        self.assertIn("[True]", data_str)

    def test_str_numerical_command_args(self):
        """
        Tests CmdData::get_str() for a command with several numerical arguments
        """
        opcode = 43
        mnemonic = "TEST_CMD_NUMERICS"
        component = "PythonTests"
        arguments = [
            ("just_int", None, numerical_types.U32Type),
            ("just_float", None, numerical_types.F64Type),
            ("just_byte", None, numerical_types.I8Type),
        ]
        command_template = CmdTemplate(opcode, mnemonic, component, arguments)
        cmd_data = CmdData((12345, 98.765, 127), command_template)

        data_str = cmd_data.get_str()

        self.assertIn("[12345, 98.765, 127]", data_str)

    def test_str_string_command_args(self):
        """
        Tests CmdData::get_str() for a command with one string argument
        """
        opcode = 44
        mnemonic = "TEST_CMD_STR"
        component = "PythonTests"
        arguments = [
            ("just_string", None, StringType.construct_type(f"String_{128}", 128))
        ]
        command_template = CmdTemplate(opcode, mnemonic, component, arguments)
        cmd_data = CmdData(("Everything is good",), command_template)

        data_str = cmd_data.get_str()

        self.assertIn("['Everything is good']", data_str)


if __name__ == "__main__":
    unittest.main()
