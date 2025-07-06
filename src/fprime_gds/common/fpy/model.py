from dataclasses import dataclass
from enum import Enum
import inspect
import struct
from fprime_gds.common.fpy.bytecode.directives import (
    AllocateStackDirective,
    AndDirective,
    CallDirective,
    CmdDirective,
    Directive,
    ExitDirective,
    GetFromHeapDirective,
    GetPrmDirective,
    GetTlmValueDirective,
    GotoDirective,
    IfDirective,
    IntAddDirective,
    IntEqualDirective,
    IntNotEqualDirective,
    PushLVarDirective,
    NoOpDirective,
    NotDirective,
    OrDirective,
    PushConstDirective,
    PopLVarDirective,
    ReturnDirective,
    ReturnValDirective,
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


class DirectiveErrorCode(Enum):
    NO_ERROR = 0
    SER_REG_OUT_OF_BOUNDS = 1
    STMT_OUT_OF_BOUNDS = 2
    SER_REG_DESERIALIZE_FAILURE = 3
    SER_REG_SERIALIZE_FAILURE = 4
    TLM_GET_NOT_CONNECTED = 5
    TLM_CHAN_NOT_FOUND = 6
    PRM_GET_NOT_CONNECTED = 7
    PRM_NOT_FOUND = 8
    CMD_SERIALIZE_FAILURE = 9
    REGISTER_OUT_OF_BOUNDS = 10
    SER_REG_ACCESS_OUT_OF_BOUNDS = 11
    DELIBERATE_FAILURE = 12
    STACK_OVERFLOW = 13
    STACK_UNDERFLOW = 14
    HEAP_OVERFLOW = 15
    UNKNOWN_FUNC = 16


@dataclass
class FunctionInfo:
    arg_count: int
    lvar_count: int
    operand_stack_depth: int
    start_idx: int

    def __post_init__(self):
        assert self.arg_count <= self.lvar_count


class FpySequencerModel:

    def __init__(self, heap_size=4096, stack_size=4096) -> None:
        self.heap = bytearray()
        self.heap_max_size = heap_size

        self.stack = bytearray()
        self.stack_max_size = stack_size
        self.lvar_array_offset = 0

        self.funcs: list[FunctionInfo] = []
        self.dirs: list[Directive] = []
        self.next_dir_idx = 0
        self.tlm_db: dict[int, bytearray] = {}
        self.prm_db: dict[int, bytearray] = {}

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

    def handle_call(self, dir: CallDirective):
        if dir.func_idx >= len(self.funcs):
            return DirectiveErrorCode.UNKNOWN_FUNC
        func = self.funcs[dir.func_idx]
        if (
            len(self.stack)
            + func.lvar_count * WORD_SIZE
            + func.operand_stack_depth * WORD_SIZE
            > self.stack_max_size
        ):
            return DirectiveErrorCode.STACK_OVERFLOW

        self.begin_func(func)

    def begin_func(self, func: FunctionInfo):
        # pop all args off the operand stack
        args = [self.pop(type=bytes) for i in range(0, func.arg_count)]

        # push next dir index so we know where to return to
        self.push(self.next_dir_idx, signed=False)
        # lvar array begins after the "frame data"
        self.lvar_array_offset = len(self.stack)

        # now put args onto lvar array
        for arg in args:
            self.push(arg)

        # now push some empty values for remaining lvars
        for i in range(0, func.lvar_count - func.arg_count):
            self.push(0)

        self.next_dir_idx = func.start_idx

    def handle_return_val(self, dir: ReturnValDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        val = self.pop()

        # okay now delete lvar array and operand stack
        assert self.lvar_array_offset <= len(self.stack), (
            self.lvar_array_offset,
            len(self.stack),
        )
        self.stack = self.stack[: self.lvar_array_offset]
        # okay now get the return addr
        return_addr = self.pop(signed=False)
        self.next_dir_idx = return_addr
        # okay now push the return value
        self.push(val)

    def handle_return(self, dir: ReturnDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        # delete lvar array and operand stack
        assert self.lvar_array_offset <= len(self.stack), (
            self.lvar_array_offset,
            len(self.stack),
        )
        self.stack = self.stack[: self.lvar_array_offset]
        # okay now get the return addr
        return_addr = self.pop(signed=False)
        self.next_dir_idx = return_addr

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

    def put_on_heap(self, bytes: bytearray) -> int:
        start_addr = len(self.heap)
        self.heap += bytes
        return start_addr

    def reset(self):
        self.heap = bytearray()

        self.stack = bytearray()
        self.lvar_array_offset = 0

        self.funcs: list[FunctionInfo] = []
        self.dirs: list[Directive] = []
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

    def run(self, dirs: list[Directive], funcs: list[FunctionInfo]):
        self.reset()
        self.dirs = dirs
        self.funcs = funcs
        # first func must be "main" method
        assert len(funcs) > 0
        assert funcs[0].start_idx == 0, funcs[0].start_idx
        self.begin_func(funcs[0])
        while self.next_dir_idx < len(self.dirs):
            next_dir = self.dirs[self.next_dir_idx]
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

    def handle_no_op(self, dir: NoOpDirective):
        pass

    def handle_push_lvar(self, dir: PushLVarDirective):
        if len(self.stack) + WORD_SIZE > self.stack_max_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        if dir.lvar_idx * WORD_SIZE + self.lvar_array_offset > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        lvar_start = self.lvar_array_offset + dir.lvar_idx * WORD_SIZE

        # grab a word beginning at lvar start and put on operand stack
        self.push(self.stack[lvar_start : (lvar_start + WORD_SIZE)])

    def handle_pop_lvar(self, dir: PopLVarDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW

        if dir.lvar_idx * WORD_SIZE + self.lvar_array_offset > len(self.stack):
            return DirectiveErrorCode.STACK_OVERFLOW

        lvar_start = self.lvar_array_offset + dir.lvar_idx * WORD_SIZE

        # grab uppermost word from stack
        value = self.stack[-WORD_SIZE:]
        # remove from stack
        self.stack = self.stack[:-WORD_SIZE]
        for i in range(0, WORD_SIZE):
            self.stack[lvar_start + i] = value[i]

    def handle_push_const(self, dir: PushConstDirective):
        if len(self.stack) + WORD_SIZE > self.stack_max_size:
            return DirectiveErrorCode.STACK_OVERFLOW
        self.push(dir.val)

    def handle_wait_rel(self, dir: WaitRelDirective):
        pass

    def handle_wait_abs(self, dir: WaitAbsDirective):
        pass

    def handle_goto(self, dir: GotoDirective):
        if dir.statement_index > len(self.dirs):
            return DirectiveErrorCode.STMT_OUT_OF_BOUNDS
        self.next_dir_idx = dir.statement_index

    def handle_if(self, dir: IfDirective):
        if dir.false_goto_stmt_index > len(self.dirs):
            return DirectiveErrorCode.STMT_OUT_OF_BOUNDS
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        conditional = self.pop()
        if conditional == 0:
            self.next_dir_idx = dir.false_goto_stmt_index

    def handle_get_tlm_val(self, dir: GetTlmValueDirective):
        value = self.tlm_db.get(dir.chan_id, None)
        if value is None:
            return DirectiveErrorCode.TLM_CHAN_NOT_FOUND
        # okay we've got some bytes. put it in memory if it can fit
        if len(value) + len(self.heap) > self.heap_max_size:
            return DirectiveErrorCode.HEAP_OVERFLOW

        # put on heap, and push the addr onto operand stack
        self.push(self.put_on_heap(value))

    def handle_get_prm(self, dir: GetPrmDirective):
        value = self.prm_db.get(dir.prm_id, None)
        if value is None:
            return DirectiveErrorCode.PRM_NOT_FOUND
        # okay we've got some bytes. put it in memory if it can fit
        if len(value) + len(self.heap) > self.heap_max_size:
            return DirectiveErrorCode.HEAP_OVERFLOW

        # put on heap, and push the addr onto operand stack
        self.push(self.put_on_heap(value))

    def handle_cmd(self, dir: CmdDirective):
        pass

    def handle_allocate_stack(self, dir: AllocateStackDirective):
        if len(self.stack) + dir.size > self.stack_max_size:
            return DirectiveErrorCode.STACK_OVERFLOW
        self.push(bytearray(dir.size), signed=False)

    def handle_get_from_heap(self, dir: GetFromHeapDirective):
        if len(self.stack) < WORD_SIZE:
            return DirectiveErrorCode.STACK_UNDERFLOW
        if len(self.stack) + dir.size > self.stack_max_size:
            return DirectiveErrorCode.STACK_OVERFLOW

        offset = self.pop(signed=False)
        if offset + dir.size > len(self.heap):
            return DirectiveErrorCode.HEAP_OVERFLOW
        bytes = self.heap[offset : (offset + dir.size)]
        self.push(bytes)

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

    def handle_exit(self, dir: ExitDirective):
        if dir.success:
            self.next_dir_idx = len(self.dirs)
        else:
            return DirectiveErrorCode.DELIBERATE_FAILURE


def main():
    model = FpySequencerModel()
    # push lvar 0 (arg 0) on stack
    # put 10 on stack
    # add them together

    seq = [
        # push 15 on stack
        PushConstDirective(15),
        # add 10 to 15, push to stack
        CallDirective(1),
        # push 25 to stack
        PushConstDirective(25),
        # check if 25 == 25, push to stack
        IntEqualDirective(),
        # check if latest stack succeeded, if so continue on to exit, otherwise fail
        IfDirective(6),
        ExitDirective(True),
        ExitDirective(False),
        PushLVarDirective(0),
        PushConstDirective(10),
        IntAddDirective(),
        ReturnValDirective(),
    ]

    funcs = [FunctionInfo(0, 1, 2, 0), FunctionInfo(1, 1, 2, 7)]

    ret = model.run(seq, funcs)
    if ret != DirectiveErrorCode.NO_ERROR:
        print("seq failed", ret)


if __name__ == "__main__":
    main()
