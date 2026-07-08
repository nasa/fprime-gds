"""
Data Product Decoder using ConfigManager

This module provides a ConfigManager-based decoder for F Prime Data Product files.
Unlike the original implementation which uses Pydantic models and JSON parsing,
this implementation queries type information directly from ConfigManager.

Key differences from the original implementation:
- Uses ConfigManager.get_type() and get_constant() instead of Pydantic models
- No JSON dictionary parsing - assumes ConfigManager is already loaded
- Simplified type resolution through ConfigManager

@author: thomas-bc
@date: January 2026
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import dataclasses
import re
from io import BytesIO
import zlib

from fprime_gds.common.dp.common import (
    ChecksumConfig,
    calculate_crc32,
    get_dp_header_type,
)
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.templates.dp_record_template import DpRecordTemplate

# ==============================================================================
# Custom Exceptions
# ==============================================================================

class DataProductError(Exception):
    """Base exception for data product decoding errors."""
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
# Data Product Decoder (ConfigManager-based)
# ==============================================================================

class DataProductDecoder:
    """Decoder for F Prime Data Product binary files.
    
    This decoder reads binary data product files and converts them to human-readable format.

    This currently only supports a JSON representation of the data product.

    Data Product Structure:
    1. Header (variable size based on configuration)
       - See common.py: get_dp_header_type()
    
    2. Data Records (repeated until DataSize bytes consumed)
       - Record metadata (id, type, etc.)
       - Record data (type depends on record definition)

    3. Data Hash (CRC32 of all record data)
    
    Assumptions:
        - ConfigManager is already loaded with dictionary information
        - dictionaries property (see constructor) is loaded with data product dictionary info
        - both these assumptions can be resolved by loading dictionaries (see executables/data_products.py)
    """
    
    def __init__(self, dictionaries: Dictionaries, binary_file_path: str, output_json_path: Optional[str] = None, disable_decompression: bool = False):
        """Initialize the decoder.
        
        Args:
            dictionaries: Dictionaries object containing dictionary information
            binary_file_path: Path to the binary data product file (.fdp)
            output_json_path: Optional path for output JSON file
                            (defaults to <binary_file>.json)
        """
        self.dictionaries = dictionaries
        self.binary_file_path = binary_file_path
        self.disable_decompression = disable_decompression
        if output_json_path is None:
            # Generate default output path if not provided as same path with .json extension
            self.output_json_path = str(Path(binary_file_path).with_suffix('.json'))
        else:
            self.output_json_path = output_json_path
        
    def decode_header(self, file_handle) -> Dict[str, Any]:
        """Decode the data product header.

        Args:
            file_handle: file handle to the data product binary
            
        Returns:
            Dictionary containing header fields

        Raises:
            CRCError: If header checksum validation fails
        """
        header = get_dp_header_type()()
        header_size = header.getMaxSize()
        header_bin_data = file_handle.read(header_size)
        header.deserialize(header_bin_data, 0)

        # Compute hash on header (from beginning until we hit the checksum)
        computed_hash = calculate_crc32(header_bin_data[:header_size - ChecksumConfig.CHECKSUM_LEN])

        # Validate hash
        if header.to_jsonable()["Checksum"]["value"] != computed_hash:
            raise CRCError("Header", header.to_jsonable()["Checksum"]["value"], computed_hash)

        return header
    
    def decode_record(self, file_handle, record_id: int) -> Dict[str, Any]:
        """Decode a single data record. file_handle is expected to be positioned at beginning of data
        and will be moved to end of data after decoding.

        Note: Dp records are retrieved through the dictionaries member, which is expected to have been
        loaded with dictionary information.
        
        Args:
            file_handle: file handle for binary dp - assuming it is positioned at beginning of data
            record_id: ID of the record to decode
            
        Returns:
            Dictionary containing record data
            
        Raises:
            RecordNotFoundError: If record ID not found
        """

        # Query ConfigManager for record definition
        record_template: DpRecordTemplate = self.dictionaries.dp_record_id.get(record_id)

        if record_template is None:
            raise RecordNotFoundError(record_id)

        # Record object to return
        record: dict = {'Record': dataclasses.asdict(record_template)}

        # Get the record type
        record_type = record_template.get_type()
        
        def read_element(element_type):
            """Inner function of decode_record
            Read a single element from file_handle, handling variable-length types.
            """
            element_instance = element_type()
            # Save start position and read MaxSize into a buffer
            start_pos = file_handle.tell()
            max_size = element_instance.getMaxSize()
            buffer = file_handle.read(max_size)
            # Deserialize from buffer
            element_instance.deserialize(buffer, 0)
            # If actual deserialized size is different than what was read, seek to correct position
            actual_size = element_instance.getSize()
            if actual_size != max_size:
                # Seek to true end of element that was just read
                file_handle.seek(start_pos + actual_size)
            return element_instance

        # decode based on whether it's an array or scalar
        if record_template.get_is_array():
            # For array records, read the array size first
            array_size_type = ConfigManager().get_type("FwSizeStoreType")()
            array_size_data = file_handle.read(array_size_type.getSize())
            array_size_type.deserialize(array_size_data, 0)
            array_size = array_size_type.val

            element_array_type = ArrayType.construct_type(
                f'{record_template.get_name()}_{array_size}', record_type, array_size, "{}"
            )

            element_instance = read_element(element_array_type)
            record['Data'] = element_instance.to_jsonable()
        else:
            # For scalar records, read the single value
            element_instance = read_element(record_type)
            record['Data'] = element_instance.to_jsonable()
        
        return record

    def decode_records(self, r_io, data_size) -> List[Any]:
        records = list()
        position_at_start = r_io.tell()
        while (r_io.tell() - position_at_start) < data_size:
            # Read record ID
            record_id_bin = r_io.read(ConfigManager().get_type("FwDpIdType").getSize())
            if len(record_id_bin) == 0:
                # No bytes read. Off nominal behavior
                raise DataProductError(f"End of file reached while processing data product")

            record_id_obj = ConfigManager().get_type("FwDpIdType")()
            record_id_obj.deserialize(record_id_bin, 0)
            record_id = record_id_obj.val

            # decode the record
            record = self.decode_record(r_io, record_id)
            records.append(record)

        return records

    def is_compression_record(self, record):
        return re.search("dpCompressProc.CompressionRecord$", record["Record"]["record_name"]) is not None

    def decompress_records(self, records):
        uncomp_bytes = bytearray()
        CompressionMetadata = ConfigManager().get_type("Svc.CompressionMetadata")

        for record in records:
            if not self.is_compression_record(record):
                # All records must be compressed, otherwise bail
                return None

            record_io = BytesIO(bytes(record["Data"]["values"]))

            record_meta = CompressionMetadata()
            record_meta_data = record_io.read(record_meta.getMaxSize())
            record_meta.deserialize(record_meta_data, 0)
            if record_meta.val['algorithm'] == 'UNCOMPRESSED':
                uncomp_bytes.extend(record_io.read())
            elif record_meta.val['algorithm'] == 'ZLIB_DEFLATE':
                uncomp_bytes.extend(zlib.decompress(record_io.read()))
            else:
                raise DataProductError(f"Compression algorithm {record_meta.val['algorithm']} unsupported")

        return uncomp_bytes

    def decode(self) -> List[Dict[str, Any]]:
        """decode the entire data product file.
        
        Returns:
            Dict object containing header and list of all records
            
        Raises:
            FileNotFoundError: If binary file doesn't exist
            CRCError: If checksum validation fails
            DataProductError: For other decoding errors
        """
        results = {"Header": None, "Records": []}
        
        with open(self.binary_file_path, 'rb') as f:
            ##################
            #  decode header  #
            ##################
            header_obj = self.decode_header(f)
            header_json = header_obj.to_jsonable()
            results["Header"] = header_json

            #####################
            # decode all records #
            #####################
            data_size = header_json['DataSize']["value"]
            position_at_start = f.tell()
            results["Records"] = self.decode_records(f, data_size)

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

        if not self.disable_decompression and len(results["Records"]) > 0 and self.is_compression_record(results["Records"][0]):

            # Compressed records. Decompress and re-process
            uncomp_bytes = self.decompress_records(results["Records"])
            if uncomp_bytes is not None:
                uncomp_io = BytesIO(uncomp_bytes)
                uncomp_records = self.decode_records(uncomp_io, len(uncomp_bytes))
                if uncomp_records is not None:
                    results["Records"] = uncomp_records

        return results

    def process(self):
        """Main processing: decode binary file and write JSON output."""
        try:
            print(f"Decoding {self.binary_file_path}...")
            data = self.decode()
            with open(self.output_json_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            print("Decoding complete!")
            
        except DataProductError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            raise

