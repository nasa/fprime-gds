"""F Prime Framer/Deframer Implementation of the CCSDS Attached Sync Marker (ASM)

The Attached Sync Marker is defined by CCSDS 131.0-B-5 (TM Synchronization and
Channel Coding) Section 9. On downlink, the spacecraft delimits each transfer
frame by prepending an ASM, producing a Sync-Marked Transfer Frame (SMTF). This
module locates the ASM in the downlink byte stream to acquire frame
synchronization, and strips it before handing the frame to the next deframer.

Uplink (TC) frames do not carry an ASM (uplink synchronization uses the CLTU
start sequence, CCSDS 231.0-B), so framing is an identity operation.
"""

import copy
import sys

from fprime_gds.common.utils.config_manager import ConfigBadTypeException, ConfigManager
from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.plugin.definitions import gds_plugin


@gds_plugin(FramerDeframer)
class AsmFramerDeframer(FramerDeframer):
    """CCSDS Attached Sync Marker synchronization layer (downlink deframing only)

    Deframing scans for the configured ASM pattern and emits the fixed-size
    transfer frame that follows it. Framing is pass-through since TC uplink
    carries no ASM.
    """

    # Default ASM for uncoded, convolutional, Reed-Solomon, concatenated,
    # rate-7/8 Transfer-Frame LDPC, and SMTF-stream LDPC coded data
    # (CCSDS 131.0-B-5 Section 9.3.1)
    DEFAULT_ASM = "1ACFFC1D"

    # For backwards compatibility if not found in dictionary (loaded by ConfigManager)
    FALLBACK_FRAME_SIZE = 1024

    def __init__(self, asm=None, frame_size=None):
        """Initialize with the given ASM hex string and transfer frame size.

        If frame_size is None it is pulled from the dictionary constant
        ComCfg.TmFrameFixedSize when available, or falls back to 1024.
        """
        self.asm = bytes.fromhex(asm if asm is not None else self.DEFAULT_ASM)
        dict_frame_size = None
        try:
            dict_frame_size = ConfigManager().get_constant("ComCfg.TmFrameFixedSize")
        except ConfigBadTypeException:
            pass  # Config value not found, move on
        if frame_size is not None and dict_frame_size is not None and frame_size != dict_frame_size:
            print(
                f"[WARNING] TM frame size value specified through CLI argument does not match value"
                f" loaded from the dictionary. CLI={frame_size}, Dictionary={dict_frame_size}",
                file=sys.stderr,
            )
        self.frame_size = frame_size or dict_frame_size or self.FALLBACK_FRAME_SIZE

    def frame(self, data):
        """Pass-through: TC uplink does not carry an ASM"""
        return data

    def deframe(self, data, no_copy=False):
        """Synchronize on the ASM and emit the transfer frame that follows it

        Bytes preceding the ASM are discarded. Once an ASM is found, the frame
        is only emitted when frame_size bytes are available after the marker;
        otherwise the (partial) data is left as remaining for the next pass.
        """
        discarded = b""
        if not no_copy:
            data = copy.copy(data)
        while True:
            index = data.find(self.asm)
            if index < 0:
                # No full ASM found: retain the longest data suffix that is a
                # prefix of the ASM, in case a marker straddles the read
                # boundary; discard the rest
                keep_from = len(data)
                for prefix_length in range(min(len(self.asm) - 1, len(data)), 0, -1):
                    if data[len(data) - prefix_length:] == self.asm[:prefix_length]:
                        keep_from = len(data) - prefix_length
                        break
                discarded += data[:keep_from]
                return None, data[keep_from:], discarded
            # Discard any bytes that precede the ASM
            discarded += data[:index]
            data = data[index:]
            start = len(self.asm)
            end = start + self.frame_size
            if len(data) < end:
                # Full frame not yet available: wait for more data
                return None, data, discarded
            return data[start:end], data[end:], discarded

    @classmethod
    def get_name(cls):
        """Name of this implementation provided to CLI"""
        return "ccsds-asm"

    @classmethod
    def get_arguments(cls):
        """Arguments to request from the CLI"""
        return {
            ("--asm",): {
                "type": str,
                "help": f"Attached Sync Marker pattern as a hex string [default: {cls.DEFAULT_ASM}]",
                "default": cls.DEFAULT_ASM,
                "required": False,
            },
            ("--frame-size",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Fixed Size of TM Frames (if specified, overrides dictionary ComCfg value)",
                "required": False,
            },
        }

    @classmethod
    def check_arguments(cls, asm, frame_size):
        """Check arguments from the CLI"""
        if asm is not None:
            try:
                pattern = bytes.fromhex(asm)
            except ValueError:
                raise TypeError(f"ASM '{asm}' is not a valid hex string")
            if len(pattern) < 1 or len(pattern) > 16:
                raise TypeError(f"ASM must be between 1 and 16 bytes, got {len(pattern)}")
        if frame_size is not None and frame_size <= 0:
            raise TypeError(f"Frame size {frame_size} is not positive")
