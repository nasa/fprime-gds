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

from fprime.common.models.serialize.numerical_types import (
    U16Type,
    U32Type,
)
from fprime.common.models.serialize.type_base import BaseType


class ConfigBadTypeException(Exception):
    def __init__(self, config_name, type_str):
        """
        Constructor

        Args:
            config_name (string): Name of the config containing the bad type
            type_str (string): Bad type string that caused the error
        """
        super().__init__(
            f"Invalid type string {type_str} read in configuration {config_name}"
        )


class ConfigManager:
    """
    This class provides a single entrypoint for all configurable properties of the GDS
    """

    __instance = None
    __prop: dict = dict()

    def __init__(self):
        """
        Constructor

        Creates a ConfigManager object with the default configuration values

        Returns:
            An instance of the ConfigManager class. Default configurations
            will be used until the set_configs method is called!
        """
        # Set default properties
        self.__prop = dict()
        self._set_defaults()

    @staticmethod
    def get_instance():
        """
        Return instance of singleton.

        Returns:
            The current ConfigManager object for this python application
        """
        if ConfigManager.__instance is None:
            ConfigManager.__instance = ConfigManager()
        return ConfigManager.__instance

    def get_type(self, name: str) -> BaseType:
        """
        Retrieve a type from the config for parsing by returning an instance
        of the associated type.

        Args:
            name (string): Name of the type to retrieve

        Returns:
            If the name is valid, returns an object of a type derived from
            TypeBase. Otherwise, raises ConfigBadTypeException
        """
        type_class = self.__prop.get(name, None)
        if type_class is None:
            raise ConfigBadTypeException(name, "Unknown type name")
        # Return an instance of the type
        return type_class()

    def _set_defaults(self):
        """
        Used by the constructor to set all ConfigParser defaults

        Establishes a dictionary of sections and then a dictionary of keyword,
        value association for each section.
        """

        ########################## TYPES ###########################
        # These configs give the types of fields in the binary data

        self.__prop.update(
            {
                "msg_len": U32Type,
                "FwPacketDescriptorType": U32Type,
                "FwChanIdType": U32Type,
                "FwEventIdType": U32Type,
                "FwOpcodeType": U32Type,
                "FwTlmPacketizeIdType": U16Type,
            }
        )

    def set_type(self, name: str, type_class: type[BaseType]):
        """
        Set a type in the config for parsing by associating a name with
        a type class.

        Args:
            name (string): Name of the type to set
            type_class (type[TypeBase]): Class of (**not** instance of) the type to associate with the name

        Returns:
            None
        """
        self.__prop[name] = type_class
