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
from fprime.common.models.serialize.type_base import DictionaryType, BaseType
from fprime_gds.version import (
    MAXIMUM_SUPPORTED_FRAMEWORK_VERSION,
    MINIMUM_SUPPORTED_FRAMEWORK_VERSION,
)

# Custom Python Modules
from . import dict_loader
import json

FORMAT_STR_MAP = {
    "U8": "%u",
    "I8": "%d",
    "U16": "%u",
    "I16": "%d",
    "U32": "%u",
    "I32": "%d",
    "U64": "%lu",
    "I64": "%ld",
    "F32": "%g",
    "F64": "%g",
    "bool": "%s",
    "string": "%s",
    "ENUM": "%d",
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

    def get_versions(self) -> tuple[str, str]:
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
                "Channel entry in dictionary has no `name` field"
            )


        match type_name:
            case "I8":
                return I8Type
            case "I16":
                return I16Type
            case "I32":
                return I32Type
            case "I64":
                return I64Type
            case "U8":
                return U8Type
            case "U16":
                return U16Type
            case "U32":
                return U32Type
            case "U64":
                return U64Type
            case "F32":
                return F32Type
            case "F64":
                return F64Type
            case "bool":
                return BoolType
            case "string":
                # Does this break the logic of checking for original arguments?
                return StringType.construct_type(
                    f'String_{type_dict.get("size")}', type_dict.get("size")
                )

        # Process for enum/array/serializable types
        qualified_type = None
        for type_def in self.json_dict.get("typeDefinitions", []):
            if type_name == type_def.get("qualifiedName"):
                qualified_type = type_def
                break

        if qualified_type is None:
            # TODO: There's an issue here with PacketTypes not being in dictionary???
            return DictionaryType.construct_type(SerializableType, type_name)
            # raise ValueError(
            #     f"Channel entry in dictionary has no corresponding type definition."
            # )

        if qualified_type.get("kind") == "array":
            return ArrayType.construct_type(
                type_name,
                self.parse_type(qualified_type.get("elementType")),
                qualified_type.get("size"),
                self.get_format_string(qualified_type.get("elementType")),
            )

        if qualified_type.get("kind") == "enum":
            return EnumType.construct_type(
                type_name,
                qualified_type.get("identifiers"),
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
                        self.get_format_string(member_dict.get("type")),
                    )

                fmt_str = self.get_format_string_obj(member_type_obj)
                description = member_type_dict.get("description", "")
                struct_members.append((name, member_type_obj, fmt_str, description))

            return SerializableType.construct_type(
                type_name,
                struct_members,
            )

    def get_format_string(self, type_dict: dict) -> str | None:
        
        #probably useless
        if type_dict.get("format") is not None:
            return type_dict.get("format")

        type_name = type_dict.get("name")
        if type_name in FORMAT_STR_MAP:
            return FORMAT_STR_MAP[type_name]

        # idk either
        return "%s"
    
    def get_format_string_obj(self, type_obj: BaseType) -> str | None:

        # needs a lot of rework
        if hasattr(type_obj, "FORMAT"):
            return type_obj.FORMAT

        if hasattr(type_obj, "REP_TYPE"):
            type_name = type_obj.REP_TYPE
            if type_name in FORMAT_STR_MAP:
                return FORMAT_STR_MAP[type_name]

        # Why? idk
        return "%s"