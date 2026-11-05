import pytest

from fprime_gds.common.communication.ccsds.space_packet_splitter import SpacePacketSplitterFramerDeframer
from fprime_gds.plugin.system import Plugins

from ccsds_streams import IDLE_APID, make_space_packet


@pytest.fixture
def splitter():
    return SpacePacketSplitterFramerDeframer()


def test_frame_pass_through(splitter):
    """Framing returns the data unchanged."""
    data = b"uplink_bytes"
    assert splitter.frame(data) == data


def test_deframe_one_packet_per_call(splitter):
    """Each deframe call yields exactly one whole packet, header included, with the rest remaining."""
    first = make_space_packet(0x100, 0, b"first")
    second = make_space_packet(0x101, 0, b"second")
    deframed, remaining, discarded = splitter.deframe(first + second)
    assert deframed == first
    assert remaining == second
    assert discarded == b""
    deframed, remaining, discarded = splitter.deframe(remaining)
    assert deframed == second
    assert remaining == b""
    assert discarded == b""


def test_deframe_drops_idle(splitter):
    """Idle packets are consumed silently: neither emitted nor discarded."""
    idle = make_space_packet(IDLE_APID, 0, bytes(10))
    packet = make_space_packet(0x100, 0, b"payload")
    packets, remaining, discarded = splitter.deframe_all(idle + packet + idle, no_copy=False)
    assert packets == [packet]
    assert remaining == b""
    assert discarded == b""


def test_deframe_partial_packet_held_across_chunks(splitter):
    """A partial packet (including a partial idle packet) is returned as remaining until completed."""
    idle = make_space_packet(IDLE_APID, 0, bytes(20))
    packet = make_space_packet(0x100, 0, b"0123456789")
    stream = idle + packet
    split = len(idle) - 4  # Cut inside the idle packet
    packets, remaining, discarded = splitter.deframe_all(stream[:split], no_copy=False)
    assert packets == []
    assert remaining == stream[:split]
    assert discarded == b""
    packets, remaining, discarded = splitter.deframe_all(remaining + stream[split:], no_copy=False)
    assert packets == [packet]
    assert remaining == b""
    assert discarded == b""


def test_deframe_header_only_held(splitter):
    """Fewer bytes than a header are held, not discarded."""
    packet = make_space_packet(0x100, 0, b"abc")
    deframed, remaining, discarded = splitter.deframe(packet[:4])
    assert deframed is None
    assert remaining == packet[:4]
    assert discarded == b""


def test_deframe_resync_on_garbage(splitter):
    """Bytes that cannot start a valid header are discarded one at a time until a packet is found."""
    packet = make_space_packet(0x100, 0, b"payload")
    garbage = b"\xFF" * 8
    deframed, remaining, discarded = splitter.deframe(garbage + packet + garbage)
    assert deframed == packet
    assert remaining == garbage
    assert discarded == garbage
    # Trailing garbage is discarded down to fewer bytes than a header, which are held as a possible packet start
    deframed, remaining, discarded = splitter.deframe(remaining)
    assert deframed is None
    assert remaining == b"\xFF" * 5
    assert discarded == b"\xFF" * 3


def test_deframe_none(splitter):
    """None input yields no packet."""
    assert splitter.deframe(None) == (None, None, b"")


def test_plugin_registered_with_unique_name():
    """The splitter is a built-in framing plugin and no two framing plugins share a name."""
    plugins = Plugins.system().get_plugins("framing")
    names = [plugin.get_name() for plugin in plugins]
    assert "space-packet-splitter" in names
    assert len(names) == len(set(names))
    implementors = {plugin.get_name(): plugin.get_implementor() for plugin in plugins}
    assert implementors["space-packet-splitter"] is SpacePacketSplitterFramerDeframer
