"""F Prime Framer/Deframer aggregating a byte stream into whole CCSDS TM transfer frames

Stream-oriented links (TCP, UART) deliver bytes in arbitrary chunks. This deframer
re-establishes the fixed-size TM transfer frame boundaries and hands each frame on intact
(header, data field, and trailer) for downstream consumers that decode TM frames themselves.
Uplink data is passed through unchanged.
"""

import copy
import struct
import sys

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.common.utils.config_manager import ConfigBadTypeException, ConfigManager
from fprime_gds.plugin.definitions import gds_plugin_implementation


class TmFrameAggregatorFramerDeframer(FramerDeframer):
    """Aggregates downlink bytes into intact fixed-size TM frames; uplink is pass-through

    Frame starts are located by the TM primary header: the transfer frame version number must be
    zero and, when known, the spacecraft ID must match. The frame error control field is not
    checked; error detection and virtual channel handling are left to downstream consumers.
    """

    TM_HEADER_SIZE = 6
    TM_TRAILER_SIZE = 2
    # Leading header field: 2b version | 10b spacecraft ID | 3b virtual channel ID | 1b OCF flag
    SYNC_FIELD_SIZE = 2
    TM_VERSION = 0
    VERSION_SHIFT = 14
    SCID_SHIFT = 4
    SCID_MASK = 0x3FF

    FRAME_SIZE_CONSTANT = "ComCfg.TmFrameFixedSize"
    SCID_CONSTANT = "ComCfg.SpacecraftId"

    def __init__(self, frame_size=None, scid=None):
        """Resolve the frame size and spacecraft ID: CLI argument first, then the dictionary constant

        Args:
            frame_size: fixed TM frame size override, or None to read ComCfg.TmFrameFixedSize
            scid: spacecraft ID override, or None to read ComCfg.SpacecraftId (unchecked when absent too)
        """
        dict_frame_size = self.dictionary_constant(self.FRAME_SIZE_CONSTANT)
        dict_scid = self.dictionary_constant(self.SCID_CONSTANT)
        if frame_size is not None and dict_frame_size is not None and frame_size != dict_frame_size:
            print(
                f"[WARNING] TM frame size value specified through CLI argument does not match value"
                f" loaded from the dictionary. CLI={frame_size}, Dictionary={dict_frame_size}",
                file=sys.stderr,
            )
        if scid is not None and dict_scid is not None and scid != dict_scid:
            print(
                f"[WARNING] SCID value specified through CLI argument does not match value"
                f" loaded from the dictionary. CLI={scid}, Dictionary={dict_scid}",
                file=sys.stderr,
            )
        self.frame_size = frame_size if frame_size is not None else dict_frame_size
        if self.frame_size is None:
            raise ValueError(
                f"TM frame size unknown: dictionary constant {self.FRAME_SIZE_CONSTANT} not loaded"
                " and no --frame-size supplied"
            )
        self.scid = scid if scid is not None else dict_scid

    @staticmethod
    def dictionary_constant(name):
        """Read an integer constant from the loaded dictionary, or None when it is not present"""
        try:
            return ConfigManager().get_constant(name)
        except ConfigBadTypeException:
            return None

    def frame(self, data):
        """Uplink pass-through: return the data unchanged"""
        return data

    def is_frame_start(self, data):
        """Check whether the bytes at the start of data form a plausible TM primary header"""
        sync_field = struct.unpack_from(">H", data)[0]
        if (sync_field >> self.VERSION_SHIFT) != self.TM_VERSION:
            return False
        return self.scid is None or ((sync_field >> self.SCID_SHIFT) & self.SCID_MASK) == self.scid

    def deframe(self, data, no_copy=False):
        """Return the first whole TM frame in data, intact

        Bytes preceding a plausible header are discarded one at a time. Once a header is found,
        bytes are retained as leftover until a full frame_size bytes are available.
        """
        discarded = bytearray()
        if not no_copy:
            data = copy.copy(data)
        data = memoryview(data)
        while len(data) >= self.SYNC_FIELD_SIZE:
            if not self.is_frame_start(data):
                discarded += data[:1]
                data = data[1:]
                continue
            if len(data) < self.frame_size:
                break
            frame = bytes(data[: self.frame_size])
            return frame, bytes(data[self.frame_size :]), bytes(discarded)
        return None, bytes(data), bytes(discarded)

    @classmethod
    def get_arguments(cls):
        """Arguments to request from the CLI"""
        return {
            ("--frame-size",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Fixed Size of TM Frames (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
            ("--scid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Spacecraft ID (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
        }

    @classmethod
    def check_arguments(cls, frame_size, scid):
        """Check arguments from the CLI, raising TypeError on invalid values"""
        minimum = cls.TM_HEADER_SIZE + cls.TM_TRAILER_SIZE
        if frame_size is not None and frame_size <= minimum:
            raise TypeError(f"TM Fixed Frame size {frame_size} must exceed header and trailer size {minimum}")
        if scid is not None:
            if scid < 0:
                raise TypeError(f"Spacecraft ID {scid} is negative")
            if scid > cls.SCID_MASK:
                raise TypeError(f"Spacecraft ID {scid} is larger than {cls.SCID_MASK}")

    @classmethod
    def get_name(cls):
        """Name of this implementation provided to CLI"""
        return "tm-frame-aggregator"

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """Register the tm-frame-aggregator framing plugin"""
        return cls
