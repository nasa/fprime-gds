"""
A suite of unit tests for the "file-uplink" GDS CLI command
"""

import argparse
from unittest.mock import MagicMock

import pytest
from fprime_gds.common.gds_cli.file_uplink import FileUplinkCommand
from fprime_gds.executables.fprime_cli import create_parser


def make_args(file_path, destination=None, timeout=5.0, no_wait=False):
    return argparse.Namespace(
        file_path=file_path,
        destination=destination,
        timeout=timeout,
        no_wait=no_wait,
    )


def make_api(entries=None, has_upload_file=False):
    api = MagicMock()
    if not has_upload_file:
        del api.pipeline.client_socket.upload_file
    api.pipeline.files.uplinker.current_files.return_value = entries or []
    return api


# ==============================================================================
# Argument parsing tests
# ==============================================================================


@pytest.mark.gds_cli
def test_parser_accepts_file_and_destination():
    parser = create_parser()
    args = parser.parse_args(["file-uplink", "local.bin", "/remote/dest.bin"])
    assert args.file_path == "local.bin"
    assert args.destination == "/remote/dest.bin"
    assert args.timeout == 60.0
    assert not args.no_wait


@pytest.mark.gds_cli
def test_parser_destination_optional():
    parser = create_parser()
    args = parser.parse_args(["file-uplink", "local.bin"])
    assert args.file_path == "local.bin"
    assert args.destination is None


@pytest.mark.gds_cli
def test_parser_timeout_and_no_wait():
    parser = create_parser()
    args = parser.parse_args(
        ["file-uplink", "local.bin", "--timeout", "12.5", "--no-wait"]
    )
    assert args.timeout == 12.5
    assert args.no_wait


@pytest.mark.gds_cli
def test_parser_requires_file():
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["file-uplink"])


# ==============================================================================
# Command execution tests
# ==============================================================================


@pytest.mark.gds_cli
def test_missing_file_exits_nonzero():
    api = make_api()
    with pytest.raises(SystemExit) as exc_info:
        FileUplinkCommand._execute_command(make_args("/nonexistent/file.bin"), api)
    assert exc_info.value.code == 1
    api.uplink_file.assert_not_called()


@pytest.mark.gds_cli
def test_no_wait_enqueues_and_returns(tmp_path):
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"\x01\x02\x03")
    api = make_api()
    FileUplinkCommand._execute_command(
        make_args(str(local_file), "/dest/data.bin", no_wait=True), api
    )
    api.uplink_file.assert_called_once_with(str(local_file), "/dest/data.bin")
    api.pipeline.files.uplinker.current_files.assert_not_called()


@pytest.mark.gds_cli
def test_waits_for_finished_state(tmp_path):
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"\x01\x02\x03")
    api = make_api(
        entries=[
            {
                "source": f"/up/{local_file.name}",
                "destination": "/data.bin",
                "state": "FINISHED",
                "percent": 100,
            }
        ]
    )
    FileUplinkCommand._execute_command(make_args(str(local_file)), api)
    api.uplink_file.assert_called_once_with(str(local_file), None)


@pytest.mark.gds_cli
@pytest.mark.parametrize("state", ["CANCELED", "TIMEOUT"])
def test_failure_states_exit_nonzero(tmp_path, state):
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"\x01\x02\x03")
    api = make_api(
        entries=[
            {
                "source": f"/up/{local_file.name}",
                "destination": "/data.bin",
                "state": state,
                "percent": 50,
            }
        ]
    )
    with pytest.raises(SystemExit) as exc_info:
        FileUplinkCommand._execute_command(make_args(str(local_file)), api)
    assert exc_info.value.code == 1


@pytest.mark.gds_cli
def test_timeout_exits_nonzero(tmp_path):
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"\x01\x02\x03")
    api = make_api(
        entries=[
            {
                "source": f"/up/{local_file.name}",
                "destination": "/data.bin",
                "state": "TRANSMITTING",
                "percent": 10,
            }
        ]
    )
    with pytest.raises(SystemExit) as exc_info:
        FileUplinkCommand._execute_command(make_args(str(local_file), timeout=0.5), api)
    assert exc_info.value.code == 1


@pytest.mark.gds_cli
def test_blocking_upload_file_transport(tmp_path):
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"\x01\x02\x03")
    api = make_api(has_upload_file=True)
    FileUplinkCommand._execute_command(make_args(str(local_file)), api)
    api.uplink_file.assert_called_once_with(str(local_file), None)
    api.pipeline.files.uplinker.current_files.assert_not_called()
