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

from dataclasses import dataclass, fields
from typing import ClassVar
import typing
from typing import Union
import struct
from fprime_gds.common.models.serialize.type_base import BaseType as FppValue
from fprime_gds.common.models.serialize.numerical_types import (
    U8Type as U8Value,
    U16Type as U16Value,
    U32Type as U32Value,
    U64Type as U64Value,
    I8Type as I8Value,
    I16Type as I16Value,
    I32Type as I32Value,
    I64Type as I64Value,
    F32Type as F32Value,
    F64Type as F64Value,
)
from fprime_gds.common.models.serialize.bool_type import BoolType as BoolValue
from enum import Enum

FwSizeType = U64Value
FwChanIdType = U32Value
FwPrmIdType = U32Value
FwOpcodeType = U32Value
ArrayIndexType = U64Value
StackSizeType = U32Value


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


class DirectiveId(Enum):
    INVALID = 0
    WAIT_REL = 1
    WAIT_ABS = 2
    GOTO = 3
    IF = 4
    NO_OP = 5
    PUSH_TLM_VAL = 6
    PUSH_PRM = 7
    CONST_CMD = 8
    # stack op directives
    # all of these are handled at the CPP level by one StackOpDirective to save boilerplate
    # you MUST keep them all in between OR and ITRUNC_64_32 inclusive
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
    NOT = 27
    # floating point conversion to signed/unsigned integer,
    # and vice versa
    FPTOSI = 28
    FPTOUI = 29
    SITOFP = 30
    UITOFP = 31
    # integer arithmetic
    ADD = 32
    SUB = 33
    MUL = 34
    UDIV = 35
    SDIV = 36
    UMOD = 37
    SMOD = 38
    # float arithmetic
    FADD = 39
    FSUB = 40
    FMUL = 41
    FDIV = 42
    FPOW = 43
    FLOG = 44
    FMOD = 45
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
    STORE_CONST_OFFSET = 59
    LOAD = 60
    PUSH_VAL = 61
    DISCARD = 62
    MEMCMP = 63
    STACK_CMD = 64
    PUSH_TLM_VAL_AND_TIME = 65
    PUSH_TIME = 66
    SET_FLAG = 67
    GET_FLAG = 68
    GET_FIELD = 69
    PEEK = 70
    STORE = 71


class Directive:
    opcode: ClassVar[DirectiveId] = DirectiveId.INVALID

    def serialize(self) -> bytes:
        arg_bytes = self.serialize_args()

        output = U8Value(self.opcode.value).serialize()
        output += U16Value(len(arg_bytes)).serialize()
        output += arg_bytes

        return output

    def serialize_args(self) -> bytes:
        output = bytes()

        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, FppValue):
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
                if issubclass(arg, FppValue):
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
                if issubclass(t, FppValue):
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

    stack_output_type: ClassVar[type[FppValue]] = FppValue
    """the type this dir pushes to the stack"""


@dataclass
class StackCmdDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STACK_CMD

    args_size: Union[int, StackSizeType]


@dataclass
class MemCompareDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.MEMCMP
    size: Union[int, StackSizeType]


@dataclass
class LoadDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.LOAD

    lvar_offset: Union[int, StackSizeType]
    size: Union[int, StackSizeType]


@dataclass
class IntegerSignedExtend8To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_8_64
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class IntegerSignedExtend16To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_16_64
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class IntegerSignedExtend32To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SIEXT_32_64
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class IntegerZeroExtend8To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_8_64
    stack_output_type: ClassVar[type[FppValue]] = U64Value


@dataclass
class IntegerZeroExtend16To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_16_64
    stack_output_type: ClassVar[type[FppValue]] = U64Value


@dataclass
class IntegerZeroExtend32To64Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ZIEXT_32_64
    stack_output_type: ClassVar[type[FppValue]] = U64Value


@dataclass
class IntegerTruncate64To8Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_8
    stack_output_type: ClassVar[type[FppValue]] = I8Value


@dataclass
class IntegerTruncate64To16Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_16
    stack_output_type: ClassVar[type[FppValue]] = I16Value


