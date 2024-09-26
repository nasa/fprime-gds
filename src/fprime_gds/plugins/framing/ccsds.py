""" fprime_gds.plugins.framing.ccsds: implementation of framing plugin to support CCSDS

This file registers a CCSDS plugin and a space-packet plugin used to frame data for use transmitting F´ data within a
CCSDS frame.
"""
import struct
from typing import List, Type

from spacepackets.ccsds.spacepacket import SpacePacketHeader, PacketType, SpacePacket

from fprime.common.models.serialize.numerical_types import U32Type
from fprime_gds.common.communication.framing import FramerDeframer, FpFramerDeframer
from fprime_gds.plugin.definitions import gds_plugin_implementation

from fprime_gds.plugins.framing.chain import ChainedFramerDeframer

from fprime_gds.plugins.framing.apid import APID

from crcmod.predefined import PredefinedCrc


class SpacePacketFramerDeframer(FramerDeframer):
    """ Concrete implementation of FramerDeframer supporting CCSDS space packets

    This implementation is registered as a "framing" plugin to support CCSDS space packets within the GDS layer.
    """
    SEQUENCE_NUMBER_MAXIMUM = 16384

    def __init__(self):
        self.sequence_number = 0

    def frame(self, data):
        """ Frame the supplied data in a SpacePacket frame

        Args:
            data: data to frame
        Return:
            space packet bytes
        """
        space_header = SpacePacketHeader(packet_type=PacketType.TC,
                                         apid=APID.from_data(data),
                                         seq_count=self.get_sequence_number(),
                                         data_len=len(data))
        space_packet = SpacePacket(space_header, sec_header=None, user_data=data)
        return space_packet.pack()

    def deframe(self, data, no_copy=False):
        """ No op deframe step """
        return data, b"", b""

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


class SpaceDataLinkFramerDeframer(SpacePacketFramerDeframer):
    """ CCSDS space data link Framer/Deframer Implementation """
    SEQUENCE_NUMBER_MAXIMUM = 256
    HEADER_SIZE = 5

    def __init__(self, scid, vcid):
        """ """
        self.scid = scid
        self.vcid = vcid
        self.sequence_number = 0
        # Note, fprime is used for downlink at this time
        self.fprime_framer_deframer = FpFramerDeframer("crc32")

    def frame(self, data):
        """ Frame the supplied data in an CCSDS space data link packet frame

        Args:
            data: data to frame
        Return:
            space data link packet bytes
        """
        space_packet_bytes = data
        length = len(space_packet_bytes)
        assert length < (pow(2, 10) - 1), "Length too-large for CCSDS format"

        # CCSDS TC Header:
        #  2b -  00 - TF version number
        #  1b - 0/1 - 0 enable FARM checks, 1 bypass FARM
        #  1b - 0/1 - 0 Type-D data, 1 Type-C data
        #  2b -  00 - Reserved
        # 10b -  XX - Spacecraft id
        #  6b -  XX - Virtual Channel ID
        # 10b -  XX - Frame length

        #  8b -  XX - Frame sequence number

        header = (0 << 30) | \
                 (0 << 29) | \
                 (0 << 28) | \
                 ((self.scid & 0x3FF) << 16) | \
                 ((self.vcid & 0x3F) << 10) | \
                 (length & 0x3FF)

        header_bytes = struct.pack(">IB", header, self.sequence_number)
        assert len(header_bytes) == self.HEADER_SIZE, "CCSDS primary header must be 5 octets long"
        full_bytes_no_crc = header_bytes + space_packet_bytes
        assert len(full_bytes_no_crc) == self.HEADER_SIZE + length, "Malformed packet generated"

        # Use CRC-16 (CCITT) with no final XOR (XOR of 0x0000)
        crc_calculator = PredefinedCrc(crc_name="crc-ccitt-false")
        crc_calculator.update(full_bytes_no_crc)

        full_bytes = full_bytes_no_crc + struct.pack(">H", crc_calculator.crcValue)
        return full_bytes

    def get_sequence_number(self):
        """ Get the sequence number and increment

        This function will return the current sequence number and then increment the sequence number for the next round.

        Return:
            current sequence number
        """
        sequence = self.sequence_number
        self.sequence_number = (self.sequence_number + 1) % self.SEQUENCE_NUMBER_MAXIMUM
        return sequence

    def deframe(self, data, no_copy=False):
        """ Deframe using fprime for now """
        return self.fprime_framer_deframer.deframe(data, no_copy)

    @classmethod
    def get_arguments(cls):
        """ Arguments to request from the CLI """
        return {
            ("--scid", ): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Spacecraft ID"
            },
            ("--vcid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Virtual channel ID"
            }
        }

    @classmethod
    def check_arguments(cls, scid, vcid):
        """ Check arguments from the CLI

        Confirms that the input arguments are valid for this framer/deframer.

        Args:
            scid: spacecraft id
            vcid: virtual channel id
        """
        if scid is None:
            raise TypeError(f"Spacecraft ID not specified")
        if scid < 0:
            raise TypeError(f"Spacecraft ID {scid} is negative")
        if scid > 0x3FF:
            raise TypeError(f"Spacecraft ID {scid} is larger than {0x3FF}")

        if vcid is None:
            raise TypeError(f"Virtual Channel ID not specified")
        if vcid < 0:
            raise TypeError(f"Virtual Channel ID {vcid} is negative")
        if vcid > 0x3F:
            raise TypeError(f"Virtual Channel ID {vcid} is larger than {0x3FF}")

    @classmethod
    def get_name(cls):
        """ Name of this implementation provided to CLI """
        return "unspecified-space-data-link"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register the MyPlugin plugin """
        return cls


class SpacePacketSpaceDataLinkFramerDeframer(ChainedFramerDeframer):
    """ Space Data Link Protocol framing and deframing that has a data unit of Space Packets """

    @classmethod
    def get_composites(cls) -> List[Type[FramerDeframer]]:
        """ Return the composite list of this """
        return [
            SpacePacketFramerDeframer,
            SpaceDataLinkFramerDeframer
        ]

    @classmethod
    def get_name(cls):
        """ Name of this implementation provided to CLI """
        return "space-packet-space-data-link"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register the MyPlugin plugin """
        return cls
