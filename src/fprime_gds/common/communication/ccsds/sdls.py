"""F Prime Framer/Deframer Implementation of a cleartext CCSDS SDLS layer

The SDLS (Space Data Link Security) cleartext layer processes SDLS frames between the
TM/TC transfer frame layer and the Space Packet layer. An SDLS frame consists of a
16-bit security association index followed by the (cleartext) payload. This
implementation performs no encryption nor decryption: framing prepends the security
association index and deframing strips it, passing the cleartext payload through.
"""

import copy
import struct

from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.plugin.definitions import gds_plugin


@gds_plugin(FramerDeframer)
class SdlsCleartextFramerDeframer(FramerDeframer):
    """Concrete implementation of FramerDeframer supporting a cleartext SDLS layer

    This implementation is registered as a "framing" plugin. It passes cleartext data
    through: framing prepends the 16-bit security association index and deframing
    strips it.
    """

    SECURITY_ASSOCIATION_INDEX_SIZE = 2

    def __init__(self, sa_index):
        """Initialize with the given security association index"""
        self.sa_index = sa_index

    def frame(self, data):
        """Frame the supplied data by prepending the security association index"""
        return struct.pack(">H", self.sa_index) + data

    def deframe(self, data, no_copy=False):
        """Deframe the supplied data by stripping the security association index"""
        discarded = b""
        if data is None:
            return None, None, discarded
        if not no_copy:
            data = copy.copy(data)
        # Not enough data for the security association index
        if len(data) < self.SECURITY_ASSOCIATION_INDEX_SIZE:
            return None, data, discarded
        # Strip the security association index and pass the cleartext payload through
        return bytes(data[self.SECURITY_ASSOCIATION_INDEX_SIZE :]), b"", discarded

    @classmethod
    def get_arguments(cls):
        """Arguments to request from the CLI"""
        return {
            ("--sa-index",): {
                "type": lambda input_arg: int(input_arg, 0),
                "help": "Security association index prepended to uplinked SDLS frames",
                "default": 0,
                "required": False,
            },
        }

    @classmethod
    def check_arguments(cls, sa_index):
        """Check arguments from the CLI

        Confirms that the input arguments are valid for this framer/deframer.

        Args:
            sa_index: security association index
        """
        if sa_index is None:
            raise TypeError("Security association index not specified")
        if sa_index < 0:
            raise TypeError(f"Security association index {sa_index} is negative")
        if sa_index > 0xFFFF:
            raise TypeError(
                f"Security association index {sa_index} is larger than {0xFFFF}"
            )

    @classmethod
    def get_name(cls):
        """Name of this implementation provided to CLI"""
        return "raw-sdls-cleartext"
