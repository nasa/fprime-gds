"""
DataDescType:

Defines an enumeration that represents each type of data packet that can be downlinked.
"""

from enum import Enum
from typing import Any
from fprime_gds.common.utils.config_manager import ConfigManager


class MetaDescType(type):
    def __call__(self, *args: Any, **kwds: Any) -> Any:
        TmpDataDescType = Enum(
            "DataDescType",
            ConfigManager.get_instance().get_type("ComCfg.Apid").ENUM_DICT,
        )
        return TmpDataDescType(*args, **kwds)

    def __getitem__(self, item: Any) -> Any:
        TmpDataDescType = Enum(
            "DataDescType",
            ConfigManager.get_instance().get_type("ComCfg.Apid").ENUM_DICT,
        )
        return TmpDataDescType[item]

    def __iter__(self):
        TmpDataDescType = Enum(
            "DataDescType",
            ConfigManager.get_instance().get_type("ComCfg.Apid").ENUM_DICT,
        )
        return iter(TmpDataDescType)


class DataDescType(metaclass=MetaDescType):
    """DataDescType is a class whose purpose is to behave like an Enum, but the values
    are dynamically loaded at call-time. This allows for values to be configured through
    ConfigManager, which loads the ComCfg.Apid object from the dictionary.

    Args:
        metaclass (_type_, optional): _description_. Defaults to MetaDescType.
    """

    value: int
    name: str


# DataDescType = Enum(
#     "DataDescType",
#     {
#         # Command packet type - incoming
#         "FW_PACKET_COMMAND": 0,
#         # Telemetry packet type - outgoing
#         "FW_PACKET_TELEM": 1,
#         # Log type - outgoing
#         "FW_PACKET_LOG": 2,
#         # File type - incoming and outgoing
#         "FW_PACKET_FILE": 3,
#         # Packetized telemetry packet type
#         "FW_PACKET_PACKETIZED_TLM": 4,
#         # Idle packet
#         "FW_PACKET_IDLE": 5,
#         # Handshake packet
#         "FW_PACKET_HAND": 0xFE,
#         # Unknown packet
#         "FW_PACKET_UNKNOWN": 0xFF,
#         # Space Packet Idle APID
#         "CCSDS_SPACE_PACKET_IDLE_APID": 0x7FF,
#     },
# )
