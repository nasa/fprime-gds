import pytest

from fprime.common.models.serialize.numerical_types import U32Type as U32Value

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


def test_comment(fprime_test_api):
    seq = """
# test
"""

    assert_run_success(fprime_test_api, seq)


def test_empty(fprime_test_api):
    seq = """"""

    assert_run_success(fprime_test_api, seq)


def test_no_newline(fprime_test_api):
    seq = """# test"""

    assert_run_success(fprime_test_api, seq)


def test_simple_var(fprime_test_api):
    seq = """
var: U32 = 1
"""

    assert_run_success(fprime_test_api, seq)


def test_var_bad_name(fprime_test_api):
    seq = """
$var: U32 = 1
"""

    assert_compile_failure(fprime_test_api, seq)


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
var = 2.123
var = 100.5e+10
var = -123.456
"""

    assert_run_success(fprime_test_api, seq)


def test_bad_float_literal(fprime_test_api):
    seq = """
var: F32 = 1.
"""

    assert_compile_failure(fprime_test_api, seq)


def test_exit_success(fprime_test_api):
    seq = """
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_exit_failure(fprime_test_api):
    seq = """
exit(123)
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


def test_namespace_type_annotation_fails(fprime_test_api):
    seq = """
var: Svc = 1
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


def test_assign_function_value(fprime_test_api):
    seq = """
var: U32 = CdhCore.cmdDisp.CMD_NO_OP
"""

    assert_compile_failure(fprime_test_api, seq)


def test_call_cmd(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP()
"""
    assert_run_success(fprime_test_api, seq)


def test_call_namespace_fails(fprime_test_api):
    seq = """
CdhCore.cmdDisp()
"""

    assert_compile_failure(fprime_test_api, seq)


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

# use exit(0) if we want the sequence to succeed
# exit(1) if we want it to fail. helpful for testing.

if var:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_expr(fprime_test_api):
    seq = """
if True or False:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_not_expr(fprime_test_api):
    seq = """
if not False:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_expr_with_vars(fprime_test_api):
    seq = """
var1: bool = True
var2: bool = False

if var1 or var2:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_geq(fprime_test_api):
    seq = """
if 2 >= 1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_geq_tlm(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP()
# NOTE! this is not guaranteed to work, if the tlm gets written
# too slowly to the DB then this will fail
if CdhCore.cmdDisp.CommandsDispatched >= 1:
    exit(0)
exit(1)
"""

    assert_run_success(
        fprime_test_api,
        seq,
        {"CdhCore.cmdDisp.CommandsDispatched": U32Value(1).serialize()},
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
        {"CdhCore.cmdDisp.CommandsDispatched": U32Value(4).serialize()},
    )


def test_int_as_stmt(fprime_test_api):
    seq = """
2
"""

    assert_run_success(fprime_test_api, seq)


def test_expr_as_stmt(fprime_test_api):
    seq = """
2 + 2
"""

    assert_run_success(fprime_test_api, seq)


def test_str_as_stmt(fprime_test_api):
    seq = """
"test"
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_as_stmt(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP
"""

    assert_compile_failure(fprime_test_api, seq)


def test_get_struct_member_of_tlm(fprime_test_api):
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.ONE, Ref.Choice.ONE))
if Ref.typeDemo.ChoicePairCh.firstChoice == Ref.Choice.ONE:
    exit(0)
exit(1)
"""

    assert_run_success(
        fprime_test_api,
        seq,
        {
            "Ref.typeDemo.ChoicePairCh": lookup_type(fprime_test_api, "Ref.ChoicePair")(
                {"firstChoice": "ONE", "secondChoice": "ONE"}
            ).serialize()
        },
    )


def test_deeply_nested_loops_exhaust_recursion_depth(fprime_test_api):
    depth = 500
    loop_header_lines = [
        ("    " * level) + f"for i{level} in 0 .. 1:" for level in range(depth)
    ]
    seq = "\n" + "\n".join(loop_header_lines) + "\n" + ("    " * depth) + "pass\n"

    # Purposefully triggers RecursionError inside the compiler's parse transform.

    assert_compile_failure(fprime_test_api, seq)


def test_get_const_struct_member(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
if var.priority == 3:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_member_of_anon_expr(fprime_test_api):
    seq = """
var: U32 = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED).priority
if var == 3:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_time_member(fprime_test_api):
    seq = """
if Fw.Time(0, 1, 2, 3).useconds == 3:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_float_cmp(fprime_test_api):
    seq = """
if 4.0 > 5.0:
    exit(1)
exit(0)
"""

    assert_run_success(fprime_test_api, seq)


def test_wait_rel(fprime_test_api):
    seq = """
sleep(1, 1000)
"""
    assert_run_success(fprime_test_api, seq)


def test_wait_abs(fprime_test_api):
    seq = """
sleep_until(Fw.Time(2, 0, 123, 123))
"""
    assert_run_success(fprime_test_api, seq)


def test_wait_abs_var_arg(fprime_test_api):
    seq = """
x: U32 = 123
sleep_until(Fw.Time(2, 0, x, 123))
"""
    assert_run_success(fprime_test_api, seq)


def test_wait_abs_var_arg_2(fprime_test_api):
    seq = """
