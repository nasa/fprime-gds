from fprime.common.models.serialize.numerical_types import U32Type
import pytest
from fprime_gds.common.fpy.test_helpers import (
    assert_run_success,
    assert_compile_failure,
    assert_compile_success,
    assert_run_failure,
    lookup_type,
)


# define this function if you want to just use the Python fpy model
@pytest.fixture(name="fprime_test_api", scope="module")
def fprime_test_api_override():
    """A file-specific override that simply returns None."""
    return None


def test_simple_var(fprime_test_api):
    seq = """
var: U32 = 1
"""

    assert_run_success(fprime_test_api, seq)


def test_int_literal(fprime_test_api):
    seq = """
var: I64 = 123_456
var = -123_456
var = +123_456
var = 000_00000_0
"""

    assert_run_success(fprime_test_api, seq)


def test_bad_int_literal(fprime_test_api):
    seq = """
var: I64 = 0123_456

"""

    assert_compile_failure(fprime_test_api, seq)

def test_float_literal(fprime_test_api):
    seq = """
var: F32 = 1.000e-5
var = .1
var = 1.
var = 2.123
var = 100.5e+10
var = -123.456
"""

    assert_run_success(fprime_test_api, seq)


def test_exit_success(fprime_test_api):
    seq = """
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_exit_failure(fprime_test_api):
    seq = """
exit(False)
"""
    assert_run_failure(fprime_test_api, seq)


def test_large_var(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
"""

    assert_run_success(fprime_test_api, seq)


def test_var_assign_to_var(fprime_test_api):
    seq = """
x: U32 = 1
var: U32 = x
"""

    assert_run_success(fprime_test_api, seq)


def test_nonexistent_var(fprime_test_api):
    seq = """
var = 1
"""

    assert_compile_failure(fprime_test_api, seq)


def test_create_after_assign_var(fprime_test_api):
    seq = """
var = 1
var: U32 = 2
"""

    assert_compile_failure(fprime_test_api, seq)


def test_bad_assign_type(fprime_test_api):
    seq = """
var: failure = 1
"""

    assert_compile_failure(fprime_test_api, seq)


def test_weird_assign_type(fprime_test_api):
    seq = """
var: CdhCore.cmdDisp.CMD_NO_OP = 1
"""

    assert_compile_failure(fprime_test_api, seq)


def test_reassign(fprime_test_api):
    seq = """
var: U32 = 1
var = 2
"""

    assert_run_success(fprime_test_api, seq)


def test_reassign_ann(fprime_test_api):
    seq = """
var: U32 = 1
var: U32 = 2
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_inconsistent_type(fprime_test_api):
    seq = """
var: U32 = 1
var: U16 = 2
"""

    assert_compile_failure(fprime_test_api, seq)


def test_call_cmd(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP()
"""
    assert_run_success(fprime_test_api, seq)


