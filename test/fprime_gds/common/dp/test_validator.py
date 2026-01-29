"""
Tests for DataProductValidator

Tests the validation of F Prime Data Product files using various methods:
- Dictionary-based validation
- Explicit header size validation
- Guess-based validation
- Invalid file handling

@Created on January 22, 2026
"""

import pytest
from pathlib import Path

from fprime_gds.common.dp.validator import DataProductValidator
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.utils.cleanup import globals_cleanup


# Path to test data directory
TEST_DATA_DIR = Path(__file__).parent / "test_dp_data"
DICTIONARY_PATH = TEST_DATA_DIR / "dictionary.json"

# In the test binaries, header size is 63 (default F´ config)
TEST_HEADER_SIZE = 63


@pytest.fixture
def load_dictionary():
    """Fixture to load the test dictionary into ConfigManager before tests.
    Also uses the globals_cleanup utility to reset global state and not interfere 
    with other tests."""
    globals_cleanup()
    Dictionaries.load_dictionaries_into_config(str(DICTIONARY_PATH))
    yield
    globals_cleanup()



class TestDataProductValidatorWithDictionary:
    """Test validation using F Prime dictionary to derive header size."""
    
    def test_validate_makeBool_with_dict(self, load_dictionary):
        """Test validation of makeBool.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        assert result is True
    
    def test_validate_makeU32_with_dict(self, load_dictionary):
        """Test validation of makeU32.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeU32.bin"))
        assert result is True
    
    def test_validate_makeI8_with_dict(self, load_dictionary):
        """Test validation of makeI8.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeI8.bin"))
        assert result is True
    
    def test_validate_makeI16_with_dict(self, load_dictionary):
        """Test validation of makeI16.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeI16.bin"))
        assert result is True
    
    def test_validate_makeI32_with_dict(self, load_dictionary):
        """Test validation of makeI32.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeI32.bin"))
        assert result is True
    
    def test_validate_makeI64_with_dict(self, load_dictionary):
        """Test validation of makeI64.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeI64.bin"))
        assert result is True
    
    def test_validate_makeF32_with_dict(self, load_dictionary):
        """Test validation of makeF32.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeF32.bin"))
        assert result is True
    
    def test_validate_makeF64_with_dict(self, load_dictionary):
        """Test validation of makeF64.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeF64.bin"))
        assert result is True
    
    def test_validate_makeEnum_with_dict(self, load_dictionary):
        """Test validation of makeEnum.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeEnum.bin"))
        assert result is True
    
    def test_validate_makeU8Array_with_dict(self, load_dictionary):
        """Test validation of makeU8Array.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeU8Array.bin"))
        assert result is True
    
    def test_validate_makeU32Array_with_dict(self, load_dictionary):
        """Test validation of makeU32Array.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeU32Array.bin"))
        assert result is True
    
    def test_validate_makeDataArray_with_dict(self, load_dictionary):
        """Test validation of makeDataArray.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeDataArray.bin"))
        assert result is True
    
    def test_validate_makeFppArray_with_dict(self, load_dictionary):
        """Test validation of makeFppArray.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeFppArray.bin"))
        assert result is True
    
    def test_validate_makeComplex_with_dict(self, load_dictionary):
        """Test validation of makeComplex.bin using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "makeComplex.bin"))
        assert result is True
    
    def test_validate_with_dict_verbose(self, load_dictionary, capsys):
        """Test validation with verbose output enabled."""
        validator = DataProductValidator(
            dictionary=str(DICTIONARY_PATH),
            verbose=True
        )
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        assert result is True
        
        captured = capsys.readouterr()
        assert "Calculated a header size of" in captured.out
        assert "Validation OK!" in captured.out


class TestDataProductValidatorWithHeaderSize:
    """Test validation using explicit header size."""
    
    def test_validate_with_correct_header_size(self, load_dictionary):
        """Test validation with correct explicit header size."""
        # Header size for the test data is TEST_HEADER_SIZE bytes
        validator = DataProductValidator(header_size=TEST_HEADER_SIZE)
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        assert result is True
    
    def test_validate_with_incorrect_header_size(self, load_dictionary):
        """Test validation with incorrect header size."""
        validator = DataProductValidator(header_size=TEST_HEADER_SIZE + 3)
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        assert result is False
    
    def test_validate_multiple_files_with_header_size(self, load_dictionary):
        """Test validation of multiple files with same header size."""
        validator = DataProductValidator(header_size=TEST_HEADER_SIZE)
        
        test_files = [
            "makeBool.bin",
            "makeU32.bin",
            "makeI8.bin",
            "makeF32.bin"
        ]
        
        for test_file in test_files:
            result = validator.process(str(TEST_DATA_DIR / test_file))
            assert result is True, f"Failed to validate {test_file}"