x: Fw.Time = Fw.Time(2, 1, 2, 3)
sleep_until(x)
"""
    assert_run_success(fprime_test_api, seq)


def test_wait_abs_bad_arg(fprime_test_api):
    seq = """
sleep_until(2, 1, 2, 3)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_time_type_ctor(fprime_test_api):
    seq = """
var: Fw.Time = Fw.Time(0, 1, 2, 3)
if var.time_base == 0 and var.time_context == 1:# and var.seconds == 2 and var.useconds == 3:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_struct_ctor_var_arg(fprime_test_api):
    seq = """
id: U32 = 111
priority: U32 = 3
state: Fw.DpState = Fw.DpState.UNTRANSMITTED
var: Svc.DpRecord = Svc.DpRecord(id, 1, 2, priority, 4, 5, state)
if var.priority == priority and var.id == id and state == var.state:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_array_ctor_var_arg(fprime_test_api):
    seq = """
arr_0: U32 = 123
arr_1: U32 = 456
val: Svc.ComQueueDepth = Svc.ComQueueDepth(arr_0, arr_1)
if val[0] == arr_0 and val[1] == arr_1:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_f32_f64_cmp(fprime_test_api):
    seq = """
val: F32 = 0.0
val2: F64 = 1.0
if val > val2:
    exit(1)
exit(0)
"""

    assert_run_success(fprime_test_api, seq)


def test_construct_array(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_item_of_array(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(222, 111)
if val[0] == 222:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_item_of_anon_expr(fprime_test_api):
    seq = """
if Svc.ComQueueDepth(123, 456)[1] == 456:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_i32_f64_cmp(fprime_test_api):
    seq = """
val: I32 = 2
val2: F64 = 1.0
if val > val2:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_i32_u32_cmp(fprime_test_api):
    seq = """
val: I32 = -2
val2: U32 = 2
# fails to compile, can't compare types of diff signedness
if val < val2:
    exit(1)
exit(0)
"""

    assert_compile_failure(fprime_test_api, seq)


# caught one bug
def test_float_int_literal_cmp(fprime_test_api):
    seq = """
if 1 < 2.0:
    exit(0)
exit(1)
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
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_if_true(fprime_test_api):
    seq = """
if True:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_false(fprime_test_api):
    seq = """
if False:
    exit(1)
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_else_true(fprime_test_api):
    seq = """
if True:
    exit(0)
else:
    exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_else_false(fprime_test_api):
    seq = """
if False:
    exit(1)
else:
    exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_if_elif_else(fprime_test_api):
    seq = """
if False:
    exit(1)
elif True:
    exit(0)
else:
    exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_and_true_true(fprime_test_api):
    seq = """
if True and True:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_and_true_false(fprime_test_api):
    seq = """
if True and False:
    exit(1)
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_false_false(fprime_test_api):
    seq = """
if False or False:
    exit(1)
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_or_true_false(fprime_test_api):
    seq = """
if True or False:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_not_true(fprime_test_api):
    seq = """
if not True:
    exit(1)
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_not_false(fprime_test_api):
    seq = """
if not False:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_and_or_not(fprime_test_api):
    seq = """
if not False and (True or False):
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_literal_comparison(fprime_test_api):
    seq = """
if 255 > 254:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_literal_comparison_false(fprime_test_api):
    seq = """
if 255 < 254:
    exit(1)
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_u8(fprime_test_api):
    seq = """
val1: U8 = 200
val2: U8 = 100

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_i8(fprime_test_api):
    seq = """
val1: I8 = 100
val2: I8 = -100

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_u32(fprime_test_api):
    seq = """
val1: U32 = 4294967295
val2: U32 = 0

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_i32(fprime_test_api):
    seq = """
val1: I32 = 2147483647
val2: I32 = -2147483648

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_f32(fprime_test_api):
    seq = """
val1: F32 = 3.14159
val2: F32 = -3.14159

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_all_comparison_operators_f64(fprime_test_api):
    seq = """
val1: F64 = 3.14159265359
val2: F64 = -3.14159265359

if val1 > val2 and val2 < val1:
    if val1 >= val2 and val2 <= val1:
        if val1 != val2 and not (val1 == val2):
            exit(0)
exit(1)
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
            exit(0)
exit(1)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_equality_edge_cases(fprime_test_api):
    seq = """
val1: U8 = 0
val2: U8 = 0
val3: F32 = 0.0
val4: F64 = 0.0
val5: I32 = 0

if val1 == val2 and val3 == val4 and val4 == val5:
    if not (val1 != val2) and not (val3 != val4) and not (val4 != val5):
        exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_nested_boolean_expressions(fprime_test_api):
    seq = """
if not (True and False or True and not False) and True:
    exit(1)  # Should not execute
exit(0)
"""
    assert_run_success(fprime_test_api, seq)


def test_maximum_integer_comparisons(fprime_test_api):
    seq = """
val_max: I64 = 9223372036854775807  # Max I64
val_mid: I64 = 1
val_min: I64 = -9223372036854775808  # Min I64

