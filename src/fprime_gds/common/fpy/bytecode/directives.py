from dataclasses import dataclass, field, fields, astuple
from types import UnionType
from typing import ClassVar
import typing
from pathlib import Path
import struct
import zlib
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.numerical_types import (
    NumericalType,
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I64Type,
    I16Type,
    I32Type,
    I8Type,
    F32Type,
    F64Type
)
from fprime.common.models.serialize.bool_type import BoolType
from enum import Enum

FwSizeType = U64Type
FwChanIdType = U32Type
FwPrmIdType = U32Type
FwOpcodeType = U32Type


class DirectiveId(Enum):
    INVALID = 0
    WAIT_REL = 1
    WAIT_ABS = 2
    GOTO = 4
    IF = 5
    NO_OP = 6
    STORE_TLM_VAL = 7
    STORE_PRM = 8
    CONST_CMD = 9
    # stack op directives
    # all of these are handled at the CPP level by one StackOpDirective
    # boolean ops
    OR = 10
    AND = 11
    # integer equalities
    IEQ = 12
    INE = 13
    # unsigned integer inequalities
    ULT = 14
    ULE = 15
    UGT = 16
    UGE = 17
    # signed integer inequalities
    SLT = 18
    SLE = 19
    SGT = 20
    SGE = 21
    # floating point equalities
    FEQ = 22
    FNE = 23
    # floating point inequalities
    FLT = 24
    FLE = 25
    FGT = 26
    FGE = 27
    NOT = 28
    # floating point conversion to signed/unsigned integer,
    # and vice versa
    FPTOSI = 29
    FPTOUI = 30
    SITOFP = 31
    UITOFP = 32
    # integer arithmetic
    IADD = 33
    ISUB = 34
    IMUL = 35
    UDIV = 36
    SDIV = 37
    IMOD = 38
    # float arithmetic
    FADD = 39
    FSUB = 40
    FMUL = 41
    FDIV = 42
    FLOAT_FLOOR_DIV = 43
    FPOW = 44
    FLOG = 45
    # floating point bitwidth conversions
    FPEXT = 46
    FPTRUNC = 47
    # integer bitwidth conversions
    # signed integer extend
    SIEXT_8_64 = 48
    SIEXT_16_64 = 49
    SIEXT_32_64 = 50
    # zero (unsigned) integer extend
    ZIEXT_8_64 = 51
    ZIEXT_16_64 = 52
    ZIEXT_32_64 = 53
    # integer truncate
    ITRUNC_64_8 = 54
    ITRUNC_64_16 = 55
    ITRUNC_64_32 = 56
    # end stack op dirs

    EXIT = 57
    ALLOCATE = 58
    STORE = 59
    LOAD = 60
    PUSH_VAL = 61
    DISCARD = 62
    MEMCMP = 63

    STACK_CMD = 64

    PRINT = 59


class Directive:
    opcode: ClassVar[DirectiveId] = DirectiveId.INVALID

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

    def __repr__(self):
        r = self.__class__.__old_repr__(self)
        name = self.__class__.__name__.replace("Directive", "").upper()
        value = "".join(r.split("(")[1:])
        return name + "(" + value

    @classmethod
    def deserialize(cls, data: bytes, offset: int) -> tuple[int, "Directive"] | None:
        if len(data) - offset < 3:
            # insufficient space
            return None
        opcode = struct.unpack_from(">B", data, offset)[0]
        arg_size = struct.unpack_from(">H", data, offset + 1)[0]
        offset += 3
        if len(data) - offset < arg_size:
            # insufficient space
            return None
        args = data[offset : (offset + arg_size)]
        offset += arg_size
        dir_type = [c for c in Directive.__subclasses__() if c.opcode.value == opcode]
        if len(dir_type) != 1:
            return None

        arg_offset = 0
        dir_type = dir_type[0]
        arg_values = []

        for field in fields(dir_type):
            field_type = (
                field.type
                if isinstance(field.type, type)
                else typing.get_origin(field.type)
            )

            if issubclass(field_type, BaseType):
                # it is already an fprime type
                # so we can deserialize it
                instance = field.type()
                arg_values.append(instance.deserialize(args, arg_offset).val)
                arg_offset += instance.getSize()
                continue

            if issubclass(field_type, bytes):
                # it is just raw bytes. deserialize until the end
                arg_values.append(args[arg_offset:])
                arg_offset = len(args)
                continue

            # okay, it is not a primitive type or bytes
            primitive_type = None
            if field_type == UnionType:
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
                    "Unknown how to deserialize field", field.name, "for", cls
                )
            instance = primitive_type()
            instance.deserialize(args, arg_offset)
            arg_values.append(instance.val)
            arg_offset += instance.getSize()

        dir = dir_type(*arg_values)
        return offset, dir

@dataclass
class StackOpDirective(Directive):
    stack_args: ClassVar[list[type[BaseType]]] = []
    """the argument types this dir pops off the stack"""
    stack_output_type: ClassVar[type[BaseType]] = BaseType
    """the type this dir pushes to the stack"""

@dataclass
class StackCmdDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STACK_CMD

    args_size: int | U16Type


@dataclass
class PrintDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PRINT


@dataclass
class MemCompareDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.MEMCMP
    size: int | U16Type


@dataclass
class LoadDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.LOAD

    lvar_offset: int | U16Type
    size: int | U16Type


