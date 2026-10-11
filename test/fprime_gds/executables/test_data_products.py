"""Tests for the fprime-dp decode command line (fprime_gds.executables.data_products)"""

import json
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

from fprime_gds.common.utils.cleanup import globals_cleanup
from fprime_gds.executables.data_products import main

TEST_DATA_DIR = Path(__file__).parent.parent / "common" / "dp" / "test_dp_data"
DICTIONARY_REF_PATH = TEST_DATA_DIR / "dictionary_ref.json"
# Container id of Ref.dpDemo.DpDemoContainer in dictionary_ref.json
DP_DEMO_CONTAINER_ID = 2576
DP_DEMO_CONTAINER_NAME = "Ref.dpDemo.DpDemoContainer"


@pytest.fixture(autouse=True)
def clean_globals():
    """Reset the global ConfigManager/dictionary state around each test"""
    globals_cleanup()
    yield
    globals_cleanup()


def run_decode(*extra_args):
    """Run `fprime-dp decode -d <ref dictionary> <extra args>` and return the exit code"""
    argv = ["fprime-dp", "decode", "-d", str(DICTIONARY_REF_PATH), *extra_args]
    with mock.patch.object(sys, "argv", argv):
        return main()


def stage(tmp_path, source, name, corrupt_offset=None):
    """Copy a test data file into tmp_path under the given name, optionally flipping one byte"""
    destination = tmp_path / name
    shutil.copy(TEST_DATA_DIR / source, destination)
    if corrupt_offset is not None:
        raw = bytearray(destination.read_bytes())
        raw[corrupt_offset] ^= 0xFF
        destination.write_bytes(raw)
    return destination


# Byte offsets to corrupt in DpDemoUncompressed.fdp: inside the header (fails the header CRC)
# and inside a string record near the end (fails record deserialization)
HEADER_CORRUPT_OFFSET = 2
RECORD_CORRUPT_OFFSET = -10


def assert_decoded(json_path):
    assert json_path.is_file(), f"{json_path} was not written"
    with open(json_path) as file_handle:
        data = json.load(file_handle)
    assert data["Header"]["Id"]["value"] == DP_DEMO_CONTAINER_ID
    assert len(data["Records"]) == 14


class TestDecodeBinFile:
    def test_default_output_name(self, tmp_path):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000010_00000020.fdp")
        assert run_decode("-b", str(bin_file)) == 0
        assert_decoded(bin_file.with_suffix(".json"))

    def test_explicit_output(self, tmp_path):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", "product.fdp")
        output = tmp_path / "out" / "custom.json"
        output.parent.mkdir()
        assert run_decode("-b", str(bin_file), "-o", str(output)) == 0
        assert_decoded(output)
        assert not bin_file.with_suffix(".json").exists()

    def test_rename_id(self, tmp_path):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000010_00000020.fdp")
        assert run_decode("-b", str(bin_file), "--rename-id") == 0
        assert_decoded(tmp_path / f"Dp_{DP_DEMO_CONTAINER_NAME}_00000010_00000020.json")
        assert not bin_file.with_suffix(".json").exists()

    def test_rename_id_explicit_output_wins(self, tmp_path):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000010_00000020.fdp")
        output = tmp_path / "custom.json"
        assert run_decode("-b", str(bin_file), "--rename-id", "-o", str(output)) == 0
        assert_decoded(output)
        assert list(tmp_path.glob("*.json")) == [output]

    def test_rename_id_downlinked_name(self, tmp_path):
        """Downlinked copies are named after the sanitized flight path (./DpCat/Dp_... -> ._DpCat_Dp_...)"""
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", f"._DpCat_Dp_{DP_DEMO_CONTAINER_ID:08d}_00000010_00000020.fdp")
        assert run_decode("-b", str(bin_file), "--rename-id") == 0
        assert_decoded(tmp_path / f"._DpCat_Dp_{DP_DEMO_CONTAINER_NAME}_00000010_00000020.json")

    def test_rename_id_unknown_container_keeps_name(self, tmp_path, capsys):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00000001_00000010_00000020.fdp")
        assert run_decode("-b", str(bin_file), "--rename-id") == 0
        assert_decoded(bin_file.with_suffix(".json"))
        assert "container id 1" in capsys.readouterr().err

    def test_rename_id_unconventional_name_keeps_name(self, tmp_path, capsys):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", "DpDemoUncompressed.fdp")
        assert run_decode("-b", str(bin_file), "--rename-id") == 0
        assert_decoded(bin_file.with_suffix(".json"))
        assert "does not match" in capsys.readouterr().err

    def test_crc_failure_returns_nonzero(self, tmp_path, capsys):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", "bad.fdp", HEADER_CORRUPT_OFFSET)
        assert run_decode("-b", str(bin_file)) == 1
        assert not bin_file.with_suffix(".json").exists()
        assert "CRC mismatch in Header" in capsys.readouterr().err

    def test_deserialize_failure_returns_nonzero(self, tmp_path, capsys):
        bin_file = stage(tmp_path, "DpDemoUncompressed.fdp", "bad.fdp", RECORD_CORRUPT_OFFSET)
        assert run_decode("-b", str(bin_file)) == 1
        assert not bin_file.with_suffix(".json").exists()
        assert "failed to decode" in capsys.readouterr().err


