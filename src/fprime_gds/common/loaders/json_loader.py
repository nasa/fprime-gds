"""
json_loader.py:

Base class for all loaders that load dictionaries from json dictionaries

@author thomas-bc
"""

import json
from typing import Optional

from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.bool_type import BoolType
from fprime.common.models.serialize.enum_type import EnumType
import fprime.common.models.serialize.numerical_types as numerical_types
from fprime.common.models.serialize.serializable_type import SerializableType
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.type_base import BaseType

from fprime_gds.common.utils.string_util import preprocess_fpp_format_str
from fprime_gds.common.loaders import dict_loader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


PRIMITIVE_TYPE_MAP = {
    "I8": numerical_types.I8Type,
    "I16": numerical_types.I16Type,
    "I32": numerical_types.I32Type,
    "I64": numerical_types.I64Type,
    "U8": numerical_types.U8Type,
    "U16": numerical_types.U16Type,
    "U32": numerical_types.U32Type,
    "U64": numerical_types.U64Type,
    "F32": numerical_types.F32Type,
    "F64": numerical_types.F64Type,
    "bool": BoolType,
}


class JsonLoader(dict_loader.DictLoader):
    """Class to help load JSON dictionaries"""

    # Cache parsed type objects at the class level so they can be reused across subclasses
    parsed_types: dict = {}

    def __init__(self, json_file: str):
        """
        Constructor

        Returns:
            An initialized loader object
        """
        super().__init__()
        self.json_file = json_file
        with open(json_file, "r") as f:
            self.json_dict = json.load(f)

    def get_versions(self):
        """
        Get the framework and project versions of the dictionary

        Returns:
            A tuple of the framework and project versions
        """
        if "metadata" not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Dictionary has no metadata field: {self.json_file}"
            )
        return (
            self.json_dict["metadata"].get("frameworkVersion", "unknown"),
            self.json_dict["metadata"].get("projectVersion", "unknown"),
        )

    def parse_type(self, type_dict: dict) -> BaseType:
        type_name: str = type_dict.get("name", None)

        if type_name is None:
            raise GdsDictionaryParsingException(
                f"Dictionary entry has no `name` field: {str(type_dict)}"
            )

        if type_name in PRIMITIVE_TYPE_MAP:
            return PRIMITIVE_TYPE_MAP[type_name]

        if type_name == "string":
            return StringType.construct_type(
                f'String_{type_dict["size"]}', type_dict["size"]
            )

        # Check if type has already been parsed
        if type_name in self.parsed_types:
            return self.parsed_types[type_name]

        # Parse new enum/array/serializable types
        qualified_type = None
        for type_def in self.json_dict.get("typeDefinitions", []):
            if type_name == type_def.get("qualifiedName"):
                qualified_type = type_def
                break
        else:
            raise GdsDictionaryParsingException(
                f"Dictionary type name has no corresponding type definition: {type_name}"
            )

        if qualified_type.get("kind") == "array":
            return self.construct_array_type(type_name, qualified_type)

        if qualified_type.get("kind") == "enum":
            return self.construct_enum_type(type_name, qualified_type)

        if qualified_type.get("kind") == "struct":
            return self.construct_serializable_type(type_name, qualified_type)

        raise GdsDictionaryParsingException(
            f"Dictionary entry has unknown type {str(type_dict)}"
        )

    def construct_enum_type(self, type_name: str, qualified_type: dict) -> EnumType:
        """
        Constructs an EnumType object of the given type name and qualified type dictionary.
        Caches the constructed EnumType object in the parsed_types dictionary.

        Args:
            type_name (str): The name of the enum type.
            qualified_type (dict): A dictionary containing the qualified type information.

        Returns:
            EnumType: The constructed EnumType object.

        """
        enum_dict = {}
        for member in qualified_type.get("enumeratedConstants"):
            enum_dict[member["name"]] = member.get("value")
        enum_type = EnumType.construct_type(
            type_name,
            enum_dict,
            qualified_type["representationType"].get("name"),
        )
        self.parsed_types[type_name] = enum_type
        return enum_type

    def construct_array_type(self, type_name: str, qualified_type: dict) -> ArrayType:
        """
        Constructs an ArrayType object based on the given type name and qualified type dictionary.
        Caches the constructed ArrayType object in the parsed_types dictionary.

        Args:
            type_name (str): The name of the array type.
            qualified_type (dict): The qualified type dictionary containing information about the array type.

        Returns:
            ArrayType: The constructed ArrayType object.

        """
        array_type = ArrayType.construct_type(
            type_name,
            self.parse_type(qualified_type.get("elementType")),
            qualified_type.get("size"),
            JsonLoader.preprocess_format_str(
                qualified_type["elementType"].get("format", "{}")
            ),
        )
        self.parsed_types[type_name] = array_type
        return array_type

    def construct_serializable_type(
        self, type_name: str, qualified_type: dict
    ) -> SerializableType:
        """
        Constructs a SerializableType based on the given type name and qualified type dictionary.
        Caches the constructed SerializableType object in the parsed_types dictionary.

        Args:
            type_name (str): The name of the serializable type.
            qualified_type (dict): The qualified type dictionary containing information about the type.

        Returns:
            SerializableType: The constructed serializable type.

        """
        struct_members = []
        for name, member_dict in qualified_type.get("members").items():
            member_type_dict = member_dict["type"]
            member_type_obj = self.parse_type(member_type_dict)

            # For member arrays (declared inline, so we create a type on the fly)
            if member_dict.get("size") is not None:
                member_type_obj = ArrayType.construct_type(
                    f"Array_{member_type_obj.__name__}_{member_dict['size']}",
                    member_type_obj,
                    member_dict["size"],
                    JsonLoader.preprocess_format_str(
                        member_dict["type"].get("format", "{}")
                    ),
                )
            fmt_str = JsonLoader.preprocess_format_str(
                member_type_obj.FORMAT if hasattr(member_type_obj, "FORMAT") else "{}"
            )
            description = member_type_dict.get("annotation", "")
            struct_members.append((name, member_type_obj, fmt_str, description))

        ser_type = SerializableType.construct_type(
            type_name,
            struct_members,
        )
        self.parsed_types[type_name] = ser_type
        return ser_type

    @staticmethod
    def preprocess_format_str(format_str: Optional[str]) -> Optional[str]:
        """Preprocess format strings before using them in Python format function
        Internally, this converts FPP-style format strings to Python-style format strings

        Args:
            format_str (str): FPP-style format string

        Returns:
            str: Python-style format string
        """
        if format_str is None:
            return None
        return preprocess_fpp_format_str(format_str)