if val_max > val_mid and val_mid > val_min:
    if val_min < val_max:
        exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_type_assignments(fprime_test_api):
    seq = """
val1: I8 = 127
val2: U8 = 255
val3: F32 = 127.0

if val1 == val3:  # Integer to float comparison
    if val2 > val3:  # Unsigned vs float comparison
        exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_negative_val_unsigned_type(fprime_test_api):
    seq = """
val1: U32 = -1
"""
    assert_compile_failure(fprime_test_api, seq)


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
        exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_complex_boolean_nesting(fprime_test_api):
    seq = """
if not not not not not True:  # Multiple not operators
    exit(1)
elif not (True and not (False or not True)):  # Complex nesting
    exit(1)
else:
    exit(0)
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
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_add_signed(fprime_test_api):
    seq = """
var1: I32 = -255
var2: I32 = 255
if var1 + var2 == 0 and (var1 + 1) > (var1 + -1):
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_add_float(fprime_test_api):
    seq = """
var1: F32 = -255.0
var2: F32 = 255.0
if var1 + var2 == 0.0 and (var1 + 1.0) > (var1 + -1.0):
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


# this test inspired by a bug
def test_float_truncate_stack_size(fprime_test_api):
    seq = """
var2: F64 = 123.0
var1: F32 = F32(-var2)
if var1 == -123.0:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_sub_unsigned(fprime_test_api):
    seq = """
var1: U32 = 1000
var2: U32 = 500
if var1 - var2 == 500 and (var1 - 1) < var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_sub_signed(fprime_test_api):
    seq = """
var1: I32 = 255
var2: I32 = 255
if var1 - var2 == 0 and (var1 - 1) < (var1 - -1):
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_sub_float(fprime_test_api):
    seq = """
var1: F32 = 255.0
var2: F32 = 255.0
if var1 - var2 == 0.0 and (var1 - 1.0) < (var1 - -1.0):
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_mul_unsigned(fprime_test_api):
    seq = """
var1: U32 = 5
var2: U32 = 20
if var1 * var2 == 100 and (var1 * 2) > var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_mul_signed(fprime_test_api):
    seq = """
var1: I32 = -5
var2: I32 = 20
if var1 * var2 == -100 and (var1 * 2) < var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_mul_float(fprime_test_api):
    seq = """
var1: F32 = 5.0
var2: F32 = 20.0
if var1 * var2 == 100.0 and (var1 * 2.0) > var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_unsigned(fprime_test_api):
    seq = """
var1: U32 = 20
var2: U32 = 5
if var1 / var2 == 4.0 and (var1 / 2) < var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_signed(fprime_test_api):
    seq = """
var1: I32 = -20
var2: I32 = 5
if var1 / var2 == -4.0: # and (var1 / -2) > var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_float(fprime_test_api):
    seq = """
var1: F32 = -20.0
var2: F32 = 5.0
if var1 / var2 == -4.0 and (var1 / -2.0) > var1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


# this test caught one bug (my mom spotted it)
def test_order_of_operations(fprime_test_api):
    seq = """
if 1 - 2 + 3 * 4 == 11 and 10.0 / 5.0 * 2.0 == 4.0:
    exit(0)
exit(1)
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
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_add(fprime_test_api):
    seq = """
var1: I32 = 1
var2: I32 = 2
var3: I32 = 3
if var1 + var2 + var3 == 6:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_sub(fprime_test_api):
    seq = """
var1: I32 = 1
var2: I32 = 2
var3: I32 = 3
if var1 - var2 - var3 == -4:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_chain_div(fprime_test_api):
    seq = """
var1: I32 = 3
var2: I32 = 2
var3: I32 = 1
if var1 / var3 / var2 == 3/2:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_pow_unsigned(fprime_test_api):
    seq = """
var1: U32 = 20
var2: U32 = 2
if var1 ** var2 == 400:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_pow_signed(fprime_test_api):
    seq = """
var1: I32 = -20
var2: I32 = 2
if var1 ** var2 == 400:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_pow_float(fprime_test_api):
    seq = """
var1: F32 = 4.0
var2: F32 = 0.5
if var1 ** var2 == 2:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_int_literal_as_float(fprime_test_api):
    seq = """
var: F32 = 1
if var == 1.0:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_log(fprime_test_api):
    seq = """
if log(4.0) > 1.385 and log(4.0) < 1.387:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_assign_complex(fprime_test_api):
    seq = """
var: I64 = 1 + 1
var = var + 3
if var == 5:
    exit(0)
exit(1)
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
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_cmd_return_val(fprime_test_api):
    seq = """
ret: Fw.CmdResponse = CdhCore.cmdDisp.CMD_NO_OP()
if ret == Fw.CmdResponse.OK:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_struct_eq(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var2: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var3: Svc.DpRecord = Svc.DpRecord(123, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
if var == var2 and var != var3:
    exit(0)
exit(1)
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
if var1 % var2 == 0.25 and (var1 + 1) % var2 == 1.25:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_mod_unsigned(fprime_test_api):
    seq = """
