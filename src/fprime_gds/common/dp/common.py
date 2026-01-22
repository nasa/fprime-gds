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
from typing import Dict

from fprime_gds.common.models.serialize.serializable_type import SerializableType
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.models.serialize.numerical_types import U8Type, U32Type
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.time_type import TimeType



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
    # Configurable values
    CHECKSUM_TOKEN_TYPE = U32Type
    CHECKSUM_INIT = 0
    CHECKSUM_XOR_OUT = 0xFFFFFFFF
    # Computed values
    CHECKSUM_LEN = CHECKSUM_TOKEN_TYPE.getSize()
    CHECKSUM_STRUCT = CHECKSUM_TOKEN_TYPE.get_serialize_format()



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

# class DataProductHeaderFields:
#     """Defines the structure of F Prime Data Product headers.
    
#     These field definitions are used by both parser and validator to:
#     - Calculate header sizes
#     - Parse data product files
#     - Validate data product structure
    
#     The header structure is defined by the F Prime framework and consists
#     of type definitions, constants, and fixed-size fields.
#     """
    
#     # Type definitions that must be looked up in the dictionary
#     FIELD_TYPES: Dict[str, str] = {
#         "PacketDescriptor": "FwPacketDescriptorType",
#         "Id": "FwDpIdType",
#         "Priority": "FwDpPriorityType",
#         "TimeBase": "TimeBase",
#         "TimeContext": "FwTimeContextStoreType",
#         "ProcTypes": "Fw.DpCfg.ProcType",
#         "DpState": "Fw.DpState",
#         "DataSize": "FwSizeStoreType",
#     }
    
#     # Constants that must be looked up in the dictionary
#     FIELD_CONSTANTS: Dict[str, str] = {
#         "UserData": "Fw.DpCfg.CONTAINER_USER_DATA_SIZE",
#     }
    
#     # Fixed-size fields (in bytes)
#     FIELD_CONST_SIZES: Dict[str, int] = {
#         "TimeSeconds": 4,
#         "TimeUseconds": 4,
#         "Checksum": 4
#     }

# PacketDescriptor	FwPacketDescriptorType	sizeof(FwPacketDescriptorType)	The F Prime packet descriptor FW_PACKET_DP
# Id	FwDpIdType	sizeof(FwDpIdType)	The container ID. This is a system-global ID (component-local ID + component base ID)
# Priority	FwDpPriorityType	sizeof(FwDpPriorityType)	The container priority
# TimeTag	Fw::Time	Fw::Time::SERIALIZED_SIZE	The time tag associated with the container
# ProcTypes	Fw::DpCfg::ProcType::SerialType	sizeof(Fw::DpCfg::ProcType::SerialType)	The processing types, represented as a bit mask
# UserData	Header::UserData	DpCfg::CONTAINER_USER_DATA_SIZE	User-configurable data
# DpState	DpState	DpState::SERIALIZED_SIZE	The data product state
# DataSize	FwSizeType	sizeof(FwSizeStoreType)	The size of the data payload in bytes
def get_dp_header_type() -> type[SerializableType]:
    return SerializableType.construct_type("DataProductHeaderType",
        [
            ("PacketDescriptor", ConfigManager().get_type("FwPacketDescriptorType"), "{}", "The F Prime packet descriptor"),
            ("Id", ConfigManager().get_type("FwDpIdType"), "{}", "The container ID"),
            ("Priority", ConfigManager().get_type("FwDpPriorityType"), "{}", "The container priority"),
            ("Time", TimeType, "{}", "Time tag"),
            # ("TimeSeconds", U32Type, "{}", "Time tag seconds"),
            # ("TimeUseconds", U32Type, "{}", "Time tag microseconds"),
            # ("TimeBase", ConfigManager().get_type("TimeBase"), "{}", "Time base"),
            # ("TimeContext", ConfigManager().get_type("FwTimeContextStoreType"), "{}", "Time context"),
            ("ProcTypes", ConfigManager().get_type("Fw.DpCfg.ProcType"), "{}", "Processing types bit mask"),
            ("UserData", ArrayType.construct_type("UserData", U8Type, ConfigManager().get_constant("Fw.DpCfg.CONTAINER_USER_DATA_SIZE"), "{}"), "{}", "User-configurable data"),
            ("DpState", ConfigManager().get_type("Fw.DpState"), "{}", "Data product state"),
            ("DataSize", ConfigManager().get_type("FwSizeStoreType"), "{}", "Size of data payload in bytes"),
            ("Checksum", U32Type, "{}", "Header checksum")
        ]
    )


# ==============================================================================
# Type Mapping for Binary Deserialization
# ==============================================================================

# Map F Prime type names to Python struct format characters
TYPE_STRUCT_MAPPING: Dict[str, str] = {
    'U8': 'B',   # Unsigned 8-bit integer
    'I8': 'b',   # Signed 8-bit integer
    'U16': 'H',  # Unsigned 16-bit integer
    'I16': 'h',  # Signed 16-bit integer
    'U32': 'I',  # Unsigned 32-bit integer
    'I32': 'i',  # Signed 32-bit integer
    'U64': 'Q',  # Unsigned 64-bit integer
    'I64': 'q',  # Signed 64-bit integer
    'F32': 'f',  # 32-bit float
    'F64': 'd',  # 64-bit double
}

