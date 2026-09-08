"""Regression tests for sequence file parsing and generation.

Tests the sequence compiler end-to-end by:
1. Generating .bin files from valid .seq files and comparing against expected .bin files
2. Capturing error messages from invalid .seq files and comparing against expected .txt files
"""

import difflib
import filecmp
import os
import unittest
from pathlib import Path
import tempfile

import fprime_gds.common.tools.seqgen as seqgen


class TestSequenceGeneration(unittest.TestCase):
    """Test sequence generation from valid sequence files."""

    @classmethod
    def setUpClass(cls):
        """Set up test paths."""
        cls.test_dir = Path(__file__).parent
        cls.input_dir = cls.test_dir / "input"
        cls.expected_dir = cls.test_dir / "expected"
        cls.resources_dir = cls.test_dir / "resources"
        cls.dictionary = cls.resources_dir / "simple_dictionary.json"
        cls.timebase = 0xFFFF

    def generate_and_compare(self, seq_filename, expected_bin_filename):
        """Generate a binary sequence file and compare against expected output."""
        input_file = self.input_dir / seq_filename
        expected_bin = self.expected_dir / expected_bin_filename

        # Generate binary in temporary location
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            output_file = Path(tmp.name)

        try:
            seqgen.generateSequence(
                str(input_file),
                str(output_file),
                str(self.dictionary),
                self.timebase
            )

            # Compare generated file with expected
            self.assertTrue(
                output_file.exists(),
                f"Output file was not created: {output_file}"
            )

            if not expected_bin.exists():
                # Save the generated file as expected for first run
                import shutil
                expected_bin.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(output_file, expected_bin)
                self.skipTest(f"Created expected output file: {expected_bin}")

            files_match = filecmp.cmp(output_file, expected_bin, shallow=False)
            self.assertTrue(
                files_match,
                f"Generated binary does not match expected: {seq_filename}"
            )

        finally:
            # Clean up temporary file
            if output_file.exists():
                output_file.unlink()

    def test_simple_sequence(self):
        """Test the existing simple_sequence.seq file."""
        self.generate_and_compare("simple_sequence.seq", "simple_expected.bin")

    def test_valid_relative_time(self):
        """Test sequence with relative time commands."""
        self.generate_and_compare("valid_relative.seq", "valid_relative.bin")

    def test_valid_absolute_time(self):
        """Test sequence with absolute time commands."""
        self.generate_and_compare("valid_absolute.seq", "valid_absolute.bin")

    def test_valid_arguments(self):
        """Test sequence with various argument types."""
        self.generate_and_compare("valid_arguments.seq", "valid_arguments.bin")

    def test_valid_delimiters(self):
        """Test sequence with comma and space delimiters."""
        self.generate_and_compare("valid_delimiters.seq", "valid_delimiters.bin")

    def test_valid_comments(self):
        """Test sequence with comments."""
        self.generate_and_compare("valid_comments.seq", "valid_comments.bin")

    def test_empty_file(self):
        """Test empty sequence file."""
        self.generate_and_compare("empty_file.seq", "empty_file.bin")


