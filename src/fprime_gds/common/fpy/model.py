from dataclasses import dataclass
from enum import Enum
import inspect
import struct
from fprime_gds.common.fpy.bytecode.directives import (
    AllocateStackDirective,
    AndDirective,
    ConstCmdDirective,
    Directive,
    ExitDirective,
    GotoDirective,
    PopDiscardDirective,
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
)

WORD_SIZE = 8
# store return addr and prev stack frame offset in stack frame header
STACK_FRAME_HEADER_SIZE = 2 * WORD_SIZE


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
            print("stack", len(self.stack))
            for byte in range(0, len(self.stack)):

                print(
                    self.stack[byte],
                    end=" ",
                )
            print()
            if result != DirectiveErrorCode.NO_ERROR:
                return result
        return DirectiveErrorCode.NO_ERROR

    def push(self, val: int | float | bytes | bytearray | bool, signed=True):
        if isinstance(val, (bytes | bytearray)):
            self.stack += val
        elif isinstance(val, bool):
            self.push(1 if val else 0)
        elif isinstance(val, float):
            self.push(struct.pack(">d", val))
        else:
            assert isinstance(val, int), val
            self.stack += val.to_bytes(length=8, byteorder="big", signed=signed)

    def pop(self, type=int, signed=True, size=64) -> int | float | bytearray:
        """pops one word off the stack and interprets it as an int or float, of
        the specified signedness (if applicable) and bit width (if applicable)"""
        last_word = self.stack[-WORD_SIZE:]
        self.stack = self.stack[:-WORD_SIZE]
        if type == int:
            if signed:
                return struct.unpack(">q", last_word)[0]
            return struct.unpack(">Q", last_word)[0]
        elif type == float:
            if size == 64:
                return struct.unpack(">d", last_word)[0]
            assert size == 32, size
            return struct.unpack(">f", last_word[:4])[0]
        elif type == bytes or type == bytearray:
            assert size == 64, size
            # compiler knows best. always let them have the last word ;)
            return last_word
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
        value = self.stack[self.stack_frame_start + dir.lvar_offset : (self.stack_frame_start + dir.lvar_offset + dir.size)]
        if len(value) < WORD_SIZE:
            # pad to make it a word
            value = bytearray(0 for i in range(0, WORD_SIZE - len(value))) + value
        self.push(value)

    def handle_store(self, dir: StoreDirective):
        if len(self.stack) < dir.size:
            return DirectiveErrorCode.STACK_UNDERFLOW

        if dir.lvar_offset + self.stack_frame_start + dir.size > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        # get the last `dir.size` bytes of the stack
        value = self.stack[-dir.size:]
        print(len(value))
        # remove them from top of stack
        self.stack = self.stack[:-dir.size]
        # put into lvar array at the given offset
        for i in range(0, len(value)):
            self.stack[dir.lvar_offset + self.stack_frame_start + i] = value[i]

    def handle_push_val(self, dir: PushValDirective):
        if len(self.stack) + WORD_SIZE > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW
        self.push(dir.val)

    def handle_wait_rel(self, dir: WaitRelDirective):
        print("wait rel", dir)

    def handle_wait_abs(self, dir: WaitAbsDirective):
        print("wait abs", dir)

    def handle_const_cmd(self, dir: ConstCmdDirective):
        print("cmd", dir)

    def handle_goto(self, dir: GotoDirective):
        if dir.dir_idx > len(self.dirs):
            return DirectiveErrorCode.DIR_OUT_OF_BOUNDS
        self.next_dir_idx = dir.dir_idx

    def handle_if(self, dir: IfDirective):
        if dir.false_goto_dir_index > len(self.dirs):
            return DirectiveErrorCode.DIR_OUT_OF_BOUNDS
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        conditional = self.pop()
        print("conditional", conditional)
        if conditional == 0:
            self.next_dir_idx = dir.false_goto_dir_index

    def handle_store_tlm_val(self, dir: StoreTlmValDirective):
        whole_value: bytearray = self.tlm_db.get(dir.chan_id, None)
        if whole_value is None:
            return DirectiveErrorCode.TLM_NOT_FOUND

        if self.stack_frame_start + dir.lvar_offset + len(whole_value) > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        self.stack[self.stack_frame_start + dir.lvar_offset:(self.stack_frame_start + dir.lvar_offset + len(whole_value))] = whole_value

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
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(signed=False)
        lhs = self.pop(signed=False)
        self.push(rhs != 0 or lhs != 0)

    def handle_and(self, dir: AndDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(signed=False)
        lhs = self.pop(signed=False)
        self.push(rhs != 0 and lhs != 0)

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
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop()
        if val != 0:
            self.push(False)
        else:
            self.push(True)

    def handle_fpext(self, dir: FloatExtendDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val_32 = self.pop(type=float, size=32)
        print("fext", val_32)
        self.push(val_32)

    def handle_fptrunc(self, dir: FloatTruncateDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val_64 = self.pop(type=float, size=64)
        val_32_bytes = struct.pack(">f", val_64)
        # pad with zeroes
        val_32_bytes += bytes((0, 0, 0, 0))
        self.push(val_32_bytes)

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
        self.push(lhs + rhs)

    def handle_isub(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs - rhs)

    def handle_imul(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs * rhs)

    def handle_idiv(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop()
        lhs = self.pop()
        self.push(lhs // rhs)

    def handle_fadd(self, dir: IntAddDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs + rhs)

    def handle_isub(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs - rhs)

    def handle_imul(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs * rhs)

    def handle_idiv(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        rhs = self.pop(type=float)
        lhs = self.pop(type=float)
        self.push(lhs / rhs)

    def handle_exit(self, dir: ExitDirective):
        if dir.success:
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
