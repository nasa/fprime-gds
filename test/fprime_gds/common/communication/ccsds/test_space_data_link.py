import pytest
import struct

from fprime_gds.common.communication.ccsds.space_data_link import (
    SpaceDataLinkFramerDeframer,
)

SCID_TEST_VALUE = 0x77
VCID_TEST_VALUE = 5
FRAME_SIZE_TEST_VALUE = 2222

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
    crc = framer_deframer.CRC_CALCULATOR.checksum(input_data_no_crc)
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
    crc = framer_deframer.CRC_CALCULATOR.checksum(input_data_no_crc) + 1  # Intentionally incorrect CRC
    input_data = input_data_no_crc + struct.pack(">H", crc)
    deframed_data, remaining_data, discarded = framer_deframer.deframe(input_data)
    assert deframed_data is None
    assert remaining_data == input_data[1:]
    assert discarded[0] == input_data[0]
