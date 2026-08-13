"""
A suite of unit tests for the "file-uplink" GDS CLI command
"""

import argparse
from unittest.mock import MagicMock

import pytest
from fprime_gds.common.gds_cli.file_uplink import FileUplinkCommand
from fprime_gds.common.testing_fw import predicates
from fprime_gds.executables.fprime_cli import create_parser


class ConstPredicate(predicates.predicate):
    """Test predicate that always evaluates to a fixed value"""

    def __init__(self, value):
        self.value = value

    def __call__(self, item):
        return self.value

    def __str__(self):
        return f"always {self.value}"


def make_args(file_path, destination=None, timeout=5.0, no_wait=False):
    return argparse.Namespace(
        file_path=file_path,
        destination=destination,
        timeout=timeout,
        no_wait=no_wait,
    )


def make_api(entries=None, has_upload_file=False, flight_confirms=True):
    api = MagicMock()
    if not has_upload_file:
        del api.pipeline.client_socket.upload_file
    api.pipeline.files.uplinker.current_files.return_value = entries or []
    api.get_event_test_history.return_value.size.return_value = 0
    if flight_confirms:
        # find_history_item returns an event satisfying the success predicate
        api.get_event_pred.return_value = ConstPredicate(True)
    else:
        api.get_event_pred.side_effect = KeyError("no FileReceived")
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
def test_flight_failure_event_exits_nonzero(tmp_path):
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
    # Success predicate rejects the found item (it is a failure event)
    api.get_event_pred.return_value = ConstPredicate(False)
    with pytest.raises(SystemExit) as exc_info:
        FileUplinkCommand._execute_command(make_args(str(local_file)), api)
    assert exc_info.value.code == 1


@pytest.mark.gds_cli
def test_no_file_received_in_dictionary_skips_confirmation(tmp_path):
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
        ],
        flight_confirms=False,
    )
    FileUplinkCommand._execute_command(make_args(str(local_file)), api)
    api.find_history_item.assert_not_called()


@pytest.mark.gds_cli
def test_blocking_upload_file_transport(tmp_path):
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"\x01\x02\x03")
    api = make_api(has_upload_file=True)
    FileUplinkCommand._execute_command(make_args(str(local_file)), api)
    api.uplink_file.assert_called_once_with(str(local_file), None)
    api.pipeline.files.uplinker.current_files.assert_not_called()
