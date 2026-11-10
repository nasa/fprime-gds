"""Tests for Svc.ComLoggerDp product decoding (fprime_gds.common.dp.comlog) and the `fprime-dp comlog` command"""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from fprime_gds.common.dp.comlog import CHANNEL_LOG_NAME, DEFAULT_SENTRY, EVENT_LOG_NAME, ComLoggerDpDecoder, write_json, write_text
from fprime_gds.common.dp.common import ChecksumConfig, calculate_crc32, get_dp_header_type
from fprime_gds.common.dp.decoder import CRCError, DataProductError
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.models.serialize.numerical_types import F32Type, U8Type, U16Type, U32Type
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.utils.cleanup import globals_cleanup
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.executables.data_products import main

REF_DICTIONARY = Path(__file__).parent / "test_dp_data" / "dictionary_ref.json"
DICTIONARY_PATH = None  # dictionary_ref.json plus a ComLoggerDp record and container, written by the dictionary_path fixture
CONTAINER_ID = 1024  # Ref.comLogger.ComBuffContainer / ComBufferRecord
HELLO_EVENT_ID, PLAIN_EVENT_ID = 16785410, 2582  # CdhCore.health.HLTH_PING_WRONG_KEY (string, U32), Ref.dpDemo.DpMemoryFail
COUNT_CHANNEL_ID, COLOR_CHANNEL_ID = 16777216, 268455946  # CdhCore.cmdDisp.CommandsDispatched (U32), Ref.typeDemo.ScalarU8Ch
HELLO_TEXT, PLAIN_TEXT = "Ping entry world responded with wrong key 0x3", "Failed to acquire a DP buffer"
FW_PACKET_TELEM, FW_PACKET_LOG = 1, 2


@pytest.fixture(scope="module", autouse=True)
def dictionary_path(tmp_path_factory):
    """Add the Svc.ComLoggerDp record and container (as Ref would declare them) to the Ref dictionary fixture"""
    global DICTIONARY_PATH
    dictionary = json.loads(REF_DICTIONARY.read_text())
    u8 = {"name": "U8", "kind": "integer", "size": 8, "signed": False}
    dictionary["records"].append({"name": "Ref.comLogger.ComBufferRecord", "type": u8, "array": True, "id": CONTAINER_ID})
    dictionary["containers"].append({"name": "Ref.comLogger.ComBuffContainer", "id": CONTAINER_ID, "defaultPriority": 5})
    DICTIONARY_PATH = tmp_path_factory.mktemp("dictionary") / "dictionary.json"
    DICTIONARY_PATH.write_text(json.dumps(dictionary))


@pytest.fixture
def dictionaries():
    globals_cleanup()
    yield Dictionaries.load_dictionaries_into_config(str(DICTIONARY_PATH))
    globals_cleanup()


def time_bytes(seconds, useconds=0):
    return TimeType(time_base=2, time_context=0, seconds=seconds, useconds=useconds).serialize()


def telemetry_packet(*channels):
    """Com buffer holding one telemetry packet of (channel id, time seconds, serialized value) entries"""
    data = U16Type(FW_PACKET_TELEM).serialize()
    for channel_id, seconds, value in channels:
        data += U32Type(channel_id).serialize() + time_bytes(seconds) + value
    return data


def event_packet(event_id, seconds, *args):
    """Com buffer holding one event packet"""
    return U16Type(FW_PACKET_LOG).serialize() + U32Type(event_id).serialize() + time_bytes(seconds) + b"".join(args)


def record(com_buffer, sentry=DEFAULT_SENTRY):
    """One ComBufferRecord as written in the product: record id, size, sentry, Com buffer"""
    data = U32Type(sentry).serialize() + com_buffer
    return U32Type(CONTAINER_ID).serialize() + U16Type(len(data)).serialize() + data


