"""
Tests for DataProductDecoder

Tests the decoding of F Prime Data Product binary files into JSON format:
- Basic decoding of various data types (primitives, arrays, structs)
- Header decoding and validation
- Record decoding for scalar and array types
- CRC validation during decoding
- Error handling for corrupted files

@Created on January 27, 2026
"""

import pytest
import json
from pathlib import Path

from fprime_gds.common.dp.decoder import DataProductDecoder, CRCError, RecordNotFoundError
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.utils.cleanup import globals_cleanup


# Path to test data directory
TEST_DATA_DIR = Path(__file__).parent / "test_dp_data"
DICTIONARY_PATH = TEST_DATA_DIR / "dictionary.json"


@pytest.fixture
def load_dictionary():
    """Fixture to load the test dictionary into ConfigManager before tests.
    Also uses the globals_cleanup utility to reset global state and not interfere 
    with other tests."""
    globals_cleanup()
    dictionaries = Dictionaries.load_dictionaries_into_config(str(DICTIONARY_PATH))
    yield dictionaries
    globals_cleanup()


class TestDataProductDecoderBasicTypes:
    """Test decoding of basic primitive data types."""
    
    def test_decode_bool(self, load_dictionary, tmp_path):
        """Test decoding of boolean data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeBool.bin"),
            str(tmp_path / "makeBool.json")
        )
        result = decoder.decode()
        
        # Verify structure
        assert "Header" in result
        assert "Records" in result
        assert len(result["Records"]) > 0
        
        # Verify header has expected fields
        header = result["Header"]
        assert "Id" in header
        assert "DataSize" in header
        assert "Checksum" in header
    
    def test_decode_u32(self, load_dictionary, tmp_path):
        """Test decoding of U32 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeU32.bin"),
            str(tmp_path / "makeU32.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
        assert len(result["Records"]) > 0
    
    def test_decode_i8(self, load_dictionary, tmp_path):
        """Test decoding of I8 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeI8.bin"),
            str(tmp_path / "makeI8.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_i16(self, load_dictionary, tmp_path):
        """Test decoding of I16 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeI16.bin"),
            str(tmp_path / "makeI16.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_i32(self, load_dictionary, tmp_path):
        """Test decoding of I32 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeI32.bin"),
            str(tmp_path / "makeI32.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_i64(self, load_dictionary, tmp_path):
        """Test decoding of I64 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeI64.bin"),
            str(tmp_path / "makeI64.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_f32(self, load_dictionary, tmp_path):
        """Test decoding of F32 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeF32.bin"),
            str(tmp_path / "makeF32.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_f64(self, load_dictionary, tmp_path):
        """Test decoding of F64 data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeF64.bin"),
            str(tmp_path / "makeF64.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_enum(self, load_dictionary, tmp_path):
        """Test decoding of enum data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeEnum.bin"),
            str(tmp_path / "makeEnum.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result


class TestDataProductDecoderArrayTypes:
    """Test decoding of array data types."""
    
    def test_decode_u8_array(self, load_dictionary, tmp_path):
        """Test decoding of U8 array data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeU8Array.bin"),
            str(tmp_path / "makeU8Array.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
        assert len(result["Records"]) > 0
        
        # Array records should have a Size field
        record = result["Records"][0]
        assert "Size" in record
        assert "Data" in record
        assert isinstance(record["Data"], list)
    
    def test_decode_u32_array(self, load_dictionary, tmp_path):
        """Test decoding of U32 array data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeU32Array.bin"),
            str(tmp_path / "makeU32Array.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
        record = result["Records"][0]
        assert "Size" in record
        assert "Data" in record
        assert isinstance(record["Data"], list)
    
    def test_decode_data_array(self, load_dictionary, tmp_path):
        """Test decoding of Data array data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeDataArray.bin"),
            str(tmp_path / "makeDataArray.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
    
    def test_decode_fpp_array(self, load_dictionary, tmp_path):
        """Test decoding of FPP array data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeFppArray.bin"),
            str(tmp_path / "makeFppArray.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result


class TestDataProductDecoderComplexTypes:
    """Test decoding of complex/struct data types."""
    
    def test_decode_complex(self, load_dictionary, tmp_path):
        """Test decoding of complex struct data product."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeComplex.bin"),
            str(tmp_path / "makeComplex.json")
        )
        result = decoder.decode()
        
        assert "Header" in result
        assert "Records" in result
        assert len(result["Records"]) > 0


class TestDataProductDecoderProcessMethod:
    """Test the process() method that writes JSON output."""
    
    def test_process_writes_json_file(self, load_dictionary, tmp_path):
        """Test that process() writes a valid JSON file."""
        output_path = tmp_path / "output.json"
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeBool.bin"),
            str(output_path)
        )
        decoder.process()
        
        # Verify file was created
        assert output_path.exists()
        
        # Verify it's valid JSON
        with open(output_path, 'r') as f:
            data = json.load(f)
        
        assert "Header" in data
        assert "Records" in data
    
    def test_process_default_output_path(self, load_dictionary, tmp_path):
        """Test that process() uses default output path when not specified."""
        # Copy test file to tmp_path so we can test default naming
        import shutil
        test_bin = tmp_path / "test.bin"
        shutil.copy(TEST_DATA_DIR / "makeBool.bin", test_bin)
        
        decoder = DataProductDecoder(
            load_dictionary,
            str(test_bin)
        )
        decoder.process()
        
        # Default output should be test.json
        expected_output = tmp_path / "test.json"
        assert expected_output.exists()
        
        # Verify it's valid JSON
        with open(expected_output, 'r') as f:
            data = json.load(f)
        
        assert "Header" in data
        assert "Records" in data


class TestDataProductDecoderErrorHandling:
    """Test error handling and edge cases."""
    
    def test_decode_corrupted_file(self, load_dictionary, tmp_path):
        """Test decoding of corrupted data product file raises an error.
        
        Corrupted files may raise CRCError (if checksum fails) or 
        RecordNotFoundError (if record IDs are corrupted).
        """
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "CRC_FAILURE_EXPECTED.bin"),
            str(tmp_path / "corrupted.json")
        )
        
        # Corrupted file should raise some kind of error
        with pytest.raises((CRCError, RecordNotFoundError)):
            decoder.decode()

    def test_decode_corrupted_header(self, load_dictionary, tmp_path):
        """Test decoding of corrupted data product file raises an error.
        
        Corrupted files may raise CRCError (if checksum fails) or 
        RecordNotFoundError (if record IDs are corrupted).
        """
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "CRC_HEADER_FAILURE_EXPECTED.bin"),
            str(tmp_path / "corrupted.json")
        )

        # Corrupted file should raise some kind of error
        with pytest.raises((CRCError, RecordNotFoundError)):
            decoder.decode()

    def test_decode_nonexistent_file(self, load_dictionary, tmp_path):
        """Test decoding of non-existent file raises FileNotFoundError."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(tmp_path / "nonexistent.bin"),
            str(tmp_path / "output.json")
        )
        
        with pytest.raises(FileNotFoundError):
            decoder.decode()
    
    def test_decode_file_too_small(self, load_dictionary, tmp_path):
        """Test decoding of file that is too small."""
        # Create a file that is smaller than minimum size
        small_file = tmp_path / "too_small.bin"
        small_file.write_bytes(b"x" * 10)
        
        decoder = DataProductDecoder(
            load_dictionary,
            str(small_file),
            str(tmp_path / "output.json")
        )
        
        # Should raise some exception (likely struct.error or similar)
        with pytest.raises(Exception):
            decoder.decode()


class TestDataProductDecoderRecordDecoding:
    """Test specific record decoding functionality."""
    
    def test_decode_header(self, load_dictionary):
        """Test header decoding returns expected fields."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeBool.bin")
        )
        
        with open(TEST_DATA_DIR / "makeBool.bin", 'rb') as f:
            header = decoder.decode_header(f)
            header_json = header.to_jsonable()
        
        # Verify all expected header fields are present
        expected_fields = ["PacketDescriptor", "Id", "Priority", "Time", 
                          "ProcTypes", "UserData", "DpState", "DataSize", "Checksum"]
        for field in expected_fields:
            assert field in header_json, f"Missing header field: {field}"
    
    def test_decode_scalar_record(self, load_dictionary):
        """Test decoding of scalar (non-array) record."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeU32.bin")
        )
        result = decoder.decode()
        
        # Find a scalar record (should not have Size field)
        records = result["Records"]
        assert len(records) > 0
        
        record = records[0]
        assert "Record" in record
        assert "Data" in record
    
    def test_decode_array_record(self, load_dictionary):
        """Test decoding of array record."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeU8Array.bin")
        )
        result = decoder.decode()
        
        # Array records should have Size and Data fields
        records = result["Records"]
        assert len(records) > 0
        
        record = records[0]
        assert "Size" in record
        assert "Data" in record
        assert isinstance(record["Data"], list)
        assert len(record["Data"]) == record["Size"]


