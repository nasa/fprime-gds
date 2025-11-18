import pytest
from fprime_gds.common.communication.ccsds.space_packet import SpacePacketFramerDeframer
from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.models.serialize.type_exceptions import TypeRangeException

@pytest.fixture
def framer_deframer():
    return SpacePacketFramerDeframer()

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
    """Test deframing a valid space packet."""
    apid = 0x123
    pkt_seq_count = 0x0001
    payload = b"0123456789"
    pkt_data_len = len(payload) - 1
    space_header = SpacePacketHeader(
        packet_type=PacketType.TM,
        apid=apid,
        seq_count=pkt_seq_count,
        data_len=pkt_data_len,
    )
    space_packet_bytes = SpacePacket(space_header, sec_header=None, user_data=payload).pack()

    input_data = b"GARBAGE" + space_packet_bytes + b"TRAILING_GARBAGE"

    deframed, remaining_data, discarded = framer_deframer.deframe(input_data)

    assert deframed == payload
    assert remaining_data == b"TRAILING_GARBAGE"
    assert discarded == b"GARBAGE"

def test_deframe_multiple_packets(framer_deframer):
    """Test deframing multiple concatenated space packets."""
    # First packet
    apid1 = 0x100
    seq1 = 0x000A
    payload1 = b"packet_one_payload"
    pkt_data_len1 = len(payload1) - 1
    header1 = SpacePacketHeader(
        packet_type=PacketType.TM,
        apid=apid1,
        seq_count=seq1,
        data_len=pkt_data_len1,
    )
    packet1 = SpacePacket(header1, sec_header=None, user_data=payload1).pack()

    # Second packet
    apid2 = 0x200
    seq2 = 0x000B
    payload2 = b"another_packet_data"
    pkt_data_len2 = len(payload2) - 1
    header2 = SpacePacketHeader(
        packet_type=PacketType.TM,
        apid=apid2,
        seq_count=seq2,
        data_len=pkt_data_len2,
    )
    packet2 = SpacePacket(header2, sec_header=None, user_data=payload2).pack()

    input_data = packet1 + packet2
    deframed, remaining_data, discarded = framer_deframer.deframe_all(input_data, no_copy=False)

    assert len(deframed) == 2
    assert deframed[0] == payload1
    assert deframed[1] == payload2
    assert remaining_data == b""
    assert discarded == b""

def test_deframe_incomplete_packet(framer_deframer):
    """Test deframing with an incomplete packet at the end."""
    header = SpacePacketHeader(
        packet_type=PacketType.TM,
        apid=0,
        seq_count=0,
        data_len=0,
    )
    packet = SpacePacket(header, sec_header=None, user_data=b"").pack()
    incomplete_packet_bytes = packet[:-1]  # Remove last byte to simulate an incomplete packet
    packets, remaining_data, discarded = framer_deframer.deframe_all(incomplete_packet_bytes, no_copy=False)
    assert len(packets) == 0
    assert remaining_data == incomplete_packet_bytes
    assert discarded == b""

def test_deframe_only_garbage(framer_deframer):
    """Test deframing data that contains no valid packet start."""
    garbage_data = b"this is not a ccsds packet at all"
    packets, remaining_data, discarded = framer_deframer.deframe_all(garbage_data, no_copy=False)
    assert len(packets) == 0
    assert discarded in garbage_data
    assert remaining_data in garbage_data
