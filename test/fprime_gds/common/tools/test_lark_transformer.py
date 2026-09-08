"""Unit tests for Lark transformer array and object parsing.

Tests the SeqTransformer's ability to handle:
1. Array literals with various value types
2. Object/dictionary literals with key-value pairs
3. Nested structures (arrays in arrays, objects in arrays, etc.)

The transformer converts arrays and objects to JSON strings for compatibility
with the F' serialization layer.
"""

import json
import unittest
from lark import Lark
from lark.exceptions import LarkError
from pathlib import Path

from fprime_gds.common.parsers.lark_seq_parser import SeqTransformer


class TestSeqTransformer(unittest.TestCase):
    """Test the SeqTransformer for array and object transformations."""

    @classmethod
    def setUpClass(cls):
        """Load the grammar for parsing."""
        grammar_path = Path(__file__).parent.parent.parent.parent.parent / "src" / "fprime_gds" / "common" / "parsers" / "grammar.lark"
        with open(grammar_path) as f:
            cls.parser = Lark(f.read(), start="input", parser="lalr")
        cls.transformer = SeqTransformer()

    def parse_and_transform(self, text):
        """Helper to parse text and transform it."""
        tree = self.parser.parse(text)
        return self.transformer.transform(tree)

    def test_empty_array(self):
        """Test parsing an empty array."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST []")
        # Extract the argument from the command
        arg = result.children[2]  # first value node
        transformed_arg = self.transformer.transform(arg)
        # Arrays are converted to JSON strings
        self.assertEqual(transformed_arg, "[]")
        self.assertEqual(json.loads(transformed_arg), [])

    def test_simple_array(self):
        """Test parsing a simple array with integers."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST [1, 2, 3]")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), [1, 2, 3])

    def test_array_with_trailing_comma(self):
        """Test parsing an array with a trailing comma."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST [1, 2, 3,]")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), [1, 2, 3])

    def test_array_mixed_types(self):
        """Test parsing an array with mixed types."""
        result = self.parse_and_transform('R00:00:01 CMD_TEST [1, "hello", true, 3.14]')
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), [1, "hello", True, 3.14])

    def test_array_with_hex(self):
        """Test parsing an array with hex numbers."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST [0xFF, 0x10, 255]")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), [255, 16, 255])

    def test_array_with_names(self):
        """Test parsing an array with enum/identifier names."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST [ENUM_VALUE, AnotherValue]")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), ["ENUM_VALUE", "AnotherValue"])

    def test_nested_arrays(self):
        """Test parsing nested arrays."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST [[1, 2], [3, 4]]")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), [[1, 2], [3, 4]])

    def test_empty_object(self):
        """Test parsing an empty object."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST {}")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), {})

    def test_simple_object(self):
        """Test parsing a simple object with key-value pairs."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST {x: 10, y: 20}")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), {"x": 10, "y": 20})

    def test_object_with_trailing_comma(self):
        """Test parsing an object with a trailing comma."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST {x: 10, y: 20,}")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), {"x": 10, "y": 20})

    def test_object_mixed_value_types(self):
        """Test parsing an object with various value types."""
        result = self.parse_and_transform('R00:00:01 CMD_TEST {num: 42, str: "test", flag: true}')
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), {"num": 42, "str": "test", "flag": True})

    def test_object_with_array_value(self):
        """Test parsing an object containing an array value."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST {coords: [1, 2, 3]}")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), {"coords": [1, 2, 3]})

    def test_object_with_nested_object(self):
        """Test parsing nested objects."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST {outer: {inner: 42}}")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), {"outer": {"inner": 42}})

    def test_array_of_objects(self):
        """Test parsing an array containing objects."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST [{x: 1}, {x: 2}]")
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        self.assertEqual(json.loads(transformed_arg), [{"x": 1}, {"x": 2}])

    def test_complex_nested_structure(self):
        """Test parsing a complex nested structure."""
        result = self.parse_and_transform(
            'R00:00:01 CMD_TEST {points: [{x: 1, y: 2}, {x: 3, y: 4}], name: "test"}'
        )
        arg = result.children[2]
        transformed_arg = self.transformer.transform(arg)
        expected = {
            "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
            "name": "test"
        }
        self.assertEqual(json.loads(transformed_arg), expected)

    def test_multiple_arguments_with_arrays(self):
        """Test parsing multiple arguments including arrays."""
        result = self.parse_and_transform("R00:00:01 CMD_TEST 100 [1, 2, 3] true")
        # Should have 3 value nodes after mnemonic
        arg1 = result.children[2]
        arg2 = result.children[3]
        arg3 = result.children[4]

        t1 = self.transformer.transform(arg1)
        t2 = self.transformer.transform(arg2)
        t3 = self.transformer.transform(arg3)

        self.assertEqual(t1, 100)
        self.assertEqual(json.loads(t2), [1, 2, 3])
        self.assertEqual(t3, True)

    def test_multiple_arguments_with_objects(self):
        """Test parsing multiple arguments including objects."""
        result = self.parse_and_transform('R00:00:01 CMD_TEST "str" {key: 42} false')
        arg1 = result.children[2]
        arg2 = result.children[3]
        arg3 = result.children[4]

        t1 = self.transformer.transform(arg1)
        t2 = self.transformer.transform(arg2)
        t3 = self.transformer.transform(arg3)

        self.assertEqual(t1, "str")
        self.assertEqual(json.loads(t2), {"key": 42})
        self.assertEqual(t3, False)


