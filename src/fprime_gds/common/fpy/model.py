from enum import Enum
import inspect
import math
import struct
from fprime_gds.common.fpy.bytecode.directives import (
    AllocateStackDirective,
    AndDirective,
    ConstCmdDirective,
    Directive,
    ExitDirective,
    FloatAddDirective,
    FloatDivideDirective,
    FloatExponentDirective,
    FloatFloorDivideDirective,
    FloatMultiplyDirective,
    FloatSubtractDirective,
    GotoDirective,
    IntDivideDirective,
    IntModuloDirective,
    IntMultiplyDirective,
    IntegerTruncateDirective,
    LogDirective,
    PopDiscardDirective,
    SignedIntegerExtendDirective,
    StackCmdDirective,
    StorePrmDirective,
    StoreTlmValDirective,
    IfDirective,
    IntAddDirective,
    IntEqualDirective,
    IntNotEqualDirective,
    IntSubtractDirective,
    LoadDirective,
    NoOpDirective,
    NotDirective,
    OrDirective,
    PushValDirective,
    StoreDirective,
    UnsignedLessThanDirective,
    UnsignedLessThanOrEqualDirective,
    UnsignedGreaterThanDirective,
    UnsignedGreaterThanOrEqualDirective,
    SignedGreaterThanDirective,
    SignedGreaterThanOrEqualDirective,
    SignedIntToFloatDirective,
    SignedLessThanDirective,
    SignedLessThanOrEqualDirective,
    UnsignedIntToFloatDirective,
    FloatEqualDirective,
    FloatExtendDirective,
    FloatGreaterThanDirective,
    FloatGreaterThanOrEqualDirective,
    FloatLessThanDirective,
    FloatLessThanOrEqualDirective,
    FloatNotEqualDirective,
    FloatToSignedIntDirective,
    FloatToUnsignedIntDirective,
    FloatTruncateDirective,
    WaitAbsDirective,
    WaitRelDirective,
    IntegerZeroExtendDirective,
)

WORD_SIZE = 8
# store return addr and prev stack frame offset in stack frame header
STACK_FRAME_HEADER_SIZE = 2 * WORD_SIZE
MAX_INT64 = 2**63 - 1
MIN_INT64 = -2**63
MASK_64_BIT = 2**64 - 1

def overflow_check(val: int) -> int:
    masked_val = val & MASK_64_BIT
    if masked_val > MAX_INT64:
        return masked_val - 2**64
    return masked_val

class DirectiveErrorCode(Enum):
    NO_ERROR = 0
    DIR_OUT_OF_BOUNDS = 1
    TLM_GET_NOT_CONNECTED = 2
    TLM_NOT_FOUND = 3
    TLM_ACCESS_OUT_OF_BOUNDS = 4
    PRM_GET_NOT_CONNECTED = 5
    PRM_NOT_FOUND = 6
    PRM_ACCESS_OUT_OF_BOUNDS = 7
    CMD_SERIALIZE_FAILURE = 8
    DELIBERATE_FAILURE = 9
    STACK_OVERFLOW = 10
    STACK_UNDERFLOW = 11
    INVALID_ARGUMENT = 12
    DIVIDE_BY_ZERO = 13