@dataclass
class IntegerSignedExtend8To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_8_64
    stack_args: ClassVar[list[type[BaseType]]] = [
        I8Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntegerSignedExtend16To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_16_64
    stack_args: ClassVar[list[type[BaseType]]] = [
        I16Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntegerSignedExtend32To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_32_64
    stack_args: ClassVar[list[type[BaseType]]] = [
        I32Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntegerZeroExtend8To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_8_64
    stack_args: ClassVar[list[type[BaseType]]] = [
        U8Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class IntegerZeroExtend16To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_16_64
    stack_args: ClassVar[list[type[BaseType]]] = [
        U16Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U64Type

@dataclass
class IntegerZeroExtend32To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_32_64
    stack_args: ClassVar[list[type[BaseType]]] = [
        U32Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class IntegerTruncate64To8Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_8
    stack_args: ClassVar[list[type[BaseType]]] = [
        U64Type|I64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U8Type|I8Type


@dataclass
class IntegerTruncate64To16Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_16
    stack_args: ClassVar[list[type[BaseType]]] = [
        U64Type|I64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U16Type|I16Type


@dataclass
class IntegerTruncate64To32Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_32
    stack_args: ClassVar[list[type[BaseType]]] = [
        U64Type|I64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U32Type|I32Type


@dataclass
class AllocateDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.ALLOCATE

    size: int | U16Type


@dataclass
class StoreDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE

    lvar_offset: int | U16Type
    size: int | U16Type


@dataclass
class DiscardDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.DISCARD

    size: int | U16Type


@dataclass
class PushValDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PUSH_VAL

    val: bytes


@dataclass
class ConstCmdDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.CONST_CMD

    cmd_opcode: int | FwOpcodeType
    args: bytes


@dataclass
class IntModuloDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IMOD
    stack_args: ClassVar[list[type[BaseType]]] = [
        I64Type|U64Type, I64Type|U64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type|U64Type


@dataclass
class IntAddDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IADD
    stack_args: ClassVar[list[type[BaseType]]] = [
        I64Type|U64Type, I64Type|U64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type|U64Type


@dataclass
class IntSubtractDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ISUB
    stack_args: ClassVar[list[type[BaseType]]] = [
        I64Type|U64Type, I64Type|U64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type|U64Type


@dataclass
class IntMultiplyDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IMUL
    stack_args: ClassVar[list[type[BaseType]]] = [
        I64Type|U64Type, I64Type|U64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type|U64Type


@dataclass
class UnsignedIntDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UDIV
    stack_args: ClassVar[list[type[BaseType]]] = [
        U64Type, U64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class SignedIntDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SDIV
    stack_args: ClassVar[list[type[BaseType]]] = [
        I64Type, I64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class FloatAddDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FADD
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatSubtractDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FSUB
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatMultiplyDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FMUL
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatExponentDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPOW
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FDIV
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatFloorDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLOAT_FLOOR_DIV
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatLogDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLOG
    stack_args: ClassVar[list[type[BaseType]]] = [
        F64Type, F64Type
    ]
    stack_output_type: ClassVar[type[BaseType]] = F64Type


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
    opcode: ClassVar[DirectiveId] = DirectiveId.WAIT_REL
    # seconds and useconds are implicit


@dataclass
class WaitAbsDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.WAIT_ABS
    # time base, time context, seconds and useconds are implicit


@dataclass
class GotoDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.GOTO
    dir_idx: int | U32Type


@dataclass
class IfDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.IF
    false_goto_dir_index: int | U32Type
    """U32: The dir index to go to if the top of stack is false."""


@dataclass
class NoOpDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.NO_OP


@dataclass
class StoreTlmValDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE_TLM_VAL
    chan_id: int | FwChanIdType
    """FwChanIdType: The telemetry channel ID to get."""
    lvar_offset: int | U16Type


@dataclass
class StorePrmDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE_PRM
    prm_id: int | FwPrmIdType
    """FwPrmIdType: The parameter ID to get the value of."""
    lvar_offset: int | U16Type


@dataclass
class OrDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.OR
    # lhs and rhs implied


@dataclass
class AndDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.AND
    # lhs and rhs implied


@dataclass
class IntEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.IEQ
    # lhs and rhs implied


@dataclass
class IntNotEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.INE
    # lhs and rhs implied


@dataclass
class UnsignedLessThanDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.ULT
    # lhs and rhs implied


@dataclass
class UnsignedLessThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.ULE
    # lhs and rhs implied


@dataclass
class UnsignedGreaterThanDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.UGT
    # lhs and rhs implied


@dataclass
class UnsignedGreaterThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.UGE
    # lhs and rhs implied


@dataclass
class SignedLessThanDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.SLT
    # lhs and rhs implied


@dataclass
class SignedLessThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.SLE
    # lhs and rhs implied


@dataclass
class SignedGreaterThanDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.SGT
    # lhs and rhs implied


@dataclass
class SignedGreaterThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.SGE
    # lhs and rhs implied


@dataclass
class FloatGreaterThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FGE
    # lhs and rhs implied


@dataclass
class FloatLessThanOrEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLE
    # lhs and rhs implied


@dataclass
class FloatLessThanDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLT
    # lhs and rhs implied


@dataclass
class FloatGreaterThanDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FGT
    # lhs and rhs implied


@dataclass
class FloatEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FEQ
    # lhs and rhs implied


@dataclass
class FloatNotEqualDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FNE
    # lhs and rhs implied


@dataclass
class NotDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.NOT
    # src implied


@dataclass
class FloatTruncateDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTRUNC
    # src implied


@dataclass
class FloatExtendDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPEXT
    # src implied


@dataclass
class FloatToSignedIntDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTOSI
    # src implied


@dataclass
class SignedIntToFloatDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.SITOFP
    # src implied


@dataclass
class FloatToUnsignedIntDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTOUI
    # src implied


@dataclass
class UnsignedIntToFloatDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.UITOFP
    # src implied


@dataclass
class ExitDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.EXIT


for cls in Directive.__subclasses__():
    cls.__old_repr__ = cls.__repr__
    cls.__repr__ = Directive.__repr__

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
