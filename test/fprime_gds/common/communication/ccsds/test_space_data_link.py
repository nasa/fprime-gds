import pytest
import struct

from fprime_gds.common.communication.ccsds.space_data_link import (
    SpaceDataLinkFramerDeframer,
)

SCID_TEST_VALUE = 0x77
VCID_TEST_VALUE = 5
FRAME_SIZE_TEST_VALUE = 2222
DATA_FIELD_SIZE = (
    FRAME_SIZE_TEST_VALUE
    - SpaceDataLinkFramerDeframer.TM_HEADER_SIZE
    - SpaceDataLinkFramerDeframer.TM_TRAILER_SIZE
)


def make_space_packet(apid, total_size):
    """Build a Space Packet of the given total size (header + payload)"""
    payload_size = total_size - SpaceDataLinkFramerDeframer.SPACE_PACKET_HEADER_SIZE
    header = struct.pack(">HHH", apid & 0x7FF, 0xC000, payload_size - 1)
    return header + bytes([i % 256 for i in range(payload_size)])


def make_tm_frame(data_field, first_header_pointer, vc_count=0, mc_count=0, data_field_size=DATA_FIELD_SIZE):
    """Build a valid TM frame around the given data field"""
    assert len(data_field) == data_field_size
    global_vcid_u16 = (SCID_TEST_VALUE << 4) | (VCID_TEST_VALUE << 1)
    status_u16 = (0x3 << 11) | (first_header_pointer & SpaceDataLinkFramerDeframer.FHP_MASK)
    frame_no_crc = (
        struct.pack(">HBBH", global_vcid_u16, mc_count, vc_count, status_u16) + data_field
    )
    crc = SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(frame_no_crc)
    return frame_no_crc + struct.pack(">H", crc)

@pytest.fixture
def framer_deframer():
    return SpaceDataLinkFramerDeframer(scid=SCID_TEST_VALUE, vcid=VCID_TEST_VALUE, frame_size=FRAME_SIZE_TEST_VALUE)


def test_frame_valid_data(framer_deframer):
    """Test framing valid data."""
    data = b"test_payload"
    framed_data = framer_deframer.frame(data)
    expected_length = (
        len(data)
        + SpaceDataLinkFramerDeframer.TC_TRAILER_SIZE
        + SpaceDataLinkFramerDeframer.TC_HEADER_SIZE
    )
    assert data in framed_data
    assert len(framed_data) == expected_length
    scid = ((framed_data[0] & 0x03) << 2) | framed_data[1]
    assert scid == SCID_TEST_VALUE
    vcid = (framed_data[2] & 0xFC) >> 2
    assert vcid == VCID_TEST_VALUE


def test_deframe_valid_frame(framer_deframer):
    """Test deframing a valid TM frame."""
    FIXED_PAYLOAD_LENGTH = (
        framer_deframer.frame_size
        - SpaceDataLinkFramerDeframer.TM_HEADER_SIZE
        - SpaceDataLinkFramerDeframer.TM_TRAILER_SIZE
    )
    global_vcid_u16 = (SCID_TEST_VALUE << 4) | (VCID_TEST_VALUE << 1)
    mc_count_u8 = 0
    vc_count_u8 = 0
    status_u16 = 0
    # A data field containing a single complete Space Packet
    payload = make_space_packet(0x123, FIXED_PAYLOAD_LENGTH)
    input_data_no_crc = (
        struct.pack(
            ">HBBH",
            global_vcid_u16,
            mc_count_u8,
            vc_count_u8,
            status_u16,
        )
        + payload
    )
    crc = SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(input_data_no_crc)
    input_data = input_data_no_crc + struct.pack(">H", crc)
    deframed_data, remaining_data, discarded = framer_deframer.deframe(input_data)
    assert deframed_data == payload
    assert remaining_data == b""
    assert discarded == b""

def test_deframe_incorrect_crc(framer_deframer):
    """Test deframing a valid TM frame."""
    FIXED_PAYLOAD_LENGTH = (
        framer_deframer.frame_size
        - SpaceDataLinkFramerDeframer.TM_HEADER_SIZE
        - SpaceDataLinkFramerDeframer.TM_TRAILER_SIZE
    )
    global_vcid_u16 = (SCID_TEST_VALUE << 4) | (VCID_TEST_VALUE << 1)
    mc_count_u8 = 0
    vc_count_u8 = 0
    status_u16 = 0
    payload = bytes([i % 256 for i in range(FIXED_PAYLOAD_LENGTH)])
    input_data_no_crc = (
        struct.pack(
            ">HBBH",
            global_vcid_u16,
            mc_count_u8,
            vc_count_u8,
            status_u16,
        )
        + payload
    )
    crc = SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(input_data_no_crc) + 1  # Intentionally incorrect CRC
    input_data = input_data_no_crc + struct.pack(">H", crc)
    deframed_data, remaining_data, discarded = framer_deframer.deframe(input_data)
    assert deframed_data is None
    assert remaining_data == input_data[1:]
    assert discarded[0] == input_data[0]


