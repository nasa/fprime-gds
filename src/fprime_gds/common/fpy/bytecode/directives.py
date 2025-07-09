from dataclasses import dataclass, fields, astuple
from types import UnionType
from typing import ClassVar
import typing
from pathlib import Path
import struct
from typing import ClassVar
import zlib
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.numerical_types import (
    NumericalType,
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I16Type,
    I32Type,
    I64Type,
    I8Type,
    F32Type,
    F64Type,
)
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.bool_type import BoolType
from enum import Enum

FwSizeType = U64Type
FwChanIdType = U32Type
FwPrmIdType = U32Type
FwOpcodeType = U32Type


class DirectiveOpcode(Enum):
    INVALID = 0
    EXIT = 1
    WAIT_REL = 2
    WAIT_ABS = 3
    GOTO = 4
    IF = 5
    NO_OP = 6
    STORE_TLM_VAL = 7
    STORE_PRM = 8
    # binary stack op directives
    # all of these are handled at the CPP level by one BinaryStackOpDirective
    # boolean ops
    OR = 9
    AND = 10
    # integer equalities
    IEQ = 11
    INE = 12
    # unsigned integer inequalities
    ULT = 13
    ULE = 14
    UGT = 15
    UGE = 16
    # signed integer inequalities
    SLT = 17
    SLE = 18
    SGT = 19
    SGE = 20
    # floating point equalities
    FEQ = 21
    FNE = 22
    # floating point inequalities
    FLT = 23
    FLE = 24
    FGT = 25
    FGE = 26
    # integer arithmetic
    IADD = 27
    ISUB = 28
    IMUL = 29
    IDIV = 30
    # float arithmetic
    FADD = 31
    FSUB = 32
    FMUL = 33
    FDIV = 34
    # end binary stack op directives

    # unary stack op dirs
    NOT = 35
    # floating point extension and truncation
    FPEXT = 36
    FPTRUNC = 37
    # floating point conversion to signed/unsigned integer,
    # and vice versa
    FPTOSI = 38
    FPTOUI = 39
    SITOFP = 40
    UITOFP = 41
    # end unary stack op dirs

    LOAD = 42
    PUSH_VAL = 43

    STORE = 44
    POP_DISCARD = 45

    CONST_CMD = 46
    STACK_CMD = 47

    ALLOCATE_STACK = 48


class Directive:
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.INVALID

    def serialize(self) -> bytes:
        arg_bytes = self.serialize_args()

        output = U8Type(self.opcode.value).serialize()
        output += U16Type(len(arg_bytes)).serialize()
        output += arg_bytes

        return output

    def serialize_args(self) -> bytes:
        output = bytes()

        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, BaseType):
                # it is already an fprime type instance
                # so we can serialize it
                output += value.serialize()
                continue

            if isinstance(value, bytes):
                # it is just raw bytes
                output += value
                continue

            # okay, it is not a primitive type or bytes
            primitive_type = None
            if typing.get_origin(field.type) == UnionType:
                # it is a union
                # find out which primitive type it is
                for arg in field.type.__args__:
                    if issubclass(arg, BaseType):
                        # it is a primitive type
                        primitive_type = arg
                        break
            elif issubclass(field.type, BaseType):
                primitive_type = field.type
            if primitive_type is None:
                raise NotImplementedError(
                    "Unknown how to serialize field", field.name, "for", self
                )

            output += primitive_type(value).serialize()

        return output


@dataclass
class Sequence:
    lvar_count: int

    dirs: list[Directive]

@dataclass
class LoadDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.LOAD

    lvar_offset: int | U16Type
    size: int | U16Type


@dataclass
class AllocateStackDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ALLOCATE_STACK

    size: int | U16Type

@dataclass
class StoreDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.STORE

    lvar_offset: int | U16Type
    size: int | U16Type


@dataclass
class PopDiscardDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.POP_DISCARD


@dataclass
class PushValDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.PUSH_VAL

    val: bytes


@dataclass
class ConstCmdDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.CONST_CMD

    cmd_opcode: int | FwOpcodeType
    args: bytes


@dataclass
class IntAddDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IADD


@dataclass
class IntSubtractDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ISUB


@dataclass
class IntMultiplyDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IMUL


@dataclass
class IntDivideDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IDIV


@dataclass
class FloatAddDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FADD


@dataclass
class FloatSubtractDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FSUB


@dataclass
class FloatMultiplyDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FMUL


@dataclass
class FloatDivideDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FDIV


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


def serialize_directives(dirs: list[Directive], output: Path = None):
    output_bytes = bytes()

    for dir in dirs:
        output_bytes += dir.serialize()

    header = Header(0, 0, 0, 1, 0, len(dirs), len(output_bytes))
    output_bytes = struct.pack(HEADER_FORMAT, *astuple(header)) + output_bytes

    crc = zlib.crc32(output_bytes) % (1 << 32)
    footer = Footer(crc)
    output_bytes += struct.pack(FOOTER_FORMAT, *astuple(footer))

    if output is None:
        output = input.with_suffix(".bin")

    output.write_bytes(output_bytes)


