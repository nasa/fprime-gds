"""
Data Product Parser using ConfigManager

This module provides a ConfigManager-based parser for F Prime Data Product files.
Unlike the original parser.py which uses Pydantic models and JSON parsing,
this implementation queries type information directly from ConfigManager.

Key differences from parser.py:
- Uses ConfigManager.get_type() and get_constant() instead of Pydantic models
- No JSON dictionary parsing - assumes ConfigManager is already loaded
- Simplified type resolution through ConfigManager

@author: Thomas Boyer-Chammard
@date: January 2026
"""

import json
import sys
from typing import Dict, List, Any, Optional

from fprime_gds.common.dp.common import (
    ChecksumConfig,
    calculate_crc32,
    get_dp_header_type,
)
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.templates.dp_record_template import DpRecordTemplate
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.serializable_type import SerializableType
from fprime_gds.common.models.serialize.array_type import ArrayType

# ==============================================================================
# Custom Exceptions
# ==============================================================================

class DataProductError(Exception):
    """Base exception for data product parsing errors."""
    pass


class CRCError(DataProductError):
    """Raised when CRC checksum validation fails."""
    
    def __init__(self, section: str, expected: int, calculated: int):
        self.section = section
        self.expected = expected
        self.calculated = calculated
        super().__init__(
            f"CRC mismatch in {section}: expected {expected:#x}, got {calculated:#x}"
        )


class RecordNotFoundError(DataProductError):
    """Raised when a record ID is not found in the dictionary."""
    
    def __init__(self, record_id: int):
        self.record_id = record_id
        super().__init__(f"Record ID {record_id} not found in dictionary")

# ==============================================================================
# Data Product Parser (ConfigManager-based)
# ==============================================================================