def test_deframe_spanning_two_frames(framer_deframer):
    """A packet starting in one frame and ending in the next is reassembled."""
    small = make_space_packet(0x100, 100)
    span = make_space_packet(0x101, DATA_FIELD_SIZE + 184)
    frame1_portion = DATA_FIELD_SIZE - len(small)
    remainder = len(span) - frame1_portion
    idle = make_space_packet(0x7FF, DATA_FIELD_SIZE - remainder)
    frame1 = make_tm_frame(small + span[:frame1_portion], 0, vc_count=0)
    frame2 = make_tm_frame(span[frame1_portion:] + idle, remainder, vc_count=1)

    deframed, remaining, discarded = framer_deframer.deframe(frame1)
    assert deframed == small  # Only the complete packet is emitted; the spanning start is retained
    assert remaining == b""
    deframed, remaining, discarded = framer_deframer.deframe(frame2)
    assert deframed == span + idle
    assert remaining == b""
    assert discarded == b""


def test_deframe_spanning_three_frames(framer_deframer):
    """A packet spanning a complete middle frame (continuation-only, FHP=0x7FF) is reassembled."""
    first = make_space_packet(0x100, 200)
    span = make_space_packet(0x101, (DATA_FIELD_SIZE - len(first)) + DATA_FIELD_SIZE + 300)
    tail = 300
    idle = make_space_packet(0x7FF, DATA_FIELD_SIZE - tail)
    frame1 = make_tm_frame(first + span[: DATA_FIELD_SIZE - len(first)], 0, vc_count=0)
    frame2 = make_tm_frame(
        span[DATA_FIELD_SIZE - len(first) : 2 * DATA_FIELD_SIZE - len(first)],
        SpaceDataLinkFramerDeframer.FHP_NO_PACKET_START,
        vc_count=1,
    )
    frame3 = make_tm_frame(span[2 * DATA_FIELD_SIZE - len(first) :] + idle, tail, vc_count=2)

    deframed, remaining, discarded = framer_deframer.deframe(frame1)
    assert deframed == first
    # Continuation-only frame emits nothing
    deframed, remaining, discarded = framer_deframer.deframe(frame2)
    assert deframed is None
    assert remaining == b""
    deframed, remaining, discarded = framer_deframer.deframe(frame3)
    assert deframed == span + idle
    assert discarded == b""


def test_deframe_spanning_frame_loss_resync(framer_deframer):
    """Pending continuation data is discarded and deframing resyncs at the FHP after frame loss."""
    span = make_space_packet(0x101, DATA_FIELD_SIZE + 500)
    packet = make_space_packet(0x102, DATA_FIELD_SIZE - 500)
    frame1 = make_tm_frame(span[:DATA_FIELD_SIZE], 0, vc_count=0)
    # The frame with vc_count=1 is lost; frame3 starts with 500 continuation bytes of another lost packet
    frame3 = make_tm_frame(b"\xAA" * 500 + packet, 500, vc_count=2)

    deframed, remaining, discarded = framer_deframer.deframe(frame1)
    assert deframed is None  # Spanning packet start retained
    deframed, remaining, discarded = framer_deframer.deframe(frame3)
    assert deframed == packet  # Lost continuation dropped, resynced at the first header
    assert remaining == b""


def test_deframe_orphan_continuation_dropped(framer_deframer):
    """Leading continuation bytes with no pending packet (mid-stream attach) are dropped, not emitted."""
    packet = make_space_packet(0x102, DATA_FIELD_SIZE - 500)
    frame = make_tm_frame(b"\xAA" * 500 + packet, 500, vc_count=7)

    deframed, remaining, discarded = framer_deframer.deframe(frame)
    assert deframed == packet
    assert remaining == b""


def test_deframe_orphan_continuation_after_oversize_discard(framer_deframer):
    """After a pending packet is discarded for exceeding MAX_PACKET_SIZE, its continuation is dropped."""
    huge_start = make_space_packet(0x101, SpaceDataLinkFramerDeframer.MAX_PACKET_SIZE)[:DATA_FIELD_SIZE]
    packet = make_space_packet(0x102, DATA_FIELD_SIZE - 500)
    frames = [make_tm_frame(huge_start, 0, vc_count=0)]
    continuation_frames = SpaceDataLinkFramerDeframer.MAX_PACKET_SIZE // DATA_FIELD_SIZE
    for count in range(1, continuation_frames + 1):
        frames.append(
            make_tm_frame(bytes(DATA_FIELD_SIZE), SpaceDataLinkFramerDeframer.FHP_NO_PACKET_START, vc_count=count)
        )
    last = make_tm_frame(b"\xAA" * 500 + packet, 500, vc_count=(continuation_frames + 1) % 256)

    for frame in frames:
        assert framer_deframer.deframe(frame)[0] is None
    assert framer_deframer.pending == b""  # Discarded as oversize
    assert framer_deframer.deframe(last)[0] == packet


