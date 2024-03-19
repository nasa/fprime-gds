"""
ch_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries 

@author thomas-bc

"""

from fprime_gds.common.templates.ch_template import ChTemplate
# from .json_loader import JsonLoader

from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.bool_type import BoolType
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.type_base import DictionaryType
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

import json


class ChJsonLoader:
    """Class to load python based telemetry channel dictionaries"""

    # Field names in the python module files (used to construct dictionaries)
    ID_FIELD = "id"
    NAME_FIELD = "name"
    KIND_FIELD = "kind"
    DESC_FIELD = "description"
    TYPE_FIELD = "type"
    FMT_STR_FIELD = "format"
    LIMIT_FIELD = "limit"
    LIMIT_LOW = "low"
    LIMIT_HIGH = "high"
    LIMIT_RED = "red"
    LIMIT_ORANGE = "orange"
    LIMIT_YELLOW = "yellow"

    def __init__(self, dict_path: str):
        with open(dict_path, "r") as file:
            self.json_dict = json.load(file)


    def construct_dicts(self):
        """
        Constructs and returns python dictionaries keyed on id and name

        Args:
            path: Path to JSON dictionary file
        Returns:
            A tuple with two channel dictionaries (python type dict):
            (id_dict, name_dict). The keys should be the channels' id and
            name fields respectively and the values should be ChTemplate
            objects.
        """
        id_dict = {}
        name_dict = {}

        for ch_dict in self.json_dict["telemetryChannels"]:
            # Create a channel template object
            ch_temp = self.construct_template_from_dict(ch_dict)

            id_dict[ch_dict[self.ID_FIELD]] = ch_temp
            name_dict[ch_dict[self.NAME_FIELD]] = ch_temp

        return dict(sorted(id_dict.items())), dict(sorted(name_dict.items()))


    def construct_template_from_dict(self, channel_dict: dict):
        component_name = channel_dict[self.NAME_FIELD].split(".")[0]
        channel_name = channel_dict[self.NAME_FIELD].split(".")[-1]
        channel_type = channel_dict.get("type")
        if channel_type is None:
            print("Hello!")
        type_obj = self.parse_type(channel_type)

        limit_field = channel_dict.get(self.LIMIT_FIELD)
        limit_low = limit_field.get(self.LIMIT_LOW) if limit_field else None
        limit_high = limit_field.get(self.LIMIT_HIGH) if limit_field else None

        limit_low_yellow = limit_low.get(self.LIMIT_YELLOW) if limit_low else None
        limit_low_red = limit_low.get(self.LIMIT_RED) if limit_low else None
        limit_low_orange = limit_low.get(self.LIMIT_ORANGE) if limit_low else None

        limit_high_yellow = limit_high.get(self.LIMIT_YELLOW) if limit_high else None
        limit_high_red = limit_high.get(self.LIMIT_RED) if limit_high else None
        limit_high_orange = limit_high.get(self.LIMIT_ORANGE) if limit_high else None

        tmp = ChTemplate(
            channel_dict[self.ID_FIELD],
            channel_name,
            component_name,
            type_obj,
            ch_fmt_str=channel_dict.get(self.FMT_STR_FIELD),
            ch_desc=channel_dict.get(self.DESC_FIELD),
            low_red=limit_low_red,
            low_orange=limit_low_orange,
            low_yellow=limit_low_yellow,
            high_yellow=limit_high_yellow,
            high_orange=limit_high_orange,
            high_red=limit_high_red,
        )
        return tmp


    def parse_type(self, type_dict: dict) -> BaseType:

        type_name: str = type_dict.get(ChJsonLoader.NAME_FIELD, None)

        if type_name is None:
            raise ValueError(
                f"Channel entry in dictionary has no `name` field"
            )

        if type_name == "I8":
            return I8Type
        if type_name == "I16":
            return I16Type
        if type_name == "I32":
            return I32Type
        if type_name == "I64":
            return I64Type
        if type_name == "U8":
            return U8Type
        if type_name == "U16":
            return U16Type
        if type_name == "U32":
            return U32Type
        if type_name == "U64":
            return U64Type
        if type_name == "F32":
            return F32Type
        if type_name == "F64":
            return F64Type
        if type_name == "bool":
            return BoolType

        if type_name == "string":
            return StringType.construct_type(
                type_dict.get(ChJsonLoader.NAME_FIELD), type_dict.get("size")
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
                qualified_type.get("format", "%s"),
            )

        if qualified_type.get("kind") == "enum":
            return EnumType.construct_type(
                type_name,
                qualified_type.get("identifiers"),
                qualified_type.get("representationType").get("name"),
                # self.parse_type(qualified_type.get("representationType")),
            )

        if qualified_type.get("kind") == "struct":
            struct_member_list = [
                (
                    name,
                    self.parse_type(member_dict.get("type")),
                    member_dict.get("type", {}).get("format", "%s"),
                    member_dict.get("type", {}).get("description", ""),
                )
                for name, member_dict in qualified_type.get("members", {}).items()
            ]
            return SerializableType.construct_type(
                type_name,
                struct_member_list,
            )

