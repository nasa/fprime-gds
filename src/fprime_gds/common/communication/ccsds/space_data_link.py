"""F Prime Framer/Deframer Implementation of the CCSDS Space Data Link (TC/TM) Protocols"""
import sys
import struct
import copy

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.plugin.definitions import gds_plugin_implementation

import crc


class SpaceDataLinkFramerDeframer(FramerDeframer):
    """CCSDS Framer/Deframer Implementation for the TC (uplink / framing) and TM (downlink / deframing)
    protocols. This FramerDeframer is used for framing TC data for uplink and deframing TM data for downlink.
    """

    SEQUENCE_NUMBER_MAXIMUM = 256
    TC_HEADER_SIZE = 5
    TM_HEADER_SIZE = 6
    TM_FIXED_FRAME_SIZE = 1024
    TM_TRAILER_SIZE = 2
    TC_TRAILER_SIZE = 2

    # As per CCSDS standard, use CRC-16 CCITT config with init value
    # all 1s and final XOR value of 0x0000
    CRC_CCITT_CONFIG = crc.Configuration(
        width=16,
        polynomial=0x1021,
        init_value=0xFFFF,
        final_xor_value=0x0000,
    )
    CRC_CALCULATOR = crc.Calculator(CRC_CCITT_CONFIG)

    def __init__(self, scid, vcid):
        """ """
        self.scid = scid
        self.vcid = vcid
        self.sequence_number = 0

    def frame(self, data):
        """Frame the supplied data in a TC frame"""
        space_packet_bytes = data
        # CCSDS TC protocol defines the length token as number of bytes in full frame, minus 1
        # so we add to packet size the size of the header and trailer and subtract 1
        length = (
            len(space_packet_bytes) + self.TC_HEADER_SIZE + self.TC_TRAILER_SIZE - 1
        )
        assert length < (pow(2, 10) - 1), "Length too-large for CCSDS format"

        # CCSDS TC Header:
        #  2b -  00 - TF version number
        #  1b - 0/1 - 0 enable FARM checks, 1 bypass FARM
        #  1b - 0/1 - 0 = data (Type-D), 1 = control information (Type-C)
        #  2b -  00 - Reserved
        # 10b -  XX - Spacecraft id
        #  6b -  XX - Virtual Channel ID
        # 10b -  XX - Frame length
        #  8b -  XX - Frame sequence number

        # First 16 bits:
        header_val1_u16 = (
            (0 << 14) |  # TF version number (2 bits)
            (1 << 13) |  # Bypass FARM (1 bit)
            (0 << 12) |  # Type-D (1 bit)
            (0 << 10) |  # Reserved (2 bits)
            ((self.scid & 0x3FF))  # SCID (10 bits)
        )
        # Second 16 bits:
        header_val2_u16 = (
            ((self.vcid & 0x3F) << 10) |  # VCID (6 bits)
            (length & 0x3FF)              # Frame length (10 bits)
        )
        # 8 bit sequence number - always 0 in bypass FARM mode
        header_val3_u8 = 0
        header_bytes = struct.pack(">HHB", header_val1_u16, header_val2_u16, header_val3_u8)
        full_bytes_no_crc = header_bytes + space_packet_bytes
        assert (
            len(header_bytes) == self.TC_HEADER_SIZE
        ), "CCSDS primary header must be 5 octets long"
        assert len(full_bytes_no_crc) == self.TC_HEADER_SIZE + len(
            data
        ), "Malformed packet generated"

        full_bytes = full_bytes_no_crc + struct.pack(
            ">H", self.CRC_CALCULATOR.checksum(full_bytes_no_crc)
        )
        return full_bytes

    def get_sequence_number(self):
        """Get the sequence number and increment - used for TM deframing

        This function will return the current sequence number and then increment the sequence number for the next round.

        Return:
            current sequence number
        """
        sequence = self.sequence_number
        self.sequence_number = (self.sequence_number + 1) % self.SEQUENCE_NUMBER_MAXIMUM
        return sequence

    def deframe(self, data, no_copy=False):
        """Deframe TM frames"""
        discarded = b""
        if not no_copy:
            data = copy.copy(data)
        # Continue until there is not enough data for the header, or until a packet is found (return)
        while len(data) >= self.TM_FIXED_FRAME_SIZE:
            # Read header information
            sc_and_channel_ids = struct.unpack_from(">H", data)
            spacecraft_id = (sc_and_channel_ids[0] & 0x3FF0) >> 4
            virtual_channel_id = (sc_and_channel_ids[0] & 0x000E) >> 1
            # Check if the header is correct with regards to expected spacecraft and VC IDs
            if spacecraft_id != self.scid or virtual_channel_id != self.vcid:
                # If the header is invalid, rotate away a Byte and keep processing
                discarded += data[0:1]
                data = data[1:]
                continue
            # Spacecraft ID and Virtual Channel ID match, so we look at end of frame for CRC
            crc_offset = self.TM_FIXED_FRAME_SIZE - self.TM_TRAILER_SIZE
            transmitted_crc = struct.unpack_from(">H", data, crc_offset)[0]
            if transmitted_crc == self.CRC_CALCULATOR.checksum(data[:crc_offset]):
                # CRC is valid, so we return the deframed data
                deframed_data_len = (
                    self.TM_FIXED_FRAME_SIZE
                    - self.TM_TRAILER_SIZE
                    - self.TM_HEADER_SIZE
                )
                deframed = struct.unpack_from(
                    f">{deframed_data_len}s", data, self.TM_HEADER_SIZE
                )[0]
                # Consume the fixed size frame
                data = data[self.TM_FIXED_FRAME_SIZE :]
                return deframed, data, discarded

            print(
                "[WARNING] Checksum validation failed.",
                file=sys.stderr,
            )
            # Bad checksum, rotate 1 and keep looking for non-garbage
            discarded += data[0:1]
            data = data[1:]
            continue
        return None, data, discarded

    @classmethod
    def get_arguments(cls):
        """Arguments to request from the CLI"""
        return {
            ("--scid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Spacecraft ID",
                "default": 0x44,
                "required": False,
            },
            ("--vcid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Virtual channel ID",
                "default": 1,
                "required": False,
            },
        }

    @classmethod
    def check_arguments(cls, scid, vcid):
        """Check arguments from the CLI

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
        """Name of this implementation provided to CLI"""
        return "raw-space-data-link"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """Register the MyPlugin plugin"""
        return cls
