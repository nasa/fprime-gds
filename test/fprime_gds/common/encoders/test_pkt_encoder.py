"""
Tests the packet encoder

Created on Jul 10, 2020
@author: Joseph Paetz, hpaulson
"""

from fprime_gds.common.models.serialize.numerical_types import U8Type, U16Type, U32Type
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.pkt_data import PktData
from fprime_gds.common.encoders.pkt_encoder import PktEncoder
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.pkt_template import PktTemplate
from fprime_gds.common.utils.config_manager import ConfigManager


def test_pkt_encoder():
    """
    Tests the encoding of the packet encoder
    """
    ch_temp_1 = ChTemplate(101, "test_ch", "test_comp", U32Type)
    ch_temp_2 = ChTemplate(102, "test_ch2", "test_comp2", U8Type)
    ch_temp_3 = ChTemplate(103, "test_ch3", "test_comp3", U16Type)

    pkt_temp = PktTemplate(64, "test_pkt", [ch_temp_1, ch_temp_2, ch_temp_3])

    time_obj = TimeType(TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758629, 123456)

    ch_obj_1 = ChData(U32Type(1356), time_obj, ch_temp_1)
    ch_obj_2 = ChData(U8Type(143), time_obj, ch_temp_2)
    ch_obj_3 = ChData(U16Type(1509), time_obj, ch_temp_3)

    pkt_obj = PktData([ch_obj_1, ch_obj_2, ch_obj_3], time_obj, pkt_temp)

    desc_bin = b"\x00\x04"  # U16 ComCfg.Apid for FW_PACKET_PACKETIZED_TLM
    id_bin = b"\x00\x40"
    time_bin = b"\x00\x02\x00\x5b\x6b\x4c\xa5\x00\x01\xe2\x40"
    ch_bin = b"\x00\x00\x05\x4c\x8f\x05\xe5"
    u32_len_bin = b"\x00\x00\x00\x16"  # 22 bytes (2+2+11+7)
    u16_len_bin = b"\x00\x16"  # 22 bytes

    u32_expected = u32_len_bin + desc_bin + id_bin + time_bin + ch_bin
    u16_expected = u16_len_bin + desc_bin + id_bin + time_bin + ch_bin

    #### Use msg_len U32Type ####
    ConfigManager().set_config("msg_len", U32Type)
    enc = PktEncoder()
    u32_output = enc.encode_api(pkt_obj)
    assert (
        u32_output == u32_expected
    ), f"FAIL: expected regular output to be {list(u32_expected)}, but found {list(u32_output)}"

    #### Use msg_len U16Type ####
    ConfigManager().set_config("msg_len", U16Type)
    enc_u16 = PktEncoder()
    u16_output = enc_u16.encode_api(pkt_obj)
    assert (
        u16_output == u16_expected
    ), f"FAIL: expected configured output to be {list(u16_expected)}, but found {list(u16_output)}"

    ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests
