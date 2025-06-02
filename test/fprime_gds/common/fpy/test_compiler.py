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