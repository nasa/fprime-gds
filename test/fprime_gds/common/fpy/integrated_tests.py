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
SEQ_MAX_STATEMENT_COUNT = 1024

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
        raise RuntimeError("compile_seq did not fail") from e


def assert_run_succeeds(
    fprime_test_api: IntegrationTestAPI, seq_bin: Path, max_duration: float = 1.0
):
    fprime_test_api.send_and_assert_command(
        "Ref.fpySeq.RUN", [str(seq_bin), "BLOCK"], max_duration, int(max_duration)
    )


def assert_seq(
    fprime_test_api,
    seq,
    compile_success=True,
    run_success=True,
    min_runtime: float = 0.0,
    max_runtime: float = 1.0,
):
    if compile_success:
        bin = assert_compile_succeeds(fprime_test_api, seq)
    else:
        assert_compile_fails(fprime_test_api, seq)
        return

    if run_success:
        run_start = time.time()
        assert_run_succeeds(fprime_test_api, bin, max_runtime)
        runtime = time.time() - run_start
        assert runtime > min_runtime, "Sequence only ran for " + str(runtime) + " seconds"
    else:
        try:
            assert_run_succeeds(fprime_test_api, bin, max_runtime)
        except BaseException as e:
            # it failed... successfully
            return
        raise RuntimeError("Sequence was expected to fail but did not")


def get_dispatched_count(fprime_test_api: IntegrationTestAPI) -> int:

    t_pred = fprime_test_api.get_telemetry_pred(
        "Ref.fpySeq.StatementsDispatched", None, None
    )

    # wait 1 sec for ref deployment to telemeter it
    time.sleep(1)
    item: ChData = fprime_test_api.find_history_item(
        t_pred, fprime_test_api.telemetry_history, "NOW", 2
    )
    if item is None:
        raise RuntimeError("Unable to find dispatched statements count")
    return item.get_val()


def test_empty_seq(fprime_test_api: IntegrationTestAPI):
    seq = """
        
    ; testing cmt


    """
    assert_seq(fprime_test_api, seq, True, True)


def test_no_op(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    Ref.cmdDisp.CMD_NO_OP_STRING "Hello World"
    Ref.cmdDisp.CMD_NO_OP
    """
    assert_seq(fprime_test_api, seq, True, True)

    fprime_test_api.assert_event_count(
        3, ["Ref.cmdDisp.NoOpReceived", "Ref.cmdDisp.NoOpStringReceived"]
    )

def test_largest_possible_seq(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    """
    seq = "\n".join([seq] * SEQ_MAX_STATEMENT_COUNT)
    assert_seq(fprime_test_api, seq, True, True)

    fprime_test_api.assert_event_count(
        SEQ_MAX_STATEMENT_COUNT, ["Ref.cmdDisp.NoOpReceived"]
    )

def test_too_big_seq(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    """
    seq = "\n".join([seq] * (SEQ_MAX_STATEMENT_COUNT + 1))
    assert_seq(fprime_test_api, seq, True, False)

def test_wait_rel(fprime_test_api: IntegrationTestAPI):
    seq = """
    Ref.cmdDisp.CMD_NO_OP
    WAIT_REL {"time_base": 2, "time_context": 0, "seconds": 2, "useconds": 0}
    Ref.cmdDisp.CMD_NO_OP_STRING "Hello World"
    """
    pre = get_dispatched_count(fprime_test_api)
    assert_seq(fprime_test_api, seq, True, True, min_runtime=2, max_runtime=4)
    assert get_dispatched_count(fprime_test_api) - pre == 3


def test_wait_abs(fprime_test_api: IntegrationTestAPI):
    time = fprime_test_api.get_latest_time()

    seq = f"""
    WAIT_ABS {{ "time_base": 2, "time_context": 0, "seconds": {time.seconds + 5}, "useconds": 0 }}
    """
    # i see a lot of variability in this depending on tlm rates. cuz latest time just returns latest tlm timestamp
    # so it might be somewhat in the past
    assert_seq(fprime_test_api, seq, True, True, min_runtime=4, max_runtime=6.1)


def test_wait_abs_past(fprime_test_api: IntegrationTestAPI):
    time = fprime_test_api.get_latest_time()

    seq = f"""
    WAIT_ABS {{ "time_base": 2, "time_context": 0, "seconds": {time.seconds - 8}, "useconds": 0 }}
    """
    assert_seq(fprime_test_api, seq, True, True, min_runtime=0, max_runtime=2)


def test_wait_bad_base(fprime_test_api: IntegrationTestAPI):
    # timebase dont match, should fail
    seq = """
    WAIT_REL { "time_base": 0, "time_context": 0, "seconds": 1, "useconds": 0 }
    """
    assert_seq(fprime_test_api, seq, True, False, min_runtime=0, max_runtime=2)

    time = fprime_test_api.get_latest_time()
    seq = f"""
    WAIT_ABS {{ "time_base": 0, "time_context": 0, "seconds": {time.seconds + 5}, "useconds": 0 }}
    """
    assert_seq(fprime_test_api, seq, True, False, min_runtime=0, max_runtime=2)


def test_wait_bad_context(fprime_test_api: IntegrationTestAPI):
    # timectx dont match, should fail
    seq = """
    WAIT_REL { "time_base": 2, "time_context": 123, "seconds": 1, "useconds": 0 }
    """
    assert_seq(fprime_test_api, seq, True, False, min_runtime=0, max_runtime=2)

    time = fprime_test_api.get_latest_time()
    seq = f"""
    WAIT_ABS {{ "time_base": 2, "time_context": 123, "seconds": {time.seconds + 5}, "useconds": 0 }}
    """
    assert_seq(fprime_test_api, seq, True, False, min_runtime=0, max_runtime=2)