class TestEnhancedArguments(unittest.TestCase):
    """Test enhanced argument types to improve coverage."""

    @classmethod
    def setUpClass(cls):
        """Set up test paths."""
        cls.test_dir = Path(__file__).parent
        cls.input_dir = cls.test_dir / "input"
        cls.expected_dir = cls.test_dir / "expected"
        cls.resources_dir = cls.test_dir / "resources"
        cls.dictionary = cls.resources_dir / "enhanced_dictionary.json"
        cls.timebase = 0xFFFF

    def generate_and_compare(self, seq_filename, expected_bin_filename):
        """Generate a binary sequence file and compare against expected output."""
        input_file = self.input_dir / seq_filename
        expected_bin = self.expected_dir / expected_bin_filename

        # Generate binary in temporary location
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            output_file = Path(tmp.name)

        try:
            seqgen.generateSequence(
                str(input_file),
                str(output_file),
                str(self.dictionary),
                self.timebase
            )

            # Compare generated file with expected
            self.assertTrue(
                output_file.exists(),
                f"Output file was not created: {output_file}"
            )

            if not expected_bin.exists():
                # Save the generated file as expected for first run
                import shutil
                expected_bin.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(output_file, expected_bin)
                self.skipTest(f"Created expected output file: {expected_bin}")

            files_match = filecmp.cmp(output_file, expected_bin, shallow=False)
            self.assertTrue(
                files_match,
                f"Generated binary does not match expected: {seq_filename}"
            )

        finally:
            # Clean up temporary file
            if output_file.exists():
                output_file.unlink()

    def test_float_arguments(self):
        """Test sequence with float arguments containing decimal points."""
        self.generate_and_compare("valid_float_args.seq", "valid_float_args.bin")

    def test_boolean_arguments(self):
        """Test sequence with boolean arguments (True/False variations)."""
        self.generate_and_compare("valid_bool_args.seq", "valid_bool_args.bin")

    def test_enum_arguments(self):
        """Test sequence with enum/string arguments."""
        self.generate_and_compare("valid_enum_args.seq", "valid_enum_args.bin")

    def test_hex_arguments(self):
        """Test sequence with hexadecimal arguments."""
        self.generate_and_compare("valid_hex_args.seq", "valid_hex_args.bin")

    def test_string_arguments(self):
        """Test sequence with quoted string arguments."""
        self.generate_and_compare("valid_string_args.seq", "valid_string_args.bin")

    def test_array_arguments(self):
        """Test sequence with array arguments."""
        self.generate_and_compare("valid_array_args.seq", "valid_array_args.bin")

    def test_object_arguments(self):
        """Test sequence with object/dictionary arguments."""
        self.generate_and_compare("valid_object_args.seq", "valid_object_args.bin")

    def test_nested_arguments(self):
        """Test sequence with nested structures (arrays of structs, structs with arrays)."""
        self.generate_and_compare("valid_nested_args.seq", "valid_nested_args.bin")

    def test_negative_arguments(self):
        """Test sequence with negative/signed numeric arguments, including inside arrays and objects."""
        self.generate_and_compare("valid_negative_args.seq", "valid_negative_args.bin")


