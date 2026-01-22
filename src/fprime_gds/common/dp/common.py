"""
Common utilities and constants for Data Product processing.

This module contains shared functionality between the Data Product Parser
and Validator, including:
- Checksum configuration and CRC32 utilities
- Header field definitions  
- Binary format constants

@author: Gerik Kubiak, Garth Watney, Thomas Boyer-Chammard
"""

import struct
from binascii import crc32
from typing import Dict

# ==============================================================================
# Binary Format Constants
# ==============================================================================

# Deserialize the binary file big endian
BIG_ENDIAN = ">"

# ==============================================================================
# Checksum Configuration
# ==============================================================================

class ChecksumConfig:
    """Configuration for CRC32 checksum validation.
    
    These values are technically configurable by F Prime end users,
    but are treated as constants here. Future work could parameterize these.
    """
    CHECKSUM_LEN = 4
    CHECKSUM_STRUCT = ">I"  # Big-endian unsigned 32-bit integer
    CHECKSUM_INIT = 0
    CHECKSUM_XOR_OUT = 0xFFFFFFFF


def calculate_crc32(data: bytes, init_value: int = ChecksumConfig.CHECKSUM_INIT) -> int:
    """Calculate CRC32 checksum for given data.
    
    Used by both parser (for accumulating CRC during read) and validator
    (for validating checksums).
    
    Args:
        data: Bytes to calculate checksum for
        init_value: Initial CRC value (default: 0)
        
    Returns:
        Calculated CRC32 checksum as 32-bit unsigned integer
    """
    return crc32(data, init_value) & ChecksumConfig.CHECKSUM_XOR_OUT


# ==============================================================================
# Data Product Header Field Definitions
# ==============================================================================

class DataProductHeaderFields:
    """Defines the structure of F Prime Data Product headers.
    
    These field definitions are used by both parser and validator to:
    - Calculate header sizes
    - Parse data product files
    - Validate data product structure
    
    The header structure is defined by the F Prime framework and consists
    of type definitions, constants, and fixed-size fields.
    """
    
    # Type definitions that must be looked up in the dictionary
    FIELD_TYPES: Dict[str, str] = {
        "PacketDescriptor": "FwPacketDescriptorType",
        "Id": "FwDpIdType",
        "Priority": "FwDpPriorityType",
        "TimeBase": "TimeBase",
        "TimeContext": "FwTimeContextStoreType",
        "ProcTypes": "Fw.DpCfg.ProcType",
        "DpState": "Fw.DpState",
        "DataSize": "FwSizeStoreType",
    }
    
    # Constants that must be looked up in the dictionary
    FIELD_CONSTANTS: Dict[str, str] = {
        "UserData": "Fw.DpCfg.CONTAINER_USER_DATA_SIZE",
    }
    
    # Fixed-size fields (in bytes)
    FIELD_CONST_SIZES: Dict[str, int] = {
        "TimeSeconds": 4,
        "TimeUseconds": 4,
        "Checksum": 4
    }
