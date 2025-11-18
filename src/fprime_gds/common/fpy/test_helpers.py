from pathlib import Path
import tempfile
import traceback
from fprime_gds.common.fpy.types import deserialize_directives
from fprime_gds.common.fpy.model import DirectiveErrorCode, FpySequencerModel
from fprime_gds.common.fpy.bytecode.directives import AllocateDirective, Directive
from fprime_gds.common.fpy.main import assemble_main, compile_main, disassemble_main
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


def compile_seq(fprime_test_api, seq: str, flags: list[str]=None) -> list[Directive]:
    input_file = tempfile.NamedTemporaryFile(suffix=".fpy", delete=False)
    output_file = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    Path(input_file.name).write_text(seq)
    args = ["-d", default_dictionary, "-o", output_file.name, input_file.name]
    for flag in flags or []:
        args.append("--flag")
        args.append(flag)
    compile_main(args)

    # also, run some additional tests: try reading the bin file, turning it into assembly,
    # parsing the assembly, writing it to disk and making sure it's the same as the bin file

    # okay write the fpybc to file
    bytecode_file = tempfile.NamedTemporaryFile(suffix=".fpybc", delete=False)
    disassemble_main([output_file.name, "-o", bytecode_file.name])
    assembled_file = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    assemble_main([bytecode_file.name, "-o", assembled_file.name])
    # okay now check that the assembled file is the same as the compiled file
    assert Path(assembled_file.name).read_bytes() == Path(output_file.name).read_bytes()

    return output_file.name


def lookup_type(fprime_test_api, type_name: str):
    dictionary = default_dictionary  # fprime_test_api.pipeline.dictionary_path
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
    file_name: str,
    tlm: dict[str, bytes] = None,
):
    if tlm is None:
        tlm = {}

    # fprime_test_api.send_and_assert_command("Ref.cmdSeq.RUN", [file_name, "BLOCK"], timeout=4)
    # return

    dictionary = default_dictionary  # fprime_test_api.pipeline.dictionary_path

    deserialized_dirs = deserialize_directives(Path(file_name).read_bytes())

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
    if len(deserialized_dirs) > 0 and isinstance(deserialized_dirs[0], AllocateDirective):
        # check that the start and end sizes are the same
        if len(model.stack) != deserialized_dirs[0].size:
            raise RuntimeError(f"Sequence leaked {len(model.stack) - deserialized_dirs[0].size} bytes")


def assert_compile_success(fprime_test_api, seq: str, flags: list[str] = None):
    compile_seq(fprime_test_api, seq, flags)


def assert_run_success(fprime_test_api, seq: str, tlm: dict[str, bytes] = None, flags: list[str]=None):
    compiled_file = compile_seq(fprime_test_api, seq, flags)

    run_seq(fprime_test_api, compiled_file, tlm)


def assert_compile_failure(fprime_test_api, seq: str, flags: list[str] = None):
    try:
        compile_seq(fprime_test_api, seq, flags)
    except AssertionError as e:
        # under any circumstances we should not assert
        raise e
    except SystemExit:
        # okay, compile "gracefully" failed
        traceback.print_exc()
        return

    # no error was generated
    raise RuntimeError("compile_seq succeeded")


def assert_run_failure(fprime_test_api, seq: str, flags: list[str] = None):
    compiled_file = compile_seq(fprime_test_api, seq, flags)
    try:
        run_seq(fprime_test_api, compiled_file)
    except (RuntimeError, AssertionError) as e:
        print(e)
        return

    # other exceptions we will let through, such as assertions
    raise RuntimeError("run_seq succeeded")