class TestSequenceErrors(unittest.TestCase):
    """Test error handling for invalid sequence files."""

    @classmethod
    def setUpClass(cls):
        """Set up test paths."""
        cls.test_dir = Path(__file__).parent
        cls.input_dir = cls.test_dir / "input"
        cls.expected_dir = cls.test_dir / "expected"
        cls.resources_dir = cls.test_dir / "resources"
        cls.dictionary = cls.resources_dir / "simple_dictionary.json"
        cls.timebase = 0xFFFF

    def generate_and_check_error(self, seq_filename, expected_error_filename):
        """
        Try to generate sequence and verify error message matches expected.

        @param seq_filename: Input .seq file
        @param expected_error_filename: Expected error message .txt file
        """
        input_file = self.input_dir / seq_filename
        expected_error = self.expected_dir / expected_error_filename

        # Generate binary in temporary location
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            output_file = Path(tmp.name)

        try:
            # Should raise an exception
            with self.assertRaises(Exception) as ctx:
                seqgen.generateSequence(
                    str(input_file),
                    str(output_file),
                    str(self.dictionary),
                    self.timebase
                )

            # Get the error message and normalize paths for reproducibility
            error_msg = str(ctx.exception)
            error_msg = self._normalize_error_message(error_msg, input_file)

            # Check if expected error file exists
            if not expected_error.exists():
                # Create expected error file for first run
                expected_error.parent.mkdir(parents=True, exist_ok=True)
                expected_error.write_text(error_msg)
                self.skipTest(f"Created expected error file: {expected_error}")

            # Read expected error
            expected_msg = expected_error.read_text().strip()

            # Check that expected error substring is in actual error
            if expected_msg not in error_msg:
                # If FPRIME_UPDATE_REF is set, update the expected file
                if os.environ.get("FPRIME_UPDATE_REF"):
                    expected_error.write_text(error_msg)
                    self.skipTest(f"Updated expected error file: {expected_error}")

                # Generate a unified diff for better visualization
                diff = difflib.unified_diff(
                    expected_msg.splitlines(keepends=True),
                    error_msg.splitlines(keepends=True),
                    fromfile="expected",
                    tofile="actual",
                    lineterm=""
                )
                diff_text = "".join(diff)
                self.fail(
                    f"Expected error message not found in actual error.\n\n"
                    f"Diff (expected vs actual):\n{diff_text}"
                )

        finally:
            # Clean up temporary file if created
            if output_file.exists():
                output_file.unlink()

    def _normalize_error_message(self, error_msg: str, input_file: Path) -> str:
        """
        Normalize error messages by replacing absolute paths with placeholders.

        This makes error messages reproducible across different machines.
        """
        # Find the fprime-gds root by looking for directory containing 'src' and 'test'
        current = input_file.absolute()
        while current.parent != current:
            if (current / 'src').is_dir() and (current / 'test').is_dir():
                abs_gds_root = str(current)
                # Replace absolute paths with <fprime-gds> placeholder
                error_msg = error_msg.replace(abs_gds_root, "<fprime-gds>")
                break
            current = current.parent

        return error_msg

    def test_bad_command(self):
        """Test error when command doesn't exist in dictionary."""
        self.generate_and_check_error(
            "simple_bad_sequence.seq",
            "simple_bad_sequence_error.txt"
        )

    def test_invalid_time_format(self):
        """Test error on invalid time format."""
        self.generate_and_check_error(
            "invalid_time_format.seq",
            "invalid_time_format_error.txt"
        )

    def test_invalid_missing_command(self):
        """Test error when command mnemonic is missing."""
        self.generate_and_check_error(
            "invalid_missing_command.seq",
            "invalid_missing_command_error.txt"
        )

    def test_invalid_time_descriptor(self):
        """Test error on invalid time descriptor (not R or A)."""
        self.generate_and_check_error(
            "invalid_time_descriptor.seq",
            "invalid_time_descriptor_error.txt"
        )

    def test_multiple_errors_with_cont(self):
        """Test cont=True mode that accumulates multiple errors."""
        input_file = self.input_dir / "multiple_errors.seq"

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            output_file = Path(tmp.name)

        try:
            # Should raise an exception with multiple error messages
            with self.assertRaises(Exception) as ctx:
                seqgen.generateSequence(
                    str(input_file),
                    str(output_file),
                    str(self.dictionary),
                    self.timebase,
                    cont=True
                )

            error_msg = str(ctx.exception)
            # Should contain multiple error mentions
            self.assertIn("Encountered syntax error", error_msg)

        finally:
            if output_file.exists():
                output_file.unlink()

    def test_invalid_array_unclosed(self):
        """Test error on unclosed array bracket."""
        self.generate_and_check_error(
            "invalid_array_unclosed.seq",
            "invalid_array_unclosed_error.txt"
        )

    def test_invalid_array_missing_comma(self):
        """Test error on missing comma in array."""
        self.generate_and_check_error(
            "invalid_array_missing_comma.seq",
            "invalid_array_missing_comma_error.txt"
        )

    def test_invalid_object_unclosed(self):
        """Test error on unclosed object brace."""
        self.generate_and_check_error(
            "invalid_object_unclosed.seq",
            "invalid_object_unclosed_error.txt"
        )

    def test_invalid_object_missing_colon(self):
        """Test error on missing colon in object."""
        self.generate_and_check_error(
            "invalid_object_missing_colon.seq",
            "invalid_object_missing_colon_error.txt"
        )


