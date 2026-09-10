"""F Prime Framer/Deframer Implementation of the CCSDS Space Data Link (TC/TM) Protocols"""

import sys
import struct
import copy

from fprime_gds.common.utils.config_manager import ConfigBadTypeException, ConfigManager
from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.plugin.definitions import gds_plugin_implementation

import crcmod


class SpaceDataLinkFramerDeframer(FramerDeframer):
    """CCSDS Framer/Deframer Implementation for the TC (uplink / framing) and TM (downlink / deframing)
    protocols. This FramerDeframer is used for framing TC data for uplink and deframing TM data for downlink.

    TM deframing expects the transfer frame data field to carry Space Packets (CCSDS 133.0-B): the First
    Header Pointer and the Space Packet length field are used to reassemble packets that span frames, so
    other data field contents are not supported.
    """

    # As per CCSDS standard
    SEQUENCE_NUMBER_MAXIMUM = 256
    TC_HEADER_SIZE = 5
    TM_HEADER_SIZE = 6
    TM_TRAILER_SIZE = 2
    TC_TRAILER_SIZE = 2
    VC_FRAME_COUNT_MAXIMUM = 256
    SPACE_PACKET_HEADER_SIZE = 6

    # First Header Pointer special values per CCSDS 132.0-B-3 4.1.2.7.6
    FHP_MASK = 0x7FF
    FHP_NO_PACKET_START = 0x7FF  # No packet starts in this frame (continuation data only)
    FHP_IDLE_DATA_ONLY = 0x7FE  # Frame contains only idle data

    # Maximum reassembled packet size: Space Packet header plus maximum length field value plus 1
    MAX_PACKET_SIZE = SPACE_PACKET_HEADER_SIZE + 65536

    # As per CCSDS standard, use CRC-16 CCITT config with init value
    # all 1s and final XOR value of 0x0000
    CCITT_CRC_FUNCTION = crcmod.mkCrcFun(
        0x11021,  # poly with implicit leading 1
        initCrc=0xFFFF,
        xorOut=0x0000,
        rev=False
    )


    # For backwards compatibility if not found in dictionary (loaded by ConfigManager)
    FALLBACK_SCID = 0x44
    FALLBACK_FRAME_SIZE = 1024

    def __init__(self, scid, vcid, frame_size):
        """Initialize with the given spacecraft id, virtual channel id, and frame size.
        If scid or frame_size are None, they will be pulled from ConfigManager constants
        if present, or use fallback values."""
        dict_scid = None
        dict_frame_size = None
        try:
            dict_scid = ConfigManager().get_constant("ComCfg.SpacecraftId")
        except ConfigBadTypeException:
            pass  # Config value not found, move on
        try:
            dict_frame_size = ConfigManager().get_constant("ComCfg.TmFrameFixedSize")
        except ConfigBadTypeException:
            pass  # Config value not found, move on
        if scid is not None and dict_scid is not None and scid != dict_scid:
            print(
                f"[WARNING] SCID value specified through CLI argument does not match value"
                f" loaded from the dictionary. CLI={scid}, Dictionary={dict_scid}",
                file=sys.stderr,
            )
        if frame_size is not None and dict_frame_size is not None and frame_size != dict_frame_size:
            print(
                f"[WARNING] TM frame size value specified through CLI argument does not match value"
                f" loaded from the dictionary. CLI={frame_size}, Dictionary={dict_frame_size}",
                file=sys.stderr,
            )
        self.sequence_number = 0
        # Continuation bytes of a packet spanning TM frames, awaiting completion
        self.pending = b""
        # Virtual channel frame count of the last valid frame, for loss detection
        self.last_vc_count = None
        self.vcid = vcid
        # Priority order: command line arg > dictionary value > fallback value
        self.scid = scid or dict_scid or self.FALLBACK_SCID
        self.frame_size = frame_size or dict_frame_size or self.FALLBACK_FRAME_SIZE

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
            ">H", SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(full_bytes_no_crc)
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
        """Deframe TM frames into complete Space Packets

        Validates each fixed-size TM frame (SCID/VCID, CRC) and passes its data field to `reassemble`, which
        buffers packets spanning frames using the First Header Pointer. Returns the complete Space Packets
        available after the frame (possibly several concatenated, or None when the frame holds only
        continuation, idle, or the start of a spanning packet), the unconsumed bytes, and any discarded
        bytes. Keeps `pending`/`last_vc_count` state across calls.
        """
        discarded = bytearray()
        if not no_copy:
            data = copy.copy(data)
        data = memoryview(data)
        # Continue until there is not enough data for the header, or until a packet is found (return)
        while len(data) >= self.frame_size:
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
            crc_offset = self.frame_size - self.TM_TRAILER_SIZE
            transmitted_crc = struct.unpack_from(">H", data, crc_offset)[0]
            if transmitted_crc == SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(data[:crc_offset]):
                # CRC is valid: extract the data field and reassemble packets spanning frames
                vc_count = data[3]
                first_header_pointer = struct.unpack_from(">H", data, 4)[0] & self.FHP_MASK
                field = bytes(data[self.TM_HEADER_SIZE : crc_offset])
                # Consume the fixed size frame
                data = data[self.frame_size :]
                deframed = self.reassemble(field, first_header_pointer, vc_count)
                if deframed:
                    return deframed, bytes(data), bytes(discarded)
                # Nothing complete to emit from this frame (continuation, idle, or partial packet start only)
                continue

            print(
                "[WARNING] Checksum validation failed.",
                file=sys.stderr,
            )
            # Bad checksum, rotate 1 and keep looking for non-garbage
            discarded += data[0:1]
            data = data[1:]
            continue
        return None, bytes(data), bytes(discarded)

    def reassemble(self, field, first_header_pointer, vc_count):
        """Reassemble Space Packets from a TM frame data field using the First Header Pointer

        Packets may span TM frames (CCSDS 132.0-B-3 4.1.2.7.6): continuation bytes are carried
        across frames and completed using the First Header Pointer of the following frame. On
        detected frame loss, pending continuation data is discarded and the First Header Pointer
        is used to resynchronize to the next packet header.

        Args:
            field: TM frame data field bytes
            first_header_pointer: First Header Pointer value from the frame Data Field Status
            vc_count: virtual channel frame count of this frame
        Return:
            bytes ready for Space Packet deframing (may be empty)
        """
        # Detect frame loss via virtual channel frame count discontinuity
        if self.last_vc_count is not None and vc_count != (self.last_vc_count + 1) % self.VC_FRAME_COUNT_MAXIMUM:
            if self.pending:
                print(
                    "[WARNING] TM frame loss detected. Discarding partial packet data.",
                    file=sys.stderr,
                )
                self.pending = b""
        self.last_vc_count = vc_count
        if first_header_pointer == self.FHP_IDLE_DATA_ONLY:
            # A packet cannot continue through an idle-only frame: any pending start is stale
            self.pending = b""
            return b""
        if first_header_pointer == self.FHP_NO_PACKET_START:
            # Continuation data only: the spanning packet continues through this entire frame
            if self.pending:
                self.pending += field
                if len(self.pending) > self.MAX_PACKET_SIZE:
                    print(
                        "[WARNING] Spanned packet exceeds maximum packet size. Discarding partial packet data.",
                        file=sys.stderr,
                    )
                    self.pending = b""
            return b""
        if first_header_pointer >= len(field):
            print(
                "[WARNING] First Header Pointer beyond TM frame data field. Discarding frame and partial packet data.",
                file=sys.stderr,
            )
            self.pending = b""
            return b""
        # Continuation bytes before the first header complete the pending spanned packet. With nothing
        # pending they belong to a packet whose start was never received (mid-stream attach, frame loss,
        # or discarded oversize packet) and are dropped.
        emitted = b""
        if self.pending:
            emitted = self.pending + field[:first_header_pointer]
            if self.split_complete_packets(emitted)[1]:
                print(
                    "[WARNING] First Header Pointer inconsistent with pending packet length. Discarding partial packet data.",
                    file=sys.stderr,
                )
                emitted = b""
        # Emit only whole packets; a packet starting in this frame may span into the next
        complete, self.pending = self.split_complete_packets(field[first_header_pointer:])
        return emitted + complete

    @classmethod
    def split_complete_packets(cls, data):
        """Split header-aligned Space Packet data into complete packets and a partial remainder"""
        offset = 0
        while len(data) - offset >= cls.SPACE_PACKET_HEADER_SIZE:
            # Space Packet length token is the number of payload bytes minus 1
            data_length = struct.unpack_from(">H", data, offset + 4)[0] + 1
            packet_length = cls.SPACE_PACKET_HEADER_SIZE + data_length
            if len(data) - offset < packet_length:
                break
            offset += packet_length
        return data[:offset], data[offset:]

    @classmethod
    def get_arguments(cls):
        """Arguments to request from the CLI"""
        return {
            ("--scid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Spacecraft ID (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
            ("--vcid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Virtual channel ID",
                "default": 1,
                "required": False,
            },
            ("--frame-size",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Fixed Size of TM Frames (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
        }

    @classmethod
    def check_arguments(cls, scid, vcid, frame_size):
        """Check arguments from the CLI

        Confirms that the input arguments are valid for this framer/deframer.

        Args:
            scid: spacecraft id
            vcid: virtual channel id
        """
        if scid is not None:
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

        if frame_size is not None and frame_size < 0:
            raise TypeError(f"TM Fixed Frame size {frame_size} is negative")

    @classmethod
    def get_name(cls):
        """Name of this implementation provided to CLI"""
        return "raw-space-data-link"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """Register the MyPlugin plugin"""
        return cls
