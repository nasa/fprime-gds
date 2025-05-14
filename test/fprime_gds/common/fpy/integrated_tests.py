import tempfile

from pathlib import Path
import time
from fprime.common.models.serialize.time_type import TimeType
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.fpy.serialize_bytecode import serialize_bytecode
from fprime_gds.common.testing_fw.api import IntegrationTestAPI
import fprime_gds.common.logger.test_logger

# disable excel logging.... wtf ew
fprime_gds.common.logger.test_logger.MODULE_INSTALLED = False


def compile_seq(fprime_test_api, seq: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".seq", delete=False) as fp:
        fp.write(seq.encode())
        input_path = Path(fp.name)
        output_path = input_path.with_suffix(".bin")

    serialize_bytecode(
        input_path, fprime_test_api.pipeline.dictionary_path, output_path
    )
    return output_path


def assert_compile_fails(fprime_test_api, seq: str):
    try:
        compile_seq(fprime_test_api, seq)
    except BaseException as e:
        return
    raise RuntimeError("compile_seq did not fail")


def assert_compile_succeeds(fprime_test_api, seq: str):
    try:
        return compile_seq(fprime_test_api, seq)
    except BaseException as e:
        raise RuntimeError("compile_seq failed") from e


def test_empty_seq(fprime_test_api: IntegrationTestAPI):
    seq = """
        
    ; testing cmt


    """
    assert_compile_succeeds(fprime_test_api, seq)


def test_nonexistent_directive(fprime_test_api):
    seq = """
    DIRECTIVE_FAILURE

    """
    assert_compile_fails(fprime_test_api, seq)


def test_nonexistent_cmd(fprime_test_api):
    seq = """
    Ref.cmdDisp.CMD_ASDF

    """
    assert_compile_fails(fprime_test_api, seq)


def test_no_op(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    Ref.cmdDisp.CMD_NO_OP_STRING "Hello World"
    Ref.cmdDisp.CMD_NO_OP
    """
    assert_compile_succeeds(fprime_test_api, seq)


def test_wrong_cmd_args(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    Ref.cmdDisp.CMD_NO_OP_STRING 123
    Ref.cmdDisp.CMD_NO_OP
    """
    assert_compile_fails(fprime_test_api, seq)




def test_wait_rel(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    WAIT_REL 2, 0
    Ref.cmdDisp.CMD_NO_OP_STRING "Hello World"
    """
    assert_compile_succeeds(fprime_test_api, seq)

    seq = """
    WAIT_REL "2", 123
    """
    assert_compile_fails(fprime_test_api, seq)

    seq = """
    WAIT_REL 2, "asdf"
    """
    assert_compile_fails(fprime_test_api, seq)


def test_wait_abs(fprime_test_api: IntegrationTestAPI):
    seq = """
    WAIT_ABS { "time_base": 2, "time_context": 0, "seconds": 12, "useconds": 0 }
    """
    assert_compile_succeeds(fprime_test_api, seq)


def test_wait_abs_past(fprime_test_api: IntegrationTestAPI):

    seq = """
    WAIT_ABS { "time_base": 2, "time_context": 0, "seconds": 10, "useconds": 0 }
    """
    assert_compile_succeeds(fprime_test_api, seq)


def test_wait_bad_base(fprime_test_api: IntegrationTestAPI):
    seq = """
    WAIT_ABS { "time_base": 0, "time_context": 0, "seconds": 12, "useconds": 0 }
    """
    assert_compile_succeeds(fprime_test_api, seq)


def test_wait_bad_context(fprime_test_api: IntegrationTestAPI):
    seq = """
    WAIT_ABS { "time_base": 2, "time_context": 123, "seconds": 12, "useconds": 0 }
    """
    assert_compile_succeeds(fprime_test_api, seq)


def test_wait_bad_arg_types(fprime_test_api: IntegrationTestAPI):
    seq = """
    WAIT_ABS { "time_base": "asdf", "time_context": 123, "seconds": 12, "useconds": 0 }
    """
    assert_compile_fails(fprime_test_api, seq)
    seq = """
    WAIT_ABS { "time_base": 12, "time_context": "12", "seconds": 12, "useconds": 0 }
    """
    assert_compile_fails(fprime_test_api, seq)
    seq = """
    WAIT_ABS { "time_base": 12, "time_context": 123, "seconds": [12], "useconds": 0 }
    """
    assert_compile_fails(fprime_test_api, seq)
    seq = """
    WAIT_ABS { "time_base": 12, "time_context": 123, "seconds": 12, "useconds": {12} }
    """
    assert_compile_fails(fprime_test_api, seq)



def test_goto_idx(fprime_test_api: IntegrationTestAPI):
    seq = """
    GOTO 2
    Ref.cmdDisp.CMD_NO_OP
    """

    assert_compile_succeeds(fprime_test_api, seq)

def test_goto_bad_idx(fprime_test_api: IntegrationTestAPI):
    seq = """
    GOTO 3
    Ref.cmdDisp.CMD_NO_OP
    """

    assert_compile_fails(fprime_test_api, seq)


def test_goto_tag(fprime_test_api: IntegrationTestAPI):
    seq = """
    GOTO "tag"
    Ref.cmdDisp.CMD_NO_OP
    tag:
    Ref.cmdDisp.CMD_NO_OP
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_goto_eof(fprime_test_api: IntegrationTestAPI):
    seq = """
    GOTO "end"
    Ref.cmdDisp.CMD_NO_OP
    Ref.cmdDisp.CMD_NO_OP
    end:
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_local_var_set(fprime_test_api: IntegrationTestAPI):
    seq = """
    SET_LVAR 0, {"type": "bool", "value": true}
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_if_true(fprime_test_api: IntegrationTestAPI):
    seq = """
    SET_LVAR 0, {"type": "bool", "value": true}
    IF 0, "else"
    Ref.cmdDisp.CMD_NO_OP
    GOTO "end"
    else:
    Ref.cmdDisp.CMD_NO_OP_STRING "should not happen"
    end:
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_local_var_set_bad_idx(fprime_test_api: IntegrationTestAPI):
    seq = """
    SET_LVAR 255, {"type": "bool", "value": false}
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_local_var_set_string(fprime_test_api: IntegrationTestAPI):
    seq = """
    SET_LVAR 0, {"type": "string", "value": "test string"}
    """

    assert_compile_succeeds(fprime_test_api, seq)



def test_local_var_set_value_way_too_big(fprime_test_api: IntegrationTestAPI):
    # max len of string type is 2^16
    string_len = 2**15
    seq = f"""
    SET_LVAR 0, {{"type": "string", "value": "{"a" * (string_len)}"}}
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_local_var_set_bad_type(fprime_test_api: IntegrationTestAPI):
    seq = """
    SET_LVAR 0, {"type": "unknown_failure", "value": 8}
    """

    assert_compile_fails(fprime_test_api, seq)


def test_get_tlm(fprime_test_api: IntegrationTestAPI):
    seq = """
    GET_TLM 0, 1, "Ref.fpySeq.StatementsDispatched"
    """

    assert_compile_succeeds(fprime_test_api, seq)


def test_get_tlm_bad_chan(fprime_test_api: IntegrationTestAPI):
    seq = """
    GET_TLM 0, 1, "Ref.fpySeq.RUN"
    """

    assert_compile_fails(fprime_test_api, seq)


def test_get_tlm_bad_idx(fprime_test_api: IntegrationTestAPI):
    seq = """
    GET_TLM 0, 255, "Ref.fpySeq.StatementsDispatched"
    """

    assert_compile_succeeds(fprime_test_api, seq)