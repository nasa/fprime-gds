"""
DataDescType:

Defines an enumeration that represents each type of data packet that can be downlinked.
"""

from enum import Enum
from typing import Any
from fprime_gds.common.utils.config_manager import ConfigManager


class MetaDescType(type):
    """Metaclass for DataDescType to allow dynamically loading enum values"""

    ENUM_TYPE_NAME: str = "DataDescType"

    LOADED: bool = False
    UNDERLYING_ENUM: type[Enum] = Enum(
        "DataDescType",
        # Default values - will be overridden if loaded from ConfigManager
        {
            # Command packet type - incoming
            "FW_PACKET_COMMAND": 0,
            # Telemetry packet type - outgoing
            "FW_PACKET_TELEM": 1,
            # Log type - outgoing
            "FW_PACKET_LOG": 2,
            # File type - incoming and outgoing
            "FW_PACKET_FILE": 3,
            # Packetized telemetry packet type
            "FW_PACKET_PACKETIZED_TLM": 4,
            # Idle packet
            "FW_PACKET_IDLE": 5,
            # Handshake packet
            "FW_PACKET_HAND": 0xFE,
            # Unknown packet
            "FW_PACKET_UNKNOWN": 0xFF,
            # Space Packet Idle APID
            "CCSDS_SPACE_PACKET_IDLE_APID": 0x7FF,
        },
    )

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        """Enables instantiation of the enum members with EnumClass(value)"""
        self.load_guard()
        return self.UNDERLYING_ENUM(*args, **kwds)

    def __getitem__(self, item: Any) -> Any:
        """Enables instantiation of the enum members with EnumClass['name']"""
        self.load_guard()
        return self.UNDERLYING_ENUM[item]

    def __iter__(self):
        """Allows for looping over Enum values"""
        self.load_guard()
        return iter(self.UNDERLYING_ENUM)

    @classmethod
    def load_guard(cls):
        """Loads the enum values from the ConfigManager if not already loaded"""
        if not cls.LOADED:
            cls.LOADED = True
            # Load the enum values from the config manager
            apid_type = ConfigManager.get_instance().get_type(cls.ENUM_TYPE_NAME)
            if apid_type is not None and hasattr(apid_type, "ENUM_DICT"):
                cls.UNDERLYING_ENUM = Enum(
                    "DataDescType",
                    apid_type.ENUM_DICT,
                )
            else:
                print(
                    f"[WARNING] Dictionary does not contain a {cls.ENUM_TYPE_NAME} "
                    "enumeration. Using default values for Packet Descriptors."
                )


class DataDescType(metaclass=MetaDescType):
    """DEPRECATED: Use ConfigManager.get_data_desc_type() instead

    DataDescType is a class whose purpose is to behave like an Enum, but the values
    are dynamically loaded from the ConfigManager the first time it is accessed.
    This allows for values to be configured through the items from the dictionary.
    """

    value: int
    name: str