class TestDataProductDecoderIntegration:
    """Integration tests for complete decoding workflow."""
    
    def test_decode_all_test_files(self, load_dictionary, tmp_path):
        """Test decoding of all valid test files."""
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
                decoder = DataProductDecoder(
                    load_dictionary,
                    str(file_path),
                    str(tmp_path / f"{test_file}.json")
                )
                result = decoder.decode()
                
                # Basic validation
                assert "Header" in result, f"Failed to decode {test_file}: missing Header"
                assert "Records" in result, f"Failed to decode {test_file}: missing Records"
                assert len(result["Records"]) > 0, f"Failed to decode {test_file}: no records"
    
    def test_decode_and_verify_json_structure(self, load_dictionary, tmp_path):
        """Test that decoded JSON has consistent structure."""
        decoder = DataProductDecoder(
            load_dictionary,
            str(TEST_DATA_DIR / "makeComplex.bin"),
            str(tmp_path / "complex.json")
        )
        decoder.process()
        
        # Load and verify JSON structure
        with open(tmp_path / "complex.json", 'r') as f:
            data = json.load(f)
        
        # Verify top-level structure
        assert isinstance(data, dict)
        assert "Header" in data
        assert "Records" in data
        
        # Verify header structure
        assert isinstance(data["Header"], dict)
        
        # Verify records structure
        assert isinstance(data["Records"], list)
        for record in data["Records"]:
            assert isinstance(record, dict)
            assert "Record" in record
            assert "Data" in record


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