@dataclass
class WaitRelDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.WAIT_REL
    seconds: int | U32Type
    useconds: int | U32Type


@dataclass
class WaitAbsDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.WAIT_ABS
    wakeup_time: TimeType


@dataclass
class GotoDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.GOTO
    dir_idx: int | U32Type


@dataclass
class IfDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IF
    false_goto_dir_index: int | U32Type
    """U32: The dir index to go to if the top of stack is false."""


@dataclass
class NoOpDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.NO_OP


@dataclass
class StoreTlmValDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.STORE_TLM_VAL
    chan_id: int | FwChanIdType
    """FwChanIdType: The telemetry channel ID to get."""
    lvar_offset: int | U16Type


@dataclass
class StorePrmDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.STORE_PRM
    prm_id: int | FwPrmIdType
    """FwPrmIdType: The parameter ID to get the value of."""
    lvar_offset: int | U16Type


@dataclass
class OrDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.OR
    # lhs and rhs implied


@dataclass
class AndDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.AND
    # lhs and rhs implied


@dataclass
class IntEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IEQ
    # lhs and rhs implied


@dataclass
class IntNotEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.INE
    # lhs and rhs implied


@dataclass
class UnsignedLessThanDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ULT
    # lhs and rhs implied


@dataclass
class UnsignedLessThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ULE
    # lhs and rhs implied


@dataclass
class UnsignedGreaterThanDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UGT
    # lhs and rhs implied


@dataclass
class UnsignedGreaterThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UGE
    # lhs and rhs implied


@dataclass
class SignedLessThanDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SLT
    # lhs and rhs implied


@dataclass
class SignedLessThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SLE
    # lhs and rhs implied


@dataclass
class SignedGreaterThanDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SGT
    # lhs and rhs implied


@dataclass
class SignedGreaterThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SGE
    # lhs and rhs implied


@dataclass
class FloatGreaterThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FGE
    # lhs and rhs implied


@dataclass
class FloatLessThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FLE
    # lhs and rhs implied


@dataclass
class FloatLessThanDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FLT
    # lhs and rhs implied


@dataclass
class FloatGreaterThanDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FGT
    # lhs and rhs implied


@dataclass
class FloatEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FEQ
    # lhs and rhs implied


@dataclass
class FloatNotEqualDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FNE
    # lhs and rhs implied


@dataclass
class NotDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.NOT
    # src implied


@dataclass
class FloatTruncateDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPTRUNC
    # src implied


@dataclass
class FloatExtendDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPEXT
    # src implied


@dataclass
class FloatToSignedIntDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPTOSI
    # src implied


@dataclass
class SignedIntToFloatDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SITOFP
    # src implied


@dataclass
class FloatToUnsignedIntDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPTOUI
    # src implied


@dataclass
class UnsignedIntToFloatDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UITOFP
    # src implied


@dataclass
class ExitDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.EXIT
    success: bool | BoolType


INT_EQUALITY_DIRECTIVES: dict[str, type[Directive]] = {
    "==": IntEqualDirective,
    "!=": IntNotEqualDirective,
}

FLOAT_EQUALITY_DIRECTIVES: dict[str, type[Directive]] = {
    "==": FloatEqualDirective,
    "!=": FloatNotEqualDirective,
}


INT_SIGNED_INEQUALITY_DIRECTIVES: dict[str, type[Directive]] = {
    ">": SignedGreaterThanDirective,
    "<": SignedLessThanDirective,
    ">=": SignedGreaterThanOrEqualDirective,
    "<=": SignedLessThanOrEqualDirective,
}
INT_UNSIGNED_INEQUALITY_DIRECTIVES: dict[str, type[Directive]] = {
    ">": UnsignedGreaterThanDirective,
    "<": UnsignedLessThanDirective,
    ">=": UnsignedGreaterThanOrEqualDirective,
    "<=": UnsignedLessThanOrEqualDirective,
}
FLOAT_INEQUALITY_DIRECTIVES: dict[str, type[Directive]] = {
    ">": FloatGreaterThanDirective,
    "<": FloatLessThanDirective,
    ">=": FloatGreaterThanOrEqualDirective,
    "<=": FloatLessThanOrEqualDirective,
}

BINARY_COMPARISON_DIRECTIVES = {}
BINARY_COMPARISON_DIRECTIVES.update(INT_EQUALITY_DIRECTIVES)
BINARY_COMPARISON_DIRECTIVES.update(INT_SIGNED_INEQUALITY_DIRECTIVES)
BINARY_COMPARISON_DIRECTIVES.update(INT_UNSIGNED_INEQUALITY_DIRECTIVES)
BINARY_COMPARISON_DIRECTIVES.update(FLOAT_EQUALITY_DIRECTIVES)
BINARY_COMPARISON_DIRECTIVES.update(FLOAT_INEQUALITY_DIRECTIVES)
