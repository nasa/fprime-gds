"""
Common utilities and constants for Data Product processing.

This module contains shared functionality between the Data Product Decoder
and Validator, including:
- Checksum configuration and CRC32 utilities
- Header field definitions  
- Binary format constants

@author: thomas-bc
"""

from binascii import crc32

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
    
    Used by both decoder (for accumulating CRC during read) and validator
    (for validating checksums).
    
    Args:
        data: Bytes to calculate checksum for
        init_value: Initial CRC value (default: 0)
        
    Returns:
        Calculated CRC32 checksum as 32-bit unsigned integer
    """
    return crc32(data, init_value) & ChecksumConfig.CHECKSUM_XOR_OUT


# ==============================================================================
# Data Product Header Type
# ==============================================================================

def get_dp_header_type() -> type[SerializableType]:
    """Returns a dictionary-configured DataProduct header serializable type
    As defined per https://fprime.jpl.nasa.gov/latest/Fw/Dp/docs/sdd 
    Ideally this should be part of the dictionary, but it is not currently."""
    # The reason to return construct_type() is that we want the type to be constructed
    # after the ConfigManager has been initialized, so we can't easily just define a type
    # statically and return it (or use it directly). 
    # So we construct the type here the first time this function is called
    return SerializableType.construct_type("DataProductHeaderType",
        [
            ("PacketDescriptor", ConfigManager().get_type("FwPacketDescriptorType"), "{}", "The F Prime packet descriptor"),
            ("Id", ConfigManager().get_type("FwDpIdType"), "{}", "The container ID"),
            ("Priority", ConfigManager().get_type("FwDpPriorityType"), "{}", "The container priority"),
            ("Time", TimeType, "{}", "Fw.Time object"),
            ("ProcTypes", ConfigManager().get_type("Fw.DpCfg.ProcType").REP_TYPE, "{}", "Processing types bit mask"),
            ("UserData", ArrayType.construct_type("UserData", U8Type, ConfigManager().get_constant("Fw.DpCfg.CONTAINER_USER_DATA_SIZE"), "{}"), "{}", "User-configurable data"),
            ("DpState", ConfigManager().get_type("Fw.DpState"), "{}", "Data product state"),
            ("DataSize", ConfigManager().get_type("FwSizeStoreType"), "{}", "Size of data payload in bytes"),
            ("Checksum", U32Type, "{}", "Header checksum")
        ]
    )

