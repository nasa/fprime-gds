from pathlib import Path

import pytest

from fprime_gds.common.fpy import main as fpy_main
from fprime_gds.common.fpy.test_helpers import default_dictionary


def compile_expect_failure(source: str, tmp_path: Path, capsys: pytest.CaptureFixture):
    input_path = tmp_path / "sample.fpy"
    input_path.write_text(source)
    with pytest.raises(SystemExit) as exc:
        fpy_main.compile_main([
            str(input_path),
            "--dictionary",
            default_dictionary,
        ])
    output = capsys.readouterr()
    return exc.value.code, output


def test_namespace_call_reports_unknown_function(tmp_path, capsys):
    code = """
CdhCore.cmdDisp()
"""
    status, output = compile_expect_failure(code, tmp_path, capsys)
    assert status == 1
    assert "Unknown function" in output.out


def test_namespace_used_as_type_reports_unknown_type(tmp_path, capsys):
    code = """
var: Svc = 1
"""
    status, output = compile_expect_failure(code, tmp_path, capsys)
    assert status == 1
    assert "Unknown type" in output.out


def test_assign_command_reference_reports_unknown_value(tmp_path, capsys):
    code = """
var: U32 = notDeclared
"""
    status, output = compile_expect_failure(code, tmp_path, capsys)
    assert status == 1
    assert "Unknown value" in output.out


def test_missing_struct_member_highlights_name(tmp_path, capsys):
    code = """
record: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
value: U32 = record.missing_field
"""
    status, output = compile_expect_failure(code, tmp_path, capsys)
    assert status == 1
    assert "has no member named missing_field" in output.out


def test_struct_index_reports_not_an_array(tmp_path, capsys):
    code = """
record: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
value: U32 = record[0]
"""
    status, output = compile_expect_failure(code, tmp_path, capsys)
    assert status == 1
    assert "is not an array" in output.out


def test_namespace_index_reports_unknown_item(tmp_path, capsys):
    code = """
value: U32 = CdhCore.cmdDisp[0]
"""
    status, output = compile_expect_failure(code, tmp_path, capsys)
    assert status == 1
    assert "Unknown item" in output.out
