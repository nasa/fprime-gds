import pytest

from fprime_gds.common.communication.ccsds.asm import AsmFramerDeframer

FRAME_SIZE_TEST_VALUE = 16
ASM = bytes.fromhex(AsmFramerDeframer.DEFAULT_ASM)


@pytest.fixture
def framer_deframer():
    return AsmFramerDeframer(frame_size=FRAME_SIZE_TEST_VALUE)


def make_frame(fill):
    return bytes([fill % 256 for _ in range(FRAME_SIZE_TEST_VALUE)])


def test_frame_is_identity(framer_deframer):
    """Uplink framing carries no ASM and must be pass-through"""
    data = b"tc_frame_bytes"
    assert framer_deframer.frame(data) == data


def test_deframe_valid_smtf(framer_deframer):
    """Deframe a single Sync-Marked Transfer Frame"""
    frame = make_frame(0xAB)
    deframed, remaining, discarded = framer_deframer.deframe(ASM + frame)
    assert deframed == frame
    assert remaining == b""
    assert discarded == b""


def test_deframe_discards_leading_garbage(framer_deframer):
    """Bytes preceding the ASM are discarded"""
    garbage = b"\x00\x01\x02noise"
    frame = make_frame(0x42)
    deframed, remaining, discarded = framer_deframer.deframe(garbage + ASM + frame)
    assert deframed == frame
    assert discarded == garbage
    assert remaining == b""


def test_deframe_multiple_frames(framer_deframer):
    """deframe_all extracts every SMTF in the stream"""
    frames = [make_frame(i) for i in range(3)]
    stream = b"".join(ASM + frame for frame in frames)
    packets, remaining, discarded = framer_deframer.deframe_all(stream, no_copy=False)
    assert packets == frames
    assert remaining == b""
    assert discarded == b""


def test_deframe_partial_frame_waits(framer_deframer):
    """An incomplete frame after the ASM is left as remaining data"""
    frame = make_frame(0x77)
    partial = ASM + frame[:-4]
    deframed, remaining, discarded = framer_deframer.deframe(partial)
    assert deframed is None
    assert remaining == partial
    assert discarded == b""
    # Frame completes once the rest of the data arrives
    deframed, remaining, discarded = framer_deframer.deframe(remaining + frame[-4:])
    assert deframed == frame


def test_deframe_partial_asm_at_boundary(framer_deframer):
    """A marker straddling the read boundary is not discarded"""
    frame = make_frame(0x11)
    first, second = ASM[:2], ASM[2:]
    deframed, remaining, discarded = framer_deframer.deframe(b"junk" + first)
    assert deframed is None
    assert remaining == first  # partial ASM retained
    assert discarded == b"junk"
    deframed, remaining, discarded = framer_deframer.deframe(remaining + second + frame)
    assert deframed == frame


def test_deframe_no_asm_discards(framer_deframer):
    """Data with no ASM is discarded except for a potential partial marker tail"""
    data = b"\x55" * 40
    deframed, remaining, discarded = framer_deframer.deframe(data)
    assert deframed is None
    assert remaining == b""  # no suffix of the data is a prefix of the ASM
    assert discarded == data


def test_configured_asm():
    """A non-default ASM pattern (64-bit Turbo/LDPC, Blue Book 9.3) is honored"""
    turbo_asm = "034776C7272895B0"
    framer_deframer = AsmFramerDeframer(asm=turbo_asm, frame_size=FRAME_SIZE_TEST_VALUE)
    frame = make_frame(0x99)
    deframed, remaining, discarded = framer_deframer.deframe(bytes.fromhex(turbo_asm) + frame)
    assert deframed == frame
    # The default ASM must not match
    deframed, _, _ = framer_deframer.deframe(ASM + frame)
    assert deframed is None


def test_check_arguments():
    """Argument validation errors"""
    with pytest.raises(TypeError):
        AsmFramerDeframer.check_arguments(asm="not-hex", frame_size=None)
    with pytest.raises(TypeError):
        AsmFramerDeframer.check_arguments(asm="", frame_size=None)
    with pytest.raises(TypeError):
        AsmFramerDeframer.check_arguments(asm="00" * 17, frame_size=None)
    with pytest.raises(TypeError):
        AsmFramerDeframer.check_arguments(asm="1ACFFC1D", frame_size=0)
    AsmFramerDeframer.check_arguments(asm="1ACFFC1D", frame_size=1024)