@dataclass
class IntegerTruncate64To32Directive(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ITRUNC_64_32
    stack_output_type: ClassVar[type[FppValue]] = I32Value


@dataclass
class AllocateDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.ALLOCATE

    size: Union[int, StackSizeType]


@dataclass
class StoreDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE

    size: Union[int, StackSizeType]


@dataclass
class StoreConstOffsetDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.STORE_CONST_OFFSET

    lvar_offset: Union[int, StackSizeType]
    size: Union[int, StackSizeType]


@dataclass
class DiscardDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.DISCARD

    size: Union[int, StackSizeType]


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
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class SignedModuloDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SMOD
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class UnsignedModuloDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UMOD
    stack_output_type: ClassVar[type[FppValue]] = U64Value


@dataclass
class IntAddDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ADD
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class IntSubtractDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SUB
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class IntMultiplyDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.MUL
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class UnsignedIntDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UDIV
    stack_output_type: ClassVar[type[FppValue]] = U64Value


@dataclass
class SignedIntDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SDIV
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class FloatAddDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FADD
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatSubtractDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FSUB
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatMultiplyDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FMUL
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatExponentDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPOW
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatDivideDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FDIV
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatLogDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLOG
    stack_output_type: ClassVar[type[FppValue]] = F64Value


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
    dir_idx: Union[int, U32Value]


@dataclass
class IfDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.IF
    false_goto_dir_index: Union[int, U32Value]
    """U32: The dir index to go to if the top of stack is false."""


@dataclass
class NoOpDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.NO_OP


@dataclass
class PushTlmValDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PUSH_TLM_VAL
    chan_id: Union[int, FwChanIdType]
    """FwChanIdType: The telemetry channel ID to get."""


@dataclass
class PushPrmDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PUSH_PRM
    prm_id: Union[int, FwPrmIdType]
    """FwPrmIdType: The parameter ID to get the value of."""


@dataclass
class OrDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.OR
    stack_args: ClassVar[list[type[FppValue]]] = [BoolValue, BoolValue]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class AndDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.AND
    stack_args: ClassVar[list[type[FppValue]]] = [BoolValue, BoolValue]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class IntEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.IEQ
    stack_args: ClassVar[list[type[FppValue]]] = [
        Union[I64Value, U64Value],
        Union[I64Value, U64Value],
    ]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class IntNotEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.INE
    stack_args: ClassVar[list[type[FppValue]]] = [
        Union[I64Value, U64Value],
        Union[I64Value, U64Value],
    ]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class UnsignedLessThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ULT
    stack_args: ClassVar[list[type[FppValue]]] = [U64Value, U64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class UnsignedLessThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.ULE
    stack_args: ClassVar[list[type[FppValue]]] = [U64Value, U64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class UnsignedGreaterThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UGT
    stack_args: ClassVar[list[type[FppValue]]] = [U64Value, U64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class UnsignedGreaterThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UGE
    stack_args: ClassVar[list[type[FppValue]]] = [U64Value, U64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class SignedLessThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SLT
    stack_args: ClassVar[list[type[FppValue]]] = [I64Value, I64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class SignedLessThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SLE
    stack_args: ClassVar[list[type[FppValue]]] = [I64Value, I64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class SignedGreaterThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SGT
    stack_args: ClassVar[list[type[FppValue]]] = [I64Value, I64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class SignedGreaterThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SGE
    stack_args: ClassVar[list[type[FppValue]]] = [I64Value, I64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatGreaterThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FGE
    stack_args: ClassVar[list[type[FppValue]]] = [F64Value, F64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatLessThanOrEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLE
    stack_args: ClassVar[list[type[FppValue]]] = [F64Value, F64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatLessThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FLT
    stack_args: ClassVar[list[type[FppValue]]] = [F64Value, F64Value]
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatGreaterThanDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FGT
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FEQ
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatNotEqualDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FNE
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class NotDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.NOT
    stack_output_type: ClassVar[type[FppValue]] = BoolValue


@dataclass
class FloatTruncateDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTRUNC
    stack_output_type: ClassVar[type[FppValue]] = F32Value


@dataclass
class FloatExtendDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPEXT
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatToSignedIntDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTOSI
    stack_output_type: ClassVar[type[FppValue]] = I64Value


@dataclass
class SignedIntToFloatDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.SITOFP
    stack_output_type: ClassVar[type[FppValue]] = F64Value


@dataclass
class FloatToUnsignedIntDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.FPTOUI
    stack_output_type: ClassVar[type[FppValue]] = U64Value


@dataclass
class UnsignedIntToFloatDirective(StackOpDirective):
    opcode: ClassVar[DirectiveId] = DirectiveId.UITOFP
    stack_output_type: ClassVar[type[FppValue]] = F64Value
    # src implied


@dataclass
class ExitDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.EXIT


@dataclass
class GetFieldDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.GET_FIELD
    # pops an offset off the stack
    parent_size: StackSizeType
    member_size: StackSizeType


@dataclass
class PeekDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PEEK


@dataclass
class PushTimeDirective(Directive):
    opcode: ClassVar[DirectiveId] = DirectiveId.PUSH_TIME


for cls in Directive.__subclasses__():
    cls.__old_repr__ = cls.__repr__
    cls.__repr__ = Directive.__repr__

for cls in StackOpDirective.__subclasses__():
    cls.__old_repr__ = cls.__repr__
    cls.__repr__ = StackOpDirective.__repr__


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

UNARY_STACK_OPS: dict[str, dict[type[FppValue], type[StackOpDirective]]] = {
    UnaryStackOp.NOT: {BoolValue: NotDirective},
    UnaryStackOp.IDENTITY: {
        I64Value: NoOpDirective,
        U64Value: NoOpDirective,
        F64Value: NoOpDirective,
    },
    UnaryStackOp.NEGATE: {
        I64Value: IntMultiplyDirective,
        U64Value: IntMultiplyDirective,
        F64Value: FloatMultiplyDirective,
    },
}

BINARY_STACK_OPS: dict[str, dict[type[FppValue], type[StackOpDirective]]] = {
    BinaryStackOp.EXPONENT: {F64Value: FloatExponentDirective},
    BinaryStackOp.MODULUS: {
        I64Value: SignedModuloDirective,
        U64Value: UnsignedModuloDirective,
        F64Value: FloatModuloDirective,
    },
    BinaryStackOp.ADD: {
        I64Value: IntAddDirective,
        U64Value: IntAddDirective,
        F64Value: FloatAddDirective,
    },
    BinaryStackOp.SUBTRACT: {
        I64Value: IntSubtractDirective,
        U64Value: IntSubtractDirective,
        F64Value: FloatSubtractDirective,
    },
    BinaryStackOp.MULTIPLY: {
        I64Value: IntMultiplyDirective,
        U64Value: IntMultiplyDirective,
        F64Value: FloatMultiplyDirective,
    },
    BinaryStackOp.DIVIDE: {
        I64Value: SignedIntDivideDirective,
        U64Value: UnsignedIntDivideDirective,
        F64Value: FloatDivideDirective,
    },
    BinaryStackOp.FLOOR_DIVIDE: {
        I64Value: SignedIntDivideDirective,
        U64Value: UnsignedIntDivideDirective,
        # special case for float floor div
    },
    BinaryStackOp.GREATER_THAN: {
        I64Value: SignedGreaterThanDirective,
        U64Value: UnsignedGreaterThanDirective,
        F64Value: FloatGreaterThanDirective,
    },
    BinaryStackOp.GREATER_THAN_OR_EQUAL: {
        I64Value: SignedGreaterThanOrEqualDirective,
        U64Value: UnsignedGreaterThanOrEqualDirective,
        F64Value: FloatGreaterThanOrEqualDirective,
    },
    BinaryStackOp.LESS_THAN_OR_EQUAL: {
        I64Value: SignedLessThanOrEqualDirective,
        U64Value: UnsignedLessThanOrEqualDirective,
        F64Value: FloatLessThanOrEqualDirective,
    },
    BinaryStackOp.LESS_THAN: {
        I64Value: SignedLessThanDirective,
        U64Value: UnsignedLessThanDirective,
        F64Value: FloatLessThanDirective,
    },
    BinaryStackOp.EQUAL: {
        I64Value: IntEqualDirective,
        U64Value: IntEqualDirective,
        F64Value: FloatEqualDirective,
    },
    BinaryStackOp.NOT_EQUAL: {
        I64Value: IntNotEqualDirective,
        U64Value: IntNotEqualDirective,
        F64Value: FloatNotEqualDirective,
    },
    BinaryStackOp.OR: {BoolValue: OrDirective},
    BinaryStackOp.AND: {BoolValue: AndDirective},
}
