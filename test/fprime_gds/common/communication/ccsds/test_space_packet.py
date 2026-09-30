import logging

import pytest
from fprime_gds.common.communication.ccsds.space_packet import SpacePacketFramerDeframer
from fprime_gds.common.communication.ccsds.chain import RawSpacePacketFramerDeframer
from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.models.serialize.type_exceptions import TypeRangeException

from ccsds_streams import IDLE_APID, make_space_packet

@pytest.fixture
def framer_deframer():
    return SpacePacketFramerDeframer()

@pytest.fixture
def chain():
    return RawSpacePacketFramerDeframer()

def test_frame_valid_data(framer_deframer):
    """Test framing valid data (if applicable)."""
    # Prefix with Descriptor, as expected by framer
    test_descriptor = ConfigManager().get_type("ComCfg.Apid")("FW_PACKET_UNKNOWN")
    data = test_descriptor.serialize() + b"test_payload"
    framed_data = framer_deframer.frame(data)
    header = SpacePacketHeader.unpack(framed_data)
    assert header.packet_type == PacketType.TC
    assert header.apid == test_descriptor.numeric_value
    assert header.data_len == len(data) - 1
    assert header.ccsds_version == 0b000  # Default version for CCSDS packets
    assert header.seq_count == 0

def test_frame_invalid_data(framer_deframer):
    """Test framing valid data with an incorrect DataDescType prefixed."""
    # Prefix with 2 bytes corresponding to the DataDescType (FF FF not valid)
    descriptor = ConfigManager().get_type("FwPacketDescriptorType")()
    descriptor.val = 0xFFFF  # invalid value
    data = descriptor.serialize() + b"test_payload"
    # Invalid DataDescType, should raise TypeRangeException
    with pytest.raises(TypeRangeException):
        framer_deframer.frame(data)

def test_deframe_valid_packet(framer_deframer):
    """Test deframing a single whole space packet into its payload."""
    apid = 0x123
    payload = b"0123456789"
    space_header = SpacePacketHeader(
        packet_type=PacketType.TM,
        apid=apid,
        seq_count=0,
        data_len=len(payload) - 1,
    )
    space_packet_bytes = SpacePacket(space_header, sec_header=None, user_data=payload).pack()

    deframed, remaining_data, discarded = framer_deframer.deframe(space_packet_bytes)

    assert deframed == payload
    assert remaining_data == b""
    assert discarded == b""

def test_deframe_trailing_data_discarded(framer_deframer):
    """Test that input longer than the single packet it starts with is discarded."""
    packet = make_space_packet(0x100, 0, b"packet_one_payload")
    input_data = packet + b"TRAILING"
    deframed, remaining_data, discarded = framer_deframer.deframe(input_data)
    assert deframed is None
    assert remaining_data == b""
    assert discarded == input_data

def test_deframe_incomplete_packet(framer_deframer):
    """Test that an incomplete packet is discarded."""
    packet = make_space_packet(0, 0, b"0123")
    incomplete_packet_bytes = packet[:-1]  # Remove last byte to simulate an incomplete packet
    packets, remaining_data, discarded = framer_deframer.deframe_all(incomplete_packet_bytes, no_copy=False)
    assert len(packets) == 0
    assert remaining_data == b""
    assert discarded == incomplete_packet_bytes

def test_deframe_only_garbage(framer_deframer):
    """Test that data without a valid packet header is discarded."""
    garbage_data = b"this is not a ccsds packet at all"
    packets, remaining_data, discarded = framer_deframer.deframe_all(garbage_data, no_copy=False)
    assert len(packets) == 0
    assert remaining_data == b""
    assert discarded == garbage_data

def test_deframe_none(framer_deframer):
    """Test that None input yields no packet."""
    assert framer_deframer.deframe(None) == (None, None, b"")

def test_deframe_sequence_count_warning(framer_deframer, caplog):
    """Test that a sequence count gap warns with the expected value and resynchronizes the count."""
    with caplog.at_level(logging.WARNING, logger="framing"):
        assert framer_deframer.deframe(make_space_packet(0x100, 0, b"a"))[0] == b"a"
        assert len(caplog.records) == 0
        assert framer_deframer.deframe(make_space_packet(0x100, 3, b"b"))[0] == b"b"
        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == "APID 256 received sequence count: 3 (expected: 1)"
        assert framer_deframer.deframe(make_space_packet(0x100, 4, b"c"))[0] == b"c"
        assert len(caplog.records) == 1

def test_chain_deframe_valid_packet(chain):
    """Test the raw-space-packet chain deframing a packet surrounded by garbage."""
    payload = b"0123456789"
    packet = make_space_packet(0x123, 1, payload)
    input_data = b"\xFF\xFF\xFF" + packet + b"\xFF" * 8

    packets, remaining_data, discarded = chain.deframe_all(input_data, no_copy=False)

    assert packets == [payload]
    # Trailing bytes fewer than a header are held as a possible packet start
    assert remaining_data == b"\xFF" * 5
    assert discarded == b"\xFF" * 6

def test_chain_deframe_multiple_packets(chain):
    """Test the raw-space-packet chain deframing concatenated packets, dropping idle packets."""
    payload1 = b"packet_one_payload"
    payload2 = b"another_packet_data"
    input_data = (
        make_space_packet(0x100, 0, payload1)
        + make_space_packet(IDLE_APID, 0, bytes(7))
        + make_space_packet(0x200, 0, payload2)
    )
    packets, remaining_data, discarded = chain.deframe_all(input_data, no_copy=False)

    assert packets == [payload1, payload2]
    assert remaining_data == b""
    assert discarded == b""

def test_chain_deframe_chunked_stream(chain):
    """Test the raw-space-packet chain over a byte-at-a-time stream, packets and idle spanning chunks."""
    payloads = [b"first", b"second_payload", b"third"]
    stream = (
        make_space_packet(0x100, 0, payloads[0])
        + make_space_packet(IDLE_APID, 0, bytes(12))
        + make_space_packet(0x101, 0, payloads[1])
        + b"\xFF\xFF"
        + make_space_packet(0x100, 1, payloads[2])
    )
    packets = []
    pending = b""
    for index in range(len(stream)):
        pending += stream[index : index + 1]
        new_packets, pending, discarded = chain.deframe_all(pending, no_copy=False)
        packets.extend(new_packets)
    assert packets == payloads
    assert pending == b""

def test_chain_deframe_incomplete_packet(chain):
    """Test the raw-space-packet chain holding an incomplete packet as remaining data."""
    packet = make_space_packet(0, 0, b"0123")
    incomplete_packet_bytes = packet[:-1]
    packets, remaining_data, discarded = chain.deframe_all(incomplete_packet_bytes, no_copy=False)
    assert len(packets) == 0
    assert remaining_data == incomplete_packet_bytes
    assert discarded == b""