class TestDecodeBinDir:
    def test_decodes_every_fdp(self, tmp_path):
        names = [
            f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000010_00000020.fdp",
            f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000011_00000021.fdp",
        ]
        stage(tmp_path, "DpDemoUncompressed.fdp", names[0])
        stage(tmp_path, "DpDemoCompressed.fdp", names[1])
        stage(tmp_path, "DpDemoUncompressed.fdp", "not-a-product.bin")
        (tmp_path / "DpState.dat").write_bytes(b"\x00")
        assert run_decode("--bin-dir", str(tmp_path)) == 0
        for name in names:
            assert_decoded(tmp_path / Path(name).with_suffix(".json"))
        assert sorted(path.name for path in tmp_path.glob("*.json")) == sorted(
            str(Path(name).with_suffix(".json")) for name in names
        )

    def test_rename_id(self, tmp_path):
        stage(tmp_path, "DpDemoUncompressed.fdp", f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000010_00000020.fdp")
        stage(tmp_path, "DpDemoCompressed.fdp", f"Dp_{DP_DEMO_CONTAINER_ID:08d}_00000011_00000021.fdp")
        assert run_decode("--bin-dir", str(tmp_path), "-r") == 0
        assert_decoded(tmp_path / f"Dp_{DP_DEMO_CONTAINER_NAME}_00000010_00000020.json")
        assert_decoded(tmp_path / f"Dp_{DP_DEMO_CONTAINER_NAME}_00000011_00000021.json")

    def test_continues_past_failures(self, tmp_path, capsys):
        bad_crc = stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00002576_00000009_00000019.fdp", HEADER_CORRUPT_OFFSET)
        good = stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00002576_00000010_00000020.fdp")
        bad_record = stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00002576_00000011_00000021.fdp", RECORD_CORRUPT_OFFSET)
        assert run_decode("--bin-dir", str(tmp_path)) == 1
        assert_decoded(good.with_suffix(".json"))
        assert not bad_crc.with_suffix(".json").exists()
        assert not bad_record.with_suffix(".json").exists()
        captured = capsys.readouterr()
        assert "CRC mismatch" in captured.err
        assert "failed to decode" in captured.err
        assert "Decoded 1/3 data products" in captured.out

    def test_rename_id_output_collision_is_reported(self, tmp_path, capsys):
        """Two inputs that rename to the same JSON must not silently overwrite each other"""
        first = stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00002576_00000010_00000020.fdp")
        stage(tmp_path, "DpDemoCompressed.fdp", "Dp_2576_00000010_00000020.fdp")
        assert run_decode("--bin-dir", str(tmp_path), "-r") == 1
        assert_decoded(tmp_path / f"Dp_{DP_DEMO_CONTAINER_NAME}_00000010_00000020.json")
        captured = capsys.readouterr()
        assert "already written" in captured.err
        assert "Decoded 1/2 data products" in captured.out
        assert first.name in captured.err

    def test_rename_id_collision_after_failure_still_decodes(self, tmp_path, capsys):
        """A failed decode must not reserve its output name"""
        stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00002576_00000010_00000020.fdp", HEADER_CORRUPT_OFFSET)
        stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_2576_00000010_00000020.fdp")
        assert run_decode("--bin-dir", str(tmp_path), "-r") == 1
        assert_decoded(tmp_path / f"Dp_{DP_DEMO_CONTAINER_NAME}_00000010_00000020.json")
        captured = capsys.readouterr()
        assert "already written" not in captured.err
        assert "Decoded 1/2 data products" in captured.out

    def test_single_file_summary(self, tmp_path, capsys):
        stage(tmp_path, "DpDemoUncompressed.fdp", "Dp_00002576_00000010_00000020.fdp")
        assert run_decode("--bin-dir", str(tmp_path)) == 0
        assert "Decoded 1/1 data products" in capsys.readouterr().out

    def test_empty_dir(self, tmp_path):
        assert run_decode("--bin-dir", str(tmp_path)) == 1

    def test_not_a_dir(self, tmp_path):
        with pytest.raises(SystemExit):
            run_decode("--bin-dir", str(tmp_path / "missing"))

    def test_output_rejected(self, tmp_path):
        with pytest.raises(SystemExit):
            run_decode("--bin-dir", str(tmp_path), "-o", str(tmp_path / "x.json"))

    def test_bin_file_and_bin_dir_exclusive(self, tmp_path):
        with pytest.raises(SystemExit):
            run_decode("--bin-dir", str(tmp_path), "-b", str(tmp_path / "x.fdp"))

    def test_input_required(self):
        with pytest.raises(SystemExit):
            run_decode()
