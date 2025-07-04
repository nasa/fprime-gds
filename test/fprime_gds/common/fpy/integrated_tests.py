import tempfile

from pathlib import Path
import time
from fprime.common.models.serialize.time_type import TimeType
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.fpy.bytecode.serialize_bytecode import serialize_directives
from fprime_gds.common.testing_fw.api import IntegrationTestAPI
import fprime_gds.common.logger.test_logger


def serialize_seq(fprime_test_api, seq: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".seq", delete=False) as fp:
        fp.write(seq.encode())
        input_path = Path(fp.name)
        output_path = input_path.with_suffix(".bin")

    serialize_directives(
        input_path, fprime_test_api.pipeline.dictionary_path, output_path
    )
    return output_path


def assert_ser_fails(fprime_test_api, seq: str):
    try:
        serialize_seq(fprime_test_api, seq)
    except BaseException as e:
        return
    raise RuntimeError("serialize_seq did not fail")


def assert_ser_succeeds(fprime_test_api, seq: str):
    try:
        return serialize_seq(fprime_test_api, seq)
    except BaseException as e:
        raise RuntimeError("serialize_seq failed") from e

