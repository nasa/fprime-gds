from dataclasses import astuple, dataclass
from pathlib import Path
import struct
from typing import ClassVar
import zlib
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I64Type,
)
from fprime.common.models.serialize.bool_type import BoolType
from enum import Enum

FwSizeType = U64Type
FwChanIdType = U32Type
FwPrmIdType = U32Type
FwOpcodeType = U32Type

MAX_SERIALIZABLE_REGISTER_SIZE = 512 - 4 - 4


class DirectiveOpcode(Enum):
    INVALID = 0
    WAIT_REL = 1
    WAIT_ABS = 2
    SET_SER_REG = 3
    GOTO = 4
    IF = 5
    NO_OP = 6
    GET_TLM = 7
    GET_PRM = 8
    CMD = 9
    SET_REG = 10
    DESER_SER_REG_8 = 11
    DESER_SER_REG_4 = 12
    DESER_SER_REG_2 = 13
    DESER_SER_REG_1 = 14
    # binary reg op directives
    # all of these are handled at the CPP level by one BinaryRegOpDirective
    # boolean ops
    OR = 15
    AND = 16
    # integer equalities
    IEQ = 17
    INE = 18
    # unsigned integer inequalities
    ULT = 19
    ULE = 20
    UGT = 21
    UGE = 22
    # signed integer inequalities
    SLT = 23
    SLE = 24
    SGT = 25
    SGE = 26
    # floating point equalities
    FEQ = 27
    FNE = 28
    # floating point inequalities
    FLT = 29
    FLE = 30
    FGT = 31
    FGE = 32
    # end binary reg op directives

    # unary reg op dirs
    NOT = 33
    # floating point extension and truncation
    FPEXT = 34
    FPTRUNC = 35
    # floating point conversion to signed/unsigned integer,
    # and vice versa
    FPTOSI = 36
    FPTOUI = 37
    SITOFP = 38
    UITOFP = 39
    # end unary reg op dirs

    EXIT = 40


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
class SetSerRegDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SET_SER_REG

    index: int
    """U8: The index of the local variable to set."""
    value: bytes
    """[Fpy.MAX_SERIALIZABLE_REGISTER_SIZE] U8: The value of the local variable."""

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
    value_dest_sreg: int
    """U8: The local variable to store the telemetry value in."""
    time_dest_sreg: int
    """U8: The local variable to store the telemetry time in."""
    chan_id: int
    """FwChanIdType: The telemetry channel ID to get."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.value_dest_sreg).serialize())
        data.extend(U8Type(self.time_dest_sreg).serialize())
        data.extend(FwChanIdType(self.chan_id).serialize())
        return bytes(data)


@dataclass
class GetPrmDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.GET_PRM
    dest_sreg_index: int
    """U8: The local variable to store the parameter value in."""
    prm_id: int
    """FwPrmIdType: The parameter ID to get the value of."""

    def serialize_args(self) -> bytes:
        return (
            U8Type(self.dest_sreg_index).serialize()
            + FwPrmIdType(self.prm_id).serialize()
        )


@dataclass
class CmdDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.CMD
    op_code: int
    """FwOpcodeType: The opcode of the command."""
    arg_buf: bytes
    """[Fpy.MAX_SERIALIZABLE_REGISTER_SIZE] U8: The argument buffer of the command."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(FwOpcodeType(self.op_code).serialize())
        data.extend(self.arg_buf)
        return bytes(data)


@dataclass
class _DeserSerRegDirective(Directive):
    """
    Deserializes up to 8 bytes from a local variable into a register.
    """

    src_sreg_idx: int
    """U8: The local variable to deserialize from."""
    src_offset: int
    """FwSizeType: The starting offset to deserialize from."""
    dest_reg: int
    """U8: The destination register to deserialize into."""

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.src_sreg_idx).serialize())
        data.extend(FwSizeType(self.src_offset).serialize())
        data.extend(U8Type(self.dest_reg).serialize())
        return bytes(data)


class DeserSerReg8Directive(_DeserSerRegDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_SER_REG_8


class DeserSerReg4Directive(_DeserSerRegDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_SER_REG_4


class DeserSerReg2Directive(_DeserSerRegDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_SER_REG_2


class DeserSerReg1Directive(_DeserSerRegDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.DESER_SER_REG_1


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
class _BinaryRegOpDirective(Directive):
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


class OrDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.OR


class AndDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.AND


class IntEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.IEQ


class IntNotEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.INE


class UnsignedLessThanDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ULT


class UnsignedLessThanOrEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.ULE


class UnsignedGreaterThanDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UGT


class UnsignedGreaterThanOrEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UGE


class SignedLessThanDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SLT


class SignedLessThanOrEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SLE


class SignedGreaterThanDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SGT


class SignedGreaterThanOrEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SGE


class FloatGreaterThanOrEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FGE


class FloatLessThanOrEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FLE


class FloatLessThanDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FLT


class FloatGreaterThanDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FGT


class FloatEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FEQ


class FloatNotEqualDirective(_BinaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FNE


@dataclass
class _UnaryRegOpDirective(Directive):
    src: int
    res: int

    def serialize_args(self) -> bytes:
        data = bytearray()
        data.extend(U8Type(self.src).serialize())
        data.extend(U8Type(self.res).serialize())
        return bytes(data)


@dataclass
class NotDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.NOT


@dataclass
class FloatTruncateDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPTRUNC


@dataclass
class FloatExtendDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPEXT


@dataclass
class FloatToSignedIntDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPTOSI


@dataclass
class SignedIntToFloatDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.SITOFP


@dataclass
class FloatToUnsignedIntDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.FPTOUI


@dataclass
class UnsignedIntToFloatDirective(_UnaryRegOpDirective):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.UITOFP


@dataclass
class ExitDirective(Directive):
    opcode: ClassVar[DirectiveOpcode] = DirectiveOpcode.EXIT
    success: bool

    def serialize_args(self):
        return BoolType(self.success).serialize()


INT_EQUALITY_DIRECTIVES: dict[str, type[_BinaryRegOpDirective]] = {
    "==": IntEqualDirective,
    "!=": IntNotEqualDirective,
}

FLOAT_EQUALITY_DIRECTIVES: dict[str, type[_BinaryRegOpDirective]] = {
    "==": FloatEqualDirective,
    "!=": FloatNotEqualDirective,
}


INT_SIGNED_INEQUALITY_DIRECTIVES: dict[str, type[_BinaryRegOpDirective]] = {
    ">": SignedGreaterThanDirective,
    "<": SignedLessThanDirective,
    ">=": SignedGreaterThanOrEqualDirective,
    "<=": SignedLessThanOrEqualDirective,
}
INT_UNSIGNED_INEQUALITY_DIRECTIVES: dict[str, type[_BinaryRegOpDirective]] = {
    ">": UnsignedGreaterThanDirective,
    "<": UnsignedLessThanDirective,
    ">=": UnsignedGreaterThanOrEqualDirective,
    "<=": UnsignedLessThanOrEqualDirective,
}
FLOAT_INEQUALITY_DIRECTIVES: dict[str, type[_BinaryRegOpDirective]] = {
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