class TestDataProductValidatorWithGuess:
    """Test validation using header size guessing."""
    
    def test_validate_with_guess(self, load_dictionary):
        """Test validation with header size guessing."""
        validator = DataProductValidator(guess_size=True)
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        assert result is True
    
    def test_validate_with_guess_verbose(self, load_dictionary, capsys):
        """Test validation with guessing and verbose output."""
        validator = DataProductValidator(guess_size=True, verbose=True)
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        assert result is True
        
        captured = capsys.readouterr()
        assert "Valid checksum found with" in captured.out
    
    def test_validate_multiple_files_with_guess(self, load_dictionary):
        """Test validation of multiple files using guessing."""
        validator = DataProductValidator(guess_size=True)
        
        test_files = [
            "makeBool.bin",
            "makeComplex.bin",
            "makeDataArray.bin",
            "makeEnum.bin",
            "makeF32.bin",
            "makeF64.bin",
            "makeFppArray.bin",
            "makeI16.bin",
            "makeI32.bin",
            "makeI64.bin",
            "makeI8.bin",
            "makeU32.bin",
            "makeU32Array.bin",
            "makeU8Array.bin"
        ]
        
        for test_file in test_files:
            result = validator.process(str(TEST_DATA_DIR / test_file))
            assert result is True, f"Failed to validate {test_file}"


class TestDataProductValidatorErrorCases:
    """Test error handling and edge cases."""
    
    def test_validate_nonexistent_file(self):
        """Test validation of non-existent file."""
        validator = DataProductValidator(guess_size=True)
        
        with pytest.raises(Exception):
            validator.process("/nonexistent/file.bin")
    
    def test_validate_file_too_small(self, tmp_path):
        """Test validation of file that is too small."""
        # Create a file that is smaller than minimum size
        small_file = tmp_path / "too_small.bin"
        small_file.write_bytes(b"x" * 10)
        
        validator = DataProductValidator(guess_size=True)
        result = validator.process(str(small_file))
        assert result is False
    
    def test_validate_corrupted_file(self, load_dictionary):
        """Test validation of corrupted data product file."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result = validator.process(str(TEST_DATA_DIR / "CRC_FAILURE_EXPECTED.bin"))
        assert result is False
    
    def test_validate_with_no_validation_method(self):
        """Test that validator requires at least one validation method."""
        # This should use guess by default since no method is specified
        validator = DataProductValidator()
        result = validator.process(str(TEST_DATA_DIR / "makeBool.bin"))
        # Should succeed with guessing
        assert result is True


class TestDataProductValidatorOptions:
    """Test validator initialization and configuration."""
    
    def test_init_with_dictionary(self):
        """Test initialization with dictionary path."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        assert validator.dictionary == str(DICTIONARY_PATH)
        assert validator.header_size is None
        assert validator.guess_size is False
        assert validator.verbose is False
    
    def test_init_with_header_size(self):
        """Test initialization with explicit header size."""
        validator = DataProductValidator(header_size=67)
        assert validator.dictionary is None
        assert validator.header_size == 67
        assert validator.guess_size is False
    
    def test_init_with_guess(self):
        """Test initialization with guess mode."""
        validator = DataProductValidator(guess_size=True)
        assert validator.dictionary is None
        assert validator.header_size is None
        assert validator.guess_size is True
    
    def test_init_with_verbose(self):
        """Test initialization with verbose mode."""
        validator = DataProductValidator(verbose=True)
        assert validator.verbose is True

class TestDataProductValidatorIntegration:
    """Integration tests combining multiple validation methods."""
    
    def test_validate_same_file_different_methods(self, load_dictionary):
        """Test that different validation methods produce same result."""
        test_file = str(TEST_DATA_DIR / "makeBool.bin")
        
        # Validate with dictionary
        validator_dict = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result_dict = validator_dict.process(test_file)
        
        # Validate with explicit size
        validator_size = DataProductValidator(header_size=TEST_HEADER_SIZE)
        result_size = validator_size.process(test_file)
        
        # Validate with guessing
        validator_guess = DataProductValidator(guess_size=True)
        result_guess = validator_guess.process(test_file)
        
        assert result_dict is True
        assert result_size is True
        assert result_guess is True
    
    def test_validate_all_test_files_with_dict(self, load_dictionary):
        """Test validation of all valid test files using dictionary."""
        validator = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        
        valid_files = [
            "makeBool.bin",
            "makeComplex.bin",
            "makeDataArray.bin",
            "makeEnum.bin",
            "makeF32.bin",
            "makeF64.bin",
            "makeFppArray.bin",
            "makeI16.bin",
            "makeI32.bin",
            "makeI64.bin",
            "makeI8.bin",
            "makeU32.bin",
            "makeU32Array.bin",
            "makeU8Array.bin"
        ]
        
        for test_file in valid_files:
            file_path = TEST_DATA_DIR / test_file
            if file_path.exists():
                result = validator.process(str(file_path))
                assert result is True, f"Failed to validate {test_file}"

    def test_failure_expected(self, load_dictionary):
        """Test that a corrupted data product fails validation."""
        test_file = str(TEST_DATA_DIR / "CRC_FAILURE_EXPECTED.bin")
        
        # Validate with dictionary
        validator_dict = DataProductValidator(dictionary=str(DICTIONARY_PATH))
        result_dict = validator_dict.process(test_file)
        
        # Validate with explicit size
        validator_size = DataProductValidator(header_size=TEST_HEADER_SIZE)
        result_size = validator_size.process(test_file)
        
        # Validate with guessing
        validator_guess = DataProductValidator(guess_size=True)
        result_guess = validator_guess.process(test_file)
        
        assert result_dict is False
        assert result_size is False
        assert result_guess is False

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
