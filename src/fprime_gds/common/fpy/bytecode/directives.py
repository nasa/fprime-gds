from __future__ import annotations
import typing
from typing import Any

# This makes the code forward-compatible. In Python 3.10+, the `|` operator
# creates a types.UnionType. In 3.9, only typing.Union exists.
try:
    from types import UnionType

    UNION_TYPES = (typing.Union, UnionType)
except ImportError:
    UNION_TYPES = (typing.Union,)

from dataclasses import dataclass, fields, astuple
from typing import ClassVar
import typing
from typing import Union
from pathlib import Path
import struct
import zlib
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I64Type,
    I16Type,
    I32Type,
    I8Type,
    F32Type,
    F64Type,
)
from fprime.common.models.serialize.bool_type import BoolType
from enum import Enum


def get_union_members(type_hint: type) -> list[type]:
    """
    If the type_hint is a Union, returns a list of its member types.
    Otherwise, returns the original type_hint.
    """
    # get_origin returns the base type (e.g., Union for Union[int, str])
    # or None if it's a simple type like int.
    origin = typing.get_origin(type_hint)

    if origin in UNION_TYPES:
        # get_args returns the type arguments (e.g., (int, str))
        return list(typing.get_args(type_hint))

    # Not a Union, so return the type itself
    return [type_hint]


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
    UMOD = 38
    SMOD = 39
    # float arithmetic
    FADD = 40
    FSUB = 41
    FMUL = 42
    FDIV = 43
    FLOAT_FLOOR_DIV = 44
    FPOW = 45
    FLOG = 46
    FMOD = 47
    # floating point bitwidth conversions
    FPEXT = 48
    FPTRUNC = 49
    # integer bitwidth conversions
    # signed integer extend
    SIEXT_8_64 = 50
    SIEXT_16_64 = 51
    SIEXT_32_64 = 52
    # zero (unsigned) integer extend
    ZIEXT_8_64 = 53
    ZIEXT_16_64 = 54
    ZIEXT_32_64 = 55
    # integer truncate
    ITRUNC_64_8 = 56
    ITRUNC_64_16 = 57
    ITRUNC_64_32 = 58
    # end stack op dirs

    EXIT = 59
    ALLOCATE = 60
    STORE = 61
    LOAD = 62
    PUSH_VAL = 63
    DISCARD = 64
    MEMCMP = 65
    STACK_CMD = 66


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
            field_type = typing.get_type_hints(self.__class__)[field.name]
            union_members = get_union_members(field_type)
            primitive_type = None
            # find out which primitive type it is
            for arg in union_members:
                if issubclass(arg, BaseType):
                    # it is a primitive type
                    primitive_type = arg
                    break
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
        dir_type = [
            c
            for c in (Directive.__subclasses__() + StackOpDirective.__subclasses__())
            if c.opcode.value == opcode
        ]
        if len(dir_type) != 1:
            return None

        arg_offset = 0
        dir_type = dir_type[0]
        arg_values = []

        # go through each field in the type of the directive
        for field in fields(dir_type):
            field_type = typing.get_type_hints(dir_type)[field.name]
            # get a list of all union members of the field type
            # or a list containing just the type if it is not a union
            union_types = get_union_members(field_type)

            base_type = None
            for t in union_types:
                if issubclass(t, BaseType):
                    base_type = t

            # if one of the members of the union was a sub of basetype
            if base_type is not None:
                # deserialize using that basetype and add to arg value list
                instance = base_type()
                instance.deserialize(args, arg_offset)
                arg_values.append(instance.val)
                arg_offset += instance.getSize()
                continue
            # none of the args were base types. the only other thing we could be
            # is a byte array. assert that that's true
            assert len(union_types) == 1 and union_types[0] == bytes
            # it is just raw bytes. deserialize until the end
            arg_values.append(args[arg_offset:])
            arg_offset = len(args)
            continue

        dir = dir_type(*arg_values)
        return offset, dir

@dataclass
class StackOpDirective(Directive):
    """the argument types this dir pops off the stack"""

    stack_output_type: ClassVar[type[BaseType]] = BaseType
    """the type this dir pushes to the stack"""


@dataclass
class StackCmdDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STACK_CMD

    args_size: Union[int, U32Type]


@dataclass
class MemCompareDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.MEMCMP
    size: Union[int, U32Type]


@dataclass
class LoadDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.LOAD

    lvar_offset: Union[int, U32Type]
    size: Union[int, U32Type]


@dataclass
class IntegerSignedExtend8To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_8_64
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntegerSignedExtend16To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_16_64
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntegerSignedExtend32To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_32_64
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntegerZeroExtend8To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_8_64
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class IntegerZeroExtend16To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_16_64
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class IntegerZeroExtend32To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_32_64
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class IntegerTruncate64To8Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_8
    stack_output_type: ClassVar[type[BaseType]] = I8Type