class TestSeqTransformerBasics(unittest.TestCase):
    """Test basic transformer functionality that was already present."""

    @classmethod
    def setUpClass(cls):
        """Load the grammar for parsing."""
        grammar_path = Path(__file__).parent.parent.parent.parent.parent / "src" / "fprime_gds" / "common" / "parsers" / "grammar.lark"
        with open(grammar_path) as f:
            cls.parser = Lark(f.read(), start="input", parser="lalr")
        cls.transformer = SeqTransformer()

    def test_number_integer(self):
        """Test parsing integer numbers."""
        result = self.parser.parse("R00:00:01 CMD_TEST 42")
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertEqual(transformed, 42)

    def test_number_float(self):
        """Test parsing float numbers."""
        result = self.parser.parse("R00:00:01 CMD_TEST 3.14")
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertAlmostEqual(transformed, 3.14)

    def test_number_hex(self):
        """Test parsing hexadecimal numbers."""
        result = self.parser.parse("R00:00:01 CMD_TEST 0xFF")
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertEqual(transformed, 255)

    def test_string(self):
        """Test parsing string literals."""
        result = self.parser.parse('R00:00:01 CMD_TEST "hello world"')
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertEqual(transformed, "hello world")

    def test_boolean_true(self):
        """Test parsing boolean true values."""
        for variant in ["True", "true", "TRUE"]:
            result = self.parser.parse(f"R00:00:01 CMD_TEST {variant}")
            arg = result.children[2]
            transformed = self.transformer.transform(arg)
            self.assertTrue(transformed)

    def test_boolean_false(self):
        """Test parsing boolean false values."""
        for variant in ["False", "false", "FALSE"]:
            result = self.parser.parse(f"R00:00:01 CMD_TEST {variant}")
            arg = result.children[2]
            transformed = self.transformer.transform(arg)
            self.assertFalse(transformed)

    def test_name_identifier(self):
        """Test parsing NAME tokens (enums, identifiers)."""
        result = self.parser.parse("R00:00:01 CMD_TEST ENUM_VALUE")
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertEqual(transformed, "ENUM_VALUE")

    def test_number_negative_integer(self):
        """Test parsing negative integer numbers."""
        result = self.parser.parse("R00:00:01 CMD_TEST -4")
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertEqual(transformed, -4)

    def test_number_negative_float(self):
        """Test parsing negative float numbers."""
        result = self.parser.parse("R00:00:01 CMD_TEST -3.14")
        arg = result.children[2]
        transformed = self.transformer.transform(arg)
        self.assertAlmostEqual(transformed, -3.14)

    def test_number_hex_no_sign(self):
        """Hex literals represent a bit pattern, not a signed quantity, so a
        leading sign is rejected rather than silently negated."""
        with self.assertRaises(LarkError):
            self.parser.parse("R00:00:01 CMD_TEST -0xFF")

    def test_multiple_arguments_with_negative_numbers(self):
        """Test parsing multiple arguments mixing positive and negative numbers."""
        result = self.parser.parse("R00:00:01 CMD_TEST 0 2 150 ARG_STR_1 ARG_STR_2 -4 13")
        args = [self.transformer.transform(child) for child in result.children[2:]]
        self.assertEqual(
            args, [0, 2, 150, "ARG_STR_1", "ARG_STR_2", -4, 13]
        )


if __name__ == "__main__":
    unittest.main()
