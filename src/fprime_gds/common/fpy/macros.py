from __future__ import annotations
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
from fprime_gds.common.fpy.types import FpyMacro, NothingValue
from fprime_gds.common.models.serialize.time_type import TimeType as TimeValue
from fprime_gds.common.models.serialize.numerical_types import (
    U8Type as U8Value,
    U32Type as U32Value,
    I64Type as I64Value,
    F64Type as F64Value,
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
        PushValDirective(F64Value(0.0).serialize()),
        # check <
        FloatLessThanDirective(),
        IrIf(leave_unmodified),
        # push -1
        PushValDirective(F64Value(-1.0).serialize()),
        # and multiply
        FloatMultiplyDirective(),
        # otherwise do nothing
        leave_unmodified,
    ]
    return dirs


MACRO_ABS_FLOAT = FpyMacro("abs", F64Value, [("value", F64Value)], generate_abs_float)


def generate_abs_signed_int(node: Ast) -> list[Directive | Ir]:
    # if input is < 0 multiply by -1
    leave_unmodified = IrLabel(node, "else")
    dirs = [
        # copy the I64
        PushValDirective(StackSizeType(8).serialize()),
        PushValDirective(StackSizeType(0).serialize()),
        PeekDirective(),
        # push 0
        PushValDirective(I64Value(0).serialize()),
        # check <
        SignedLessThanDirective(),
        IrIf(leave_unmodified),
        # push -1
        PushValDirective(I64Value(-1).serialize()),
        # and multiply
        IntMultiplyDirective(),
        # otherwise do nothing
        leave_unmodified,
    ]
    return dirs


MACRO_ABS_SIGNED_INT = FpyMacro(
    "abs", I64Value, [("value", I64Value)], generate_abs_signed_int
)

MACRO_SLEEP_SECONDS_USECONDS = FpyMacro(
    "sleep",
    NothingValue,
    [
        (
            "seconds",
            U32Value,
        ),
        ("microseconds", U32Value),
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
        PushValDirective(F64Value(1_000_000.0).serialize()),
        # now convert to u32
        FloatToUnsignedIntDirective(),
        IntegerTruncate64To32Directive(),
    ]

    return dirs


MACRO_SLEEP_FLOAT = FpyMacro(
    "sleep", NothingValue, [("seconds", F64Value)], generate_sleep_float
)


def generate_log_signed_int(node: Ast) -> list[Directive | Ir]:
    return [
        # convert int to float
        SignedIntToFloatDirective(),
        FloatLogDirective(),
    ]


MACROS: dict[str, FpyMacro] = {
    "sleep": MACRO_SLEEP_SECONDS_USECONDS,
    "sleep_until": FpyMacro(
        "sleep_until",
        NothingValue,
        [("wakeup_time", TimeValue)],
        lambda n: [WaitAbsDirective()],
    ),
    "exit": FpyMacro(
        "exit", NothingValue, [("exit_code", U8Value)], lambda n: [ExitDirective()]
    ),
    "log": FpyMacro(
        "log", F64Value, [("operand", F64Value)], lambda n: [FloatLogDirective()]
    ),
    "now": FpyMacro("now", TimeValue, [], lambda n: [PushTimeDirective()]),
    "iabs": MACRO_ABS_SIGNED_INT,
    "fabs": MACRO_ABS_FLOAT,
}
