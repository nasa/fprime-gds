"""Tests for the TM frame aggregating framer/deframer (tm-frame-aggregator plugin)"""

import struct

import pytest

from fprime_gds.common.communication.ccsds.tm_frame_aggregator import (
    TmFrameAggregatorFramerDeframer,
)
from fprime_gds.common.utils.config_manager import (
    ConfigBadTypeException,
    ConfigManager,
)
from fprime_gds.executables.cli import ParserBase, PluginArgumentParser
from fprime_gds.plugin.system import Plugins

FRAME_SIZE = 64
SCID = 0x44
FRAME_SIZE_CONSTANT = "ComCfg.TmFrameFixedSize"
SCID_CONSTANT = "ComCfg.SpacecraftId"


@pytest.fixture
def constants(monkeypatch):
    """Control the dictionary constants seen by the deframer without touching the ConfigManager singleton"""
    values = {FRAME_SIZE_CONSTANT: FRAME_SIZE, SCID_CONSTANT: SCID}

    def get_constant(self, name):
        if name not in values:
            raise ConfigBadTypeException("Unknown constant name", name)
        return values[name]

    monkeypatch.setattr(ConfigManager, "get_constant", get_constant)
    return values


@pytest.fixture
def plugin_system():
    """Framing-only plugin system installed as the singleton for CLI binding tests"""
    previous = Plugins._singleton
    system = Plugins(["framing"])
    Plugins._singleton = system
    yield system
    Plugins._singleton = previous


@pytest.fixture
def deframer(constants):
    """Deframer configured entirely from the (patched) dictionary constants"""
    return TmFrameAggregatorFramerDeframer()


DATA_FIELD_SIZE = FRAME_SIZE - 6 - 2
# Data field status as emitted by Svc::Ccsds::TmFramer: flags clear, segment length ID 0b11, FHP variable
SEGMENT_LENGTH_ID = 0x3 << 11
FHP_IDLE = 0x7FE
FHP_NO_PACKET_START = 0x7FF


def make_frame(
    scid=SCID, vcid=1, mc_count=0, fill=0xAB, size=FRAME_SIZE, version=0, fhp=0, dfs_flags=0
):
    """Build a fixed-size TM frame with the given header fields (trailer is arbitrary; CRC is not checked)"""
    global_vcid = (version << 14) | ((scid & 0x3FF) << 4) | ((vcid & 0x7) << 1)
    data_field_status = dfs_flags | SEGMENT_LENGTH_ID | fhp
    header = struct.pack(">HBBH", global_vcid, mc_count, mc_count, data_field_status)
    trailer = b"\xCC\xCC"
    return header + bytes([fill]) * (size - len(header) - len(trailer)) + trailer


class TestConfiguration:
    """REQ-TMF-001/002: frame size and SCID come from the dictionary unless overridden on the CLI"""

    def test_frame_size_from_dictionary(self, deframer):
        assert deframer.frame_size == FRAME_SIZE
        assert deframer.scid == SCID

    def test_cli_override_takes_precedence(self, constants, capsys):
        deframer = TmFrameAggregatorFramerDeframer(frame_size=128, scid=0x55)
        assert deframer.frame_size == 128
        assert deframer.scid == 0x55
        captured = capsys.readouterr()
        assert "frame size" in captured.err.lower()
        assert "scid" in captured.err.lower()

    def test_cli_matching_dictionary_no_warning(self, constants, capsys):
        TmFrameAggregatorFramerDeframer(frame_size=FRAME_SIZE, scid=SCID)
        assert capsys.readouterr().err == ""

    def test_missing_frame_size_raises(self, constants):
        del constants[FRAME_SIZE_CONSTANT]
        with pytest.raises(ValueError, match=FRAME_SIZE_CONSTANT):
            TmFrameAggregatorFramerDeframer()

    def test_missing_frame_size_cli_fallback(self, constants):
        del constants[FRAME_SIZE_CONSTANT]
        assert TmFrameAggregatorFramerDeframer(frame_size=FRAME_SIZE).frame_size == FRAME_SIZE

    def test_missing_scid_disables_scid_check(self, constants, capsys):
        del constants[SCID_CONSTANT]
        deframer = TmFrameAggregatorFramerDeframer()
        assert deframer.scid is None
        assert "spacecraft id unknown" in capsys.readouterr().err.lower()
        frame = make_frame(scid=0x123)
        assert deframer.deframe(frame) == (frame, b"", b"")

    @pytest.mark.parametrize(
        "name,value,match",
        [
            (FRAME_SIZE_CONSTANT, 0, "must exceed header and trailer"),
            (FRAME_SIZE_CONSTANT, 8, "must exceed header and trailer"),
            (SCID_CONSTANT, 0x400, "larger than"),
        ],
    )
    def test_invalid_dictionary_values_rejected(self, constants, name, value, match):
        constants[name] = value
        with pytest.raises(TypeError, match=match):
            TmFrameAggregatorFramerDeframer()