def product(*records, container_id=CONTAINER_ID, break_header_crc=False, break_data_crc=False):
    """A complete data product file: header, records, data CRC"""
    data = b"".join(records)
    config = ConfigManager()
    header_bytes = (
        U16Type(0).serialize()
        + U32Type(container_id).serialize()
        + config.get_type("FwDpPriorityType")(5).serialize()
        + time_bytes(100)
        + config.get_type("Fw.DpCfg.ProcType").REP_TYPE(0).serialize()
        + b"\x00" * config.get_constant("Fw.DpCfg.CONTAINER_USER_DATA_SIZE")
        + config.get_type("Fw.DpState")("UNTRANSMITTED").serialize()
        + U16Type(len(data)).serialize()
        + U32Type(0).serialize()
    )
    assert len(header_bytes) == get_dp_header_type()().getMaxSize()
    header_crc = calculate_crc32(header_bytes[:-ChecksumConfig.CHECKSUM_LEN]) ^ (0xFF if break_header_crc else 0)
    data_crc = calculate_crc32(data) ^ (0xFF if break_data_crc else 0)
    return header_bytes[:-ChecksumConfig.CHECKSUM_LEN] + U32Type(header_crc).serialize() + data + U32Type(data_crc).serialize()


def sample_records():
    """Two channels in one telemetry packet, an event with a string then a number, and a plain event"""
    return [
        record(telemetry_packet((COUNT_CHANNEL_ID, 10, U32Type(7).serialize()), (COLOR_CHANNEL_ID, 11, U8Type(1).serialize()))),
        record(event_packet(HELLO_EVENT_ID, 12, StringType.construct_type("S40", 40)("world").serialize(), U32Type(3).serialize())),
        record(event_packet(PLAIN_EVENT_ID, 9)),
    ]


def write(path, data):
    path.write_bytes(data)
    return path


