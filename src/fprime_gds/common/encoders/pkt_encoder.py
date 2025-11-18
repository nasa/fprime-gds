"""
@brief Encoder for Packet data

This encoder takes in PktData objects, serializes them, and sends the results
to all registered senders.

Serialized Packet format:
    +--------------------------------+          -
    | Header = "A5A5 "               |          |
    | (5 byte string)                |          |
    +--------------------------------+      Added by
    | Destination = "GUI " or "FSW " |       Sender
    | (4 byte string)                |          |
    +--------------------------------+          -
    | Length of descriptor, ID,      |
    | and channel data               |
    | (variable bytes, check config) |
    +--------------------------------+
    | Descriptor type = 4            |
    | (4 bytes)                      |
    +--------------------------------+
    | ID                             |
    | (2 bytes)                      |
    +--------------------------------+
    | Channel 1 value                |
    +--------------------------------+
    | Channel 2 value                |
    +--------------------------------+
    | ...                            |
    +--------------------------------+
    | Channel n value                |
    +--------------------------------+

@date Created August 9, 2018
@author R. Joseph Paetz

@bug No known bugs
"""

from fprime_gds.common.data_types.pkt_data import PktData
from fprime_gds.common.utils.config_manager import ConfigManager


from .encoder import Encoder


class PktEncoder(Encoder):
    """Encoder class for packet data"""

    def __init__(self):
        """
        Constructor

        Returns:
            An initialized PktEncoder object
        """
        super().__init__()

        self.len_obj = ConfigManager().get_config("msg_len")()
        self.id_obj = ConfigManager().get_type("FwTlmPacketizeIdType")()

    def encode_api(self, data):
        """
        Encodes the given PktData object as binary data and returns the result.

        Args:
            data (PktData obj): object to encode

        Returns:
            Encoded version of the data argument as binary data
        """
        assert isinstance(data, PktData), "Encoder handling incorrect type"
        pkt_temp = data.get_template()

        desc_bin = (
            ConfigManager()
            .get_type("ComCfg.Apid")("FW_PACKET_PACKETIZED_TLM")
            .serialize()
        )

        self.id_obj.val = pkt_temp.get_id()
        id_bin = self.id_obj.serialize()

        time_bin = data.get_time().serialize()

        ch_bin = b""
        for ch in data.get_chs():
            ch_bin += ch.get_val_obj().serialize()

        len_val = len(desc_bin) + len(id_bin) + len(time_bin) + len(ch_bin)
        self.len_obj.val = len_val
        len_bin = self.len_obj.serialize()

        binary_data = len_bin + desc_bin + id_bin + time_bin + ch_bin

        return binary_data