class TestDeframe:
    """REQ-TMF-003..007: aggregate stream bytes into intact fixed-size frames"""

    def test_whole_frame_intact(self, deframer):
        frame = make_frame()
        assert deframer.deframe(frame) == (frame, b"", b"")

    def test_partial_frame_retained(self, deframer):
        frame = make_frame()
        assert deframer.deframe(frame[:10]) == (None, frame[:10], b"")

    def test_sub_header_bytes_retained(self, deframer):
        assert deframer.deframe(b"\x04") == (None, b"\x04", b"")
        assert deframer.deframe(b"") == (None, b"", b"")

    def test_frame_split_across_reads(self, deframer):
        frame = make_frame()
        pending = b""
        for chunk in (frame[:7], frame[7:40]):
            packets, pending, discarded = deframer.deframe_all(pending + chunk, no_copy=False)
            assert (packets, discarded) == ([], b"")
        assert pending == frame[:40]
        packets, pending, discarded = deframer.deframe_all(pending + frame[40:], no_copy=False)
        assert (packets, pending, discarded) == ([frame], b"", b"")

    def test_multiple_frames_and_tail_in_one_read(self, deframer):
        first, second, third = make_frame(fill=1), make_frame(fill=2), make_frame(fill=3)
        packets, leftover, discarded = deframer.deframe_all(first + second + third[:20], no_copy=False)
        assert packets == [first, second]
        assert leftover == third[:20]
        assert discarded == b""

    def test_garbage_prefix_discarded(self, deframer):
        # 0xFF has version bits 0b11, so it can never be a frame start
        garbage = b"\xFF\xFE\xFD"
        frame = make_frame()
        assert deframer.deframe(garbage + frame) == (frame, b"", garbage)

    def test_garbage_then_partial_frame(self, deframer):
        garbage = b"\xFF\xFE"
        frame = make_frame()
        assert deframer.deframe(garbage + frame[:10]) == (None, frame[:10], garbage)

    def test_garbage_only(self, deframer):
        garbage = b"\xFF\xFE\xFD"
        packets, leftover, discarded = deframer.deframe_all(garbage, no_copy=False)
        # The final byte cannot yet be tested as a header start and is retained
        assert (packets, leftover, discarded) == ([], garbage[-1:], garbage[:-1])

    @pytest.mark.parametrize("version", [1, 2, 3])
    def test_bad_version_discarded(self, deframer, version):
        # Correct SCID, so only the version check can reject this header
        bad = make_frame(version=version)
        good = make_frame()
        assert deframer.deframe(bad + good) == (good, b"", bad)

    def test_bad_version_discarded_without_scid(self, constants):
        del constants[SCID_CONSTANT]
        deframer = TmFrameAggregatorFramerDeframer()
        garbage = b"\xFF\xFF\xFF"
        good = make_frame(scid=0x123)
        assert deframer.deframe(garbage + good) == (good, b"", garbage)

    def test_scid_mismatch_resynchronizes(self, deframer):
        bad = make_frame(scid=SCID + 1)
        good = make_frame()
        packet, leftover, discarded = deframer.deframe(bad + good)
        assert packet == good
        assert leftover == b""
        # Scanning slips one byte at a time until the good header lines up
        assert len(discarded) == FRAME_SIZE
        assert discarded == bad

    @pytest.mark.parametrize(
        "fhp", [0, 1, DATA_FIELD_SIZE // 2, DATA_FIELD_SIZE - 1, FHP_IDLE, FHP_NO_PACKET_START]
    )
    def test_spanning_first_header_pointers_accepted(self, deframer, fhp):
        # Packets spanning frames move the FHP anywhere in the data field or to a reserved value
        frame = make_frame(fhp=fhp)
        assert deframer.deframe(frame) == (frame, b"", b"")

    @pytest.mark.parametrize("fhp", [DATA_FIELD_SIZE, DATA_FIELD_SIZE + 1, FHP_IDLE - 1])
    def test_first_header_pointer_beyond_data_field_discarded(self, deframer, fhp):
        bad = make_frame(fhp=fhp)
        good = make_frame()
        assert deframer.deframe(bad + good) == (good, b"", bad)

    @pytest.mark.parametrize(
        "dfs_flags",
        [1 << 14, 1 << 13, (1 << 14) | (1 << 13)],
        ids=["sync-flag", "packet-order-flag", "both-flags"],
    )
    def test_data_field_status_flags_set_discarded(self, deframer, dfs_flags):
        bad = make_frame(dfs_flags=dfs_flags)
        good = make_frame()
        assert deframer.deframe(bad + good) == (good, b"", bad)

    @pytest.mark.parametrize("segment_length_id", [0, 1, 2])
    def test_segment_length_id_not_11_discarded(self, deframer, segment_length_id):
        bad = bytearray(make_frame())
        struct.pack_into(">H", bad, 4, segment_length_id << 11)
        bad = bytes(bad)
        good = make_frame()
        assert deframer.deframe(bad + good) == (good, b"", bad)

    def test_secondary_header_flag_accepted(self, deframer):
        # Not constrained: a secondary header does not alter the fixed frame boundaries
        frame = make_frame(dfs_flags=1 << 15)
        assert deframer.deframe(frame) == (frame, b"", b"")

    def test_header_judged_progressively(self, deframer):
        # Bytes 0-5 alone look plausible; a bad data field status is rejected once byte 5 arrives
        bad = make_frame(dfs_flags=1 << 14)
        assert deframer.deframe(bad[:5]) == (None, bad[:5], b"")
        assert deframer.deframe(bad[:6]) == (None, bad[5:6], bad[:5])

    def test_one_byte_slip_resynchronizes_without_scid(self, constants):
        # Payload bytes rarely form a valid data field status, so a slip re-locks on the next real header
        del constants[SCID_CONSTANT]
        deframer = TmFrameAggregatorFramerDeframer()
        frames = [make_frame(fill=fill) for fill in (0x00, 0x11, 0x22)]
        stream = b"".join(frames)[1:]
        packets, leftover, discarded = deframer.deframe_all(stream, no_copy=False)
        assert packets == frames[1:]
        assert (leftover, discarded) == (b"", frames[0][1:])

    def test_all_virtual_channels_delivered(self, deframer):
        frames = [make_frame(vcid=vcid, fill=vcid) for vcid in range(8)]
        packets, leftover, discarded = deframer.deframe_all(b"".join(frames), no_copy=False)
        assert packets == frames
        assert (leftover, discarded) == (b"", b"")

    def test_no_copy_input_untouched_when_false(self, deframer):
        frame = bytearray(make_frame())
        original = bytes(frame)
        deframer.deframe(frame, no_copy=False)
        assert bytes(frame) == original

    def test_stateless_between_frames(self, deframer):
        # Master channel counts jump; frames are still delivered independently
        frames = [make_frame(mc_count=count) for count in (5, 200, 3)]
        for frame in frames:
            assert deframer.deframe(frame) == (frame, b"", b"")


class TestFrame:
    """REQ-TMF-008: uplink is pass-through"""

    def test_frame_identity(self, deframer):
        data = b"\x01\x02\x03uplink"
        assert deframer.frame(data) == data
        assert deframer.frame(b"") == b""


class TestPlugin:
    """REQ-TMF-009: registered as a built-in framing plugin"""

    def test_name(self):
        assert TmFrameAggregatorFramerDeframer.get_name() == "tm-frame-aggregator"

    def test_registered_built_in(self):
        built_ins = Plugins.get_plugin_metadata("framing")["built-in"]
        assert TmFrameAggregatorFramerDeframer in built_ins

    def test_arguments(self):
        flags = {flag for flags in TmFrameAggregatorFramerDeframer.get_arguments() for flag in flags}
        assert flags == {"--frame-size", "--scid"}

    @pytest.mark.parametrize("frame_size,scid", [(None, None), (1024, None), (None, 0x3FF), (9, 0)])
    def test_check_arguments_accepts(self, constants, frame_size, scid):
        TmFrameAggregatorFramerDeframer.check_arguments(frame_size=frame_size, scid=scid)

    @pytest.mark.parametrize(
        "frame_size,scid,match",
        [
            (8, None, "must exceed header and trailer"),
            (0, None, "must exceed header and trailer"),
            (-1, None, "must exceed header and trailer"),
            (None, -1, "negative"),
            (None, 0x400, "larger than"),
        ],
    )
    def test_check_arguments_rejects(self, constants, frame_size, scid, match):
        with pytest.raises(TypeError, match=match):
            TmFrameAggregatorFramerDeframer.check_arguments(frame_size=frame_size, scid=scid)

    def test_check_arguments_ignores_dictionary(self, constants):
        # Parsers run in no fixed order, so an unloaded dictionary must not fail the CLI check
        del constants[FRAME_SIZE_CONSTANT]
        TmFrameAggregatorFramerDeframer.check_arguments(frame_size=None, scid=None)

    def test_cli_binding(self, constants, plugin_system):
        ParserBase.parse_args(
            [PluginArgumentParser(plugin_system)],
            arguments=["--framing-selection", "tm-frame-aggregator", "--frame-size", "0x80", "--scid", "0x55"],
        )
        instance = plugin_system.get_selected_class("framing")()
        assert isinstance(instance, TmFrameAggregatorFramerDeframer)
        assert (instance.frame_size, instance.scid) == (0x80, 0x55)

    def test_cli_rejects_invalid_frame_size(self, constants, plugin_system):
        with pytest.raises(SystemExit):
            ParserBase.parse_args(
                [PluginArgumentParser(plugin_system)],
                arguments=["--framing-selection", "tm-frame-aggregator", "--frame-size", "8"],
            )

    def test_cli_without_frame_size_defers_to_constructor(self, constants, plugin_system):
        # The dictionary parser may run after this plugin's check; only construction can fail
        del constants[FRAME_SIZE_CONSTANT]
        ParserBase.parse_args(
            [PluginArgumentParser(plugin_system)],
            arguments=["--framing-selection", "tm-frame-aggregator"],
        )
        with pytest.raises(ValueError, match=FRAME_SIZE_CONSTANT):
            plugin_system.get_selected_class("framing")()
        # Dictionary loaded after the plugin check (the adverse parser order) must still work
        constants[FRAME_SIZE_CONSTANT] = FRAME_SIZE
        assert plugin_system.get_selected_class("framing")().frame_size == FRAME_SIZE
