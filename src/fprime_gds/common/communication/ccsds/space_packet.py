"""F Prime Framer/Deframer Implementation of the CCSDS Space Packet Protocol
"""

from __future__ import annotations

import struct
import copy

from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.plugin.definitions import gds_plugin_implementation, gds_plugin
from fprime_gds.common.utils.data_desc_type import DataDescType

from .apid import APID
import logging

LOGGER = logging.getLogger("framing")
LOGGER.setLevel(logging.DEBUG)

@gds_plugin(FramerDeframer)
class SpacePacketFramerDeframer(FramerDeframer):
    """ Concrete implementation of FramerDeframer supporting SpacePacket protocol

    This implementation is registered as a "framing" plugin to support encryption within the GDS layer.
    """
    SEQUENCE_COUNT_MAXIMUM = 16384 # 2^14
    HEADER_SIZE = 6
    IDLE_APID = 0x7FF # max 11 bit value per protocol specification

    def __init__(self):
        # self.sequence_number = 0
        # Map APID to sequence counts
        self.apid_to_sequence_count_map = dict()
        for key in DataDescType:
            self.apid_to_sequence_count_map[key.value] = 0

    def frame(self, data):
        """ Frame the supplied data in an encrypted frame

        Frame the data in an encrypted frame using the configured encryption algorithms.

        Args:
            data: data to frame
        Return:
            encrypted bytes
        """
        apid = APID.from_data(data)
        space_header = SpacePacketHeader(packet_type=PacketType.TC,
                                         apid=apid,
                                         seq_count=self.get_sequence_count(apid),
                                         data_len=len(data)) #TODO: strip off DDT fix w.r.t next line
        space_packet = SpacePacket(space_header, sec_header=None, user_data=data)
        return space_packet.pack()

    def deframe(self, data, no_copy=False):
        """ No op deframe step """
        discarded = b""
        if data is None:
            return None, None, discarded
        if not no_copy:
            data = copy.copy(data)
        deframed_packets = []
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
            # Discard Idle Packets
            if sp_header.apid == self.IDLE_APID:
                # LOGGER.debug(f"Discarding idle packet: {sp_header}")
                data = data[sp_header.packet_len:]
                continue
            # Check sequence count and warn if not expected value (don't drop the packet)
            if sp_header.seq_count != self.get_sequence_count(sp_header.apid):
                LOGGER.warning(f"APID {sp_header.apid} received sequence count: {sp_header.seq_count} (expected: {self.get_sequence_count(sp_header.apid)})")
                # Set the sequence count to the next expected value (consider missing packets have been lost)
                self.apid_to_sequence_count_map[sp_header.apid] = sp_header.seq_count + 1
            # If the pool is large enough to read the whole packet, then read it
            if len(data) >= sp_header.packet_len:
                deframed = struct.unpack_from(
                    # data_len is number of bytes minus 1 per SpacePacket spec
                    f">{sp_header.data_len + 1}s", data, self.HEADER_SIZE
                )[0]
                data = data[sp_header.packet_len:]
                LOGGER.debug(f"Deframed packet: {sp_header}")
                deframed_packets.append(deframed)
                continue
            else:
                LOGGER.debug(f"ERROR: Not enough data to read packet: {sp_header}")
                # If we don't have enough data, then break out of the loop
                continue
        return deframed_packets, data, discarded

    def get_sequence_count(self, apid: int):
        """ Get the sequence number and increment

        This function will return the current sequence number and then increment the sequence number for the next round.
        Should an APID not be registered already, it will be initialized to 0.

        Return:
            current sequence number
        """
        try:
            sequence = self.apid_to_sequence_count_map[apid]
        except KeyError:
            # If the APID is not in the map, initialize it to 0
            sequence = 0
            self.apid_to_sequence_count_map[apid] = 0
        self.apid_to_sequence_count_map[apid] = (sequence + 1) % self.SEQUENCE_COUNT_MAXIMUM
        return sequence

    @classmethod
    def get_name(cls):
        """ Name of this implementation provided to CLI """
        return "raw-space-packet"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register the MyPlugin plugin """
        return cls
