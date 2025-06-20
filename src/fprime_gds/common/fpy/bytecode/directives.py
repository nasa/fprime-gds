from dataclasses import dataclass
import dataclasses
from typing import ClassVar
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.numerical_types import (
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
    WAIT_REL = 1
    WAIT_ABS = 2
    SET_LVAR = 3
    GOTO = 4
    IF = 5
    NO_OP = 6
    GET_TLM = 7
    GET_PRM = 8
    CMD = 9
    SET_REG = 10
    DESER_LVAR_8 = 11
    DESER_LVAR_4 = 12
    DESER_LVAR_2 = 13
    DESER_LVAR_1 = 14
    # binary comparison directives
    # all of these are handled at the CPP level by one BinaryCmpDirective
    # NO REORDER
    # boolean ops
    OR = 15
    AND = 16
    # equality ops
    EQ = 17
    NE = 18
    # unsigned inequalities
    ULT = 19
    ULE = 20
    UGT = 21
    UGE = 22
    # signed inequalities
    SLT = 23
    SLE = 24
    SGT = 25
    SGE = 26
    # END NO REORDER
    # end binary comparison directives
    NOT = 27


class Directive:
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.INVALID

    def serialize(self) -> bytes:
        arg_bytes = self.serialize_args()
        
        output = U8Type(self.opcode.value).serialize()
        output += U16Type(len(arg_bytes)).serialize()
        output += arg_bytes

        return output

    def serialize_args(self) -> bytes:
        raise NotImplementedError("serialize_args not implemented")


@dataclass
class WaitRelDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.WAIT_REL
    seconds: int
    useconds: int

    def serialize_args(self) -> bytes:
        return U32Type(self.seconds).serialize() + U32Type(self.useconds).serialize()


@dataclass
class WaitAbsDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.WAIT_ABS
    wakeup_time: TimeType

    def serialize_args(self) -> bytes:
        return self.wakeup_time.serialize()


@dataclass
class SetLocalVarDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SET_LVAR

    index: int
    """U8: The index of the local variable to set."""
    value: bytes
    """[Fpy.MAX_LOCAL_VARIABLE_BUFFER_SIZE] U8: The value of the local variable."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.index).serialize())
        data.extend(self.value)
        return bytes(data)


@dataclass
class GotoDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.GOTO
    statement_index: int
    """U32: The statement index to execute next."""

    def serialize_args(self) -> bytes:
        return U32Type(self.statement_index).serialize()


@dataclass
class IfDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IF
    conditional_reg: int
    """U8: The register to branch based off of (interpreted as a C++ boolean)."""
    false_goto_stmt_index: int
    """U32: The statement index to go to if the register is false."""

    def serialize_args(self) -> bytes:
        return (
            U8Type(self.conditional_reg).serialize()
            + U32Type(self.false_goto_stmt_index).serialize()
        )


@dataclass
class NoOpDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.NO_OP

    def serialize_args(self) -> bytes:
        return bytes()


@dataclass
class GetTlmDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.GET_TLM
    value_dest_lvar: int
    """U8: The local variable to store the telemetry value in."""
    time_dest_lvar: int
    """U8: The local variable to store the telemetry time in."""
    chan_id: int
    """FwChanIdType: The telemetry channel ID to get."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.value_dest_lvar).serialize())
        data.extend(U8Type(self.time_dest_lvar).serialize())
        data.extend(FwChanIdType(self.chan_id).serialize())
        return bytes(data)


@dataclass
class GetPrmDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.GET_PRM
    dest_lvar_index: int
    """U8: The local variable to store the parameter value in."""
    prm_id: int
    """FwPrmIdType: The parameter ID to get the value of."""

    def serialize_args(self) -> bytes:
        return (
            U8Type(self.dest_lvar_index).serialize()
            + FwPrmIdType(self.prm_id).serialize()
        )


@dataclass
class CmdDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.CMD
    op_code: int
    """FwOpcodeType: The opcode of the command."""
    arg_buf: bytes
    """[Fpy.MAX_LOCAL_VARIABLE_BUFFER_SIZE] U8: The argument buffer of the command."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(FwOpcodeType(self.op_code).serialize())
        data.extend(self.arg_buf)
        return bytes(data)


@dataclass
class _DeserLocalVarDirective(Directive):
    """
    Deserializes up to 8 bytes from a local variable into a register.
    """

    src_lvar_idx: int
    """U8: The local variable to deserialize from."""
    src_offset: int
    """FwSizeType: The starting offset to deserialize from."""
    dest_reg: int
    """U8: The destination register to deserialize into."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.src_lvar_idx).serialize())
        data.extend(FwSizeType(self.src_offset).serialize())
        data.extend(U8Type(self.dest_reg).serialize())
        return bytes(data)


class DeserLocalVar8Directive(_DeserLocalVarDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_LVAR_8


class DeserLocalVar4Directive(_DeserLocalVarDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_LVAR_4


class DeserLocalVar2Directive(_DeserLocalVarDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_LVAR_2


class DeserLocalVar1Directive(_DeserLocalVarDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_LVAR_1


@dataclass
class SetRegDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SET_REG

    dest: int
    """U8: The register to store the value in."""
    value: int
    """I64: The value to store in the register."""

    def serialize_args(self) -> bytes:
        return U8Type(self.dest).serialize() + I64Type(self.value).serialize()


@dataclass
class _BinaryCmpDirective(Directive):
    lhs: int
    """U8: The left-hand side register for comparison."""
    rhs: int
    """U8: The right-hand side register for comparison."""
    res: int
    """U8: The destination register for the boolean result."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.lhs).serialize())
        data.extend(U8Type(self.rhs).serialize())
        data.extend(U8Type(self.res).serialize())
        return bytes(data)


class OrDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.OR


class AndDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.AND


class EqualDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.EQ


class NotEqualDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.NE


class UnsignedLessThanDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ULT


class UnsignedLessThanOrEqualDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ULE


class UnsignedGreaterThanDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UGT


class UnsignedGreaterThanOrEqualDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UGE


class SignedLessThanDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SLT


class SignedLessThanOrEqualDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SLE


class SignedGreaterThanDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SGT


class SignedGreaterThanOrEqualDirective(_BinaryCmpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SGE


@dataclass
class NotDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.NOT
    src: int
    res: int

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.src).serialize())
        data.extend(U8Type(self.res).serialize())
        return bytes(data)


EQUALITY_DIRECTIVES: dict[str, type[_BinaryCmpDirective]] = {
    "==": EqualDirective,
    "!=": NotEqualDirective,
}


SIGNED_INEQUALITY_DIRECTIVES: dict[str, type[_BinaryCmpDirective]] = {
    ">": SignedGreaterThanDirective,
    "<": SignedLessThanDirective,
    ">=": SignedGreaterThanOrEqualDirective,
    "<=": SignedLessThanOrEqualDirective,
}
UNSIGNED_INEQUALITY_DIRECTIVES: dict[str, type[_BinaryCmpDirective]] = {
    ">": UnsignedGreaterThanDirective,
    "<": UnsignedLessThanDirective,
    ">=": UnsignedGreaterThanOrEqualDirective,
    "<=": UnsignedLessThanOrEqualDirective,
}

BINARY_COMPARISON_DIRECTIVES = {}
BINARY_COMPARISON_DIRECTIVES.update(EQUALITY_DIRECTIVES)
BINARY_COMPARISON_DIRECTIVES.update(SIGNED_INEQUALITY_DIRECTIVES)
BINARY_COMPARISON_DIRECTIVES.update(UNSIGNED_INEQUALITY_DIRECTIVES)