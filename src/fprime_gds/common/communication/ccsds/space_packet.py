"""F Prime Framer/Deframer Implementation of the CCSDS Space Packet Protocol"""

from __future__ import annotations

import struct
import copy

from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.plugin.definitions import gds_plugin_implementation, gds_plugin

import logging

LOGGER = logging.getLogger("framing")


@gds_plugin(FramerDeframer)
class SpacePacketFramerDeframer(FramerDeframer):
    """Concrete implementation of FramerDeframer supporting SpacePacket protocol

    This implementation is registered as a "framing" plugin to support encryption within the GDS layer.
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
        """Deframe the supplied data according to Space Packet protocol"""
        discarded = b""
        if data is None:
            return None, None, discarded
        if not no_copy:
            data = copy.copy(data)
        # Deframe all packets until there is not enough data for a header
        while len(data) >= self.HEADER_SIZE:
            # Read header information including start token and size and check if we have enough for the total size
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
            # Skip Idle Packets as they are not meaningful
            if sp_header.apid == self.IDLE_APID:
                data = data[sp_header.packet_len :]
                continue
            # Check sequence count and warn if not expected value (don't drop the packet)
            if sp_header.seq_count != self.get_sequence_count(sp_header.apid):
                LOGGER.warning(
                    f"APID {sp_header.apid} received sequence count: {sp_header.seq_count}"
                    f" (expected: {self.get_sequence_count(sp_header.apid)})"
                )
                # Set the sequence count to the next expected value (consider missing packets have been lost)
                self.apid_to_sequence_count_map[sp_header.apid] = (
                    sp_header.seq_count + 1
                )
            # If the pool is large enough to read the whole packet, then read it
            if len(data) >= sp_header.packet_len:
                deframed = struct.unpack_from(
                    # data_len is number of bytes minus 1 per SpacePacket spec
                    f">{sp_header.data_len + 1}s",
                    data,
                    self.HEADER_SIZE,
                )[0]
                data = data[sp_header.packet_len :]
                LOGGER.debug(f"Deframed packet: {sp_header}")
                return deframed, data, discarded
            else:
                # If we don't have enough data, then break out of the loop
                break
        return None, data, discarded

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

    @classmethod
    def get_name(cls):
        """Name of this implementation provided to CLI"""
        return "raw-space-packet"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """Register the MyPlugin plugin"""
        return cls
