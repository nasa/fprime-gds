"""
json_loader.py:

Base class for all loaders that load dictionaries from json dictionaries

@author thomas-bc
"""

from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.bool_type import BoolType
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.numerical_types import (
    F32Type,
    F64Type,
    I8Type,
    I16Type,
    I32Type,
    I64Type,
    U8Type,
    U16Type,
    U32Type,
    U64Type,
)
from fprime.common.models.serialize.serializable_type import SerializableType
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.type_base import BaseType

from typing import Optional

# Custom Python Modules
from . import dict_loader

import json
from fprime_gds.common.utils.string_util import preprocess_fpp_format_str


PRIMITIVE_TYPE_MAP = {
    "I8": I8Type,
    "I16": I16Type,
    "I32": I32Type,
    "I64": I64Type,
    "U8": U8Type,
    "U16": U16Type,
    "U32": U32Type,
    "U64": U64Type,
    "F32": F32Type,
    "F64": F64Type,
    "bool": BoolType,
}


class JsonLoader(dict_loader.DictLoader):
    """Class to help load JSON dictionaries"""

    def __init__(self, json_dict: dict):
        """
        Constructor

        Returns:
            An initialized loader object
        """
        super().__init__()

        # These dicts hold already parsed enum objects so things don't need
        # to be parsed multiple times
        self.enums = {}
        self.serializable_types = {}
        self.array_types = {}
        with open(json_dict, "r") as f:
            self.json_dict = json.load(f)

    def get_versions(self):
        """
        Get the framework and project versions of the dictionary

        Returns:
            A tuple of the framework and project versions
        """
        return (
            self.json_dict.get("framework_version", "unknown"),
            self.json_dict.get("project_version", "unknown"),
        )

    def parse_type(self, type_dict: dict) -> BaseType:

        type_name: str = type_dict.get("name", None)

        if type_name is None:
            raise ValueError(
                f"Channel entry in dictionary has no `name` field: {str(type_dict)}"
            )

        if type_name in PRIMITIVE_TYPE_MAP:
            return PRIMITIVE_TYPE_MAP[type_name]

        if type_name == "string":
            # REVIEW NOTE: Does name matter? I believe not
            return StringType.construct_type(
                f'String_{type_dict.get("size")}', type_dict.get("size")
            )

        # Process for enum/array/serializable types
        # TODO: Rework logic here to cache typeDefinitions in member variable, either at read-time or init-time?
        qualified_type = None
        for type_def in self.json_dict.get("typeDefinitions", []):
            if type_name == type_def.get("qualifiedName"):
                qualified_type = type_def
                break

        if qualified_type is None:
            raise ValueError(
                f"Channel entry {type_name} in dictionary has no corresponding type definition."
            )

        if qualified_type.get("kind") == "array":
            return ArrayType.construct_type(
                type_name,
                self.parse_type(qualified_type.get("elementType")),
                qualified_type.get("size"),
                qualified_type.get("elementType").get("format", "{}"),
            )

        if qualified_type.get("kind") == "enum":
            enum_dict = {}
            for member in qualified_type.get("enumeratedConstants"):
                enum_dict[member.get("name")] = member.get("value")
            return EnumType.construct_type(
                type_name,
                enum_dict,
                qualified_type.get("representationType").get("name"),
            )

        if qualified_type.get("kind") == "struct":
            struct_members = []
            for name, member_dict in qualified_type.get("members").items():
                member_type_dict = member_dict.get("type")
                member_type_obj = self.parse_type(member_type_dict)

                # For member arrays (declared inline, so we create a type on the fly)
                if member_dict.get("size") is not None:
                    member_type_obj = ArrayType.construct_type(
                        f"Array_{member_type_obj.__name__}_{member_dict.get('size')}",
                        member_type_obj,
                        member_dict.get("size"),
                        member_dict.get("type").get("format", "{}"),
                    )

                fmt_str = (
                    member_type_obj.FORMAT
                    if hasattr(member_type_obj, "FORMAT")
                    else "{}"
                )
                description = member_type_dict.get("annotation", "")
                struct_members.append((name, member_type_obj, fmt_str, description))

            return SerializableType.construct_type(
                type_name,
                struct_members,
            )

        raise ValueError(
            f"Channel entry in dictionary has unknown type {str(type_dict)}"
        )

    @staticmethod
    def preprocess_format_str(format_str: Optional[str]) -> str:
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
