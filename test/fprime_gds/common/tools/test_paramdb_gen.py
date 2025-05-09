import filecmp
from pathlib import Path
import tempfile
from fprime_gds.common.tools.params import convert_json


def assert_prmdb_cfg(input: Path, expected_output: Path = None, should_fail=False):
    dict_file = Path(__file__).parent / "resources" / "simple_dictionary.json"

    temp_dir = tempfile.TemporaryDirectory()
    output_bin = Path(f"{temp_dir.name}/out_binary")
    if should_fail:
        try:
            convert_json(input, dict_file, output_bin, "dat")
            temp_dir.cleanup()
            raise RuntimeError("Config file conversion did not fail")
        except BaseException as e:
            # failed, test succeeded
            temp_dir.cleanup()
            return
    else:
        if expected_output is None:
            raise RuntimeError("Must specify expected output if should fail is False")
        convert_json(input, dict_file, output_bin, "dat")
    is_equal = filecmp.cmp(output_bin, expected_output)
    temp_dir.cleanup()

    assert is_equal


def test_nominal_paramdb():
    expected_output = Path(__file__).parent / "expected" / "simple_paramdb.dat"
    cfg_file = Path(__file__).parent / "input" / "simple_paramdb.json"
    assert_prmdb_cfg(cfg_file, expected_output)


def test_failure_paramdb():
    cfg_file = Path(__file__).parent / "input" / "simple_bad_paramdb.json"
    assert_prmdb_cfg(cfg_file, should_fail=True)
