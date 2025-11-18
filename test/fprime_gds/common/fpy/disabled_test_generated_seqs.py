import math
import pytest
from fprime_gds.common.fpy.codegen import (
    SPECIFIC_INTEGER_TYPES,
    SPECIFIC_NUMERIC_TYPES,
    UNSIGNED_INTEGER_TYPES,
    SIGNED_INTEGER_TYPES,
    SPECIFIC_FLOAT_TYPES,
    FppTypeClass,
)
from fprime_gds.common.models.serialize.numerical_types import (
    U64Type as U64Value,
    I64Type as I64Value,
    F64Type as F64Value,
)

from fprime_gds.common.fpy.model import MIN_INT64, overflow_check
from fprime_gds.common.fpy.test_helpers import (
    assert_compile_failure,
    assert_run_success,
)

MAX_BITWIDTH_TYPES = [I64Value, U64Value, F64Value]
NUMERIC_VALUES = ["min", "-1", "0", "1", "max"]

ARITHMETIC_OPERATORS = [
    "+",
    "-",
    "/",
    "*",
]


def get_max(type: FppTypeClass) -> int | float:
    assert type in SPECIFIC_NUMERIC_TYPES
    if type in SPECIFIC_INTEGER_TYPES:
        return type.range()[1] - 1

    # otherwise, return float or double max

    if type.get_bits() == 32:
        # f32
        return 3.402823e38
    # f64
    return 1.79769e308


def get_min(type: FppTypeClass) -> int | float:
    assert type in SPECIFIC_NUMERIC_TYPES
    if type in SPECIFIC_INTEGER_TYPES:
        return type.range()[0]

    # otherwise, return float or double min

    if type.get_bits() == 32:
        # f32
        return -3.402823e38
    # f64
    return -1.79769e308


def get_fpy_str(type: FppTypeClass) -> str:
    assert type in SPECIFIC_NUMERIC_TYPES
    return type.get_canonical_name()


def get_val(type: FppTypeClass, val_str: str) -> int | float:
    assert type in SPECIFIC_NUMERIC_TYPES
    if val_str == "max":
        return get_max(type)
    if val_str == "min":
        return get_min(type)

    if type in SPECIFIC_INTEGER_TYPES:
        return int(val_str)
    return float(val_str)


@pytest.mark.parametrize("lhs_type", MAX_BITWIDTH_TYPES)
@pytest.mark.parametrize("rhs_type", MAX_BITWIDTH_TYPES)
@pytest.mark.parametrize("lhs_val", NUMERIC_VALUES)
@pytest.mark.parametrize("rhs_val", NUMERIC_VALUES)
@pytest.mark.parametrize("op", ARITHMETIC_OPERATORS)
def test_math_with_max_bitwidth_types(
    fprime_test_api, lhs_type, rhs_type, lhs_val, rhs_val, op
):
    lhs_val = get_val(lhs_type, lhs_val)
    rhs_val = get_val(rhs_type, rhs_val)
    seq = ""
    # set lhs and rhs vars
    seq += "lhs: " + lhs_type.get_canonical_name() + " = " + str(lhs_val) + "\n"
    seq += "rhs: " + rhs_type.get_canonical_name() + " = " + str(rhs_val) + "\n"

    if not (get_min(lhs_type) <= lhs_val <= get_max(lhs_type)) or not (
        get_min(rhs_type) <= rhs_val <= get_max(rhs_type)
    ):
        print(lhs_type, get_min(lhs_type))
        # not representable. seq should fail compile
        assert_compile_failure(fprime_test_api, seq)
        return

    result_type = None
    if F64Value in (lhs_type, rhs_type):
        result_type = F64Value
    elif U64Value in (lhs_type, rhs_type):
        result_type = U64Value
    else:
        result_type = I64Value

    should_fail = False

    ans = 0
    if op == "/":
        if rhs_val == 0:
            should_fail = True
            ans = math.inf
        else:
            if result_type == F64Value:
                ans = lhs_val / rhs_val
            else:
                if lhs_val == MIN_INT64 and rhs_val == -1:
                    # cpp specific overflow behavior
                    ans = MIN_INT64
                else:
                    # do int division
                    ans = int(lhs_val / rhs_val)
    elif op == "+":
        ans = lhs_val + rhs_val
    elif op == "-":
        ans = lhs_val - rhs_val
    elif op == "*":
        ans = lhs_val * rhs_val
    else:
        assert False, op

    if result_type != F64Value and op != "/":
        # if integer and not division, prevent overflow
        ans = overflow_check(ans)

    # in a perfect world, this is the answer
    # but this is not a perfect world.

    if math.isinf(ans):
        should_fail = True

    seq += "if lhs " + op + " rhs == " + str(ans) + ":\n"
    seq += "    exit(True)\n"
    seq += "exit(False)\n"
    print(seq)
    if should_fail:
        assert_compile_failure(fprime_test_api, seq)
    else:
        assert_run_success(fprime_test_api, seq)
