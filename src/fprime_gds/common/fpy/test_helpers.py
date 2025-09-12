import ast
from pathlib import Path
import tempfile
import traceback
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.numerical_types import U32Type, U8Type
from fprime_gds.common.fpy.bytecode.assembler import deserialize_directives
from fprime_gds.common.fpy.model import DirectiveErrorCode, FpySequencerModel
from fprime_gds.common.fpy.bytecode.directives import Directive
from fprime_gds.common.fpy.codegen import compile, serialize_directives
from fprime_gds.common.fpy.parser import parse
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.event_json_loader import EventJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.testing_fw.api import IntegrationTestAPI

default_dictionary = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "test"
    / "fprime_gds"
    / "common"
    / "fpy"
    / "RefTopologyDictionary.json"
)


def compile_seq(fprime_test_api, seq: str) -> list[Directive]:
    return compile(parse(seq), default_dictionary) #fprime_test_api.pipeline.dictionary_path)


def lookup_type(fprime_test_api, type_name: str):
    dictionary = default_dictionary #fprime_test_api.pipeline.dictionary_path
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
    event_json_dict_loader = EventJsonLoader(dictionary)
    (event_id_dict, event_name_dict, versions) = event_json_dict_loader.construct_dicts(
        dictionary
    )
    type_name_dict = cmd_json_dict_loader.parsed_types
    type_name_dict.update(ch_json_dict_loader.parsed_types)
    type_name_dict.update(prm_json_dict_loader.parsed_types)
    type_name_dict.update(event_json_dict_loader.parsed_types)

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

    # fprime_test_api.send_and_assert_command("Ref.cmdSeq.RUN", [file.name, "BLOCK"], timeout=4)
    # return

    dictionary = default_dictionary # fprime_test_api.pipeline.dictionary_path

    deserialized_dirs = deserialize_directives(Path(file.name).read_bytes())

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )
    model = FpySequencerModel(cmd_dict=cmd_id_dict)
    tlm_db = {}
    for chan_name, val in tlm.items():
        ch_template = ch_name_dict[chan_name]
        tlm_db[ch_template.get_id()] = val
    ret = model.run(deserialized_dirs, tlm_db)
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
        traceback.print_exc()
        return
    raise RuntimeError("compile_seq succeeded")


def assert_run_failure(fprime_test_api, seq: str):
    directives = compile_seq(fprime_test_api, seq)
    try:
        run_seq(fprime_test_api, directives)
    except BaseException as e:
        print(e)
        return
    raise RuntimeError("run_seq succeeded")
