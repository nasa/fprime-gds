from dataclasses import dataclass
from enum import Enum
import struct
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
)


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
    args: list[type[BaseType]]
    """list of argument types of this statement"""


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
    """converts a json object into a TimeType object"""
    return TimeType(js["time_base"], js["time_context"], js["seconds"], js["useconds"])


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
]