class FpySequencerModel:

    def __init__(self, stack_size=4096) -> None:
        self.stack = bytearray()
        self.max_stack_size = stack_size
        self.stack_frame_start = 0

        self.dirs: list[Directive] = None
        self.next_dir_idx = 0
        self.tlm_db: dict[int, bytearray] = {}
        self.prm_db: dict[int, bytearray] = {}

    def reset(self):
        self.stack = bytearray()
        self.stack_frame_start = 0

        self.dirs: list[Directive] = None
        self.next_dir_idx = 0
        self.tlm_db: dict[int, bytearray] = {}
        self.prm_db: dict[int, bytearray] = {}

    def dispatch(self, dir: Directive) -> DirectiveErrorCode:
        opcode = dir.opcode
        opcode_name = opcode.name

        handler_fn = None
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if not name.startswith("handle"):
                # not a dir handler
                continue
            signature = inspect.signature(func)
            params = list(signature.parameters.values())
            assert len(params) == 2
            assert params[1].annotation is not None
            if isinstance(dir, params[1].annotation):
                handler_fn = func
                break

        if handler_fn is None:
            raise NotImplementedError(opcode_name + " not implemented")

        # otherwise call the handler
        ret = handler_fn(self, dir)
        if ret is None:
            return DirectiveErrorCode.NO_ERROR
        return ret

    def run(self, dirs: list[Directive], tlm: dict[int, bytearray]):
        self.reset()
        self.dirs = dirs
        self.tlm_db = tlm
        # begin the sequence at dir 0
        print("stack", len(self.stack))
        for byte in range(0, len(self.stack)):

            print(
                type(self.stack[byte]),
                end=" ",
            )
        print()
        while self.next_dir_idx < len(self.dirs):
            next_dir = self.dirs[self.next_dir_idx]
            print(f"{self.next_dir_idx}:", next_dir)
            self.next_dir_idx += 1
            result = self.dispatch(next_dir)
            if result != DirectiveErrorCode.NO_ERROR:
                return result
            print("stack", len(self.stack))
            for byte in range(0, len(self.stack)):

                print(
                    self.stack[byte],
                    end=" ",
                )
            print()
        return DirectiveErrorCode.NO_ERROR

    def get_int_fmt_str(self, size: int, signed: bool) -> str:
        fmt_char = None
        if size == 1:
            fmt_char = "b"
        elif size == 2:
            fmt_char = "h"
        elif size == 4:
            fmt_char = "i"
        elif size == 8:
            fmt_char = "q"
        else:
            assert False, size
        if not signed:
            fmt_char = fmt_char.upper()

        return ">" + fmt_char

    def push(
        self, val: int | float | bytes | bytearray | bool, signed=True, size=WORD_SIZE
    ):
        if isinstance(val, (bytes | bytearray)):
            self.stack += val
        elif isinstance(val, bool):
            # push a byte onto stack
            self.push(b"\xff" if val else b"\x00")
        elif isinstance(val, float):
            self.push(struct.pack(">d", val))
        else:
            assert isinstance(val, int), val
            fmt_str = self.get_int_fmt_str(size, signed)
            serialized_val = struct.pack(fmt_str, val)
            self.stack += serialized_val

    def pop(self, type=int, signed=True, size=WORD_SIZE) -> int | float | bytearray:
        """pops one word off the stack and interprets it as an int or float, of
        the specified signedness (if applicable) and bit width (if applicable)"""
        value = self.stack[-size:]
        self.stack = self.stack[:-size]
        if type == int:
            fmt_str = self.get_int_fmt_str(size, signed)
            return struct.unpack(fmt_str, value)[0]
        elif type == float:
            if size == 8:
                return struct.unpack(">d", value)[0]
            assert size == 4, size
            return struct.unpack(">f", value)[0]
        elif type == bytes or type == bytearray:
            assert size == 8, size
            # compiler knows best. always let them have the last word ;)
            return value
        elif type == bool:
            assert size == 1, size
            return bool(value[0])
        else:
            assert False, type

    def handle_allocate_stack(self, dir: AllocateStackDirective):
        if len(self.stack) + dir.size > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        self.stack += bytearray(0 for i in range(0, dir.size))

    def handle_no_op(self, dir: NoOpDirective):
        pass

    def handle_pop_discard(self, dir: PopDiscardDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.pop()

    def handle_load(self, dir: LoadDirective):
        if len(self.stack) + dir.size > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        if dir.lvar_offset + self.stack_frame_start + dir.size > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        # grab a word beginning at lvar start and put on operand stack
        value = self.stack[
            self.stack_frame_start
            + dir.lvar_offset : (self.stack_frame_start + dir.lvar_offset + dir.size)
        ]
        self.push(value)

    def handle_store(self, dir: StoreDirective):
        if len(self.stack) < dir.size:
            return DirectiveErrorCode.STACK_UNDERFLOW

        if dir.lvar_offset + self.stack_frame_start + dir.size > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        # get the last `dir.size` bytes of the stack
        value = self.stack[-dir.size :]
        # remove them from top of stack
        self.stack = self.stack[: -dir.size]
        # put into lvar array at the given offset
        for i in range(0, len(value)):
            self.stack[dir.lvar_offset + self.stack_frame_start + i] = value[i]

    def handle_push_val(self, dir: PushValDirective):
        if len(self.stack) + WORD_SIZE > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW
        self.push(dir.val)

    def handle_wait_rel(self, dir: WaitRelDirective):
        if len(self.stack) < 8:
            return DirectiveErrorCode.STACK_UNDERFLOW

        seconds = self.pop(type=float)

        print("wait rel", seconds)

    def handle_wait_abs(self, dir: WaitAbsDirective):
        if len(self.stack) < 11:
            return DirectiveErrorCode.STACK_UNDERFLOW
        useconds = self.pop(size=4)
        seconds = self.pop(size=4)
        time_context = self.pop(size=1)
        time_base = self.pop(size=2)

        print("wait abs", time_context, time_base, seconds, useconds)

    def handle_const_cmd(self, dir: ConstCmdDirective):
        print("cmd opcode", dir.cmd_opcode, "args", dir.args)

    def handle_stack_cmd(self, dir: StackCmdDirective):
        if len(self.stack) < dir.size:
            return DirectiveErrorCode.STACK_UNDERFLOW

        cmd = self.stack[-dir.size :]
        self.stack = self.stack[: -dir.size]

        print("cmd opcode", cmd[:4], "args", cmd[4:])

    def handle_goto(self, dir: GotoDirective):
        if dir.dir_idx > len(self.dirs):
            return DirectiveErrorCode.DIR_OUT_OF_BOUNDS
        self.next_dir_idx = dir.dir_idx

    def handle_if(self, dir: IfDirective):
        if dir.false_goto_dir_index > len(self.dirs):
            return DirectiveErrorCode.DIR_OUT_OF_BOUNDS
        if len(self.stack) < 1:
            return DirectiveErrorCode.STACK_UNDERFLOW
        conditional = self.pop(type=bool, size=1)
        print("conditional", conditional)
        if not conditional:
            self.next_dir_idx = dir.false_goto_dir_index

    def handle_store_tlm_val(self, dir: StoreTlmValDirective):
        whole_value: bytearray = self.tlm_db.get(dir.chan_id, None)
        if whole_value is None:
            return DirectiveErrorCode.TLM_NOT_FOUND

        if (
            self.stack_frame_start + dir.lvar_offset + len(whole_value)
            > self.max_stack_size
        ):
            return DirectiveErrorCode.STACK_OVERFLOW

        self.stack[
            self.stack_frame_start
            + dir.lvar_offset : (
                self.stack_frame_start + dir.lvar_offset + len(whole_value)
            )
        ] = whole_value

    def handle_push_prm(self, dir: StorePrmDirective):
        whole_value: bytearray = self.prm_db.get(dir.prm_id, None)
        if whole_value is None:
            return DirectiveErrorCode.PRM_NOT_FOUND

        if dir.offset + dir.size > len(whole_value):
            return DirectiveErrorCode.PRM_ACCESS_OUT_OF_BOUNDS

        if dir.size > 8:
            return DirectiveErrorCode.STACK_MISALIGNMENT

        value = whole_value[dir.offset : (dir.offset + dir.size)]
        # pad value up to 8 bytes
        padded_value = value.extend(0 for i in range(0, 8 - len(value)))

        self.push(padded_value)

    def handle_or(self, dir: OrDirective):
        if len(self.stack) < 2:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=bool, size=1)
        lhs = self.pop(type=bool, size=1)
        self.push(lhs or rhs)

    def handle_and(self, dir: AndDirective):
        if len(self.stack) < 2:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=bool, size=1)
        lhs = self.pop(type=bool, size=1)
        self.push(lhs and rhs)

    def handle_ieq(self, dir: IntEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() == self.pop())

    def handle_ine(self, dir: IntNotEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() != self.pop())

    def handle_ult(self, dir: UnsignedLessThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(signed=False)
        lhs = self.pop(signed=False)
        self.push(lhs < rhs)

    def handle_ule(self, dir: UnsignedLessThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(signed=False)
        lhs = self.pop(signed=False)
        self.push(lhs <= rhs)

    def handle_ugt(self, dir: UnsignedGreaterThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(signed=False)
        lhs = self.pop(signed=False)
        self.push(lhs > rhs)

    def handle_uge(self, dir: UnsignedGreaterThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(signed=False)
        lhs = self.pop(signed=False)
        self.push(lhs >= rhs)

    def handle_slt(self, dir: SignedLessThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        print(lhs, "<", rhs, lhs < rhs)
        self.push(lhs < rhs)

    def handle_sle(self, dir: SignedLessThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs <= rhs)

    def handle_sgt(self, dir: SignedGreaterThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs > rhs)

    def handle_sge(self, dir: SignedGreaterThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs >= rhs)

    def handle_feq(self, dir: FloatEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(type=float) == self.pop(type=float))

    def handle_fne(self, dir: FloatNotEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(type=float) != self.pop(type=float))

    def handle_flt(self, dir: FloatLessThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs < rhs)

    def handle_fle(self, dir: FloatLessThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs <= rhs)

    def handle_fgt(self, dir: FloatGreaterThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs > rhs)

    def handle_fge(self, dir: FloatGreaterThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs >= rhs)

    def handle_not(self, dir: NotDirective):
        if len(self.stack) < 1:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop(type=bool, size=1)
        if val:
            self.push(False)
        else:
            self.push(True)

    def handle_fpext(self, dir: FloatExtendDirective):
        if len(self.stack) < 4:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val_bytes = self.stack[-4:]
        self.stack = self.stack[:-4]
        val_as_float = struct.unpack(">f", val_bytes)[0]

        self.push(val_as_float)

    def handle_siext(self, dir: SignedIntegerExtendDirective):
        if len(self.stack) < dir.from_size:
            return DirectiveErrorCode.STACK_UNDERFLOW
        if len(self.stack) - dir.from_size + dir.to_size > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        # make sure it's from/to a valid size
        if dir.from_size not in (1, 2, 4, 8) or dir.to_size not in (1, 2, 4, 8):
            return DirectiveErrorCode.INVALID_ARGUMENT

        # pop val off stack
        val = self.pop(type=int, signed=True, size=dir.from_size)

        self.push(val, signed=True, size=dir.to_size)

    def handle_ziext(self, dir: IntegerZeroExtendDirective):
        if len(self.stack) < dir.from_size:
            return DirectiveErrorCode.STACK_UNDERFLOW
        if len(self.stack) - dir.from_size + dir.to_size > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        # make sure it's from/to a valid size
        if dir.from_size not in (1, 2, 4, 8) or dir.to_size not in (1, 2, 4, 8):
            return DirectiveErrorCode.INVALID_ARGUMENT

        # pop val off stack
        val_as_int = self.pop(type=int, signed=False, size=dir.from_size)

        self.push(val_as_int, signed=False, size=dir.to_size)

    def handle_fptrunc(self, dir: FloatTruncateDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val_64 = self.pop(type=float)
        val_32_bytes = struct.pack(">f", val_64)
        # pad with zeroes
        val_32_bytes += bytes((0, 0, 0, 0))
        self.push(val_32_bytes)

    def handle_itrunc(self, dir: IntegerTruncateDirective):
        if len(self.stack) < dir.from_size:
            return DirectiveErrorCode.STACK_UNDERFLOW

        val = self.pop(type=int, size=dir.from_size)
        self.push(val, size=dir.to_size)

    def handle_fptosi(self, dir: FloatToSignedIntDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop(type=float)
        self.push(val)

    def handle_fptoui(self, dir: FloatToUnsignedIntDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop(type=float)
        self.push(val)

    def handle_sitofp(self, dir: SignedIntToFloatDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop()
        print(val, "to", float(val))
        self.push(float(val))

    def handle_uitofp(self, dir: UnsignedIntToFloatDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop(signed=False)
        self.push(float(val))


    def handle_iadd(self, dir: IntAddDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(overflow_check(lhs + rhs))

    def handle_isub(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(overflow_check(lhs - rhs))

    def handle_imul(self, dir: IntMultiplyDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(overflow_check(lhs * rhs))

    def handle_idiv(self, dir: IntDivideDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()

        if lhs == 0:
            # C++ behavior for division by zero is undefined.
            return DirectiveErrorCode.DIVIDE_BY_ZERO

        # Special overflow case: MIN_INT64 / -1
        # This results in MAX_INT64 + 1, which overflows to MIN_INT64 in C++.
        if rhs == MIN_INT64 and lhs == -1:
            return MIN_INT64 # C++ specific overflow behavior

        # Perform division, truncating towards zero
        # This is different from Python's // which floors.
        python_quotient = int(rhs / lhs)

        # For division, overflow detection isn't typically done with the mask on the result
        # because the quotient itself is within range, except for the MIN_INT64 / -1 case.
        # The result of division will usually fit within int64_t's range if the divisor isn't 0.
        return python_quotient

    def handle_fadd(self, dir: FloatAddDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs + rhs)

    def handle_fsub(self, dir: FloatSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs - rhs)

    def handle_fmul(self, dir: FloatMultiplyDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs * rhs)

    def handle_fdiv(self, dir: FloatDivideDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs / rhs)

    def handle_imod(self, dir: IntModuloDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs % rhs)

    def handle_fpow(self, dir: FloatExponentDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs**rhs)

    def handle_log(self, dir: LogDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        operand = self.pop(type=float)
        self.push(math.log(operand))

    def handle_float_floor_div(self, dir: FloatFloorDivideDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs // rhs)

    def handle_exit(self, dir: ExitDirective):
        success = self.pop(type=bool, size=1)
        if success:
            self.next_dir_idx = len(self.dirs)
        else:
            return DirectiveErrorCode.DELIBERATE_FAILURE


def main():
    model = FpySequencerModel()

    seq = [
        PushValDirective(123123),
        PushValDirective(1),
        IntAddDirective(),
        PushValDirective(123124),
        IntEqualDirective(),
        IfDirective(7),
        ExitDirective(True),
        ExitDirective(False),
    ]

    ret = model.run(seq)
    if ret != DirectiveErrorCode.NO_ERROR:
        print("seq failed", ret)


if __name__ == "__main__":
    main()
