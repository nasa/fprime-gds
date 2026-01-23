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
import os
import sys
from typing import Dict, List, Any, Optional

from fprime_gds.common.dp.common import (
    ChecksumConfig,
    calculate_crc32,
    get_dp_header_type,
)
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.utils.config_manager import ConfigManager


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


class TypeResolutionError(DataProductError):
    """Raised when unable to resolve a type from ConfigManager."""
    
    def __init__(self, type_name: str, reason: str = ""):
        self.type_name = type_name
        super().__init__(f"Cannot resolve type '{type_name}': {reason}")


# ==============================================================================
# Data Product Parser (ConfigManager-based)
# ==============================================================================

class DataProductParser:
    """Parser for F Prime Data Product binary files using ConfigManager.
    
    This parser reads binary data product files and converts them to JSON format.
    It uses ConfigManager to query type information instead of parsing JSON
    dictionaries directly.
    
    Data Product Structure:
    1. Header (variable size based on configuration)
       - PacketDescriptor
       - Id
       - Priority  
       - TimeTag (seconds + microseconds)
       - ProcTypes
       - UserData
       - DpState
       - DataSize
       - HeaderHash (CRC32)
    
    2. Data Records (repeated until DataSize bytes consumed)
       - RecordId
       - Record data (type depends on record definition)
    
    3. Data Hash (CRC32 of all record data)
    
    Assumptions:
    - ConfigManager is already loaded with dictionary information
    - Data product record definitions are available via ConfigManager
      (This may require future work to add DP-specific dictionary loading)
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
            TypeResolutionError: If unable to resolve header field types
        """
        header = get_dp_header_type()()
        header_bin_data = file_handle.read(header.getMaxSize())
        header.deserialize(header_bin_data, 0)

        # Compute hash on header (from beginning until we hit the checksum)
        computed_hash = calculate_crc32(header_bin_data[:-ChecksumConfig.CHECKSUM_LEN])

        # Validate hash
        if header.to_jsonable()["Checksum"]["value"] != computed_hash:
            raise CRCError("Header", header['HeaderHash'], computed_hash)

        return header
    
    def parse_record(self, file_handle, record_id: int) -> Dict[str, Any]:
        """Parse a single data record.
        
        Args:
            file_handle: file handle for binary dp - assuming it is positioned at beginning of data
            record_id: ID of the record to parse
            
        Returns:
            Dictionary containing record data
            
        Raises:
            RecordNotFoundError: If record ID not found
            TypeResolutionError: If unable to resolve record type
            
        Note:
            Data product record definitions are now loaded into ConfigManager via
            dp_json_loader.py. Use ConfigManager().get_dp_record_by_id(record_id)
            to retrieve record metadata.
        """
        record = {'RecordId': record_id}
        
        # Query ConfigManager for record definition
        record_template = self.dictionaries.dp_record_id.get(record_id)
        
        if record_template is None:
            raise RecordNotFoundError(record_id)
        
        # Get the record type
        record_type = record_template.get_type()
        
        # Parse based on whether it's an array or scalar
        if record_template.is_array():
            # For array records, read the array size first
            array_size_type = ConfigManager().get_type("FwSizeStoreType")() # TODO: verify this is correct
            array_size_data = file_handle.read(array_size_type.getSize())
            array_size_type.deserialize(array_size_data, 0)
            array_size = array_size_type.val
            
            record['Size'] = array_size
            record['Data'] = []
            
            # Read each array element
            for _ in range(array_size):
                element_instance = record_type()
                element_data = file_handle.read(element_instance.getSize())
                element_instance.deserialize(element_data, 0)
                record['Data'].append(element_instance.to_jsonable())
        else:
            # For scalar records, read the single value
            type_instance = record_type()
            type_data = file_handle.read(type_instance.getSize())
            type_instance.deserialize(type_data, 0)
            record['Data'] = type_instance.to_jsonable()
        
        return record
    
    def parse_type(self, reader, type_name: str) -> Any:
        """Parse a value of the given type.
        
        Args:
            reader: BinaryReader instance
            type_name: Name of the type to parse
            
        Returns:
            Parsed value (type depends on type_name)
            
        Raises:
            TypeResolutionError: If unable to resolve type
            
        Note:
            This is a placeholder for complex type parsing.
            Full implementation requires type metadata in ConfigManager.
        """
        try:
            type_class = ConfigManager().get_type(type_name)
            type_instance = type_class()
            
            field_size = type_instance.getSize()
            field_data = reader.read_bytes(field_size)
            
            type_instance.deserialize(field_data, 0)
            return type_instance.val
            
        except KeyError as e:
            raise TypeResolutionError(type_name, f"Type not found: {e}")
        except Exception as e:
            raise TypeResolutionError(type_name, f"Error parsing: {e}")
    
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
            # Parse header
            header_obj = self.parse_header(f)
            header_json = header_obj.to_jsonable()
            results["Header"] = header_json

            # Get total data size from header
            data_size = header_json['DataSize']["value"]

            # Parse records until we've read all data
            position_at_start = f.tell()

            while (f.tell() - position_at_start) < data_size:
                # Read record ID
                record_id_bin = f.read(ConfigManager().get_type("FwDpIdType").getSize())
                record_id_obj = ConfigManager().get_type("FwDpIdType")()
                record_id_obj.deserialize(record_id_bin, 0)
                record_id = record_id_obj.val

                # Parse the record
                try:
                    record = self.parse_record(f, record_id)
                    results["Records"].append(record)
                except NotImplementedError:
                    # For now, break if record parsing not implemented
                    print(
                        "Warning: Record parsing not yet implemented. "
                        "Stopping after header.",
                        file=sys.stderr
                    )
                    break
            
            # # Validate data checksum
            # computed_data_hash = reader.get_crc()
            # data_hash = reader.read_integer('U32')
            
            # if data_hash != computed_data_hash:
            #     raise CRCError("Data", data_hash, computed_data_hash)
            
            # # Store data hash in header for reference
            # header['DataHash'] = data_hash
        # print(f"Results: {results}")
        return results
    
    def write_json(self, data: Dict[str, Any]):
        """Write parsed data to JSON file.
        
        Args:
            data: Dictionary of parsed data to write
        """
        pass
        # # Determine output path
        # if self.output_json_path is None:
        #     base_name = os.path.basename(self.binary_file_path)
        #     self.output_json_path = os.path.splitext(base_name)[0] + '.json'
        
        # # Handle macOS hidden file prefix
        # if self.output_json_path.startswith('._'):
        #     self.output_json_path = self.output_json_path.replace('._', '')
        
        # # Write JSON
        # with open(self.output_json_path, 'w') as f:
        #     json.dump(data, f, indent=2, default=str)  # default=str handles bytes
        
        # print(f'Output written to {self.output_json_path}')
    
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

