"""F Prime Framer/Deframer Implementation of the CCSDS Space Packet Protocol

Splitting of byte streams into whole Space Packets and idle packet removal are handled by
`fprime_gds.common.communication.ccsds.space_packet_splitter`; this module frames uplink data and strips
the primary header (with sequence count checking) from one complete downlink Space Packet at a time.
"""

from __future__ import annotations

import struct
import copy

from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.utils.config_manager import ConfigManager

import logging

LOGGER = logging.getLogger("framing")


class SpacePacketFramerDeframer(FramerDeframer):
    """Concrete implementation of FramerDeframer supporting SpacePacket protocol

    Frames uplink data into a Space Packet and deframes exactly one whole Space Packet into its payload. It is
    a stage of the chained "framing" plugins in `fprime_gds.common.communication.ccsds.chain`, which precede it
    with `SpacePacketSplitterFramerDeframer` to split byte streams into whole packets.
    """

    SEQUENCE_COUNT_MAXIMUM = 16384  # 2^14
    HEADER_SIZE = 6
    IDLE_APID = 0x7FF  # max 11 bit value per protocol specification

    def __init__(self):
        # Internal APID object for deserialization
        self.apid_obj: EnumType = ConfigManager().get_type("ComCfg.Apid")()  # type: ignore
        # Map APID to sequence counts
        self.apid_to_sequence_count_map = dict()
        for key in self.apid_obj.keys():
            self.apid_to_sequence_count_map[key] = 0

    def frame(self, data):
        """Frame the supplied data in Space Packet"""
        # The protocol defines length token to be number of bytes minus 1
        data_length_token = len(data) - 1
        # Extract the APID from the data
        self.apid_obj.deserialize(data, offset=0)
        space_header = SpacePacketHeader(
            packet_type=PacketType.TC,
            apid=self.apid_obj.numeric_value,
            seq_count=self.get_sequence_count(self.apid_obj.numeric_value),
            data_len=data_length_token,
        )
        space_packet = SpacePacket(space_header, sec_header=None, user_data=data)
        return space_packet.pack()

    def deframe(self, data, no_copy=False):
        """Deframe exactly one complete Space Packet, stripping the primary header and checking sequence count

        Input that is not a single whole Space Packet (short, invalid header, or length mismatch) is discarded.
        """
        discarded = b""
        if data is None:
            return None, None, discarded
        if not no_copy:
            data = copy.copy(data)
        if len(data) < self.HEADER_SIZE:
            return None, b"", bytes(data)
        try:
            sp_header = SpacePacketHeader.unpack(data)
        except ValueError:
            return None, b"", bytes(data)
        # Space Packet version is specified as 0 per protocol
        if sp_header.ccsds_version != 0 or sp_header.packet_type != PacketType.TM:
            return None, b"", bytes(data)
        if len(data) != sp_header.packet_len:
            return None, b"", bytes(data)
        # Check sequence count and warn if not expected value (don't drop the packet)
        expected_sequence_count = self.get_sequence_count(sp_header.apid)
        if sp_header.seq_count != expected_sequence_count:
            LOGGER.warning(
                f"APID {sp_header.apid} received sequence count: {sp_header.seq_count}"
                f" (expected: {expected_sequence_count})"
            )
            # Set the sequence count to the next expected value (consider missing packets have been lost)
            self.apid_to_sequence_count_map[sp_header.apid] = (
                sp_header.seq_count + 1
            )
        deframed = struct.unpack_from(
            # data_len is number of bytes minus 1 per SpacePacket spec
            f">{sp_header.data_len + 1}s",
            data,
            self.HEADER_SIZE,
        )[0]
        LOGGER.debug(f"Deframed packet: {sp_header}")
        return deframed, b"", discarded

    def get_sequence_count(self, apid: int):
        """Get the sequence number and increment

        This function will return the current sequence number and then increment the sequence number for the next round.
        Should an APID not be registered already, it will be initialized to 0.

        Return:
            current sequence number
        """
        # If APID is not registered, initialize it to 0
        sequence = self.apid_to_sequence_count_map.get(apid, 0)
        self.apid_to_sequence_count_map[apid] = (
            sequence + 1
        ) % self.SEQUENCE_COUNT_MAXIMUM
        return sequence
