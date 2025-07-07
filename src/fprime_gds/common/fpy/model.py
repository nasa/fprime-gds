from dataclasses import dataclass
from enum import Enum
import inspect
import struct
from fprime_gds.common.fpy.bytecode.directives import (
    AndDirective,
    ConstCmdDirective,
    Directive,
    ExitDirective,
    GotoDirective,
    PushPrmDirective,
    PushTlmValDirective,
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


@dataclass
class Sequence:
    lvar_count: int

    dirs: list[Directive]


class FpySequencerModel:

    def __init__(self, stack_size=4096) -> None:
        self.stack = bytearray()
        self.max_stack_size = stack_size
        self.stack_frame_start = 0

        self.seq: Sequence = None
        self.next_dir_idx = 0
        self.tlm_db: dict[int, bytearray] = {}
        self.prm_db: dict[int, bytearray] = {}

    def reset(self):
        self.stack = bytearray()
        self.stack_frame_start = 0

        self.seq: Sequence = None
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

    def run(self, seq: Sequence):
        self.reset()
        self.seq = seq
        if seq.lvar_count * WORD_SIZE + STACK_FRAME_HEADER_SIZE > self.max_stack_size:
            # can't even run the sequence
            return DirectiveErrorCode.STACK_OVERFLOW
        # begin the sequence at dir 0
        # push empty values for all its lvars
        for i in range(0, seq.lvar_count):
            self.push(0)
        while self.next_dir_idx < len(self.seq.dirs):
            next_dir = self.seq.dirs[self.next_dir_idx]
            print("stack", len(self.stack))
            for word in range(0, len(self.stack) // WORD_SIZE):
                print(
                    struct.unpack(
                        ">q",
                        self.stack[(word * WORD_SIZE) : (word * WORD_SIZE) + WORD_SIZE],
                    )[0],
                    end=" ",
                )
            print()
            print(f"{self.next_dir_idx}:", next_dir)
            self.next_dir_idx += 1
            result = self.dispatch(next_dir)
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
            # compiler knows best. always let them have the last word ;)
            return last_word
        else:
            assert False, type


    def handle_no_op(self, dir: NoOpDirective):
        pass

    def handle_load(self, dir: LoadDirective):
        if len(self.stack) + WORD_SIZE > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        if dir.lvar_idx * WORD_SIZE + self.stack_frame_start > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        lvar_start = (
            self.stack_frame_start + STACK_FRAME_HEADER_SIZE + dir.lvar_idx * WORD_SIZE
        )

        # grab a word beginning at lvar start and put on operand stack
        self.push(self.stack[lvar_start : (lvar_start + WORD_SIZE)])

    def handle_store(self, dir: StoreDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW

        if dir.lvar_idx * WORD_SIZE + self.stack_frame_start > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        lvar_start = (
            self.stack_frame_start + STACK_FRAME_HEADER_SIZE + dir.lvar_idx * WORD_SIZE
        )

        # grab uppermost word from stack
        value = self.pop(type=bytes)
        # put into lvar
        for i in range(0, WORD_SIZE):
            self.stack[lvar_start + i] = value[i]

    def handle_push_val(self, dir: PushValDirective):
        if len(self.stack) + len(dir.val) > self.max_stack_size:
            return DirectiveErrorCode.STACK_OVERFLOW
        self.push(dir.val)

    def handle_wait_rel(self, dir: WaitRelDirective):
        print("wait rel", dir)

    def handle_wait_abs(self, dir: WaitAbsDirective):
        print("wait abs", dir)

    def handle_const_cmd(self, dir: ConstCmdDirective):
        print("cmd", dir)

    def handle_goto(self, dir: GotoDirective):
        if dir.dir_idx > len(self.seq.dirs):
            return DirectiveErrorCode.DIR_OUT_OF_BOUNDS
        self.next_dir_idx = dir.dir_idx

    def handle_if(self, dir: IfDirective):
        if dir.false_goto_dir_index > len(self.seq.dirs):
            return DirectiveErrorCode.DIR_OUT_OF_BOUNDS
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        conditional = self.pop()
        if conditional == 0:
            self.next_dir_idx = dir.false_goto_dir_index

    def handle_push_tlm_val(self, dir: PushTlmValDirective):
        value = self.tlm_db.get(dir.chan_id, None)
        if value is None:
            return DirectiveErrorCode.TLM_NOT_FOUND

        if dir.offset + dir.size > len(value):
            return DirectiveErrorCode.TLM_ACCESS_OUT_OF_BOUNDS

        self.push(value[dir.offset : (dir.offset + dir.size)])

    def handle_push_prm(self, dir: PushPrmDirective):
        value = self.prm_db.get(dir.prm_id, None)
        if value is None:
            return DirectiveErrorCode.PRM_NOT_FOUND

        if dir.offset + dir.size > len(value):
            return DirectiveErrorCode.PRM_ACCESS_OUT_OF_BOUNDS

        self.push(value[dir.offset : (dir.offset + dir.size)])

    def handle_or(self, dir: OrDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() | self.pop())

    def handle_and(self, dir: AndDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() & self.pop())

    def handle_ieq(self, dir: IntEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        lhs = self.pop()
        rhs = self.pop()
        print(lhs, rhs)
        self.push(lhs == rhs)

    def handle_ine(self, dir: IntNotEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() != self.pop())

    def handle_ult(self, dir: UnsignedLessThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(signed=False) < self.pop(signed=False))

    def handle_ule(self, dir: UnsignedLessThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(signed=False) <= self.pop(signed=False))

    def handle_ugt(self, dir: UnsignedGreaterThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(signed=False) > self.pop(signed=False))

    def handle_uge(self, dir: UnsignedGreaterThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(signed=False) >= self.pop(signed=False))

    def handle_slt(self, dir: SignedLessThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() < self.pop())

    def handle_sle(self, dir: SignedLessThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() <= self.pop())

    def handle_sgt(self, dir: SignedGreaterThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() > self.pop())

    def handle_sge(self, dir: SignedGreaterThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() >= self.pop())

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
        self.push(self.pop(type=float) < self.pop(type=float))

    def handle_fle(self, dir: FloatLessThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(type=float) <= self.pop(type=float))

    def handle_fgt(self, dir: FloatGreaterThanDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(type=float) > self.pop(type=float))

    def handle_fge(self, dir: FloatGreaterThanOrEqualDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop(type=float) >= self.pop(type=float))

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
        self.push(float(val))

    def handle_uitofp(self, dir: UnsignedIntToFloatDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop(signed=False)
        self.push(float(val))

    def handle_iadd(self, dir: IntAddDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() + self.pop())

    def handle_isub(self, dir: IntSubtractDirective):
        if len(self.stack) < 2 * WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        self.push(self.pop() - self.pop())

    def handle_exit(self, dir: ExitDirective):
        if dir.success:
            self.next_dir_idx = len(self.seq.dirs)
        else:
            return DirectiveErrorCode.DELIBERATE_FAILURE


def main():
    model = FpySequencerModel()

    seq = [
        PushValDirective(int(123123).to_bytes(8, "big")),
        PushValDirective(int(1).to_bytes(8, "big")),
        IntAddDirective(),
        PushValDirective(int(123124).to_bytes(8, "big")),
        IntEqualDirective(),
        IfDirective(7),
        ExitDirective(True),
        ExitDirective(False)
    ]

    ret = model.run(Sequence(0, seq))
    if ret != DirectiveErrorCode.NO_ERROR:
        print("seq failed", ret)


if __name__ == "__main__":
    main()
