import ast
from pathlib import Path
import tempfile
from fprime_gds.common.fpy.bytecode.directives import Directive
from fprime_gds.common.fpy.bytecode.serialize_bytecode import serialize_directives
from fprime_gds.common.fpy.compiler import compile
from fprime_gds.common.fpy.parser import parse
from fprime_gds.common.testing_fw.api import IntegrationTestAPI


def compile_seq(fprime_test_api, seq: str) -> list[Directive]:
    return compile(parse(seq), fprime_test_api.pipeline.dictionary_path)


def run_seq(fprime_test_api: IntegrationTestAPI, seq: str):
    directives = compile_seq(fprime_test_api, seq)

    file = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)

    serialize_directives(directives, Path(file.name))

    fprime_test_api.send_and_assert_command("ComFpy.cmdSeq.RUN", [file.name, "BLOCK"])


def assert_compile_success(fprime_test_api, seq: str):
    compile_seq(fprime_test_api, seq)


def assert_run_success(fprime_test_api, seq: str):
    run_seq(fprime_test_api, seq)


def assert_compile_failure(fprime_test_api, seq: str):
    try:
        compile_seq(fprime_test_api, seq)
    except BaseException as e:
        return
    raise RuntimeError("compile_seq succeeded")


def assert_run_failure(fprime_test_api, seq: str):
    try:
        run_seq(fprime_test_api, seq)
    except BaseException as e:
        return
    raise RuntimeError("run_seq succeeded")


def test_simple_var(fprime_test_api):
    seq = """
var: U32 = 1
"""

    assert_compile_success(fprime_test_api, seq)


def test_large_var(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
"""

    assert_compile_success(fprime_test_api, seq)


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

    assert_compile_success(fprime_test_api, seq)


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
    assert_compile_success(fprime_test_api, seq)


def test_call_cmd_with_str_arg(fprime_test_api):
    seq = """
CdhCore.cmdDisp.CMD_NO_OP_STRING("hello world")
"""
    assert_compile_success(fprime_test_api, seq)


def test_call_cmd_with_int_arg(fprime_test_api):
    seq = """
FpyDemo.sendBuffComp.PARAMETER3_PRM_SET(4)
"""
    assert_compile_success(fprime_test_api, seq)


def test_bad_enum_ctor(fprime_test_api):
    seq = """
FpyDemo.SG5.Settings(123, 0.5, 0.5, FpyDemo.SignalType(1))
"""
    assert_compile_failure(fprime_test_api, seq)


def test_cmd_with_enum(fprime_test_api):
    seq = """
FpyDemo.SG5.Settings(123, 0.5, 0.5, FpyDemo.SignalType.TRIANGLE)
"""
    assert_compile_success(fprime_test_api, seq)


def test_instantiate_type_for_cmd(fprime_test_api):
    seq = """
FpyDemo.typeDemo.CHOICE_PAIR(FpyDemo.ChoicePair(FpyDemo.Choice.ONE, FpyDemo.Choice.TWO))
"""
    assert_compile_success(fprime_test_api, seq)


def test_var_with_enum_type(fprime_test_api):
    seq = """
var: FpyDemo.Choice = FpyDemo.Choice.ONE
"""

    assert_compile_success(fprime_test_api, seq)


def test_simple_if(fprime_test_api):
    seq = """
var: bool = True

if var:
    pass
"""
    assert_compile_success(fprime_test_api, seq)


def test_or_expr(fprime_test_api):
    seq = """
if True or False:
    pass
"""
    assert_compile_success(fprime_test_api, seq)


def test_not_expr(fprime_test_api):
    seq = """
if not False:
    pass
"""
    assert_compile_success(fprime_test_api, seq)


def test_or_expr_with_vars(fprime_test_api):
    seq = """
var1: bool = True
var2: bool = False

if var1 or var2:
    pass
"""
    assert_compile_success(fprime_test_api, seq)


def test_geq(fprime_test_api):
    seq = """
if 2 >= 1:
    pass
"""
    assert_compile_success(fprime_test_api, seq)


def test_geq_tlm(fprime_test_api):
    seq = """
if CdhCore.cmdDisp.CommandsDispatched > 1:
    pass
"""

    assert_compile_success(fprime_test_api, seq)


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
elif CdhCore.cmdDisp.CommandsDispatched == 5:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("5")
elif CdhCore.cmdDisp.CommandsDispatched == 6:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("6")
elif CdhCore.cmdDisp.CommandsDispatched == 7:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("7")
elif CdhCore.cmdDisp.CommandsDispatched == 8:
    CdhCore.cmdDisp.CMD_NO_OP_STRING("8")
else:
    CdhCore.cmdDisp.CMD_NO_OP_STRING(">8")
"""

    assert_compile_success(fprime_test_api, seq)


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
if ComFpy.cmdSeq.Debug.nextStatementOpcode == 8:
    pass
"""

    assert_compile_success(fprime_test_api, seq)


def test_get_const_struct_member(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
if var.priority == 1:
    pass
"""

    assert_compile_success(fprime_test_api, seq)


def test_float_cmp(fprime_test_api):
    seq = """
if 4.0 > 5.0:
    pass
"""

    assert_compile_success(fprime_test_api, seq)


def test_exit(fprime_test_api):
    seq = """
exit(False)
"""
    assert_compile_success(fprime_test_api, seq)


def test_wait_rel(fprime_test_api):
    seq = """
sleep(0, 1)
"""
    assert_compile_success(fprime_test_api, seq)


def test_f32_f64_cmp(fprime_test_api):
    seq = """
val: F32 = 0.0
val2: F64 = 1.0
if val > val2:
    pass
"""

    assert_compile_success(fprime_test_api, seq)


def test_construct_array(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
"""

    assert_compile_success(fprime_test_api, seq)


def test_get_item_of_var(fprime_test_api):
    seq = """
val: Svc.ComQueueDepth = Svc.ComQueueDepth(0, 0)
if val[0] == 0:
    pass
"""

    assert_compile_success(fprime_test_api, seq)


def test_i32_f64_cmp(fprime_test_api):
    seq = """
val: I32 = 0
val2: F64 = 1.0
if val > val2:
    pass
"""

    assert_compile_success(fprime_test_api, seq)
