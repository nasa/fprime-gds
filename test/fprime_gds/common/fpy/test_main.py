from pathlib import Path

import pytest

from fprime_gds.common.fpy import main as fpy_main
import fprime_gds.common.fpy.error as fpy_error
import fprime_gds.common.fpy.model as fpy_model


@pytest.mark.parametrize(
    "size,expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1 KB"),
        (1536, "1 KB"),
        (5 * 1024 * 1024, "5 MB"),
    ],
)
def test_human_readable_size(size, expected):
    assert fpy_main.human_readable_size(size) == expected


def test_compile_main_missing_input(tmp_path, capsys):
    missing = tmp_path / "missing.fpy"
    dict_path = tmp_path / "dict.json"
    with pytest.raises(SystemExit) as exc:
        fpy_main.compile_main(
            [
                str(missing),
                "--dictionary",
                str(dict_path),
            ]
        )
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.out


def test_compile_main_bytecode_output(monkeypatch, tmp_path, capsys):
    input_path = tmp_path / "seq.fpy"
    input_path.write_text("content")
    dict_path = tmp_path / "dict.json"
    dict_path.write_text("{}")

    monkeypatch.setattr(fpy_error, "debug", False, raising=False)
    monkeypatch.setattr(fpy_main, "text_to_ast", lambda text: "AST")

    def fake_ast_to_directives(body, dictionary):
        assert body == "AST"
        assert Path(dictionary) == dict_path
        return ["directive"]

    monkeypatch.setattr(fpy_main, "ast_to_directives", fake_ast_to_directives)
    monkeypatch.setattr(fpy_main, "directives_to_fpybc", lambda directives: "FPYBC")

    def fail_serialize(_):
        raise AssertionError("serialize_directives should not be called")

    monkeypatch.setattr(fpy_main, "serialize_directives", fail_serialize)

    fpy_main.compile_main(
        [
            str(input_path),
            "--dictionary",
            str(dict_path),
            "--bytecode",
            "--debug",
        ]
    )

    captured = capsys.readouterr()
    assert captured.out.strip() == "FPYBC"
    assert fpy_error.debug is True


def test_compile_main_binary_output(monkeypatch, tmp_path, capsys):
    input_path = tmp_path / "seq.fpy"
    input_path.write_text("content")
    dict_path = tmp_path / "dict.json"
    dict_path.write_text("{}")

    monkeypatch.setattr(fpy_main, "text_to_ast", lambda text: "AST")
    monkeypatch.setattr(
        fpy_main,
        "ast_to_directives",
        lambda body, dictionary: ["directive"],
    )
    monkeypatch.setattr(fpy_main, "directives_to_fpybc", lambda directives: "FPYBC")
    monkeypatch.setattr(
        fpy_main,
        "serialize_directives",
        lambda directives: (b"\x01\x02", 0xABCD),
    )

    fpy_main.compile_main(
        [
            str(input_path),
            "--dictionary",
            str(dict_path),
        ]
    )

    output_path = input_path.with_suffix(".bin")
    assert output_path.read_bytes() == b"\x01\x02"
    captured = capsys.readouterr()
    assert "CRC 0xabcd" in captured.out
    assert "2 B" in captured.out


def test_model_main_success(monkeypatch, tmp_path):
    binary = tmp_path / "seq.bin"
    binary.write_bytes(b"data")

    monkeypatch.setattr(fpy_model, "debug", False, raising=False)
    monkeypatch.setattr(fpy_main, "deserialize_directives", lambda data: ["dir"])

    instances = []

    class DummyModel:
        def __init__(self):
            instances.append(self)
            self.ran_with = None

        def run(self, directives):
            self.ran_with = directives
            return fpy_main.DirectiveErrorCode.NO_ERROR

    monkeypatch.setattr(fpy_main, "FpySequencerModel", DummyModel)

    fpy_main.model_main([str(binary), "--debug"])

    assert fpy_model.debug is True
    assert instances[0].ran_with == ["dir"]


def test_model_main_failure(monkeypatch, tmp_path, capsys):
    binary = tmp_path / "seq.bin"
    binary.write_bytes(b"data")

    monkeypatch.setattr(fpy_main, "deserialize_directives", lambda data: ["dir"])

    class DummyModel:
        def run(self, directives):
            return fpy_main.DirectiveErrorCode.EXIT_WITH_ERROR

    monkeypatch.setattr(fpy_main, "FpySequencerModel", DummyModel)

    with pytest.raises(SystemExit) as exc:
        fpy_main.model_main([str(binary)])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Sequence failed" in captured.out


def test_assemble_main_missing_input(tmp_path, capsys):
    source = tmp_path / "seq.fpybc"
    with pytest.raises(SystemExit) as exc:
        fpy_main.assemble_main([str(source)])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.out


def test_assemble_main_writes_binary(monkeypatch, tmp_path, capsys):
    source = tmp_path / "seq.fpybc"
    source.write_text("bc")

    monkeypatch.setattr(fpy_main, "fpybc_parse", lambda text: ["body"])
    monkeypatch.setattr(fpy_main, "assemble", lambda body: ["dirs"])
    monkeypatch.setattr(
        fpy_main,
        "serialize_directives",
        lambda directives: (b"\x03\x04\x05", 0x1234),
    )

    fpy_main.assemble_main([str(source)])

    output_path = source.with_suffix(".bin")
    assert output_path.read_bytes() == b"\x03\x04\x05"
    captured = capsys.readouterr()
    assert "CRC 0x1234" in captured.out


def test_disassemble_main_missing_input(tmp_path, capsys):
    source = tmp_path / "seq.bin"
    with pytest.raises(SystemExit) as exc:
        fpy_main.disassemble_main([str(source)])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.out


def test_disassemble_main_writes_text(monkeypatch, tmp_path, capsys):
    source = tmp_path / "seq.bin"
    source.write_bytes(b"data")

    monkeypatch.setattr(fpy_main, "deserialize_directives", lambda data: ["dirs"])
    monkeypatch.setattr(fpy_main, "directives_to_fpybc", lambda dirs: "FPYBC")

    fpy_main.disassemble_main([str(source)])

    output_path = source.with_suffix(".fpybc")
    assert output_path.read_text() == "FPYBC"
    captured = capsys.readouterr()
    assert captured.out.strip() == "Done"
