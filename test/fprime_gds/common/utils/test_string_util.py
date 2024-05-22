"""
Tests format_string util

@Created on March 18, 2021
@janamian
"""

import unittest

from fprime_gds.common.utils.string_util import (
    format_string_template,
    preprocess_c_style_format_str,
    preprocess_fpp_format_str,
)


class TestFormatString(unittest.TestCase):
    ########################## C-style Tests ##########################
    def test_format_with_no_issue(self):
        template = "Opcode 0x%04X dispatched to port %d and value %f"
        values = (181, 8, 1.234)
        expected = "Opcode 0x00B5 dispatched to port 8 and value 1.234000"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_value_with_string_input_as_other_types(self):
        template = "Opcode 0x%04X dispatched to port %u and value %.2f"
        values = (181, "8", 1.234)
        expected = "Opcode 0x00B5 dispatched to port 8 and value 1.23"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_with_format_spec(self):
        template = "Opcode 0x%04X dispatched to port %04d and value %0.02f"
        values = (181, 8, 1.234)
        expected = "Opcode 0x00B5 dispatched to port 0008 and value 1.23"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_bad_case(self):
        template = "Opcode 0x%04X dispatched to port %04d and value %0.02f"
        values = ("181", "8", "0.123")
        with self.assertRaises(ValueError):
            format_string_template(preprocess_c_style_format_str(template), values)

    def test_format_decimal_with_width_flag(self):
        template = "Decimals: %d %ld"
        values = (1977, 650000)
        expected = "Decimals: 1977 650000"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_preceding_with_blanks(self):
        template = "Preceding with blanks: %10d"
        values = (1977,)
        expected = "Preceding with blanks:       1977"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_preceding_with_zeros(self):
        template = "Preceding with zeros: %010d"
        values = (1977,)
        expected = "Preceding with zeros: 0000001977"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_some_different_radices(self):
        template = "Some different radices: %d %x %o %#x %#o"
        values = (100, 100, 100, 100, 100)
        # The alternate form causes a leading octal specifier ('0o') to be inserted before the first digit. This is different than C behavior
        # `See https://docs.python.org/3/library/stdtypes.html#printf-style-bytes-formatting`
        expected = "Some different radices: 100 64 144 0x64 0o144"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_floats(self):
        template = "floats: %4.2f %+.0e %E"
        values = (3.1416, 3.1416, 3.1416)
        expected = "floats: 3.14 +3e+00 3.141600E+00"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_asterisk_width(self):
        # asterisk `*` is not supported by python string-format
        template = "Width trick: %*d"
        values = (5, 10)
        with self.assertRaises(ValueError):
            format_string_template(preprocess_c_style_format_str(template), values)

    def test_format_regular_string(self):
        template = "%s"
        values = ("A string",)
        expected = "A string"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_percent_sign(self):
        template = "%.2f%%"
        values = (1.23456,)
        expected = "1.23%"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_single_value(self):
        template = "%.2f%%"
        values = 1.23456
        expected = "1.23%"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_list_value(self):
        template = "%.2f%%, %.2f%%"
        values = [1.23456, 1.23456]
        expected = "1.23%, 1.23%"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_tuple_value(self):
        template = "%.2f%%, %.2f%%"
        values = (1.23456, 1.23456)
        expected = "1.23%, 1.23%"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_format_unsigned_flag_with_length_flag(self):
        template = "Something %lu something %llu something else %lu"
        values = (123456, 123457, 123458)
        expected = "Something 123456 something 123457 something else 123458"
        actual = format_string_template(preprocess_c_style_format_str(template), values)
        self.assertEqual(expected, actual)


    ########################## FPP-style Tests ##########################

    def test_fpp_format_with_no_issue(self):
        template = "Opcode 0x{04X} dispatched to port {} and value {f}"
        values = (181, 8, 1.234)
        expected = "Opcode 0x00B5 dispatched to port 8 and value 1.234000"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_value_with_string_input_as_other_types(self):
        template = "Opcode 0x{04x} dispatched to port {} and value {.2f}"
        values = (181, "8", 1.234)
        expected = "Opcode 0x00b5 dispatched to port 8 and value 1.23"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_with_format_spec(self):
        template = "Opcode 0x{04X} dispatched to port {04d} and value {0.02f}"
        values = (181, 8, 1.234)
        expected = "Opcode 0x00B5 dispatched to port 0008 and value 1.23"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_bad_case(self):
        template = "Opcode 0x{04X} dispatched to port {04d} and value {0.02f}"
        values = ("181", "8", "0.123")
        with self.assertRaises(ValueError):
            format_string_template(preprocess_fpp_format_str(template), values)

    def test_fpp_format_decimal_with_width_flag(self):
        template = "Decimals: {} {}"
        values = (1977, 650000)
        expected = "Decimals: 1977 650000"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_preceding_with_blanks(self):
        template = "Preceding with blanks: {10d}"
        values = (1977,)
        expected = "Preceding with blanks:       1977"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_preceding_with_zeros(self):
        template = "Preceding with zeros: {010d}"
        values = (1977,)
        expected = "Preceding with zeros: 0000001977"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_with_escape_sequence(self):
        template = "Some different radices: {} 0x{x} {{ i'm escaped }}"
        values = (100, 100, 100, 100, 100)
        expected = "Some different radices: 100 0x64 { i'm escaped }"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_regular_string(self):
        template = "{}"
        values = ["A string"] # list instead of tuples
        expected = "A string"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)

    def test_fpp_format_list_value(self):
        template = "{.2f}%, {.2f}%"
        values = [1.23456, 1.23456]
        expected = "1.23%, 1.23%"
        actual = format_string_template(preprocess_fpp_format_str(template), values)
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
