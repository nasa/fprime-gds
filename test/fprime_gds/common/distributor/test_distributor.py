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