var1: U32 = 5
var2: U32 = 20
if var2 % var1 == 0 and (var2 + 1) % var1 == 1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_mod_signed(fprime_test_api):
    seq = """
var1: I32 = -5
var2: I32 = 20
if var2 % var1 == 0 and (var2 + 1) % var1 == -4:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


@pytest.mark.parametrize(
    "lhs_type,rhs_type,lhs_value,rhs_value,result_type,expected_value",
    [
        ("U64", "I64", "9", "2", "U64", "4"),
        ("U64", "U64", "9", "2", "U64", "4"),
        ("F64", "F64", "5.5", "2.0", "F64", "2.0"),
        ("F64", "F64", "-5.5", "2.0", "F64", "-2.0"),
        ("F64", "I64", "5.5", "2", "F64", "2.0"),
        ("I64", "F64", "5", "2.5", "F64", "2.0"),
        ("U64", "F64", "9", "2.0", "F64", "4.0"),
        ("F64", "U64", "9.0", "2", "F64", "4.0"),
    ],
)
def test_floor_divide_64_bit_numeric_types(
    fprime_test_api,
    lhs_type,
    rhs_type,
    lhs_value,
    rhs_value,
    result_type,
    expected_value,
):
    seq = f"""
lhs: {lhs_type} = {lhs_value}
rhs: {rhs_type} = {rhs_value}
result: {result_type} = lhs // rhs
assert result == {expected_value}
"""

    assert_run_success(fprime_test_api, seq)


@pytest.mark.parametrize(
    "lhs_type,rhs_type,lhs_value,rhs_value,result_type,expected_value",
    [
        ("I64", "U64", "9", "2", "U64", "4"),
        ("U64", "I64", "9", "2", "U64", "4"),
    ],
)
def test_floor_divide_64_bit_numeric_types(
    fprime_test_api,
    lhs_type,
    rhs_type,
    lhs_value,
    rhs_value,
    result_type,
    expected_value,
):
    seq = f"""
lhs: {lhs_type} = {lhs_value}
rhs: {rhs_type} = {rhs_value}
result: {result_type} = lhs // rhs
assert result == {expected_value}
"""

    assert_compile_failure(fprime_test_api, seq)


def test_bool_stack_value(fprime_test_api):
    seq = """
if (1 == 1) == True:
    exit(0)
exit(1)
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
    from fprime_gds.common.fpy.types import MAX_DIRECTIVES_COUNT

    seq = "CdhCore.cmdDisp.CMD_NO_OP()\n" * (MAX_DIRECTIVES_COUNT + 1)
    assert_compile_failure(fprime_test_api, seq)


def test_dir_too_large(fprime_test_api):
    # TODO this doesn't actually crash cuz the dir is too large... not sure at the moment how to trigger this
    from fprime_gds.common.fpy.types import MAX_DIRECTIVE_SIZE

    seq = 'CdhCore.cmdDisp.CMD_NO_OP_STRING("' + "a" * MAX_DIRECTIVE_SIZE + '")'
    assert_compile_failure(fprime_test_api, seq)


def test_readme_examples(fprime_test_api):
    seq = """
Ref.sendBuffComp.PARAMETER4_PRM_SET(1 - 2 + 3 * 4 + 10 / 5 * 2)
param4: F32 = 15.0
Ref.sendBuffComp.PARAMETER4_PRM_SET(param4)

#prm_3: U8 = Ref.sendBuffComp.parameter3
#cmds_dispatched: U32 = CdhCore.cmdDisp.CommandsDispatched
cmds_dispatched: U32 = 0

signal_pair: Ref.SignalPair = Ref.SignalPair(0, 0)

signal_pair.time = 0.2

# Svc.ComQueueDepth is an array type
com_queue_depth: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
com_queue_depth[0] = 1
#signal_pair_time: F32 = Ref.SG1.PairOutput.time
#com_queue_depth_0: U32 = ComCcsds.comQueue.comQueueDepth[0]


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
counter: U64 = 0
while counter < 100:
    counter = counter + 1

assert counter == 100
sum: I64 = 0
# loop i from 0 inclusive to 5 exclusive
for i in 0 .. 5:
    sum = sum + i

assert sum == 10
counter = 0
while True:
    counter = counter + 1
    if counter == 100:
        break

assert counter == 100
odd_numbers_sum: I64 = 0
for i in 0 .. 10:
    if i % 2 == 0:
        continue
    odd_numbers_sum = odd_numbers_sum + i

assert odd_numbers_sum == 25

low_bitwidth_int: U8 = 123
high_bitwidth_int: U32 = low_bitwidth_int
# high_bitwidth_int == 123
low_bitwidth_float: F32 = 123.0
high_bitwidth_float: F64 = low_bitwidth_float
# high_bitwidth_float == 123.0
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_plus_unsigned(fprime_test_api):
    seq = """
var: U32 = 1
if +var == var:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_plus_signed(fprime_test_api):
    seq = """
var: I32 = 1
if +var == var:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_plus_float(fprime_test_api):
    seq = """
var: F32 = 1.0
if +var == var:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_minus_signed(fprime_test_api):
    seq = """
var: I32 = 1
if -var == -1:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_unary_minus_float(fprime_test_api):
    seq = """