class TestComLoggerDpDecoder:
    def test_decode_channels_and_events(self, dictionaries, tmp_path):
        path = write(tmp_path / "Dp_00001024_1.fdp", product(*sample_records()))
        result = ComLoggerDpDecoder(dictionaries).decode(path)

        assert result["Header"]["Id"]["value"] == CONTAINER_ID
        assert result["Statistics"] == {"Records": 3, "Events": 2, "Channels": 2, "Errors": 0}
        telemetry, hello, plain = result["Records"]
        assert telemetry["PacketType"] == "FW_PACKET_TELEM"
        assert [(ch.template.get_full_name(), ch.get_val(), ch.time.seconds) for ch in telemetry["Packets"]] == [
            ("CdhCore.cmdDisp.CommandsDispatched", 7, 10), ("Ref.typeDemo.ScalarU8Ch", 1, 11)]
        assert hello["PacketType"] == "FW_PACKET_LOG"
        assert hello["Packets"][0].display_text == HELLO_TEXT
        assert plain["Packets"][0].display_text == PLAIN_TEXT
        assert "Data" not in telemetry

    def test_bad_sentry_is_reported_per_record(self, dictionaries, tmp_path):
        path = write(tmp_path / "a.fdp", product(record(event_packet(PLAIN_EVENT_ID, 1), sentry=0x12345678), *sample_records()))
        result = ComLoggerDpDecoder(dictionaries).decode(path)
        assert result["Statistics"]["Errors"] == 1
        assert "Sentry mismatch" in result["Records"][0]["Error"]
        assert result["Records"][0]["Data"]["values"][:4] == [0x12, 0x34, 0x56, 0x78]
        assert result["Statistics"]["Events"] == 2

        assert ComLoggerDpDecoder(dictionaries, sentry=0x12345678).decode(path)["Records"][0]["Packets"][0].display_text == PLAIN_TEXT
        assert ComLoggerDpDecoder(dictionaries, validate_sentry=False).decode(path)["Statistics"]["Errors"] == 0

    def test_invalid_time_tag_is_reported_per_record(self, dictionaries, tmp_path):
        bad_time = U16Type(FW_PACKET_LOG).serialize() + U32Type(PLAIN_EVENT_ID).serialize() + time_bytes(1)[:-4] + U32Type(1_000_000).serialize()
        path = write(tmp_path / "a.fdp", product(record(bad_time), *sample_records()))
        result = ComLoggerDpDecoder(dictionaries).decode(path)
        assert "Invalid time tag" in result["Records"][0]["Error"]
        assert result["Statistics"]["Errors"] == 1 and result["Statistics"]["Events"] == 2
        write_json(result, tmp_path / "a.json")
        write_text(result, tmp_path / "a.txt")
        assert json.loads((tmp_path / "a.json").read_text())["Statistics"]["Errors"] == 1

    def test_crc_validation(self, dictionaries, tmp_path):
        path = write(tmp_path / "a.fdp", product(*sample_records(), break_data_crc=True))
        with pytest.raises(CRCError, match="CRC mismatch"):
            ComLoggerDpDecoder(dictionaries).decode(path)
        truncated = write(tmp_path / "b.fdp", product(*sample_records())[:-ChecksumConfig.CHECKSUM_LEN])
        with pytest.raises(Exception):
            ComLoggerDpDecoder(dictionaries).decode(truncated)
        assert ComLoggerDpDecoder(dictionaries, validate_crc=False).decode(truncated)["Statistics"]["Events"] == 2
        assert ComLoggerDpDecoder(dictionaries, validate_crc=False).decode(path)["Statistics"]["Events"] == 2

    def test_unsupported_packet_type(self, dictionaries, tmp_path):
        path = write(tmp_path / "a.fdp", product(record(U16Type(4).serialize() + b"\x00" * 8)))
        result = ComLoggerDpDecoder(dictionaries).decode(path)
        assert "Unsupported packet type FW_PACKET_PACKETIZED_TLM" in result["Records"][0]["Error"]

    def test_reconstruct_damaged_file(self, dictionaries, tmp_path):
        good = product(*sample_records())
        damaged = b"\x00" * 7 + good[20:]  # header destroyed, records intact
        path = write(tmp_path / "a.fdp", damaged)
        result = ComLoggerDpDecoder(dictionaries).reconstruct(path)
        assert result["File"]["sentries_found"] == 3
        assert result["Statistics"] == {"Records": 3, "Events": 2, "Channels": 2, "Errors": 0}
        assert result["Records"][1]["Packets"][0].display_text == HELLO_TEXT

    def test_malformed_record_data(self, dictionaries):
        decoder = ComLoggerDpDecoder(dictionaries)
        with pytest.raises(DataProductError, match="too short"):
            decoder.decode_record_data(b"\xde\xad")
        with pytest.raises(DataProductError, match="Unknown packet descriptor"):
            decoder.decode_com_buffer(b"\xff" * 8)

    def test_reconstruct_without_length_prefixes(self, dictionaries, tmp_path):
        records = sample_records()
        damaged = bytearray(b"".join(records))
        last = sum(len(item) for item in records[:-1])
        for offset in (4, 5, last + 4, last + 5):  # corrupt the length prefixes of the first and last records
            damaged[offset] = 0xFF
        result = ComLoggerDpDecoder(dictionaries).reconstruct(write(tmp_path / "a.fdp", bytes(damaged)))
        assert result["Statistics"]["Channels"] == 2
        assert result["Statistics"]["Errors"] == 0

    def test_reconstruct_last_record_followed_by_crc(self, dictionaries, tmp_path):
        records = [sample_records()[2], sample_records()[0]]  # the telemetry record comes last
        damaged = bytearray(b"".join(records) + b"\x12\x34\x56\x78")  # followed by the product's data CRC
        last = len(records[0])
        damaged[last + 4] = damaged[last + 5] = 0xFF  # corrupt the length prefix of the last record
        result = ComLoggerDpDecoder(dictionaries).reconstruct(write(tmp_path / "a.fdp", bytes(damaged)))
        assert result["Statistics"]["Channels"] == 2
        assert result["Statistics"]["Errors"] == 0
        assert result["Records"][1]["Record"]["size"] == len(records[1]) - 6


def run_comlog(*args):
    with mock.patch.object(sys, "argv", ["fprime-dp", "comlog", "-d", str(DICTIONARY_PATH), *[str(arg) for arg in args]]):
        return main()


