from fprime_gds.common.fpy.bytecode.directives import (
    ExitDirective,
    FloatLogDirective,
    PushTimeDirective,
    SignedIntToFloatDirective,
    WaitAbsDirective,
    WaitRelDirective,
)
from fprime_gds.common.fpy.ir import Ir, IrIf, IrLabel
from fprime_gds.common.fpy.syntax import Ast
from fprime_gds.common.fpy.types import FpyMacro, FpyOverloadedCallable, NothingValue
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U8Type,
    F64Type,
    I64Type,
    U64Type,
)
from fprime_gds.common.fpy.bytecode.directives import (
    FloatLessThanDirective,
    FloatMultiplyDirective,
    FloatSubtractDirective,
    FloatToUnsignedIntDirective,
    IntMultiplyDirective,
    IntegerTruncate64To32Directive,
    IntegerZeroExtend32To64Directive,
    PeekDirective,
    PushTimeDirective,
    PushValDirective,
    FloatLogDirective,
    Directive,
    ExitDirective,
    SignedLessThanDirective,
    StackSizeType,
    UnsignedIntToFloatDirective,
    WaitAbsDirective,
    WaitRelDirective,
)


def generate_abs_float(node: Ast) -> list[Directive | Ir]:
    # if input is < 0 multiply by -1
    leave_unmodified = IrLabel(node, "else")
    dirs = [
        # copy the f64
        PushValDirective(StackSizeType(8).serialize()),
        PushValDirective(StackSizeType(0).serialize()),
        PeekDirective(),
        # push 0
        PushValDirective(F64Type(0.0).serialize()),
        # check <
        FloatLessThanDirective(),
        IrIf(leave_unmodified),
        # push -1
        PushValDirective(F64Type(-1.0).serialize()),
        # and multiply
        FloatMultiplyDirective(),
        # otherwise do nothing
        leave_unmodified,
    ]
    return dirs


MACRO_ABS_FLOAT = FpyMacro(F64Type, [("value", F64Type)], generate_abs_float)


def generate_abs_signed_int(node: Ast) -> list[Directive | Ir]:
    # if input is < 0 multiply by -1
    leave_unmodified = IrLabel(node, "else")
    dirs = [
        # copy the I64
        PushValDirective(StackSizeType(8).serialize()),
        PushValDirective(StackSizeType(0).serialize()),
        PeekDirective(),
        # push 0
        PushValDirective(I64Type(0.0).serialize()),
        # check <
        SignedLessThanDirective(),
        IrIf(leave_unmodified),
        # push -1
        PushValDirective(I64Type(-1.0).serialize()),
        # and multiply
        IntMultiplyDirective(),
        # otherwise do nothing
        leave_unmodified,
    ]
    return dirs


MACRO_ABS_SIGNED_INT = FpyMacro(I64Type, [("value", I64Type)], generate_abs_signed_int)


def generate_abs_unsigned_int(node: Ast) -> list[Directive | Ir]:
    # unsigned is already positive!
    return []


MACRO_ABS_UNSIGNED_INT = FpyMacro(
    U64Type, [("value", U64Type)], generate_abs_unsigned_int
)

MACRO_ABS = FpyOverloadedCallable(
    [MACRO_ABS_FLOAT, MACRO_ABS_SIGNED_INT, MACRO_ABS_UNSIGNED_INT]
)


MACRO_SLEEP_SECONDS_USECONDS = FpyMacro(
    NothingValue,
    [
        (
            "seconds",
            U32Type,
        ),
        ("microseconds", U32Type),
    ],
    lambda n: [WaitRelDirective()],
)


def generate_sleep_float(node: Ast) -> list[Directive | Ir]:
    # convert F64 to seconds and microseconds
    dirs = [
        # first do seconds
        # copy the f64
        PushValDirective(StackSizeType(8).serialize()),
        PushValDirective(StackSizeType(0).serialize()),
        PeekDirective(),
        # convert to U64
        FloatToUnsignedIntDirective(),
        # and then U32
        IntegerTruncate64To32Directive(),
        # now we have f64, u32 (seconds) on stack
        # now do microseconds
        # copy the f64 and u32
        PushValDirective(StackSizeType(12).serialize()),
        PushValDirective(StackSizeType(0).serialize()),
        PeekDirective(),
        # turn the u32 into a float
        IntegerZeroExtend32To64Directive(),
        UnsignedIntToFloatDirective(),
        # subtract, this should give us the frac
        FloatSubtractDirective(),
        # okay now multiply by 1000000
        PushValDirective(F64Type(1_000_000.0).serialize()),
        # now convert to u32
        FloatToUnsignedIntDirective(),
        IntegerTruncate64To32Directive(),
    ]

    return dirs


MACRO_SLEEP_FLOAT = FpyMacro(NothingValue, [("seconds", F64Type)], generate_sleep_float)

MACRO_SLEEP = FpyOverloadedCallable([MACRO_SLEEP_FLOAT, MACRO_SLEEP_SECONDS_USECONDS])

def generate_log_signed_int(node: Ast) -> list[Directive|Ir]:
    return [
        # convert int to float
        SignedIntToFloatDirective(),
        FloatLogDirective()
    ]

MACROS: dict[str, FpyMacro | FpyOverloadedCallable] = {
    "sleep": MACRO_SLEEP,
    "sleep_until": FpyMacro(
        NothingValue, [("wakeup_time", TimeType)], lambda n: [WaitAbsDirective()]
    ),
    "exit": FpyMacro(NothingValue, [("exit_code", U8Type)], lambda n: [ExitDirective()]),
    "log": FpyMacro(F64Type, [("operand", F64Type)], lambda n: [FloatLogDirective()]),
    "now": FpyMacro(TimeType, [], lambda n: [PushTimeDirective()]),
    "abs": MACRO_ABS,
}