def test_deframe_idle_only_frame_discards_pending(framer_deframer):
    """An idle-only frame (FHP=0x7FE) emits nothing and invalidates pending continuation data."""
    span = make_space_packet(0x101, DATA_FIELD_SIZE + 500)
    idle = make_space_packet(0x7FF, DATA_FIELD_SIZE - 500)
    frame1 = make_tm_frame(span[:DATA_FIELD_SIZE], 0, vc_count=0)
    frame_idle = make_tm_frame(bytes(DATA_FIELD_SIZE), SpaceDataLinkFramerDeframer.FHP_IDLE_DATA_ONLY, vc_count=1)
    frame2 = make_tm_frame(span[DATA_FIELD_SIZE:] + idle, 500, vc_count=2)

    assert framer_deframer.deframe(frame1)[0] is None
    assert framer_deframer.deframe(frame_idle)[0] is None
    assert framer_deframer.pending == b""
    # The stale span tail is dropped, only the packet starting at the FHP is emitted
    assert framer_deframer.deframe(frame2)[0] == idle


def test_deframe_spanning_vc_count_wrap(framer_deframer):
    """A vc_count wrap from 255 to 0 is a valid sequence, not frame loss."""
    span = make_space_packet(0x101, DATA_FIELD_SIZE + 500)
    idle = make_space_packet(0x7FF, DATA_FIELD_SIZE - 500)
    frame1 = make_tm_frame(span[:DATA_FIELD_SIZE], 0, vc_count=255)
    frame2 = make_tm_frame(span[DATA_FIELD_SIZE:] + idle, 500, vc_count=0)

    assert framer_deframer.deframe(frame1)[0] is None
    assert framer_deframer.deframe(frame2)[0] == span + idle


def test_deframe_multiple_packets_in_frame(framer_deframer):
    """Several whole packets in one frame are all emitted."""
    packets = [make_space_packet(0x100 + i, 700) for i in range(3)]
    idle = make_space_packet(0x7FF, DATA_FIELD_SIZE - 3 * 700)
    frame = make_tm_frame(b"".join(packets) + idle, 0, vc_count=0)

    deframed, remaining, discarded = framer_deframer.deframe(frame)
    assert deframed == b"".join(packets) + idle
    assert remaining == b""
    assert discarded == b""


def test_deframe_fhp_inconsistent_with_pending(framer_deframer):
    """A FHP that does not complete the pending packet to a whole packet discards the pending data."""
    span = make_space_packet(0x101, DATA_FIELD_SIZE + 500)
    packet = make_space_packet(0x102, DATA_FIELD_SIZE - 400)
    frame1 = make_tm_frame(span[:DATA_FIELD_SIZE], 0, vc_count=0)
    # Pointer says 400 continuation bytes, but the pending packet needs 500
    frame2 = make_tm_frame(span[DATA_FIELD_SIZE : DATA_FIELD_SIZE + 400] + packet, 400, vc_count=1)

    assert framer_deframer.deframe(frame1)[0] is None
    assert framer_deframer.deframe(frame2)[0] == packet


def test_deframe_fhp_beyond_data_field():
    """A FHP pointing past the end of the data field discards the frame data and pending data."""
    frame_size = 1024
    field_size = frame_size - SpaceDataLinkFramerDeframer.TM_HEADER_SIZE - SpaceDataLinkFramerDeframer.TM_TRAILER_SIZE
    deframer = SpaceDataLinkFramerDeframer(scid=SCID_TEST_VALUE, vcid=VCID_TEST_VALUE, frame_size=frame_size)
    span = make_space_packet(0x101, field_size + 500)
    packet = make_space_packet(0x102, field_size)
    frame1 = make_tm_frame(span[:field_size], 0, vc_count=0, data_field_size=field_size)
    frame_bad = make_tm_frame(bytes(field_size), field_size, vc_count=1, data_field_size=field_size)
    frame3 = make_tm_frame(packet, 0, vc_count=2, data_field_size=field_size)

    assert deframer.deframe(frame1)[0] is None
    deframed, remaining, discarded = deframer.deframe(frame_bad)
    assert deframed is None
    assert remaining == b""
    assert deframer.pending == b""
    assert deframer.deframe(frame3)[0] == packet