class TestArrayObjectValidationErrors(unittest.TestCase):
    """Test validation errors for array and object arguments."""

    @classmethod
    def setUpClass(cls):
        """Set up test paths with enhanced dictionary for validation."""
        cls.test_dir = Path(__file__).parent
        cls.input_dir = cls.test_dir / "input"
        cls.expected_dir = cls.test_dir / "expected"
        cls.resources_dir = cls.test_dir / "resources"
        cls.dictionary = cls.resources_dir / "enhanced_dictionary.json"
        cls.timebase = 0xFFFF

    def generate_and_check_error(self, seq_filename, expected_error_filename):
        """
        Try to generate sequence and verify error message matches expected.

        @param seq_filename: Input .seq file
        @param expected_error_filename: Expected error message .txt file
        """
        input_file = self.input_dir / seq_filename
        expected_error = self.expected_dir / expected_error_filename

        # Generate binary in temporary location
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            output_file = Path(tmp.name)

        try:
            # Should raise an exception
            with self.assertRaises(Exception) as ctx:
                seqgen.generateSequence(
                    str(input_file),
                    str(output_file),
                    str(self.dictionary),
                    self.timebase
                )

            # Get the error message and normalize paths for reproducibility
            error_msg = str(ctx.exception)
            error_msg = self._normalize_error_message(error_msg, input_file)

            # Check if expected error file exists
            if not expected_error.exists():
                # Create expected error file for first run
                expected_error.parent.mkdir(parents=True, exist_ok=True)
                expected_error.write_text(error_msg)
                self.skipTest(f"Created expected error file: {expected_error}")

            # Read expected error
            expected_msg = expected_error.read_text().strip()

            # Check that expected error substring is in actual error
            if expected_msg not in error_msg:
                # If FPRIME_UPDATE_REF is set, update the expected file
                if os.environ.get("FPRIME_UPDATE_REF"):
                    expected_error.write_text(error_msg)
                    self.skipTest(f"Updated expected error file: {expected_error}")

                # Generate a unified diff for better visualization
                diff = difflib.unified_diff(
                    expected_msg.splitlines(keepends=True),
                    error_msg.splitlines(keepends=True),
                    fromfile="expected",
                    tofile="actual",
                    lineterm=""
                )
                diff_text = "".join(diff)
                self.fail(
                    f"Expected error message not found in actual error.\n\n"
                    f"Diff (expected vs actual):\n{diff_text}"
                )

        finally:
            # Clean up temporary file if created
            if output_file.exists():
                output_file.unlink()

    def _normalize_error_message(self, error_msg: str, input_file: Path) -> str:
        """
        Normalize error messages by replacing absolute paths with placeholders.

        This makes error messages reproducible across different machines.
        """
        # Find the fprime-gds root by looking for directory containing 'src' and 'test'
        current = input_file.absolute()
        while current.parent != current:
            if (current / 'src').is_dir() and (current / 'test').is_dir():
                abs_gds_root = str(current)
                # Replace absolute paths with <fprime-gds> placeholder
                error_msg = error_msg.replace(abs_gds_root, "<fprime-gds>")
                break
            current = current.parent

        return error_msg

    def test_invalid_array_wrong_length(self):
        """Test error on array with wrong length."""
        self.generate_and_check_error(
            "invalid_array_wrong_length.seq",
            "invalid_array_wrong_length_error.txt"
        )

    def test_invalid_object_missing_field(self):
        """Test error on object missing required field."""
        self.generate_and_check_error(
            "invalid_object_missing_field.seq",
            "invalid_object_missing_field_error.txt"
        )

    def test_invalid_object_extra_field(self):
        """Test error on object with extra field."""
        self.generate_and_check_error(
            "invalid_object_extra_field.seq",
            "invalid_object_extra_field_error.txt"
        )

    def test_invalid_bool_bad_value(self):
        """Test error on boolean with invalid value."""
        self.generate_and_check_error(
            "invalid_bool_bad_value.seq",
            "invalid_bool_bad_value_error.txt"
        )

    def test_invalid_int_not_number(self):
        """Test error on integer with non-numeric value."""
        self.generate_and_check_error(
            "invalid_int_not_number.seq",
            "invalid_int_not_number_error.txt"
        )

    def test_invalid_float_not_number(self):
        """Test error on float with non-numeric value."""
        self.generate_and_check_error(
            "invalid_float_not_number.seq",
            "invalid_float_not_number_error.txt"
        )

    def test_invalid_hex_bad_format(self):
        """Test error on hex with invalid format."""
        self.generate_and_check_error(
            "invalid_hex_bad_format.seq",
            "invalid_hex_bad_format_error.txt"
        )

    def test_invalid_enum_bad_value(self):
        """Test error on enum with invalid value."""
        self.generate_and_check_error(
            "invalid_enum_bad_value.seq",
            "invalid_enum_bad_value_error.txt"
        )


if __name__ == "__main__":
    unittest.main()
