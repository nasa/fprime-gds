"""
@brief Utility class to read config files and provide configuration values

After the first instance of this class is initialized, any class can obtain
the same instance by calling the static getInstance function. This allows any
part of the python program retrieve configuration data.

Based on the ConfigManager class written by Len Reder in the fprime Gse

@author R. Joseph Paetz

@date Created July 25, 2018

@license Copyright 2018, California Institute of Technology.
         ALL RIGHTS RESERVED. U.S. Government Sponsorship acknowledged.
"""

from fprime_gds.common.models.serialize.numerical_types import (
    U16Type,
    U32Type,
    U8Type,
    ValueType,
)
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.type_exceptions import FprimeGdsException

from typing import Any



class ConfigBadTypeException(FprimeGdsException):
    def __init__(self, config_name, type_str):
        """
        Constructor

        Args:
            config_name (string): Name of the config containing the bad type
            type_str (string): Bad type string that caused the error
        """
        super().__init__(f"{config_name}: {type_str}")


class ConfigManager:
    """
    This class provides a single entrypoint for all configurable properties of the GDS

    The properties are meant to be stored in 3 sections (sub-dictionaries):
    1. types - typeDefinitions from FSW dictionary (key: qualifiedName, value: Type class)
    2. constants - constants definitions from FSW dictionary (key: qualifiedName, value: int)
    3. config - mapping of config field names to arbitrary values (managed internally)
    """

    # Singleton instance
    __instance = None
    # Dictionary holding all config properties
    __prop: dict

    def __new__(cls):
        """Controls creation of and access to the singleton instance.

        This forbids construction of multiple ConfigManager instances.

        Usage:
            MyType = ConfigManager().get_type("MyType")

        Returns:
            The singleton ConfigManager object for this python application
        """
        if cls.__instance is None:
            cls.__instance = super(ConfigManager, cls).__new__(cls)
            # Initialization of the singleton instance - only ran once
            cls.__instance.__prop = {"types": {}, "constants": {}, "config": {}}
            cls.__instance._set_defaults()
        return cls.__instance

    @staticmethod
    def get_instance():
        """
        Return instance of singleton. Superseded by the __new__ access method, but
        left for backwards compatibility.

        Returns:
            The current ConfigManager object for this python application
        """
        return ConfigManager()

    def get_type(self, name: str) -> type[ValueType]:
        """
        Return the associated type class for the given name.
        
        Args:
            name (string): Name of the type to retrieve

        Returns:
            If the name is valid, returns a class derived from
            ValueType. Otherwise, raises ConfigBadTypeException
        """
        type_class = self.__prop["types"].get(name, None)
        if type_class is None:
            raise ConfigBadTypeException("Unknown type name", name)
        return type_class

    def set_type(self, name: str, type_class: type[ValueType]):
        """
        Set a type in the config for parsing by associating a name with
        a type class.

        Args:
            name (string): Name of the type to set
            type_class (type[ValueType]): Class of (**not** instance of) the type to associate with the name
        """
        self.__prop["types"][name] = type_class

    def get_constant(self, name: str) -> int:
        """
        Get constant from the config, returning the associated integer value.

        Args:
            name (string): Name of the constant to retrieve

        Returns:
            If the name is known, returns the value of the constant.
            Otherwise, raises ConfigBadTypeException.
        """
        constant_value = self.__prop["constants"].get(name, None)
        if constant_value is None:
            raise ConfigBadTypeException("Unknown constant name", name)
        return constant_value

    def set_constant(self, name: str, value: int):
        """
        Set a constant in the config for parsing by associating a name with
        an integer value.

        Args:
            name (string): Name of the constant to set
            value (int): Value of the constant to associate with the name

        Returns:
            None
        """
        self.__prop["constants"][name] = value

    def get_config(self, name: str) -> Any:
        """
        Get config field from the config, returning the associated object

        Args:
            name (string): Name of the config field to retrieve

        Returns:
            If the name is known, returns the config field.
            Otherwise, raises ConfigBadTypeException
        """
        config_value = self.__prop["config"].get(name, None)
        if config_value is None:
            raise ConfigBadTypeException("Unknown config field name", name)
        return config_value

    def set_config(self, name: str, entry: Any):
        """
        Set a configuration entry in the config

        Args:
            name (string): Name of the config to set
            entry (Any): config to associate with the name

        Returns:
            None
        """
        self.__prop["config"][name] = entry

    def _set_defaults(self):
        """
        Set all ConfigManager defaults. Needed for backwards compatibility if the flight dictionary
        does not provide certain types or constants.
        """
        self.__prop["types"].update(
            {
                "FwPacketDescriptorType": U16Type,
                "FwChanIdType": U32Type,
                "FwEventIdType": U32Type,
                "FwOpcodeType": U32Type,
                "FwTlmPacketizeIdType": U16Type,
                "FwSizeStoreType": U16Type,
                "FwTimeContextStoreType": U8Type,
                "TimeBase": EnumType.construct_type(
                    "__GdsInternal_TimeBase_Fallback",
                    {
                        "TB_NONE": 0,
                        # Processor cycle time. Not tried to external time
                        "TB_PROC_TIME": 1,
                        # Time on workstation where software is running. For testing.
                        "TB_WORKSTATION_TIME": 2,
                        # Time as reported by the SCLK.
                        "TB_SC_TIME": 3,
                        # Time as reported by the FPGA clock
                        "TB_FPGA_TIME": 4,
                        # Don't care value for sequences
                        "TB_DONT_CARE": 0xFFFF,
                    },
                    rep_type="U16",
                ),
                "ComCfg.Apid": EnumType.construct_type(
                    "__GdsInternal_Apid_Fallback",
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
                    rep_type="U16",
                ),
            }
        )
        self.__prop["constants"].update(
            {
                "FW_SERIALIZE_TRUE_VALUE": 0xFF,
                "FW_SERIALIZE_FALSE_VALUE": 0,
            }
        )
        self.__prop["config"].update(
            {
                # msg_len is an internal type used within the GDS only
                "msg_len": U32Type,
                # Used for processing logged data from Svc.ComLogger
                "key_val": U16Type,
                "use_key": False,
            }
        )