@dataclass
class IntegerTruncate64To16Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_16
    stack_output_type: ClassVar[type[BaseType]] = I16Type


@dataclass
class IntegerTruncate64To32Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_32
    stack_output_type: ClassVar[type[BaseType]] = I32Type


@dataclass
class AllocateDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.ALLOCATE

    size: Union[int, U32Type]


@dataclass
class StoreDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE

    lvar_offset: Union[int, U32Type]
    size: Union[int, U32Type]


@dataclass
class DiscardDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.DISCARD

    size: Union[int, U32Type]


@dataclass
class PushValDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PUSH_VAL

    val: bytes


@dataclass
class ConstCmdDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.CONST_CMD

    cmd_opcode: Union[int, FwOpcodeType]
    args: bytes


@dataclass
class FloatModuloDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FMOD
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class SignedModuloDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SMOD
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class UnsignedModuloDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UMOD
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class IntAddDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IADD
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntSubtractDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ISUB
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class IntMultiplyDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IMUL
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class UnsignedIntDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UDIV
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class SignedIntDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SDIV
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class FloatAddDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FADD
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatSubtractDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FSUB
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatMultiplyDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FMUL
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatExponentDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPOW
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FDIV
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatFloorDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLOAT_FLOOR_DIV
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatLogDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLOG
    stack_output_type: ClassVar[type[BaseType]] = F64Type


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
    dir_idx: Union[int, U32Type]


@dataclass
class IfDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.IF
    false_goto_dir_index: Union[int, U32Type]
    """U32: The dir index to go to if the top of stack is false."""


@dataclass
class NoOpDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.NO_OP


@dataclass
class StoreTlmValDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE_TLM_VAL
    chan_id: Union[int, FwChanIdType]
    """FwChanIdType: The telemetry channel ID to get."""
    lvar_offset: Union[int, U32Type]


@dataclass
class StorePrmDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE_PRM
    prm_id: Union[int, FwPrmIdType]
    """FwPrmIdType: The parameter ID to get the value of."""
    lvar_offset: Union[int, U32Type]


