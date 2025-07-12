import ast
from pathlib import Path
import tempfile
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.numerical_types import U32Type, U8Type
from fprime_gds.common.fpy.bytecode.directives import (
    Directive,
    Sequence,
    serialize_directives,
)
from fprime_gds.common.fpy.compiler import compile
from fprime_gds.common.fpy.model import DirectiveErrorCode, FpySequencerModel
from fprime_gds.common.fpy.parser import parse
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.testing_fw.api import IntegrationTestAPI


def compile_seq(fprime_test_api, seq: str) -> Sequence:
    return compile(parse(seq), fprime_test_api.pipeline.dictionary_path)


def lookup_type(fprime_test_api, type_name: str):
    dictionary = fprime_test_api.pipeline.dictionary_path
    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    prm_json_dict_loader = PrmJsonLoader(dictionary)
    (prm_id_dict, prm_name_dict, versions) = prm_json_dict_loader.construct_dicts(
        dictionary
    )
    type_name_dict = cmd_json_dict_loader.parsed_types
    type_name_dict.update(ch_json_dict_loader.parsed_types)
    type_name_dict.update(prm_json_dict_loader.parsed_types)

    return type_name_dict[type_name]


def run_seq(
    fprime_test_api: IntegrationTestAPI,
    dirs: list[Directive],
    tlm: dict[str, bytes] = None,
):
    for idx, d in enumerate(dirs):
        print(idx, d)
    if tlm is None:
        tlm = {}
    file = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)

    serialize_directives(dirs, Path(file.name))

    # fprime_test_api.send_and_assert_command("ComFpy.cmdSeq.RUN", [file.name, "BLOCK"], timeout=4)

    model = FpySequencerModel()
    ch_json_dict_loader = ChJsonLoader(fprime_test_api.pipeline.dictionary_path)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        fprime_test_api.pipeline.dictionary_path
    )
    tlm_db = {}
    for chan_name, val in tlm.items():
        ch_template = ch_name_dict[chan_name]
        tlm_db[ch_template.get_id()] = val
        print("tlm", ch_template.get_id())
    ret = model.run(dirs, tlm_db)
    if ret != DirectiveErrorCode.NO_ERROR:
        raise RuntimeError("Sequence returned", ret)


def assert_compile_success(fprime_test_api, seq: str):
    compile_seq(fprime_test_api, seq)


def assert_run_success(fprime_test_api, seq: str, tlm: dict[str, bytes] = None):
    seq = compile_seq(fprime_test_api, seq)

    run_seq(fprime_test_api, seq, tlm)


def assert_compile_failure(fprime_test_api, seq: str):
    try:
        compile_seq(fprime_test_api, seq)
    except BaseException as e:
        return
    raise RuntimeError("compile_seq succeeded")


def assert_run_failure(fprime_test_api, seq: str):
    directives = compile_seq(fprime_test_api, seq)
    try:
        run_seq(fprime_test_api, directives)
    except BaseException as e:
        return
    raise RuntimeError("run_seq succeeded")


def test_simple_var(fprime_test_api):
    seq = """
var: U32 = 1
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


def test_var_wrong_rhs(fprime_test_api):
    seq = """
x: U32 = 1
var: U32 = x
"""

    assert_compile_failure(fprime_test_api, seq)


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
var: asdfasdfasdf = 1
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
FpyDemo.sendBuffComp.PARAMETER3_PRM_SET(4)
"""
    assert_run_success(fprime_test_api, seq)


def test_bad_enum_ctor(fprime_test_api):
    seq = """
FpyDemo.SG5.Settings(123, 0.5, 0.5, FpyDemo.SignalType(1))
"""
    assert_compile_failure(fprime_test_api, seq)


def test_cmd_with_enum(fprime_test_api):
    seq = """
FpyDemo.SG5.Settings(123, 0.5, 0.5, FpyDemo.SignalType.TRIANGLE)
"""
    assert_run_success(fprime_test_api, seq)


def test_instantiate_type_for_cmd(fprime_test_api):
    seq = """
FpyDemo.typeDemo.CHOICE_PAIR(FpyDemo.ChoicePair(FpyDemo.Choice.ONE, FpyDemo.Choice.TWO))
"""
    assert_run_success(fprime_test_api, seq)


def test_var_with_enum_type(fprime_test_api):
    seq = """
var: FpyDemo.Choice = FpyDemo.Choice.ONE
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
if ComFpy.cmdSeq.Debug.nextStatementOpcode == 0:
    # should be 0 because we aren't in debug mode
    exit(True)
exit(False)
"""

    assert_run_success(
        fprime_test_api,
        seq,
        {
            "ComFpy.cmdSeq.Debug": lookup_type(
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


def test_float_cmp(fprime_test_api):
    seq = """
if 4.0 > 5.0:
    exit(False)
exit(True)
"""

    assert_run_success(fprime_test_api, seq)


def test_wait_rel(fprime_test_api):
    seq = """
sleep(0, 1)
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
val3: I64 = -9223372036854775808  # Min I64, should be max i64 + 1 in unsigned

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


def test_type_mismatch_compile_error(fprime_test_api):
    seq = """
val1: U32 = -1  # Should fail: negative value in unsigned type
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
        exit(True)
exit(False)
"""
    # cannot currently compare booleans
    assert_compile_failure(fprime_test_api, seq)


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
CdhCore.cmdDisp.CMD_NO_OP_STRING(ComFpy.cmdSeq.SeqPath)
"""
    assert_run_success(fprime_test_api, seq)


def test_non_const_int_arg(fprime_test_api):
    seq = """
var: U8 = 255
FpyDemo.sendBuffComp.PARAMETER3_PRM_SET(var)
"""
    assert_run_success(fprime_test_api, seq)


def test_non_const_float_arg(fprime_test_api):
    seq = """
var: F32 = 1.2
FpyDemo.sendBuffComp.PARAMETER4_PRM_SET(var)
"""
    assert_run_success(fprime_test_api, seq)


def test_non_const_builtin_arg(fprime_test_api):
    seq = """
var: U32 = 123123
sleep(var, 0)
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
var1: F32 = -255
var2: F32 = 255
if var1 + var2 == 0 and (var1 + 1) > (var1 + -1):
    exit(True)
exit(False)
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
var1: F32 = 255
var2: F32 = 255
if var1 - var2 == 0 and (var1 - 1) < (var1 - -1):
    exit(True)
exit(False)
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
var1: F32 = 5
var2: F32 = 20
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
if var1 / var2 == -4 and (var1 / -2) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


def test_div_float(fprime_test_api):
    seq = """
var1: F32 = -20
var2: F32 = 5
if var1 / var2 == -4 and (var1 / -2) > var1:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)


# this test caught one bug (my mom spotted it)
def test_order_of_operations(fprime_test_api):
    seq = """
if 1 - 2 + 3 * 4 == 11 and 10 / 5 * 2 == 1:
    exit(True)
exit(False)
"""


def test_arithmetic_arg_to_builtin(fprime_test_api):
    seq = """
sleep(123 + 456 * 789, 0)
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
if var1 / var3 / var2 == 1:
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
var1: F32 = 4
var2: F32 = 0.5
if var1 ** var2 == 2:
    exit(True)
exit(False)
"""
    assert_run_success(fprime_test_api, seq)