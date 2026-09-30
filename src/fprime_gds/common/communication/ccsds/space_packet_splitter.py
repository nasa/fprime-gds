"""F Prime Framer/Deframer splitting header-aligned bytes into whole CCSDS Space Packets

Deframing yields exactly one complete, non-idle Space Packet (primary header included) per call,
discarding bytes that do not start a valid version-0 telemetry header and silently consuming idle
packets (APID 0x7FF). Bytes that do not yet hold a whole packet are returned as the remainder so
a byte stream may be aggregated across calls. Framing passes data through unchanged.

Select with ``--framing-selection space-packet-splitter`` to receive whole Space Packets, or use
it as a stage of a chained framer/deframer (see ``fprime_gds.common.communication.ccsds.chain``).
"""

import copy

from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.common.communication.ccsds.space_packet import SpacePacketFramerDeframer
from fprime_gds.plugin.definitions import gds_plugin


@gds_plugin(FramerDeframer)
class SpacePacketSplitterFramerDeframer(FramerDeframer):
    """Splits header-aligned Space Packet bytes into whole non-idle Space Packets; framing is pass-through"""

    def frame(self, data):
        """Pass the supplied data through unchanged"""
        return data

    def deframe(self, data, no_copy=False):
        """Deframe one whole non-idle Space Packet, or None when a whole packet is not yet available"""
        discarded = b""
        if data is None:
            return None, None, discarded
        if not no_copy:
            data = copy.copy(data)
        # Walk packets until one is found to return or there is not enough data for a whole packet
        while len(data) >= SpacePacketFramerDeframer.HEADER_SIZE:
            try:
                sp_header = SpacePacketHeader.unpack(data)
            except ValueError:
                # If the header is invalid, rotate away a byte and keep processing
                discarded += data[0:1]
                data = data[1:]
                continue
            if sp_header.ccsds_version != 0 or sp_header.packet_type != PacketType.TM:
                # Space Packet version is specified as 0 per protocol
                discarded += data[0:1]
                data = data[1:]
                continue
            # Not enough data for the whole packet: hold it for aggregation with subsequent data
            if len(data) < sp_header.packet_len:
                break
            packet = data[: sp_header.packet_len]
            data = data[sp_header.packet_len :]
            # Skip Idle Packets as they are not meaningful
            if sp_header.apid == SpacePacketFramerDeframer.IDLE_APID:
                continue
            return packet, data, discarded
        return None, data, discarded

    @classmethod
    def get_name(cls):
        """Name of this implementation provided to CLI"""
        return "space-packet-splitter"
