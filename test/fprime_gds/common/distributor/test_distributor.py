"""
Tests the distributor

Created on Jul 10, 2020
@author: Josef Biberstein, Joseph Paetz, hpaulson
"""


from fprime_gds.common.distributor.distributor import Distributor
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.models.serialize.numerical_types import U16Type, U32Type

def test_distributor():
    """
    Tests the raw messages and leftover data for the distributor
    """
    ConfigManager().set_config("msg_len", U16Type)
    ConfigManager().set_type("FwPacketDescriptorType", U32Type)

    dist = Distributor()

    header_1 = b"\x00\x0E\x00\x00\x00\x04"
    length_1 = 14
    desc_1 = 4
    data_1 = b"\x61\x62\x63\x64\x65\x66\x67\x68\x69\x6A"

    header_2 = b"\x00\x0A\x00\x00\x00\x01"
    length_2 = 10
    desc_2 = 1
    data_2 = b"\x41\x42\x43\x44\x45\x46"

    leftover_data = b"\x00\x0F\x00\x00\x00\x02\xFF"

    data = header_1 + data_1 + header_2 + data_2 + leftover_data

    (test_leftover, raw_msgs) = dist.parse_into_raw_msgs_api(bytearray(data))

    assert (
        test_leftover == leftover_data
    ), f"expected leftover data to be {list(leftover_data)}, but found {list(test_leftover)}"
    assert raw_msgs[0] == (
        header_1 + data_1
    ), f"expected first raw_msg to be {list(header_1 + data_1)}, but found {list(raw_msgs[0])}"
    assert raw_msgs[1] == (
        header_2 + data_2
    ), f"expected second raw_msg to be {list(header_2 + data_2)}, but found {list(raw_msgs[1])}"

    (test_len_1, test_desc_1, test_msg_1) = dist.parse_raw_msg_api(raw_msgs[0])
    (test_len_2, test_desc_2, test_msg_2) = dist.parse_raw_msg_api(raw_msgs[1])

    assert test_len_1 == length_1, f"expected 1st length to be {length_1} but found {test_len_1}"
    assert test_len_2 == length_2, f"expected 2nd length to be {length_2} but found {test_len_2}"
    assert test_desc_1 == desc_1, f"expected 1st desc to be {desc_1} but found {test_desc_1}"
    assert test_desc_2 == desc_2, f"expected 2nd desc to be {desc_2} but found {test_desc_2}"
    assert (test_msg_1 == data_1), f"expected 1st msg to be {list(data_1)} but found {list(test_msg_1)}"
    assert (test_msg_2 == data_2), f"expected 2nd msg to be {list(data_2)} but found {list(test_msg_2)}"

    ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests


class RecordingDecoder:
    """Decoder stub recording the messages it receives"""

    def __init__(self):
        self.received = []

    def data_callback(self, data):
        self.received.append(bytes(data))


def test_distributor_skips_malformed_messages():
    """
    Tests that malformed messages (unknown descriptor, truncated descriptor) and messages with no
    registered decoder are skipped without raising, and that subsequent valid messages in the same
    batch are still delivered
    """
    ConfigManager().set_config("msg_len", U16Type)
    ConfigManager().set_type("FwPacketDescriptorType", U32Type)
    try:
        dist = Distributor()
        decoder = RecordingDecoder()
        dist.register("FW_PACKET_TELEM", decoder)

        unknown_desc = b"\x00\x06\x00\x01\x00\x00\xAA\xBB"  # descriptor 65536 is not a valid ComCfg.Apid
        truncated_desc = b"\x00\x02\x00\x01"  # too short to hold a U32 descriptor
        no_decoder = b"\x00\x06\x00\x00\x00\x02\xEE\xFF"  # FW_PACKET_LOG, no decoder registered
        valid_telem = b"\x00\x06\x00\x00\x00\x01\xCC\xDD"  # FW_PACKET_TELEM

        dist.on_recv(unknown_desc + truncated_desc + no_decoder + valid_telem)

        assert decoder.received == [b"\xCC\xDD"]
    finally:
        ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests
