import ast
from fprime_gds.common.fpy.compiler import compile
from fprime_gds.common.fpy.parser import parse


def compile_seq(fprime_test_api, seq: str):
    compile(parse(seq), fprime_test_api.pipeline.dictionary_path)


def assert_success(fprime_test_api, seq: str):
    try:
        compile_seq(fprime_test_api, seq)
    except BaseException as e:
        raise RuntimeError("compile_seq failed") from e


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


def test_nonexistent_var(fprime_test_api):
    seq = """
var = 1
"""

    assert_failure(fprime_test_api, seq)


def test_bad_assign_type(fprime_test_api):
    seq = """
var: asdfasdfasdf = 1
"""

    assert_failure(fprime_test_api, seq)


def test_weird_assign_type(fprime_test_api):
    seq = """
var: U32.asdf = 1
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
    assert_success(fprime_test_api, seq)


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
