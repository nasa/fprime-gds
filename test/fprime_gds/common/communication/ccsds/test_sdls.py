import pytest
from fprime_gds.common.communication.ccsds.sdls import SdlsCleartextFramerDeframer


@pytest.fixture
def framer_deframer():
    return SdlsCleartextFramerDeframer(sa_index=0x1234)


def test_frame_prepends_sa_index(framer_deframer):
    """Test framing prepends the 16-bit security association index."""
    data = b"test_payload"
    framed_data = framer_deframer.frame(data)
    assert framed_data == b"\x12\x34" + data


def test_frame_empty_data(framer_deframer):
    """Test framing empty data yields only the security association index."""
    assert framer_deframer.frame(b"") == b"\x12\x34"


def test_deframe_strips_sa_index(framer_deframer):
    """Test deframing strips the security association index."""
    payload = b"cleartext_payload"
    deframed, remaining, discarded = framer_deframer.deframe(b"\x00\x01" + payload)
    assert deframed == payload
    assert remaining == b""
    assert discarded == b""


def test_deframe_insufficient_data(framer_deframer):
    """Test deframing data shorter than the security association index."""
    deframed, remaining, discarded = framer_deframer.deframe(b"\x00")
    assert deframed is None
    assert remaining == b"\x00"
    assert discarded == b""


def test_frame_deframe_round_trip(framer_deframer):
    """Test that deframing a framed payload returns the original payload."""
    payload = b"round_trip_payload"
    deframed, remaining, discarded = framer_deframer.deframe(
        framer_deframer.frame(payload)
    )
    assert deframed == payload
    assert remaining == b""
    assert discarded == b""


def test_check_arguments_rejects_out_of_range():
    """Test argument validation of the security association index."""
    SdlsCleartextFramerDeframer.check_arguments(sa_index=0)
    SdlsCleartextFramerDeframer.check_arguments(sa_index=0xFFFF)
    with pytest.raises(TypeError):
        SdlsCleartextFramerDeframer.check_arguments(sa_index=-1)
    with pytest.raises(TypeError):
        SdlsCleartextFramerDeframer.check_arguments(sa_index=0x10000)
    with pytest.raises(TypeError):
        SdlsCleartextFramerDeframer.check_arguments(sa_index=None)
