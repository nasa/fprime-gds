from dataclasses import dataclass
from enum import Enum
import struct
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.time_type import TimeType
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


class StatementType(Enum):
    DIRECTIVE = 0
    CMD = 1


@dataclass
class StatementTemplate:
    statement_type: StatementType
    opcode: int
    name: str
    args: list[type[BaseType]]


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
    INVALID = 0
    WAIT_REL = 0x00000001
    WAIT_ABS = 0x00000002


def time_type_from_json(js):
    return TimeType(js["time_base"], js["time_context"], js["seconds"], js["useconds"])


directives: list[StatementTemplate] = [
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.WAIT_REL.value,
        "WAIT_REL",
        [time_type_from_json],
    ),
    StatementTemplate(
        StatementType.DIRECTIVE,
        DirectiveOpcode.WAIT_ABS.value,
        "WAIT_ABS",
        [time_type_from_json],
    ),
]
