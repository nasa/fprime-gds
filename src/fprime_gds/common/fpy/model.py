from enum import Enum
import inspect
from fprime_gds.common.fpy.bytecode.directives import (
    AllocateStackDirective,
    AndDirective,
    CmdDirective,
    DeserSerReg1Directive,
    DeserSerReg2Directive,
    DeserSerReg4Directive,
    DeserSerReg8Directive,
    Directive,
    ExitDirective,
    GetPrmDirective,
    GetTlmValueDirective,
    GotoDirective,
    IfDirective,
    IntEqualDirective,
    IntNotEqualDirective,
    NoOpDirective,
    NotDirective,
    OrDirective,
    PushConstDirective,
    SetRegDirective,
    SetSerRegDirective,
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


class FpySequencerModel:

    def __init__(self, heap_size=4096, stack_size=4096) -> None:
        self.heap = bytearray()
        self.heap_max_size = heap_size

        self.stack = bytearray()
        self.stack_max_size = stack_size

        self.dirs = []
        self.dir_idx = 0
        self.tlm_db: dict[int, bytearray] = {}
        self.prm_db: dict[int, bytearray] = {}

    def push(self, val: int | bytes):
        if isinstance(val, bytes):
            self.stack += val
        else:
            assert isinstance(val, int)
            self.stack += val.to_bytes(length=8, byteorder="big", signed=True)

    def pop(self) -> int:
        last_8 = self.stack[-8:]
        self.stack = self.stack[:-8]
        return int.from_bytes(last_8, byteorder="big", signed=True)

    def put_on_heap(self, bytes: bytearray) -> int:
        start_addr = len(self.heap)
        self.heap += bytes
        return start_addr

    def reset(self):
        self.heap = bytearray()
        self.stack = bytearray()
        self.dirs = []
        self.dir_idx = 0

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

    def run(self, dirs: list[Directive]):
        self.reset()
        self.dirs = dirs
        while self.dir_idx < len(self.dirs):
            next_dir = self.dirs[self.dir_idx]
            self.dir_idx += 1
            result = self.dispatch(next_dir)
            if result != DirectiveErrorCode.NO_ERROR:
                return result
        return DirectiveErrorCode.NO_ERROR

    def handle_no_op(self, dir: NoOpDirective):
        pass

    def handle_push_const(self, dir: PushConstDirective):
        if len(self.stack) + 8 > self.stack_max_size:
            return DirectiveErrorCode.STACK_OVERFLOW
        self.push(dir.val)

    def handle_wait_rel(self, dir: WaitRelDirective):
        pass

    def handle_wait_abs(self, dir: WaitAbsDirective):
        pass

    def handle_goto(self, dir: GotoDirective):
        if dir.statement_index > len(self.dirs):
            return DirectiveErrorCode.STMT_OUT_OF_BOUNDS
        self.dir_idx = dir.statement_index

    def handle_if(self, dir: IfDirective):
        if dir.false_goto_stmt_index > len(self.dirs):
            return DirectiveErrorCode.STMT_OUT_OF_BOUNDS
        if len(self.stack) < 8:
            return DirectiveErrorCode.STACK_UNDERFLOW
        conditional = self.pop()
        if conditional == 0:
            self.dir_idx = dir.false_goto_stmt_index
        

    def handle_no_op(self, dir: NoOpDirective):
        pass

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
        self.push(bytearray(dir.size))

    def handle_deser_ser_reg_8(self, dir: DeserSerReg8Directive):
        pass

    def handle_deser_ser_reg_4(self, dir: DeserSerReg4Directive):
        pass

    def handle_deser_ser_reg_2(self, dir: DeserSerReg2Directive):
        pass

    def handle_deser_ser_reg_1(self, dir: DeserSerReg1Directive):
        pass

    def handle_or(self, dir: OrDirective):
        pass

    def handle_and(self, dir: AndDirective):
        pass

    def handle_ieq(self, dir: IntEqualDirective):
        pass

    def handle_ine(self, dir: IntNotEqualDirective):
        pass

    def handle_ult(self, dir: UnsignedLessThanDirective):
        pass

    def handle_ule(self, dir: UnsignedLessThanOrEqualDirective):
        pass

    def handle_ugt(self, dir: UnsignedGreaterThanDirective):
        pass

    def handle_uge(self, dir: UnsignedGreaterThanOrEqualDirective):
        pass

    def handle_slt(self, dir: SignedLessThanDirective):
        pass

    def handle_sle(self, dir: SignedLessThanOrEqualDirective):
        pass

    def handle_sgt(self, dir: SignedGreaterThanDirective):
        pass

    def handle_sge(self, dir: SignedGreaterThanOrEqualDirective):
        pass

    def handle_feq(self, dir: FloatEqualDirective):
        pass

    def handle_fne(self, dir: FloatNotEqualDirective):
        pass

    def handle_flt(self, dir: FloatLessThanDirective):
        pass

    def handle_fle(self, dir: FloatLessThanOrEqualDirective):
        pass

    def handle_fgt(self, dir: FloatGreaterThanDirective):
        pass

    def handle_fge(self, dir: FloatGreaterThanOrEqualDirective):
        pass

    def handle_not(self, dir: NotDirective):
        pass

    def handle_fpext(self, dir: FloatExtendDirective):
        pass

    def handle_fptrunc(self, dir: FloatTruncateDirective):
        pass

    def handle_fptosi(self, dir: FloatToSignedIntDirective):
        pass

    def handle_fptoui(self, dir: FloatToUnsignedIntDirective):
        pass

    def handle_sitofp(self, dir: SignedIntToFloatDirective):
        pass

    def handle_uitofp(self, dir: UnsignedIntToFloatDirective):
        pass

    def handle_exit(self, dir: ExitDirective):
        pass


def main():
    model = FpySequencerModel()
    seq = [NoOpDirective(), PushConstDirective(123)]
    model.run(seq)


if __name__ == "__main__":
    main()
