"""F Prime Framer/Deframer aggregating a byte stream into whole CCSDS TM transfer frames

Stream-oriented links (TCP, UART) deliver bytes in arbitrary chunks. This deframer
re-establishes the fixed-size TM transfer frame boundaries and hands each frame on intact
(header, data field, and trailer) for downstream consumers that decode TM frames themselves.
Uplink data is passed through unchanged.

Select with ``--framing-selection tm-frame-aggregator``. Frame size and spacecraft ID come from
the dictionary constants ``ComCfg.TmFrameFixedSize`` / ``ComCfg.SpacecraftId`` unless overridden
with ``--frame-size`` / ``--scid``; a frame size available from neither source is a fatal error.
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
    FRAME_ID_FIELD_FORMAT = ">H"
    FRAME_ID_FIELD_SIZE = struct.calcsize(FRAME_ID_FIELD_FORMAT)
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
        self.frame_size = self.resolve_constant(frame_size, self.FRAME_SIZE_CONSTANT, "TM frame size")
        if self.frame_size is None:
            raise ValueError(
                f"TM frame size unknown: dictionary constant {self.FRAME_SIZE_CONSTANT} not loaded"
                " and no --frame-size supplied"
            )
        self.scid = self.resolve_constant(scid, self.SCID_CONSTANT, "SCID")
        if self.scid is None:
            print(
                f"[WARNING] Spacecraft ID unknown ({self.SCID_CONSTANT} not loaded, no --scid):"
                " TM frame synchronization uses the version bits only",
                file=sys.stderr,
            )
        self.check_arguments(self.frame_size, self.scid)

    @staticmethod
    def dictionary_constant(name):
        """Read an integer constant from the loaded dictionary, or None when it is not present"""
        try:
            return ConfigManager().get_constant(name)
        except ConfigBadTypeException:
            return None

    @classmethod
    def resolve_constant(cls, cli_value, constant_name, label):
        """Return the CLI value when given, else the dictionary constant (None if absent); warn on mismatch"""
        dict_value = cls.dictionary_constant(constant_name)
        if cli_value is not None and dict_value is not None and cli_value != dict_value:
            print(
                f"[WARNING] {label} value specified through CLI argument does not match value"
                f" loaded from the dictionary. CLI={cli_value}, Dictionary={dict_value}",
                file=sys.stderr,
            )
        return cli_value if cli_value is not None else dict_value

    def frame(self, data):
        """Uplink pass-through: return the data unchanged"""
        return data

    def is_frame_start(self, data):
        """Check whether the bytes at the start of data form a plausible TM primary header"""
        frame_id = struct.unpack_from(self.FRAME_ID_FIELD_FORMAT, data)[0]
        if (frame_id >> self.VERSION_SHIFT) != self.TM_VERSION:
            return False
        return self.scid is None or ((frame_id >> self.SCID_SHIFT) & self.SCID_MASK) == self.scid

    def deframe(self, data, no_copy=False):
        """Return the first whole TM frame in data, intact

        Bytes preceding a plausible header are discarded one at a time. Once a header is found,
        bytes are retained as leftover until a full frame_size bytes are available.
        """
        discarded = bytearray()
        if not no_copy:
            data = copy.copy(data)
        data = memoryview(data)
        while len(data) >= self.FRAME_ID_FIELD_SIZE:
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
                "help": "Fixed Size of TM Frames, shared with raw-space-data-link"
                " (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
            ("--scid",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Spacecraft ID, shared with raw-space-data-link"
                " (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
        }

    @classmethod
    def check_arguments(cls, frame_size, scid):
        """Check CLI or dictionary-resolved values, raising TypeError on invalid ones"""
        if frame_size is None and cls.dictionary_constant(cls.FRAME_SIZE_CONSTANT) is None:
            raise TypeError(
                f"TM frame size unknown: dictionary constant {cls.FRAME_SIZE_CONSTANT} not loaded"
                " and no --frame-size supplied"
            )
        overhead = cls.TM_HEADER_SIZE + cls.TM_TRAILER_SIZE
        if frame_size is not None and frame_size <= overhead:
            raise TypeError(f"TM Fixed Frame size {frame_size} must exceed header and trailer size {overhead}")
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
