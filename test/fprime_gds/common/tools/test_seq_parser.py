"""Regression tests for sequence file parsing and generation.

Tests the sequence compiler end-to-end by:
1. Generating .bin files from valid .seq files and comparing against expected .bin files
2. Capturing error messages from invalid .seq files and comparing against expected .txt files
"""

import filecmp
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

            # Get the error message
            error_msg = str(ctx.exception)

            # Check if expected error file exists
            if not expected_error.exists():
                # Create expected error file for first run
                expected_error.parent.mkdir(parents=True, exist_ok=True)
                expected_error.write_text(error_msg)
                self.skipTest(f"Created expected error file: {expected_error}")

            # Read expected error
            expected_msg = expected_error.read_text().strip()

            # Check that expected error substring is in actual error
            self.assertIn(
                expected_msg,
                error_msg,
                f"Expected error message to contain:\n  {expected_msg}\n"
                f"Actual error:\n  {error_msg}"
            )

        finally:
            # Clean up temporary file if created
            if output_file.exists():
                output_file.unlink()

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


if __name__ == "__main__":
    unittest.main()