@pytest.mark.usefixtures("dictionaries")  # types must be loaded to build products; `main` reloads the dictionary itself
class TestComlogCommand:
    @pytest.fixture
    def product_dir(self, tmp_path):
        write(tmp_path / "Dp_00001024_10.fdp", product(*sample_records()))
        write(tmp_path / "Dp_00001024_20.fdp", product(record(event_packet(PLAIN_EVENT_ID, 5)), record(telemetry_packet((COUNT_CHANNEL_ID, 1, U32Type(1).serialize())))))
        write(tmp_path / "Dp_00001024_30.bin", product(record(event_packet(PLAIN_EVENT_ID, 50)), container_id=7))  # misleading name
        return tmp_path

    def test_single_file_json_and_text(self, tmp_path):
        path = write(tmp_path / "a.fdp", product(*sample_records()))
        assert run_comlog("-b", path) == 0
        data = json.loads((tmp_path / "a.json").read_text())
        packets = data["Records"][0]["Packets"]
        assert [(p["type"], p["name"], p["value"]) for p in packets] == [("channel", "CdhCore.cmdDisp.CommandsDispatched", 7), ("channel", "Ref.typeDemo.ScalarU8Ch", 1)]
        hello = data["Records"][1]["Packets"][0]
        assert hello["severity"] == "EventSeverity.FATAL"
        assert hello["args"] == [{"name": "entry", "value": "world"}, {"name": "badKey", "value": 3}]
        assert data["Statistics"]["Events"] == 2
        text = (tmp_path / "a.txt").read_text()
        assert HELLO_TEXT in text and "Ref.typeDemo.ScalarU8Ch (268455946)" in text

    def test_directory_with_dp_id_filter(self, product_dir):
        assert run_comlog("-B", product_dir, "--dp-id", "0x400", "-f", "text", "-o", product_dir / "out") == 0
        written = sorted(p.name for p in (product_dir / "out").iterdir())
        assert written == ["Dp_00001024_10.txt", "Dp_00001024_20.txt"]

    def test_collect(self, product_dir):
        assert run_comlog("-B", product_dir, "--collect", "-o", product_dir / "logs") == 0
        channels = (product_dir / "logs" / CHANNEL_LOG_NAME).read_text().splitlines()
        events = (product_dir / "logs" / EVENT_LOG_NAME).read_text().splitlines()
        assert channels[0] == "Time,Raw Time,Name,ID,Value"
        assert [line.split(",")[2] for line in channels[1:]] == ["CdhCore.cmdDisp.CommandsDispatched", "CdhCore.cmdDisp.CommandsDispatched", "Ref.typeDemo.ScalarU8Ch"]
        event_seconds = [int(line.split(",")[1].split("-")[1].split(":")[0]) for line in events[1:]]
        assert event_seconds == sorted(event_seconds) == [5, 9, 12, 50]
        assert len(events) == 1 + 4
        assert events[1].endswith(",Ref.dpDemo.DpMemoryFail,2582,EventSeverity.WARNING_HI,Failed to acquire a DP buffer")

    def test_reconstruct_and_failures(self, tmp_path):
        path = write(tmp_path / "a.fdp", product(*sample_records(), break_header_crc=True))
        assert run_comlog("-b", path) == 1
        assert run_comlog("-b", path, "--no-crc") == 0
        assert run_comlog("-b", path, "--reconstruct", "-f", "both") == 0
        data = json.loads((tmp_path / "a_reconstructed.json").read_text())
        assert data["File"]["sentries_found"] == 3 and data["Statistics"]["Events"] == 2
        assert "[Record 0 @ " in (tmp_path / "a_reconstructed.txt").read_text()

    def test_sentry_options(self, tmp_path):
        path = write(tmp_path / "a.fdp", product(record(event_packet(PLAIN_EVENT_ID, 1), sentry=0xCAFEF00D)))
        assert run_comlog("-b", path, "-f", "text") == 1
        assert "ERROR: Sentry mismatch" in (tmp_path / "a.txt").read_text()
        assert run_comlog("-b", path, "-f", "json", "--sentry", "0xCAFEF00D") == 0
        assert run_comlog("-b", path, "-f", "json", "--no-sentry") == 0
        assert run_comlog("-b", path, "-f", "json", "--reconstruct", "--sentry", "0xCAFEF00D") == 0
        assert json.loads((tmp_path / "a_reconstructed.json").read_text())["Statistics"]["Events"] == 1
