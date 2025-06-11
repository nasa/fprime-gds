import ast
from fprime_gds.common.fpy.parser import parse


def parse_seq(fprime_test_api, seq: str):
    parse(seq)


def assert_success(fprime_test_api, seq: str):
    try:
        return parse_seq(fprime_test_api, seq)
    except BaseException as e:
        raise RuntimeError("compile_seq failed") from e


def test_bool_literal(fprime_test_api):
    seq = """
if True:
    var = False
"""

    assert_success(fprime_test_api, seq)


def test_simple_if(fprime_test_api):
    seq = """
if bool_var:
    cmd()
"""

    assert_success(fprime_test_api, seq)


def test_elif(fprime_test_api):
    seq = """
if bool_var:
    cmd()
elif other_bool_var:
    directive()
"""

    assert_success(fprime_test_api, seq)

def test_pass(fprime_test_api):
    seq = """
pass
"""

    assert_success(fprime_test_api, seq)




def test_funcdef(fprime_test_api):
    seq = """
def func():
    pass
"""

    assert_success(fprime_test_api, seq)
