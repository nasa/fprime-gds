import ast
from fprime_gds.common.fpy.old_compiler import compile


def compile_seq(fprime_test_api, seq: str):

    node = ast.parse(seq)
    print(ast.dump(node, indent=4))

def assert_success(fprime_test_api, seq: str):
    try:
        return compile_seq(fprime_test_api, seq)
    except BaseException as e:
        raise RuntimeError("compile_seq failed") from e

def test_basic(fprime_test_api):
    seq = \
"""

directive()
Ref.cmdDisp.CMD_NO_OP()

if Ref.cmdSeq.test_bool:
    Ref.cmdDisp.CMD_NO_OP_STRING("asdf")

x = "whatever"

Ref.cmdDisp.CMD_NO_OP_STRING(x)
"""

    assert_success(fprime_test_api, seq)