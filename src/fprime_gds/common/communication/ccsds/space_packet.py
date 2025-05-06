"""F Prime Framer/Deframer Implementation of the CCSDS Space Packet Protocol
"""

from __future__ import annotations

import struct
import copy

from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket

from fprime_gds.common.communication.framing import FramerDeframer, FpFramerDeframer
from fprime_gds.plugin.definitions import gds_plugin_implementation

from .apid import APID



class SpacePacketFramerDeframer(FramerDeframer):
    """ Concrete implementation of FramerDeframer supporting encryption

    This implementation is registered as a "framing" plugin to support encryption within the GDS layer.
    """
    SEQUENCE_NUMBER_MAXIMUM = 16384
    HEADER_SIZE = 6

    def __init__(self):
        self.sequence_number = 0

    def frame(self, data):
        """ Frame the supplied data in an encrypted frame

        Frame the data in an encrypted frame using the configured encryption algorithms.

        Args:
            data: data to frame
        Return:
            encrypted bytes
        """
        space_header = SpacePacketHeader(packet_type=PacketType.TC,
                                         apid=APID.from_data(data),
                                         seq_count=self.get_sequence_number(),
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
        # Continue until there is not enough data for the header, or until a packet is found (return)
        while len(data) >= SpacePacketFramerDeframer.HEADER_SIZE:
            # Read header information including start token and size and check if we have enough for the total size
            try: 
                sp_header = SpacePacketHeader.unpack(data)
            except ValueError:
                # If the header is invalid, rotate away a byte and keep processing
                discarded += data[0:1]
                data = data[1:]
                continue
            # If the header is valid, check if we have enough data for the whole packet
            # # If the pool is large enough to read the whole packet, then read it
            if len(data) >= sp_header.packet_len:
                deframed = struct.unpack_from(
                    # data_len is number of bytes minus 1 per SpacePacket spec
                    f">{sp_header.data_len + 1}s", data, SpacePacketFramerDeframer.HEADER_SIZE
                )[0]
                data = data[sp_header.packet_len:]
                # Return the deframed data
                print(f"SpacePacket deframed: {deframed.hex()}")
                return deframed, data, discarded
            # # Case of not enough data for a full packet, return hoping for more later
            # return None, data, discarded
        return None, data, discarded

    def get_sequence_number(self):
        """ Get the sequence number and increment

        This function will return the current sequence number and then increment the sequence number for the next round.

        Return:
            current sequence number
        """
        sequence = self.sequence_number
        self.sequence_number = (self.sequence_number + 1) % self.SEQUENCE_NUMBER_MAXIMUM
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