def test_call_cmd_with_str_arg(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP_STRING("hello world")
"""
    assert_run_success(fprime_test_api, seq)


def test_call_cmd_with_int_arg(fprime_test_api):
    seq = """
Ref.sendBuffComp.PARAMETER3_PRM_SET(4)
"""
    assert_run_success(fprime_test_api, seq)


def test_bad_enum_ctor(fprime_test_api):
    seq = """
Ref.SG5.Settings(123, 0.5, 0.5, Ref.SignalType(1))
"""
    assert_compile_failure(fprime_test_api, seq)


def test_cmd_with_enum(fprime_test_api):
    seq = """
Ref.SG5.Settings(123, 0.5, 0.5, Ref.SignalType.TRIANGLE)
"""
    assert_run_success(fprime_test_api, seq)


def test_instantiate_type_for_cmd(fprime_test_api):
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.ONE, Ref.Choice.TWO))
"""
    assert_run_success(fprime_test_api, seq)


def test_var_with_enum_type(fprime_test_api):
    seq = """
var: Ref.Choice = Ref.Choice.ONE
"""

    assert_run_success(fprime_test_api, seq)


def test_simple_if(fprime_test_api):
    seq = """
var: bool = True

# use exit(True) if we want the sequence to succeed
# exit(False) if we want it to fail. helpful for testing.

if var:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_expr(fprime_test_api):
    seq = """
if True or False:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_not_expr(fprime_test_api):
    seq = """
if not False:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_expr_with_vars(fprime_test_api):
    seq = """
var1: bool = True
var2: bool = False

if var1 or var2:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_geq(fprime_test_api):
    seq = """
if 2 >= 1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_geq_tlm(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP()
if CdhCore.cmdDisp.CommandsDispatched >= 1:
    exit(True)
exit(False)
"""

    assert_run_success(
        fprime_test_api,
        seq,
        {"CdhCore.cmdDisp.CommandsDispatched": U32Type(1).serialize()},
    )


def test_large_elifs(fprime_test_api):
    seq = """
if CdhCore.cmdDisp.CommandsDispatched == 0:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("0")
elif CdhCore.cmdDisp.CommandsDispatched == 1:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("1")
elif CdhCore.cmdDisp.CommandsDispatched == 2:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("2")
elif CdhCore.cmdDisp.CommandsDispatched == 3:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("3")
elif CdhCore.cmdDisp.CommandsDispatched == 4:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("4")
else:
    CdhCore.cmdDisp.CMD_NO_OP_STRING(">4")
"""

    assert_run_success(
        fprime_test_api,
        seq,
        {"CdhCore.cmdDisp.CommandsDispatched": U32Type(4).serialize()},
    )


def test_int_as_stmt(fprime_test_api):
    seq = """
2
"""

    assert_compile_failure(fprime_test_api, seq)


def test_complex_as_stmt(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP
"""

    assert_compile_failure(fprime_test_api, seq)


def test_get_struct_member(fprime_test_api):
    seq = """
if Ref.cmdSeq.Debug.nextStatementOpcode == 0:
    # should be 0 because we aren't in debug mode
    exit(True)
exit(False)
"""

    assert_run_success(
        fprime_test_api,
        seq,
        {
            "Ref.cmdSeq.Debug": lookup_type(
                fprime_test_api, "Svc.FpySequencer.DebugTelemetry"
            )(
                {
                    "reachedEndOfFile": False,
                    "nextStatementReadSuccess": False,
                    "nextStatementOpcode": 0,
                    "nextCmdOpcode": 0,
                }
            ).serialize()
        },
    )


def test_get_const_struct_member(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
if var.priority == 3:
    exit(True)
exit(False)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_const_member_of_ctor(fprime_test_api):
    seq = """
# currently this is not supported, but it should be in the future
var: U32 = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED).priority
if var == 3:
    exit(True)
exit(False)
"""

    assert_compile_failure(fprime_test_api, seq)


def test_float_cmp(fprime_test_api):
    seq = """
if 4.0 > 5.0:
    exit(False)
exit(True)
"""

    assert_run_success(fprime_test_api, seq)


def test_wait_rel(fprime_test_api):
    seq = """
sleep(1, 1000)
"""
    assert_run_success(fprime_test_api, seq)


def test_f32_f64_cmp(fprime_test_api):
    seq = """
val: F32 = 0.0
val2: F64 = 1.0
if val > val2:
    exit(False)
exit(True)
"""

    assert_run_success(fprime_test_api, seq)


def test_construct_array(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_item_of_var(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
if val[0] == 0:
    exit(True)
exit(False)
"""

    assert_run_success(fprime_test_api, seq)


def test_i32_f64_cmp(fprime_test_api):
    seq = """
val: I32 = 2
val2: F64 = 1.0
if val > val2:
    exit(True)
exit(False)
"""

    assert_run_success(fprime_test_api, seq)


def test_i32_u32_cmp(fprime_test_api):
    seq = """
val: I32 = -2
val2: U32 = 2
# this is actually false because we interpret both sides as unsigned
if val < val2:
    exit(False)
exit(True)
"""

    assert_run_success(fprime_test_api, seq)


# caught one bug
def test_float_int_literal_cmp(fprime_test_api):
    seq = """
if 1 < 2.0:
    exit(True)
exit(False)
"""

    assert_run_success(fprime_test_api, seq)


def test_assign_float_to_int(fprime_test_api):
    seq = """
val: I64 = 1.0
"""

    assert_compile_failure(fprime_test_api, seq)


# caught one bug
def test_and_of_ors(fprime_test_api):
    seq = """
if True or False and True or True:
    exit(True)
exit(False)
"""

    assert_run_success(fprime_test_api, seq)


def test_if_true(fprime_test_api):
    seq = """
if True:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_false(fprime_test_api):
    seq = """
if False:
    exit(False)
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_else_true(fprime_test_api):
    seq = """
if True:
    exit(True)
else:
    exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_else_false(fprime_test_api):
    seq = """
if False:
    exit(False)
else:
    exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_elif_else(fprime_test_api):
    seq = """
if False:
    exit(False)
elif True:
    exit(True)
else:
    exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_and_true_true(fprime_test_api):
    seq = """
if True and True:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_and_true_false(fprime_test_api):
    seq = """
if True and False:
    exit(False)
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_false_false(fprime_test_api):
    seq = """
if False or False:
    exit(False)
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_true_false(fprime_test_api):
    seq = """
if True or False:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_not_true(fprime_test_api):
    seq = """
if not True:
    exit(False)
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_not_false(fprime_test_api):
    seq = """
if not False:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_and_or_not(fprime_test_api):
    seq = """
if not False and (True or False):
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_literal_comparison(fprime_test_api):
    seq = """
if 255 > 254:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_literal_comparison_false(fprime_test_api):
    seq = """
if 255 < 254:
    exit(False)
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_u8(fprime_test_api):
    seq = """
val1: U8 = 200
val2: U8 = 100

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_i8(fprime_test_api):
    seq = """
val1: I8 = 100
val2: I8 = -100

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_u32(fprime_test_api):
    seq = """
val1: U32 = 4294967295
val2: U32 = 0

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_i32(fprime_test_api):
    seq = """
val1: I32 = 2147483647
val2: I32 = -2147483648

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_f32(fprime_test_api):
    seq = """
val1: F32 = 3.14159
val2: F32 = -3.14159

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_f64(fprime_test_api):
    seq = """
val1: F64 = 3.14159265359
val2: F64 = -3.14159265359

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_mixed_numeric_comparisons(fprime_test_api):
    seq = """
val_u8: U8 = 255
val_i8: I8 = -10
val_u32: U32 = 4294967295
val_i32: I32 = -2147483648
val_f32: F32 = 3.14159
val_f64: F64 = -3.14159265359

# i32 > u32 because the cmp happens as unsigned, and so the
# two's complement negative is really large
if val_u8 < val_i8 and val_i32 > val_u32:
    if val_f64 <= val_f32 and val_f32 >= val_f64:
        if val_u8 != val_i8 and not (val_u32 == val_i32):
            exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_equality_edge_cases(fprime_test_api):
    seq = """
val1: U8 = 0
val2: U8 = 0
val3: F32 = 0.0
val4: F64 = 0.0
val5: I32 = 0

if val1 == val2 and val3 == val4 and val4 == val5:
    if not (val1 != val2) and not (val3 != val4) and not (val4 != val5):
        exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_nested_boolean_expressions(fprime_test_api):
    seq = """
if not (True and False or True and not False) and True:
    exit(False)  # Should not execute
exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_maximum_integer_comparisons(fprime_test_api):
    seq = """
val1: U64 = 18446744073709551615  # Max U64
val2: I64 = 9223372036854775807   # Max I64, should be same in unsigned
# TODO there is currently a bug in this
#val3: I64 = -9223372036854775808  # Min I64, should be max i64 + 1 in unsigned
val3: I64 = -9223372036854775807  # Min I64 - 1, should be max i64 + 1 in unsigned

if val1 > val2 and val2 > val3:
    if val3 < val1:
        exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_type_assignments(fprime_test_api):
    seq = """
val1: I8 = 127
val2: U8 = 255
val3: F32 = 127.0

if val1 == val3:  # Integer to float comparison
    if val2 > val3:  # Unsigned vs float comparison
        exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_negative_val_unsigned_type(fprime_test_api):
    seq = """
val1: U32 = -1  # Should succeed and be equal to largest u32 val
exit(val1 == 2 ** 32 - 1)
"""
    assert_run_success(fprime_test_api, seq)


def test_overflow_compile_error(fprime_test_api):
    seq = """
val1: U8 = 256  # Should fail: value too large for U8
"""
    assert_compile_failure(fprime_test_api, seq)


def test_mixed_boolean_numeric_comparison(fprime_test_api):
    seq = """
val1: U8 = 1
val2: I8 = -1
if (val1 > 0) == True and (val2 < 0) == True:  # Compare boolean results
    if not ((val1 <= 0) == True or (val2 >= 0) == True):
        exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_boolean_nesting(fprime_test_api):
    seq = """
if not not not not not True:  # Multiple not operators
    exit(False)
elif not (True and not (False or not True)):  # Complex nesting
    exit(False)
else:
    exit(True)
"""
    assert_run_success(fprime_test_api, seq)


def test_non_const_str_arg(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP_STRING(Ref.cmdSeq.SeqPath)
"""
    # currently can't do non const string args
    assert_compile_failure(fprime_test_api, seq)


def test_non_const_int_arg(fprime_test_api):
    seq = """
var: U8 = 255
Ref.sendBuffComp.PARAMETER3_PRM_SET(var)
"""
    assert_run_success(fprime_test_api, seq)


def test_non_const_float_arg(fprime_test_api):
    seq = """
var: F32 = 1.2
Ref.sendBuffComp.PARAMETER4_PRM_SET(var)
"""
    assert_run_success(fprime_test_api, seq)


def test_non_const_builtin_arg(fprime_test_api):
    seq = """
var: U32 = 1
var2: U32 = 123123
sleep(var, var2)
"""
    assert_run_success(fprime_test_api, seq)


def test_add_unsigned(fprime_test_api):
    seq = """
var1: U32 = 500
var2: U32 = 1000
if var1 + var2 == 1500 and (var1 + 1) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_add_signed(fprime_test_api):
    seq = """
var1: I32 = -255
var2: I32 = 255
if var1 + var2 == 0 and (var1 + 1) > (var1 + -1):
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_add_float(fprime_test_api):
    seq = """
var1: F32 = -255.0
var2: F32 = 255.0
if var1 + var2 == 0 and (var1 + 1) > (var1 + -1):
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


# this test inspired by a bug
def test_float_truncate_stack_size(fprime_test_api):
    seq = """
var2: F64 = 123.0
var1: F32 = -var2
exit(var1 == -123.0)
"""
    assert_run_success(fprime_test_api, seq)


def test_sub_unsigned(fprime_test_api):
    seq = """
var1: U32 = 1000
var2: U32 = 500
if var1 - var2 == 500 and (var1 - 1) < var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_sub_signed(fprime_test_api):
    seq = """
var1: I32 = 255
var2: I32 = 255
if var1 - var2 == 0 and (var1 - 1) < (var1 - -1):
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_sub_float(fprime_test_api):
    seq = """
var1: F32 = 255.0
var2: F32 = 255.0
if var1 - var2 == 0 and (var1 - 1) < (var1 - -1):
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_mul_unsigned(fprime_test_api):
    seq = """
var1: U32 = 5
var2: U32 = 20
if var1 * var2 == 100 and (var1 * 2) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_mul_signed(fprime_test_api):
    seq = """
var1: I32 = -5
var2: I32 = 20
if var1 * var2 == -100 and (var1 * 2) < var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_mul_float(fprime_test_api):
    seq = """
var1: F32 = 5.0
var2: F32 = 20.0
if var1 * var2 == 100 and (var1 * 2) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_unsigned(fprime_test_api):
    seq = """
var1: U32 = 20
var2: U32 = 5
if var1 / var2 == 4 and (var1 / 2) < var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_signed(fprime_test_api):
    seq = """
var1: I32 = -20
var2: I32 = 5
if var1 / var2 == -4: # and (var1 / -2) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_float(fprime_test_api):
    seq = """
var1: F32 = -20.0
var2: F32 = 5.0
if var1 / var2 == -4 and (var1 / -2) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


# this test caught one bug (my mom spotted it)
def test_order_of_operations(fprime_test_api):
    seq = """
if 1 - 2 + 3 * 4 == 11 and 10 / 5 * 2 == 4:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_arithmetic_arg_to_builtin_bad_type(fprime_test_api):
    seq = """
sleep(1 + 2 * 0, (0 + 1 / 2))
"""
    assert_compile_failure(fprime_test_api, seq)


def test_arithmetic_arg_to_builtin(fprime_test_api):
    seq = """
sleep(1 + 2 * 0, (0 + 1 // 2))
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_mul(fprime_test_api):
    seq = """
var1: I32 = 1
var2: I32 = 2
var3: I32 = 3
if var1 * var2 * var3 == 6:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_add(fprime_test_api):
    seq = """
var1: I32 = 1
var2: I32 = 2
var3: I32 = 3
if var1 + var2 + var3 == 6:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_sub(fprime_test_api):
    seq = """
var1: I32 = 1
var2: I32 = 2
var3: I32 = 3
if var1 - var2 - var3 == -4:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_div(fprime_test_api):
    seq = """
var1: I32 = 3
var2: I32 = 2
var3: I32 = 1
if var1 / var3 / var2 == 3/2:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_pow_unsigned(fprime_test_api):
    seq = """
var1: U32 = 20
var2: U32 = 2
if var1 ** var2 == 400:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_pow_signed(fprime_test_api):
    seq = """
var1: I32 = -20
var2: I32 = 2
if var1 ** var2 == 400:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_pow_float(fprime_test_api):
    seq = """
var1: F32 = 4.0
var2: F32 = 0.5
if var1 ** var2 == 2:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_int_literal_as_float(fprime_test_api):
    seq = """
var: F32 = 1
exit(var == 1.0)
"""

    assert_run_success(fprime_test_api, seq)


def test_log(fprime_test_api):
    seq = """
if log(4.0) > 1.385 and log(4.0) < 1.387:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_assign_complex(fprime_test_api):
    seq = """
var: I64 = 1 + 1
var = var + 3
if var == 5:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_assign_cycle(fprime_test_api):
    seq = """
var: I64 = var
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_cycle_2(fprime_test_api):
    seq = """
var: I64 = (var + 1)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_use_before_declare(fprime_test_api):
    seq = """
var: I64 = var2
var2: I64 = 0
"""
    assert_compile_failure(fprime_test_api, seq)


def test_math_after_cmd(fprime_test_api):
    seq = """
var: I32 = 1
CdhCore.cmdDisp.CMD_NO_OP()
# making sure that the cmd doesn't mess with the stack
if var + 1 == 2:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_cmd_return_val(fprime_test_api):
    seq = """
ret: Fw.CmdResponse = CdhCore.cmdDisp.CMD_NO_OP()
if ret == Fw.CmdResponse.OK:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_struct_eq(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var2: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var3: Svc.DpRecord = Svc.DpRecord(123, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
exit(var == var2 and var != var3)
"""

    assert_run_success(fprime_test_api, seq)


def test_complex_eq_fail(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var2: Fw.CmdResponse = Fw.CmdResponse.OK
exit(var == var2)
"""

    assert_compile_failure(fprime_test_api, seq)


def test_mod_float(fprime_test_api):
    seq = """
var1: F32 = 25.25
var2: F32 = 5
exit(var1 % var2 == 0.25 and (var1 + 1) % var2 == 1.25)
"""
    assert_run_success(fprime_test_api, seq)


def test_mod_unsigned(fprime_test_api):
    seq = """
var1: U32 = 5
var2: U32 = 20
exit(var2 % var1 == 0 and (var2 + 1) % var1 == 1)
"""
    assert_run_success(fprime_test_api, seq)


def test_mod_signed(fprime_test_api):
    seq = """
var1: I32 = -5
var2: I32 = 20
exit(var2 % var1 == 0 and (var2 + 1) % var1 == -4)
"""
    assert_run_success(fprime_test_api, seq)


def test_bool_stack_value(fprime_test_api):
    seq = """
exit((1 == 1) == True)
"""
    assert_run_success(fprime_test_api, seq)


def test_u8_too_large(fprime_test_api):
    seq = """
var: U8 = 123
var = 256
"""
    assert_compile_failure(fprime_test_api, seq)


def test_string_eq(fprime_test_api):
    seq = """
exit("asdf" == "asdf")
"""
    assert_compile_failure(fprime_test_api, seq)


def test_string_var_eq(fprime_test_api):
    seq = """
var: string = "test"
var1: string = "test"
exit(var == var1)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_string_type(fprime_test_api):
    seq = """
var: string = "test"
"""
    assert_compile_failure(fprime_test_api, seq)


def test_too_many_dirs(fprime_test_api):
    from fprime_gds.common.fpy.codegen import MAX_DIRECTIVES_COUNT

    seq = "CdhCore.cmdDisp.CMD_NO_OP()\n" * (MAX_DIRECTIVES_COUNT + 1)
    assert_compile_failure(fprime_test_api, seq)


def test_dir_too_large(fprime_test_api):
    # TODO this doesn't actually crash cuz the dir is too large... not sure at the moment how to trigger this
    from fprime_gds.common.fpy.codegen import MAX_DIRECTIVE_SIZE

    seq = 'CdhCore.cmdDisp.CMD_NO_OP_STRING("' + "a" * MAX_DIRECTIVE_SIZE + '")'
    assert_compile_failure(fprime_test_api, seq)


def test_readme_examples(fprime_test_api):
    seq = """
Ref.recvBuffComp.PARAMETER4_PRM_SET(1 - 2 + 3 * 4 + 10 / 5 * 2)
param4: F32 = 15.0
Ref.recvBuffComp.PARAMETER4_PRM_SET(param4)

prm_3: U8 = Ref.sendBuffComp.parameter3
cmds_dispatched: U32 = CdhCore.cmdDisp.CommandsDispatched

signal_pair: Ref.SignalPair = Ref.SG1.PairOutput

signal_pair_time: F32 = Ref.SG1.PairOutput.time
com_queue_depth_0: U32 = ComCcsds.comQueue.comQueueDepth[0]
value: bool = 1 > 2 and (3 + 4) != 5
many_cmds_dispatched: bool = cmds_dispatched >= 123
record1: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
record2: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
records_equal: bool = record1 == record2 # == True
random_value: I8 = 4 # chosen by fair dice roll. guaranteed to be random

if random_value < 0:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("won't happen")
elif random_value > 0 and random_value <= 6:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("should happen!")
else:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("uh oh...")
"""
    assert_compile_failure(fprime_test_api, seq)


def test_unary_plus_unsigned(fprime_test_api):
    seq = """
var: U32 = 1
exit(+var == var)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_plus_signed(fprime_test_api):
    seq = """
var: I32 = 1
exit(+var == var)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_plus_float(fprime_test_api):
    seq = """
var: F32 = 1.0
exit(+var == var)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_minus_signed(fprime_test_api):
    seq = """
var: I32 = 1
exit(-var == -1)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_minus_float(fprime_test_api):
    seq = """
var: F32 = 1.0
exit(-var == -1.0)
"""
    assert_run_success(fprime_test_api, seq)


# this is an interesting case, because one side is unsigned
# has an unsigned intermediate, so the literal is converted to
# U64, but -1 is outside range of U64 so it fails to compile.
# what should really happen here? TODO should -var fail to compile?
# should intermediate type of unary minus be signed?
def test_negative_int_literal_unsigned_op(fprime_test_api):
    seq = """
var: U32 = 1
exit(-var == -1)
"""
    assert_run_success(fprime_test_api, seq)


def test_multi_arg_variable_arg_cmd(fprime_test_api):
    seq = """
var1: I32 = 1
var2: F32 = 1.0
var3: U8 = 8
CdhCore.cmdDisp.CMD_TEST_CMD_1(var1, var2, var3)
"""
    assert_run_success(fprime_test_api, seq)