class DataProductParser:
    """Parser for F Prime Data Product binary files.
    
    This parser reads binary data product files and converts them to human-readable format.

    This currently only supports a JSON representation of the data product.
    
    Data Product Structure:
    1. Header (variable size based on configuration)
       - See common.py: get_dp_header_type()
    
    2. Data Records (repeated until DataSize bytes consumed)
       - RecordId
       - Record data (type depends on record definition)

    3. Data Hash (CRC32 of all record data)
    
    Assumptions:
        - ConfigManager is already loaded with dictionary information
        - dictionaries property (see constructor) is loaded with data product dictionary info
        - both these assumptions can be resolved by using the DictionaryParser (see executables/data_products.py)
    """
    
    def __init__(self, dictionaries: Dictionaries, binary_file_path: str, output_json_path: Optional[str] = None):
        """Initialize the parser.
        
        Args:
            dictionaries: Dictionaries object containing dictionary information
            binary_file_path: Path to the binary data product file (.fdp)
            output_json_path: Optional path for output JSON file
                            (defaults to <binary_file>.json)
        """
        self.dictionaries = dictionaries
        self.binary_file_path = binary_file_path
        self.output_json_path = output_json_path
        
    def parse_header(self, file_handle) -> Dict[str, Any]:
        """Parse the data product header.
        
        Args:
            file_handle: file handle to the data product binary
            
        Returns:
            Dictionary containing header fields

        Raises:
            CRCError: If header checksum validation fails
        """
        header = get_dp_header_type()()
        max_header_size = header.getMaxSize()
        header_bin_data = file_handle.read(max_header_size)
        header.deserialize(header_bin_data, 0)
        
        # Get actual header size and adjust file position
        actual_header_size = header.getSize()
        if actual_header_size < max_header_size:
            # Seek back to correct position (we read too much)
            file_handle.seek(file_handle.tell() - (max_header_size - actual_header_size))

        # Compute hash on header (from beginning until we hit the checksum)
        computed_hash = calculate_crc32(header_bin_data[:actual_header_size - ChecksumConfig.CHECKSUM_LEN])

        # Validate hash
        if header.to_jsonable()["Checksum"]["value"] != computed_hash:
            raise CRCError("Header", header['HeaderHash'], computed_hash)

        return header
    
    def parse_record(self, file_handle, record_id: int) -> Dict[str, Any]:
        """Parse a single data record. file_handle is expected to be positioned at beginning of data
        and will be moved to end of data after parsing.

        Note: Dp records are retrieved through the dictionaries member, which is expected to have been
        loaded with dictionary information.
        
        Args:
            file_handle: file handle for binary dp - assuming it is positioned at beginning of data
            record_id: ID of the record to parse
            
        Returns:
            Dictionary containing record data
            
        Raises:
            RecordNotFoundError: If record ID not found
        """
        record = {'RecordId': record_id}
        
        # Query ConfigManager for record definition
        record_template: DpRecordTemplate = self.dictionaries.dp_record_id.get(record_id)

        if record_template is None:
            raise RecordNotFoundError(record_id)
        
        # Get the record type
        record_type = record_template.get_type()
        
        def read_element(element_type):
            """Read a single element from file, handling variable-length types.
            
            Variable-length types (strings, structs with strings, arrays) require special handling:
            1. Read getMaxSize() bytes into a buffer
            2. Deserialize from the buffer (handles nested variable-length members)
            3. Get actual bytes consumed via getSize()
            4. Seek to correct absolute position
            
            This avoids cumulative position errors from relative seeking.
            """

            element_instance = element_type()
            
            # For types that may have variable length, read max size and adjust
            if issubclass(element_type, (StringType, SerializableType, ArrayType)):
                start_pos = file_handle.tell()
                max_size = element_instance.getMaxSize()
                buffer = file_handle.read(max_size)
                
                # Deserialize from buffer
                element_instance.deserialize(buffer, 0)
                
                # Get actual size consumed
                actual_size = element_instance.getSize()
                
                # Seek to correct position (start + actual_size)
                file_handle.seek(start_pos + actual_size)
            else:
                # For fixed-size types, just read the exact size
                element_data = file_handle.read(element_instance.getMaxSize())
                element_instance.deserialize(element_data, 0)
            
            return element_instance

        # Parse based on whether it's an array or scalar
        if record_template.is_array():
            # For array records, read the array size first
            array_size_type = ConfigManager().get_type("FwSizeStoreType")()
            array_size_data = file_handle.read(array_size_type.getSize())
            array_size_type.deserialize(array_size_data, 0)
            array_size = array_size_type.val

            record['Size'] = array_size
            record['Data'] = []

            # Read each array element
            for _ in range(array_size):
                element_instance = read_element(record_type)
                record['Data'].append(element_instance.to_jsonable())
        else:
            # For scalar records, read the single value
            element_instance = read_element(record_type)
            record['Data'] = element_instance.to_jsonable()
        
        return record

    def parse(self) -> List[Dict[str, Any]]:
        """Parse the entire data product file.
        
        Returns:
            List of dictionaries containing header and all records
            
        Raises:
            FileNotFoundError: If binary file doesn't exist
            CRCError: If checksum validation fails
            DataProductError: For other parsing errors
        """
        results = {"Header": None, "Records": []}
        
        with open(self.binary_file_path, 'rb') as f:
            ##################
            #  Parse header  #
            ##################
            header_obj = self.parse_header(f)
            header_json = header_obj.to_jsonable()
            results["Header"] = header_json

            #####################
            # Parse all records #
            #####################
            data_size = header_json['DataSize']["value"]
            position_at_start = f.tell()
            while (f.tell() - position_at_start) < data_size:
                # Read record ID
                record_id_bin = f.read(ConfigManager().get_type("FwDpIdType").getSize())
                record_id_obj = ConfigManager().get_type("FwDpIdType")()
                record_id_obj.deserialize(record_id_bin, 0)
                record_id = record_id_obj.val

                # Parse the record
                record = self.parse_record(f, record_id)
                results["Records"].append(record)

            #####################
            # Validate checksum #
            #####################
            #   1) Retrieve checksum in data product file
            assert f.tell() == position_at_start + data_size
            dp_crc_bin = f.read(ChecksumConfig.CHECKSUM_LEN)
            dp_crc = ChecksumConfig.CHECKSUM_TOKEN_TYPE()
            dp_crc.deserialize(dp_crc_bin, 0)
            #   2) Compute checksum of data
            f.seek(position_at_start)
            data_to_crc = f.read(data_size)
            computed_crc = calculate_crc32(data_to_crc)
            #   3) Compare computed and stored checksums
            if computed_crc != dp_crc.val:
                raise CRCError("Data", dp_crc.val, computed_crc)

        return results

    def process(self):
        """Main processing: parse binary file and write JSON output."""
        try:
            print(f"Parsing {self.binary_file_path}...")
            data = self.parse()
            with open(self.output_json_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            print("Parsing complete!")
            
        except DataProductError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            raise

