from dataclasses import dataclass
import struct
from fprime.common.models.serialize.type_base import BaseType
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


@dataclass
class StatementTemplate:
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

# enum DirectiveId : FwOpcodeType {
#     INVALID = 0x00000000,
#     WAIT_REL = 0x00000001,
#     WAIT_ABS = 0x00000002,
#     MAX_DIRECTIVE_ID = 0x00000040
# };