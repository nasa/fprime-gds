import ast
from fprime_gds.common.fpy.compiler import compile
from fprime_gds.common.fpy.parser import parse


def compile_seq(fprime_test_api, seq: str):
    compile(parse(seq), fprime_test_api.pipeline.dictionary_path)


def assert_success(fprime_test_api, seq: str):
    compile_seq(fprime_test_api, seq)


def assert_failure(fprime_test_api, seq: str):
    try:
        compile_seq(fprime_test_api, seq)
    except BaseException as e:
        return
    raise RuntimeError("compile_seq succeeded")


def test_simple_var(fprime_test_api):
    seq = """
var: U32 = 1
"""

    assert_success(fprime_test_api, seq)


def test_large_var(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
"""

    assert_success(fprime_test_api, seq)


def test_var_wrong_rhs(fprime_test_api):
    seq = """
x: U32 = 1
var: U32 = x
"""

    assert_failure(fprime_test_api, seq)


def test_nonexistent_var(fprime_test_api):
    seq = """
var = 1
"""

    assert_failure(fprime_test_api, seq)


def test_create_after_assign_var(fprime_test_api):
    seq = """
var = 1
var: U32 = 2
"""

    assert_failure(fprime_test_api, seq)


def test_bad_assign_type(fprime_test_api):
    seq = """
var: asdfasdfasdf = 1
"""

    assert_failure(fprime_test_api, seq)


def test_weird_assign_type(fprime_test_api):
    seq = """
var: Ref.cmdDisp.CMD_NO_OP = 1
"""

    assert_failure(fprime_test_api, seq)


def test_reassign(fprime_test_api):
    seq = """
var: U32 = 1
var = 2
"""

    assert_success(fprime_test_api, seq)


def test_reassign_ann(fprime_test_api):
    seq = """
var: U32 = 1
var: U32 = 2
"""
    assert_failure(fprime_test_api, seq)


def test_assign_inconsistent_type(fprime_test_api):
    seq = """
var: U32 = 1
var: U16 = 2
"""

    assert_failure(fprime_test_api, seq)


def test_call_cmd(fprime_test_api):
    seq = """
Ref.cmdDisp.CMD_NO_OP()
"""
    assert_success(fprime_test_api, seq)


def test_call_cmd_with_int_arg(fprime_test_api):
    seq = """
Ref.sendBuffComp.PARAMETER3_PRM_SET(4)
"""
    assert_success(fprime_test_api, seq)


def test_bad_enum_ctor(fprime_test_api):
    seq = """
Ref.SG5.Settings(123, 0.5, 0.5, Ref.SignalType(1))
"""
    assert_failure(fprime_test_api, seq)


def test_cmd_with_enum(fprime_test_api):
    seq = """
Ref.SG5.Settings(123, 0.5, 0.5, Ref.SignalType.TRIANGLE)
"""
    assert_success(fprime_test_api, seq)


def test_instantiate_type_for_cmd(fprime_test_api):
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.ONE, Ref.Choice.TWO))
"""
    assert_success(fprime_test_api, seq)


def test_var_with_enum_type(fprime_test_api):
    seq = """
var: Ref.Choice = Ref.Choice.ONE
"""

    assert_success(fprime_test_api, seq)


def test_simple_if(fprime_test_api):
    seq = """
var: bool = True

if var:
    pass
"""
    assert_success(fprime_test_api, seq)


def test_or_expr(fprime_test_api):
    seq = """
if True or False:
    pass
"""
    assert_success(fprime_test_api, seq)


def test_not_expr(fprime_test_api):
    seq = """
if not False:
    pass
"""
    assert_success(fprime_test_api, seq)


def test_or_expr_with_vars(fprime_test_api):
    seq = """
var1: bool = True
var2: bool = False

if var1 or var2:
    pass
"""
    assert_success(fprime_test_api, seq)


def test_geq(fprime_test_api):
    seq = """
if 2 >= 1:
    pass
"""
    assert_success(fprime_test_api, seq)


def test_geq_tlm(fprime_test_api):
    seq = """
if Ref.cmdDisp.CommandsDispatched > 1:
    pass
"""

    assert_success(fprime_test_api, seq)


def test_large_elifs(fprime_test_api):
    seq = """
if Ref.cmdDisp.CommandsDispatched == 0:
    Ref.cmdDisp.CMD_NO_OP_STRING("0")
elif Ref.cmdDisp.CommandsDispatched == 1:
    Ref.cmdDisp.CMD_NO_OP_STRING("1")
elif Ref.cmdDisp.CommandsDispatched == 2:
    Ref.cmdDisp.CMD_NO_OP_STRING("2")
elif Ref.cmdDisp.CommandsDispatched == 3:
    Ref.cmdDisp.CMD_NO_OP_STRING("3")
elif Ref.cmdDisp.CommandsDispatched == 4:
    Ref.cmdDisp.CMD_NO_OP_STRING("4")
elif Ref.cmdDisp.CommandsDispatched == 5:
    Ref.cmdDisp.CMD_NO_OP_STRING("5")
elif Ref.cmdDisp.CommandsDispatched == 6:
    Ref.cmdDisp.CMD_NO_OP_STRING("6")
elif Ref.cmdDisp.CommandsDispatched == 7:
    Ref.cmdDisp.CMD_NO_OP_STRING("7")
elif Ref.cmdDisp.CommandsDispatched == 8:
    Ref.cmdDisp.CMD_NO_OP_STRING("8")
else:
    Ref.cmdDisp.CMD_NO_OP_STRING(">8")
"""

    assert_success(fprime_test_api, seq)


def test_int_as_stmt(fprime_test_api):
    seq = """
2
"""

    assert_failure(fprime_test_api, seq)


def test_complex_as_stmt(fprime_test_api):
    seq = """
Ref.cmdDisp.CMD_NO_OP
"""

    assert_failure(fprime_test_api, seq)

def test_get_struct_member(fprime_test_api):
    seq = """
if Ref.fpySeq.Debug.nextStatementOpcode == 8:
    pass
"""

    assert_success(fprime_test_api, seq)


def test_get_const_struct_member(fprime_test_api):
    seq = """
var: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
if var.priority == 1:
    pass
"""

    assert_success(fprime_test_api, seq)


def test_float_cmp(fprime_test_api):
    seq = """
if 4.0 > 5.0:
    pass
"""

    assert_success(fprime_test_api, seq)