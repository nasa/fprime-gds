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
from typing import Any


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

    The properties are meant to be stored in 3 sections (sub-dictionaries):
    1. types - typeDefinitions from FSW dictionary (key: qualifiedName, value: Type class)
    2. constants - constants definitions from FSW dictionary (key: qualifiedName, value: int)
    3. config - mapping of config field names to arbitrary values (managed internally)
    """

    # Singleton instance
    __instance = None
    # Dictionary holding all config properties
    __prop: dict

    def __init__(self):
        """
        Constructor

        Creates a ConfigManager object with the default configuration values

        Returns:
            An instance of the ConfigManager class. Default configurations
            will be used until the set_configs method is called!
        """
        # `types` and `constants` are meant to be pulled from the FSW dictionary
        # `config` is for config that is internal to the GDS
        self.__prop = {"types": {}, "constants": {}, "config": {}}
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
        Return an **instance** of the associated type.

        Args:
            name (string): Name of the type to retrieve

        Returns:
            If the name is valid, returns an object of a type derived from
            TypeBase. Otherwise, raises ConfigBadTypeException
        """
        type_class = self.__prop["types"].get(name, None)
        if type_class is None:
            raise ConfigBadTypeException(name, "Unknown type name")
        # Return an instance of the type
        return type_class()

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
        self.__prop["types"][name] = type_class

    def get_constant(self, name: str) -> int:
        """
        Get constant from the config, returning the associated integer value

        Args:
            name (string): Name of the constant to retrieve

        Returns:
            If the name is known, returns the value of the constant.
            Otherwise, raises ConfigBadTypeException
        """
        constant_value = self.__prop["constants"].get(name, None)
        if constant_value is None:
            raise ConfigBadTypeException(name, "Unknown constant name")
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
            raise ConfigBadTypeException(name, "Unknown config field name")
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
        Used by the constructor to set all ConfigManager defaults
        """
        self.__prop["types"].update(
            {
                "FwPacketDescriptorType": U16Type,
                "FwChanIdType": U32Type,
                "FwEventIdType": U32Type,
                "FwOpcodeType": U32Type,
                "FwTlmPacketizeIdType": U16Type,
            }
        )
        self.__prop["config"].update(
            {
                # msg_len is an internal type used within the GDS only
                "msg_len": U32Type,
                # Used for processing logged data from Svc.ComLogger
                "key_val": U16Type,
                "use_key": False
            }
        )
