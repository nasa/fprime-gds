"""Tests of the chained CCSDS framing plugins over byte streams and TM frames

Reference digests were captured from the pre-splitter deframers fed the whole stream at once (raw-space-packet)
and frame by frame (space-packet-space-data-link); the chained plugins must reproduce them exactly.
"""
import logging

from fprime_gds.common.communication.ccsds.chain import (
    RawSpacePacketFramerDeframer,
    RawSpaceDataLinkFramerDeframer,
    SpacePacketSpaceDataLinkFramerDeframer,
)
from fprime_gds.common.communication.ccsds.space_data_link import SpaceDataLinkFramerDeframer
from fprime_gds.common.communication.ccsds.space_packet import SpacePacketFramerDeframer
from fprime_gds.common.communication.ccsds.space_packet_splitter import SpacePacketSplitterFramerDeframer
from fprime_gds.plugin.system import Plugins

import ccsds_streams

REFERENCE_STREAM_DIGEST = "c60de26d44a3c7d0b862a22228b71c67658286373eaef5358d5cc9bbf071d58d"
REFERENCE_STREAM_WARNINGS = 4
REFERENCE_TM_DIGEST = "97c48b536e941d206ae3206fd686b64f8b5368a41a70ef424cc1dfa00714233d"
REFERENCE_TM_WARNINGS = 7


def framing_plugins():
    """Framing plugin implementors by name"""
    return {plugin.get_name(): plugin.get_implementor() for plugin in Plugins.system().get_plugins("framing")}


def deframe_stream(deframer, chunks):
    """Feed chunks through deframe_all, aggregating unconsumed bytes as a stream consumer does"""
    packets = []
    pending = b""
    for piece in chunks:
        pending += piece
        new_packets, pending, _ = deframer.deframe_all(pending, no_copy=False)
        packets.extend(new_packets)
    return packets, pending


def test_plugin_chain_compositions():
    """Plugin names map to the expected chain compositions (framing order, innermost first)."""
    plugins = framing_plugins()
    assert plugins["raw-space-packet"] is RawSpacePacketFramerDeframer
    assert plugins["raw-space-data-link"] is RawSpaceDataLinkFramerDeframer
    assert plugins["space-packet-space-data-link"] is SpacePacketSpaceDataLinkFramerDeframer
    assert "space-packet-sdls-space-data-link" not in plugins
    assert "raw-sdls-cleartext" not in plugins
    assert RawSpacePacketFramerDeframer.get_composites() == [
        SpacePacketFramerDeframer,
        SpacePacketSplitterFramerDeframer,
    ]
    assert RawSpaceDataLinkFramerDeframer.get_composites() == [
        SpacePacketSplitterFramerDeframer,
        SpaceDataLinkFramerDeframer,
    ]
    assert SpacePacketSpaceDataLinkFramerDeframer.get_composites() == [
        SpacePacketFramerDeframer,
        SpacePacketSplitterFramerDeframer,
        SpaceDataLinkFramerDeframer,
    ]
    assert len(plugins) == len(set(plugins))


def test_raw_space_packet_whole_stream_matches_reference(caplog):
    """raw-space-packet over a whole stream yields the reference payload sequence and warnings."""
    packets, stream, _ = ccsds_streams.build_stream()
    deframer = framing_plugins()["raw-space-packet"]()
    with caplog.at_level(logging.WARNING, logger="framing"):
        deframed, remaining, discarded = deframer.deframe_all(stream, no_copy=False)
    assert deframed == ccsds_streams.expected_payloads(packets)
    assert ccsds_streams.digest(deframed) == REFERENCE_STREAM_DIGEST
    assert remaining == b""
    assert discarded == ccsds_streams.GARBAGE * 6
    assert len(caplog.records) == REFERENCE_STREAM_WARNINGS


def test_raw_space_packet_chunked_stream_matches_reference(caplog):
    """raw-space-packet over a chunked stream yields the same payloads as the whole stream, warnings included."""
    packets, _, chunks = ccsds_streams.build_stream()
    deframer = framing_plugins()["raw-space-packet"]()
    with caplog.at_level(logging.WARNING, logger="framing"):
        deframed, remaining = deframe_stream(deframer, chunks)
    assert deframed == ccsds_streams.expected_payloads(packets)
    assert ccsds_streams.digest(deframed) == REFERENCE_STREAM_DIGEST
    assert remaining == b""
    assert len(caplog.records) == REFERENCE_STREAM_WARNINGS


def test_space_packet_space_data_link_frames_match_reference(caplog):
    """space-packet-space-data-link over TM frames yields the reference per-frame payloads and warnings."""
    packets, frames = ccsds_streams.build_frames()
    deframer = framing_plugins()["space-packet-space-data-link"](
        scid=ccsds_streams.SCID, vcid=ccsds_streams.VCID, frame_size=ccsds_streams.FRAME_SIZE
    )
    per_frame = []
    deframed = []
    with caplog.at_level(logging.WARNING, logger="framing"):
        for frame in frames:
            frame_packets, remaining, discarded = deframer.deframe_all(frame, no_copy=False)
            assert remaining == b""
            assert discarded == b""
            per_frame.append(b"".join(frame_packets))
            deframed.extend(frame_packets)
    assert deframed == ccsds_streams.expected_payloads(packets)
    assert ccsds_streams.digest(per_frame) == REFERENCE_TM_DIGEST
    assert len(caplog.records) == REFERENCE_TM_WARNINGS


def test_raw_space_data_link_frames_yield_whole_packets():
    """raw-space-data-link over TM frames yields each whole non-idle Space Packet, header included."""
    packets, frames = ccsds_streams.build_frames()
    deframer = framing_plugins()["raw-space-data-link"](
        scid=ccsds_streams.SCID, vcid=ccsds_streams.VCID, frame_size=ccsds_streams.FRAME_SIZE
    )
    deframed = []
    for frame in frames:
        frame_packets, remaining, discarded = deframer.deframe_all(frame, no_copy=False)
        assert remaining == b""
        assert discarded == b""
        deframed.extend(frame_packets)
    assert deframed == [packet for apid, packet, _ in packets if apid != ccsds_streams.IDLE_APID]


def test_space_data_link_output_leaves_splitter_no_remainder():
    """The TM stage emits whole packets only, so the inner splitter never holds a remainder for the chain to drop."""
    _, frames = ccsds_streams.build_frames()
    space_data_link = SpaceDataLinkFramerDeframer(
        scid=ccsds_streams.SCID, vcid=ccsds_streams.VCID, frame_size=ccsds_streams.FRAME_SIZE
    )
    splitter = SpacePacketSplitterFramerDeframer()
    emitted = 0
    for frame in frames:
        for output in space_data_link.deframe_all(frame, no_copy=False)[0]:
            _, remaining, discarded = splitter.deframe_all(output, no_copy=False)
            assert remaining == b""
            assert discarded == b""
            emitted += 1
    assert emitted > 0