var: F32 = 1.0
if -var == -1.0:
    exit(0)
exit(1)
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
if -var == -1:
    exit(0)
exit(1)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_multi_arg_variable_arg_cmd(fprime_test_api):
    seq = """
var1: I32 = 1
var2: F32 = 1.0
var3: U8 = 8
CdhCore.cmdDisp.CMD_TEST_CMD_1(var1, var2, var3)
"""
    assert_run_success(fprime_test_api, seq)


def test_weird_arg_type(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP_STRING(CdhCore.cmdDisp.CMD_NO_OP_STRING)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_func_bad_type(fprime_test_api):
    seq = """
var: U32 = 1
(var + 1)(3)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_field_with_type_ann_bad(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var.priority = 123
if var.priority == 123:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_assign_field_with_type_ann_bad_2(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var.priority: U8 = 123
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_field_before_declare(fprime_test_api):
    seq = """
var.priority = 123
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_array_element(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
val[0] = 55
if val[0] == 55:
    exit(0)
exit(1)
"""
    assert_run_success(fprime_test_api, seq)


def test_assign_array_element_with_type_ann_bad(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
val[0]: U8 = 55
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_bad_lhs_1(fprime_test_api):
    seq = """
Svc.ComQueueDepth = 55
"""
    assert_compile_failure(fprime_test_api, seq)


def test_assign_bad_lhs_2(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP = 55
"""
    assert_compile_failure(fprime_test_api, seq)


# TODO test deep field access/assignments (2+ levels)


def test_assign_tlm_struct_member_bad(fprime_test_api):
    seq = """
Ref.cmdSeq.Debug.nextStatementOpcode = 0
"""

    assert_compile_failure(fprime_test_api, seq)


def test_set_item_of_anon_expr(fprime_test_api):
    seq = """
Svc.ComQueueDepth(123, 456)[1] = 456
"""

    assert_compile_failure(fprime_test_api, seq)


def test_set_member_of_anon_expr(fprime_test_api):
    seq = """
Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED).priority = 5
"""

    assert_compile_failure(fprime_test_api, seq)


def test_array_oob_1(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
val[2] = 3
"""
    assert_compile_failure(fprime_test_api, seq)


def test_array_oob_2(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(123, 456)
if val[-1] == 456:
    exit(0)
exit(1)
"""
    # TODO in the future this should work, should be the last element
    assert_compile_failure(fprime_test_api, seq)


def test_get_variable_array_idx(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(456, 123)
idx: U8 = 1
if val[idx] == 123:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_get_variable_array_idx_oob(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(456, 123)
idx: U8 = 2
if val[idx] == 123:
    exit(0)
exit(1)
"""

    assert_run_failure(fprime_test_api, seq)


def test_set_variable_array_idx_oob(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(456, 123)
idx: U8 = 2
val[idx] = 111
"""

    assert_run_failure(fprime_test_api, seq)


def test_set_variable_array_idx(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(456, 123)
idx: U8 = 1
val[idx] = 111
if val[1] == 111:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_break_outside_loop(fprime_test_api):
    seq = """
break
"""

    assert_compile_failure(fprime_test_api, seq)


def test_continue_outside_loop(fprime_test_api):
    seq = """
continue
"""

    assert_compile_failure(fprime_test_api, seq)


def test_simple_for(fprime_test_api):
    seq = """
for i in 0..2:
    pass
"""

    assert_run_success(fprime_test_api, seq)


def test_for_loop_break(fprime_test_api):
    seq = """
for i in 0 .. 10:
    break
assert i == 0
"""
    assert_run_success(fprime_test_api, seq)


def test_for_loop_continue(fprime_test_api):
    seq = """
for i in 0 .. 10:
    continue
assert i == 10 # will be equal to the ending index
"""
    assert_run_success(fprime_test_api, seq)


def test_nested_for_while_break(fprime_test_api):
    seq = """
for i in 0 .. 10:
    while True:
        break
assert i == 10
"""
    assert_run_success(fprime_test_api, seq)


def test_nested_for_loops_break_inner(fprime_test_api):
    seq = """
for i in 0 .. 10:
    for j in 0 .. 5:
        break
assert i == 10 and j == 0
"""
    assert_run_success(fprime_test_api, seq)


def test_nested_for_loops_break_outer(fprime_test_api):
    seq = """
for i in 0 .. 10:
    for j in 0 .. 5:
        break
    break
"""
    assert_run_success(fprime_test_api, seq)


def test_slightly_more_complex_for(fprime_test_api):
    seq = """
counter: U8 = 0
for i in 0 .. 2:
    if i > 2:
        exit(1)
    counter = U8(counter + 1)


assert counter == 2
"""

    assert_run_success(fprime_test_api, seq)


def test_loop_var_outside_loop_after(fprime_test_api):
    seq = """
for i in 0 .. 7:
    pass
assert i == 7
# succeeds because i is declared in the scope of for
i = 123
assert i == 123
"""

    assert_run_success(fprime_test_api, seq)


def test_loop_var_outside_loop_before(fprime_test_api):
    seq = """
i = 123
for i in 0 .. 7:
    pass
"""

    assert_compile_failure(fprime_test_api, seq)


def test_loop_var_redeclare_right_type(fprime_test_api):
    seq = """
i: I64 = 123
for i in 0 .. 7:
    assert i >= 0 and i < 7
assert i == 7
"""
    assert_run_success(fprime_test_api, seq)


def test_two_fors_same_loop_var(fprime_test_api):
    seq = """
for i in 0 .. 7:
    assert i >= 0 and i < 7
for i in 0 .. 7:
    assert i >= 0 and i < 7
assert i == 7
"""
    assert_run_success(fprime_test_api, seq)


def test_loop_var_redeclare_wrong_type(fprime_test_api):
    seq = """
i: U16 = 123
for i in 0 .. 7:
    pass
"""

    assert_compile_failure(fprime_test_api, seq)


def test_scope_override_name(fprime_test_api):
    seq = """
i: U8 = 0
while True:
    # fails because while does not begin a new scope
    i: U8 = 1
    if i == 1:
        exit(0)
    exit(1)
"""

    assert_compile_failure(fprime_test_api, seq)


def test_override_global_name(fprime_test_api):
    seq = """
CdhCore: U8 = 1
if CdhCore == 1:
    exit(0)
exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_assert(fprime_test_api):
    seq = """
assert True
assert not False
"""

    assert_run_success(fprime_test_api, seq)


def test_assert_failure(fprime_test_api):
    seq = """
assert False
"""

    assert_run_failure(fprime_test_api, seq)


def test_assert_failure_with_exit_code(fprime_test_api):
    seq = """
assert False, 123
"""

    assert_run_failure(fprime_test_api, seq)


def test_assert_wrong_bool_type(fprime_test_api):
    seq = """
assert 123
"""

    assert_compile_failure(fprime_test_api, seq)


def test_assert_wrong_exit_code_type(fprime_test_api):
    seq = """
assert True, True
"""

    assert_compile_failure(fprime_test_api, seq)


def test_redeclare_after_scope(fprime_test_api):
    seq = """
for i in 0 .. 7:
    pass
i: U16 = 0
assert i == 0
"""

    assert_compile_failure(fprime_test_api, seq)


def test_nested_for_loops(fprime_test_api):
    seq = """
z: U8 = 123
for i in 0 .. 7:
    for y in 20 .. 30:
        assert i < 8
        assert y >= 20 and y < 30
        assert z == 123
"""

    assert_run_success(fprime_test_api, seq)


def test_redeclare_in_nested_scopes(fprime_test_api):
    seq = """
z: U8 = 123
for i in 0 .. 7:
    for z in 0 .. 7:
        assert z < 8
"""

    assert_compile_failure(fprime_test_api, seq)


def test_for_loop_declare_var_bad(fprime_test_api):
    seq = """
for x.y in 0 .. 7:
    pass
"""

    assert_compile_failure(fprime_test_api, seq)


def test_use_loop_var_in_bounds(fprime_test_api):
    seq = """
for i in i .. 8:
    pass
"""

    assert_compile_failure(fprime_test_api, seq)


def test_get_time(fprime_test_api):
    seq = """
time: Fw.Time = now()
"""

    assert_run_success(fprime_test_api, seq)


def test_signed_int_const_casts(fprime_test_api):
    seq = """
assert I8(-256) == 0
assert I8(-129) == 127
assert I16(-65536) == 0
assert I16(-32769) == 32767
assert I32(-4294967296) == 0
assert I32(-2147483649) == 2147483647
assert I64(-18446744073709551616) == 0
assert I64(-9223372036854775809) == 9223372036854775807
"""

    assert_run_success(fprime_test_api, seq)


def test_unsigned_int_const_casts(fprime_test_api):
    seq = """
assert U8(-1) == 255
assert U8(256) == 0
assert U16(-1) == 65535
assert U16(65536) == 0
assert U32(-1) == 4294967295
assert U32(4294967296) == 0
assert U64(-1) == 18446744073709551615
assert U64(18446744073709551616) == 0
"""

    assert_run_success(fprime_test_api, seq)


def test_float_const_casts(fprime_test_api):
    seq = """
assert F32(0.5) == 0.5
assert F32(-0.75) == -0.75
assert F32(1024.0) == 1024.0
assert F32(-2048.0) == -2048.0
assert F64(0.5) == 0.5
assert F64(-0.75) == -0.75
assert F64(123456789.5) == 123456789.5
assert F64(-987654321.25) == -987654321.25
"""

    assert_run_success(fprime_test_api, seq)


def test_float_to_signed_int_const_casts(fprime_test_api):
    seq = """
assert I8(-128.0) == -128
assert I8(127.0) == 127
assert I16(-32768.0) == -32768
assert I16(32767.0) == 32767
assert I32(-2147483648.0) == -2147483648
assert I32(2147483647.0) == 2147483647
"""

    assert_run_success(fprime_test_api, seq)


def test_float_to_unsigned_int_const_casts(fprime_test_api):
    seq = """
assert U8(0.0) == 0
assert U8(255.0) == 255
assert U16(65535.0) == 65535
assert U32(4294967295.0) == 4294967295
"""

    assert_run_success(fprime_test_api, seq)


def test_signed_int_to_float_const_casts(fprime_test_api):
    seq = """
assert F32(-128) == -128.0
assert F64(-128) == -128.0
assert F32(32767) == 32767.0
assert F64(32767) == 32767.0
assert F64(-2147483648) == -2147483648.0
assert F64(2147483647) == 2147483647.0
"""

    assert_run_success(fprime_test_api, seq)


def test_unsigned_int_to_float_const_casts(fprime_test_api):
    seq = """
assert F32(U32(0)) == 0.0
assert F64(U32(0)) == 0.0
assert F32(U32(65535)) == 65535.0
assert F64(U32(65535)) == 65535.0
assert F64(U64(4294967295)) == 4294967295.0
"""

    assert_run_success(fprime_test_api, seq)


def test_signed_int_runtime_casts(fprime_test_api):
    seq = """
src: I64 = -256
assert I8(src) == 0

src = -129
assert I8(src) == 127

src = -65536
assert I16(src) == 0

src = -32769
assert I16(src) == 32767

src = -4294967296
assert I32(src) == 0

src = -2147483649
assert I32(src) == 2147483647
"""

    assert_run_success(fprime_test_api, seq)


def test_unsigned_int_runtime_casts(fprime_test_api):
    seq = """
signed_src: I64 = -1
assert U8(signed_src) == 255
assert U16(signed_src) == 65535
assert U32(signed_src) == 4294967295
assert U64(signed_src) == 18446744073709551615

unsigned_src: U64 = 256
assert U8(unsigned_src) == 0

unsigned_src = 65536
assert U16(unsigned_src) == 0

unsigned_src = 4294967296
assert U32(unsigned_src) == 0
"""

    assert_run_success(fprime_test_api, seq)


def test_float_runtime_casts(fprime_test_api):
    seq = """
wide_src: F64 = 0.5
assert F32(wide_src) == 0.5

wide_src = -0.75
assert F32(wide_src) == -0.75

wide_src = 1024.0
assert F32(wide_src) == 1024.0

wide_src = -2048.0
assert F32(wide_src) == -2048.0

narrow_src: F32 = 0.5
assert F64(narrow_src) == 0.5

narrow_src = -0.75
assert F64(narrow_src) == -0.75

narrow_src = 123.5
assert F64(narrow_src) == 123.5

narrow_src = -987.25
assert F64(narrow_src) == -987.25
"""

    assert_run_success(fprime_test_api, seq)


def test_float_to_signed_int_runtime_casts(fprime_test_api):
    seq = """
f_src: F64 = -128.0
assert I8(f_src) == -128

f_src = 127.0
assert I8(f_src) == 127

f_src = -32768.0
assert I16(f_src) == -32768

f_src = 32767.0
assert I16(f_src) == 32767

f_src = -2147483648.0
assert I32(f_src) == -2147483648

f_src = 2147483647.0
assert I32(f_src) == 2147483647
"""

    assert_run_success(fprime_test_api, seq)


def test_float_to_unsigned_int_runtime_casts(fprime_test_api):
    seq = """
f_src: F64 = 0.0
assert U8(f_src) == 0

f_src = 255.0
assert U8(f_src) == 255

f_src = 65535.0
assert U16(f_src) == 65535

f_src = 4294967295.0
assert U32(f_src) == 4294967295
"""

    assert_run_success(fprime_test_api, seq)


def test_signed_int_to_float_runtime_casts(fprime_test_api):
    seq = """
i_src: I32 = -128
assert F32(i_src) == -128.0
assert F64(i_src) == -128.0

i_src = 32767
assert F32(i_src) == 32767.0
assert F64(i_src) == 32767.0

wide_src: I64 = -2147483648
assert F64(wide_src) == -2147483648.0

wide_src = 2147483647
assert F64(wide_src) == 2147483647.0
"""

    assert_run_success(fprime_test_api, seq)


def test_unsigned_int_to_float_runtime_casts(fprime_test_api):
    seq = """
u_src: U32 = 0
assert F32(u_src) == 0.0
assert F64(u_src) == 0.0

u_src = 65535
assert F32(u_src) == 65535.0
assert F64(u_src) == 65535.0

wide_src: U64 = 4294967295
assert F64(wide_src) == 4294967295.0
"""

    assert_run_success(fprime_test_api, seq)


def test_downcast(fprime_test_api):
    seq = """
i: U32 = 123123
u: U8 = U8(i)
assert u == (i % 256)
"""

    assert_run_success(fprime_test_api, seq)


def test_downcast_fail(fprime_test_api):
    seq = """
i: U32 = 123123
u: U8 = i
"""

    assert_compile_failure(fprime_test_api, seq)


def test_upcast(fprime_test_api):
    seq = """
i: U8 = 255
u: U32 = U32(i)
assert u == i
"""

    assert_run_success(fprime_test_api, seq)


def test_wrong_bool_type(fprime_test_api):
    seq = """
val: bool = 123
"""

    assert_compile_failure(fprime_test_api, seq)


def test_while_break_in_if(fprime_test_api):
    seq = """
while True:
    if True:
        break
    exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_for_break_in_if(fprime_test_api):
    seq = """
for i in 0 .. 100:
    if True:
        break
    exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_while_continue_in_if(fprime_test_api):
    seq = """
i: U64 = 0
while i < 2:
    i = i + 1
    if True:
        continue
    exit(1)
"""

    assert_run_success(fprime_test_api, seq)


def test_for_continue_in_if(fprime_test_api):
    seq = """
sum: U64 = 0
for i in 0 .. 100:
    sum = sum + 1
    if True:
        continue
    exit(1)
assert sum == 100
"""

    assert_run_success(fprime_test_api, seq)


def test_downcast_large_literal(fprime_test_api):
    seq = """
val: U8 = U8(1231231231243) # this is allowed but suspicious
"""

    assert_run_success(fprime_test_api, seq)


@pytest.mark.xfail(reason="Support for non utf-8 characters should be added later")
def test_non_utf_8(fprime_test_api):
    seq = """
val: F64 = 0.0 

CdhCore.cmdDisp.CMD_NO_OP_STRING("в")
"""
    assert_run_success(fprime_test_api, seq)


# TODO assert failure should split based on whether it's a syntax or semantic failure


def test_abs_float(fprime_test_api):
    seq = """
assert fabs(1.0) == 1.0
assert fabs(-1.0) == 1.0
assert fabs(0.0) == 0.0
"""

    assert_run_success(fprime_test_api, seq)


def test_abs_i64(fprime_test_api):
    seq = """
assert iabs(I64(-1)) == 1
assert iabs(I64(1)) == 1
assert iabs(I64(0)) == 0
# need to use a large subtract here cuz otherwise float precision kills us... this is kinda sus
assert iabs(I64(2**63 - 6556)) == 2**63 - 6556
"""

    assert_run_success(fprime_test_api, seq)


def test_abs_u64(fprime_test_api):
    seq = """
# fails, iabs takes signed
assert iabs(U64(1)) == 1
assert iabs(U64(0)) == 0
"""

    assert_compile_failure(fprime_test_api, seq)


def test_abs_literal_int(fprime_test_api):
    seq = """
assert iabs(1) == 1
assert iabs(-1) == 1
"""

    assert_run_success(fprime_test_api, seq)


def test_abs_literal_float(fprime_test_api):
    seq = """
assert fabs(1.0) == 1.0
assert fabs(-1.0) == 1.0
"""

    assert_run_success(fprime_test_api, seq)


def test_var_type_ann_bad(fprime_test_api):
    seq = """
var: Fw.Time.asdf = 0
"""

    assert_compile_failure(fprime_test_api, seq)


def test_var_type_ann_bad_2(fprime_test_api):
    seq = """
var: Svc = 0
"""

    assert_compile_failure(fprime_test_api, seq)


def test_const_folding_time_eq(fprime_test_api):
    seq = """
assert Fw.Time(0, 0, 0, 0) == Fw.Time(0, 0, 0, 0)
assert Fw.Time(0, 0, 1, 0) != Fw.Time(0, 0, 0, 0)
"""

    assert_run_success(fprime_test_api, seq)


def test_calling_struct_field_should_fail_gracefully(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
var.priority()
"""

    assert_compile_failure(fprime_test_api, seq)


def test_calling_namespace_should_fail_gracefully(fprime_test_api):
    seq = """
Ref.typeDemo()
"""

    assert_compile_failure(fprime_test_api, seq)


def test_calling_variable_should_fail_gracefully(fprime_test_api):
    seq = """
x: U32 = 1
x()
"""

    assert_compile_failure(fprime_test_api, seq)


def test_const_divide_by_zero(fprime_test_api):
    seq = """
1 / 0
"""

    assert_compile_failure(fprime_test_api, seq)


def test_const_complex_pow(fprime_test_api):
    seq = """
(-1) ** 0.5
"""

    assert_compile_failure(fprime_test_api, seq)


def test_very_large_const_pow(fprime_test_api):
    seq = """
10.0 ** 1000
"""

    assert_run_success(fprime_test_api, seq)


def test_func_call_a_namespace(fprime_test_api):
    seq = """
CdhCore.cmdDisp()
"""
    assert_compile_failure(fprime_test_api, seq)


def test_missing_struct_member(fprime_test_api):
    seq = """
record: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
value: U32 = record.missing_field
"""
    assert_compile_failure(fprime_test_api, seq)


def test_get_item_of_struct(fprime_test_api):
    seq = """
record: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
value: U32 = record[0]
"""
    assert_compile_failure(fprime_test_api, seq)


def test_get_item_of_namespace(fprime_test_api):
    seq = """
value: U32 = CdhCore.cmdDisp[0]
"""
    assert_compile_failure(fprime_test_api, seq)


def test_literal_float_coercion_overflow(fprime_test_api):
    seq = """
var: F32 = 999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999
"""

    assert_compile_failure(fprime_test_api, seq)


def test_empty_range(fprime_test_api):
    seq = """
for i in 7..0:
    exit(1)
"""
    assert_run_success(fprime_test_api, seq)
