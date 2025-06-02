from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import struct
from typing import Any, Callable
from fprime.common.models.serialize.type_base import BaseType, ValueType
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.numerical_types import U32Type, U16Type, U8Type
from fprime.common.models.serialize.string_type import StringType

from fprime_gds.common.loaders.json_loader import PRIMITIVE_TYPE_MAP
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate


def get_type_obj_for(type: str) -> type[ValueType]:
    if type == "FwOpcodeType":
        return U32Type
    elif type == "FwSizeStoreType":
        return U16Type
    elif type == "FwChanIdType":
        return U32Type
    elif type == "FwPrmIdType":
        return U32Type

    raise RuntimeError("Unknown FPrime type alias " + str(type))


class StatementType(Enum):
    DIRECTIVE = 0
    CMD = 1


@dataclass
class StatementTemplate:
    """a statement with unspecified argument values"""

    statement_type: StatementType
    opcode: int
    name: str
    """fully qualified statement name"""
    args: list[type[BaseType] | Callable[[Any, BytecodeParseContext], BaseType]]
    """list of argument types of this statement, or functions that return an arg type"""


@dataclass
class StatementData:
    template: StatementTemplate
    arg_values: list[BaseType]


HEADER_FORMAT = "!BBBBBHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass
class Header:
    majorVersion: int
    minorVersion: int
    patchVersion: int
    schemaVersion: int
    argumentCount: int
    statementCount: int
    bodySize: int


FOOTER_FORMAT = "!I"
FOOTER_SIZE = struct.calcsize(FOOTER_FORMAT)


@dataclass
class Footer:
    crc: int


class DirectiveOpcode(Enum):
    INVALID = 0x00000000
    WAIT_REL = 0x00000001
    WAIT_ABS = 0x00000002
    SET_LVAR = 0x00000003
    GOTO = 0x00000004
    IF = 0x00000005
    NO_OP = 0x00000006
    GET_TLM = 0x00000007
    GET_PRM = 0x00000008


@dataclass
class BytecodeParseContext:
    goto_tags: map[str, int] = field(default_factory=dict)
    """a map of tag name with tag statement index"""
    types: map[str, type[BaseType]] = field(default_factory=dict)
    """a map of name to all parsed types available in the dictionary"""
    channels: map[str, ChTemplate] = field(default_factory=dict)
    """a map of name to ChTemplate object for all tlm channels"""
    params: map[str, PrmTemplate] = field(default_factory=dict)
    """a map of name to PrmTemplate object for all prms"""


def time_type_from_json(js, ctx: BytecodeParseContext):
    return TimeType(js["time_base"], js["time_context"], js["seconds"], js["useconds"])


def arbitrary_type_from_json(js, ctx: BytecodeParseContext):
    type_name = js["type"]

    if type_name == "string":
        # by default no max size restrictions in the bytecode
        return StringType.construct_type(f"String", None)(js["value"])

    # try first checking parsed_types, then check primitive types
    type_class = ctx.types.get(type_name, PRIMITIVE_TYPE_MAP.get(type_name, None))
    if type_class is None:
        raise RuntimeError("Unknown type " + str(type_name))

    return type_class(js["value"])


def goto_tag_or_idx_from_json(js, ctx: BytecodeParseContext):
    if isinstance(js, str):
        # it's a tag
        if js not in ctx.goto_tags:
            raise RuntimeError("Unknown goto tag " + str(js))
        return U32Type(ctx.goto_tags[js])

    # otherwise it is a statement index
    return U32Type(js)


def tlm_chan_id_from_json(js, ctx: BytecodeParseContext):
    if isinstance(js, str):
        if js not in ctx.channels:
            raise RuntimeError("Unknown telemetry channel " + str(js))
        return get_type_obj_for("FwChanIdType")(ctx.channels[js].id)
    elif isinstance(js, int):
        matching = [tmp for tmp in ctx.channels.keys() if tmp.id == js]
        if len(matching) != 1:
            if len(matching) == 0:
                raise RuntimeError("Unknown telemetry channel id " + str(js))
            raise RuntimeError("Multiple matches for telemetry channel id " + str(js))
        matching = matching[0]
        return get_type_obj_for("FwChanIdType")(matching.id)


def prm_id_from_json(js, ctx: BytecodeParseContext):
    if isinstance(js, str):
        if js not in ctx.params:
            raise RuntimeError("Unknown parameter " + str(js))
        return get_type_obj_for("FwPrmIdType")(ctx.params[js].prm_id)
    elif isinstance(js, int):
        matching = [tmp for tmp in ctx.params.keys() if tmp.prm_id == js]
        if len(matching) != 1:
            if len(matching) == 0:
                raise RuntimeError("Unknown param id " + str(js))
            raise RuntimeError("Multiple matches for param id " + str(js))
        matching = matching[0]
        return get_type_obj_for("FwPrmIdType")(matching.prm_id)


FPY_DIRECTIVES: list[StatementTemplate] = [
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.WAIT_REL.value,
        "WAIT_REL",
        [U32Type, U32Type],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.WAIT_ABS.value,
        "WAIT_ABS",
        [time_type_from_json],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.SET_LVAR.value,
        "SET_LVAR",
        [U8Type, arbitrary_type_from_json],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.GOTO.value,
        "GOTO",
        [goto_tag_or_idx_from_json],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.IF.value,
        "IF",
        [U8Type, goto_tag_or_idx_from_json],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.GET_TLM.value,
        "GET_TLM",
        [U8Type, U8Type, tlm_chan_id_from_json],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.GET_PRM.value,
        "GET_PRM",
        [U8Type, prm_id_from_json],
    ),
]
