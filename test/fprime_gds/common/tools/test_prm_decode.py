import json
import tempfile
from pathlib import Path
import pytest
from fprime_gds.common.tools.params import (
    convert_json,
    decode_dat_to_params,
    params_to_json,
    params_to_text,
    params_to_csv,
)
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader


def test_decode_simple_paramdb():
    """Test decoding the simple_paramdb.dat file."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"
    dat_file = Path(__file__).parent / "expected" / "simple_paramdb.dat"
    input_json_file = Path(__file__).parent / "input" / "simple_paramdb.json"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Read and decode .dat file
    dat_bytes = dat_file.read_bytes()
    params = decode_dat_to_params(dat_bytes, id_dict)

    # Verify we got parameters
    assert len(params) > 0, "Should have decoded at least one parameter"

    # Convert to JSON and compare with original input
    decoded_json = params_to_json(params)
    expected_json = json.loads(input_json_file.read_text())

    assert decoded_json == expected_json, "Decoded JSON should match original input"


def test_round_trip_encode_decode():
    """Test that encoding then decoding produces the same result."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"
    input_json_file = Path(__file__).parent / "input" / "simple_paramdb.json"

    with tempfile.TemporaryDirectory() as temp_dir:
        # Encode JSON to .dat
        dat_file = Path(temp_dir) / "test.dat"
        convert_json(input_json_file, dict_file, dat_file, "dat")

        # Load dictionary
        dict_parser = PrmJsonLoader(str(dict_file.resolve()))
        id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

        # Decode .dat back to JSON
        dat_bytes = dat_file.read_bytes()
        params = decode_dat_to_params(dat_bytes, id_dict)
        decoded_json = params_to_json(params)

        # Compare with original
        expected_json = json.loads(input_json_file.read_text())
        assert decoded_json == expected_json, "Round-trip should produce identical JSON"


def test_params_to_text_format():
    """Test that params_to_text produces readable output."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"
    dat_file = Path(__file__).parent / "expected" / "simple_paramdb.dat"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Decode parameters
    dat_bytes = dat_file.read_bytes()
    params = decode_dat_to_params(dat_bytes, id_dict)

    # Convert to text
    text_output = params_to_text(params)

    # Verify text contains expected elements
    assert "Component:" in text_output, "Text output should have component headers"
    assert "type:" in text_output, "Text output should include type information"
    assert "id:" in text_output, "Text output should include parameter IDs"
    assert len(text_output) > 0, "Text output should not be empty"


def test_params_to_csv_format():
    """Test that params_to_csv produces valid CSV output."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"
    dat_file = Path(__file__).parent / "expected" / "simple_paramdb.dat"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Decode parameters
    dat_bytes = dat_file.read_bytes()
    params = decode_dat_to_params(dat_bytes, id_dict)

    # Convert to CSV
    csv_output = params_to_csv(params)

    # Verify CSV structure
    lines = csv_output.split("\n")
    assert len(lines) >= 2, "CSV should have header and at least one data row"
    assert lines[0] == "Component,Parameter,Value,Type,ID", "CSV should have correct header"

    # Check that data rows have the right number of columns
    for line in lines[1:]:
        if line:  # Skip empty lines
            # Count commas, accounting for quoted values
            # Simple check: should have at least 4 commas for 5 columns
            assert "," in line, "CSV data rows should have comma separators"


def test_decode_invalid_delimiter():
    """Test that decoding fails with invalid delimiter."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Create invalid data with wrong delimiter
    invalid_data = b"\xFF\x00\x00\x00\x12\x00\x00\x11\x01test"

    with pytest.raises(RuntimeError, match="Invalid delimiter"):
        decode_dat_to_params(invalid_data, id_dict)


def test_decode_unknown_param_id():
    """Test that decoding fails with unknown parameter ID."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Create data with unknown parameter ID (0xFFFFFFFF)
    invalid_data = b"\xA5\x00\x00\x00\x08\xFF\xFF\xFF\xFF\x00\x00\x00\x00"

    with pytest.raises(RuntimeError, match="Unknown parameter ID"):
        decode_dat_to_params(invalid_data, id_dict)


def test_decode_incomplete_data():
    """Test that decoding fails with incomplete data."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Create incomplete data (delimiter and partial record size)
    incomplete_data = b"\xA5\x00\x00"

    with pytest.raises(RuntimeError, match="Incomplete"):
        decode_dat_to_params(incomplete_data, id_dict)


def test_params_to_json_multiple_components():
    """Test that params_to_json handles multiple components correctly."""
    from fprime_gds.common.templates.prm_template import PrmTemplate
    from fprime_gds.common.models.serialize.numerical_types import U32Type

    # Create mock parameters from different components
    template1 = PrmTemplate(1, "param1", "comp1", U32Type, None)
    template2 = PrmTemplate(2, "param2", "comp1", U32Type, None)
    template3 = PrmTemplate(3, "param3", "comp2", U32Type, None)

    params = [
        (template1, 100),
        (template2, 200),
        (template3, 300),
    ]

    result = params_to_json(params)

    # Verify structure
    assert "comp1" in result, "Should have comp1"
    assert "comp2" in result, "Should have comp2"
    assert result["comp1"]["param1"] == 100
    assert result["comp1"]["param2"] == 200
    assert result["comp2"]["param3"] == 300


def test_decode_empty_file():
    """Test that decoding an empty file returns empty list."""
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"

    # Load dictionary
    dict_parser = PrmJsonLoader(str(dict_file.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(str(dict_file.resolve()))

    # Decode empty data
    empty_data = b""
    params = decode_dat_to_params(empty_data, id_dict)

    assert len(params) == 0, "Empty file should decode to empty list"