@dataclass
class OrDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.OR
    stack_args: ClassVar[list[type[BaseType]]] = [BoolType, BoolType]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class AndDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.AND
    stack_args: ClassVar[list[type[BaseType]]] = [BoolType, BoolType]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class IntEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IEQ
    stack_args: ClassVar[list[type[BaseType]]] = [
        Union[I64Type, U64Type],
        Union[I64Type, U64Type],
    ]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class IntNotEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.INE
    stack_args: ClassVar[list[type[BaseType]]] = [
        Union[I64Type, U64Type],
        Union[I64Type, U64Type],
    ]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class UnsignedLessThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ULT
    stack_args: ClassVar[list[type[BaseType]]] = [U64Type, U64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class UnsignedLessThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ULE
    stack_args: ClassVar[list[type[BaseType]]] = [U64Type, U64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class UnsignedGreaterThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UGT
    stack_args: ClassVar[list[type[BaseType]]] = [U64Type, U64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class UnsignedGreaterThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UGE
    stack_args: ClassVar[list[type[BaseType]]] = [U64Type, U64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class SignedLessThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SLT
    stack_args: ClassVar[list[type[BaseType]]] = [I64Type, I64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class SignedLessThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SLE
    stack_args: ClassVar[list[type[BaseType]]] = [I64Type, I64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class SignedGreaterThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SGT
    stack_args: ClassVar[list[type[BaseType]]] = [I64Type, I64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class SignedGreaterThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SGE
    stack_args: ClassVar[list[type[BaseType]]] = [I64Type, I64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatGreaterThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FGE
    stack_args: ClassVar[list[type[BaseType]]] = [F64Type, F64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatLessThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLE
    stack_args: ClassVar[list[type[BaseType]]] = [F64Type, F64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatLessThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLT
    stack_args: ClassVar[list[type[BaseType]]] = [F64Type, F64Type]
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatGreaterThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FGT
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FEQ
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatNotEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FNE
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class NotDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.NOT
    stack_output_type: ClassVar[type[BaseType]] = BoolType


@dataclass
class FloatTruncateDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTRUNC
    stack_output_type: ClassVar[type[BaseType]] = F32Type


@dataclass
class FloatExtendDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPEXT
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatToSignedIntDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTOSI
    stack_output_type: ClassVar[type[BaseType]] = I64Type


@dataclass
class SignedIntToFloatDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SITOFP
    stack_output_type: ClassVar[type[BaseType]] = F64Type


@dataclass
class FloatToUnsignedIntDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTOUI
    stack_output_type: ClassVar[type[BaseType]] = U64Type


@dataclass
class UnsignedIntToFloatDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UITOFP
    stack_output_type: ClassVar[type[BaseType]] = F64Type
    # src implied


@dataclass
class ExitDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.EXIT


for cls in Directive.__subclasses__() + StackOpDirective.__subclasses__():
    cls.__old_repr__ = cls.__repr__
    cls.__repr__ = Directive.__repr__


class UnaryStackOp(str, Enum):
    NOT = "not"
    IDENTITY = "+"
    NEGATE = "-"


class BinaryStackOp(str, Enum):
    EXPONENT = "**"
    MODULUS = "%"
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"
    FLOOR_DIVIDE = "//"
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="
    LESS_THAN = "<"
    EQUAL = "=="
    NOT_EQUAL = "!="
    OR = "or"
    AND = "and"


NUMERIC_OPERATORS = {
    UnaryStackOp.IDENTITY,
    UnaryStackOp.NEGATE,
    BinaryStackOp.ADD,
    BinaryStackOp.SUBTRACT,
    BinaryStackOp.MULTIPLY,
    BinaryStackOp.DIVIDE,
    BinaryStackOp.MODULUS,
    BinaryStackOp.EXPONENT,
    BinaryStackOp.FLOOR_DIVIDE,
}
BOOLEAN_OPERATORS = {UnaryStackOp.NOT, BinaryStackOp.OR, BinaryStackOp.AND}

UNARY_STACK_OPS: dict[str, dict[type[BaseType], type[StackOpDirective]]] = {
    UnaryStackOp.NOT: {BoolType: NotDirective},
    UnaryStackOp.IDENTITY: {
        I64Type: NoOpDirective,
        U64Type: NoOpDirective,
        F64Type: NoOpDirective,
    },
    UnaryStackOp.NEGATE: {
        I64Type: IntMultiplyDirective,
        U64Type: IntMultiplyDirective,
        F64Type: FloatMultiplyDirective
    },
}

BINARY_STACK_OPS: dict[str, dict[type[BaseType], type[StackOpDirective]]] = {
    BinaryStackOp.EXPONENT: {F64Type: FloatExponentDirective},
    BinaryStackOp.MODULUS: {
        I64Type: SignedModuloDirective,
        U64Type: UnsignedModuloDirective,
        F64Type: FloatModuloDirective,
    },
    BinaryStackOp.ADD: {
        I64Type: IntAddDirective,
        U64Type: IntAddDirective,
        F64Type: FloatAddDirective,
    },
    BinaryStackOp.SUBTRACT: {
        I64Type: IntSubtractDirective,
        U64Type: IntSubtractDirective,
        F64Type: FloatSubtractDirective,
    },
    BinaryStackOp.MULTIPLY: {
        I64Type: IntMultiplyDirective,
        U64Type: IntMultiplyDirective,
        F64Type: FloatMultiplyDirective,
    },
    BinaryStackOp.DIVIDE: {
        I64Type: SignedIntDivideDirective,
        U64Type: UnsignedIntDivideDirective,
        F64Type: FloatDivideDirective,
    },
    BinaryStackOp.FLOOR_DIVIDE: {
        I64Type: SignedIntDivideDirective,
        U64Type: UnsignedIntDivideDirective,
        F64Type: FloatFloorDivideDirective,
    },
    BinaryStackOp.GREATER_THAN: {
        I64Type: SignedGreaterThanDirective,
        U64Type: UnsignedGreaterThanDirective,
        F64Type: FloatGreaterThanDirective,
    },
    BinaryStackOp.GREATER_THAN_OR_EQUAL: {
        I64Type: SignedGreaterThanOrEqualDirective,
        U64Type: UnsignedGreaterThanOrEqualDirective,
        F64Type: FloatGreaterThanOrEqualDirective,
    },
    BinaryStackOp.LESS_THAN_OR_EQUAL: {
        I64Type: SignedLessThanOrEqualDirective,
        U64Type: UnsignedLessThanOrEqualDirective,
        F64Type: FloatLessThanOrEqualDirective,
    },
    BinaryStackOp.LESS_THAN: {
        I64Type: SignedLessThanDirective,
        U64Type: UnsignedLessThanDirective,
        F64Type: FloatLessThanDirective,
    },
    BinaryStackOp.EQUAL: {
        I64Type: IntEqualDirective,
        U64Type: IntEqualDirective,
        F64Type: FloatEqualDirective,
    },
    BinaryStackOp.NOT_EQUAL: {
        I64Type: IntNotEqualDirective,
        U64Type: IntNotEqualDirective,
        F64Type: FloatNotEqualDirective,
    },
    BinaryStackOp.OR: {BoolType: OrDirective},
    BinaryStackOp.AND: {BoolType: AndDirective},
}
