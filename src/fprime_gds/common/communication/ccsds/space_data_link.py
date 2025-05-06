import sys
import struct
import copy

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.plugin.definitions import gds_plugin_implementation

from crcmod.predefined import PredefinedCrc


class SpaceDataLinkFramerDeframer(FramerDeframer):
    """ CCSDS Framer/Deframer Implementation for the TC (uplink / framing) and TM (downlink / deframing) 
    protocols. This FramerDeframer is used for framing TC data for uplink and deframing TM data for downlink."""
    SEQUENCE_NUMBER_MAXIMUM = 256
    TC_HEADER_SIZE = 5
    TM_HEADER_SIZE = 6
    TM_FIXED_FRAME_SIZE = 1024


    def __init__(self, scid, vcid):
        """ """
        self.scid = scid
        self.vcid = vcid
        self.sequence_number = 0


    def frame(self, data):
        """ Frame the supplied data in a TC frame
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
        assert len(header_bytes) == self.TC_HEADER_SIZE, "CCSDS primary header must be 5 octets long"
        full_bytes_no_crc = header_bytes + space_packet_bytes
        assert len(full_bytes_no_crc) == self.TC_HEADER_SIZE + length, "Malformed packet generated"

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
        """Deframe TM frames"""
        discarded = b""
        if not no_copy:
            data = copy.copy(data)
        # Continue until there is not enough data for the header, or until a packet is found (return)
        while len(data) >= self.TM_FIXED_FRAME_SIZE:
            # Read header information including start token and size and check if we have enough for the total size
            sc_and_channel_ids = struct.unpack_from(">H", data)
            spacecraft_id = (sc_and_channel_ids[0] & 0x3FF0) >> 4
            virtual_channel_id = (sc_and_channel_ids[0] & 0x000E) >> 1
            if spacecraft_id != self.scid: # or virtual_channel_id != self.vcid:
                # If the header is invalid, rotate away a Byte and keep processing
                discarded += data[0:1]
                data = data[1:]
                continue
            # Spacecraft ID and Virtual Channel ID match, so we look at end of frame for CRC
            crc_offset = self.TM_FIXED_FRAME_SIZE - 2
            transmitted_crc = struct.unpack_from(">H", data, crc_offset)[0]

            # Use CRC-16 (CCITT) with no final XOR (XOR of 0x0000)
            crc_calculator = PredefinedCrc(crc_name="crc-ccitt-false")
            crc_calculator.update(data[:crc_offset])

            if transmitted_crc == crc_calculator.crcValue:
                # CRC is valid, so we return the deframed data
                deframed_data_len = self.TM_FIXED_FRAME_SIZE - 2 - self.TM_HEADER_SIZE
                deframed = struct.unpack_from(
                    f">{deframed_data_len}s", data, self.TM_HEADER_SIZE
                )[0]
                # Discard the fixed size frame
                data = data[self.TM_FIXED_FRAME_SIZE:]
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

